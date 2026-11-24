"""Custom-painted instrumentation widgets and small animated accents."""
from __future__ import annotations

import math
import random
from collections import deque

from PySide6.QtCore import (QEasingCurve, QEvent, QObject, QPoint, QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation,
                            Signal)
from PySide6.QtGui import (QBrush, QColor, QImage, QRegion, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QPolygonF, QRadialGradient)
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)

from ..capabilities.features import Status
from . import theme
from .theme import font, qc

RADIUS = 8


# =============================================================================== shared animation clock
class Clock(QObject):
    """One 30 fps timer for every ambient animation; stopped when animations are off."""
    tick = Signal(float)
    _inst = None

    def __init__(self):
        super().__init__()
        self.t = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._step)

    @classmethod
    def get(cls) -> "Clock":
        if cls._inst is None:
            cls._inst = Clock()
        return cls._inst

    def set_running(self, on: bool):
        (self.timer.start() if on else self.timer.stop())

    @property
    def running(self) -> bool:
        return self.timer.isActive()

    def _step(self):
        self.t += 0.033
        self.tick.emit(self.t)


def _noise_tile(size: int = 160, alpha: int = 14, seed: int = 7) -> QPixmap:
    rng = random.Random(seed)
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    for y in range(size):
        for x in range(size):
            v = rng.randint(0, 255)
            a = rng.randint(0, alpha)
            img.setPixelColor(x, y, QColor(v, v, v, a))
    return QPixmap.fromImage(img)


_NOISE: QPixmap | None = None


def noise() -> QPixmap:
    global _NOISE
    if _NOISE is None:
        _NOISE = _noise_tile()
    return _NOISE


