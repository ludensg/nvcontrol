from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QMessageBox, QScrollArea, QVBoxLayout,
                               QWidget)

from ...capabilities.features import Feature, Status
from ..labels import L
from ..widgets import CircuitDivider, StatusBadge, label

log = logging.getLogger("nvcontrol.ui")


class Page(QWidget):
    nav_key = ""
    kicker = ""
    subtitle = ""

    def __init__(self, ctx, main):
        super().__init__()
        self.ctx, self.main = ctx, main
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(scroll)
        inner = QWidget()
        inner.setObjectName("Workspace")
        scroll.setWidget(inner)
        self.lay = QVBoxLayout(inner)
        self.lay.setContentsMargins(34, 26, 34, 34)
        self.lay.setSpacing(16)
        head = QVBoxLayout()
        head.setSpacing(4)
        self.k = label(self.kicker, "Kicker")
        self.h = label(L(self.nav_key), "H1")
        self.sub = label(self.subtitle, "Muted", wrap=True)
        head.addWidget(self.k)
        head.addWidget(self.h)
        head.addWidget(self.sub)
        self.lay.addLayout(head)
        self.lay.addWidget(CircuitDivider())

    def retranslate(self):
        self.h.setText(L(self.nav_key))

    def on_telemetry(self, t):
        pass

    def on_caps(self):
        pass

    def on_show(self):
        pass

    # helpers ------------------------------------------------------------
    def grid(self, cols: int = 2) -> QGridLayout:
        g = QGridLayout()
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(14)
        for c in range(cols):
            g.setColumnStretch(c, 1)
        return g

    def info(self, title: str, text: str):
        QMessageBox.information(self, title, text)

    def error(self, title: str, text: str):
        log.error("%s: %s", title, text)
        QMessageBox.warning(self, title, f"{text}\n\nDetails are in the log (Settings ▸ Logs).")

    def confirm(self, title: str, text: str) -> bool:
        return QMessageBox.question(self, title, text, QMessageBox.Yes | QMessageBox.No,
                                    QMessageBox.No) == QMessageBox.Yes

    def status_row(self, f: Feature | None) -> QHBoxLayout:
        row = QHBoxLayout()
        if f is None:
            return row
        row.addWidget(StatusBadge(f.status))
        txt = f.mechanism + (f" — {f.detail}" if f.detail else "")
        lb = label(txt, "Faint", wrap=True)
        row.addWidget(lb, 1)
        return row


def usable(f: Feature | None) -> bool:
    return bool(f and f.status == Status.OPERATIONAL)
