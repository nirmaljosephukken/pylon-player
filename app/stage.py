"""The stage pages and the native video surface VLC draws into."""
import sys

from PySide6.QtCore import QPoint, QPointF, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QFrame, QWidget

from .overlay import real_position


PAGE_HOME, PAGE_VIDEO, PAGE_AUDIO = 0, 1, 2

class VideoCanvas(QWidget):
    """The native window VLC draws into. It fills the surface, except with Super Resolution on, where
    the window sizes it to the picture (#42). Mouse events aren't handled here, so they go on to the
    surface around it."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setAttribute(Qt.WA_DontCreateNativeAncestors, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("background: #000;")
        self.setFocusPolicy(Qt.NoFocus)
        self.setMouseTracking(True)

    def wheelEvent(self, e):
        # Qt passes clicks on to the surface by itself, but only some wheel events
        p = QPointF(self.pos()) + e.position()
        self.parentWidget().wheelEvent(QWheelEvent(p, e.globalPosition(), e.pixelDelta(), e.angleDelta(),
                                                   e.buttons(), e.modifiers(), e.phase(), e.inverted()))
        e.accept()

    def device_size(self) -> tuple[int, int]:
        """The size in device pixels, which is what VLC sees. On Windows ask Windows itself, so that
        rounding at display scales such as 125% can't leave VLC a pixel to letterbox."""
        if sys.platform == "win32":
            try:
                import ctypes
                from ctypes import wintypes
                r = wintypes.RECT()
                u = ctypes.windll.user32
                u.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
                u.GetClientRect.restype = wintypes.BOOL
                if u.GetClientRect(int(self.winId()), ctypes.byref(r)) and r.right > 0 and r.bottom > 0:
                    return r.right - r.left, r.bottom - r.top
            except Exception:
                pass
        dpr = self.devicePixelRatioF() or 1.0
        return round(self.width() * dpr), round(self.height() * dpr)


