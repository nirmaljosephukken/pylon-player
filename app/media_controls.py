"""Media keys and the system's media controls.

* Every system: the keyboard's media keys (play/pause, next, previous, stop) while Pylon is in front.
* Windows: the media overlay that appears with the volume keys and on the lock screen (System Media Transport
  Controls). It shows what's playing and its buttons, headset buttons and media keys reach Pylon even while
  another app is in front. Pylon talks to it through Windows' own COM interfaces, so nothing has to be
  installed.
* Linux: MPRIS over D-Bus, which desktop media widgets, headset buttons and `playerctl` use.
* macOS: media keys while Pylon is in front. Now Playing would need Apple's frameworks, which Pylon's bundled
  Python doesn't include.

A command can arrive twice for one key press (Windows hands a media key both to the overlay and to the window
in front), so a second identical command within DEDUPE_S is ignored.
"""
import ctypes
import os
import sys
import time

from PySide6.QtCore import QObject, Signal

DEDUPE_S = 0.4
COMMANDS = ("play", "pause", "toggle", "next", "previous", "stop", "raise")


class MediaControls(QObject):
    command = Signal(str)          # one of COMMANDS
    seek_to = Signal(int)          # jump to this many ms (MPRIS SetPosition)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.backend = None
        self.backend_name = ""
        self._last = ("", 0.0)
        self.position_source = None    # a function giving the position now, in ms
        self._state = {"status": "stopped", "title": "", "artist": "", "length": 0, "position": 0, "audio": False}

    # ---------------------------------------------------------------- setup
    def start(self, hwnd: int = 0) -> str:
        """Connect to the system's media controls. Returns which ones ("" if none could be used)."""
        if self.backend is not None:
            return self.backend_name
        try:
            if sys.platform == "win32" and hwnd and not os.environ.get("PYLON_NO_SMTC"):
                self.backend, self.backend_name = WindowsSMTC(hwnd, self._from_system), "windows"
            elif sys.platform.startswith("linux") and HAVE_DBUS:
                self.backend, self.backend_name = MprisService(self), "mpris"
        except Exception as err:          # the controls are a nicety: Pylon works without them
            print(f"System media controls unavailable: {err}", file=sys.stderr, flush=True)
            self.backend, self.backend_name = None, ""
        if self.backend is not None:
            self.backend.update(self._state)
        return self.backend_name

    def stop(self):
        if self.backend is not None:
            try:
                self.backend.close()
            except Exception:
                pass
        self.backend, self.backend_name = None, ""

    # ---------------------------------------------------------------- commands in
    def from_key(self, cmd: str):
        """A media key pressed while Pylon is in front."""
        self._emit(cmd)

    def _from_system(self, cmd: str):
        """A button in the system's controls (may run on another thread; the signal is queued)."""
        self._emit(cmd)

    def _emit(self, cmd: str):
        if cmd not in COMMANDS:
            return
        kind = "playpause" if cmd in ("play", "pause", "toggle") else cmd
        now = time.monotonic()
        if self._last[0] == kind and now - self._last[1] < DEDUPE_S:
            return
        self._last = (kind, now)
        self.command.emit(cmd)

    # ---------------------------------------------------------------- state out
    def update(self, **state):
        """Tell the system what's playing: status ("playing", "paused", "stopped"), title, artist, length (ms),
        position (ms), audio (a song rather than a video)."""
        changed = {k: v for k, v in state.items() if self._state.get(k) != v}
        if not changed:
            return
        self._state.update(changed)
        if self.backend is not None and set(changed) - {"position"}:
            try:
                self.backend.update(self._state)
            except Exception as err:
                print(f"System media controls: {err}", file=sys.stderr, flush=True)

    def position(self) -> int:
        try:
            return int(self.position_source()) if self.position_source else int(self._state["position"])
        except Exception:
            return 0

    @property
    def state(self) -> dict:
        return dict(self._state)


# ==================================================================== Linux: MPRIS
HAVE_DBUS = False
if sys.platform.startswith("linux") or os.environ.get("PYLON_TEST_MPRIS"):
    try:                           # some Linux PySide6 packages leave QtDBus out: then only the media keys work
        from PySide6.QtCore import ClassInfo, Property, Slot
        from PySide6.QtDBus import QDBusAbstractAdaptor, QDBusConnection, QDBusMessage, QDBusObjectPath
        HAVE_DBUS = True
    except ImportError:
        pass

