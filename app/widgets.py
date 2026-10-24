"""Custom widgets: icon buttons, the thick seek bar, the cone volume control,
floating overlay windows, the on-screen toast and the subtitle timeline."""
import time

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QCursor, QFont, QFontMetrics, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPixmap, QPolygonF)
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QSizePolicy, QToolButton, QToolTip,
                               QVBoxLayout, QWidget)

from . import theme
from .icons import icon
from .util import fmt_delay, fmt_time


class IconButton(QToolButton):
    def __init__(self, name: str, tip: str = "", size: int = 20, checkable=False, parent=None, box: int | None = None,
                 color=None):
        super().__init__(parent)
        self._name, self._size = name, size
        self._color = color          # None, a colour, or a function returning one (e.g. theme.on_accent)
        self.setCheckable(checkable)
        self.setToolTip(tip)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setIconSize(QSize(size, size))
        b = box or size + 12
        self.setFixedSize(b, b)
        self.refresh()

    def set_icon(self, name: str):
        self._name = name
        self.refresh()

    def set_dot(self, on: bool):
        """A small accent-coloured dot in the corner, for a mode that is switched on."""
        self._dot = bool(on)
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.objectName() == "PlayButton" and self.underMouse():
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(QPen(QColor(255, 255, 255, 90), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 8, 8)
            p.end()
        if getattr(self, "_dot", False):
            from PySide6.QtGui import QPainter
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.accent()))
            r = max(3.0, self.width() / 9)
            p.drawEllipse(QPointF(self.width() - r - 2, r + 2), r, r)
            p.end()

    def refresh(self):
        c = self._color() if callable(self._color) else self._color
        if c:
            self.setIcon(icon(self._name, c, self._size))
        else:
            self.setIcon(icon(self._name, theme.TEXT, self._size, active=theme.accent()))


def hline():
    from PySide6.QtWidgets import QFrame
    f = QFrame()
    f.setObjectName("Divider")
    return f


# ---------------------------------------------------------------- seek bar

