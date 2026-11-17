from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QFormLayout, QHBoxLayout, QPlainTextEdit, QSlider,
                               QSpinBox)

from ... import TAGLINE, __version__
from ...core import logs, runner
from ...core.config import atomic_write, config_dir, data_dir
from ...core.report import build_report
from ..widgets import HudPanel, button, label
from .base import Page


class SettingsPage(Page):
    nav_key = "nav.settings"
    kicker = "// 08 · APPLICATION"
    subtitle = "Interface, monitoring, logs and the things nobody asked for."

    def __init__(self, ctx, main):
        super().__init__(ctx, main)
        s = ctx.settings
        grid = self.grid(2)

        ip = HudPanel("Interface", "UI")
        f = QFormLayout()
        self.anim = QCheckBox("Animations (gauges, transitions)")
        self.anim.setChecked(s.animations)
        self.scan = QCheckBox("CRT scanlines")
        self.scan.setChecked(s.scanlines)
        self.graph = QSpinBox()
        self.graph.setRange(30, 900)
        self.graph.setSuffix(" s")
        self.graph.setValue(s.graph_seconds)
        f.addRow("", self.anim)
        f.addRow("", self.scan)
        f.addRow("Graph history", self.graph)
        ip.add(f)
        for w in (self.anim, self.scan):
            w.toggled.connect(self._save)
        self.graph.valueChanged.connect(self._save)
        grid.addWidget(ip, 0, 0)

        sp = HudPanel("Sound", "AUDIO · NEVER AUTOPLAYS")
        f2 = QFormLayout()
        self.mute = QCheckBox("Mute all sound effects")
        self.mute.setChecked(s.sound_muted)
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(s.sound_volume)
        f2.addRow("", self.mute)
        f2.addRow("Volume", self.vol)
        sp.add(f2)
        self.mute.toggled.connect(self._save)
        self.vol.valueChanged.connect(self._save)
        grid.addWidget(sp, 0, 1)

        vp = HudPanel("Modo especial", "???")
        vp.add(label("Purely cosmetic. Hardware settings and safety warnings are untouched. "
                     "Shortcut: Ctrl+Alt+V.", "Faint", wrap=True))
        self.veneco_btn = button("ACTIVAR MODO VENECO", "Primary", main.toggle_veneco)
        vp.add(self.veneco_btn)
        grid.addWidget(vp, 1, 0)

        wp = HudPanel("Setup", "WIZARD")
        wp.add(label("Re-run the first-run wizard: inspection, dependencies, feature discovery, presets.",
                     "Faint", wrap=True))
        r = QHBoxLayout()
        r.addWidget(button("RUN SETUP WIZARD", None, main.run_wizard))
        r.addWidget(button("RE-DETECT SYSTEM", None, main.redetect))
        r.addStretch(1)
        wp.add(r)
        grid.addWidget(wp, 1, 1)
        self.lay.addLayout(grid)

        lp = HudPanel("Logs & bug reports", "SUPPORT")
        lp.add(label("If something fails, press COPY BUG REPORT and paste it into a chat or issue — it contains "
                     "diagnostics plus the latest log lines (no passwords or personal files).", "Muted", wrap=True))
        lr = QHBoxLayout()
        lr.addWidget(button("COPY BUG REPORT", "Primary", self._copy_report))
        lr.addWidget(button("SAVE BUG REPORT…", None, self._save_report))
        lr.addWidget(button("OPEN LOG FOLDER", None,
                            lambda: runner.launch_detached(["xdg-open", str(logs.log_dir())])))
        lr.addWidget(button("REFRESH", None, self._show_log))
        lr.addStretch(1)
        lp.add(lr)
        lp.add(label(f"App log: {logs.log_file()}\nHelper log: {logs.HELPER_LOG}", "Mono", wrap=True))
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("Mono")
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(220)
        lp.add(self.log_view)
        self.lay.addWidget(lp)

        ap = HudPanel("About", "NV//CONTROL")
        ap.add(label(f"NV//CONTROL {__version__} — {TAGLINE}", "H3"))
        ap.add(label(f"Config: {config_dir()}\nData & backups: {data_dir()}\nBackend: {ctx.backend.name} — "
                     f"{ctx.backend.source}", "Mono", wrap=True))
        ap.add(label("Independent open-source project. Not affiliated with or endorsed by NVIDIA Corporation. "
                     "NVIDIA, GeForce, RTX, DLSS, G-SYNC and Reflex are trademarks of NVIDIA Corporation.",
                     "Faint", wrap=True))
        self.lay.addWidget(ap)
        self.lay.addStretch(1)
        self.retranslate()

    def retranslate(self):
        super().retranslate()
        from .. import theme
        self.veneco_btn.setText("VOLVER A LA NORMALIDAD" if theme.is_veneco() else "ACTIVAR MODO VENECO")

    def on_show(self):
        self._show_log()

    def _show_log(self):
        self.log_view.setPlainText(logs.tail(logs.log_file(), 200))
        self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())

    def _report(self) -> str:
        return logs.bug_report(build_report(self.ctx))

    def _copy_report(self):
        QGuiApplication.clipboard().setText(self._report())
        self.main.toast("Bug report copied to clipboard")

    def _save_report(self):
        p, _ = QFileDialog.getSaveFileName(self, "Save bug report", str(Path.home() / "nvcontrol-bugreport.md"),
                                           "Markdown (*.md);;Text (*.txt)")
        if p:
            atomic_write(p, self._report())
            self.main.toast(f"Saved {p}")

    def _save(self):
        s = self.ctx.settings
        s.animations = self.anim.isChecked()
        s.scanlines = self.scan.isChecked()
        s.graph_seconds = self.graph.value()
        s.sound_muted = self.mute.isChecked()
        s.sound_volume = self.vol.value()
        s.save()
        self.main.apply_ui_settings()
