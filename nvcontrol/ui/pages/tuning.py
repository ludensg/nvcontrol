from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QGridLayout, QHBoxLayout,
                               QPlainTextEdit, QSlider, QSpinBox, QVBoxLayout)

from ...core.config import data_dir, load_json, save_json
from ...integrations.tools import launch_tool
from ...tuning.presets import DESCRIPTIONS, PRESET_NAMES, preset_settings
from ..async_util import run_async
from ..labels import L
from ..widgets import CountdownDialog, HudPanel, button, label
from .base import Page, usable

log = logging.getLogger("nvcontrol.tuning")
WARN_OC = ("Clock offsets beyond what your card tolerates cause crashes, artifacts or driver resets. "
           "Increase in small steps (+15…+50 MHz core, +100…+200 MHz memory) and use TEST first.")


class SliderSpin:
    """Slider + spinbox pair kept in sync."""

    def __init__(self, lo: int, hi: int, val: int, suffix: str):
        self.slider = QSlider(Qt.Horizontal)
        self.spin = QSpinBox()
        self.spin.setSuffix(suffix)
        self.spin.setMinimumWidth(110)
        self.set_range(lo, hi, val)
        self.slider.valueChanged.connect(self.spin.setValue)
        self.spin.valueChanged.connect(self.slider.setValue)

    def set_range(self, lo, hi, val):
        for w in (self.slider, self.spin):
            w.blockSignals(True)
            w.setRange(int(lo), int(hi))
            w.setValue(int(val))
            w.blockSignals(False)

    def value(self) -> int:
        return self.spin.value()

    def set_enabled(self, on: bool):
        self.slider.setEnabled(on)
        self.spin.setEnabled(on)

    def row(self) -> QHBoxLayout:
        r = QHBoxLayout()
        r.addWidget(self.slider, 1)
        r.addWidget(self.spin)
        return r