class SeekBar(QWidget):
    """A thick seek bar with hover time, bookmark and chapter markers, an optional
    waveform of the sound, and the part an A–B loop repeats."""
    seek_requested = Signal(int)   # ms
    seek_preview = Signal(int)
    hovered = Signal(int, float)   # ms under the mouse, x in this widget
    hover_left = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.length = 0
        self.position = 0
        self.markers: list[int] = []     # bookmarks (ms)
        self.chapters: list[int] = []    # chapter starts (ms)
        self.wave: list[float] = []      # loudness bars 0..1 along the bar, or empty for the plain bar
        self.ab: tuple = (None, None)    # A–B loop start and end (ms), either can be None
        self._hover_x = None
        self._dragging = False
        self._last_sent, self._last_sent_t = None, 0.0
        self._hold_ms, self._hold_until = None, 0.0
        self._pending = None
        self._drag_timer = QTimer(self)
        self._drag_timer.setSingleShot(True)
        self._drag_timer.timeout.connect(self._flush)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(18)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_length(self, ms):
        self.length = max(0, int(ms))
        self.update()

    def set_wave(self, peaks):
        self.wave = list(peaks or [])
        self.update()

    def set_ab(self, a, b):
        self.ab = (a, b)
        self.update()

    def set_position(self, ms):
        if self._dragging:
            return
        ms = max(0, int(ms))
        # Right after a seek, VLC still reports the old time for a moment.
        # Hold the new position until it catches up, so the bar doesn't jump back and forth.
        if self._hold_ms is not None:
            if abs(ms - self._hold_ms) < 1500 or time.monotonic() > self._hold_until:
                self._hold_ms = None
            else:
                return
        self.position = ms
        self.update()

    def _ms_at(self, x):
        if self.length <= 0:
            return 0
        return int(max(0.0, min(1.0, x / max(1, self.width()))) * self.length)

    def _send(self, ms, force=False):
        """Ask for a seek, but never twice to the same place and not more than a few times a second while dragging."""
        now = time.monotonic()
        if not force and now - self._last_sent_t < 0.18:
            self._pending = ms
            self._drag_timer.start(int((0.18 - (now - self._last_sent_t)) * 1000) + 1)
            return
        self._pending = None
        if self._last_sent is not None and abs(ms - self._last_sent) < 50:
            return
        self._last_sent, self._last_sent_t = ms, now
        self._hold_ms, self._hold_until = ms, now + 1.2
        self.seek_requested.emit(ms)

    def _flush(self):
        if self._pending is not None:
            self._send(self._pending, force=True)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.length > 0:
            self._dragging = True
            self._last_sent = None
            self.position = self._ms_at(e.position().x())
            self._send(self.position, force=True)
            self.update()

    def mouseMoveEvent(self, e):
        self._hover_x = e.position().x()
        ms = self._ms_at(self._hover_x)
        if self.length:
            self.hovered.emit(ms, float(self._hover_x))
        if self._dragging:
            self.position = ms
            self._send(ms)
        self.update()

    def mouseReleaseEvent(self, e):
        if self._dragging:
            self._dragging = False
            self._drag_timer.stop()
            self._pending = None
            self._send(self.position, force=True)   # skipped if it's where we already went

    def leaveEvent(self, e):
        self._hover_x = None
        self.hover_left.emit()
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        hover = self._hover_x is not None or self._dragging
        th = 10 if hover else 8
        top = h - th
        track = QRectF(0, top, w, th)
        p.setPen(Qt.NoPen)
        if self.length and self.ab[0] is not None:
            self._paint_ab(p, w, h)
        if self.wave and self.length:
            self._paint_wave(p, w, h, hover)
            self._paint_marks(p, w, 6, h - 6, hover)
            p.end()
            return
        p.setBrush(QColor(255, 255, 255, 40))
        p.drawRoundedRect(track, 2, 2)
        if self._hover_x is not None and self.length:
            p.setBrush(QColor(255, 255, 255, 40))
            p.drawRoundedRect(QRectF(0, top, self._hover_x, th), 2, 2)
        if self.length:
            frac = min(1.0, self.position / self.length)
            fill = QRectF(0, top, w * frac, th)
            if theme.glow() and frac > 0:          # neon themes: soft light around the bar
                for grow, alpha in ((5, 28), (3, 45), (1.5, 70)):
                    gc = QColor(theme.accent2())
                    gc.setAlpha(alpha)
                    p.setBrush(gc)
                    p.drawRoundedRect(fill.adjusted(-grow, -grow, grow, grow), 2 + grow, 2 + grow)
            p.setBrush(theme.brush(0, w))
            p.drawRoundedRect(fill, 2, 2)
            self._paint_marks(p, w, top, th, hover)
        p.end()

    def _paint_marks(self, p, w, top, th, hover):
        """Chapter gaps, bookmark ticks and (while hovering) the playhead."""
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 170))
        for c in self.chapters:
            if 0 < c < self.length:
                x = w * c / self.length
                p.drawRect(QRectF(x - 1, top, 2, th))
        p.setBrush(QColor("#FFFFFF"))
        for b in self.markers:
            if 0 <= b <= self.length:
                x = w * b / self.length
                p.drawPolygon(QPolygonF([QPointF(x - 4, top - 6), QPointF(x + 4, top - 6), QPointF(x, top - 1)]))
        if hover:
            x = w * min(1.0, self.position / self.length)
            p.setBrush(QColor("#FFFFFF"))
            p.drawRoundedRect(QRectF(x - 2, top - 3, 4, th + 3), 1.5, 1.5)

    def _paint_wave(self, p, w, h, hover):
        """The sound's loudness as thin bars rising from the bottom edge: played part in the
        accent colour, the rest faint, and a little brighter up to the mouse."""
        n = len(self.wave)
        played_x = w * min(1.0, self.position / self.length)
        hover_x = self._hover_x if self._hover_x is not None else -1
        step = 3.0                                     # a 2-pixel bar every 3 pixels
        played = theme.brush(0, w)
        rest, near = QColor(255, 255, 255, 70), QColor(255, 255, 255, 120)
        x = 0.0
        while x < w:
            i = min(n - 1, int(x / w * n))
            v = max(self.wave[i: i + max(1, int(step / w * n) + 1)] or [0])
            bh = max(2.0, v * (h - 2))
            p.setBrush(played if x < played_x else (near if x < hover_x else rest))
            p.drawRect(QRectF(x, h - bh, 2, bh))
            x += step

    def _paint_ab(self, p, w, h):
        """The part an A–B loop repeats, as a tinted band behind the bar, with its two ends."""
        a, b = self.ab
        xa = w * min(1.0, a / self.length)
        xb = w * min(1.0, b / self.length) if b is not None else xa
        tint = QColor(theme.accent())
        tint.setAlpha(60)
        p.setBrush(tint)
        if b is not None:
            p.drawRect(QRectF(xa, 0, max(2.0, xb - xa), h))
        p.setBrush(QColor(theme.accent()))
        for x in (xa, xb) if b is not None else (xa,):
            p.drawRect(QRectF(x - 1, 0, 2, h))


