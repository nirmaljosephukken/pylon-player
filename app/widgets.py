"""Custom widgets: icon buttons, the thick seek bar, the cone volume control,
floating overlay windows, the on-screen toast and the subtitle timeline."""
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QCursor, QFont, QFontMetrics, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPolygonF)
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QSizePolicy, QToolButton, QToolTip,
                               QVBoxLayout, QWidget)

from . import theme
from .icons import icon
from .util import fmt_delay, fmt_time


class IconButton(QToolButton):
    def __init__(self, name: str, tip: str = "", size: int = 20, checkable=False, parent=None, box: int | None = None):
        super().__init__(parent)
        self._name, self._size = name, size
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

    def refresh(self):
        self.setIcon(icon(self._name, theme.TEXT, self._size, active=theme.accent()))


def hline():
    from PySide6.QtWidgets import QFrame
    f = QFrame()
    f.setObjectName("Divider")
    return f


# ---------------------------------------------------------------- seek bar

class SeekBar(QWidget):
    """A thick seek bar with hover time, bookmark and chapter markers."""
    seek_requested = Signal(int)   # ms
    seek_preview = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.length = 0
        self.position = 0
        self.markers: list[int] = []     # bookmarks (ms)
        self.chapters: list[int] = []    # chapter starts (ms)
        self._hover_x = None
        self._dragging = False
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(18)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_length(self, ms):
        self.length = max(0, int(ms))
        self.update()

    def set_position(self, ms):
        if not self._dragging:
            self.position = max(0, int(ms))
            self.update()

    def _ms_at(self, x):
        if self.length <= 0:
            return 0
        return int(max(0.0, min(1.0, x / max(1, self.width()))) * self.length)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.length > 0:
            self._dragging = True
            self.position = self._ms_at(e.position().x())
            self.seek_requested.emit(self.position)
            self.update()

    def mouseMoveEvent(self, e):
        self._hover_x = e.position().x()
        ms = self._ms_at(self._hover_x)
        if self.length:
            QToolTip.showText(self.mapToGlobal(QPoint(int(self._hover_x) - 18, -34)), fmt_time(ms), self)
        if self._dragging:
            self.position = ms
            self.seek_requested.emit(ms)
        self.update()

    def mouseReleaseEvent(self, e):
        if self._dragging:
            self._dragging = False
            self.seek_requested.emit(self.position)

    def leaveEvent(self, e):
        self._hover_x = None
        QToolTip.hideText()
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
        p.setBrush(QColor(255, 255, 255, 40))
        p.drawRoundedRect(track, 2, 2)
        if self._hover_x is not None and self.length:
            p.setBrush(QColor(255, 255, 255, 40))
            p.drawRoundedRect(QRectF(0, top, self._hover_x, th), 2, 2)
        if self.length:
            frac = min(1.0, self.position / self.length)
            p.setBrush(QColor(theme.accent()))
            p.drawRoundedRect(QRectF(0, top, w * frac, th), 2, 2)
            # chapter gaps
            p.setBrush(QColor(0, 0, 0, 170))
            for c in self.chapters:
                if 0 < c < self.length:
                    x = w * c / self.length
                    p.drawRect(QRectF(x - 1, top, 2, th))
            # bookmark ticks
            p.setBrush(QColor("#FFFFFF"))
            for b in self.markers:
                if 0 <= b <= self.length:
                    x = w * b / self.length
                    p.drawPolygon(QPolygonF([QPointF(x - 4, top - 6), QPointF(x + 4, top - 6), QPointF(x, top - 1)]))
            # playhead
            if hover:
                x = w * frac
                p.setBrush(QColor("#FFFFFF"))
                p.drawRoundedRect(QRectF(x - 2, top - 3, 4, th + 3), 1.5, 1.5)
        p.end()


# ---------------------------------------------------------------- cone volume

class ConeVolume(QWidget):
    """Volume as a traffic cone lying on its side: narrow tip = quiet,
    wide base = loud. Fills with the accent color, white reflective bands
    keep the cone look. Goes up to 125%."""
    volume_changed = Signal(int)

    MAX = 125

    def __init__(self, parent=None):
        super().__init__(parent)
        self.value = 80
        self.muted = False
        self.setFixedSize(84, 26)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)

    def set_value(self, v, muted=None):
        self.value = max(0, min(self.MAX, int(v)))
        if muted is not None:
            self.muted = muted
        self.setToolTip(f"Volume {self.value}%")
        self.update()

    def _shape(self) -> QPainterPath:
        w, h = self.width() - 4, self.height() - 2
        path = QPainterPath()
        path.moveTo(2, h * 0.62)
        path.lineTo(w, 2)
        path.lineTo(w, h)
        path.lineTo(2, h)
        path.closeSubpath()
        return path

    def _set_from_x(self, x):
        v = round(max(0, min(1, (x - 2) / (self.width() - 6))) * self.MAX)
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
        w = self.width() - 6
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 38))
        p.drawPath(shape)
        frac = self.value / self.MAX
        p.save()
        p.setClipRect(QRectF(0, 0, 2 + w * frac, self.height()))
        p.setBrush(QColor(theme.FAINT if self.muted else theme.accent()))
        p.drawPath(shape)
        # reflective bands
        p.setClipPath(shape, Qt.IntersectClip)
        p.setBrush(QColor(255, 255, 255, 150 if not self.muted else 60))
        for fx in (0.38, 0.66):
            x = 2 + w * fx
            p.drawRect(QRectF(x, 0, w * 0.09, self.height()))
        p.restore()
        # 100% notch
        x100 = 2 + w * (100 / self.MAX)
        p.setPen(QPen(QColor(255, 255, 255, 120), 1))
        p.drawLine(QPointF(x100, self.height() - 1), QPointF(x100, self.height() - 4))
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

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        if self.gradient == "up":       # bottom bar: dark at the bottom
            g = QLinearGradient(0, 0, 0, r.height())
            g.setColorAt(0, QColor(10, 10, 10, int(self.alpha * 0.55)))
            g.setColorAt(1, QColor(10, 10, 10, self.alpha))
            p.fillRect(r, QBrush(g))
        elif self.gradient == "down":   # top bar
            g = QLinearGradient(0, 0, 0, r.height())
            g.setColorAt(0, QColor(10, 10, 10, self.alpha))
            g.setColorAt(1, QColor(10, 10, 10, int(self.alpha * 0.55)))
            p.fillRect(r, QBrush(g))
        else:
            p.setPen(QPen(QColor(255, 255, 255, 28), 1))
            p.setBrush(QColor(20, 20, 20, self.alpha))
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
        p.setPen(QColor(theme.accent()))
        p.drawText(QRectF(w / 2 + 6, 0, 120, 12), Qt.AlignLeft | Qt.AlignTop, fmt_delay(self.delay))
        p.end()


class Card(QWidget):
    """Clickable card used on the home page."""
    clicked = Signal()

    def __init__(self, title: str, subtitle: str = "", icon_name: str = "file", progress: float | None = None,
                 parent=None):
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

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.progress is not None:
            p = QPainter(self)
            r = QRect(1, self.height() - 4, self.width() - 2, 3)
            p.fillRect(r, QColor(255, 255, 255, 30))
            p.fillRect(QRect(1, self.height() - 4, int((self.width() - 2) * self.progress), 3), QColor(theme.accent()))
            p.end()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
