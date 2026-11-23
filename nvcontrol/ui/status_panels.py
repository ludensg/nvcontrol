"""Driver-health banner and Smooth Motion verification panel."""
from __future__ import annotations

import logging
import time

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..capabilities import smoothmotion as SM
from ..capabilities.driverhealth import DriverHealth
from ..core import runner
from .async_util import run_async
from .theme import font, qc
from .widgets import HudPanel, button, label

log = logging.getLogger("nvcontrol.status")


# ============================================================================ driver health banner
class HealthBanner(QFrame):
    """Shown above every page while the driver is unusable."""

    def __init__(self, main):
        super().__init__()
        self.main = main
        self.health: DriverHealth | None = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(22, 14, 18, 14)
        lay.setSpacing(16)
        col = QVBoxLayout()
        col.setSpacing(4)
        self.title = label("", "H3")
        self.detail = label("", None, wrap=True)
        self.fix = label("", "Muted", wrap=True)
        col.addWidget(self.title)
        col.addWidget(self.detail)
        col.addWidget(self.fix)
        col.addStretch(1)
        lay.addLayout(col, 1)
        btns = QVBoxLayout()
        self.reboot = button("Restart now", "Primary", self._reboot)
        self.copy = button("Copy details", None, self._copy)
        self.recheck = button("Check again", None, main.redetect)
        for b in (self.reboot, self.copy, self.recheck):
            btns.addWidget(b)
        btns.addStretch(1)
        lay.addLayout(btns)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.hide()

    def set_health(self, h: DriverHealth | None):
        self.health = h
        if h is None or h.ok:
            self.hide()
            return
        self.title.setText("⚠  " + h.title)
        self.detail.setText(h.detail)
        steps = "\n".join(f"{i + 1}.  {s}" for i, s in enumerate(h.fix))
        ver = f"\nKernel module: {h.kernel_version or 'not loaded'}  ·  Installed driver: {h.userspace_version or '?'}"
        self.fix.setText(steps + ver)
        self.reboot.setVisible(h.can_reboot_fix)
        self.show()
        self.update()

    def _copy(self):
        h = self.health
        if h:
            QGuiApplication.clipboard().setText(
                f"{h.title}\n{h.detail}\nkernel={h.kernel_version} userspace={h.userspace_version}\n"
                f"nvidia-smi: {h.smi_message}")
            self.main.toast("Driver details copied")

    def _reboot(self):
        from PySide6.QtWidgets import QMessageBox
        if QMessageBox.question(self, "Restart", "Restart the computer now? Save your work first.",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            log.info("user requested reboot from health banner")
            if not runner.launch_detached(["systemctl", "reboot"]):
                self.main.toast("Couldn't start the restart. Use your desktop's restart button.")

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 8, 8)
        p.fillPath(path, qc("crit", 26))
        p.setPen(QPen(qc("crit", 140), 1))
        p.drawPath(path)
        p.setPen(Qt.NoPen)
        p.setBrush(qc("crit"))
        p.drawRoundedRect(QRectF(r.left(), r.top() + 10, 3, r.height() - 20), 1.5, 1.5)
        p.end()


# ============================================================================ smooth motion panel
class CheckRow(QWidget):
    def __init__(self, check: SM.Check):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        icon = {True: ("✓", "accent"), False: ("✕", "crit"), None: ("i", "info")}[check.ok]
        ic = QLabel(icon[0])
        ic.setFixedWidth(22)
        ic.setAlignment(Qt.AlignCenter)
        c = qc(icon[1])
        ic.setStyleSheet(f"color: {c.name()}; font-weight: 700; background: rgba({c.red()},{c.green()},{c.blue()},0.13);"
                         " border-radius: 11px; min-height: 22px;")
        lay.addWidget(ic)
        t = label(check.name)
        t.setStyleSheet("font-weight: 600;")
        t.setMinimumWidth(210)
        lay.addWidget(t)
        lay.addWidget(label(check.detail, "Muted", wrap=True), 1)