if HAVE_DBUS:

    MPRIS_PATH = "/org/mpris/MediaPlayer2"
    PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
    STATUS = {"playing": "Playing", "paused": "Paused", "stopped": "Stopped"}

    @ClassInfo({"D-Bus Interface": "org.mpris.MediaPlayer2"})
    class _MprisRoot(QDBusAbstractAdaptor):
        def __init__(self, parent, hub):
            super().__init__(parent)
            self.hub = hub

        CanQuit = Property(bool, lambda self: False)
        CanRaise = Property(bool, lambda self: True)
        HasTrackList = Property(bool, lambda self: False)
        Identity = Property(str, lambda self: "Pylon")
        DesktopEntry = Property(str, lambda self: "pylon")
        SupportedUriSchemes = Property("QStringList", lambda self: [])
        SupportedMimeTypes = Property("QStringList", lambda self: [])

        @Slot()
        def Raise(self):
            self.hub._from_system("raise")

        @Slot()
        def Quit(self):
            pass

    @ClassInfo({"D-Bus Interface": PLAYER_IFACE})
    class _MprisPlayer(QDBusAbstractAdaptor):
        def __init__(self, parent, hub):
            super().__init__(parent)
            self.hub = hub

        def _st(self):
            return self.hub._state

        PlaybackStatus = Property(str, lambda self: STATUS.get(self._st()["status"], "Stopped"))
        Rate = Property(float, lambda self: 1.0)
        MinimumRate = Property(float, lambda self: 1.0)
        MaximumRate = Property(float, lambda self: 1.0)
        Metadata = Property("QVariantMap", lambda self: _mpris_metadata(self._st()))
        Position = Property("qlonglong", lambda self: self.hub.position() * 1000)
        CanGoNext = Property(bool, lambda self: True)
        CanGoPrevious = Property(bool, lambda self: True)
        CanPlay = Property(bool, lambda self: True)
        CanPause = Property(bool, lambda self: True)
        CanSeek = Property(bool, lambda self: bool(self._st()["length"]))
        CanControl = Property(bool, lambda self: True)

        @Slot()
        def Play(self):
            self.hub._from_system("play")

        @Slot()
        def Pause(self):
            self.hub._from_system("pause")

        @Slot()
        def PlayPause(self):
            self.hub._from_system("toggle")

        @Slot()
        def Stop(self):
            self.hub._from_system("stop")

        @Slot()
        def Next(self):
            self.hub._from_system("next")

        @Slot()
        def Previous(self):
            self.hub._from_system("previous")

        @Slot("qlonglong")
        def Seek(self, offset_us):
            self.hub.seek_to.emit(max(0, self.hub.position() + int(offset_us) // 1000))

        @Slot(QDBusObjectPath, "qlonglong")
        def SetPosition(self, _track, position_us):
            self.hub.seek_to.emit(max(0, int(position_us) // 1000))

    def _mpris_metadata(st) -> dict:
        md = {"mpris:trackid": QDBusObjectPath("/org/pylon/track/current" if st["title"] else
                                               "/org/mpris/MediaPlayer2/TrackList/NoTrack")}
        if st["title"]:
            md["xesam:title"] = st["title"]
        if st["artist"]:
            md["xesam:artist"] = [st["artist"]]
        if st["length"]:
            md["mpris:length"] = int(st["length"]) * 1000
        return md

    class MprisService:
        """Pylon on the session bus as org.mpris.MediaPlayer2.pylon."""
        def __init__(self, hub):
            self.bus = QDBusConnection.sessionBus()
            if not self.bus.isConnected():
                raise RuntimeError("no D-Bus session bus")
            self.obj = QObject()
            self.root = _MprisRoot(self.obj, hub)
            self.player = _MprisPlayer(self.obj, hub)
            if not self.bus.registerObject(MPRIS_PATH, self.obj, QDBusConnection.ExportAdaptors):
                raise RuntimeError("couldn't register the MPRIS object")
            self.name = "org.mpris.MediaPlayer2.pylon"
            if not self.bus.registerService(self.name):
                self.name = f"org.mpris.MediaPlayer2.pylon.instance{os.getpid()}"
                if not self.bus.registerService(self.name):
                    self.bus.unregisterObject(MPRIS_PATH)
                    raise RuntimeError("couldn't take an MPRIS name")
            self._sent = {}

        def update(self, st):
            props = {"PlaybackStatus": STATUS.get(st["status"], "Stopped"), "Metadata": _mpris_metadata(st),
                     "CanSeek": bool(st["length"])}
            changed = {k: v for k, v in props.items() if self._sent.get(k) != repr(v)}
            if not changed:
                return
            for k, v in changed.items():
                self._sent[k] = repr(v)
            msg = QDBusMessage.createSignal(MPRIS_PATH, "org.freedesktop.DBus.Properties", "PropertiesChanged")
            msg.setArguments([PLAYER_IFACE, changed, []])
            self.bus.send(msg)

        def close(self):
            self.bus.unregisterService(self.name)
            self.bus.unregisterObject(MPRIS_PATH)


# ==================================================================== Windows: System Media Transport Controls
class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16), ("Data3", ctypes.c_uint16),
                ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, text: str):
        h = text.strip("{}").replace("-", "")
        g = cls(int(h[:8], 16), int(h[8:12], 16), int(h[12:16], 16))
        for i in range(8):
            g.Data4[i] = int(h[16 + 2 * i:18 + 2 * i], 16)
        return g

    def __eq__(self, other):
        return bytes(self) == bytes(other)


IID_SMTC_INTEROP = _GUID.parse("ddb0472d-c911-4a1f-86d9-dc3d71a95f5a")
IID_SMTC = _GUID.parse("99fa3ff4-1742-42a6-902e-087d41f965ec")
IID_BUTTON_HANDLER = _GUID.parse("0557e996-7b23-5bae-aa81-ea0d671143a4")   # TypedEventHandler<SMTC, ButtonPressedEventArgs>
IID_IUNKNOWN = _GUID.parse("00000000-0000-0000-c000-000000000046")
IID_IAGILE = _GUID.parse("94ea2b94-e9cc-49e0-c0ff-ee64ca8f5b90")
E_NOINTERFACE = 0x80004002 - (1 << 32)

# ISystemMediaTransportControls, after IInspectable's six methods (windows.media.h)
SMTC_PUT_STATUS, SMTC_GET_UPDATER, SMTC_PUT_ENABLED = 7, 8, 11
SMTC_PUT_PLAY, SMTC_PUT_STOP, SMTC_PUT_PAUSE, SMTC_PUT_PREVIOUS, SMTC_PUT_NEXT = 13, 15, 17, 25, 27
SMTC_ADD_BUTTON, SMTC_REMOVE_BUTTON = 32, 33
# ISystemMediaTransportControlsDisplayUpdater
UPD_PUT_TYPE, UPD_GET_MUSIC, UPD_GET_VIDEO, UPD_CLEAR, UPD_UPDATE = 7, 12, 13, 16, 17
PROPS_PUT_TITLE, MUSIC_PUT_ARTIST, VIDEO_PUT_SUBTITLE = 7, 11, 9
SMTC_BUTTONS = {0: "play", 1: "pause", 2: "stop", 6: "next", 7: "previous"}
SMTC_STATUS = {"stopped": 2, "playing": 3, "paused": 4}


def _method(ptr, index, *argtypes):
    """A COM method from an interface pointer's vtable, returning the HRESULT as an int."""
    vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)
    fn = proto(vtbl[index])
    return lambda *args: fn(ptr, *args)


def _check(hr, what):
    if hr < 0:
        raise OSError(f"{what} failed (0x{hr & 0xFFFFFFFF:08X})")


class WindowsSMTC:
    def __init__(self, hwnd: int, on_button):
        combase = ctypes.WinDLL("combase")
        self._create = combase.WindowsCreateString
        self._create.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
        self._create.restype = ctypes.c_long
        self._delete = combase.WindowsDeleteString
        self._delete.argtypes = [ctypes.c_void_p]
        combase.RoInitialize.argtypes = [ctypes.c_int]
        combase.RoInitialize(0)          # already initialised by Qt on this thread: harmless
        factory_fn = combase.RoGetActivationFactory
        factory_fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
        factory_fn.restype = ctypes.c_long
        self.on_button = on_button
        cls = self._hstring("Windows.Media.SystemMediaTransportControls")
        interop = ctypes.c_void_p()
        try:
            _check(factory_fn(cls, ctypes.byref(IID_SMTC_INTEROP), ctypes.byref(interop)), "RoGetActivationFactory")
        finally:
            self._delete(cls)
        smtc = ctypes.c_void_p()
        hr = _method(interop, 6, ctypes.c_void_p, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p))(
            ctypes.c_void_p(hwnd), ctypes.byref(IID_SMTC), ctypes.byref(smtc))
        _method(interop, 2)()
        _check(hr, "GetForWindow")
        self.smtc = smtc
        for index in (SMTC_PUT_ENABLED, SMTC_PUT_PLAY, SMTC_PUT_PAUSE, SMTC_PUT_STOP, SMTC_PUT_NEXT, SMTC_PUT_PREVIOUS):
            _check(_method(smtc, index, ctypes.c_ubyte)(1), "enabling the buttons")
        self._handler = _ButtonHandler(self._pressed)
        self._token = ctypes.c_int64()
        _check(_method(smtc, SMTC_ADD_BUTTON, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int64))(
            self._handler.pointer, ctypes.byref(self._token)), "add_ButtonPressed")

    def _hstring(self, text: str):
        h = ctypes.c_void_p()
        _check(self._create(text, len(text), ctypes.byref(h)), "WindowsCreateString")
        return h

    def _pressed(self, button: int):
        cmd = SMTC_BUTTONS.get(button)
        if cmd:
            self.on_button(cmd)

    def update(self, st):
        _method(self.smtc, SMTC_PUT_STATUS, ctypes.c_int)(SMTC_STATUS.get(st["status"], 2))
        upd = ctypes.c_void_p()
        _check(_method(self.smtc, SMTC_GET_UPDATER, ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(upd)),
               "DisplayUpdater")
        try:
            if not st["title"]:
                _method(upd, UPD_CLEAR)()
            else:
                audio = bool(st["audio"])
                _method(upd, UPD_PUT_TYPE, ctypes.c_int)(1 if audio else 2)       # Music or Video
                props = ctypes.c_void_p()
                _check(_method(upd, UPD_GET_MUSIC if audio else UPD_GET_VIDEO, ctypes.POINTER(ctypes.c_void_p))(
                    ctypes.byref(props)), "display properties")
                try:
                    self._put(props, PROPS_PUT_TITLE, st["title"])
                    if st["artist"]:
                        self._put(props, MUSIC_PUT_ARTIST if audio else VIDEO_PUT_SUBTITLE, st["artist"])
                finally:
                    _method(props, 2)()
            _method(upd, UPD_UPDATE)()
        finally:
            _method(upd, 2)()

    def _put(self, obj, index, text):
        h = self._hstring(text)
        try:
            _method(obj, index, ctypes.c_void_p)(h)
        finally:
            self._delete(h)

    def close(self):
        if self.smtc:
            _method(self.smtc, SMTC_REMOVE_BUTTON, ctypes.c_int64)(self._token)
            _method(self.smtc, SMTC_PUT_ENABLED, ctypes.c_ubyte)(0)
            _method(self.smtc, 2)()
            self.smtc = None


