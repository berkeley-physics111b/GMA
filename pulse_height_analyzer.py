import time
import datetime
import csv
import threading
import queue
import numpy as np
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# ---------------------------------------------------------------------------
# Hardware driver
# ---------------------------------------------------------------------------
from waveforms_ads import WaveFormsADS, DWFError, DwfTriggerSlopeRise, DwfTriggerSlopeFall


# ---------------------------------------------------------------------------
# Palette / style constants
# ---------------------------------------------------------------------------
BG        = "#1e1e2e"
FG        = "#cdd6f4"
ACCENT    = "#89b4fa"
PANEL     = "#313244"
ENTRY_BG  = "#45475a"
BUTTON_BG = "#585b70"
GREEN     = "#a6e3a1"
RED       = "#f38ba8"
YELLOW    = "#f9e2af"
PURPLE    = "#cba6f7"
MONO      = ("Courier", 10)
SANS      = ("Helvetica", 10)
SANS_B    = ("Helvetica", 10, "bold")
SANS_LG   = ("Helvetica", 12, "bold")
PADX = 8
PADY = 4

MPL_STYLE = {
    "figure.facecolor":  BG,
    "axes.facecolor":    PANEL,
    "axes.edgecolor":    FG,
    "axes.labelcolor":   FG,
    "xtick.color":       FG,
    "ytick.color":       FG,
    "text.color":        FG,
    "grid.color":        "#585b70",
    "grid.alpha":        0.4,
    "lines.color":       ACCENT,
}
for k, v in MPL_STYLE.items():
    plt.rcParams[k] = v


# ---------------------------------------------------------------------------
# Tiny helpers
# ---------------------------------------------------------------------------

def _lf(parent, text, col=0, row=0, sticky="e", colspan=1, **kw):
    lbl = tk.Label(parent, text=text, bg=PANEL, fg=FG, font=SANS, **kw)
    lbl.grid(column=col, row=row, sticky=sticky, padx=PADX, pady=PADY,
             columnspan=colspan)
    return lbl


def _ef(parent, textvariable, col=1, row=0, width=10, colspan=1):
    e = tk.Entry(parent, textvariable=textvariable, width=width,
                 bg=ENTRY_BG, fg=FG, insertbackground=FG,
                 relief="flat", font=MONO)
    e.grid(column=col, row=row, sticky="ew", padx=PADX, pady=PADY,
           columnspan=colspan)
    return e


def _btn(parent, text, cmd, col=0, row=0, fg=FG, bg=BUTTON_BG,
         colspan=1, **kw):
    b = tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg,
                  activebackground=ACCENT, activeforeground=BG,
                  relief="flat", font=SANS_B, padx=6, pady=3, **kw)
    b.grid(column=col, row=row, padx=PADX, pady=PADY, sticky="ew",
           columnspan=colspan)
    return b


def _section(parent, title, row=0, colspan=10):
    lbl = tk.Label(parent, text=f"  {title}  ", bg=ACCENT, fg=BG, font=SANS_B)
    lbl.grid(column=0, row=row, columnspan=colspan, sticky="ew",
             padx=PADX, pady=(10, 2))
    return lbl


# ---------------------------------------------------------------------------
# Scrollable frame
# ---------------------------------------------------------------------------

