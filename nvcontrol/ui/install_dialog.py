"""Shows the exact pacman command, asks for confirmation, streams output."""
from __future__ import annotations

import logging

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPlainTextEdit, QVBoxLayout

from ..integrations.tools import install_command
from .widgets import button, label

log = logging.getLogger("nvcontrol.install")


class InstallDialog(QDialog):
    def __init__(self, parent, packages: list[str], descriptions: list[str], mock: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Install dependencies")
        self.setMinimumSize(680, 460)
        self.mock = mock
        self.cmd = install_command(packages)
        self.ok = False
        lay = QVBoxLayout(self)
        lay.addWidget(label("INSTALL DEPENDENCIES", "H2"))
        lay.addWidget(label("These packages come from the official Arch / CachyOS repositories:", "Muted"))
        for d in descriptions:
            lay.addWidget(label("• " + d, None, wrap=True))
        lay.addWidget(label("EXACT COMMAND (runs as root after polkit authentication)", "Kicker"))
        c = label("$ " + " ".join(self.cmd), "Mono", wrap=True)
        lay.addWidget(c)
        self.out = QPlainTextEdit()
        self.out.setObjectName("Mono")
        self.out.setReadOnly(True)
        lay.addWidget(self.out, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.close_btn = button("CLOSE", None, self.reject)
        self.run_btn = button("INSTALL", "Primary", self._run)
        row.addWidget(self.close_btn)
        row.addWidget(self.run_btn)
        lay.addLayout(row)
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.finished.connect(self._done)

    def _run(self):
        self.run_btn.setEnabled(False)
        log.info("install: %s", self.cmd)
        if self.mock:
            self.out.appendPlainText("[mock] would run: " + " ".join(self.cmd))
            self._done(0, None)
            return
        self.proc.start(self.cmd[0], self.cmd[1:])

    def _read(self):
        txt = bytes(self.proc.readAllStandardOutput()).decode(errors="replace")
        self.out.appendPlainText(txt.rstrip())
        log.debug("pacman: %s", txt.rstrip())

    def _done(self, code, _status):
        self.ok = code == 0
        msg = "✓ Installation finished." if self.ok else f"✗ pacman exited with code {code} (cancelled or failed)."
        (log.info if self.ok else log.error)("install finished code=%s", code)
        self.out.appendPlainText("\n" + msg)
        self.close_btn.setText("DONE")
