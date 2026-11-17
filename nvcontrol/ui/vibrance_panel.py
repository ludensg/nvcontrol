"""Per-monitor Digital Vibrance.

Wayland: nVibrant addresses *physical GPU ports*. We detect them, show only connected ones,
guess the matching KDE output name, and offer IDENTIFY (briefly turns that monitor grey).
X11: nvidia-settings DigitalVibrance per display name.
"""
from __future__ import annotations

import logging
import shlex
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QCheckBox, QGridLayout, QHBoxLayout, QSlider, QWidget

from ..core import runner
from ..core.config import atomic_write
from ..integrations import display as D
from .async_util import run_async
from .widgets import HudPanel, button, label

log = logging.getLogger("nvcontrol.vibrance")


def autostart_path() -> Path:
    import os
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "autostart" / "nvcontrol-vibrance.desktop"


def pct(v: int) -> str:
    return f"{v:+5d}  ({(v + 1024) / 20.47:3.0f} %)"


class VibranceRow:
    def __init__(self, grid: QGridLayout, r: int, title: str, sub: str, value: int, on_release, on_identify):
        self.t = label(title, "H3")
        self.s = label(sub, "Faint", wrap=True)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(D.VIBRANCE_MIN, D.VIBRANCE_MAX)
        self.slider.setValue(value)
        self.slider.setPageStep(64)
        self.val = label(pct(value), "Mono")
        self.slider.valueChanged.connect(lambda v: self.val.setText(pct(v)))
        self.slider.sliderReleased.connect(on_release)
        self.ident = button("IDENTIFY", None, on_identify, "Turns this monitor grey for 2 seconds")
        self.reset = button("0", None, lambda: (self.slider.setValue(0), on_release()), "Default vibrance")
        self.reset.setFixedWidth(40)
        col = QWidget()
        cl = QHBoxLayout(col)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.t)
        cl.addWidget(self.s, 1)
        grid.addWidget(col, r * 2, 0, 1, 4)
        grid.addWidget(self.slider, r * 2 + 1, 0)
        grid.addWidget(self.val, r * 2 + 1, 1)
        grid.addWidget(self.reset, r * 2 + 1, 2)
        grid.addWidget(self.ident, r * 2 + 1, 3)

    def widgets(self):
        return [self.t, self.s, self.slider, self.val, self.ident, self.reset]


