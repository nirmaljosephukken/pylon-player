"""How Pylon's floating windows (the bars, the toast, the seek preview) are placed over the video.

Qt widgets can't be drawn on top of the native window VLC draws into, so anything that floats over
the video is a small window of its own that Pylon moves into place. Most window managers put such a
window exactly where Pylon asks. Some don't: on Wayland desktops Pylon runs through XWayland, and
COSMIC's window manager places these windows itself and ignores later moves, so the bars ended up
stacked in the corner and didn't follow the window (#81).

There, the windows bypass the window manager (override-redirect, the way menus and tooltips work),
and the X server puts them exactly where Pylon asks. Such a window isn't stacked with Pylon's own
window by the window manager, so the main window hides them whenever Pylon isn't the active app.
On other X11 desktops Pylon checks where the window really went and switches to the same mode if
the window manager moved it.

PYLON_OVERLAYS=bypass or =managed forces either mode."""
import ctypes
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

BASE_FLAGS = Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint | Qt.WindowDoesNotAcceptFocus

_state = {"bypass": None, "reason": ""}


def _platform() -> str:
    try:
        return QGuiApplication.platformName()
    except Exception:
        return ""


def on_xwayland() -> bool:
    """True when Pylon draws through XWayland on a Wayland desktop."""
    return sys.platform.startswith("linux") and _platform() == "xcb" and (
        bool(os.environ.get("WAYLAND_DISPLAY")) or os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland")


def bypass() -> bool:
    """Whether floating windows bypass the window manager."""
    if _state["bypass"] is None:
        force = os.environ.get("PYLON_OVERLAYS", "").strip().lower()
        if force in ("bypass", "managed"):
            _state["bypass"], _state["reason"] = force == "bypass", "PYLON_OVERLAYS"
        elif on_xwayland():
            _state["bypass"], _state["reason"] = True, "XWayland"
        else:
            _state["bypass"], _state["reason"] = False, ""
    return _state["bypass"]


def switch_to_bypass(reason: str) -> bool:
    """Use override-redirect from now on (X11 only). Returns True if this changed anything."""
    if bypass() or _platform() != "xcb" or os.environ.get("PYLON_OVERLAYS", "").strip().lower() == "managed":
        return False
    _state["bypass"], _state["reason"] = True, reason
    return True


def reason() -> str:
    return _state["reason"]


def flags() -> Qt.WindowFlags:
    f = BASE_FLAGS
    if bypass():
        f |= Qt.X11BypassWindowManagerHint
    return f


def reset_for_tests():
    _state["bypass"], _state["reason"] = None, ""


def real_position(widget):
    """Where the X server really has the widget's window, in device pixels, or None off X11."""
    from .stage import _x11
    lib, dpy = _x11()
    if lib is None or not widget.isVisible():
        return None
    x, y, child = ctypes.c_int(), ctypes.c_int(), ctypes.c_ulong()
    try:
        if not lib.XTranslateCoordinates(dpy, int(widget.winId()), lib.XDefaultRootWindow(dpy), 0, 0,
                                         ctypes.byref(x), ctypes.byref(y), ctypes.byref(child)):
            return None
    except Exception:
        return None
    return x.value, y.value
