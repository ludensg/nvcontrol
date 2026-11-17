from __future__ import annotations

import logging

from PySide6.QtCore import QByteArray, QEasingCurve, QPointF, QPropertyAnimation, QTimer
from PySide6.QtGui import QKeySequence, QPainter, QPen, QPolygonF, QShortcut
from PySide6.QtWidgets import (QApplication, QButtonGroup, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QMainWindow, QMessageBox, QStackedWidget, QStatusBar, QVBoxLayout, QWidget)

from .. import APP_NAME, TAGLINE
from ..core import logs
from . import theme
from .context import AppContext, TelemetryThread
from .labels import L
from .pages.dashboard import DashboardPage
from .pages.display import DisplayPage
from .pages.performance import PerformancePage
from .pages.profiles import ProfilesPage
from .pages.rtx import RtxPage
from .pages.settings import SettingsPage
from .pages.tools import ToolsPage
from .pages.tuning import TuningPage
from .veneco import KeygenDialog, Sounds, VenecoBanner, VenecoIntro
from .widgets import ScanlineOverlay, button, label

log = logging.getLogger("nvcontrol.ui")
PAGES = [DashboardPage, TuningPage, DisplayPage, RtxPage, ProfilesPage, PerformancePage, ToolsPage, SettingsPage]