class VibrancePanel(HudPanel):
    def __init__(self, ctx, main, outputs_fn):
        super().__init__("Digital Vibrance", "SATURATION · PER MONITOR · DRIVER-NATIVE")
        self.ctx, self.main, self.outputs_fn = ctx, main, outputs_fn
        self.ports: list[D.VibrancePort] = []
        self.rows: dict[object, VibranceRow] = {}
        self.busy = False

        top = QHBoxLayout()
        self.detect_btn = button("DETECT MONITORS", None, self.detect)
        top.addWidget(self.detect_btn)
        top.addSpacing(12)
        top.addWidget(label("ALL", "Kicker"))
        self.master = QSlider(Qt.Horizontal)
        self.master.setRange(D.VIBRANCE_MIN, D.VIBRANCE_MAX)
        self.master_val = label(pct(0), "Mono")
        self.master.valueChanged.connect(lambda v: self.master_val.setText(pct(v)))
        self.master.sliderReleased.connect(self._set_all)
        top.addWidget(self.master, 1)
        top.addWidget(self.master_val)
        self.add(top)

        self.grid = QGridLayout()
        self.grid.setColumnStretch(0, 1)
        self.grid.setHorizontalSpacing(10)
        self.add(self.grid)
        self.info = label("Press DETECT MONITORS.", "Faint", wrap=True)
        self.add(self.info)

        bottom = QHBoxLayout()
        self.login = QCheckBox("Re-apply at login")
        self.login.setChecked(autostart_path().exists())
        self.login.toggled.connect(lambda _: self._write_autostart())
        bottom.addWidget(self.login)
        bottom.addStretch(1)
        self.reset_btn = button("RESET ALL", None, self._reset_all)
        self.apply_btn = button("APPLY", "Primary", self.apply)
        bottom.addWidget(self.reset_btn)
        bottom.addWidget(self.apply_btn)
        self.add(bottom)
        self.status = QHBoxLayout()
        self.add(self.status)

    # ------------------------------------------------------------- state
    @property
    def wayland(self) -> bool:
        return not self.ctx.sysinfo.is_x11

    def _stored(self) -> dict:
        key = "vibrance_x11" if not self.wayland else "vibrance_ports"
        return self.ctx.settings.extra.setdefault(key, {})

    def _save_values(self):
        st = self._stored()
        st.clear()
        for k, row in self.rows.items():
            st[str(k)] = row.slider.value()
        self.ctx.settings.save()

    def values(self) -> dict[int, int]:
        """Wayland: port index -> value, including disconnected ports (kept at their stored value)."""
        st = {int(k): v for k, v in self._stored().items() if str(k).lstrip("-").isdigit()}
        for k, row in self.rows.items():
            st[int(k)] = row.slider.value()
        return st

    def set_enabled(self, on: bool):
        for w in (self.detect_btn, self.master, self.apply_btn, self.reset_btn, self.login):
            w.setEnabled(on)
        for row in self.rows.values():
            for w in row.widgets():
                w.setEnabled(on)

    # ------------------------------------------------------------- nvibrant / nvidia-settings
    def _run(self, values: dict[int, int]):
        """Runs off the GUI thread."""
        if self.ctx.mock:
            vec = D.vector(values, 4)
            out = D.mock_nvibrant_output(vec)
            log.info("[mock] nvibrant %s", vec)
            return runner.Result(True, 0, out, ""), D.parse_nvibrant(out)
        return D.nvibrant_apply(values, len(self.ports))

    def detect(self):
        if self.busy:
            return
        self.busy = True
        self.detect_btn.setEnabled(False)
        if not self.wayland:
            self._build_x11()
            self.busy = False
            self.detect_btn.setEnabled(True)
            return
        stored = self.values()   # re-applies what the user had, so detection doesn't reset anything

        def done(res, exc):
            self.busy = False
            self.detect_btn.setEnabled(True)
            if exc or not res or not res[0].ok:
                err = str(exc) if exc else (res[0].err or res[0].out if res else "")
                self.info.setText("nVibrant failed — see log. " + err.strip()[:300])
                log.error("nvibrant detect failed: %s", err)
                return
            self.ports = res[1]
            D.guess_output_names(self.ports, [o.name for o in self.outputs_fn()])
            for p in self.ports:
                if p.index in stored:
                    p.value = stored[p.index]
            self._build_wayland()
        run_async(lambda: self._run(stored), done)

    def _clear_rows(self):
        for row in self.rows.values():
            for w in row.widgets():
                w.setParent(None)
                w.deleteLater()
        while self.grid.count():
            it = self.grid.takeAt(0)
            if it.widget():
                it.widget().setParent(None)
        self.rows = {}

    def _build_wayland(self):
        self._clear_rows()
        outs = {o.name: o for o in self.outputs_fn()}
        connected = [p for p in self.ports if p.connected]
        for r, p in enumerate(connected):
            o = outs.get(p.guess or "")
            sub = (f"→ {p.guess}" + (f" · {o.current_mode.label}" if o and o.current_mode else "")
                   if p.guess else "→ couldn't match a KDE output, use IDENTIFY")
            self.rows[p.index] = VibranceRow(self.grid, r, p.label, sub, p.value, self.apply,
                                             lambda _=False, i=p.index: self.identify(i))
        empty = len(self.ports) - len(connected)
        self.info.setText(
            f"{len(connected)} monitor(s) on {len(self.ports)} GPU ports ({empty} empty). "
            "Names are matched by port order. Press IDENTIFY if unsure which is which."
            if connected else "nVibrant found no connected monitors.")
        self._save_values()

    def _build_x11(self):
        self._clear_rows()
        st = self._stored()
        for r, o in enumerate(self.outputs_fn()):
            v = D.nvsettings_query("DigitalVibrance", o.name)
            v = v if v is not None else int(st.get(o.name, 0))
            self.rows[o.name] = VibranceRow(self.grid, r, o.name, o.current_mode.label if o.current_mode else "",
                                            v, self.apply, lambda _=False, n=o.name: self.identify(n))
        self.info.setText(f"{len(self.rows)} display(s) via nvidia-settings (X11).")

    def apply(self, *_):
        if not self.rows:
            self.detect()
            return
        self._save_values()
        if not self.wayland:
            errs = []
            for name, row in self.rows.items():
                r = D.nvsettings_assign("DigitalVibrance", row.slider.value(), name)
                if not r.ok:
                    errs.append(f"{name}: {r.err.strip()}")
            if errs:
                self.main.toast("Vibrance error — see log")
                log.error("nvidia-settings vibrance: %s", errs)
            else:
                self.main.toast("Vibrance applied")
            self._write_autostart()
            return
        vals = self.values()

        def done(res, exc):
            if exc or not res[0].ok:
                self.main.toast("nVibrant failed — see Settings ▸ Logs")
                return
            self.main.toast("Vibrance applied: " + ", ".join(
                f"{p.guess or p.label} {vals.get(p.index, 0):+d}" for p in self.ports if p.connected))
            self._write_autostart()
        run_async(lambda: self._run(vals), done)

    def identify(self, key):
        """Grey out one monitor for 2 s so the user can see which slider is which."""
        if not self.wayland:
            old = self.rows[key].slider.value()
            D.nvsettings_assign("DigitalVibrance", -1024, key)
            QTimer.singleShot(2000, lambda: D.nvsettings_assign("DigitalVibrance", old, key))
            return
        flash = dict(self.values())
        flash[key] = -1024
        restore = self.values()
        self.main.toast(f"Port {key} is now grey…")
        run_async(lambda: self._run(flash), lambda *_: QTimer.singleShot(
            2000, lambda: run_async(lambda: self._run(restore), lambda *_: None)))

    def _set_all(self):
        for row in self.rows.values():
            row.slider.setValue(self.master.value())
        self.apply()

    def _reset_all(self):
        self.master.setValue(0)
        self._set_all()

    def _write_autostart(self):
        if not self.login.isChecked():
            if autostart_path().exists():
                autostart_path().unlink()
                log.info("removed %s", autostart_path())
            return
        if not self.wayland:
            exe = runner.which("nvidia-settings") or "nvidia-settings"
            args = " ".join(f"-a {shlex.quote(f'[DPY:{n}]/DigitalVibrance={r.slider.value()}')}"
                            for n, r in self.rows.items())
            cmd = f"{shlex.quote(exe)} {args}"
        else:
            exe = runner.which("nvibrant") or "nvibrant"
            vec = D.vector(self.values(), len(self.ports))
            cmd = f"{shlex.quote(exe)} {' '.join(str(v) for v in vec)}"
        atomic_write(autostart_path(), "[Desktop Entry]\nType=Application\nName=NV//CONTROL vibrance\n"
                                f"Exec={cmd}\nX-KDE-autostart-phase=2\nNoDisplay=true\n")
        log.info("autostart vibrance: %s", cmd)

    def update_feature(self, feature, status_row):
        ok = bool(feature and feature.status.name == "OPERATIONAL")
        self.set_enabled(ok)
        while self.status.count():
            it = self.status.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
            elif it.layout():
                lay = it.layout()
                while lay.count():
                    x = lay.takeAt(0)
                    if x.widget():
                        x.widget().deleteLater()
        self.status.addLayout(status_row)
        return ok