# ---------------------------------------------------------------- cone volume

class ConeVolume(QWidget):
    """Volume as a traffic cone lying on its side: narrow tip = quiet,
    wide base = loud. Fills with the accent color, white reflective bands
    keep the cone look. Goes up to 125% by default, or 150% or 200% (#47)."""
    volume_changed = Signal(int)

    MAX = 125

    def __init__(self, parent=None):
        super().__init__(parent)
        self.value = 80
        self.muted = False
        self.MAX = ConeVolume.MAX
        self.setFixedSize(84, 26)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)

    def set_max(self, m: int):
        self.MAX = int(m)
        self.set_value(self.value)

    def set_value(self, v, muted=None):
        self.value = max(0, min(self.MAX, int(v)))
        if muted is not None:
            self.muted = muted
        self.setToolTip(f"Volume {self.value}%")
        self.update()

    def _shape(self) -> QPainterPath:
        """A full cone on its side: narrow, rounded tip on the left, wide end on the right."""
        r = 2.5                                   # corner rounding
        w, h = self.width(), self.height()
        cy = h / 2
        left, right = 1 + r, w - 1 - r
        tip, base = h * 0.07, h / 2 - 1 - r       # half-heights (before rounding)
        core = QPainterPath()
        core.moveTo(left, cy - tip)
        core.lineTo(right, cy - base)
        core.lineTo(right, cy + base)
        core.lineTo(left, cy + tip)
        core.closeSubpath()
        from PySide6.QtGui import QPainterPathStroker
        st = QPainterPathStroker()
        st.setWidth(2 * r)
        st.setJoinStyle(Qt.RoundJoin)
        return st.createStroke(core).united(core).simplified()

    def _set_from_x(self, x):
        v = round(max(0, min(1, (x - 1) / (self.width() - 2))) * self.MAX)
        if abs(v - 100) <= 3:
            v = 100  # snap to 100%
        self.set_value(v)
        self.volume_changed.emit(self.value)

    def mousePressEvent(self, e):
        self._set_from_x(e.position().x())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self._set_from_x(e.position().x())

    def wheelEvent(self, e):
        step = 5 if e.angleDelta().y() > 0 else -5
        self.set_value(self.value + step)
        self.volume_changed.emit(self.value)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        shape = self._shape()
        w = self.width() - 2
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 38))
        p.drawPath(shape)
        frac = self.value / self.MAX
        p.save()
        p.setClipRect(QRectF(0, 0, 1 + w * frac + (1 if frac >= 1 else 0), self.height()))
        p.setBrush(QColor(theme.FAINT) if self.muted else theme.brush(0, self.width()))
        p.drawPath(shape)
        p.restore()
        # 100% mark: a thin gap across the cone
        x100 = 1 + w * (100 / self.MAX)
        p.save()
        p.setClipPath(shape)
        p.setPen(QPen(QColor(0, 0, 0, 110), 1.5))
        p.drawLine(QPointF(x100, 0), QPointF(x100, self.height()))
        p.restore()
        p.end()


# ---------------------------------------------------------------- overlays

