from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QComboBox, QFileDialog, QGridLayout, QHBoxLayout

from ...core.config import atomic_write
from ...core.report import build_report
from ..labels import L
from ..widgets import HudPanel, LiveGraph, MetricTile, RadialGauge, button, label
from .base import Page

INTERVALS = [("250 ms", 250), ("500 ms", 500), ("1 s", 1000), ("2 s", 2000), ("5 s", 5000)]


class DashboardPage(Page):
    nav_key = "nav.command"
    kicker = "// 01 · LIVE TELEMETRY"
    subtitle = "Real-time GPU state straight from the NVIDIA driver."

    def __init__(self, ctx, main):
        super().__init__(ctx, main)
        # --- identity strip
        ident = HudPanel("", "GPU IDENTITY")
        row = QHBoxLayout()
        self.gpu_name = label("No NVIDIA GPU detected", "H2")
        row.addWidget(self.gpu_name, 1)
        row.addWidget(label("POLL", "Kicker"))
        self.interval = QComboBox()
        for name, ms in INTERVALS:
            self.interval.addItem(name, ms)
        idx = next((i for i, (_, ms) in enumerate(INTERVALS) if ms == ctx.settings.poll_interval_ms), 2)
        self.interval.setCurrentIndex(idx)
        self.interval.currentIndexChanged.connect(self._interval)
        row.addWidget(self.interval)
        row.addWidget(button("EXPORT DIAGNOSTICS", None, self._export,
                             "Save a full text report (system, GPU, features, tools)."))
        ident.add(row)
        self.ident_line = label("", "Mono", wrap=True)
        ident.add(self.ident_line)
        self.lay.addWidget(ident)

        # --- gauges
        gp = HudPanel("", "PRIMARY INSTRUMENTS")
        gl = QHBoxLayout()
        self.g_temp = RadialGauge(L("temp"), "°C", 100, warn=80, crit=88)
        self.g_load = RadialGauge(L("load"), "%", 100)
        self.g_power = RadialGauge(L("power"), "W", 300, warn=None)
        self.g_fan = RadialGauge(L("fan"), "%", 100)
        for g in (self.g_temp, self.g_load, self.g_power, self.g_fan):
            g.animate = ctx.settings.animations
            gl.addWidget(g)
        gp.add(gl)
        self.lay.addWidget(gp)

        # --- tiles
        tp = HudPanel("", "SUBSYSTEMS")
        tg = QGridLayout()
        tg.setSpacing(8)
        self.t_core = MetricTile(L("core"), "MHz")
        self.t_mem = MetricTile(L("mem"), "MHz")
        self.t_vram = MetricTile(L("vram"), "")
        self.t_pl = MetricTile(L("power"), "W")
        self.t_ps = MetricTile("P-state")
        self.t_drv = MetricTile("Driver")
        self.t_prof = MetricTile("Profile")
        self.t_thr = MetricTile("Clock limiter")
        for i, t in enumerate((self.t_core, self.t_mem, self.t_vram, self.t_pl,
                               self.t_ps, self.t_drv, self.t_prof, self.t_thr)):
            tg.addWidget(t, i // 4, i % 4)
        tp.add(tg)
        self.lay.addWidget(tp)

        # --- graphs
        grid = self.grid(2)
        secs = ctx.settings.graph_seconds
        self.gr_tl = LiveGraph("Thermal / load", "°C · %", 100, secs)
        self.gr_tl.add_series("TEMP", "warn")
        self.gr_tl.add_series("LOAD", "accent")
        self.gr_clk = LiveGraph("Clocks", "MHz", None, secs)
        self.gr_clk.add_series("CORE", "accent")
        self.gr_clk.add_series("MEM", "graph2")
        self.gr_pw = LiveGraph("Power", "W", None, secs)
        self.gr_pw.add_series("DRAW", "accent")
        self.gr_pw.add_series("LIMIT", "crit")
        self.gr_vram = LiveGraph("VRAM", "MiB", None, secs)
        self.gr_vram.add_series("USED", "info")
        for i, g in enumerate((self.gr_tl, self.gr_clk, self.gr_pw, self.gr_vram)):
            p = HudPanel()
            p.add(g)
            grid.addWidget(p, i // 2, i % 2)
        self.lay.addLayout(grid)
        self.lay.addStretch(1)
        self.on_caps()

    def retranslate(self):
        super().retranslate()
        for g, k in ((self.g_temp, "temp"), (self.g_load, "load"), (self.g_power, "power"), (self.g_fan, "fan")):
            g.title = L(k)
            g.update()
        for t, k in ((self.t_core, "core"), (self.t_mem, "mem"), (self.t_vram, "vram"), (self.t_pl, "power")):
            t.title = L(k)
            t.update()

    def on_caps(self):
        g = self.ctx.gpu
        if not g:
            self.gpu_name.setText("NO NVIDIA GPU DETECTED")
            self.ident_line.setText(self.ctx.backend.source + " — check that the nvidia driver is loaded "
                                    "(lsmod | grep nvidia) and nvidia-utils is installed.")
            return
        self.gpu_name.setText(g.name.upper())
        vram = f"{g.vram_total_mb / 1024:.0f} GB" if g.vram_total_mb else "?"
        mod = {True: "open kernel module", False: "proprietary kernel module"}.get(g.open_kernel_module, "?")
        self.ident_line.setText(
            f"ARCH {g.arch or '?'} · VRAM {vram} · DRIVER {g.driver_version} ({mod}) · CUDA {g.cuda_version or '—'}"
            f" · PCI {g.pci_bus_id} · VBIOS {g.vbios or '—'} · SOURCE {self.ctx.backend.name}")
        self.t_drv.set(g.driver_version or "—")
        self.t_prof.set(self.ctx.settings.active_preset)
        if self.ctx.caps.power:
            self.g_power.vmax = self.ctx.caps.power.max_w

    def on_telemetry(self, t):
        self.g_temp.set_value(t.temp_c)
        self.g_load.set_value(t.util_gpu, f"MEM {t.util_mem:.0f}%" if t.util_mem is not None else "")
        if t.power_limit_w and not self.ctx.caps.power:
            self.g_power.vmax = t.power_limit_w
        self.g_power.set_value(t.power_w, f"LIMIT {t.power_limit_w:.0f} W" if t.power_limit_w else "")
        self.g_fan.set_value(t.fan_pct, "" if t.fan_pct is not None else "not exposed")
        if t.clock_gpu_mhz is not None:
            self.t_core.set(f"{t.clock_gpu_mhz:.0f}", t.clock_gpu_mhz / t.clock_gpu_max_mhz if t.clock_gpu_max_mhz else None)
        if t.clock_mem_mhz is not None:
            self.t_mem.set(f"{t.clock_mem_mhz:.0f}", t.clock_mem_mhz / t.clock_mem_max_mhz if t.clock_mem_max_mhz else None)
        if t.vram_used_mb is not None and t.vram_total_mb:
            frac = t.vram_used_mb / t.vram_total_mb
            self.t_vram.set(f"{t.vram_used_mb / 1024:.1f}/{t.vram_total_mb / 1024:.0f} GB", frac,
                            "warn" if frac > 0.9 else "accent")
        if t.power_limit_w:
            self.t_pl.set(f"{t.power_limit_w:.0f}", (t.power_w or 0) / t.power_limit_w)
        self.t_ps.set(t.pstate or "—")
        thr = [x for x in t.throttle if x != "GPU idle"]
        self.t_thr.set(thr[0] if thr else ("Idle" if "GPU idle" in t.throttle else "None"), None,
                       "warn" if any("thermal" in x.lower() or "HW" in x for x in thr) else "accent")
        ts = t.timestamp
        self.gr_tl.push("TEMP", ts, t.temp_c)
        self.gr_tl.push("LOAD", ts, t.util_gpu)
        self.gr_clk.push("CORE", ts, t.clock_gpu_mhz)
        self.gr_clk.push("MEM", ts, t.clock_mem_mhz)
        self.gr_pw.push("DRAW", ts, t.power_w)
        self.gr_pw.push("LIMIT", ts, t.power_limit_w)
        self.gr_vram.push("USED", ts, t.vram_used_mb)
        if self.isVisible():
            for g in (self.gr_tl, self.gr_clk, self.gr_pw, self.gr_vram):
                g.update()

    def _interval(self):
        ms = self.interval.currentData()
        self.ctx.settings.poll_interval_ms = ms
        self.ctx.settings.save()
        self.main.telemetry.set_interval(ms)

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export diagnostics", str(Path.home() / "nvcontrol-diagnostics.txt"),
                                              "Text (*.txt)")
        if path:
            atomic_write(path, build_report(self.ctx))
            self.main.toast(f"Diagnostics saved to {path}")
