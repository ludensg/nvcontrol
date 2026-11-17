"""Custom-painted instrumentation widgets."""
from __future__ import annotations

import math
from collections import deque

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen,
                           QPolygonF)
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

from ..capabilities.features import Status
from . import theme
from .theme import font, qc

CUT = 12


def chamfer_path(r: QRectF, cut: float = CUT) -> QPainterPath:
    p = QPainterPath()
    p.moveTo(r.left(), r.top())
    p.lineTo(r.right() - cut, r.top())
    p.lineTo(r.right(), r.top() + cut)
    p.lineTo(r.right(), r.bottom())
    p.lineTo(r.left() + cut, r.bottom())
    p.lineTo(r.left(), r.bottom() - cut)
    p.closeSubpath()
    return p


def label(text: str, obj: str | None = None, wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if obj:
        lb.setObjectName(obj)
    if wrap:
        lb.setWordWrap(True)
    lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lb


def button(text: str, obj: str | None = None, cb=None, tip: str = "") -> QPushButton:
    b = QPushButton(text)
    if obj:
        b.setObjectName(obj)
    if cb:
        b.clicked.connect(cb)
    if tip:
        b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    return b


class HudPanel(QFrame):
    """Panel with chamfered corner, accent tick and kicker title."""

    def __init__(self, title: str = "", kicker: str = "", parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(16, 12, 16, 14)
        self._outer.setSpacing(8)
        self.title_row = QHBoxLayout()
        self.title_row.setSpacing(8)
        self.kicker = QLabel(kicker.upper()) if kicker else None
        self.title = QLabel(title)
        self.title.setObjectName("H3")
        if title or kicker:
            col = QVBoxLayout()
            col.setSpacing(0)
            if self.kicker:
                self.kicker.setObjectName("Kicker")
                col.addWidget(self.kicker)
            col.addWidget(self.title)
            self.title_row.addLayout(col)
            self.title_row.addStretch(1)
            self._outer.addLayout(self.title_row)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        self._outer.addLayout(self.body)

    def set_title(self, t: str) -> None:
        self.title.setText(t)

    def add(self, w) -> None:
        if isinstance(w, QWidget):
            self.body.addWidget(w)
        else:
            self.body.addLayout(w)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = chamfer_path(r)
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0, qc("panel_hi"))
        g.setColorAt(1, qc("panel"))
        p.fillPath(path, QBrush(g))
        p.setPen(QPen(qc("border"), 1))
        p.drawPath(path)
        # accent: top-left tick + chamfer highlight
        p.setPen(QPen(qc("accent"), 2))
        p.drawLine(QPointF(r.left(), r.top() + 1), QPointF(r.left() + 28, r.top() + 1))
        p.drawLine(QPointF(r.right() - CUT, r.top()), QPointF(r.right(), r.top() + CUT))
        p.setPen(QPen(qc("accent_dim"), 1))
        p.drawLine(QPointF(r.left() + CUT, r.bottom()), QPointF(r.left() + CUT + 40, r.bottom()))
        if theme.is_veneco():
            p.setPen(QPen(QColor("#FF00FF"), 2, Qt.DashLine))
            p.drawPath(chamfer_path(r.adjusted(3, 3, -3, -3)))


class CircuitDivider(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(10)

    def paintEvent(self, e):
        p = QPainter(self)
        w, y = self.width(), 5
        p.setPen(QPen(qc("border"), 1))
        p.drawLine(0, y, w, y)
        p.setPen(QPen(qc("accent"), 1))
        x = 0
        step = 90
        while x < w:
            p.drawLine(x, y, x + 18, y)
            p.drawLine(x + 18, y, x + 24, y - 4)
            p.drawLine(x + 24, y - 4, x + 36, y - 4)
            p.fillRect(QRectF(x + 36, y - 6, 3, 3), qc("accent"))
            x += step
        p.end()


class StatusBadge(QLabel):
    COLORS = {
        Status.OPERATIONAL: "accent", Status.NEEDS_CONFIG: "warn", Status.EXTERNAL: "info",
        Status.PER_GAME: "accent_hi", Status.UNSUPPORTED: "faint", Status.WINDOWS_ONLY: "faint",
    }

    def __init__(self, status: Status, parent=None):
        super().__init__(parent)
        self.set_status(status)

    def set_status(self, status: Status):
        col = theme.C[self.COLORS.get(status, "muted")]
        self.setText(status.value.upper())
        self.setStyleSheet(
            f"color: {col}; border: 1px solid {col}; padding: 2px 6px; font-family: '{theme.FONTS.get('mono')}';"
            f" font-size: 7.5pt; letter-spacing: 1px;")
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)


class RadialGauge(QWidget):
    def __init__(self, title: str, unit: str, vmax: float, warn: float | None = None,
                 crit: float | None = None, parent=None):
        super().__init__(parent)
        self.title, self.unit, self.vmax = title, unit, vmax
        self.warn, self.crit = warn, crit
        self.value: float | None = None
        self._shown = 0.0
        self.sub = ""
        self.animate = True
        self.setMinimumSize(150, 150)
        self._anim = QTimer(self)
        self._anim.setInterval(16)
        self._anim.timeout.connect(self._step)

    def sizeHint(self):
        return QSize(170, 170)

    def set_value(self, v: float | None, sub: str = ""):
        self.value, self.sub = v, sub
        if v is None or not self.animate:
            self._shown = v or 0.0
            self.update()
        elif not self._anim.isActive():
            self._anim.start()

    def _step(self):
        target = self.value or 0.0
        self._shown += (target - self._shown) * 0.2
        if abs(target - self._shown) < 0.05:
            self._shown = target
            self._anim.stop()
        self.update()

    def _color(self, v: float) -> QColor:
        if self.crit is not None and v >= self.crit:
            return qc("crit")
        if self.warn is not None and v >= self.warn:
            return qc("warn")
        return qc("accent")

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height()) - 14
        r = QRectF((self.width() - side) / 2, (self.height() - side) / 2 + 4, side, side)
        start, span = 225, -270
        # ticks
        p.setPen(QPen(qc("border_hi"), 1))
        cx, cy = r.center().x(), r.center().y()
        for i in range(28):
            a = math.radians(start + span * i / 27)
            r1, r2 = side / 2 + 2, side / 2 + (6 if i % 3 == 0 else 3)
            p.drawLine(QPointF(cx + r1 * math.cos(a), cy - r1 * math.sin(a)),
                       QPointF(cx + r2 * math.cos(a), cy - r2 * math.sin(a)))
        inner = r.adjusted(8, 8, -8, -8)
        p.setPen(QPen(qc("border"), 7, Qt.SolidLine, Qt.FlatCap))
        p.drawArc(inner, start * 16, span * 16)
        if self.value is not None:
            frac = max(0.0, min(1.0, self._shown / self.vmax if self.vmax else 0))
            col = self._color(self._shown)
            glow = QColor(col)
            glow.setAlpha(60)
            p.setPen(QPen(glow, 13, Qt.SolidLine, Qt.FlatCap))
            p.drawArc(inner, start * 16, int(span * frac * 16))
            p.setPen(QPen(col, 7, Qt.SolidLine, Qt.FlatCap))
            p.drawArc(inner, start * 16, int(span * frac * 16))
        # text
        p.setPen(qc("text"))
        p.setFont(font("head", max(14, int(side / 6.5)), True))
        txt = "—" if self.value is None else f"{self.value:.0f}"
        p.drawText(QRectF(r.left(), cy - side * 0.2, r.width(), side * 0.3), Qt.AlignCenter, txt)
        p.setPen(qc("muted"))
        p.setFont(font("mono", 8))
        p.drawText(QRectF(r.left(), cy + side * 0.08, r.width(), 16), Qt.AlignCenter, self.unit)
        p.setPen(qc("accent"))
        size = 7.0
        f = font("mono", 7, spacing=1.5)
        while size > 4.5:
            f.setPointSizeF(size)
            p.setFont(f)
            if p.fontMetrics().horizontalAdvance(self.title.upper()) <= r.width() * 0.92:
                break
            size -= 0.5
        p.drawText(QRectF(r.left() - 10, r.bottom() - side * 0.2, r.width() + 20, 16), Qt.AlignCenter,
                   self.title.upper())
        if self.sub:
            p.setPen(qc("faint"))
            p.drawText(QRectF(r.left(), r.bottom() - side * 0.2 + 13, r.width(), 14), Qt.AlignCenter, self.sub)
        p.end()