class OverlayWindow(QWidget):
    """A frameless, translucent window that floats over the native video
    surface (Qt widgets cannot be drawn on top of the VLC video directly)."""

    def __init__(self, owner, gradient: str = "none", radius: int = 0, alpha: int = 215):
        super().__init__(owner, Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint
                         | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)
        self.gradient = gradient
        self.radius = radius
        self.alpha = alpha
        self.solid = False      # True: fully opaque bar (controls pinned outside fullscreen)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        br, bg_, bb = theme.rgb(theme.BG)
        if self.solid and self.gradient in ("up", "down"):
            p.fillRect(r, QColor(theme.PANEL))
        elif self.gradient == "up":       # bottom bar: dark at the bottom
            g = QLinearGradient(0, 0, 0, r.height())
            g.setColorAt(0, QColor(br, bg_, bb, int(self.alpha * 0.55)))
            g.setColorAt(1, QColor(br, bg_, bb, self.alpha))
            p.fillRect(r, QBrush(g))
        elif self.gradient == "down":   # top bar
            g = QLinearGradient(0, 0, 0, r.height())
            g.setColorAt(0, QColor(br, bg_, bb, self.alpha))
            g.setColorAt(1, QColor(br, bg_, bb, int(self.alpha * 0.55)))
            p.fillRect(r, QBrush(g))
        else:
            sr, sg, sb = theme.rgb(theme.SURFACE)
            p.setPen(QPen(QColor(255, 255, 255, 28), 1))
            p.setBrush(QColor(sr, sg, sb, self.alpha))
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), self.radius, self.radius)
        p.end()


class Toast(OverlayWindow):
    """On-screen message. Shows the action and the key that triggered it."""

    def __init__(self, owner):
        super().__init__(owner, radius=theme.RADIUS + 2, alpha=225)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 9, 14, 9)
        lay.setSpacing(10)
        self.text = QLabel()
        self.text.setStyleSheet("font-size: 15px; font-weight: 600; background: transparent;")
        self.key = QLabel()
        self.key.setStyleSheet(f"background: rgba(255,255,255,0.10); border: 1px solid rgba(255,255,255,0.18);"
                               f"border-radius: 3px; padding: 1px 7px; color: {theme.MUTED}; font-size: 12px;")
        lay.addWidget(self.text)
        lay.addWidget(self.key)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self.anchor = QPoint(0, 0)

    def show_message(self, text: str, key: str = "", ms: int = 1400):
        self.text.setText(text)
        self.key.setText(key)
        self.key.setVisible(bool(key))
        self.adjustSize()
        self.move(self.anchor)
        self.show()
        self.raise_()
        self._timer.start(ms)


class SeekPreview(OverlayWindow):
    """Floats above the seek bar: a preview frame (when there is one) and the time."""

    clicked = Signal(int)

    def __init__(self, owner):
        super().__init__(owner, radius=theme.RADIUS + 2, alpha=235)
        self.timestamp = None
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide_if_outside)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 6)
        lay.setSpacing(4)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setStyleSheet("background: transparent; border-radius: 4px;")
        self.time = QLabel()
        self.time.setAlignment(Qt.AlignCenter)
        self.time.setStyleSheet("font-size: 13px; font-weight: 600; background: transparent;")
        lay.addWidget(self.image)
        lay.addWidget(self.time)

    def defer_hide(self):
        self._hide_timer.start(300)

    def _hide_if_outside(self):
        if not self.underMouse():
            self.hide()

    def enterEvent(self, e):
        self._hide_timer.stop()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.defer_hide()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.timestamp is not None:
            self.clicked.emit(self.timestamp)
            self.hide()
        super().mouseReleaseEvent(e)

    def show_at(self, gx: int, bottom_y: int, ms: int, img=None, min_x=None, max_x=None):
        """Centre horizontally on gx, sitting just above bottom_y (global coordinates)."""
        if img is not None and not img.isNull():
            dpr = self.devicePixelRatioF() or 1.0
            pm = QPixmap.fromImage(img)
            tw = 168
            pm = pm.scaledToWidth(int(tw * dpr), Qt.SmoothTransformation)
            pm.setDevicePixelRatio(dpr)
            self.image.setPixmap(pm)
            self.image.setFixedSize(int(pm.width() / dpr), int(pm.height() / dpr))
            self.image.show()
        else:
            self.image.hide()
        self._hide_timer.stop()
        self.timestamp = ms if img is not None and not img.isNull() else None
        self.setCursor(Qt.PointingHandCursor if self.timestamp is not None else Qt.ArrowCursor)
        self.setToolTip("Click to seek to this preview" if self.timestamp is not None else "")
        self.time.setText(fmt_time(ms))
        self.adjustSize()
        x = int(gx - self.width() / 2)
        if min_x is not None:
            x = max(min_x, x)
        if max_x is not None:
            x = min(max_x - self.width(), x)
        self.move(x, int(bottom_y - self.height()))
        if not self.isVisible():
            self.show()
        self.raise_()


