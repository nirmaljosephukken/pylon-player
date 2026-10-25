"""The stage pages and the native video surface VLC draws into."""
import ctypes
import ctypes.util

from PySide6.QtCore import QPoint, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QFrame


PAGE_HOME, PAGE_VIDEO, PAGE_AUDIO = 0, 1, 2

_X11 = {}


def _x11():
    """libX11 and a display connection of our own, or None when this isn't X11."""
    if "lib" not in _X11:
        _X11["lib"] = _X11["dpy"] = None
        try:
            if QGuiApplication.platformName() == "xcb":
                lib = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
                lib.XOpenDisplay.restype = ctypes.c_void_p
                lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
                lib.XDefaultRootWindow.restype = ctypes.c_ulong
                lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
                lib.XTranslateCoordinates.argtypes = [
                    ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
                    ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_ulong)]
                dpy = lib.XOpenDisplay(None)
                if dpy:
                    _X11["lib"], _X11["dpy"] = lib, dpy
        except Exception:
            pass
    return _X11["lib"], _X11["dpy"]


class VideoSurface(QFrame):
    """Native window that VLC draws into. Mouse input is turned off in VLC so
    clicks and the wheel reach this widget."""
    action = Signal(str)
    context = Signal(QPoint)
    wheel = Signal(int)
    zoom_wheel = Signal(int, QPointF)    # Ctrl+scroll: delta, position (#39)
    pan = Signal(QPointF)               # drag while zoomed: movement in pixels
    resized = Signal()

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
        self._x11_seen = None               # (Qt's position, the X11 position) when they last agreed
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setAttribute(Qt.WA_DontCreateNativeAncestors, True)
        self.setStyleSheet("background: #000;")
        self.setMouseTracking(True)
        self._click = QTimer(self)
        self._click.setSingleShot(True)
        self._click.setInterval(QApplication.doubleClickInterval() if QApplication.instance() else 250)
        self._click.timeout.connect(lambda: self._emit_action(self._pending_action))

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
        lib, dpy = _x11()
        if lib is None:
            return QPoint()
        x, y, child = ctypes.c_int(), ctypes.c_int(), ctypes.c_ulong()
        try:
            if not lib.XTranslateCoordinates(dpy, int(self.winId()), lib.XDefaultRootWindow(dpy), 0, 0,
                                             ctypes.byref(x), ctypes.byref(y), ctypes.byref(child)):
                return QPoint()
        except Exception:
            return QPoint()
        real, here = (x.value, y.value), self.mapToGlobal(QPoint(0, 0))
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
            press, self._press_pos = getattr(self, "_press_pos", None), None
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
        self.resized.emit()

    def set_zoomed(self, on: bool):
        self.zoomed = on
        if not self._panned:
            self.setCursor(Qt.OpenHandCursor if on else Qt.ArrowCursor)
