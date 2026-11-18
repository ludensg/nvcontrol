"""Draggable fan-curve editor (temperature °C → fan %)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from .theme import font, qc

T_MIN, T_MAX = 20, 100
FAILSAFE_C = 87

PRESETS = {
    "Silent": [[40, 30], [60, 38], [70, 50], [78, 70], [84, 100]],
    "Balanced": [[35, 30], [55, 42], [65, 55], [75, 75], [82, 100]],
    "Aggressive": [[30, 35], [50, 55], [60, 70], [70, 90], [76, 100]],
}


def sanitize(points: list[list[int]], fan_min: int = 0) -> list[list[int]]:
    """Force the same rules the root helper enforces (strictly rising temp, non-decreasing %)."""
    pts = sorted(([int(t), int(p)] for t, p in points), key=lambda x: x[0])
    out: list[list[int]] = []
    for t, p in pts:
        t = max(T_MIN, min(T_MAX, t))
        p = max(fan_min, min(100, p))
        if out and t <= out[-1][0]:
            t = out[-1][0] + 1
        if out and p < out[-1][1]:
            p = out[-1][1]
        out.append([min(t, T_MAX), p])
    if out and out[-1][0] >= FAILSAFE_C:
        out[-1][1] = 100
    return out


class CurveEditor(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.points: list[list[int]] = [list(p) for p in PRESETS["Balanced"]]
        self.fan_min = 30
        self.live: tuple[float, float] | None = None
        self.drag = -1
        self.setMinimumHeight(260)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.setToolTip("Drag points · double-click to add · right-click to remove")

    # --------------------------------------------------------------- geometry
    def _plot(self) -> QRectF:
        return QRectF(self.rect()).adjusted(46, 16, -16, -30)

    def _to_px(self, t: float, p: float) -> QPointF:
        r = self._plot()
        return QPointF(r.left() + (t - T_MIN) / (T_MAX - T_MIN) * r.width(), r.bottom() - p / 100 * r.height())

    def _from_px(self, pt: QPointF) -> tuple[int, int]:
        r = self._plot()
        t = T_MIN + (pt.x() - r.left()) / r.width() * (T_MAX - T_MIN)
        p = (r.bottom() - pt.y()) / r.height() * 100
        return round(t), round(p)

    def _hit(self, pos) -> int:
        for i, (t, p) in enumerate(self.points):
            if (self._to_px(t, p) - QPointF(pos)).manhattanLength() < 14:
                return i
        return -1

    # --------------------------------------------------------------- API
    def set_points(self, pts):
        self.points = sanitize(pts, self.fan_min)
        self.changed.emit()
        self.update()

    def set_live(self, temp: float | None, pct: float | None):
        self.live = (temp, pct) if temp is not None else None
        self.update()

    # --------------------------------------------------------------- mouse
    def mousePressEvent(self, e):
        i = self._hit(e.position())
        if e.button() == Qt.RightButton and i >= 0 and len(self.points) > 2:
            del self.points[i]
            self.changed.emit()
            self.update()
            return
        self.drag = i

    def mouseDoubleClickEvent(self, e):
        if len(self.points) >= 12:
            return
        t, p = self._from_px(e.position())
        self.points.append([t, p])
        self.points = sanitize(self.points, self.fan_min)
        self.changed.emit()
        self.update()

    def mouseMoveEvent(self, e):
        if self.drag < 0:
            self.setCursor(Qt.PointingHandCursor if self._hit(e.position()) >= 0 else Qt.ArrowCursor)
            return
        t, p = self._from_px(e.position())
        i = self.drag
        lo_t = self.points[i - 1][0] + 1 if i > 0 else T_MIN
        hi_t = self.points[i + 1][0] - 1 if i < len(self.points) - 1 else T_MAX
        lo_p = self.points[i - 1][1] if i > 0 else self.fan_min
        hi_p = self.points[i + 1][1] if i < len(self.points) - 1 else 100
        self.points[i] = [max(lo_t, min(hi_t, t)), max(lo_p, min(hi_p, p))]
        self.changed.emit()
        self.update()

    def mouseReleaseEvent(self, e):
        if self.drag >= 0:
            self.points = sanitize(self.points, self.fan_min)
            self.changed.emit()
            self.update()
        self.drag = -1

    # --------------------------------------------------------------- paint
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self._plot()
        p.fillRect(QRectF(self.rect()), qc("bg2"))
        # failsafe zone
        fz = QRectF(self._to_px(FAILSAFE_C, 100), self._to_px(T_MAX, 0))
        c = QColor(qc("crit"))
        c.setAlpha(28)
        p.fillRect(fz, c)
        p.setFont(font("mono", 7))
        p.setPen(qc("crit"))
        p.drawText(fz.adjusted(4, 4, 0, 0), Qt.AlignTop | Qt.AlignLeft, "FAILSAFE\n100 %")
        # grid
        p.setPen(QPen(qc("border"), 1, Qt.DotLine))
        for t in range(T_MIN, T_MAX + 1, 10):
            x = self._to_px(t, 0).x()
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
        for pct in range(0, 101, 20):
            y = self._to_px(T_MIN, pct).y()
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        p.setPen(qc("faint"))
        for t in range(T_MIN, T_MAX + 1, 10):
            p.drawText(QRectF(self._to_px(t, 0).x() - 15, r.bottom() + 4, 30, 14), Qt.AlignCenter, f"{t}°")
        for pct in range(0, 101, 20):
            p.drawText(QRectF(2, self._to_px(T_MIN, pct).y() - 7, 40, 14), Qt.AlignRight | Qt.AlignVCenter,
                       f"{pct}%")
        # minimum fan speed
        y = self._to_px(T_MIN, self.fan_min).y()
        p.setPen(QPen(qc("warn"), 1, Qt.DashLine))
        p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        # curve
        pts = [self._to_px(t, pc) for t, pc in self.points]
        path = QPainterPath(QPointF(r.left(), pts[0].y()))
        for pt in pts:
            path.lineTo(pt)
        path.lineTo(self._to_px(FAILSAFE_C, 100) if self.points[-1][0] < FAILSAFE_C else pts[-1])
        path.lineTo(QPointF(r.right(), self._to_px(0, 100).y()))
        fill = QPainterPath(path)
        fill.lineTo(r.bottomRight())
        fill.lineTo(r.bottomLeft())
        fc = QColor(qc("accent"))
        fc.setAlpha(40)
        p.fillPath(fill, QBrush(fc))
        p.setPen(QPen(qc("accent"), 2))
        p.drawPath(path)
        for i, pt in enumerate(pts):
            p.setBrush(qc("text") if i == self.drag else qc("accent"))
            p.setPen(QPen(qc("bg"), 1.5))
            p.drawRect(QRectF(pt.x() - 5, pt.y() - 5, 10, 10))
            p.setPen(qc("muted"))
            t, pc = self.points[i]
            p.drawText(QPointF(pt.x() + 8, pt.y() - 6), f"{t}° {pc}%")
        if self.live:
            t, pc = self.live
            x = self._to_px(max(T_MIN, min(T_MAX, t)), 0).x()
            p.setPen(QPen(qc("info"), 1.5))
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            p.drawText(QPointF(x + 4, r.top() + 12), f"NOW {t:.0f}°C" + (f" · {pc:.0f}%" if pc is not None else ""))
        p.end()