class SmoothMotionPanel(HudPanel):
    """Preflight + live detection + per-game verification log."""

    def __init__(self, ctx, main, title="Smooth Motion check"):
        super().__init__(title, "IS IT WORKING?")
        self.ctx, self.main = ctx, main
        self.appid: str | None = None
        self.verdict = label("", "H2", wrap=True)
        self.add(self.verdict)
        self.reasons = label("", "Muted", wrap=True)
        self.add(self.reasons)
        self.checks_box = QVBoxLayout()
        self.checks_box.setSpacing(2)
        self.add(self.checks_box)
        self.live = label("", "Mono", wrap=True)
        self.add(self.live)
        self.logbox = label("", "Faint", wrap=True)
        self.add(self.logbox)
        r = QHBoxLayout()
        r.addStretch(1)
        r.addWidget(button("How to test", None, self._howto))
        r.addWidget(button("Check now", "Primary", self.refresh))
        self.add(r)
        self.games: list[SM.RunningGame] = []

    def set_appid(self, appid: str | None):
        self.appid = appid
        self.refresh()

    def _clear(self):
        while self.checks_box.count():
            it = self.checks_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

    def refresh(self):
        gpu, health, vk = self.ctx.gpu, self.ctx.health, self.ctx.sysinfo.vulkan_ok
        mock = self.ctx.mock
        drv = gpu.driver_version if gpu else ""

        def job():
            from ..capabilities.driverhealth import mock_health
            layers = [SM.LayerInfo(__import__("pathlib").Path("/usr/share/vulkan/implicit_layer.d/nvidia_layers.json"),
                                   "libnvidia-present.so.580.95.05")] if mock else SM.find_layers()
            checks = SM.preflight(gpu, health or mock_health(), vk, layers)
            games = SM.mock_scan() if mock else SM.scan([li.library for li in layers], drv)
            return checks, games
        run_async(job, self._show)

    def _show(self, res, exc):
        if exc or not res:
            self.verdict.setText("Couldn't check Smooth Motion (see log)")
            return
        checks, games = res
        self.games = games
        self._clear()
        for c in checks:
            self.checks_box.addWidget(CheckRow(c))
        ready = all(c.ok is not False for c in checks)
        mine = [g for g in games if self.appid is None or g.appid == self.appid]
        if mine:
            g = mine[0]
            self.verdict.setText(("●  " if g.active else "○  ") + g.verdict)
            self.verdict.setStyleSheet(f"color: {qc('accent' if g.active else 'warn').name()};")
            self.reasons.setText("\n".join("• " + r for r in g.reasons))
            self.live.setText(f"running: {g.name} (pid {g.pid}) · steam app {g.appid or '—'} · "
                              f"env {'on' if g.env_on else 'off'} · vulkan {'yes' if g.vulkan else 'no'} · "
                              f"{'DXVK/VKD3D' if g.dxvk else ('WineD3D' if g.wined3d else 'native')} · "
                              f"{'32' if g.is32 else '64'}-bit · layer "
                              f"{'loaded' if g.layer_loaded else ('unknown' if g.layer_loaded is None else 'not loaded')}")
        else:
            if ready:
                self.verdict.setText("Ready. Start a game with Smooth Motion on to confirm it's running")
                self.verdict.setStyleSheet(f"color: {qc('text').name()};")
                self.reasons.setText("NV//CONTROL watches running games and tells you whether NVIDIA's Smooth "
                                     "Motion layer actually loaded.")
            else:
                bad = next(c for c in checks if c.ok is False)
                self.verdict.setText("✕  Smooth Motion can't work right now")
                self.verdict.setStyleSheet(f"color: {qc('crit').name()};")
                self.reasons.setText(f"{bad.name}: {bad.detail}")
            self.live.setText("No running game detected." if self.appid is None
                              else "This game isn't running right now.")
        self._show_log()
        self.main.smooth_motion_status(games)

    def _show_log(self):
        if not self.appid:
            self.logbox.setText("")
            return
        lr = SM.read_log(SM.log_path(self.appid))
        if not lr.exists:
            self.logbox.setText("Verification log: none yet. Enable 'Verification log' in this game's profile, "
                                "write it to Steam and play for a few seconds.")
        elif lr.loaded:
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(lr.modified)) if lr.modified else "?"
            self.logbox.setText(f"Verification log ({when}): ✓ the NVIDIA layer loaded and wrote {lr.lines} lines."
                                + ("\n" + "\n".join(lr.highlights) if lr.highlights else ""))
        else:
            self.logbox.setText("Verification log exists but is empty: the layer did not run.")

    def _howto(self):
        self.main.info_dialog(
            "How to test Smooth Motion",
            "1. Game Profiles ▸ pick the game ▸ tick Smooth Motion (and Verification log).\n"
            "2. Close Steam completely, press Write to Steam, start Steam and the game.\n"
            "3. Come back here and press Check now while the game is running.\n\n"
            "Green = NVIDIA's VK_LAYER_NV_present layer is running inside the game.\n"
            "Motion should look noticeably smoother.\n"
            "Turn the verification log off afterwards (it writes debug output).")