class _ButtonHandler:
    """A COM object implementing the ButtonPressed event handler, made from ctypes callbacks. It lives as long
    as Pylon (reference counting is a formality), and only passes the button on."""
    def __init__(self, on_button):
        F = ctypes.WINFUNCTYPE
        self._qi = F(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p))(self._query)
        self._addref = F(ctypes.c_ulong, ctypes.c_void_p)(lambda _this: 1)
        self._release = F(ctypes.c_ulong, ctypes.c_void_p)(lambda _this: 1)
        self._invoke = F(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(self._call)
        self._vtbl = (ctypes.c_void_p * 4)(*[ctypes.cast(f, ctypes.c_void_p) for f in
                                             (self._qi, self._addref, self._release, self._invoke)])
        self._obj = ctypes.c_void_p(ctypes.addressof(self._vtbl))
        self.pointer = ctypes.c_void_p(ctypes.addressof(self._obj))
        self.on_button = on_button

    def _query(self, this, riid, ppv):
        iid = riid.contents
        if iid == IID_BUTTON_HANDLER or iid == IID_IUNKNOWN or iid == IID_IAGILE:
            ppv[0] = this
            return 0
        ppv[0] = None
        return E_NOINTERFACE

    def _call(self, _this, _sender, args):
        try:
            button = ctypes.c_int()
            if _method(ctypes.c_void_p(args), 6, ctypes.POINTER(ctypes.c_int))(ctypes.byref(button)) >= 0:
                self.on_button(button.value)
        except Exception:
            pass
        return 0
