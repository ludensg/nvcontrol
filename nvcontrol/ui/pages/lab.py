"""GPU LAB — every control NVML exposes for this card (RTX 4070 and other GeForce)."""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QHeaderView, QSlider,
                               QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from ...core import runner
from ...integrations import lact
from ..async_util import run_async
from ..curve_editor import PRESETS, CurveEditor, sanitize
from ..widgets import HudPanel, button, label
from .base import Page

log = logging.getLogger("nvcontrol.lab")


class LabPage(Page):
    nav_key = "nav.lab"
    kicker = "// 03 · EVERY KNOB THE DRIVER EXPOSES"
    subtitle = ("Advanced controls for this exact card: temperature target, memory clock locking, per-fan "
                "control, a real fan-curve service, persistence mode and deep sensors. Values are limited to "
                "what the driver reports. Unsupported controls are disabled and say why.")

    def __init__(self, ctx, main):
        super().__init__(ctx, main)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._controls_tab(), "CONTROLS")
        self.tabs.addTab(self._curve_tab(), "FAN CURVE")
        self.tabs.addTab(self._sensors_tab(), "SENSORS")
        self.tabs.setMinimumHeight(720)
        self.lay.addWidget(self.tabs)
        self.lay.addStretch(1)
        self.sens_timer = QTimer(self)
        self.sens_timer.timeout.connect(self._refresh_sensors)
        self.on_caps()

    # =============================================================== CONTROLS
    def _controls_tab(self):
        w = QWidget()
        g = QGridLayout(w)
        g.setSpacing(14)

        # temperature target
        self.p_tt = HudPanel("Temperature target", "THERMAL")
        self.tt = QSlider(Qt.Horizontal)
        self.tt_val = label("—", "Mono")
        self.tt.valueChanged.connect(lambda v: self.tt_val.setText(f"{v} °C"))
        r = QHBoxLayout()
        r.addWidget(self.tt, 1)
        r.addWidget(self.tt_val)
        self.p_tt.add(r)
        self.p_tt.add(label("The GPU lowers its boost clocks to stay at or below this temperature. "
                            "Lower = cooler and quieter, slightly slower. It can't go past the hardware "
                            "slowdown/shutdown limits.", "Faint", wrap=True))
        r = QHBoxLayout()
        r.addStretch(1)
        self.tt_reset = button("RESET", None, lambda: self._helper(self.ctx.helper.reset_temp_target,
                                                                   self.ctx.gpu_index, msg="Temperature target reset"))
        self.tt_apply = button("APPLY", "Primary", self._apply_tt)
        r.addWidget(self.tt_reset)
        r.addWidget(self.tt_apply)
        self.p_tt.add(r)
        self.tt_info = label("", "Faint", wrap=True)
        self.p_tt.add(self.tt_info)
        g.addWidget(self.p_tt, 0, 0)

        # memory clock lock
        self.p_mem = HudPanel("Memory clock lock", "VRAM")
        r = QHBoxLayout()
        self.mem_min, self.mem_max = QComboBox(), QComboBox()
        r.addWidget(label("MIN", "Kicker"))
        r.addWidget(self.mem_min)
        r.addWidget(label("MAX", "Kicker"))
        r.addWidget(self.mem_max)
        r.addStretch(1)
        self.p_mem.add(r)
        self.p_mem.add(label("Pins the VRAM clock between two of the driver's supported steps. Locking MIN at the top "
                             "step stops memory downclocking (useful against stutter in some games, costs idle "
                             "power). Overclock memory with the offset on GPU TUNING.", "Faint", wrap=True))
        r = QHBoxLayout()
        r.addStretch(1)
        self.mem_reset = button("UNLOCK", None, lambda: self._helper(self.ctx.helper.reset_mem, self.ctx.gpu_index,
                                                                     msg="Memory clocks unlocked"))
        self.mem_apply = button("LOCK", "Primary", self._apply_mem)
        r.addWidget(self.mem_reset)
        r.addWidget(self.mem_apply)
        self.p_mem.add(r)
        g.addWidget(self.p_mem, 0, 1)

        # per-fan control
        self.p_fans = HudPanel("Per-fan control", "COOLING")
        self.fan_box = QVBoxLayout()
        self.p_fans.add(self.fan_box)
        r = QHBoxLayout()
        r.addStretch(1)
        r.addWidget(button("ALL FANS AUTOMATIC", None,
                           lambda: self._helper(self.ctx.helper.reset_fan, self.ctx.gpu_index, msg="Fans automatic")))
        self.p_fans.add(r)
        self.fan_sliders: list[QSlider] = []
        g.addWidget(self.p_fans, 1, 0)

        # power behaviour + persistence
        self.p_pwr = HudPanel("Power behaviour", "DRIVER")
        self.persist = QCheckBox("Persistence mode (keep the driver loaded, so settings survive idle)")
        self.persist.clicked.connect(lambda on: self._helper(self.ctx.helper.set_persistence, self.ctx.gpu_index,
                                                             on, msg=f"Persistence mode {'on' if on else 'off'}"))
        self.p_pwr.add(self.persist)
        self.p_pwr.add(label("Prefer maximum performance: keeps the core clock high instead of letting it idle down "
                             "(the Windows 'Power management mode' setting). On Wayland it's done by locking the "
                             "minimum core clock. More heat and power at idle.", "Faint", wrap=True))
        r = QHBoxLayout()
        self.maxperf = button("PREFER MAXIMUM PERFORMANCE", None, self._max_perf)
        self.normal = button("NORMAL (ADAPTIVE)", None, lambda: self._helper(self.ctx.helper.reset_clocks,
                                                                            self.ctx.gpu_index, msg="Adaptive clocks"))
        r.addWidget(self.maxperf)
        r.addWidget(self.normal)
        r.addStretch(1)
        self.p_pwr.add(r)
        g.addWidget(self.p_pwr, 1, 1)

        self.ctl_log = label("", "Mono", wrap=True)
        g.addWidget(self.ctl_log, 2, 0, 1, 2)
        g.setRowStretch(3, 1)
        return w

    # =============================================================== FAN CURVE
    def _curve_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        top = QHBoxLayout()
        top.addWidget(label("PRESET", "Kicker"))
        self.curve_preset = QComboBox()
        self.curve_preset.addItems(["(custom)"] + list(PRESETS))
        self.curve_preset.currentTextChanged.connect(
            lambda n: n in PRESETS and self.curve.set_points(PRESETS[n]))
        top.addWidget(self.curve_preset)
        top.addStretch(1)
        self.curve_state = label("", "H3")
        top.addWidget(self.curve_state)
        v.addLayout(top)
        self.curve = CurveEditor()
        saved = self.ctx.settings.extra.get("fan_curve")
        if saved:
            self.curve.points = sanitize(saved, self.curve.fan_min)
        v.addWidget(self.curve, 1)
        v.addWidget(label("Drag points · double-click to add · right-click to remove. Above 87 °C the fans always "
                          "run at 100 % (failsafe), and the curve never drops below the driver's minimum (dashed line). "
                          "Speeds only go down after the GPU has cooled 3 °C (hysteresis). The curve runs as a "
                          "system service, so it keeps working with NV//CONTROL closed and after reboot. "
                          "When disabled, the fans go back to the card's own automatic curve.",
                          "Faint", wrap=True))
        self.lact_warn = label("", "Warn", wrap=True)
        v.addWidget(self.lact_warn)
        r = QHBoxLayout()
        r.addStretch(1)
        self.curve_off = button("DISABLE CURVE", "Danger", lambda: self._curve_enable(False))
        self.curve_on = button("SAVE && ENABLE CURVE", "Primary", self._curve_save)
        r.addWidget(self.curve_off)
        r.addWidget(self.curve_on)
        v.addLayout(r)
        return w

    # =============================================================== SENSORS
    def _sensors_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(label("Read-only. Refreshes every 2 s while this tab is open.", "Faint"))
        self.sens = QTableWidget(0, 3)
        self.sens.setHorizontalHeaderLabels(["GROUP", "SENSOR", "VALUE"])
        self.sens.verticalHeader().setVisible(False)
        self.sens.setAlternatingRowColors(True)
        self.sens.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        v.addWidget(self.sens, 1)
        self.tabs_index_sensors = 2
        return w

    # =============================================================== state
    def on_caps(self):
        c, f = self.ctx.caps, self.ctx.feature
        helper_ok = self.ctx.sysinfo.helper_installed and self.ctx.sysinfo.pkexec
        why = "" if helper_ok else "Privileged helper missing: run install.sh."
        # temperature target
        tt = c.temp_target
        self.tt.setEnabled(bool(tt) and helper_ok)
        for b in (self.tt_apply, self.tt_reset):
            b.setEnabled(bool(tt) and helper_ok)
        if tt:
            self.tt.blockSignals(True)
            self.tt.setRange(tt.min_c, tt.max_c)
            self.tt.setValue(tt.current_c)
            self.tt.blockSignals(False)
            self.tt_val.setText(f"{tt.current_c} °C")
            self.tt_info.setText(f"Driver range {tt.min_c}–{tt.max_c} °C · current {tt.current_c} °C. {why}")
        else:
            self.tt_info.setText("Not exposed by this GPU/driver (NVML acoustic threshold unsupported).")
        # memory lock
        mems = c.supported_mem_clocks
        for cb in (self.mem_min, self.mem_max):
            cb.clear()
            for m in mems:
                cb.addItem(f"{m} MHz", m)
        if mems:
            self.mem_min.setCurrentIndex(0)
            self.mem_max.setCurrentIndex(len(mems) - 1)
        for wdg in (self.mem_min, self.mem_max, self.mem_apply, self.mem_reset):
            wdg.setEnabled(bool(mems) and helper_ok)
        # fans
        while self.fan_box.count():
            it = self.fan_box.takeAt(0)
            if it.layout():
                while it.layout().count():
                    x = it.layout().takeAt(0)
                    if x.widget():
                        x.widget().deleteLater()
            elif it.widget():
                it.widget().deleteLater()
        self.fan_sliders = []
        fan_ok = bool(c.fan_count) and helper_ok
        if not c.fan_count:
            self.fan_box.addWidget(label("No controllable fans reported (laptop, or the fans are managed "
                                         "by the board).", "Faint", wrap=True))
        lo = c.fan_min_pct or 30
        self.curve.fan_min = lo
        for i in range(c.fan_count):
            r = QHBoxLayout()
            s = QSlider(Qt.Horizontal)
            s.setRange(lo, c.fan_max_pct or 100)
            s.setValue(max(lo, 50))
            val = label(f"{s.value()} %", "Mono")
            s.valueChanged.connect(lambda v, lb=val: lb.setText(f"{v} %"))
            ap = button("SET", None, lambda _=False, idx=i, sl=s: self._helper(
                self.ctx.helper.set_fan_one, self.ctx.gpu_index, idx, sl.value(), msg=f"Fan {idx} → {sl.value()} %"))
            for x in (s, ap):
                x.setEnabled(fan_ok)
            r.addWidget(label(f"FAN {i}", "Kicker"))
            r.addWidget(s, 1)
            r.addWidget(val)
            r.addWidget(ap)
            self.fan_box.addLayout(r)
            self.fan_sliders.append(s)
        # power
        self.persist.setEnabled(c.persistence is not None and helper_ok)
        self.persist.setChecked(bool(c.persistence))
        lk = f("clock_lock")
        for b in (self.maxperf, self.normal):
            b.setEnabled(bool(lk and lk.status.name == "OPERATIONAL"))
        # curve
        for b in (self.curve_on, self.curve_off):
            b.setEnabled(fan_ok)
        self._curve_status()

    def on_show(self):
        self._curve_status()
        self.sens_timer.start(2000)
        self._refresh_sensors()

    def hideEvent(self, e):
        self.sens_timer.stop()
        super().hideEvent(e)

    def on_telemetry(self, t):
        if self.isVisible():
            self.curve.set_live(t.temp_c, t.fan_pct)

    # =============================================================== actions
    def _helper(self, fn, *args, msg: str = "Done"):
        log.info("lab action: %s %s", getattr(fn, "__name__", fn), args)

        def done(res, exc):
            if exc or not res.ok:
                err = str(exc) if exc else res.error
                self.ctl_log.setText(f"✗ {err}")
                self.error("GPU Lab", err)
            else:
                self.ctl_log.setText(f"✓ {msg}")
                self.main.toast(msg)
            self.ctx.refresh_caps()
            self._curve_status()
        run_async(lambda: fn(*args), done)

    def _apply_tt(self):
        v = self.tt.value()
        if v > (self.ctx.caps.temp_target.current_c if self.ctx.caps.temp_target else v) and not self.confirm(
                "Raise temperature target",
                f"Let the GPU run up to {v} °C before it reduces boost clocks? Still within the driver's limits, "
                "but hotter and louder."):
            return
        self._helper(self.ctx.helper.set_temp_target, self.ctx.gpu_index, v, msg=f"Temperature target {v} °C")

    def _apply_mem(self):
        lo, hi = self.mem_min.currentData(), self.mem_max.currentData()
        if lo is None or hi is None:
            return
        if lo > hi:
            self.error("Memory clock lock", "MIN must be ≤ MAX.")
            return
        self._helper(self.ctx.helper.lock_mem, self.ctx.gpu_index, lo, hi, msg=f"Memory locked {lo}–{hi} MHz")

    def _max_perf(self):
        clocks = self.ctx.caps.supported_gpu_clocks
        if not clocks:
            self.error("Prefer maximum performance", "The driver reports no supported clock list.")
            return
        hi = max(clocks)
        lo = min((c for c in clocks if c >= hi * 0.7), default=hi)
        self._helper(self.ctx.helper.lock_clocks, self.ctx.gpu_index, lo, hi,
                     msg=f"Prefer maximum performance: core locked {lo}–{hi} MHz")

    def _curve_status(self):
        if self.ctx.mock:
            on = getattr(self.ctx.backend, "fan_curve_on", False)
        else:
            on = runner.run(["systemctl", "is-active", "--quiet", "nvcontrol-fancurve.service"],
                            timeout=4, quiet=True).ok
        self.curve_state.setText("● CURVE ACTIVE" if on else "○ CURVE OFF (card's automatic curve)")
        self.curve_state.setStyleSheet(f"color: {'#76B900' if on else '#8D938A'};")
        self.lact_warn.setText("⚠ LACT's daemon (lactd) is running. If LACT also has a fan curve, they will fight. "
                               "Use only one of them." if self.ctx.sysinfo.lactd_active else "")

    def _curve_save(self):
        pts = sanitize(self.curve.points, self.curve.fan_min)
        if self.ctx.sysinfo.lactd_active and lact.SOCKET.exists() and not self.confirm(
                "LACT is running", "LACT may also be controlling the fans. Enable the NV//CONTROL curve anyway?"):
            return
        self.ctx.settings.extra["fan_curve"] = pts
        self.ctx.settings.save()
        gpu = self.ctx.gpu_index

        def job():
            r = self.ctx.helper.save_fan_curve(gpu, pts)
            return r if not r.ok else self.ctx.helper.fan_curve(True)
        self._helper(job, msg="Fan curve saved and enabled")

    def _curve_enable(self, on: bool):
        self._helper(self.ctx.helper.fan_curve, on, msg="Fan curve " + ("enabled" if on else "disabled — fans automatic"))

    def _refresh_sensors(self):
        if self.tabs.currentIndex() != self.tabs_index_sensors or not self.isVisible():
            return
        rows = self.ctx.backend.lab_sensors(self.ctx.gpu_index) if self.ctx.gpu else []
        if not rows:
            rows = [("—", "Deep sensors need NVML", "install python-nvidia-ml-py")]
        self.sens.setRowCount(len(rows))
        for i, (sec, lab, val) in enumerate(rows):
            for j, txt in enumerate((sec, lab, val)):
                it = self.sens.item(i, j)
                if it is None:
                    self.sens.setItem(i, j, QTableWidgetItem(txt))
                elif it.text() != txt:
                    it.setText(txt)
        self.sens.resizeColumnToContents(0)
        self.sens.resizeColumnToContents(1)
