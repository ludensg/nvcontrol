"""Window chrome: animated top bar and navigation rail."""
from __future__ import annotations

import math
import random
from collections import deque

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QAbstractButton, QSizePolicy, QVBoxLayout, QWidget

from .. import TAGLINE
from . import theme
from .theme import font, qc
from .widgets import Clock, noise

# =============================================================================== top bar
class TopBar(QWidget):
    """Wordmark, GPU identity, a live load ribbon and quiet ambient motion."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(68)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.gpu = "No NVIDIA GPU"
        self.sub = ""
        self.ok = False
        self.loads: deque = deque([0.0] * 48, maxlen=48)
        self.temp: float | None = None
        self.beat = 0.0           # flashes on every telemetry sample
        self.badge: str | None = None
        rng = random.Random(3)
        self.motes = [(rng.random(), rng.random(), 0.15 + rng.random() * 0.5, rng.random()) for _ in range(14)]
        Clock.get().tick.connect(self._tick)

    def set_info(self, gpu: str, sub: str, ok: bool):
        self.gpu, self.sub, self.ok = gpu, sub, ok
        self.update()

    def set_badge(self, text: str | None):
        if text != self.badge:
            self.badge = text
            self.update()

    def push(self, load: float | None, temp: float | None):
        self.loads.append(max(0.0, min(100.0, load or 0.0)))
        self.temp = temp
        self.beat = 1.0
        self.update()

    def _tick(self, t):
        self.beat = max(0.0, self.beat - 0.06)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        clock = Clock.get()
        t = clock.t if clock.running else 0.0
        bg = QLinearGradient(r.topLeft(), r.bottomLeft())
        bg.setColorAt(0, qc("bg2"))
        bg.setColorAt(1, qc("bg"))
        p.fillRect(r, bg)
        if not theme.is_veneco():
            # brushed diagonal texture
            p.setPen(QPen(QColor(255, 255, 255, 5), 1))
            for x in range(-80, int(r.width()) + 80, 7):
                p.drawLine(QPointF(x, r.bottom()), QPointF(x + 60, r.top()))
            p.drawTiledPixmap(r.toRect(), noise())
            # drifting light sheen
            if clock.running:
                sx = ((t * 0.045) % 1.6 - 0.3) * r.width()
                sh = QLinearGradient(sx - 240, 0, sx + 240, 0)
                sh.setColorAt(0, qc("accent", 0))
                sh.setColorAt(0.5, qc("accent", 16))
                sh.setColorAt(1, qc("accent", 0))
                p.fillRect(r, sh)
                # slow motes
                p.setPen(Qt.NoPen)
                for (x0, y0, sp, ph) in self.motes:
                    x = ((x0 + t * sp * 0.02) % 1.0) * r.width()
                    y = r.top() + 8 + (y0 * (r.height() - 16)) + math.sin(t * 0.8 + ph * 6) * 3
                    a = int(30 + 40 * (0.5 + 0.5 * math.sin(t * 1.3 + ph * 9)))
                    p.setBrush(qc("accent", a))
                    p.drawEllipse(QPointF(x, y), 1.1, 1.1)
        # bottom hairline + travelling comet
        p.setPen(QPen(qc("border"), 1))
        p.drawLine(QPointF(0, r.bottom() - 0.5), QPointF(r.right(), r.bottom() - 0.5))
        if clock.running and not theme.is_veneco():
            cx = ((t * 0.16) % 1.25) / 1.25 * (r.width() + 300) - 150
            cg = QLinearGradient(cx - 150, 0, cx + 20, 0)
            cg.setColorAt(0, qc("accent", 0))
            cg.setColorAt(0.85, qc("accent_hi", 200))
            cg.setColorAt(1, qc("accent", 0))
            p.setPen(QPen(QBrush(cg), 1.5))
            p.drawLine(QPointF(max(0, cx - 150), r.bottom() - 0.5), QPointF(min(r.right(), cx + 20), r.bottom() - 0.5))

        self._wordmark(p, QRectF(18, 0, 260, r.height()))
        # right block: load ribbon
        rib = QRectF(r.right() - 190, 16, 160, r.height() - 32)
        self._ribbon(p, rib)
        # GPU identity, right-aligned before the ribbon
        right = rib.left() - 26
        p.setFont(font("head", 13.5, weight=theme.QFont.DemiBold, spacing=0.4))
        p.setPen(qc("text"))
        p.drawText(QRectF(right - 520, 13, 520, 22), Qt.AlignRight | Qt.AlignVCenter, self.gpu)
        p.setFont(font("mono", 7.5, spacing=0.6))
        p.setPen(qc("muted"))
        p.drawText(QRectF(right - 520, 35, 506, 16), Qt.AlignRight | Qt.AlignVCenter, self.sub)
        if self.badge:
            p.setFont(font("body", 7.5, weight=theme.QFont.DemiBold, spacing=0.6))
            tw = p.fontMetrics().horizontalAdvance(self.badge) + 34
            fm = p.fontMetrics()
            gpu_w = 0
            p.save()
            p.setFont(font("head", 13.5, weight=theme.QFont.DemiBold, spacing=0.4))
            gpu_w = p.fontMetrics().horizontalAdvance(self.gpu)
            p.restore()
            bx = right - gpu_w - tw - 22
            br = QRectF(bx, 20, tw, 24)
            pulse = 0.5 + 0.5 * math.sin(t * 3.0)
            p.setPen(QPen(qc("accent", 150), 1))
            p.setBrush(qc("accent", int(22 + 18 * pulse)))
            p.drawRoundedRect(br, 12, 12)
            p.setPen(Qt.NoPen)
            p.setBrush(qc("accent_hi"))
            p.drawEllipse(QPointF(bx + 13, br.center().y()), 3 + pulse, 3 + pulse)
            p.setPen(qc("accent_hi"))
            p.drawText(QRectF(bx + 22, br.top(), tw - 26, br.height()), Qt.AlignLeft | Qt.AlignVCenter, self.badge)
            _ = fm
        # status dot (beats with telemetry)
        dot = QPointF(right - 3, 43)
        col = qc("accent") if self.ok else qc("crit")
        halo = QRadialGradient(dot, 7 + 5 * self.beat)
        halo.setColorAt(0, QColor(col.red(), col.green(), col.blue(), int(90 + 120 * self.beat)))
        halo.setColorAt(1, QColor(col.red(), col.green(), col.blue(), 0))
        p.setPen(Qt.NoPen)
        p.setBrush(halo)
        p.drawEllipse(dot, 9, 9)
        p.setBrush(col)
        p.drawEllipse(dot, 2.6, 2.6)
        p.end()

    def _wordmark(self, p: QPainter, r: QRectF):
        x, y, s = r.left(), r.center().y() - 15, 30
        path = QPainterPath()
        path.addRoundedRect(QRectF(x, y, s, s), 7, 7)
        g = QLinearGradient(x, y, x + s, y + s)
        g.setColorAt(0, qc("accent_hi"))
        g.setColorAt(1, qc("accent_dim"))
        p.fillPath(path, QBrush(g))
        p.setPen(QPen(qc("on_accent"), 3.2, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(x + 9, y + s - 8), QPointF(x + 15, y + 8))
        p.drawLine(QPointF(x + 16, y + s - 8), QPointF(x + 22, y + 8))
        p.setFont(font("head", 17, weight=theme.QFont.Bold, spacing=0.8))
        tx = x + s + 12
        for part, key in (("NV", "text"), ("//", "accent"), ("CONTROL", "text")):
            p.setPen(qc(key))
            p.drawText(QPointF(tx, r.center().y() + 3), part)
            tx += p.fontMetrics().horizontalAdvance(part)
        p.setFont(font("mono", 6.2, spacing=1.6))
        p.setPen(qc("faint"))
        p.drawText(QPointF(x + s + 13, r.center().y() + 16), TAGLINE)

    def _ribbon(self, p: QPainter, r: QRectF):
        p.setPen(Qt.NoPen)
        path = QPainterPath()
        path.addRoundedRect(r, 6, 6)
        p.fillPath(path, qc("bg", 200))
        p.setPen(QPen(qc("border"), 1))
        p.drawPath(path)
        inner = r.adjusted(8, 16, -8, -5)
        n = len(self.loads)
        bw = inner.width() / n
        for i, v in enumerate(self.loads):
            h = max(1.5, inner.height() * v / 100)
            a = int(70 + 150 * (i / n))
            col = qc("warn" if v > 95 else "accent", a)
            p.fillRect(QRectF(inner.left() + i * bw + 0.5, inner.bottom() - h, max(1.0, bw - 1.2), h), col)
        p.setFont(font("mono", 6.5, spacing=1.0))
        p.setPen(qc("muted"))
        p.drawText(QRectF(r.left() + 8, r.top() + 3, 60, 12), Qt.AlignLeft | Qt.AlignVCenter, "GPU LOAD")
        p.setPen(qc("text"))
        last = self.loads[-1] if self.loads else 0
        txt = f"{last:.0f}%" + (f"  {self.temp:.0f}°C" if self.temp is not None else "")
        p.drawText(QRectF(r.left(), r.top() + 3, r.width() - 8, 12), Qt.AlignRight | Qt.AlignVCenter, txt)


# =============================================================================== navigation
class NavButton(QAbstractButton):
    def __init__(self, number: int, text: str, parent=None):
        super().__init__(parent)
        self.number = number
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(40)
        self._hover = 0.0
        self._anim = QVariantAnimation(self, duration=160, easingCurve=QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(lambda v: (setattr(self, "_hover", float(v)), self.update()))

    def sizeHint(self):
        return QSize(220, 40)

    def _fade(self, to):
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(to)
        self._anim.start()

    def enterEvent(self, e):
        self._fade(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._fade(0.0)
        super().leaveEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(10, 2, -10, -2)
        if self.isChecked() or self._hover > 0.01:
            a = 22 if self.isChecked() else int(12 * self._hover)
            path = QPainterPath()
            path.addRoundedRect(r, 6, 6)
            g = QLinearGradient(r.topLeft(), r.topRight())
            g.setColorAt(0, qc("accent", a) if self.isChecked() else QColor(255, 255, 255, a))
            g.setColorAt(1, QColor(255, 255, 255, 0))
            p.fillPath(path, g)
        p.setFont(font("mono", 7.5))
        p.setPen(qc("accent") if self.isChecked() else qc("faint"))
        p.drawText(QRectF(r.left() + 14, r.top(), 26, r.height()), Qt.AlignLeft | Qt.AlignVCenter,
                   f"{self.number:02d}")
        veneco = theme.is_veneco()
        p.setFont(font("head" if veneco else "body", 9 if veneco else 10,
                       weight=theme.QFont.DemiBold if (self.isChecked() or veneco) else theme.QFont.Medium))
        col = qc("text") if self.isChecked() else (qc("muted") if self._hover < 0.5 else qc("text"))
        p.setPen(col)
        p.drawText(QRectF(r.left() + 44, r.top(), r.width() - 50, r.height()), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(self.text(), Qt.ElideRight, int(r.width() - 52)))
        p.end()


class NavIndicator(QWidget):
    """Glowing bar that glides to the selected nav item."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.resize(14, 40)
        self._anim = QVariantAnimation(self, duration=320, easingCurve=QEasingCurve.OutBack)
        self._anim.valueChanged.connect(lambda v: self.move(0, int(v)))

    def glide(self, y: int, animate: bool):
        if not animate or not self.isVisible():
            self.move(0, y)
            return
        self._anim.stop()
        self._anim.setStartValue(self.y())
        self._anim.setEndValue(y)
        self._anim.start()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h = self.height()
        glow = QRadialGradient(QPointF(2, h / 2), 14)
        glow.setColorAt(0, qc("accent", 120))
        glow.setColorAt(1, qc("accent", 0))
        p.fillRect(QRectF(0, 0, 14, h), glow)
        p.setPen(Qt.NoPen)
        p.setBrush(qc("accent_hi"))
        p.drawRoundedRect(QRectF(0, 9, 3, h - 18), 1.5, 1.5)
        p.end()