class TuningPage(Page):
    nav_key = "nav.tuning"
    kicker = "// 02 · HARDWARE CONTROL"
    subtitle = ("Driver-enforced limits only. Changes go through the audited root helper (polkit). "
                "TEST applies for 20 seconds and reverts unless you confirm.")

    def __init__(self, ctx, main):
        super().__init__(ctx, main)
        self.snapshot_path = data_dir() / "original-tuning.json"

        # presets
        pp = HudPanel("Profiles", "PRESET")
        r = QHBoxLayout()
        self.preset = QComboBox()
        self.preset.addItems(PRESET_NAMES)
        self.preset.setCurrentText(ctx.settings.active_preset)
        self.preset.currentTextChanged.connect(self._preset_changed)
        r.addWidget(self.preset)
        self.preset_desc = label("", "Muted", wrap=True)
        r.addWidget(self.preset_desc, 1)
        pp.add(r)
        self.lay.addWidget(pp)

        grid = self.grid(2)
        # power
        self.p_power = HudPanel(L("power"), "POWER")
        self.power = SliderSpin(100, 400, 250, " W")
        self.p_power.add(self.power.row())
        self.power_info = label("", "Faint", wrap=True)
        self.p_power.add(self.power_info)
        self.power_status = QHBoxLayout()
        self.p_power.add(self.power_status)
        grid.addWidget(self.p_power, 0, 0)

        # fan
        self.p_fan = HudPanel(L("fan"), "COOLING")
        self.fan_manual = QCheckBox("Manual fixed speed (overrides the VBIOS curve)")
        self.fan = SliderSpin(30, 100, 50, " %")
        self.fan_manual.toggled.connect(lambda on: self.fan.set_enabled(on and usable(self.ctx.feature("fan_manual"))))
        self.p_fan.add(self.fan_manual)
        self.p_fan.add(self.fan.row())
        self.fan_info = label("", "Faint", wrap=True)
        self.p_fan.add(self.fan_info)
        lr = QHBoxLayout()
        self.lact_btn = button("OPEN LACT · FAN CURVES", None, lambda: self._launch("lact"))
        lr.addWidget(self.lact_btn)
        lr.addStretch(1)
        self.p_fan.add(lr)
        grid.addWidget(self.p_fan, 0, 1)

        # offsets
        self.p_oc = HudPanel("Clock offsets", "OVERCLOCK / UNDERVOLT")
        self.core = SliderSpin(-500, 500, 0, " MHz")
        self.mem = SliderSpin(-1000, 3000, 0, " MHz")
        g = QGridLayout()
        g.addWidget(label("CORE", "Kicker"), 0, 0)
        g.addLayout(self.core.row(), 0, 1)
        g.addWidget(label("MEMORY", "Kicker"), 1, 0)
        g.addLayout(self.mem.row(), 1, 1)
        self.p_oc.add(g)
        self.oc_info = label("", "Faint", wrap=True)
        self.p_oc.add(self.oc_info)
        w = label("⚠ " + WARN_OC, "Warn", wrap=True)
        self.p_oc.add(w)
        grid.addWidget(self.p_oc, 1, 0)

        # clock lock
        self.p_lock = HudPanel("Clock locking", "FREQUENCY")
        self.lock = QCheckBox("Lock GPU core clock range")
        self.lock_min, self.lock_max = QSpinBox(), QSpinBox()
        for s in (self.lock_min, self.lock_max):
            s.setRange(100, 4000)
            s.setSuffix(" MHz")
        self.lock_min.setValue(210)
        self.lock_max.setValue(1800)
        self.p_lock.add(self.lock)
        lr2 = QHBoxLayout()
        lr2.addWidget(label("MIN", "Kicker"))
        lr2.addWidget(self.lock_min)
        lr2.addWidget(label("MAX", "Kicker"))
        lr2.addWidget(self.lock_max)
        lr2.addStretch(1)
        self.p_lock.add(lr2)
        self.p_lock.add(label("Undervolt recipe: raise the core offset (e.g. +150) and lock the max clock "
                              "slightly below stock boost. The card reaches that clock at a lower voltage. "
                              "Test stability with your games.", "Faint", wrap=True))
        self.lock_status = QHBoxLayout()
        self.p_lock.add(self.lock_status)
        grid.addWidget(self.p_lock, 1, 1)
        self.lay.addLayout(grid)

        # actions
        ap = HudPanel("Apply", "COMMIT")
        row = QHBoxLayout()
        self.b_test = button("TEST 20 s", "Primary", self._test, "Apply now, auto-revert unless confirmed.")
        self.b_apply = button("APPLY", None, self._apply, "Apply until reboot.")
        self.b_startup = button("SAVE AS STARTUP PROFILE", None, self._save_startup,
                                "Apply at every boot (systemd, with crash-loop protection).")
        self.b_clear = button("CLEAR STARTUP", None, self._clear_startup)
        self.b_reset = button("RESET TO DEFAULTS", "Danger", self._reset)
        for b in (self.b_test, self.b_apply, self.b_startup, self.b_clear):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.b_reset)
        ap.add(row)
        self.cmd_preview = label("", "Mono", wrap=True)
        ap.add(self.cmd_preview)
        self.log = QPlainTextEdit()
        self.log.setObjectName("Mono")
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(110)
        self.log.setPlaceholderText("Results of tuning operations appear here.")
        ap.add(self.log)
        ap.add(label("Recovery: if a startup profile ever makes the system unstable, it is skipped automatically "
                     "after a boot that did not reach the 3-minute stable mark. You can also add "
                     "nvcontrol.safe=1 to the kernel command line at the boot menu, or run "
                     "'sudo /usr/lib/nvcontrol/nvcontrol-helper reset-all'.", "Faint", wrap=True))
        self.lay.addWidget(ap)
        self.lay.addStretch(1)
        for s in (self.power.spin, self.core.spin, self.mem.spin, self.fan.spin, self.lock_min, self.lock_max):
            s.valueChanged.connect(self._update_preview)
        for cb in (self.lock, self.fan_manual):
            cb.toggled.connect(self._update_preview)
        self._preset_changed(self.preset.currentText(), init=True)
        self.on_caps()

    # ---------------------------------------------------------------- state
    def retranslate(self):
        super().retranslate()
        self.p_power.set_title(L("power"))
        self.p_fan.set_title(L("fan"))

    def on_caps(self):
        c, f = self.ctx.caps, self.ctx.feature
        for lay in (self.power_status, self.lock_status):
            while lay.count():
                it = lay.takeAt(0)
                if it.widget():
                    it.widget().deleteLater()
        if c.power:
            self.power.set_range(c.power.min_w, c.power.max_w, c.power.current_w)
            self.power_info.setText(f"Driver range {c.power.min_w:.0f}–{c.power.max_w:.0f} W · "
                                    f"default {c.power.default_w:.0f} W · current {c.power.current_w:.0f} W")
        else:
            self.power_info.setText(f("power_limit").detail if f("power_limit") else "")
        self.power.set_enabled(usable(f("power_limit")))
        self.power_status.addLayout(self.status_row(f("power_limit")))

        fm = f("fan_manual")
        self.fan_manual.setEnabled(usable(fm))
        if c.fan_count:
            self.fan.set_range(c.fan_min_pct or 30, c.fan_max_pct or 100, max(c.fan_min_pct or 30, 50))
        self.fan.set_enabled(usable(fm) and self.fan_manual.isChecked())
        self.fan_info.setText((fm.mechanism + " — " + fm.detail) if fm else "")
        self.lact_btn.setEnabled(self.ctx.sysinfo.has("lact"))

        okc, okm = usable(f("gpc_offset")), usable(f("mem_offset"))
        if c.gpc_offset:
            self.core.set_range(c.gpc_offset.min_mhz, c.gpc_offset.max_mhz, c.gpc_offset.current_mhz)
        if c.mem_offset:
            self.mem.set_range(c.mem_offset.min_mhz, c.mem_offset.max_mhz, c.mem_offset.current_mhz)
        self.core.set_enabled(okc)
        self.mem.set_enabled(okm)
        txt = []
        for fid in ("gpc_offset", "mem_offset"):
            ff = f(fid)
            if ff:
                txt.append(f"{ff.name}: {ff.status.value} — {ff.requirement or ff.detail}")
        txt.append("Memory offsets are NVML units; X11 nvidia-settings displays twice this value for GDDR memory.")
        self.oc_info.setText("\n".join(txt))

        lk = f("clock_lock")
        self.lock.setEnabled(usable(lk))
        self.lock_min.setEnabled(usable(lk))
        self.lock_max.setEnabled(usable(lk))
        if c.supported_gpu_clocks:
            lo, hi = min(c.supported_gpu_clocks), max(c.supported_gpu_clocks)
            for s in (self.lock_min, self.lock_max):
                s.setRange(lo, hi)
            if self.lock_max.value() == 1800:
                self.lock_max.setValue(hi)
        self.lock_status.addLayout(self.status_row(lk))
        any_ok = any(usable(f(x)) for x in ("power_limit", "gpc_offset", "mem_offset", "clock_lock", "fan_manual"))
        for b in (self.b_test, self.b_apply, self.b_startup, self.b_reset, self.b_clear):
            b.setEnabled(any_ok)
        self._update_preview()

    def _preset_changed(self, name: str, init: bool = False):
        self.preset_desc.setText(DESCRIPTIONS.get(name, ""))
        if init or name == "Custom":
            return
        s, notes = preset_settings(name, self.ctx.caps)
        if s.power_w is not None:
            self.power.spin.setValue(int(s.power_w))
        if s.core_offset is not None:
            self.core.spin.setValue(s.core_offset)
        if s.mem_offset is not None:
            self.mem.spin.setValue(s.mem_offset)
        self.lock.setChecked(False)
        self.fan_manual.setChecked(False)
        for n in notes:
            self._log(n)
        self._update_preview()

    # ---------------------------------------------------------------- actions
    def desired(self) -> dict:
        f = self.ctx.feature
        d: dict = {}
        if usable(f("power_limit")):
            d["power_w"] = self.power.value()
        if usable(f("gpc_offset")):
            d["core_offset"] = self.core.value()
        if usable(f("mem_offset")):
            d["mem_offset"] = self.mem.value()
        if usable(f("clock_lock")) and self.lock.isChecked():
            d["lock_min"], d["lock_max"] = self.lock_min.value(), self.lock_max.value()
        if usable(f("fan_manual")) and self.fan_manual.isChecked():
            d["fan_pct"] = self.fan.value()
        return d

    def current(self) -> dict:
        c = self.ctx.caps
        d: dict = {}
        if c.power:
            d["power_w"] = c.power.current_w
        if c.gpc_offset:
            d["core_offset"] = c.gpc_offset.current_mhz
        if c.mem_offset:
            d["mem_offset"] = c.mem_offset.current_mhz
        return d

    def _update_preview(self):
        from ...tuning.helper_client import describe
        d = self.desired()
        args = ["apply", "--gpu", str(self.ctx.gpu_index)]
        for k, fl in (("power_w", "--power"), ("core_offset", "--core"), ("mem_offset", "--mem"),
                      ("lock_min", "--lock-min"), ("lock_max", "--lock-max"), ("fan_pct", "--fan")):
            if k in d:
                args += [fl, str(int(d[k]))]
        if "lock_min" not in d:
            args.append("--unlock")
        if "fan_pct" not in d and self.ctx.caps.fan_count:
            args.append("--fan-auto")
        self.cmd_preview.setText("$ " + describe(args))

    def _log(self, msg: str):
        log.info(msg)
        self.log.appendPlainText(msg)

    def _risky(self, d: dict) -> bool:
        return d.get("core_offset", 0) > 0 or d.get("mem_offset", 0) > 0 or \
            (self.ctx.caps.power and d.get("power_w", 0) > self.ctx.caps.power.default_w)

    def _ensure_snapshot(self):
        if not self.snapshot_path.exists() and self.ctx.gpu:
            save_json(self.snapshot_path, {"gpu": self.ctx.gpu.uuid, **self.current()})
            self._log(f"Saved original settings snapshot: {self.snapshot_path}")

    def _do_apply(self, d: dict, then=None):
        self._update_preview()
        self._ensure_snapshot()
        unlock = "lock_min" not in d and self.ctx.feature("clock_lock") and usable(self.ctx.feature("clock_lock"))
        fan_auto = "fan_pct" not in d and usable(self.ctx.feature("fan_manual"))
        self._log("Applying: " + ", ".join(f"{k}={v}" for k, v in d.items()))
        self.setEnabled(False)
        gpu = self.ctx.gpu_index

        def done(res, exc):
            self.setEnabled(True)
            if exc or not res.ok:
                err = str(exc) if exc else res.error
                self._log(f"✗ {err}")
                self.error("Tuning failed", err)
            else:
                self._log("✓ applied")
            self.ctx.refresh_caps()
            if then:
                then(bool(res and res.ok))

        run_async(lambda: self.ctx.helper.apply(gpu, d, unlock=bool(unlock), fan_auto=bool(fan_auto)), done)

    def _test(self):
        d = self.desired()
        before = self.current()

        def after(ok):
            if not ok:
                return
            dlg = CountdownDialog(self, "Test settings",
                                  "The new settings are active. Run a game or benchmark now. "
                                  "Keep them, or they revert automatically.", 20)
            if dlg.exec() == QDialog.Accepted:
                self._log("Test settings kept (until reboot).")
                self._mark_custom()
            else:
                self._log("Reverting test settings…")
                self._do_apply(before)

        if self._risky(d) and not self.confirm("Unstable settings", WARN_OC + "\n\nContinue with the test?"):
            return
        self._do_apply(d, after)

    def _apply(self):
        d = self.desired()
        if self._risky(d) and not self.confirm(
                "Apply without testing?", WARN_OC + "\n\nApply until the next reboot?"):
            return
        self._do_apply(d, lambda ok: ok and self._mark_custom())

    def _mark_custom(self):
        self.ctx.settings.active_preset = self.preset.currentText()
        self.ctx.settings.save()

    def _save_startup(self):
        d = {k: v for k, v in self.desired().items() if k != "fan_pct"}
        if not self.confirm("Startup profile",
                            "Apply these settings at every boot?\n\n" +
                            "\n".join(f"  {k} = {v}" for k, v in d.items()) +
                            "\n\nFan speed is never applied at boot (the VBIOS curve stays in control). "
                            "Requires the nvcontrol-apply service (enabled by install.sh)."):
            return
        gpu = self.ctx.gpu_index

        def done(res, exc):
            if exc or not res.ok:
                self.error("Could not save startup profile", str(exc) if exc else res.error)
            else:
                self._log("✓ startup profile saved (/etc/nvcontrol/tuning.json)")
                self.ctx.settings.startup_profile = self.preset.currentText()
                self.ctx.settings.save()

        run_async(lambda: self.ctx.helper.save_startup(gpu, d), done)

    def _clear_startup(self):
        run_async(self.ctx.helper.clear_startup,
                  lambda r, e: self._log("✓ startup profile cleared" if r and r.ok else f"✗ {e or r.error}"))

    def _reset(self):
        if not self.confirm("Reset", "Reset power limit, offsets, clock lock and fans to driver defaults?"):
            return
        gpu = self.ctx.gpu_index

        def done(res, exc):
            self._log("✓ reset to defaults" if res and res.ok else f"✗ {exc or res.error}")
            self.ctx.refresh_caps()
            self.preset.setCurrentText("Balanced")

        run_async(lambda: self.ctx.helper.reset_all(gpu), done)

    def _launch(self, tid):
        if not launch_tool(tid):
            self.error("Launch failed", f"Could not start {tid}. Is it installed?")

    def original_snapshot(self) -> dict:
        return load_json(self.snapshot_path, {})
