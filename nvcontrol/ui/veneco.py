"""ULTRA VENECO KEYGEN MODE — purely visual/audio. Touches no hardware, no settings, no licensing.

All artwork is drawn procedurally here and all sounds are synthesized at runtime
(original square-wave chiptune), so nothing copyrighted is bundled.
"""
from __future__ import annotations

import logging
import math
import random
import struct
import wave
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, QUrl
from PySide6.QtGui import (QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
                           QPolygonF, QRadialGradient)
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..core.config import cache_dir
from . import theme

log = logging.getLogger("nvcontrol.veneco")

YELLOW, BLUE, RED = QColor("#FFCC00"), QColor("#00247D"), QColor("#CF142B")
NEON, PURPLE, MAGENTA = QColor("#39FF14"), QColor("#7A00FF"), QColor("#FF00FF")

BOOT_LINES = [
    "INICIANDO SISTEMA DE POTENCIA...",
    "CALIBRANDO LOS CABALLOS DE FUERZA...",
    "CONTACTANDO SATÉLITE SIMÓN BOLÍVAR...",
    "ACTIVANDO EL PODER DEL SALTO ÁNGEL...",
    "MAMAGÜEVO ENGINE v4.20 CARGADO",
    "POTENCIA VENEZOLANA: 999999%",
]

# Original 15x11 pixel eagle (1 = feather, 2 = beak/eye)
EAGLE = [
    "1.............1",
    "11...........11",
    "111...111...111",
    "1111.11211.1111",
    ".111111111111.",
    "..11111111111..",
    "....1111111....",
    ".....11111.....",
    "......111......",
    ".....1.1.1.....",
    "....1..1..1....",
]


# --------------------------------------------------------------------------- drawing helpers
def draw_flag(p: QPainter, r: QRectF, phase: float):
    """Venezuelan tricolor with 8-star arc, 'spinning' around its vertical axis."""
    sx = math.cos(phase)
    w = max(2.0, abs(sx) * r.width())
    rr = QRectF(r.center().x() - w / 2, r.top(), w, r.height())
    h3 = r.height() / 3
    dim = 1.0 if sx >= 0 else 0.65
    for i, c in enumerate((YELLOW, BLUE, RED)):
        cc = QColor(int(c.red() * dim), int(c.green() * dim), int(c.blue() * dim))
        p.fillRect(QRectF(rr.left(), rr.top() + i * h3, rr.width(), h3 + 0.5), cc)
    if abs(sx) > 0.15:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("white"))
        cx, cy = rr.center().x(), rr.top() + h3 * 1.75
        rad = h3 * 0.9
        for k in range(8):
            a = math.radians(160 - k * (140 / 7))
            x = cx + math.cos(a) * rad * (rr.width() / r.width())
            y = cy - math.sin(a) * rad * 0.75
            star(p, QPointF(x, y), max(1.5, h3 * 0.12 * abs(sx)))
    p.setPen(QPen(QColor(255, 255, 255, 120), 1))
    p.setBrush(Qt.NoBrush)
    p.drawRect(rr)


def star(p: QPainter, c: QPointF, r: float):
    pts = []
    for i in range(10):
        a = math.pi / 2 + i * math.pi / 5
        rad = r if i % 2 == 0 else r * 0.45
        pts.append(QPointF(c.x() + math.cos(a) * rad, c.y() - math.sin(a) * rad))
    p.drawPolygon(QPolygonF(pts))


def draw_eagle(p: QPainter, origin: QPointF, px: float, flap: float):
    for y, row in enumerate(EAGLE):
        for x, ch in enumerate(row):
            if ch == ".":
                continue
            dy = math.sin(flap) * 2 * abs(x - 7) / 7 if ch == "1" else 0
            col = QColor("#FFCC00") if ch == "2" else QColor("#5A3A1A" if y > 6 else "#3B2410")
            p.fillRect(QRectF(origin.x() + x * px, origin.y() + y * px - dy, px, px), col)