class NavRail(QWidget):
    selected = Signal(int)

    def __init__(self, labels: list[str], parent=None):
        super().__init__(parent)
        self.setFixedWidth(236)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 16, 0, 12)
        self.lay.setSpacing(1)
        self.buttons: list[NavButton] = []
        for i, text in enumerate(labels):
            b = NavButton(i + 1, text)
            b.clicked.connect(lambda _=False, idx=i: self.selected.emit(idx))
            self.buttons.append(b)
            self.lay.addWidget(b)
        self.lay.addStretch(1)
        self.indicator = NavIndicator(self)
        self.animate = True
        self.current = 0

    def footer(self, w: QWidget):
        self.lay.addWidget(w)

    def set_current(self, i: int):
        self.current = i
        for k, b in enumerate(self.buttons):
            b.setChecked(k == i)
        b = self.buttons[i]
        self.indicator.resize(14, b.height())
        self.indicator.glide(b.y(), self.animate)
        self.indicator.raise_()

    def set_labels(self, labels: list[str]):
        for b, t in zip(self.buttons, labels):
            b.setText(t)
            b.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.buttons:
            self.indicator.move(0, self.buttons[self.current].y())

    def showEvent(self, e):
        super().showEvent(e)
        self.indicator.move(0, self.buttons[self.current].y())

    def paintEvent(self, e):
        p = QPainter(self)
        r = QRectF(self.rect())
        g = QLinearGradient(r.topLeft(), r.topRight())
        g.setColorAt(0, qc("bg2"))
        g.setColorAt(1, qc("bg"))
        p.fillRect(r, g)
        if not theme.is_veneco():
            p.drawTiledPixmap(r.toRect(), noise())
        p.setPen(QPen(qc("border"), 1))
        p.drawLine(QPointF(r.right() - 0.5, 0), QPointF(r.right() - 0.5, r.bottom()))
        p.end()