# =============================================================================== helpers
def label(text: str, obj: str | None = None, wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if obj:
        lb.setObjectName(obj)
    if wrap:
        lb.setWordWrap(True)
    lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lb


def button(text: str, obj: str | None = None, cb=None, tip: str = "") -> QPushButton:
    from .text import sentence_case
    b = QPushButton(text if theme.is_veneco() else sentence_case(text))
    b.setProperty("orig_text", text)
    if obj:
        b.setObjectName(obj)
    if cb:
        b.clicked.connect(cb)
    if tip:
        b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    return b


def rounded(r: QRectF, rad: float = RADIUS) -> QPainterPath:
    p = QPainterPath()
    p.addRoundedRect(r, rad, rad)
    return p


# =============================================================================== backdrop
class Backdrop(QWidget):
    """Workspace background.

    Static layer (bloom, dot grid, film grain) is cached in a pixmap. On top of it an
    optional ambient layer in the spirit of the PS3 XMB: slow translucent ribbons and
    soft sparkles drifting along them. Everything stays *behind* the pages.

    Cost control: sparkles tick at ~15 fps and repaint only the small rectangles around
    themselves; the ribbons repaint their band ~5x/s (they move well under 1 px per frame).
    """

    N_SPARKS = 46

    def __init__(self, parent=None):
        super().__init__(parent)
        self.textured = True
        self.ambient = False
        self.setAttribute(Qt.WA_StyledBackground, False)
        self._cache: QPixmap | None = None
        self._cache_key = None
        self._t = 0.0
        self._frame = 0
        self._rng = random.Random(3)
        self._sparks: list[list[float]] = []
        self._sprites: dict[tuple, QPixmap] = {}
        self._occ: QRegion | None = None
        Clock.get().tick.connect(self._tick)

    # ------------------------------------------------------------ static layer
    def _static(self) -> QPixmap:
        key = (self.width(), self.height(), self.textured, theme.MODE.get("name"))
        if self._cache is not None and self._cache_key == key:
            return self._cache
        pm = QPixmap(max(1, self.width()), max(1, self.height()))
        r = QRectF(pm.rect())
        p = QPainter(pm)
        p.fillRect(r, qc("bg"))
        if not theme.is_veneco():
            g = QRadialGradient(QPointF(r.right() * 0.92, -r.height() * 0.15), r.width() * 0.75)
            g.setColorAt(0, qc("accent", 26))
            g.setColorAt(0.5, qc("accent", 6))
            g.setColorAt(1, qc("accent", 0))
            p.fillRect(r, g)
            g2 = QRadialGradient(QPointF(r.width() * 0.05, r.height() * 1.1), r.width() * 0.6)
            g2.setColorAt(0, QColor(108, 200, 218, 10))
            g2.setColorAt(1, QColor(108, 200, 218, 0))
            p.fillRect(r, g2)
            if self.textured:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(255, 255, 255, 9))
                step = 24
                for y in range(12, int(r.height()), step):
                    for x in range(12, int(r.width()), step):
                        p.drawRect(QRectF(x, y, 1, 1))
                p.drawTiledPixmap(r.toRect(), noise())
        p.end()
        self._cache, self._cache_key = pm, key
        return pm

    def invalidate(self):
        self._cache = None
        self._ribbon_pm = None
        self._sprites.clear()
        self.update()

    # ------------------------------------------------------------ ambient geometry
    def set_ambient(self, on: bool):
        self.ambient = on
        if on and not self._sparks:
            self._sparks = [self._spawn(fresh=True) for _ in range(self.N_SPARKS)]
        self.update()

    def _wave_y(self, x: float, layer: int, t: float) -> float:
        h, w = self.height(), max(1, self.width())
        cy = h * (0.60 + 0.07 * layer)
        u = x / w * math.tau
        amp = h * (0.075 - 0.015 * layer)
        return (cy + amp * math.sin(u * (0.9 + 0.25 * layer) + t * (0.11 + 0.04 * layer) + layer * 1.7)
                + amp * 0.45 * math.sin(u * (2.1 - 0.3 * layer) - t * (0.07 + 0.03 * layer) + layer))

    def _band(self) -> QRectF:
        h = self.height()
        return QRectF(0, h * 0.40, self.width(), h * 0.48)

    def _spawn(self, fresh: bool = False) -> list[float]:
        r = self._rng
        w = max(1, self.width())
        depth = r.random()
        return [r.uniform(0, w) if fresh else w + r.uniform(0, 40),   # x
                r.gauss(0, 1) * 34 * (0.5 + depth),                     # offset from ribbon
                r.choice((0, 0, 1, 2)),                                 # ribbon it follows
                r.uniform(5, 16) * (0.5 + depth),                       # speed (drifts left)
                0.8 + depth * 2.6,                                      # size
                r.uniform(0, 1) if fresh else 0.0,                      # life 0..1
                1 / r.uniform(9, 20),                                   # life rate /s
                r.uniform(0, math.tau),                                 # twinkle phase
                depth]

    def _spark_pos(self, s, t) -> QPointF:
        bob = math.sin(t * 0.6 + s[7]) * 5
        return QPointF(s[0], self._wave_y(s[0], int(s[2]), t) + s[1] + bob)

    def _spark_rect(self, s, t) -> QRectF:
        c = self._spark_pos(s, t)
        rad = s[4] * 6 + 5
        return QRectF(c.x() - rad, c.y() - rad, rad * 2, rad * 2)

    def _sprite(self, color: QColor, size: float) -> QPixmap:
        key = (color.rgba(), round(size, 1))
        pm = self._sprites.get(key)
        if pm is None:
            rad = int(size * 6 + 4)
            pm = QPixmap(rad * 2, rad * 2)
            pm.fill(Qt.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)
            g = QRadialGradient(QPointF(rad, rad), rad)
            for stop, a in ((0.0, 230), (0.12, 150), (0.3, 46), (1.0, 0)):
                c = QColor(color)
                c.setAlpha(a)
                g.setColorAt(stop, c)
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawEllipse(QPointF(rad, rad), rad, rad)
            p.setBrush(QColor(255, 255, 255, 235))
            p.drawEllipse(QPointF(rad, rad), size * 0.45, size * 0.45)
            p.end()
            if len(self._sprites) > 96:
                self._sprites.clear()
            self._sprites[key] = pm
        return pm

    # ------------------------------------------------------------ animation
    def _tick(self, t: float):
        if not self.ambient or not self.isVisible():
            return
        win = self.window()
        if win is not None and win.isMinimized():
            return
        focused = win is None or win.isActiveWindow()
        self._frame += 1
        every = 2 if focused else 4             # ~15 fps focused, ~7 fps unfocused: motion is <1 px/frame
        if self._frame % every:
            return
        dt = 0.033 * every
        old_t, self._t = self._t, t
        w = self.width()
        if self._frame % 15 == 0 or self._occ is None:
            self._occ = self._occluders()
        occ = self._occ
        dirty = QRegion()
        for s in self._sparks:
            old = self._spark_rect(s, old_t)
            s[0] -= s[3] * dt
            s[5] += s[6] * dt
            if s[5] >= 1 or s[0] < -30:
                s[:] = self._spawn()
                s[0] = self._rng.uniform(0, w)
            dirty += QRegion(old.united(self._spark_rect(s, t)).toAlignedRect())
        if self._frame % (every * 3) == 0:      # ribbons: ~5 fps, they barely move
            self._ribbon_pm = None
            dirty += QRegion(self._band().toAlignedRect())
        # Cards are ~92% opaque: whatever moves behind them is invisible, so never
        # repaint there. Only the gaps between cards get redrawn.
        dirty -= occ
        if not dirty.isEmpty():
            self.update(dirty)

    def _occluders(self) -> QRegion:
        reg = QRegion()
        for panel in self.findChildren(HudPanel):
            if panel.isVisible() and panel.width() > 40:
                vis = panel.visibleRegion()
                if not vis.isEmpty():
                    reg += vis.translated(panel.mapTo(self, QPoint(0, 0))).boundingRect().adjusted(2, 2, -2, -2)
        return reg

    # ------------------------------------------------------------ paint
    def paintEvent(self, e):
        p = QPainter(self)
        clip = QRectF(e.rect())
        p.drawPixmap(e.rect(), self._static(), e.rect())
        if not self.ambient:
            p.end()
            return
        t = self._t
        p.setRenderHint(QPainter.Antialiasing)
        band = self._band()
        if clip.intersects(band):
            pm = self._ribbons_pm()
            p.drawPixmap(band.topLeft(), pm)
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        base = qc("accent_hi")
        cool = QColor(200, 255, 170) if not theme.is_veneco() else QColor("#FFD000")
        for s in self._sparks:
            rr = self._spark_rect(s, t)
            if not rr.intersects(clip):
                continue
            life = math.sin(math.pi * min(1.0, max(0.0, s[5])))          # fade in, fade out
            tw = 0.55 + 0.45 * math.sin(t * 1.3 + s[7] * 3)
            p.setOpacity(life * tw * (0.25 + 0.55 * s[8]))
            pm = self._sprite(cool if s[8] > 0.8 else base, round(s[4], 1))
            c = rr.center()
            p.drawPixmap(QPointF(c.x() - pm.width() / 2, c.y() - pm.height() / 2), pm)
        p.end()

    def _ribbons_pm(self) -> QPixmap:
        band = self._band().toAlignedRect()
        pm = getattr(self, "_ribbon_pm", None)
        if pm is None or pm.size() != band.size():
            pm = QPixmap(max(1, band.width()), max(1, band.height()))
            pm.fill(Qt.transparent)
            rp = QPainter(pm)
            rp.setRenderHint(QPainter.Antialiasing)
            rp.translate(0, -band.top())
            self._paint_ribbons(rp, self._t, QRectF(band))
            rp.end()
            self._ribbon_pm = pm
        return pm

    def _paint_ribbons(self, p: QPainter, t: float, region: QRectF):
        w = self.width()
        x0, x1 = max(0.0, region.left() - 8), min(float(w), region.right() + 8)
        steps = max(8, int((x1 - x0) / 14))
        acc = qc("accent")
        for layer in (2, 1, 0):
            top = QPainterPath()
            bot = []
            spread = self.height() * (0.018 + 0.012 * layer)
            for i in range(steps + 1):
                x = x0 + (x1 - x0) * i / steps
                y = self._wave_y(x, layer, t)
                th = spread * (0.55 + 0.45 * math.sin(x / max(1, w) * 5.0 + t * 0.2 + layer))
                (top.moveTo if i == 0 else top.lineTo)(x, y - th)
                bot.append(QPointF(x, y + th))
            edge = QPainterPath(top)
            for pt in reversed(bot):
                top.lineTo(pt)
            top.closeSubpath()
            tint = QColor(acc).lighter(135)
            fill = QLinearGradient(0, 0, w, 0)            # fade in from the left, out at the right
            for stop, a in ((0.0, 0), (0.25, 13 - layer * 3), (0.7, 17 - layer * 4), (1.0, 2)):
                c = QColor(tint)
                c.setAlpha(max(0, a))
                fill.setColorAt(stop, c)
            p.fillPath(top, QBrush(fill))
            line = QLinearGradient(0, 0, w, 0)
            for stop, a in ((0.0, 0), (0.35, 34 - layer * 8), (0.8, 26 - layer * 6), (1.0, 0)):
                line.setColorAt(stop, QColor(255, 255, 255, max(0, a)))
            p.setPen(QPen(QBrush(line), 1.1))
            p.setBrush(Qt.NoBrush)
            p.drawPath(edge)


