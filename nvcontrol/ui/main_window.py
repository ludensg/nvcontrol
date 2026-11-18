from __future__ import annotations

import logging
import time

from PySide6.QtCore import QByteArray, QEasingCurve, QObject, QPointF, QPropertyAnimation, QTimer, Signal
from PySide6.QtGui import QKeySequence, QPainter, QPen, QPolygonF, QShortcut
from PySide6.QtWidgets import (QApplication, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QMainWindow,
                               QMessageBox, QPushButton, QStackedWidget, QStatusBar, QVBoxLayout, QWidget)

from .. import APP_NAME, TAGLINE
from ..core import logs
from . import theme
from .context import AppContext, TelemetryThread
from .labels import L
from .pages.dashboard import DashboardPage
from .pages.display import DisplayPage
from .pages.global_graphics import GlobalGraphicsPage
from .pages.lab import LabPage
from .pages.performance import PerformancePage
from .pages.profiles import ProfilesPage
from .pages.rtx import RtxPage
from .pages.settings import SettingsPage
from .pages.tools import ToolsPage
from .pages.tuning import TuningPage
from .veneco import KeygenDialog, Sounds, VenecoBanner, VenecoIntro
from .chrome import NavRail, TopBar
from .text import sentence_case
from .widgets import Backdrop, Clock, ScanlineOverlay, button, label

log = logging.getLogger("nvcontrol.ui")
PAGES = [DashboardPage, TuningPage, LabPage, DisplayPage, GlobalGraphicsPage, RtxPage, ProfilesPage,
         PerformancePage, ToolsPage, SettingsPage]


class ResumeWatcher(QObject):
    """Detects resume from suspend/hibernate without D-Bus.

    CLOCK_BOOTTIME keeps counting while the machine sleeps, CLOCK_MONOTONIC doesn't:
    when their difference grows, the system was asleep for that long.
    """
    resumed = Signal(float)

    def __init__(self, parent, interval_ms: int = 3000):
        super().__init__(parent)
        self.offset = self._offset()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(interval_ms)

    @staticmethod
    def _offset() -> float:
        try:
            return time.clock_gettime(time.CLOCK_BOOTTIME) - time.monotonic()
        except (AttributeError, OSError):
            return 0.0

    def _tick(self):
        now = self._offset()
        slept = now - self.offset
        self.offset = now
        if slept > 5:
            self.resumed.emit(slept)


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
        self.topbar = TopBar()
        outer.addWidget(self.topbar)

        body = QHBoxLayout()
        body.setSpacing(0)
        outer.addLayout(body, 1)

        # ---- nav rail
        self.rail = NavRail([L(cls.nav_key) for cls in PAGES])
        self.rail.selected.connect(self.show_page)
        self.nav_buttons = self.rail.buttons
        self.rail_status = label("", "Faint", wrap=True)
        self.rail_status.setContentsMargins(22, 0, 14, 0)
        self.rail.footer(self.rail_status)
        body.addWidget(self.rail)

        # ---- workspace (textured backdrop behind the pages)
        self.backdrop = Backdrop()
        bl = QVBoxLayout(self.backdrop)
        bl.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        self.stack.setObjectName("Workspace")
        bl.addWidget(self.stack)
        body.addWidget(self.backdrop, 1)
        self.pages = [cls(ctx, self) for cls in PAGES]
        for i, p in enumerate(self.pages):
            p.k.setText(f"{i + 1:02d}  ·  {p.kicker.split('·', 1)[-1].strip()}")
            self.stack.addWidget(p)
        self.scan = ScanlineOverlay(self.stack)

        self.setStatusBar(QStatusBar())
        self.status_poll = QLabel()
        self.update_btn = button("⬆ UPDATE AVAILABLE", "Primary", lambda: self.show_page(len(PAGES) - 1))
        self.update_btn.hide()
        self.statusBar().addPermanentWidget(self.update_btn)
        self.statusBar().addPermanentWidget(self.status_poll)

        # ---- wiring
        ctx.caps_changed.connect(self._on_caps)
        self.telemetry = TelemetryThread(ctx)
        self.telemetry.sample.connect(self._on_sample)
        self.telemetry.start()
        QShortcut(QKeySequence("Ctrl+Alt+V"), self, activated=self.toggle_veneco)
        self.resume = ResumeWatcher(self)
        self.resume.resumed.connect(self._on_resume)
        logs.on_crash(self._crash_dialog)

        self.rail.set_current(0)
        self.apply_ui_settings()
        self._on_caps()
        if ctx.settings.window_geometry:
            self.restoreGeometry(QByteArray.fromBase64(ctx.settings.window_geometry.encode()))
        if ctx.settings.check_updates and not ctx.mock:
            QTimer.singleShot(5000, lambda: self.pages[-1].check_updates(quiet=True))
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
        Clock.get().set_running(s.animations)
        self.rail.animate = s.animations
        self.backdrop.textured = s.extra.get("texture", True)
        self.scan.set_active(s.scanlines)
        self.backdrop.update()
        for p in self.pages:
            for g in getattr(p, "__dict__", {}).values():
                if hasattr(g, "animate"):
                    g.animate = s.animations
        self.status_poll.setText(f"poll {s.poll_interval_ms} ms  ·  {self.ctx.backend.name}"
                                 + ("  ·  simulated hardware" if self.ctx.mock else ""))

    def restyle(self):
        QApplication.instance().setStyleSheet(theme.stylesheet())
        for b in self.findChildren(QPushButton):
            orig = b.property("orig_text")
            if orig:
                b.setText(orig if theme.is_veneco() else sentence_case(orig))
        from PySide6.QtWidgets import QTabWidget
        for tw in self.findChildren(QTabWidget):
            for i in range(tw.count()):
                orig = tw.tabBar().tabData(i) or tw.tabText(i)
                tw.tabBar().setTabData(i, orig)
                tw.setTabText(i, orig if theme.is_veneco() else sentence_case(orig))
        self._chips()
        for w in self.findChildren(QWidget):
            w.update()

    def _chips(self):
        g = self.ctx.gpu
        s = self.ctx.sysinfo
        sub = "  ·  ".join(x for x in (f"driver {g.driver_version}" if g else "no driver",
                                       (s.session or "?"), (s.desktop or "?")) if x)
        self.topbar.set_info(g.name.replace("NVIDIA ", "") if g else "No NVIDIA GPU", sub.lower(), bool(g))

    def show_page(self, i: int):
        old = self.stack.currentIndex()
        self.stack.setCurrentIndex(i)
        self.rail.set_current(i)
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
        self.topbar.push(t.util_gpu, t.temp_c)
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

    def _on_resume(self, slept: float):
        log.info("system resumed after %.0f s asleep", slept)
        # give KWin and the driver a moment to bring the outputs back
        QTimer.singleShot(4000, self._after_resume)

    def _after_resume(self):
        for p in self.pages:
            fn = getattr(p, "on_resume", None)
            if fn:
                try:
                    fn()
                except Exception:  # noqa: BLE001
                    log.exception("on_resume failed in %s", type(p).__name__)

    def update_available(self, st):
        self.update_btn.setText(f"⬆ UPDATE AVAILABLE ({st.latest or st.behind})")
        self.update_btn.show()
        self.toast(f"NV//CONTROL update available: {st.behind} change(s). Settings ▸ Updates.", 10000)

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
        self.rail.set_labels([L(cls.nav_key) for cls in PAGES])
        for p in self.pages:
            p.retranslate()
        self.rail.setFixedWidth(330 if on else 236)
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