class MetricTile(QWidget):
    def __init__(self, title: str, unit: str = "", parent=None):
        super().__init__(parent)
        self.title, self.unit = title, unit
        self.value = "—"
        self.frac: float | None = None
        self.state = "accent"
        self.setMinimumHeight(64)
        self.setMinimumWidth(120)

    def set(self, value: str, frac: float | None = None, state: str = "accent"):
        self.value, self.frac, self.state = value, frac, state
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.fillRect(r, qc("bg2"))
        p.setPen(QPen(qc("border"), 1))
        p.drawRect(r)
        p.fillRect(QRectF(r.left(), r.top(), 2, r.height()), qc(self.state))
        p.setPen(qc("muted"))
        p.setFont(font("mono", 7, spacing=1.5))
        p.drawText(QRectF(12, 6, r.width() - 16, 14), Qt.AlignLeft | Qt.AlignVCenter, self.title.upper())
        p.setPen(qc("text"))
        p.setFont(font("head", 16, True))
        p.drawText(QRectF(12, 20, r.width() - 16, 28), Qt.AlignLeft | Qt.AlignVCenter,
                   f"{self.value}" + (f" {self.unit}" if self.unit and self.value != "—" else ""))
        if self.frac is not None:
            y = r.bottom() - 8
            p.fillRect(QRectF(12, y, r.width() - 24, 3), qc("border"))
            p.fillRect(QRectF(12, y, (r.width() - 24) * max(0, min(1, self.frac)), 3), qc(self.state))
        p.end()