# =============================================================================== panels
class HudPanel(QFrame):
    """Card with a hairline border, inner highlight and an animated accent notch on hover."""

    def __init__(self, title: str = "", kicker: str = "", parent=None):
        super().__init__(parent)
        self._hover = 0.0
        self._anim = QVariantAnimation(self, duration=220, easingCurve=QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._set_hover)
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(18, 14, 18, 16)
        self._outer.setSpacing(9)
        self.title_row = QHBoxLayout()
        self.title_row.setSpacing(8)
        self.kicker = QLabel(kicker.upper()) if kicker else None
        self.title = QLabel(title)
        self.title.setObjectName("H3")
        if title or kicker:
            col = QVBoxLayout()
            col.setSpacing(1)
            if self.kicker:
                self.kicker.setObjectName("Kicker")
                col.addWidget(self.kicker)
            if title:
                col.addWidget(self.title)
            self.title_row.addLayout(col)
            self.title_row.addStretch(1)
            self._outer.addLayout(self.title_row)
        self.body = QVBoxLayout()
        self.body.setSpacing(9)
        self._outer.addLayout(self.body)
        self._outer.addStretch(1)

    def _set_hover(self, v):
        self._hover = float(v)
        self.update()

    def enterEvent(self, e):
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(1.0)
        self._anim.start()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(0.0)
        self._anim.start()
        super().leaveEvent(e)

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
        path = rounded(r)
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0, qc("panel_hi", 235))
        g.setColorAt(1, qc("panel", 225))
        p.fillPath(path, QBrush(g))
        # inner top highlight (glass edge)
        hl = QLinearGradient(r.topLeft(), r.topRight())
        hl.setColorAt(0, QColor(255, 255, 255, 0))
        hl.setColorAt(0.5, QColor(255, 255, 255, 16))
        hl.setColorAt(1, QColor(255, 255, 255, 0))
        p.setPen(QPen(QBrush(hl), 1))
        p.drawLine(QPointF(r.left() + RADIUS, r.top() + 1), QPointF(r.right() - RADIUS, r.top() + 1))
        border = QColor(qc("border"))
        hb = qc("border_hi")
        h = self._hover
        border = QColor(int(border.red() + (hb.red() - border.red()) * h),
                        int(border.green() + (hb.green() - border.green()) * h),
                        int(border.blue() + (hb.blue() - border.blue()) * h))
        p.setPen(QPen(border, 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        # accent notch: grows on hover
        w = 18 + 26 * h
        p.setPen(QPen(qc("accent"), 2, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(r.left() + 14, r.top() + 0.5), QPointF(r.left() + 14 + w, r.top() + 0.5))
        if h > 0.01:
            glow = QRadialGradient(QPointF(r.left() + 14 + w / 2, r.top()), 60)
            glow.setColorAt(0, qc("accent", int(40 * h)))
            glow.setColorAt(1, qc("accent", 0))
            p.fillPath(path, glow)
        if theme.is_veneco():
            p.setPen(QPen(QColor("#FF00FF"), 2, Qt.DashLine))
            p.drawPath(rounded(r.adjusted(3, 3, -3, -3), RADIUS - 2))


class CircuitDivider(QWidget):
    """Hairline divider with a slow light sweep travelling along it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(12)
        self.phase = random.random()
        Clock.get().tick.connect(self._tick)

    def _tick(self, t):
        if self.isVisible():
            self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, y = self.width(), 6
        g = QLinearGradient(0, y, w, y)
        g.setColorAt(0, qc("accent", 140))
        g.setColorAt(0.12, qc("border_hi"))
        g.setColorAt(1, qc("border_hi", 0))
        p.setPen(QPen(QBrush(g), 1))
        p.drawLine(QPointF(0, y), QPointF(w, y))
        p.fillRect(QRectF(0, y - 1.5, 26, 3), qc("accent"))
        clock = Clock.get()
        if clock.running:
            x = ((clock.t * 0.18 + self.phase) % 1.4) / 1.4 * (w + 200) - 100
            sg = QLinearGradient(x - 90, y, x + 90, y)
            sg.setColorAt(0, qc("accent", 0))
            sg.setColorAt(0.5, qc("accent_hi", 170))
            sg.setColorAt(1, qc("accent", 0))
            p.setPen(QPen(QBrush(sg), 1.5))
            p.drawLine(QPointF(max(0, x - 90), y), QPointF(min(w, x + 90), y))
        p.end()


# =============================================================================== status pill
class StatusBadge(QLabel):
    COLORS = {
        Status.OPERATIONAL: "accent", Status.NEEDS_CONFIG: "warn", Status.EXTERNAL: "info",
        Status.PER_GAME: "accent_hi", Status.UNSUPPORTED: "faint", Status.WINDOWS_ONLY: "faint",
    }

    def __init__(self, status: Status, parent=None):
        super().__init__(parent)
        self.set_status(status)

    def set_status(self, status: Status):
        self.status = status
        col = qc(self.COLORS.get(status, "muted"))
        r, g, b = col.red(), col.green(), col.blue()
        self.setText(f"●  {status.value}")
        self.setStyleSheet(
            f"color: rgb({r},{g},{b}); background: rgba({r},{g},{b},0.10); border: 1px solid rgba({r},{g},{b},0.28);"
            f" border-radius: 9px; padding: 2px 9px; font-family: '{theme.FONTS.get('body')}';"
            f" font-size: 7.5pt; font-weight: 600;")
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)


# =============================================================================== gauges & tiles
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
        self.setMinimumSize(160, 160)
        self._anim = QTimer(self)
        self._anim.setInterval(16)
        self._anim.timeout.connect(self._step)

    def sizeHint(self):
        return QSize(180, 180)

    def set_value(self, v: float | None, sub: str = ""):
        self.value, self.sub = v, sub
        if v is None or not self.animate:
            self._shown = v or 0.0
            self.update()
        elif not self._anim.isActive():
            self._anim.start()

    def _step(self):
        target = self.value or 0.0
        self._shown += (target - self._shown) * 0.18
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
        side = min(self.width(), self.height()) - 16
        r = QRectF((self.width() - side) / 2, (self.height() - side) / 2 + 4, side, side)
        cx, cy = r.center().x(), r.center().y()
        start, span = 225, -270
        # tick ring is static: cache it per size/theme
        key = (self.width(), self.height(), theme.MODE.get("name"))
        if getattr(self, "_ticks_key", None) != key:
            pm = QPixmap(max(1, self.width()), max(1, self.height()))
            pm.fill(Qt.transparent)
            tp = QPainter(pm)
            tp.setRenderHint(QPainter.Antialiasing)
            for i in range(55):
                a = math.radians(start + span * i / 54)
                major = i % 9 == 0
                r1, r2 = side / 2 - 1, side / 2 + (5 if major else 2)
                tp.setPen(QPen(qc("border_hi") if major else qc("border"), 1))
                tp.drawLine(QPointF(cx + r1 * math.cos(a), cy - r1 * math.sin(a)),
                            QPointF(cx + r2 * math.cos(a), cy - r2 * math.sin(a)))
            tp.end()
            self._ticks_pm, self._ticks_key = pm, key
        p.drawPixmap(0, 0, self._ticks_pm)
        inner = r.adjusted(9, 9, -9, -9)
        p.setPen(QPen(qc("border"), 6, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(inner, start * 16, span * 16)
        if self.value is not None:
            frac = max(0.0, min(1.0, self._shown / self.vmax if self.vmax else 0))
            col = self._color(self._shown)
            if frac > 0.002:
                for w, a in ((14, 26), (10, 40)):
                    gc = QColor(col)
                    gc.setAlpha(a)
                    p.setPen(QPen(gc, w, Qt.SolidLine, Qt.RoundCap))
                    p.drawArc(inner, start * 16, int(span * frac * 16))
                p.setPen(QPen(col, 6, Qt.SolidLine, Qt.RoundCap))
                p.drawArc(inner, start * 16, int(span * frac * 16))
                a = math.radians(start + span * frac)
                rr = inner.width() / 2
                tip = QPointF(cx + rr * math.cos(a), cy - rr * math.sin(a))
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(255, 255, 255, 230))
                p.drawEllipse(tip, 2.2, 2.2)
        p.setPen(qc("text"))
        p.setFont(font("head", max(15, side / 6.2), weight=theme.QFont.DemiBold))
        txt = "—" if self.value is None else f"{self.value:.0f}"
        p.drawText(QRectF(r.left(), cy - side * 0.2, r.width(), side * 0.3), Qt.AlignCenter, txt)
        p.setPen(qc("muted"))
        p.setFont(font("mono", 7.5))
        p.drawText(QRectF(r.left(), cy + side * 0.07, r.width(), 16), Qt.AlignCenter, self.unit)
        p.setPen(qc("muted"))
        size = 7.5
        f = font("body", 7.5, weight=theme.QFont.DemiBold, spacing=0.8)
        while size > 5:
            f.setPointSizeF(size)
            p.setFont(f)
            if p.fontMetrics().horizontalAdvance(self.title.upper()) <= r.width() * 0.9:
                break
            size -= 0.5
        p.drawText(QRectF(r.left() - 10, r.bottom() - side * 0.2, r.width() + 20, 16), Qt.AlignCenter,
                   self.title.upper())
        if self.sub:
            p.setPen(qc("faint"))
            p.setFont(font("mono", 7))
            p.drawText(QRectF(r.left() - 10, r.bottom() - side * 0.2 + 14, r.width() + 20, 14), Qt.AlignCenter,
                       self.sub)
        p.end()


class MetricTile(QWidget):
    def __init__(self, title: str, unit: str = "", parent=None):
        super().__init__(parent)
        self.title, self.unit = title, unit
        self.value = "—"
        self.frac: float | None = None
        self._frac_shown = 0.0
        self.state = "accent"
        self.setMinimumHeight(70)
        self.setMinimumWidth(130)
        self._anim = QVariantAnimation(self, duration=450, easingCurve=QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._set_frac)

    def _set_frac(self, v):
        self._frac_shown = float(v)
        self.update()

    def set(self, value: str, frac: float | None = None, state: str = "accent"):
        changed = value != self.value or state != self.state
        self.value, self.state = value, state
        if frac is not None and (self.frac is None or abs(frac - self.frac) > 0.003):
            self._anim.stop()
            self._anim.setStartValue(self._frac_shown)
            self._anim.setEndValue(max(0.0, min(1.0, frac)))
            self._anim.start()
        self.frac = frac
        if changed:
            self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.fillPath(rounded(r, 6), qc("bg2", 220))
        p.setPen(QPen(qc("border"), 1))
        p.drawPath(rounded(r, 6))
        p.setPen(Qt.NoPen)
        p.setBrush(qc(self.state))
        p.drawRoundedRect(QRectF(r.left() + 1, r.top() + 12, 2, r.height() - 24), 1, 1)
        p.setPen(qc("muted"))
        p.setFont(font("body", 7.5, weight=theme.QFont.DemiBold, spacing=0.7))
        p.drawText(QRectF(14, 8, r.width() - 18, 14), Qt.AlignLeft | Qt.AlignVCenter, self.title.upper())
        p.setPen(qc("text"))
        p.setFont(font("head", 16.5, weight=theme.QFont.DemiBold))
        p.drawText(QRectF(14, 22, r.width() - 18, 30), Qt.AlignLeft | Qt.AlignVCenter, self.value)
        if self.unit and self.value != "—":
            w = p.fontMetrics().horizontalAdvance(self.value)
            p.setPen(qc("faint"))
            p.setFont(font("mono", 7.5))
            p.drawText(QRectF(14 + w + 5, 26, 60, 26), Qt.AlignLeft | Qt.AlignVCenter, self.unit)
        if self.frac is not None:
            y = r.bottom() - 9
            p.setPen(Qt.NoPen)
            p.setBrush(qc("border"))
            p.drawRoundedRect(QRectF(14, y, r.width() - 28, 3), 1.5, 1.5)
            g = QLinearGradient(14, y, r.width() - 14, y)
            g.setColorAt(0, qc(self.state, 120))
            g.setColorAt(1, qc(self.state))
            p.setBrush(g)
            p.drawRoundedRect(QRectF(14, y, (r.width() - 28) * self._frac_shown, 3), 1.5, 1.5)
        p.end()


class LiveGraph(QWidget):
    """Time-series graph. series: name -> (color_key, deque)."""

    def __init__(self, title: str, unit: str, vmax: float | None = None, seconds: int = 120, parent=None):
        super().__init__(parent)
        self.title, self.unit, self.vmax = title, unit, vmax
        self.seconds = seconds
        self.series: dict[str, tuple[str, deque]] = {}
        self.setMinimumHeight(170)

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
        plot = r.adjusted(40, 30, -8, -18)
        p.setPen(QPen(qc("border"), 1, Qt.DotLine))
        for i in range(5):
            y = plot.top() + plot.height() * i / 4
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
        now = max((dq[-1][0] for _, dq in self.series.values() if dq), default=0)
        vmax = self.vmax or max((max(v for _, v in dq) for _, dq in self.series.values() if dq), default=1) * 1.15
        vmax = max(vmax, 1e-6)
        p.setFont(font("mono", 7))
        p.setPen(qc("faint"))
        for i in range(5):
            val = vmax * (4 - i) / 4
            p.drawText(QRectF(0, plot.top() + plot.height() * i / 4 - 7, 34, 14), Qt.AlignRight | Qt.AlignVCenter,
                       f"{val:.0f}")
        p.drawText(QRectF(plot.left(), plot.bottom() + 3, 60, 12), Qt.AlignLeft, f"−{self.seconds}s")
        p.drawText(QRectF(plot.right() - 40, plot.bottom() + 3, 40, 12), Qt.AlignRight, "now")
        p.setPen(qc("text"))
        p.setFont(font("head", 11, weight=theme.QFont.DemiBold))
        p.drawText(QRectF(4, 2, 300, 20), Qt.AlignLeft | Qt.AlignVCenter, self.title)
        tw = p.fontMetrics().horizontalAdvance(self.title)
        p.setPen(qc("faint"))
        p.setFont(font("mono", 7))
        p.drawText(QRectF(10 + tw, 2, 120, 20), Qt.AlignLeft | Qt.AlignVCenter, self.unit)
        lx = r.right() - 4
        p.setFont(font("mono", 7.5))
        for name, (ck, dq) in reversed(list(self.series.items())):
            txt = f"{name.lower()} {dq[-1][1]:.0f}" if dq else name.lower()
            w = p.fontMetrics().horizontalAdvance(txt) + 18
            lx -= w
            p.setPen(Qt.NoPen)
            p.setBrush(qc(ck))
            p.drawEllipse(QPointF(lx + 4, 12), 3, 3)
            p.setPen(qc("muted"))
            p.drawText(QRectF(lx + 11, 2, w, 20), Qt.AlignLeft | Qt.AlignVCenter, txt)
        for name, (ck, dq) in self.series.items():
            if len(dq) < 2:
                continue
            pts = [QPointF(plot.right() - (now - t) / self.seconds * plot.width(),
                           plot.bottom() - max(0, min(1, v / vmax)) * plot.height()) for t, v in dq]
            col = qc(ck)
            line = QPainterPath(pts[0])
            for a, b in zip(pts, pts[1:]):
                mx = (a.x() + b.x()) / 2
                line.cubicTo(QPointF(mx, a.y()), QPointF(mx, b.y()), b)
            fill = QPainterPath(line)
            fill.lineTo(QPointF(pts[-1].x(), plot.bottom()))
            fill.lineTo(QPointF(pts[0].x(), plot.bottom()))
            g = QLinearGradient(plot.topLeft(), plot.bottomLeft())
            g.setColorAt(0, qc(ck, 60))
            g.setColorAt(1, qc(ck, 0))
            p.fillPath(fill, QBrush(g))
            p.setPen(QPen(col, 1.6))
            p.setBrush(Qt.NoBrush)
            p.drawPath(line)
            halo = QRadialGradient(pts[-1], 9)
            halo.setColorAt(0, qc(ck, 120))
            halo.setColorAt(1, qc(ck, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(halo)
            p.drawEllipse(pts[-1], 9, 9)
            p.setBrush(col)
            p.drawEllipse(pts[-1], 2.6, 2.6)
        p.end()


# =============================================================================== legacy overlay (kept for API)
class _FollowParent(QObject):
    """Keeps an overlay widget sized to its parent (the parent's layout resizes it late)."""

    def __init__(self, overlay: QWidget):
        super().__init__(overlay)
        self.overlay = overlay
        overlay.parentWidget().installEventFilter(self)
        overlay.setGeometry(overlay.parentWidget().rect())

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Resize:
            self.overlay.setGeometry(obj.rect())
        return False


class ScanlineOverlay(QWidget):
    """Very faint CRT lines — optional, off by default."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.enabled_lines = False
        self._follow = _FollowParent(self)

    def set_active(self, lines: bool, animate: bool = False):
        self.enabled_lines = lines
        self.setVisible(lines)

    def paintEvent(self, e):
        if not self.enabled_lines:
            return
        p = QPainter(self)
        c = QColor(0, 0, 0, 26)
        for y in range(0, self.height(), 3):
            p.fillRect(0, y, self.width(), 1, c)
        p.end()


# =============================================================================== dialogs / rows
class CountdownDialog(QDialog):
    """'Keep these settings?' with automatic revert."""

    def __init__(self, parent, title: str, message: str, seconds: int = 20):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.total = self.remaining = seconds
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 20)
        lay.setSpacing(10)
        lay.addWidget(label(title, "H2"))
        lay.addWidget(label(message, "Muted", wrap=True))
        self.count = label("", "Warn")
        lay.addWidget(self.count)
        from PySide6.QtWidgets import QProgressBar
        self.bar = QProgressBar()
        self.bar.setRange(0, seconds * 10)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(4)
        lay.addWidget(self.bar)
        row = QHBoxLayout()
        row.addStretch(1)
        self.revert = button("Revert now", "Danger", self.reject)
        self.keep = button("Keep settings", "Primary", self.accept)
        row.addWidget(self.revert)
        row.addWidget(self.keep)
        lay.addLayout(row)
        self.ticks = seconds * 10
        self.t = QTimer(self)
        self.t.timeout.connect(self._tick)
        self.t.start(100)
        self._tick(first=True)
        self.setMinimumWidth(480)

    def _tick(self, first=False):
        if not first:
            self.ticks -= 1
        self.bar.setValue(self.ticks)
        self.count.setText(f"Reverting automatically in {math.ceil(self.ticks / 10)} s")
        if self.ticks <= 0:
            self.t.stop()
            self.reject()


class ToggleRow(QWidget):
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
