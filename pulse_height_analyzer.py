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
    def __init__(self, parent, **kw):
        super().__init__(parent, text="Scope / Trigger Settings",
                         bg=PANEL, fg=ACCENT, font=SANS_B, **kw)
        self._build()

    def _build(self):
        self.channel      = tk.IntVar(value=0)
        self.trig_level   = tk.DoubleVar(value=0.15)
        self.edge         = tk.StringVar(value="Rise")
        self.sample_freq  = tk.DoubleVar(value=1e6)
        self.y_range      = tk.DoubleVar(value=2.5)
        self.y_offset     = tk.DoubleVar(value=0.0)
        self.time_base_us = tk.DoubleVar(value=5.0)
        self.probe_invert = tk.BooleanVar(value=False)

        rows = [
            ("Channel (0-based):",   self.channel,      5),
            ("Trigger Level (V):",   self.trig_level,   8),
            ("Sample Freq (Hz):",    self.sample_freq,  12),
            ("Y Range (V Pk to Pk):",self.y_range,      8),
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
# Shared signal processing settings panel
# ---------------------------------------------------------------------------

class SignalProcessingSettings(tk.LabelFrame):
    def __init__(self, parent, **kw):
        super().__init__(parent, text="Signal Processing Settings",
                         bg=PANEL, fg=ACCENT, font=SANS_B, **kw)
        self._build()

    def _build(self):
        self.apply_baseline = tk.BooleanVar(value=False)
        self.size = tk.DoubleVar(value=100)
        self.position = tk.DoubleVar(value=100)
        self.max_noise_percent = tk.DoubleVar(value=2)

        self.apply_slope_max = tk.BooleanVar(value=False)
        self.max_slope_percent = tk.DoubleVar(value=2)

        tk.Checkbutton(self, text="Apply baseline", variable=self.apply_baseline,
                       bg=PANEL, fg=FG, selectcolor=ENTRY_BG,
                       activebackground=PANEL, font=SANS).grid(
                       column=0, row=0, columnspan=2, sticky="w", padx=PADX, pady=PADY)

        rows = [
            ("Size (μs):",                   self.size,                8),
            ("Position (μs):",               self.position,            8),
            ("Max noise (%):",               self.max_noise_percent,   8),
        ]
        for r, (label, var, width) in enumerate(rows):
            _lf(self, label, col=0, row=r+1)
            _ef(self, var, col=1, row=r+1, width=width)

        r = len(rows) + 1
        tk.Checkbutton(self, text="Apply max slope", variable=self.apply_slope_max,
                       bg=PANEL, fg=FG, selectcolor=ENTRY_BG,
                       activebackground=PANEL, font=SANS).grid(
            column=0, row=r, columnspan=2, sticky="w", padx=PADX, pady=PADY)

        r += 1
        _lf(self, "Max slope (%):", col=0, row=r)
        _ef(self, self.max_slope_percent, col=1, row=r, width=8)

    def get_params(self):
        size = float(self.size.get()) / 1e6
        position = float(self.position.get()) / 1e6
        max_noise_percent = max(0, min(float(self.max_noise_percent.get()), 100))
        self.max_noise_percent.set(max_noise_percent)
        max_slope_percent = max(0, min(float(self.max_slope_percent.get()), 100))
        self.max_slope_percent.set(max_slope_percent)
        
        return dict(
            apply_baseline=self.apply_baseline.get(),
            size=size,
            position=position,
            max_noise_percent=max_noise_percent,
            apply_slope_max=self.apply_slope_max.get(),
            max_slope_percent=max_slope_percent
        )


# ---------------------------------------------------------------------------
# Ultra-low deadtime acquisition worker (Zero calculation overhead)
# ---------------------------------------------------------------------------

class AcqWorker:
    def __init__(self, ads: WaveFormsADS, params: dict, result_q: queue.Queue):
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
        attenuation = -1.0 if invert else 1.0

        try:
            self._ads.analog_in_set_range(ch, p["y_range"])
            self._ads.analog_in_set_offset(ch, p["y_offset"])
        except Exception:
            pass

        while not self._stop.is_set():
            try:
                trace = self._ads.analog_in_capture(
                    channel=ch,
                    sample_rate_hz=fs,
                    buffer_size=buf,
                    attenuation=attenuation,
                    trigger_level_v=trig,
                    trigger_condition=slope,
                    auto_timeout_s=0.0,
                    timeout_s=3.0,
                )
                self._q.put(trace)
            except TimeoutError:
                pass
            except Exception as exc:
                self._q.put(exc)
                break


# ---------------------------------------------------------------------------
# ─── TAB 1 : Scope View ────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class ScopeTab(tk.Frame):
    def __init__(self, parent, status_var: tk.StringVar, **kw):
        super().__init__(parent, bg=BG, **kw)
        self._status = status_var
        self._worker: AcqWorker | None = None
        self._ads:    WaveFormsADS | None = None
        self._q:      queue.Queue = queue.Queue(maxsize=100)
        self._traces: list = []
        self._running = False
        self._time_indices = None
        
        # Diagnostics
        self._start_time = 0.0
        self._total_events = 0
        self._last_drawn_events = 0
        self._last_metrics_time = 0.0
        
        self._build()

    def _build(self):
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        left_scroll = ScrollableFrame(self, bg=BG, width=310)
        left_scroll.grid(row=0, column=0, sticky="ns", padx=(4, 0), pady=4)
        left = left_scroll.inner

        self.scope_settings = ScopeSettingsPanel(left)
        self.scope_settings.pack(fill="x", padx=4, pady=4)

        self.signal_processing_settings = SignalProcessingSettings(left)
        self.signal_processing_settings.pack(fill="x", padx=4, pady=4)

        trace_frm = tk.LabelFrame(left, text="Trace Viewer Settings",
                                 bg=PANEL, fg=ACCENT, font=SANS_B)
        trace_frm.pack(fill="x", padx=4, pady=4)
        trace_frm.columnconfigure(1, weight=1)

        self.pulses_display = tk.IntVar(value=5)
        _lf(trace_frm, "Number of pulses to display", col=0, row=0)
        _ef(trace_frm, self.pulses_display, col=1, row=0, width=5)

        ctrl = tk.Frame(left, bg=BG)
        ctrl.pack(fill="x", padx=4, pady=4)
        ctrl.columnconfigure(0, weight=1)
        ctrl.columnconfigure(1, weight=1)

        self._start_btn = _btn(ctrl, "▶  Start", self._start, col=0, row=0, fg=BG, bg=GREEN)
        self._stop_btn  = _btn(ctrl, "■  Stop",  self._stop, col=1, row=0, fg=BG, bg=RED)
        self._stop_btn.configure(state="disabled")

        _btn(ctrl, "Clear Traces", self._clear_traces, col=0, row=1, colspan=2)

        # Performance Monitoring Indicators
        stats_frm = tk.LabelFrame(left, text="Performance Monitor", bg=PANEL, fg=YELLOW, font=SANS_B)
        stats_frm.pack(fill="x", padx=4, pady=4)
        stats_frm.columnconfigure(1, weight=1)
        
        self._rate_var = tk.StringVar(value="Rate: 0.0 Hz")
        self._dead_var = tk.StringVar(value="Deadtime: 0.0 %")
        
        tk.Label(stats_frm, textvariable=self._rate_var, bg=PANEL, fg=FG, font=SANS_B, anchor="w").grid(row=0, column=0, sticky="w", padx=PADX, pady=PADY)
        tk.Label(stats_frm, textvariable=self._dead_var, bg=PANEL, fg=RED, font=SANS_B, anchor="w").grid(row=1, column=0, sticky="w", padx=PADX, pady=PADY)

        right = tk.Frame(self, bg=BG)
        right.grid(row=0, column=1, sticky="nsew", padx=4, pady=4)
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        self._fig, self._ax = plt.subplots(figsize=(8, 5))
        self._fig.patch.set_facecolor(BG)
        self._ax.set_facecolor(PANEL)
        self._ax.set_xlabel("Time (μs)", color=FG)
        self._ax.set_ylabel("Voltage (V)", color=FG)
        self._ax.set_title("Scope - Recent Pulses", color=ACCENT)
        self._ax.grid(True)

        self._canvas = FigureCanvasTkAgg(self._fig, master=right)
        self._canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        self._canvas.draw()

        self._colors = [ACCENT, GREEN, YELLOW, PURPLE, RED]

    def _start(self):
        if self._running:
            return
        try:
            self._ads = WaveFormsADS()
        except Exception as exc:
            messagebox.showerror("Device Error", str(exc))
            return

        self._params = self.scope_settings.get_params()
        self._signal_params = self.signal_processing_settings.get_params()
        self._max_traces = self.pulses_display.get()
        
        self._time_indices = np.arange(self._params["buffer_size"])
        
        # Reset Diagnostics
        self._start_time = time.perf_counter()
        self._last_metrics_time = self._start_time
        self._total_events = 0
        self._last_drawn_events = 0
        
        self._q      = queue.Queue(maxsize=100)
        self._worker = AcqWorker(self._ads, self._params, self._q)
        self._worker.start()
        self._running = True
        self._start_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")
        self._status.set("Scope running …")
        
        self._poll()
        self._schedule_plots_refresh()

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

    def _poll(self):
        if not self._running:
            return
        try:
            while not self._q.empty():
                item = self._q.get_nowait()
                if isinstance(item, Exception):
                    self._status.set(f"Error: {item}")
                    self._stop()
                    return
                
                self._total_events += 1
                processed_item = self._process_trace(item)
                if processed_item is not None:
                    self._add_trace(processed_item)
        except queue.Empty:
            pass
        self.after(20, self._poll)

    def _process_trace(self, trace: np.ndarray) -> np.ndarray | None:
        s = self._signal_params
        if not s["apply_baseline"]:
            return trace
            
        max_val = np.max(trace)
        if max_val == 0: 
            max_val = 1e-6
            
        fs = self._params["sample_rate"]
        max_index = np.argmax(trace)
        stop_index = max(int(max_index - (s["position"] * fs)), 0)
        start_index = max(int(stop_index - (s["size"] * fs)), 0)
        
        if start_index >= stop_index:
            return None
            
        noise = np.std(trace[start_index:stop_index])
        if (noise / max_val) > (s["max_noise_percent"] / 100.0):
            return None
            
        mid_index = start_index + (stop_index - start_index) // 2
        baseline_section_one = trace[start_index:mid_index]
        if len(baseline_section_one) == 0:
            return None
        y_offset = np.mean(baseline_section_one)
        
        baseline_section_two = trace[mid_index:stop_index]
        if len(baseline_section_two) == 0:
            return None
            
        denom = stop_index - start_index
        slope_val = (np.mean(baseline_section_two) - y_offset) / denom if denom != 0 else 0

        if s["apply_slope_max"]:
            if (slope_val / max_val) > (s["max_slope_percent"] / 100.0):
                return None
        
        true_baseline = slope_val * (self._time_indices - start_index) + y_offset
        return trace - true_baseline

    def _add_trace(self, data: np.ndarray):
        p  = self._params
        fs = p["sample_rate"]
        t  = np.linspace(-len(data) / (2 * fs) * 1e6, len(data) / (2 * fs) * 1e6, len(data))
        self._traces.append((t, data))
        if len(self._traces) > self._max_traces:
            self._traces.pop(0)

    def _schedule_plots_refresh(self):
        if self._running:
            self._redraw(self._traces)
            self._update_performance_metrics()
            self.after(350, self._schedule_plots_refresh)

    def _update_performance_metrics(self):
        now = time.perf_counter()
        dt = now - self._last_metrics_time
        if dt <= 0:
            return
            
        # Calculate localized trigger count rate (Hz)
        events_caught = self._total_events - self._last_drawn_events
        current_rate = events_caught / dt
        self._rate_var.set(f"Rate: {current_rate:.1f} Hz")
        
        # Calculate Deadtime percentage based on current hardware payload size
        buffer_duration_s = self._params["buffer_size"] / self._params["sample_rate"]
        live_time_s = events_caught * buffer_duration_s
        dead_time_pct = max(0.0, min(100.0, ((dt - live_time_s) / dt) * 100.0))
        self._dead_var.set(f"Deadtime: {dead_time_pct:.1f} %")
        
        self._last_drawn_events = self._total_events
        self._last_metrics_time = now

    def _redraw(self, traces):
        p = self._params
        y_range = p["y_range"]
        time_base = p["time_base_us"]
        self._ax.cla()
        self._ax.set_xlim(-time_base / 2, time_base / 2)
        self._ax.set_ylim(-y_range / 2, y_range / 2)
        self._ax.set_facecolor(PANEL)
        self._ax.set_xlabel("Time (μs)", color=FG)
        self._ax.set_ylabel("Voltage (V)", color=FG)
        self._ax.set_title("Scope - Recent Pulses", color=ACCENT)
        self._ax.grid(True)

        if traces:
            for i, (t, d) in enumerate(traces):
                alpha = 0.4 + 0.6 * (i + 1) / len(traces)
                self._ax.plot(t, d, color=self._colors[i % len(self._colors)],
                              lw=1.2, alpha=alpha)
            self._ax.axhline(p["trigger_level"], color=RED, lw=0.8,
                             linestyle="--", alpha=0.7, label="Trigger")

        self._canvas.draw_idle()

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
        self._q:      queue.Queue  = queue.Queue(maxsize=1000)
        self._heights: list[float] = []
        self._last_waveform: np.ndarray | None = None
        self._running = False
        self._csv_file = None
        self._csv_writer = None
        self._time_indices = None
        
        # Diagnostics
        self._start_time = 0.0
        self._total_events = 0
        self._last_drawn_events = 0
        self._last_metrics_time = 0.0
        
        self._build()

    def _build(self):
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        left_scroll = ScrollableFrame(self, bg=BG, width=310)
        left_scroll.grid(row=0, column=0, sticky="ns", padx=(4, 0), pady=4)
        left = left_scroll.inner

        self.scope_settings = ScopeSettingsPanel(left)
        self.scope_settings.pack(fill="x", padx=4, pady=4)

        self.signal_processing_settings = SignalProcessingSettings(left)
        self.signal_processing_settings.pack(fill="x", padx=4, pady=4)

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

        ctrl = tk.Frame(left, bg=BG)
        ctrl.pack(fill="x", padx=4, pady=4)
        ctrl.columnconfigure(0, weight=1)
        ctrl.columnconfigure(1, weight=1)

        self._start_btn = _btn(ctrl, "▶  Start", self._start, col=0, row=0, fg=BG, bg=GREEN)
        self._stop_btn  = _btn(ctrl, "■  Stop",  self._stop, col=1, row=0, fg=BG, bg=RED)
        self._stop_btn.configure(state="disabled")

        _btn(ctrl, "Clear Histogram", self._clear_hist, col=0, row=1, colspan=2)

        # Performance Monitoring Indicators
        stats_frm = tk.LabelFrame(left, text="Performance Monitor", bg=PANEL, fg=YELLOW, font=SANS_B)
        stats_frm.pack(fill="x", padx=4, pady=4)
        stats_frm.columnconfigure(1, weight=1)
        
        self._rate_var = tk.StringVar(value="Rate: 0.0 Hz")
        self._dead_var = tk.StringVar(value="Deadtime: 0.0 %")
        self._count_var = tk.StringVar(value="Events logged: 0")
        
        tk.Label(stats_frm, textvariable=self._rate_var, bg=PANEL, fg=FG, font=SANS_B, anchor="w").grid(row=0, column=0, sticky="w", padx=PADX, pady=PADY)
        tk.Label(stats_frm, textvariable=self._dead_var, bg=PANEL, fg=RED, font=SANS_B, anchor="w").grid(row=1, column=0, sticky="w", padx=PADX, pady=PADY)
        tk.Label(stats_frm, textvariable=self._count_var, bg=PANEL, fg=YELLOW, font=SANS_B, anchor="w").grid(row=2, column=0, sticky="w", padx=PADX, pady=PADY)

        right = tk.Frame(self, bg=BG)
        right.grid(row=0, column=1, sticky="nsew", padx=4, pady=4)
        right.rowconfigure(0, weight=3)
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

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

    def _browse_file(self):
        path = filedialog.asksavesasfilename(
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
            self._count_var.set(f"Events logged: {len(self._heights)}")
            self._redraw()
        except Exception as exc:
            messagebox.showerror("Import Error", str(exc))

    def _start(self):
        if self._running:
            return
        try:
            self._ads = WaveFormsADS()
        except Exception as exc:
            messagebox.showerror("Device Error", str(exc))
            return

        path = self.filename.get().strip()
        if path:
            try:
                self._csv_file   = open(path, "a", newline="")
                self._csv_writer = csv.writer(self._csv_file)
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
        self._signal_params = self.signal_processing_settings.get_params()
        
        self._time_indices = np.arange(self._params["buffer_size"])
        
        # Reset Diagnostics
        self._start_time = time.perf_counter()
        self._last_metrics_time = self._start_time
        self._total_events = 0
        self._last_drawn_events = 0
        
        self._q      = queue.Queue(maxsize=1000)
        self._worker = AcqWorker(self._ads, self._params, self._q)
        self._worker.start()
        self._running = True
        self._start_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")
        self._status.set("Histogram running …")
        
        self._poll()
        self._schedule_plots_refresh()

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
        self._count_var.set("Events logged: 0")
        self._redraw()

    def _poll(self):
        if not self._running:
            return
        
        ts = None
        if self._csv_writer:
            ts = datetime.datetime.now().isoformat(timespec="milliseconds")

        while not self._q.empty():
            try:
                item = self._q.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, Exception):
                self._status.set(f"Error: {item}")
                self._stop()
                return
            
            self._total_events += 1
            processed = self._process_trace(item)
            if processed is not None:
                peak = float(np.max(processed))
                self._heights.append(peak)
                self._last_waveform = processed
                
                if self._csv_writer:
                    self._csv_writer.writerow([ts, f"{peak:.6f}"])

        if self._csv_writer:
            self._csv_file.flush()

        self.after(20, self._poll)

    def _process_trace(self, trace: np.ndarray) -> np.ndarray | None:
        s = self._signal_params
        if not s["apply_baseline"]:
            return trace
            
        max_val = np.max(trace)
        if max_val == 0: 
            max_val = 1e-6
            
        fs = self._params["sample_rate"]
        max_index = np.argmax(trace)
        stop_index = max(int(max_index - (s["position"] * fs)), 0)
        start_index = max(int(stop_index - (s["size"] * fs)), 0)
        
        if start_index >= stop_index:
            return None
            
        noise = np.std(trace[start_index:stop_index])
        if (noise / max_val) > (s["max_noise_percent"] / 100.0):
            return None
            
        mid_index = start_index + (stop_index - start_index) // 2
        baseline_section_one = trace[start_index:mid_index]
        if len(baseline_section_one) == 0:
            return None
        y_offset = np.mean(baseline_section_one)
        
        baseline_section_two = trace[mid_index:stop_index]
        if len(baseline_section_two) == 0:
            return None
            
        denom = stop_index - start_index
        slope_val = (np.mean(baseline_section_two) - y_offset) / denom if denom != 0 else 0

        if s["apply_slope_max"]:
            if (slope_val / max_val) > (s["max_slope_percent"] / 100.0):
                return None
        
        true_baseline = slope_val * (self._time_indices - start_index) + y_offset
        return trace - true_baseline

    def _schedule_plots_refresh(self):
        if self._running:
            self._redraw()
            self._redraw_pulse()
            self._update_performance_metrics()
            self.after(350, self._schedule_plots_refresh)

    def _update_performance_metrics(self):
        now = time.perf_counter()
        dt = now - self._last_metrics_time
        if dt <= 0:
            return
            
        # Calculate pulse capture frequency
        events_caught = self._total_events - self._last_drawn_events
        current_rate = events_caught / dt
        self._rate_var.set(f"Rate: {current_rate:.1f} Hz")
        
        # Calculate Deadtime percentage based on current hardware payload size
        buffer_duration_s = self._params["buffer_size"] / self._params["sample_rate"]
        live_time_s = events_caught * buffer_duration_s
        dead_time_pct = max(0.0, min(100.0, ((dt - live_time_s) / dt) * 100.0))
        self._dead_var.set(f"Deadtime: {dead_time_pct:.1f} %")
        
        self._count_var.set(f"Events logged: {len(self._heights)}")
        self._status.set(f"Histogram running … {len(self._heights)} events")
        
        self._last_drawn_events = self._total_events
        self._last_metrics_time = now

    def _redraw_pulse(self):
        p = self._params
        y_range = p["y_range"]
        time_base = p["time_base_us"]
        self._pax.cla()
        self._pax.set_xlim(-time_base / 2, time_base / 2)
        self._pax.set_ylim(-y_range / 2, y_range / 2)
        self._pax.set_facecolor(PANEL)
        self._pax.set_xlabel("Time (μs)", color=FG)
        self._pax.set_ylabel("V", color=FG)
        self._pax.set_title("Most Recent Pulse", color=ACCENT)
        self._pax.grid(True)
        if self._last_waveform is not None:
            fs = p["sample_rate"]
            t  = np.linspace(-len(self._last_waveform) / (2*fs) * 1e6, 
                             len(self._last_waveform) / (2*fs) * 1e6,
                             len(self._last_waveform))
            self._pax.plot(t, self._last_waveform, color=GREEN, lw=1.2)
            self._pax.axhline(p["trigger_level"], color=RED,
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

        self._status = tk.StringVar(value="Ready")
        status_bar = tk.Label(self, textvariable=self._status,
                              bg=BG, fg=YELLOW, font=MONO, anchor="w",
                              relief="flat")
        status_bar.pack(side="bottom", fill="x", padx=8, pady=2)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=4, pady=4)

        self._scope_tab = ScopeTab(nb, self._status)
        nb.add(self._scope_tab, text="  Scope View  ")

        self._hist_tab = HistogramTab(nb, self._status)
        nb.add(self._hist_tab, text="  Pulse Height Histogram  ")

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        try:
            self._scope_tab._stop()
            self._hist_tab._stop()
        except Exception:
            pass
        self.quit()
        self.destroy()


if __name__ == "__main__":
    app = PulseHeightAnalyzer()
    app.mainloop()