class ScrollableFrame(tk.Frame):
    def __init__(self, parent, bg=BG, width=310, **kw):
        super().__init__(parent, bg=bg, **kw)
        self._canvas = tk.Canvas(self, bg=bg, highlightthickness=0, width=width)
        sb = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self.inner = tk.Frame(self._canvas, bg=bg)
        self._win = self._canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self._canvas.configure(yscrollcommand=sb.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.inner.bind("<Configure>", lambda _e: self._canvas.configure(
            scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", lambda e: self._canvas.itemconfig(
            self._win, width=e.width))
        self._canvas.bind("<Enter>",  lambda _e: self._canvas.bind_all(
            "<MouseWheel>", self._scroll))
        self._canvas.bind("<Leave>",  lambda _e: self._canvas.unbind_all(
            "<MouseWheel>"))

    def _scroll(self, event):
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


# ---------------------------------------------------------------------------
# Shared scope-settings panel
# ---------------------------------------------------------------------------

class ScopeSettingsPanel(tk.LabelFrame):
    """Reusable panel for ADS acquisition parameters."""

    def __init__(self, parent, **kw):
        super().__init__(parent, text="Scope / Trigger Settings",
                         bg=PANEL, fg=ACCENT, font=SANS_B, **kw)
        self._build()

    def _build(self):
        self.channel      = tk.IntVar(value=0)
        self.trig_level   = tk.DoubleVar(value=0.15)
        self.edge         = tk.StringVar(value="Rise")
        self.sample_freq  = tk.DoubleVar(value=1e8)
        self.y_range      = tk.DoubleVar(value=1.0)
        self.y_offset     = tk.DoubleVar(value=0.0)
        self.time_base_us = tk.DoubleVar(value=10.0)
        self.probe_invert = tk.BooleanVar(value=False)

        rows = [
            ("Channel (0-based):",   self.channel,      5),
            ("Trigger Level (V):",   self.trig_level,   8),
            ("Sample Freq (Hz):",    self.sample_freq,  12),
            ("Y Range (V p-p):",     self.y_range,      8),
            ("Vertical Offset (V):", self.y_offset,     8),
            ("Time Base (μs):",      self.time_base_us, 8),
        ]
        for r, (label, var, width) in enumerate(rows):
            _lf(self, label, col=0, row=r)
            _ef(self, var, col=1, row=r, width=width)

        r = len(rows)
        _lf(self, "Edge:", col=0, row=r)
        om = ttk.OptionMenu(self, self.edge, "Rise", "Rise", "Fall")
        om.grid(column=1, row=r, sticky="ew", padx=PADX, pady=PADY)

        r += 1
        tk.Checkbutton(self, text="Invert Probe", variable=self.probe_invert,
                       bg=PANEL, fg=FG, selectcolor=ENTRY_BG,
                       activebackground=PANEL, font=SANS).grid(
            column=0, row=r, columnspan=2, sticky="w", padx=PADX, pady=PADY)

    def get_params(self):
        fs   = float(self.sample_freq.get())
        tb   = float(self.time_base_us.get()) / 1e6
        buf  = max(64, int(fs * tb))
        slope = DwfTriggerSlopeRise if self.edge.get() == "Rise" else DwfTriggerSlopeFall
        return dict(
            channel=int(self.channel.get()),
            trigger_level=float(self.trig_level.get()),
            slope=slope,
            sample_rate=fs,
            y_range=float(self.y_range.get()),
            y_offset=float(self.y_offset.get()),
            time_base_us=float(self.time_base_us.get()),
            buffer_size=buf,
            invert=self.probe_invert.get(),
        )


# ---------------------------------------------------------------------------
# Acquisition worker (runs in a background thread)
# ---------------------------------------------------------------------------

class AcqWorker:
    """
    Background thread that calls analog_in_capture in a loop and posts
    results to a queue.  Stopped gracefully via stop().
    """

    def __init__(self, ads: WaveFormsADS, params: dict,
                 result_q: queue.Queue):
        self._ads    = ads
        self._params = params
        self._q      = result_q
        self._stop   = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        p = self._params
        ch    = p["channel"]
        fs    = p["sample_rate"]
        buf   = p["buffer_size"]
        trig  = p["trigger_level"]
        slope = p["slope"]
        invert = p["invert"]

        # Range / offset are set once (ADS methods called directly)
        try:
            self._ads.analog_in_set_range(ch, p["y_range"])
            self._ads.analog_in_set_offset(ch, p["y_offset"])
        except Exception:
            pass

        while not self._stop.is_set():
            try:
                data = self._ads.analog_in_capture(
                    channel=ch,
                    sample_rate_hz=fs,
                    buffer_size=buf,
                    trigger_level_v=trig,
                    trigger_condition=slope,
                    auto_timeout_s=0.5,
                    timeout_s=3.0,
                )
                if invert:
                    data = -data
                self._q.put(data)
            except TimeoutError:
                # No trigger – just retry
                pass
            except Exception as exc:
                self._q.put(exc)
                break


# ---------------------------------------------------------------------------
# ─── TAB 1 : Scope View ────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class ScopeTab(tk.Frame):
    MAX_TRACES = 5   # number of recent pulses to overlay

    def __init__(self, parent, status_var: tk.StringVar, **kw):
        super().__init__(parent, bg=BG, **kw)
        self._status = status_var
        self._worker: AcqWorker | None = None
        self._ads:    WaveFormsADS | None = None
        self._q:      queue.Queue = queue.Queue(maxsize=20)
        self._traces: list = []
        self._running = False
        self._build()

    # ── Layout ─────────────────────────────────────────────────────────────

    def _build(self):
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        # ── Left panel (settings) ──
        left_scroll = ScrollableFrame(self, bg=BG, width=310)
        left_scroll.grid(row=0, column=0, sticky="ns", padx=(4, 0), pady=4)
        left = left_scroll.inner

        self.scope_settings = ScopeSettingsPanel(left)
        self.scope_settings.pack(fill="x", padx=4, pady=4)

        ctrl = tk.Frame(left, bg=BG)
        ctrl.pack(fill="x", padx=4, pady=4)
        ctrl.columnconfigure(0, weight=1)
        ctrl.columnconfigure(1, weight=1)

        self._start_btn = _btn(ctrl, "▶  Start", self._start,
                               col=0, row=0, fg=BG, bg=GREEN)
        self._stop_btn  = _btn(ctrl, "■  Stop",  self._stop,
                               col=1, row=0, fg=BG, bg=RED)
        self._stop_btn.configure(state="disabled")

        _btn(ctrl, "Clear Traces", self._clear_traces,
             col=0, row=1, colspan=2)

        # ── Right panel (plot) ──
        right = tk.Frame(self, bg=BG)
        right.grid(row=0, column=1, sticky="nsew", padx=4, pady=4)
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        self._fig, self._ax = plt.subplots(figsize=(8, 5))
        self._fig.patch.set_facecolor(BG)
        self._ax.set_facecolor(PANEL)
        self._ax.set_xlabel("Time (μs)", color=FG)
        self._ax.set_ylabel("Voltage (V)", color=FG)
        self._ax.set_title("Scope – Recent Pulses", color=ACCENT)
        self._ax.grid(True)

        self._canvas = FigureCanvasTkAgg(self._fig, master=right)
        self._canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        self._canvas.draw()

        # Colour cycle for traces
        self._colors = [ACCENT, GREEN, YELLOW, PURPLE, RED]

    # ── Control ────────────────────────────────────────────────────────────

    def _start(self):
        if self._running:
            return
        try:
            self._ads = WaveFormsADS()
        except Exception as exc:
            messagebox.showerror("Device Error", str(exc))
            return

        self._params = self.scope_settings.get_params()
        self._q      = queue.Queue(maxsize=20)
        self._worker = AcqWorker(self._ads, self._params, self._q)
        self._worker.start()
        self._running = True
        self._start_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")
        self._status.set("Scope running …")
        self._poll()

    def _stop(self):
        self._running = False
        if self._worker:
            self._worker.stop()
            self._worker = None
        if self._ads:
            try: self._ads.close()
            except Exception: pass
            self._ads = None
        self._start_btn.configure(state="normal")
        self._stop_btn.configure(state="disabled")
        self._status.set("Scope stopped.")

    def _clear_traces(self):
        self._traces.clear()
        self._redraw([])

    # ── Poll & draw ────────────────────────────────────────────────────────

    def _poll(self):
        if not self._running:
            return
        try:
            item = self._q.get_nowait()
            if isinstance(item, Exception):
                self._status.set(f"Error: {item}")
                self._stop()
                return
            self._add_trace(item)
        except queue.Empty:
            pass
        self.after(50, self._poll)

    def _add_trace(self, data: np.ndarray):
        p  = self._params
        fs = p["sample_rate"]
        t  = np.linspace(0, len(data) / fs * 1e6, len(data))   # μs
        self._traces.append((t, data))
        if len(self._traces) > self.MAX_TRACES:
            self._traces.pop(0)
        self._redraw(self._traces)
        n = len(self._traces)
        self._status.set(f"Scope: {n} trace{'s' if n != 1 else ''} shown")

    def _redraw(self, traces):
        self._ax.cla()
        self._ax.set_facecolor(PANEL)
        self._ax.set_xlabel("Time (μs)", color=FG)
        self._ax.set_ylabel("Voltage (V)", color=FG)
        self._ax.set_title("Scope – Recent Pulses", color=ACCENT)
        self._ax.grid(True)

        if traces:
            p = self._params
            for i, (t, d) in enumerate(traces):
                alpha = 0.4 + 0.6 * (i + 1) / len(traces)
                self._ax.plot(t, d, color=self._colors[i % len(self._colors)],
                              lw=1.2, alpha=alpha,
                              label=f"T-{len(traces)-i}")
            # Trigger line
            self._ax.axhline(p["trigger_level"], color=RED, lw=0.8,
                             linestyle="--", alpha=0.7, label="Trigger")
            self._ax.legend(loc="upper right", facecolor=PANEL,
                            labelcolor=FG, fontsize=8, framealpha=0.7)

        self._canvas.draw_idle()

    # ── Teardown ───────────────────────────────────────────────────────────

    def destroy(self):
        self._stop()
        super().destroy()


# ---------------------------------------------------------------------------
# ─── TAB 2 : Pulse-Height Histogram ───────────────────────────────────────
# ---------------------------------------------------------------------------

class HistogramTab(tk.Frame):

    def __init__(self, parent, status_var: tk.StringVar, **kw):
        super().__init__(parent, bg=BG, **kw)
        self._status  = status_var
        self._worker: AcqWorker | None = None
        self._ads:    WaveFormsADS | None = None
        self._q:      queue.Queue  = queue.Queue(maxsize=200)
        self._heights: list[float] = []
        self._last_waveform: np.ndarray | None = None
        self._running = False
        self._csv_file = None
        self._csv_writer = None
        self._pulse_redraw_pending = False
        self._build()

    # ── Layout ─────────────────────────────────────────────────────────────

    def _build(self):
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        # ── Left panel ──
        left_scroll = ScrollableFrame(self, bg=BG, width=310)
        left_scroll.grid(row=0, column=0, sticky="ns", padx=(4, 0), pady=4)
        left = left_scroll.inner

        # Scope settings
        self.scope_settings = ScopeSettingsPanel(left)
        self.scope_settings.pack(fill="x", padx=4, pady=4)

        # Histogram settings
        hist_frm = tk.LabelFrame(left, text="Histogram Settings",
                                 bg=PANEL, fg=ACCENT, font=SANS_B)
        hist_frm.pack(fill="x", padx=4, pady=4)
        hist_frm.columnconfigure(1, weight=1)

        self.n_bins   = tk.IntVar(value=100)
        self.v_min    = tk.DoubleVar(value=0.0)
        self.v_max    = tk.DoubleVar(value=1.0)

        for var in (self.n_bins, self.v_min, self.v_max):
            var.trace_add("write", lambda *_: self.after(0, self._redraw))

        _lf(hist_frm, "Bins:",      col=0, row=0); _ef(hist_frm, self.n_bins,  col=1, row=0, width=6)
        _lf(hist_frm, "V min:",     col=0, row=1); _ef(hist_frm, self.v_min,   col=1, row=1, width=8)
        _lf(hist_frm, "V max:",     col=0, row=2); _ef(hist_frm, self.v_max,   col=1, row=2, width=8)

        # File settings
        file_frm = tk.LabelFrame(left, text="Data File",
                                 bg=PANEL, fg=ACCENT, font=SANS_B)
        file_frm.pack(fill="x", padx=4, pady=4)
        file_frm.columnconfigure(1, weight=1)

        self.filename = tk.StringVar(value="")
        _lf(file_frm, "File:", col=0, row=0)
        fe = tk.Entry(file_frm, textvariable=self.filename, width=16,
                      bg=ENTRY_BG, fg=FG, insertbackground=FG,
                      relief="flat", font=MONO)
        fe.grid(column=1, row=0, sticky="ew", padx=PADX, pady=PADY)
        _btn(file_frm, "Browse / Save As…", self._browse_file, col=0, row=1, colspan=2)
        _btn(file_frm, "Import CSV…", self._import_csv, col=0, row=2, colspan=2)

        # Control buttons
        ctrl = tk.Frame(left, bg=BG)
        ctrl.pack(fill="x", padx=4, pady=4)
        ctrl.columnconfigure(0, weight=1)
        ctrl.columnconfigure(1, weight=1)

        self._start_btn = _btn(ctrl, "▶  Start", self._start,
                               col=0, row=0, fg=BG, bg=GREEN)
        self._stop_btn  = _btn(ctrl, "■  Stop",  self._stop,
                               col=1, row=0, fg=BG, bg=RED)
        self._stop_btn.configure(state="disabled")

        _btn(ctrl, "Clear Histogram", self._clear_hist,
             col=0, row=1, colspan=2)

        # Count label
        self._count_var = tk.StringVar(value="Events: 0")
        tk.Label(left, textvariable=self._count_var,
                 bg=BG, fg=YELLOW, font=SANS_B).pack(pady=4)

        # ── Right panel (two plots) ──
        right = tk.Frame(self, bg=BG)
        right.grid(row=0, column=1, sticky="nsew", padx=4, pady=4)
        right.rowconfigure(0, weight=3)
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        # Histogram figure
        self._fig, self._ax = plt.subplots(figsize=(8, 4))
        self._fig.patch.set_facecolor(BG)
        self._ax.set_facecolor(PANEL)
        self._ax.set_xlabel("Pulse Height (V)", color=FG)
        self._ax.set_ylabel("Counts", color=FG)
        self._ax.set_title("Pulse-Height Histogram", color=ACCENT)
        self._ax.grid(True)
        self._canvas = FigureCanvasTkAgg(self._fig, master=right)
        self._canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        self._canvas.draw()

        # Last-pulse waveform figure
        self._pfig, self._pax = plt.subplots(figsize=(8, 2))
        self._pfig.patch.set_facecolor(BG)
        self._pfig.subplots_adjust(left=0.08, right=0.97, top=0.82, bottom=0.22)
        self._pax.set_facecolor(PANEL)
        self._pax.set_xlabel("Time (μs)", color=FG)
        self._pax.set_ylabel("V", color=FG)
        self._pax.set_title("Most Recent Pulse", color=ACCENT)
        self._pax.grid(True)
        self._pcanvas = FigureCanvasTkAgg(self._pfig, master=right)
        self._pcanvas.get_tk_widget().grid(row=1, column=0, sticky="nsew")
        self._pcanvas.draw()

    # ── File browse ────────────────────────────────────────────────────────

    def _browse_file(self):
        path = filedialog.asksaveasfilename(
            title="Save pulse heights to CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if path:
            self.filename.set(path)

    def _import_csv(self):
        path = filedialog.askopenfilename(
            title="Import pulse-height CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            imported = []
            with open(path, newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                # Expect columns: timestamp, pulse_height_V — find height col by name or default to col 1
                ph_col = 1
                if header:
                    for i, h in enumerate(header):
                        if "height" in h.lower() or "pulse" in h.lower() or "voltage" in h.lower():
                            ph_col = i
                            break
                for row in reader:
                    if len(row) > ph_col:
                        try:
                            imported.append(float(row[ph_col]))
                        except ValueError:
                            pass
            if not imported:
                messagebox.showwarning("Import", "No numeric pulse-height values found in file.")
                return
            self._heights.extend(imported)
            n = len(self._heights)
            self._count_var.set(f"Events: {n}")
            self._status.set(
                f"Imported {len(imported)} events from {path.split('/')[-1]}  (total: {n})")
            self._redraw()
        except Exception as exc:
            messagebox.showerror("Import Error", str(exc))

    # ── Control ────────────────────────────────────────────────────────────

    def _start(self):
        if self._running:
            return
        try:
            self._ads = WaveFormsADS()
        except Exception as exc:
            messagebox.showerror("Device Error", str(exc))
            return

        # Open CSV if a path is given
        path = self.filename.get().strip()
        if path:
            try:
                self._csv_file   = open(path, "a", newline="")
                self._csv_writer = csv.writer(self._csv_file)
                # Write header only if the file is empty / new
                if self._csv_file.tell() == 0:
                    self._csv_writer.writerow(["timestamp", "pulse_height_V"])
            except Exception as exc:
                messagebox.showerror("File Error", str(exc))
                self._ads.close()
                self._ads = None
                return
        else:
            self._csv_file   = None
            self._csv_writer = None

        self._params = self.scope_settings.get_params()
        self._q      = queue.Queue(maxsize=200)
        self._worker = AcqWorker(self._ads, self._params, self._q)
        self._worker.start()
        self._running = True
        self._start_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")
        self._status.set("Histogram running …")
        self._poll()
        self._schedule_pulse_redraw()

    def _stop(self):
        self._running = False
        if self._worker:
            self._worker.stop()
            self._worker = None
        if self._ads:
            try: self._ads.close()
            except Exception: pass
            self._ads = None
        if self._csv_file:
            try: self._csv_file.close()
            except Exception: pass
            self._csv_file   = None
            self._csv_writer = None
        self._start_btn.configure(state="normal")
        self._stop_btn.configure(state="disabled")
        self._status.set(f"Histogram stopped. {len(self._heights)} events recorded.")

    def _clear_hist(self):
        self._heights.clear()
        self._count_var.set("Events: 0")
        self._redraw()

    # ── Poll & draw ────────────────────────────────────────────────────────

    def _poll(self):
        if not self._running:
            return
        updated = False
        while not self._q.empty():
            try:
                item = self._q.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, Exception):
                self._status.set(f"Error: {item}")
                self._stop()
                return
            # Find peak
            peak = float(np.max(np.abs(item)))
            self._heights.append(peak)
            self._last_waveform = item          # store for waveform viewer
            if self._csv_writer:
                ts = datetime.datetime.now().isoformat(timespec="milliseconds")
                self._csv_writer.writerow([ts, f"{peak:.6f}"])
                self._csv_file.flush()
            updated = True

        if updated:
            n = len(self._heights)
            self._count_var.set(f"Events: {n}")
            self._status.set(f"Histogram running … {n} events")
            self._redraw()

        self.after(80, self._poll)

    def _schedule_pulse_redraw(self):
        """Throttled waveform refresh — fires every 500 ms while running."""
        self._redraw_pulse()
        if self._running:
            self.after(500, self._schedule_pulse_redraw)

    def _redraw_pulse(self):
        self._pax.cla()
        self._pax.set_facecolor(PANEL)
        self._pax.set_xlabel("Time (μs)", color=FG)
        self._pax.set_ylabel("V", color=FG)
        self._pax.set_title("Most Recent Pulse", color=ACCENT)
        self._pax.grid(True)
        if self._last_waveform is not None and hasattr(self, "_params"):
            fs = self._params["sample_rate"]
            t  = np.linspace(0, len(self._last_waveform) / fs * 1e6,
                             len(self._last_waveform))
            self._pax.plot(t, self._last_waveform, color=GREEN, lw=1.2)
            self._pax.axhline(self._params["trigger_level"], color=RED,
                              lw=0.8, linestyle="--", alpha=0.7)
        self._pcanvas.draw_idle()

    def _redraw(self):
        self._ax.cla()
        self._ax.set_facecolor(PANEL)
        self._ax.set_xlabel("Pulse Height (V)", color=FG)
        self._ax.set_ylabel("Counts", color=FG)
        self._ax.set_title("Pulse-Height Histogram", color=ACCENT)
        self._ax.grid(True)

        if self._heights:
            try:
                bins  = max(2, int(self.n_bins.get()))
                vmin  = float(self.v_min.get())
                vmax  = float(self.v_max.get())
                if vmax <= vmin:
                    vmax = vmin + 1.0
                edges = np.linspace(vmin, vmax, bins + 1)
                counts, _ = np.histogram(self._heights, bins=edges)
                centers    = 0.5 * (edges[:-1] + edges[1:])
                width      = edges[1] - edges[0]
                self._ax.bar(centers, counts, width=width * 0.92,
                             color=ACCENT, edgecolor=PANEL, linewidth=0.4,
                             alpha=0.85)
            except (ValueError, tk.TclError):
                pass

        self._canvas.draw_idle()

    # ── Teardown ───────────────────────────────────────────────────────────

    def destroy(self):
        self._stop()
        super().destroy()


# ---------------------------------------------------------------------------
# ─── Main Application ──────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class PulseHeightAnalyzer(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("Pulse Height Analyzer")
        self.configure(bg=BG)
        self.minsize(1000, 600)
        self.geometry("1280x780")

        # ── ttk style overrides ──
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TNotebook",       background=BG,    borderwidth=0)
        style.configure("TNotebook.Tab",   background=PANEL, foreground=FG,
                        font=SANS_B, padding=[12, 6])
        style.map("TNotebook.Tab",
                  background=[("selected", ACCENT)],
                  foreground=[("selected", BG)])
        style.configure("TMenubutton",     background=ENTRY_BG, foreground=FG,
                        font=MONO, relief="flat")
        style.configure("TScrollbar",      background=PANEL, troughcolor=BG,
                        arrowcolor=FG)

        # ── Status bar ──
        self._status = tk.StringVar(value="Ready")
        status_bar = tk.Label(self, textvariable=self._status,
                              bg=BG, fg=YELLOW, font=MONO, anchor="w",
                              relief="flat")
        status_bar.pack(side="bottom", fill="x", padx=8, pady=2)

        # ── Notebook ──
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=4, pady=4)

        self._scope_tab = ScopeTab(nb, self._status)
        nb.add(self._scope_tab, text="  🔭  Scope View  ")

        self._hist_tab = HistogramTab(nb, self._status)
        nb.add(self._hist_tab, text="  📊  Pulse Height Histogram  ")

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        try:
            self._scope_tab._stop()
            self._hist_tab._stop()
        except Exception:
            pass
        self.destroy()


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = PulseHeightAnalyzer()
    app.mainloop()