class Wordmark(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(236, 56)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # emblem: chamfered square with slash
        p.setPen(QPen(theme.qc("accent"), 2))
        x, y, s = 4, 12, 30
        p.drawPolygon(QPolygonF([QPointF(x, y), QPointF(x + s - 8, y), QPointF(x + s, y + 8),
                                 QPointF(x + s, y + s), QPointF(x + 8, y + s), QPointF(x, y + s - 8)]))
        p.drawLine(QPointF(x + 9, y + s - 7), QPointF(x + s - 9, y + 7))
        p.drawLine(QPointF(x + 15, y + s - 7), QPointF(x + s - 3, y + 11))
        p.setFont(theme.font("head", 17, True, 1.5))
        p.setPen(theme.qc("text"))
        p.drawText(44, 34, "NV")
        w = p.fontMetrics().horizontalAdvance("NV")
        p.setPen(theme.qc("accent"))
        p.drawText(44 + w, 34, "//")
        w2 = p.fontMetrics().horizontalAdvance("//")
        p.setPen(theme.qc("text"))
        p.drawText(44 + w + w2, 34, "CONTROL")
        p.setFont(theme.font("mono", 6, spacing=1.2))
        p.setPen(theme.qc("muted"))
        p.drawText(45, 47, TAGLINE)
        p.end()


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(APP_NAME)
        self.resize(1440, 920)
        self.setMinimumSize(1100, 700)
        self.sounds = Sounds(ctx.settings)

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- veneco banner (hidden normally)
        self.banner = VenecoBanner(self, self.open_keygen, self.toggle_veneco)
        self.banner.hide()
        outer.addWidget(self.banner)

        # ---- top bar
        top = QWidget()
        top.setFixedHeight(64)
        top.setObjectName("TopBar")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(16, 4, 20, 4)
        tl.addWidget(Wordmark())
        tl.addStretch(1)
        self.top_gpu = label("", "H3")
        self.top_drv = QLabel()
        self.top_sess = QLabel()
        tl.addWidget(self.top_gpu)
        tl.addSpacing(16)
        tl.addWidget(self.top_drv)
        tl.addSpacing(8)
        tl.addWidget(self.top_sess)
        outer.addWidget(top)
        self.topbar = top

        body = QHBoxLayout()
        body.setSpacing(0)
        outer.addLayout(body, 1)

        # ---- nav rail
        rail = QWidget()
        rail.setFixedWidth(250)
        rail.setObjectName("Rail")
        rl = QVBoxLayout(rail)
        rl.setContentsMargins(0, 18, 0, 14)
        rl.setSpacing(2)
        self.nav = QButtonGroup(self)
        self.nav_buttons = []
        for i, cls in enumerate(PAGES):
            b = button(f"{i + 1:02d}  {L(cls.nav_key)}", "Nav")
            b.setCheckable(True)
            self.nav.addButton(b, i)
            self.nav_buttons.append(b)
            rl.addWidget(b)
        self.nav.idClicked.connect(self.show_page)
        rl.addStretch(1)
        self.rail_status = label("", "Faint", wrap=True)
        self.rail_status.setContentsMargins(16, 0, 12, 0)
        rl.addWidget(self.rail_status)
        body.addWidget(rail)
        self.rail = rail

        # ---- workspace
        self.stack = QStackedWidget()
        self.stack.setObjectName("Workspace")
        body.addWidget(self.stack, 1)
        self.pages = [cls(ctx, self) for cls in PAGES]
        for p in self.pages:
            self.stack.addWidget(p)
        self.scan = ScanlineOverlay(self.stack)

        self.setStatusBar(QStatusBar())
        self.status_poll = QLabel()
        self.statusBar().addPermanentWidget(self.status_poll)

        # ---- wiring
        ctx.caps_changed.connect(self._on_caps)
        self.telemetry = TelemetryThread(ctx)
        self.telemetry.sample.connect(self._on_sample)
        self.telemetry.start()
        QShortcut(QKeySequence("Ctrl+Alt+V"), self, activated=self.toggle_veneco)
        logs.on_crash(self._crash_dialog)

        self.nav_buttons[0].setChecked(True)
        self.apply_ui_settings()
        self._on_caps()
        if ctx.settings.window_geometry:
            self.restoreGeometry(QByteArray.fromBase64(ctx.settings.window_geometry.encode()))
        if ctx.settings.veneco_mode:
            QTimer.singleShot(300, lambda: self._set_veneco(True, intro=False))

    # ------------------------------------------------------------------ chrome
    def paintEvent(self, e):
        super().paintEvent(e)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.scan.setGeometry(self.stack.rect())

    def apply_ui_settings(self):
        s = self.ctx.settings
        self.scan.set_active(s.scanlines, s.animations)
        for p in self.pages:
            for g in getattr(p, "__dict__", {}).values():
                if hasattr(g, "animate"):
                    g.animate = s.animations
        self.status_poll.setText(f"POLL {s.poll_interval_ms} ms · {self.ctx.backend.name.upper()}"
                                 + (" · SIMULATED HARDWARE" if self.ctx.mock else ""))

    def restyle(self):
        QApplication.instance().setStyleSheet(theme.stylesheet())
        self.topbar.setStyleSheet(f"#TopBar {{ background: {theme.C['bg2']}; border-bottom: 1px solid {theme.C['border']}; }}")
        self.rail.setStyleSheet(f"#Rail {{ background: {theme.C['bg2']}; border-right: 1px solid {theme.C['border']}; }}")
        self._chips()
        for w in self.findChildren(QWidget):
            w.update()

    def _chips(self):
        g = self.ctx.gpu
        ok = theme.C["accent"]
        bad = theme.C["crit"]
        mono = theme.FONTS.get("mono")
        chip = "border:1px solid {c}; color:{c}; padding:3px 8px; font-family:'%s'; font-size:8pt; letter-spacing:1px;" % mono
        self.top_drv.setText(f"DRIVER {g.driver_version}" if g else "NO DRIVER")
        self.top_drv.setStyleSheet(chip.format(c=ok if g else bad))
        s = self.ctx.sysinfo
        self.top_sess.setText(f"{(s.session or '?').upper()} · {(s.desktop or '?').upper()}")
        self.top_sess.setStyleSheet(chip.format(c=theme.C["muted"]))
        self.top_gpu.setText(g.name.upper() if g else "NO NVIDIA GPU")

    def show_page(self, i: int):
        old = self.stack.currentIndex()
        self.stack.setCurrentIndex(i)
        self.nav_buttons[i].setChecked(True)
        page = self.pages[i]
        page.on_show()
        if self.ctx.settings.animations and old != i:
            eff = QGraphicsOpacityEffect(page)
            page.setGraphicsEffect(eff)
            a = QPropertyAnimation(eff, b"opacity", page)
            a.setDuration(180)
            a.setStartValue(0.0)
            a.setEndValue(1.0)
            a.setEasingCurve(QEasingCurve.OutCubic)
            a.finished.connect(lambda: page.setGraphicsEffect(None))
            a.start()
        self.scan.raise_()

    def toast(self, msg: str, ms: int = 6000):
        log.info("toast: %s", msg)
        self.statusBar().showMessage(msg, ms)

    # ------------------------------------------------------------------ data
    def _on_sample(self, t):
        self.ctx.last = t
        for p in self.pages:
            p.on_telemetry(t)
        if t.temp_c is not None and t.temp_c >= 90:
            # Safety warning is never replaced by joke text.
            self.statusBar().showMessage(f"⚠ GPU TEMPERATURE {t.temp_c:.0f} °C — check cooling / airflow", 5000)

    def _on_caps(self):
        self._chips()
        s = self.ctx.sysinfo
        self.rail_status.setText(
            f"{s.distro}\nkernel {s.kernel}\nhelper: {'installed' if s.helper_installed else 'missing'}\n"
            f"log: {logs.log_file()}")
        for p in self.pages:
            try:
                p.on_caps()
            except Exception:  # noqa: BLE001
                log.exception("page %s failed to refresh", type(p).__name__)

    def redetect(self):
        from .async_util import run_async
        self.toast("Re-detecting system…")
        run_async(self.ctx.detect_system, lambda r, e: self.toast("Detection failed — see log" if e else "System re-detected"))

    def request_steam_access(self):
        if self.ctx.settings.steam_access_granted:
            return
        r = QMessageBox.question(self, "Steam library access",
                                 "Allow NV//CONTROL to read your Steam library (installed games, Proton versions and "
                                 "launch options)?\n\nNothing is written to Steam unless you explicitly press WRITE "
                                 "TO STEAM for a game.", QMessageBox.Yes | QMessageBox.No)
        if r == QMessageBox.Yes:
            self.ctx.settings.steam_access_granted = True
            self.ctx.settings.save()

    def run_wizard(self):
        from .wizard import SetupWizard
        SetupWizard(self.ctx, self).exec()
        self._on_caps()

    # ------------------------------------------------------------------ veneco
    def toggle_veneco(self):
        self._set_veneco(not theme.is_veneco(), intro=True)

    def _set_veneco(self, on: bool, intro: bool):
        log.info("veneco mode %s", "ON" if on else "OFF")
        self.ctx.settings.veneco_mode = on
        self.ctx.settings.save()
        theme.set_mode("veneco" if on else "nvidia")
        self.restyle()
        for i, b in enumerate(self.nav_buttons):
            b.setText(f"{i + 1:02d}  {L(PAGES[i].nav_key)}")
        for p in self.pages:
            p.retranslate()
        self.rail.setFixedWidth(370 if on else 250)
        self.banner.setVisible(on)
        self.banner.set_running(on and self.ctx.settings.animations)
        self.setWindowTitle("GPU TURBO MEGA ULTRA 3000 — NV//CONTROL" if on else APP_NAME)
        if on and intro:
            self.sounds.play("zap")
            VenecoIntro(self, lambda: None, self.ctx.settings.animations)

    def open_keygen(self):
        KeygenDialog(self, self.sounds).exec()

    # ------------------------------------------------------------------ lifecycle
    def _crash_dialog(self, text: str):
        QMessageBox.critical(self, "Unexpected error",
                             "Something went wrong. The details were written to the log:\n"
                             f"{logs.log_file()}\n\nSettings ▸ COPY BUG REPORT puts everything on your clipboard.\n\n"
                             + text.strip().splitlines()[-1])

    def closeEvent(self, e):
        self.ctx.settings.window_geometry = bytes(self.saveGeometry().toBase64()).decode()
        self.ctx.settings.save()
        self.telemetry.stop()
        self.ctx.backend.close()
        log.info("shutdown")
        super().closeEvent(e)