# ---------------------------------------------------------------- subtitle timeline

class SubtitleTimeline(QWidget):
    """Shows subtitle cues around the current time. Drag sideways to shift
    the subtitles until the text block lines up with the speech."""
    delay_changed = Signal(int)  # ms

    WINDOW = 10000  # ms visible

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cues: list[tuple[int, int, str]] = []
        self.now = 0
        self.delay = 0
        self._drag_x = None
        self._drag_delay = 0
        self.setMinimumHeight(86)
        self.setCursor(Qt.SizeHorCursor)
        self.setToolTip("Drag left or right to move the subtitles")

    def set_cues(self, cues):
        self.cues = cues or []
        self.update()

    def set_state(self, now_ms, delay_ms):
        self.now, self.delay = now_ms, delay_ms
        self.update()

    def _px_per_ms(self):
        return self.width() / self.WINDOW

    def mousePressEvent(self, e):
        self._drag_x = e.position().x()
        self._drag_delay = self.delay

    def mouseMoveEvent(self, e):
        if self._drag_x is None:
            return
        dx = e.position().x() - self._drag_x
        d = int(round((self._drag_delay + dx / self._px_per_ms()) / 50) * 50)
        if d != self.delay:
            self.delay = d
            self.delay_changed.emit(d)
            self.update()

    def mouseReleaseEvent(self, e):
        self._drag_x = None

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor(theme.SURFACE))
        ppm = self._px_per_ms()
        start = self.now - self.WINDOW / 2
        # ticks every second
        p.setPen(QPen(QColor(255, 255, 255, 25), 1))
        first = int(start // 1000 + 1) * 1000
        f = QFont(self.font())
        f.setPointSizeF(7.5)
        p.setFont(f)
        for t in range(first, int(start + self.WINDOW), 1000):
            x = (t - start) * ppm
            p.setPen(QPen(QColor(255, 255, 255, 50 if t % 5000 == 0 else 22), 1))
            p.drawLine(QPointF(x, h - 14), QPointF(x, h))
            if t % 5000 == 0 and t >= 0:
                p.setPen(QColor(theme.FAINT))
                p.drawText(QPointF(x + 3, h - 3), fmt_time(t))
        if not self.cues:
            p.setPen(QColor(theme.MUTED))
            p.drawText(self.rect().adjusted(8, 0, -8, -14), Qt.AlignCenter | Qt.TextWordWrap,
                       "Load a subtitle file (SRT, VTT, ASS) to see its timeline here")
        fm = QFontMetrics(self.font())
        p.setFont(self.font())
        for s, en, text in self.cues:
            s2, e2 = s + self.delay, en + self.delay
            if e2 < start or s2 > start + self.WINDOW:
                continue
            x1, x2 = (s2 - start) * ppm, (e2 - start) * ppm
            r = QRectF(x1, 10, max(4.0, x2 - x1), h - 32)
            active = s2 <= self.now <= e2
            p.setPen(Qt.NoPen)
            c = QColor(theme.accent())
            c.setAlpha(230 if active else 110)
            p.setBrush(c)
            p.drawRoundedRect(r, 3, 3)
            p.setPen(QColor("#111") if active else QColor(theme.TEXT))
            p.drawText(r.adjusted(5, 2, -4, -2), Qt.AlignLeft | Qt.AlignVCenter,
                       fm.elidedText(text, Qt.ElideRight, int(max(0, r.width() - 9))))
        # playhead
        p.setPen(QPen(QColor("#FFFFFF"), 2))
        p.drawLine(QPointF(w / 2, 2), QPointF(w / 2, h - 14))
        # offset label: sized to its own font so the digits aren't cut off at the top
        small = QFont(self.font())
        small.setPointSizeF(8)
        small.setBold(True)
        p.setFont(small)
        sfm = QFontMetrics(small)
        label = fmt_delay(self.delay)
        box = QRectF(w / 2 + 5, 2, sfm.horizontalAdvance(label) + 8, sfm.height() + 2)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.SURFACE))
        p.drawRoundedRect(box, 3, 3)
        p.setPen(QColor(theme.accent()))
        p.drawText(box, Qt.AlignCenter, label)
        p.end()