class VideoSurface(QFrame):
    """The video page. VLC draws into its canvas; mouse input is turned off in VLC so
    clicks and the wheel reach this widget."""
    action = Signal(str)
    context = Signal(QPoint)
    wheel = Signal(int)
    zoom_wheel = Signal(int, QPointF)    # Ctrl+scroll: delta, position (#39)
    pan = Signal(QPointF)               # drag while zoomed: movement in pixels
    resized = Signal()
    pressed = Signal()                  # any click on the video (#79)

    def __init__(self, store):
        super().__init__()
        self.store = store
        self._double_release = False
        self._pending_action = "none"
        self.zoomed = False                 # set by the window; dragging pans only when zoomed
        self.pip = False                    # borderless picture in picture: drag moves the window
        self._drag_from = None
        self._panned = False
        self._move_from = None
        self._moved = False
        self._press_pos = None              # where a left press started, to tell a click from a drag
        self._x11_seen = None               # (Qt's position, the X11 position) when they last agreed
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setAttribute(Qt.WA_DontCreateNativeAncestors, True)
        self.setStyleSheet("background: #000;")
        self.setMouseTracking(True)
        self._click = QTimer(self)
        self._click.setSingleShot(True)
        self._click.setInterval(QApplication.doubleClickInterval() if QApplication.instance() else 250)
        self._click.timeout.connect(lambda: self._emit_action(self._pending_action))
        self.canvas = VideoCanvas(self)
        self.fit_rect = None                # where the canvas sits when sized to the picture (#42)

    def _emit_action(self, action):
        if (QApplication.activeModalWidget() is None and QApplication.activePopupWidget() is None
                and action in ("play_pause", "fullscreen", "mute", "next", "prev", "seek_back", "seek_fwd")):
            self.action.emit(action)

    def cancel_click(self):
        self._click.stop()
        self._double_release = False

    def x11_drift(self) -> QPoint:
        """How far the window has moved since Qt last heard where it is. While the window manager
        drags a window, Qt on X11 isn't told it moved until the drag ends (#59)."""
        real = real_position(self, visible_only=False)
        if real is None:
            return QPoint()
        here = self.mapToGlobal(QPoint(0, 0))
        if self._x11_seen is None or self._x11_seen[0] != here:
            self._x11_seen = (here, real)      # Qt knows where the window is: measure from here
            return QPoint()
        dpr = self.devicePixelRatioF() or 1.0
        start = self._x11_seen[1]
        return QPoint(round((real[0] - start[0]) / dpr), round((real[1] - start[1]) / dpr))

    def hideEvent(self, e):
        self.cancel_click()
        super().hideEvent(e)

    def mousePressEvent(self, e):
        self.pressed.emit()
        if e.button() == Qt.LeftButton:
            self._moved = False              # a system move may have swallowed the last release
            self._press_pos = e.position()
        if e.button() == Qt.LeftButton and self.pip:
            win = self.window()
            if win.pip_edges(e.globalPosition().toPoint()) and win.pip_grab(e.globalPosition().toPoint(), move=False):
                self._moved = True           # resizing from an edge is not a click
                return
        if e.button() == Qt.LeftButton and self.zoomed:
            self._drag_from = e.position()
            self._panned = False
        elif e.button() == Qt.LeftButton and self.pip:
            self._move_from = e.position()
            self._moved = False
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self.pip and not e.buttons():
            cur = self.window().edge_cursor(self.window().pip_edges(e.globalPosition().toPoint()))
            if cur is not None:
                self.setCursor(cur)
            else:
                self.setCursor(Qt.OpenHandCursor if self.zoomed else Qt.ArrowCursor)
        if self._move_from is not None and e.buttons() & Qt.LeftButton:
            d = e.position() - self._move_from
            if abs(d.x()) + abs(d.y()) > 4:
                self._move_from = None
                self._moved = True
                self.cancel_click()
                self.window().pip_grab(e.globalPosition().toPoint())
            return
        if self._drag_from is not None and e.buttons() & Qt.LeftButton:
            d = e.position() - self._drag_from
            if self._panned or abs(d.x()) + abs(d.y()) > 4:
                if not self._panned:
                    self._panned = True
                    self.cancel_click()
                    self.setCursor(Qt.ClosedHandCursor)
                self._drag_from = e.position()
                self.pan.emit(d)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._move_from = None
            press, self._press_pos = self._press_pos, None
            if self._moved:                  # moving or resizing the window is not a click
                self._moved = False
                return
            if self.pip and press is not None and not self.zoomed:
                d = e.position() - press
                if abs(d.x()) + abs(d.y()) > 4:
                    return                   # released somewhere else: a drag, not a click
        if e.button() == Qt.LeftButton and self._drag_from is not None:
            self._drag_from = None
            if self._panned:                 # a drag is not a click
                self._panned = False
                self.setCursor(Qt.OpenHandCursor if self.zoomed else Qt.ArrowCursor)
                return
        if e.button() == Qt.LeftButton:
            if self._double_release:
                self._double_release = False
                return
            action = self.store.setting("mouse_single")
            if self.store.setting("mouse_double") == "none":
                self._emit_action(action)
            else:
                # Preserve the system's double-click interval; shortening it can
                # execute a single-click action before a valid double-click.
                self._pending_action = action
                self._click.start(QApplication.doubleClickInterval())
        else:
            key = {Qt.MiddleButton: "mouse_middle", Qt.BackButton: "mouse_back",
                   Qt.ForwardButton: "mouse_forward"}.get(e.button())
            if key:
                self._emit_action(self.store.setting(key))

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._click.stop()
            if self.store.setting("mouse_double") == "none":
                # Qt still reports a double-click event when no action is bound.
                self._emit_action(self.store.setting("mouse_single"))
            else:
                self._emit_action(self.store.setting("mouse_double"))
            # Fullscreen can hide/recreate the native surface while dispatching.
            self._double_release = True

    def contextMenuEvent(self, e):
        self.context.emit(e.globalPos())

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            self.zoom_wheel.emit(e.angleDelta().y(), e.position())
            return
        self.wheel.emit(e.angleDelta().y())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.fit_rect is None:
            self.canvas.setGeometry(self.rect())
        self.resized.emit()

    def fit_canvas(self, rect: QRect | None):
        """Put the canvas at rect (the picture's place), or let it fill the surface with None."""
        self.fit_rect = QRect(rect) if rect is not None else None
        target = self.fit_rect if self.fit_rect is not None else self.rect()
        if self.canvas.geometry() != target:
            self.canvas.setGeometry(target)

    def set_zoomed(self, on: bool):
        self.zoomed = on
        if not self._panned:
            self.setCursor(Qt.OpenHandCursor if on else Qt.ArrowCursor)