class LiveGraph(QWidget):
    """Time-series graph. series: name -> (color_key, deque)."""

    def __init__(self, title: str, unit: str, vmax: float | None = None, seconds: int = 120, parent=None):
        super().__init__(parent)
        self.title, self.unit, self.vmax = title, unit, vmax
        self.seconds = seconds
        self.series: dict[str, tuple[str, deque]] = {}
        self.setMinimumHeight(150)

    def add_series(self, name: str, color_key: str):
        self.series[name] = (color_key, deque())

    def push(self, name: str, t: float, v: float | None):
        if name not in self.series or v is None:
            return
        dq = self.series[name][1]
        dq.append((t, float(v)))
        while dq and dq[0][0] < t - self.seconds:
            dq.popleft()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.fillRect(r, qc("bg2"))
        p.setPen(QPen(qc("border"), 1))
        p.drawRect(r)
        plot = r.adjusted(44, 24, -10, -18)
        # grid
        p.setPen(QPen(qc("border"), 1, Qt.DotLine))
        for i in range(5):
            y = plot.top() + plot.height() * i / 4
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
        for i in range(7):
            x = plot.left() + plot.width() * i / 6
            p.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
        now = max((dq[-1][0] for _, dq in self.series.values() if dq), default=0)
        vmax = self.vmax or max((max(v for _, v in dq) for _, dq in self.series.values() if dq), default=1) * 1.15
        vmax = max(vmax, 1e-6)
        p.setFont(font("mono", 7))
        p.setPen(qc("faint"))
        for i in range(5):
            val = vmax * (4 - i) / 4
            p.drawText(QRectF(2, plot.top() + plot.height() * i / 4 - 7, 38, 14), Qt.AlignRight | Qt.AlignVCenter,
                       f"{val:.0f}")
        p.drawText(QRectF(plot.left(), plot.bottom() + 3, 60, 12), Qt.AlignLeft, f"-{self.seconds}s")
        p.drawText(QRectF(plot.right() - 40, plot.bottom() + 3, 40, 12), Qt.AlignRight, "now")
        # title + legend
        p.setPen(qc("accent"))
        p.setFont(font("mono", 7, spacing=1.5))
        p.drawText(QRectF(10, 4, 300, 16), Qt.AlignLeft | Qt.AlignVCenter, f"{self.title.upper()}  [{self.unit}]")
        lx = r.right() - 10
        for name, (ck, dq) in reversed(list(self.series.items())):
            txt = f"{name} {dq[-1][1]:.0f}" if dq else name
            w = p.fontMetrics().horizontalAdvance(txt) + 16
            lx -= w
            p.fillRect(QRectF(lx, 10, 8, 3), qc(ck))
            p.setPen(qc("muted"))
            p.drawText(QRectF(lx + 11, 4, w, 16), Qt.AlignLeft | Qt.AlignVCenter, txt)
        # series
        for name, (ck, dq) in self.series.items():
            if len(dq) < 2:
                continue
            pts = [QPointF(plot.right() - (now - t) / self.seconds * plot.width(),
                           plot.bottom() - max(0, min(1, v / vmax)) * plot.height()) for t, v in dq]
            col = qc(ck)
            fill = QPainterPath(QPointF(pts[0].x(), plot.bottom()))
            for pt in pts:
                fill.lineTo(pt)
            fill.lineTo(QPointF(pts[-1].x(), plot.bottom()))
            g = QLinearGradient(plot.topLeft(), plot.bottomLeft())
            c1 = QColor(col)
            c1.setAlpha(70)
            c2 = QColor(col)
            c2.setAlpha(0)
            g.setColorAt(0, c1)
            g.setColorAt(1, c2)
            p.fillPath(fill, QBrush(g))
            p.setPen(QPen(col, 1.6))
            p.drawPolyline(QPolygonF(pts))
            p.setBrush(col)
            p.drawEllipse(pts[-1], 2.5, 2.5)
        p.end()