class ProgressLine(QWidget):
    """Thin rounded progress bar (track plus accent fill)."""

    def __init__(self, value: float, parent=None):
        super().__init__(parent)
        self.value = max(0.0, min(1.0, float(value)))
        self.setFixedHeight(4)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        r = QRectF(self.rect())
        p.setBrush(QColor(255, 255, 255, 38))
        p.drawRoundedRect(r, 2, 2)
        if self.value > 0:
            p.setBrush(theme.brush(0, r.width()))
            p.drawRoundedRect(QRectF(0, 0, max(4.0, r.width() * self.value), r.height()), 2, 2)
        p.end()


class Card(QWidget):
    """Clickable card used on the home page."""
    clicked = Signal()

    def __init__(self, title: str, subtitle: str = "", icon_name: str = "file", progress: float | None = None,
                 parent=None, picture=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QFrame
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(210, 128)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        frame = QFrame()
        frame.setObjectName("Card")
        outer.addWidget(frame)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 12, 12, 10)
        lay.setSpacing(4)
        ic = QLabel()
        from .icons import pixmap
        if picture is not None and not picture.isNull():     # album cover art
            ic.setPixmap(picture)
        else:
            ic.setPixmap(pixmap(icon_name, theme.accent(), 26))
        ic.setStyleSheet("background: transparent; border: none;")
        lay.addWidget(ic)
        lay.addStretch(1)
        t = QLabel(title)
        t.setStyleSheet("font-weight: 600; background: transparent; border: none;")
        t.setWordWrap(False)
        fm = QFontMetrics(t.font())
        t.setText(fm.elidedText(title, Qt.ElideRight, 186))
        t.setToolTip(title)
        lay.addWidget(t)
        if subtitle:
            s = QLabel(fm.elidedText(subtitle, Qt.ElideRight, 186))
            s.setStyleSheet(f"color: {theme.MUTED}; font-size: 12px; background: transparent; border: none;")
            lay.addWidget(s)
        self.progress = progress
        if progress is not None:          # how far you've watched, as a thin bar at the bottom of the card
            lay.addSpacing(4)
            lay.addWidget(ProgressLine(progress))

        self._corner = None

    def add_corner_button(self, name: str, tip: str, callback):
        """A small round button in the top-right corner that shows while the mouse is over the card."""
        b = IconButton(name, tip, size=18, box=30, parent=self)
        b.setObjectName("CardCorner")
        b.move(self.width() - 30 - 8, 8)
        b.clicked.connect(lambda *_: callback())    # clicked(bool) would land in the callback's arguments
        b.hide()
        self._corner = b
        return b

    def enterEvent(self, e):
        if self._corner:
            self._corner.show()
            self._corner.raise_()
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self._corner:
            self._corner.hide()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()


def subtitle_search_menu(parent, store, query_fn):
    """Menu of subtitle sites for "Find online" (#46). The order never changes; the preferred
    site from Preferences > Subtitles is marked with a star (#54)."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QMenu
    from .util import SUBTITLE_SITES, subtitle_search_url
    menu = QMenu(parent)

    from .icons import icon

    from PySide6.QtGui import QIcon, QPixmap
    pm = QPixmap(16, 16)
    pm.fill(Qt.transparent)
    blank = QIcon(pm)

    def fill():
        menu.clear()
        star = store.setting("sub_site_star")
        for key, name, _url in SUBTITLE_SITES:
            act = menu.addAction(name, lambda k=key: open_site(k))
            if key == star:
                act.setIcon(icon("star", theme.accent(), 16))
                act.setToolTip(f"Your preferred site. Search {name} in your browser")
            else:
                act.setIcon(blank)                                 # keeps the names lined up
                act.setToolTip(f"Search {name} in your browser")

    def open_site(key):
        QDesktopServices.openUrl(QUrl(subtitle_search_url(key, query_fn())))

    menu.aboutToShow.connect(fill)
    fill()
    return menu