def draw_flames(p: QPainter, r: QRectF, t: float):
    path = QPainterPath(QPointF(r.left(), r.bottom()))
    n = 40
    for i in range(n + 1):
        x = r.left() + r.width() * i / n
        hgt = r.height() * (0.45 + 0.35 * math.sin(i * 1.7 + t * 6) + 0.2 * math.sin(i * 0.6 - t * 9))
        path.lineTo(QPointF(x, r.bottom() - max(4, hgt)))
    path.lineTo(QPointF(r.right(), r.bottom()))
    g = QLinearGradient(r.bottomLeft(), r.topLeft())
    g.setColorAt(0, QColor("#FF00FF"))
    g.setColorAt(0.4, QColor("#7A00FF"))
    g.setColorAt(1, QColor(122, 0, 255, 0))
    p.fillPath(path, QBrush(g))


def draw_lightning(p: QPainter, a: QPointF, b: QPointF, rng: random.Random):
    pts = [a]
    for i in range(1, 9):
        f = i / 9
        pts.append(QPointF(a.x() + (b.x() - a.x()) * f + rng.uniform(-18, 18), a.y() + (b.y() - a.y()) * f))
    pts.append(b)
    for w, c in ((9, QColor(0, 229, 255, 60)), (4, QColor(180, 255, 255, 160)), (1.5, QColor("white"))):
        p.setPen(QPen(c, w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPolyline(QPolygonF(pts))


def draw_flare(p: QPainter, c: QPointF, r: float):
    for k, (rad, alpha) in enumerate(((r, 120), (r * 0.4, 200), (r * 2.4, 40))):
        g = QRadialGradient(c, rad)
        g.setColorAt(0, QColor(255, 255, 255, alpha))
        g.setColorAt(0.3, QColor(255, 220, 120, alpha // 2))
        g.setColorAt(1, QColor(255, 0, 255, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(c, rad, rad)
    p.setPen(QPen(QColor(255, 255, 255, 140), 1.5))
    p.drawLine(QPointF(c.x() - r * 3, c.y()), QPointF(c.x() + r * 3, c.y()))


def chrome_text(p: QPainter, rect: QRectF, text: str, size: int, t: float = 0.0):
    f = QFont(theme.FONTS.get("veneco", "Sans Serif"), size)
    f.setBold(True)
    path = QPainterPath()
    path.addText(0, 0, f, text)
    br = path.boundingRect()
    scale = min(1.0, (rect.width() - 20) / max(1, br.width()))
    p.save()
    p.translate(rect.center().x() - br.width() * scale / 2 - br.left() * scale,
                rect.center().y() + br.height() * scale / 3)
    p.scale(scale, scale)
    for d in range(7, 0, -1):            # 3D extrusion
        p.save()
        p.translate(d, d)
        p.fillPath(path, QColor(40 + d * 10, 0, 80 + d * 15))
        p.restore()
    g = QLinearGradient(0, br.top(), 0, br.bottom())
    g.setColorAt(0, QColor("#FFFFFF"))
    g.setColorAt(0.45, QColor("#B6FF00"))
    g.setColorAt(0.5, QColor("#1E8A0A"))
    g.setColorAt(1, QColor("#EFFFD0"))
    p.fillPath(path, QBrush(g))
    p.setPen(QPen(QColor(255, 0, 255, int(160 + 90 * math.sin(t * 5))), 2.5))
    p.drawPath(path)
    p.restore()


# --------------------------------------------------------------------------- sound
class Sounds:
    def __init__(self, settings):
        self.settings = settings
        self.effects = {}
        try:
            from PySide6.QtMultimedia import QSoundEffect
            self._cls = QSoundEffect
        except Exception:  # noqa: BLE001 - QtMultimedia optional
            self._cls = None
            log.info("QtMultimedia unavailable; Veneco sounds disabled")

    @staticmethod
    def _synth(path: Path, notes: list[tuple[float, float]], square: bool = True, vol: float = 0.35):
        rate = 22050
        frames = bytearray()
        for freq, dur in notes:
            n = int(rate * dur)
            for i in range(n):
                env = min(1.0, i / 200) * max(0.0, 1 - i / n) ** 0.5
                if freq <= 0:
                    s = 0.0
                elif square:
                    s = 1.0 if math.sin(2 * math.pi * freq * i / rate) >= 0 else -1.0
                else:
                    s = math.sin(2 * math.pi * freq * i / rate)
                frames += struct.pack("<h", int(s * env * vol * 32767))
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(bytes(frames))

    def _ensure(self, name: str) -> Path:
        p = cache_dir() / f"veneco-{name}.wav"
        if p.exists():
            return p
        A = 440.0
        def nt(semi):
            return A * 2 ** (semi / 12)
        if name == "keygen":     # original arpeggio loop, ~3 s
            seq = []
            for root in (0, -4, 3, -2):
                for k in (0, 7, 12, 16, 12, 7):
                    seq.append((nt(root + k), 0.085))
            self._synth(p, seq)
        elif name == "zap":
            self._synth(p, [(nt(24 - i), 0.012) for i in range(40)])
        elif name == "tada":
            self._synth(p, [(nt(0), 0.1), (nt(4), 0.1), (nt(7), 0.1), (nt(12), 0.35)], square=False)
        return p

    def play(self, name: str):
        if self._cls is None or self.settings.sound_muted:
            return
        try:
            eff = self.effects.get(name)
            if eff is None:
                eff = self._cls()
                eff.setSource(QUrl.fromLocalFile(str(self._ensure(name))))
                self.effects[name] = eff
            eff.setVolume(max(0.0, min(1.0, self.settings.sound_volume / 100)))
            eff.play()
        except Exception:  # noqa: BLE001
            log.exception("sound failed")


# --------------------------------------------------------------------------- intro overlay
class VenecoIntro(QWidget):
    """Full-window theatrical intro. Click or Esc to skip. Does nothing real."""

    def __init__(self, parent, on_done, animate: bool = True):
        super().__init__(parent)
        self.on_done = on_done
        self.t = 0.0
        self.total = 7.0 if animate else 0.1
        self.rng = random.Random(7)
        self.setGeometry(parent.rect())
        self.setFocusPolicy(Qt.StrongFocus)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)
        self.show()
        self.raise_()
        self.setFocus()

    def _tick(self):
        self.t += 0.033
        if self.t >= self.total:
            self.finish()
        self.update()

    def finish(self):
        self.timer.stop()
        self.hide()
        self.deleteLater()
        self.on_done()

    def mousePressEvent(self, e):
        self.finish()

    def keyPressEvent(self, e):
        self.finish()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0, QColor("#0A0018"))
        g.setColorAt(0.5, QColor("#3A0075"))
        g.setColorAt(1, QColor("#000000"))
        p.fillRect(r, g)
        t = self.t
        # rotating rays
        p.save()
        p.translate(r.center())
        p.rotate(t * 40)
        for i in range(16):
            p.rotate(360 / 16)
            col = QColor(YELLOW if i % 3 == 0 else (BLUE if i % 3 == 1 else RED))
            col.setAlpha(45)
            p.setBrush(col)
            p.setPen(Qt.NoPen)
            p.drawPolygon(QPolygonF([QPointF(0, 0), QPointF(-60, -2000), QPointF(60, -2000)]))
        p.restore()
        # explosions
        for k in range(5):
            ph = (t * 1.3 + k * 0.37) % 1.0
            c = QPointF(r.width() * ((k * 0.23 + 0.1) % 1), r.height() * ((k * 0.41 + 0.2) % 1))
            rg = QRadialGradient(c, 140 * ph)
            rg.setColorAt(0, QColor(255, 255, 200, int(220 * (1 - ph))))
            rg.setColorAt(0.5, QColor(255, 120, 0, int(160 * (1 - ph))))
            rg.setColorAt(1, QColor(255, 0, 255, 0))
            p.setBrush(rg)
            p.drawEllipse(c, 140 * ph, 140 * ph)
        if int(t * 10) % 7 == 0:
            draw_lightning(p, QPointF(self.rng.uniform(0, r.width()), 0),
                           QPointF(self.rng.uniform(0, r.width()), r.height() * 0.6), self.rng)
        # flags + eagle
        fw = min(160.0, r.width() / 7)
        draw_flag(p, QRectF(40, 40, fw, fw * 0.66), t * 3)
        draw_flag(p, QRectF(r.width() - 40 - fw, 40, fw, fw * 0.66), -t * 3)
        draw_eagle(p, QPointF(r.center().x() - 45, 30), 6, t * 8)
        # titles
        if t < 2.3:
            chrome_text(p, QRectF(0, r.height() * 0.28, r.width(), 120),
                        "BIENVENIDO AL SISTEMA MÁS ARRECHO DE VENEZUELA", 46, t)
        else:
            chrome_text(p, QRectF(0, r.height() * 0.22, r.width(), 140), "GPU TURBO MEGA ULTRA 3000", 64, t)
            p.setPen(QColor("#FFCC00"))
            f = QFont(theme.FONTS.get("veneco", "Sans"), 15)
            f.setItalic(True)
            p.setFont(f)
            p.drawText(QRectF(0, r.height() * 0.22 + 120, r.width(), 30), Qt.AlignCenter,
                       "Desarrollado en Maracaibo con tecnología de la NASA.")
            # boot lines
            p.setFont(QFont(theme.FONTS.get("mono", "Monospace"), 12, QFont.Bold))
            shown = int((t - 2.3) / 0.6) + 1
            y = r.height() * 0.22 + 175
            for i, line in enumerate(BOOT_LINES[:shown]):
                p.setPen(NEON if i < shown - 1 else QColor("white"))
                tick = " [OK]" if i < shown - 1 else ("_" if int(t * 4) % 2 else "")
                p.drawText(QRectF(r.width() * 0.25, y + i * 24, r.width() * 0.6, 22), Qt.AlignLeft, "> " + line + tick)
            # progress
            frac = min(1.0, (t - 2.3) / (self.total - 2.6))
            bar = QRectF(r.width() * 0.25, y + 6 * 24 + 12, r.width() * 0.5, 22)
            p.setPen(QPen(YELLOW, 2))
            p.setBrush(QColor(0, 0, 0, 160))
            p.drawRect(bar)
            bg = QLinearGradient(bar.topLeft(), bar.topRight())
            bg.setColorAt(0, YELLOW)
            bg.setColorAt(0.5, BLUE)
            bg.setColorAt(1, RED)
            p.fillRect(bar.adjusted(3, 3, -3 - (bar.width() - 6) * (1 - frac), -3), bg)
            p.setPen(QColor("white"))
            p.drawText(bar, Qt.AlignCenter, f"{int(999999 * frac**3)}%")
        draw_flare(p, QPointF(r.width() * (0.1 + 0.8 * ((t * 0.25) % 1)), r.height() * 0.15), 30)
        draw_flames(p, QRectF(0, r.height() - 110, r.width(), 110), t)
        p.setPen(QColor(255, 255, 255, 140))
        p.setFont(QFont(theme.FONTS.get("mono", "Monospace"), 8))
        p.drawText(r.adjusted(0, 0, -12, -8), Qt.AlignBottom | Qt.AlignRight,
                   "click para saltar · solo es un chiste visual, no se toca el hardware")
        p.end()


# --------------------------------------------------------------------------- persistent banner
class VenecoBanner(QWidget):
    MARQUEE = ("★ GPU TURBO MEGA ULTRA 3000 ★ 100% REAL NO FAKE ★ CRACKEADO POR LOS PANAS DEL CYBER ★ "
               "SI SE TRANCA DALE CTRL+ALT+V ★ SALUDOS A TODO MARACAIBO ★ ")

    def __init__(self, parent, on_keygen, on_exit):
        super().__init__(parent)
        self.setFixedHeight(86)
        self.t = 0.0
        self.rng = random.Random(3)
        self.bolt = 0
        lay = QHBoxLayout(self)
        lay.setContentsMargins(190, 0, 14, 0)
        lay.addStretch(1)
        kg = QPushButton("KEYGEN")
        kg.clicked.connect(on_keygen)
        ex = QPushButton("VOLVER A LA NORMALIDAD")
        ex.clicked.connect(on_exit)
        for b in (kg, ex):
            b.setCursor(Qt.PointingHandCursor)
            lay.addWidget(b)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

    def set_running(self, on: bool):
        (self.timer.start(40) if on else self.timer.stop())

    def _tick(self):
        self.t += 0.04
        if self.rng.random() < 0.02:
            self.bolt = 4
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0, QColor("#E8E8F0"))
        g.setColorAt(0.48, QColor("#8A8AA0"))
        g.setColorAt(0.52, QColor("#3A3A55"))
        g.setColorAt(1, QColor("#1A0033"))
        p.fillRect(r, g)
        draw_flames(p, QRectF(0, r.height() - 30, r.width(), 30), self.t)
        draw_flag(p, QRectF(12, 14, 62, 42), self.t * 2.5)
        draw_eagle(p, QPointF(86, 16), 4, self.t * 9)
        p.setFont(QFont(theme.FONTS.get("veneco", "Sans"), 20, QFont.Bold))
        fm = p.fontMetrics()
        text = self.MARQUEE * 3
        w = fm.horizontalAdvance(self.MARQUEE)
        x = 160 - (self.t * 120) % w
        p.save()
        p.setClipRect(QRectF(160, 0, r.width() - 520, r.height()))
        p.setPen(QColor(0, 0, 0, 160))
        p.drawText(QPointF(x + 2, 52), text)
        hue = int(self.t * 60) % 360
        p.setPen(QColor.fromHsv(hue, 255, 255))
        p.drawText(QPointF(x, 50 + 3 * math.sin(self.t * 6)), text)
        p.restore()
        draw_flare(p, QPointF(160 + (r.width() - 520) * ((self.t * 0.3) % 1), 20), 10)
        if self.bolt > 0:
            self.bolt -= 1
            x0 = self.rng.uniform(200, r.width() - 400)
            draw_lightning(p, QPointF(x0, 0), QPointF(x0 + self.rng.uniform(-40, 40), r.height()), self.rng)
        p.setPen(QPen(YELLOW, 2))
        p.drawLine(0, int(r.height()) - 1, int(r.width()), int(r.height()) - 1)
        p.end()


# --------------------------------------------------------------------------- keygen window
class KeygenDialog(QDialog):
    TITLE = "NVIDIA RTX VENECO EDITION — FULL CRACK 100% REAL NO FAKE"

    def __init__(self, parent, sounds: Sounds):
        super().__init__(parent)
        self.sounds = sounds
        self.setWindowTitle(self.TITLE)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setFixedSize(600, 470)
        self.t = 0.0
        self.progress = -1.0
        self.done_msg = False
        self.rng = random.Random()
        self.hexlines = [self._hex() for _ in range(6)]
        self._drag = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 300, 24, 22)
        self.btn = QPushButton("⚡ GENERAR POTENCIA ⚡")
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.setMinimumHeight(46)
        self.btn.clicked.connect(self._generate)
        lay.addWidget(self.btn)
        row = QHBoxLayout()
        self.mute = QPushButton("🔇" if sounds.settings.sound_muted else "🔊")
        self.mute.setFixedWidth(48)
        self.mute.setToolTip("Mute / unmute (volume in Settings)")
        self.mute.clicked.connect(self._toggle_mute)
        close = QPushButton("SALIR")
        close.clicked.connect(self.accept)
        row.addWidget(self.mute)
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)
        self.disclaimer = QLabel("")
        self.disclaimer.setAlignment(Qt.AlignCenter)
        self.disclaimer.setStyleSheet("color:#FFD6FF; font-size:8pt; font-style:italic;")
        lay.addWidget(self.disclaimer)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(40)
        self.sounds.play("keygen")

    def _hex(self) -> str:
        return " ".join(f"{self.rng.randrange(256):02X}" for _ in range(16))

    def _toggle_mute(self):
        s = self.sounds.settings
        s.sound_muted = not s.sound_muted
        s.save()
        self.mute.setText("🔇" if s.sound_muted else "🔊")

    def _generate(self):
        self.progress = 0.0
        self.done_msg = False
        self.disclaimer.setText("")
        self.btn.setEnabled(False)
        self.sounds.play("zap")

    def _tick(self):
        self.t += 0.04
        if int(self.t * 25) % 2 == 0:
            self.hexlines = self.hexlines[1:] + [self._hex()]
        if 0 <= self.progress < 1:
            self.progress = min(1.0, self.progress + 0.012 + 0.02 * self.rng.random())
            if self.progress >= 1:
                self.done_msg = True
                self.btn.setEnabled(True)
                self.disclaimer.setText("No se modificó absolutamente nada. Deja de creer en milagros, becerro.")
                self.sounds.play("tada")
        self.update()

    def _serial(self) -> str:
        # Obviously fake, not a key format of any real product.
        rnd = random.Random(int(self.t * 3))
        return "ARRECHO-" + "-".join("".join(rnd.choice("VENZ0LA9") for _ in range(4)) for _ in range(3))

    def mousePressEvent(self, e):
        self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0, QColor("#2A2A3A"))
        g.setColorAt(0.5, QColor("#4B0082"))
        g.setColorAt(1, QColor("#0A0018"))
        p.fillRect(r, g)
        # metallic title bar
        tb = QRectF(0, 0, r.width(), 30)
        mg = QLinearGradient(tb.topLeft(), tb.bottomLeft())
        mg.setColorAt(0, QColor("#F4F4F4"))
        mg.setColorAt(0.5, QColor("#7A7A90"))
        mg.setColorAt(1, QColor("#C8C8D8"))
        p.fillRect(tb, mg)
        p.setPen(QColor("#1A0033"))
        p.setFont(QFont(theme.FONTS.get("veneco", "Sans"), 9, QFont.Bold))
        p.drawText(tb.adjusted(10, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, self.TITLE)
        # flag
        draw_flag(p, QRectF(24, 46, 120, 80), self.t * 2)
        draw_eagle(p, QPointF(500, 50), 5, self.t * 7)
        # bouncing title
        chrome_text(p, QRectF(150, 50 + 8 * abs(math.sin(self.t * 3)), 340, 70), "GPU MEGA ULTRA", 30, self.t)
        # hex stream
        p.setFont(QFont(theme.FONTS.get("mono", "Monospace"), 9))
        p.setPen(NEON)
        box = QRectF(24, 140, r.width() - 48, 92)
        p.fillRect(box, QColor(0, 0, 0, 180))
        for i, line in enumerate(self.hexlines):
            p.drawText(QRectF(box.left() + 8, box.top() + 4 + i * 14, box.width(), 14), Qt.AlignLeft, line)
        # serial
        p.setPen(QPen(YELLOW, 2))
        p.setBrush(QColor(0, 0, 0, 200))
        sr = QRectF(24, 240, r.width() - 48, 26)
        p.drawRect(sr)
        p.setPen(QColor("white"))
        p.setFont(QFont(theme.FONTS.get("mono", "Monospace"), 11, QFont.Bold))
        p.drawText(sr, Qt.AlignCenter, "SERIAL: " + self._serial())
        # progress
        pr = QRectF(24, 272, r.width() - 48, 18)
        p.setPen(QPen(MAGENTA, 1))
        p.setBrush(QColor(0, 0, 0, 160))
        p.drawRect(pr)
        if self.progress >= 0:
            bg = QLinearGradient(pr.topLeft(), pr.topRight())
            bg.setColorAt(0, YELLOW)
            bg.setColorAt(0.5, BLUE)
            bg.setColorAt(1, RED)
            p.fillRect(pr.adjusted(2, 2, -2 - (pr.width() - 4) * (1 - self.progress), -2), bg)
            p.setPen(QColor("white"))
            p.setFont(QFont(theme.FONTS.get("mono", "Monospace"), 8, QFont.Bold))
            p.drawText(pr, Qt.AlignCenter, f"PARCHEANDO LA BICHA... {self.progress * 100:.0f}%")
        if self.done_msg:
            p.fillRect(QRectF(0, 140, r.width(), 130), QColor(0, 0, 0, 200))
            chrome_text(p, QRectF(0, 160, r.width(), 50), "¡LISTO, MAMAGÜEVO!", 30, self.t)
            p.setPen(YELLOW)
            p.setFont(QFont(theme.FONTS.get("veneco", "Sans"), 13, QFont.Bold))
            p.drawText(QRectF(0, 215, r.width(), 30), Qt.AlignCenter, "TU GRÁFICA YA ES MÁS ARRECHA.")
        p.setPen(QPen(YELLOW, 3))
        p.setBrush(Qt.NoBrush)
        p.drawRect(r.adjusted(1, 1, -1, -1))
        p.end()
