from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QGridLayout,
                               QHBoxLayout, QLineEdit, QSlider, QSpinBox)

from ...core import runner
from ...integrations import display as D
from ..async_util import run_async
from ..vibrance_panel import VibrancePanel
from ..widgets import CountdownDialog, HudPanel, button, label
from .base import Page

log = logging.getLogger("nvcontrol.display")


class DisplayPage(Page):
    nav_key = "nav.display"
    kicker = "// 03 · OUTPUT PIPELINE"
    subtitle = ("Per-display configuration through KWin (Wayland) or xrandr/nvidia-settings (X11). "
                "Compositor brightness, monitor backlight (DDC/CI) and HDR are different things and are "
                "labelled separately.")

    def __init__(self, ctx, main):
        super().__init__(ctx, main)
        # ---------------- outputs
        op = HudPanel("Outputs", "KSCREEN / XRANDR")
        top = QHBoxLayout()
        self.out = QComboBox()
        self.out.currentIndexChanged.connect(self._load_output)
        top.addWidget(label("OUTPUT", "Kicker"))
        top.addWidget(self.out, 1)
        top.addWidget(button("REFRESH", None, self._refresh))
        top.addWidget(button("KDE DISPLAY SETTINGS", None,
                             lambda: runner.launch_detached(["systemsettings", "kcm_kscreen"])))
        op.add(top)
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        self.mode = QComboBox()
        self.scale = QDoubleSpinBox()
        self.scale.setRange(0.5, 4.0)
        self.scale.setSingleStep(0.05)
        self.vrr = QComboBox()
        self.vrr.addItems(["never", "automatic", "always"])
        self.vrr.setToolTip("automatic = VRR for fullscreen apps only (recommended). "
                            "This is how G-SYNC / G-SYNC Compatible is enabled on KDE Wayland.")
        self.hdr = QCheckBox("HDR output")
        self.bright = QSlider(Qt.Horizontal)
        self.bright.setRange(0, 100)
        self.bright.setToolTip("Applied when you release the slider.")
        self.bright.sliderReleased.connect(self._apply_brightness)
        self.icc = QLineEdit()
        self.icc.setPlaceholderText("/path/to/profile.icc (empty = none)")
        self.posx, self.posy = QSpinBox(), QSpinBox()
        for s in (self.posx, self.posy):
            s.setRange(-16384, 16384)
        rows = [("MODE", self.mode), ("SCALE", self.scale), ("ADAPTIVE SYNC / VRR", self.vrr), ("HDR", self.hdr),
                ("COMPOSITOR BRIGHTNESS", self.bright)]
        for i, (k, w) in enumerate(rows):
            g.addWidget(label(k, "Kicker"), i, 0)
            g.addWidget(w, i, 1)
        g.addWidget(label("ICC PROFILE", "Kicker"), len(rows), 0)
        ir = QHBoxLayout()
        ir.addWidget(self.icc, 1)
        ir.addWidget(button("BROWSE", None, self._browse_icc))
        g.addLayout(ir, len(rows), 1)
        g.addWidget(label("POSITION", "Kicker"), len(rows) + 1, 0)
        pr = QHBoxLayout()
        pr.addWidget(self.posx)
        pr.addWidget(self.posy)
        pr.addStretch(1)
        g.addLayout(pr, len(rows) + 1, 1)
        g.setColumnStretch(1, 1)
        op.add(g)
        op.add(label("Compositor brightness dims the image in KWin (works for SDR and HDR); it does not change "
                     "the monitor backlight. Use DDC/CI below for real monitor luminance.", "Faint", wrap=True))
        ar = QHBoxLayout()
        self.restore_sleep = QCheckBox("Restore brightness && vibrance after sleep / hibernate")
        self.restore_sleep.setChecked(ctx.settings.extra.get("restore_after_sleep", True))
        self.restore_sleep.toggled.connect(self._save_restore_pref)
        ar.addWidget(self.restore_sleep)
        ar.addStretch(1)
        self.apply_btn = button("APPLY OUTPUT", "Primary", self._apply_output)
        ar.addWidget(self.apply_btn)
        op.add(ar)
        self.out_status = QHBoxLayout()
        op.add(self.out_status)
        self.lay.addWidget(op)

        grid = self.grid(2)
        # ---------------- vibrance (per monitor)
        self.vp = VibrancePanel(ctx, main, lambda: self.outputs)
        self.vib_detected = False
        self.lay.addWidget(self.vp)

        # ---------------- DDC
        self.dp = HudPanel("Monitor controls (DDC/CI)", "REAL BACKLIGHT")
        dr = QHBoxLayout()
        self.ddc = QComboBox()
        dr.addWidget(self.ddc, 1)
        self.ddc_detect = button("DETECT MONITORS", None, self._ddc_detect)
        dr.addWidget(self.ddc_detect)
        self.dp.add(dr)
        self.ddc_b = QSlider(Qt.Horizontal)
        self.ddc_c = QSlider(Qt.Horizontal)
        for s in (self.ddc_b, self.ddc_c):
            s.setRange(0, 100)
            s.setValue(50)
        dg = QGridLayout()
        dg.addWidget(label("BRIGHTNESS", "Kicker"), 0, 0)
        dg.addWidget(self.ddc_b, 0, 1)
        dg.addWidget(label("CONTRAST", "Kicker"), 1, 0)
        dg.addWidget(self.ddc_c, 1, 1)
        self.dp.add(dg)
        dr2 = QHBoxLayout()
        dr2.addStretch(1)
        self.ddc_apply = button("APPLY TO MONITOR", None, self._ddc_apply)
        dr2.addWidget(self.ddc_apply)
        self.dp.add(dr2)
        self.ddc_status = QHBoxLayout()
        self.dp.add(self.ddc_status)
        grid.addWidget(self.dp, 0, 0)

        # ---------------- color
        cp = HudPanel("Color temperature · Gamma", "COLOR")
        self.color_status = QHBoxLayout()
        cp.add(self.color_status)
        cb = QHBoxLayout()
        cb.addWidget(button("KDE NIGHT LIGHT", None,
                            lambda: runner.launch_detached(["systemsettings", "kcm_nightlight"])))
        cb.addWidget(button("NVIDIA SETTINGS", None, lambda: runner.launch_detached(["nvidia-settings"])))
        cb.addStretch(1)
        cp.add(cb)
        grid.addWidget(cp, 0, 1)
        self.lay.addLayout(grid)
        self.lay.addStretch(1)
        self.outputs: list[D.Output] = []
        self.on_caps()

    # ------------------------------------------------------------------
    def _clear(self, lay):
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
            elif it.layout():
                self._clear(it.layout())

    def on_caps(self):
        f = self.ctx.feature
        s = self.ctx.sysinfo
        prev = self._cur().name if self._cur() else None
        self.outputs = list(s.displays)
        self.out.blockSignals(True)
        self.out.clear()
        for o in self.outputs:
            self.out.addItem(f"{o.name}  ·  {o.current_mode.label if o.current_mode else '?'}")
        keep = next((i for i, o in enumerate(self.outputs) if o.name == prev), 0)
        self.out.setCurrentIndex(keep)
        self.out.blockSignals(False)
        self._load_output()
        res = f("resolution")
        on = bool(res and res.status.name == "OPERATIONAL" and self.outputs)
        kde = s.is_kde and s.has("kscreen")
        for w in (self.mode, self.apply_btn, self.posx, self.posy):
            w.setEnabled(on)
        for w in (self.scale, self.vrr, self.hdr, self.bright, self.icc):
            w.setEnabled(on and kde)
        self._clear(self.out_status)
        for fid in ("resolution", "vrr", "hdr", "icc"):
            if f(fid):
                self.out_status.addLayout(self.status_row(f(fid)))
                break
        if not self.outputs:
            self.out_status.addWidget(label("No outputs detected (kscreen-doctor / xrandr unavailable).", "Warn"))

        vf = f("vibrance")
        self.vp.update_feature(vf, self.status_row(vf))

        df = f("ddc")
        dok = bool(df and df.status.name == "OPERATIONAL")
        for w in (self.ddc_detect, self.ddc_apply, self.ddc_b, self.ddc_c, self.ddc):
            w.setEnabled(dok)
        self._clear(self.ddc_status)
        self.ddc_status.addLayout(self.status_row(df))

        self._clear(self.color_status)
        for fid in ("color_temp", "gamma"):
            if f(fid):
                self.color_status.addLayout(self.status_row(f(fid)))

    def _cur(self) -> D.Output | None:
        i = self.out.currentIndex()
        return self.outputs[i] if 0 <= i < len(self.outputs) else None

    def _load_output(self):
        o = self._cur()
        self.mode.clear()
        if not o:
            return
        for m in o.modes:
            self.mode.addItem(m.label, m)
        if o.current_mode:
            idx = next((i for i, m in enumerate(o.modes) if m.id == o.current_mode.id), 0)
            self.mode.setCurrentIndex(idx)
        self.scale.setValue(o.scale)
        self.vrr.setCurrentText(o.vrr_policy or "never")
        self.hdr.setChecked(bool(o.hdr))
        self.hdr.setEnabled(o.hdr is not None)
        self.bright.setValue(o.brightness if o.brightness is not None else 100)
        self.bright.setEnabled(o.brightness is not None)
        self.icc.setText(o.icc_profile or "")
        self.posx.setValue(o.pos[0])
        self.posy.setValue(o.pos[1])

    def _refresh(self):
        def job():
            if self.ctx.mock:
                return self.ctx.sysinfo.displays
            return D.kscreen_outputs() if self.ctx.sysinfo.is_kde else D.xrandr_outputs()

        def done(outs, exc):
            if outs is not None:
                self.ctx.sysinfo.displays = outs
            self.on_caps()
        run_async(job, done)

    def _browse_icc(self):
        p, _ = QFileDialog.getOpenFileName(self, "ICC profile", str(Path.home()), "ICC (*.icc *.icm)")
        if p:
            self.icc.setText(p)

    def _set(self, name, prop, value) -> str | None:
        if self.ctx.mock:
            log.info("[mock] kscreen-doctor output.%s.%s.%s", name, prop, value)
            return None
        r = D.kscreen_set(name, prop, value)
        return None if r.ok else (r.err.strip() or r.out.strip() or f"exit {r.code}")

    def _apply_output(self):
        o = self._cur()
        if not o:
            return
        m: D.Mode = self.mode.currentData()
        errs: list[str] = []
        risky = (m and o.current_mode and m.id != o.current_mode.id) or abs(self.scale.value() - o.scale) > 1e-3
        old_mode, old_scale = o.current_mode, o.scale
        if self.ctx.sysinfo.is_kde:
            ops = []
            if m and (not o.current_mode or m.id != o.current_mode.id):
                ops.append(("mode", m.id))
            if abs(self.scale.value() - o.scale) > 1e-3:
                ops.append(("scale", f"{self.scale.value():.2f}"))
            if self.vrr.currentText() != (o.vrr_policy or "never"):
                ops.append(("vrrpolicy", self.vrr.currentText()))
            if o.hdr is not None and self.hdr.isChecked() != bool(o.hdr):
                ops.append(("hdr", "enable" if self.hdr.isChecked() else "disable"))
            if o.brightness is not None:
                # always send: the cached value may be stale (KDE dimming, resume from sleep)
                ops.append(("brightness", str(self.bright.value())))
                self._remember_brightness(o.name, self.bright.value())
            icc = self.icc.text().strip()
            if icc != (o.icc_profile or "") and icc:
                ops.append(("iccprofile", icc))
            if (self.posx.value(), self.posy.value()) != o.pos:
                ops.append(("position", f"{self.posx.value()},{self.posy.value()}"))
            for prop, val in ops:
                e = self._set(o.name, prop, val)
                if e:
                    errs.append(f"{prop}: {e}")
        elif m:
            r = D.xrandr_set_mode(o.name, m)
            if not r.ok:
                errs.append(r.err)
        if errs:
            self.error("Display change failed", "\n".join(errs))
        if risky and not errs:
            dlg = CountdownDialog(self, "Keep display settings?",
                                  "Can you see this clearly? The previous mode is restored automatically.", 15)
            if dlg.exec() != QDialog.Accepted:
                if self.ctx.sysinfo.is_kde:
                    if old_mode:
                        self._set(o.name, "mode", old_mode.id)
                    self._set(o.name, "scale", f"{old_scale:.2f}")
                elif old_mode:
                    D.xrandr_set_mode(o.name, old_mode)
                self.main.toast("Display settings reverted")
        self._refresh()

    # ---------------------------------------------------------- brightness / resume
    def _save_restore_pref(self, on):
        self.ctx.settings.extra["restore_after_sleep"] = bool(on)
        self.ctx.settings.save()

    def _remember_brightness(self, name: str, value: int):
        self.ctx.settings.extra.setdefault("brightness", {})[name] = int(value)
        self.ctx.settings.save()

    def _apply_brightness(self):
        o = self._cur()
        if not o or not self.ctx.sysinfo.is_kde:
            return
        v = self.bright.value()
        self._remember_brightness(o.name, v)
        name = o.name

        def done(err, exc):
            if exc or err:
                self.error("Brightness", str(exc or err))
            else:
                o.brightness = v
                self.main.toast(f"{name} compositor brightness {v} %")
        run_async(lambda: self._set(name, "brightness", str(v)), done)

    def on_resume(self):
        """Called after sleep/hibernate. KWin and the NVIDIA driver can come back with a different
        brightness and with vibrance reset to 0; put back what the user had."""
        if not self.restore_sleep.isChecked():
            log.info("resume: restore disabled")
            return
        before = {o.name: o.brightness for o in self.outputs if o.brightness is not None}
        wanted = dict(before)
        wanted.update(self.ctx.settings.extra.get("brightness", {}))
        kde = self.ctx.sysinfo.is_kde
        mock = self.ctx.mock

        def job():
            outs = self.ctx.sysinfo.displays if mock else (D.kscreen_outputs() if kde else D.xrandr_outputs())
            fixed = []
            if kde:
                for o in outs:
                    want = wanted.get(o.name)
                    if want is not None and o.brightness != want:
                        log.info("resume: %s brightness %s -> %s", o.name, o.brightness, want)
                        if self._set(o.name, "brightness", str(want)) is None:
                            o.brightness = want
                            fixed.append(f"{o.name} {want}%")
            return outs, fixed

        def done(res, exc):
            if exc:
                log.error("resume restore failed: %s", exc)
                return
            outs, fixed = res
            if outs:
                self.ctx.sysinfo.displays = outs
            self.on_caps()
            if self.vp.rows:
                self.vp.apply()
            self.ddc.clear()          # i2c buses can be renumbered after resume; re-detect when needed
            self.main.toast("Restored after sleep: " + (", ".join(fixed) if fixed else "vibrance"))
        run_async(job, done)

    def on_show(self):
        vf = self.ctx.feature("vibrance")
        if not self.vib_detected and vf and vf.status.name == "OPERATIONAL":
            self.vib_detected = True
            self.vp.detect()

    def _ddc_detect(self):
        self.ddc_detect.setEnabled(False)

        def done(res, exc):
            self.ddc_detect.setEnabled(True)
            self.ddc.clear()
            for d in res or []:
                self.ddc.addItem(f"#{d.number} {d.model}", d.number)
            if not res:
                self.error("DDC/CI", "No DDC/CI monitors found. Enable DDC/CI in the monitor OSD, load i2c-dev "
                                     "and add your user to the i2c group.")
                return
            cur = D.ddc_get(res[0].number, 0x10)
            if cur:
                self.ddc_b.setValue(cur[0])
        run_async(D.ddc_displays, done)

    def _ddc_apply(self):
        n = self.ddc.currentData()
        if n is None:
            return
        b, c = self.ddc_b.value(), self.ddc_c.value()

        def job():
            return [D.ddc_set(n, 0x10, b), D.ddc_set(n, 0x12, c)]

        def done(res, exc):
            bad = [r.err for r in res or [] if not r.ok]
            if exc or bad:
                self.error("DDC/CI", str(exc) if exc else "\n".join(bad))
            else:
                self.main.toast("Monitor updated")
        run_async(job, done)