class ScanlineOverlay(QWidget):
    """Subtle CRT scanlines over the workspace. Transparent to input."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.offset = 0
        self.enabled_lines = True
        self.timer = QTimer(self)
        self.timer.setInterval(80)
        self.timer.timeout.connect(self._tick)

    def set_active(self, lines: bool, animate: bool):
        self.enabled_lines = lines
        self.setVisible(lines)
        if lines and animate:
            self.timer.start()
        else:
            self.timer.stop()
        self.update()

    def _tick(self):
        self.offset = (self.offset + 1) % 4
        self.update()

    def paintEvent(self, e):
        if not self.enabled_lines:
            return
        p = QPainter(self)
        c = QColor(0, 0, 0, 38 if not theme.is_veneco() else 25)
        for y in range(self.offset, self.height(), 4):
            p.fillRect(0, y, self.width(), 1, c)
        p.end()


class CountdownDialog(QDialog):
    """'Keep these settings?' with automatic revert."""

    def __init__(self, parent, title: str, message: str, seconds: int = 20):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.remaining = seconds
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        h = label(title.upper(), "H2")
        lay.addWidget(h)
        lay.addWidget(label(message, wrap=True))
        self.count = label("", "Warn")
        lay.addWidget(self.count)
        row = QHBoxLayout()
        row.addStretch(1)
        self.revert = button("REVERT NOW", "Danger", self.reject)
        self.keep = button("KEEP SETTINGS", "Primary", self.accept)
        row.addWidget(self.revert)
        row.addWidget(self.keep)
        lay.addLayout(row)
        self.t = QTimer(self)
        self.t.timeout.connect(self._tick)
        self.t.start(1000)
        self._tick(first=True)
        self.setMinimumWidth(460)

    def _tick(self, first=False):
        if not first:
            self.remaining -= 1
        self.count.setText(f"Reverting automatically in {self.remaining} s…")
        if self.remaining <= 0:
            self.t.stop()
            self.reject()


class ToggleRow(QWidget):
    """Label + description + right-aligned widget, disabled with reason when unsupported."""
    changed = Signal()

    def __init__(self, title: str, desc: str, widget: QWidget, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        col = QVBoxLayout()
        col.setSpacing(1)
        self.t = label(title)
        self.t.setStyleSheet("font-weight: 600;")
        self.d = label(desc, "Faint", wrap=True)
        col.addWidget(self.t)
        col.addWidget(self.d)
        lay.addLayout(col, 1)
        lay.addWidget(widget, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.widget = widget
