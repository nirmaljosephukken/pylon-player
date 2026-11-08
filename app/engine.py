"""Thin wrapper around libVLC (python-vlc).

Everything VLC-specific lives here so the UI never touches the binding
directly. libVLC events arrive on a VLC thread; they are re-emitted as Qt
signals, which Qt delivers on the GUI thread.
"""
import ctypes
import math
import os
import sys
import time
from fractions import Fraction

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from .util import disc_mrl, is_disc, is_url


def _video_track(track):
    """The video details of a libvlc media track. In C they are a union (audio, video or subtitle at
    the same place), but python-vlc lists them one after another, so its .video reads past the pointer
    and crashes. Read the pointer where the union really is."""
    try:
        off = type(track).audio.offset
        ptr = ctypes.c_void_p.from_address(ctypes.addressof(track) + off).value
        return ctypes.cast(ptr, ctypes.POINTER(vlc.VideoTrack)).contents if ptr else None
    except Exception:
        return None


# Rotate and flip (#83). Matrices act on (x, y) with y pointing down, so "90" turns the picture clockwise.
_ROT = {0: (1, 0, 0, 1), 90: (0, -1, 1, 0), 180: (-1, 0, 0, -1), 270: (0, 1, -1, 0)}
_FLIP_H, _FLIP_V = (-1, 0, 0, 1), (1, 0, 0, -1)
# VLC's --transform-type values: the eight ways a picture can be turned and mirrored
VLC_TRANSFORMS = {"": _ROT[0], "90": _ROT[90], "180": _ROT[180], "270": _ROT[270],
                  "hflip": _FLIP_H, "vflip": _FLIP_V, "transpose": (0, 1, 1, 0), "antitranspose": (0, -1, -1, 0)}
# the other way round, as Pylon shows it: VLC value -> (rotation, flip H, flip V)
_PARTS = {"": (0, False, False), "90": (90, False, False), "180": (180, False, False), "270": (270, False, False),
          "hflip": (0, True, False), "vflip": (0, False, True), "transpose": (90, True, False),
          "antitranspose": (270, True, False)}


def _mul(a, b):
    return (a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3],
            a[2] * b[0] + a[3] * b[2], a[2] * b[1] + a[3] * b[3])


def compose_transform(rotate: int = 0, flip_h: bool = False, flip_v: bool = False) -> str:
    """The one VLC transform that turns the picture by `rotate` degrees clockwise and then mirrors what
    you see (#83: Flip H with 90° or 270° used to be impossible, because VLC takes a single value)."""
    m = _ROT[int(rotate) % 360]
    if flip_v:
        m = _mul(_FLIP_V, m)
    if flip_h:
        m = _mul(_FLIP_H, m)
    return next(k for k, v in VLC_TRANSFORMS.items() if v == m)


def transform_parts(value: str) -> tuple[int, bool, bool]:
    """(rotation, flip H, flip V) for a VLC transform value, the way the Video tab shows it."""
    return _PARTS.get(str(value or ""), (0, False, False))


# VLC's visualizations for sound with no video (#85): key -> (name, VLC options). The first four come with
# every VLC; Goom and 3D spectrum are separate modules that some builds (Linux distributions) leave out.
VISUALIZERS = {
    "": ("Off", []),
    "spectrum": ("Spectrum", ["--audio-visual=visual", "--effect-list=spectrum"]),
    "scope": ("Scope", ["--audio-visual=visual", "--effect-list=scope"]),
    "vumeter": ("VU meter", ["--audio-visual=visual", "--effect-list=vuMeter"]),
    "spectrometer": ("Spectrometer", ["--audio-visual=visual", "--effect-list=spectrometer"]),
    "goom": ("Goom", ["--audio-visual=goom"]),
    "glspectrum": ("3D spectrum", ["--audio-visual=glspectrum"]),
}

def vlc_place(src: tuple[int, int], sar: tuple[int, int], area: tuple[int, int]):
    """The picture size VLC 3 fits into a video area (vout_display_PlacePicture, display.c), with its
    integer maths: src is the (cropped) picture in pixels, sar its sample aspect ratio. None when VLC's
    32-bit sums would overflow and give nonsense."""
    (w, h), (sn, sd), (aw, ah) = src, sar, area
    g = math.gcd(sn, sd) or 1
    sn, sd = sn // g, sd // g
    if not (w and h and sn and sd and aw and ah) or max(w * sn, h * sd) >= 2 ** 32:
        return None
    scaled_h = h * aw * sd // (w * sn)
    scaled_w = w * ah * sn // (h * sd)
    return (scaled_w, ah) if scaled_w <= aw else (aw, scaled_h)


def fill_aspects(area: tuple[int, int], crop: tuple[int, int], src: tuple[int, int], count: int = 2):
    """Aspect ratios a:b to give VLC so that the cropped picture (crop, in pixels of the src picture)
    fills the area exactly, with no black bar even one pixel wide (#42). VLC turns a:b into a sample
    aspect ratio of a*src_h : b*src_w, so without a crop the result doesn't depend on the source size at
    all. The simplest ratios come first; a second one lets Pylon make VLC redraw without letterboxing."""
    (aw, ah), (cw, ch), (sw, sh) = area, crop, src
    if not (aw and ah and cw and ch and sw and sh):
        return []
    lo = Fraction(aw * ch * sw, ah * cw * sh)          # a/b may be up to a pixel wider than the area
    hi = Fraction((aw + 1) * ch * sw, ah * cw * sh)
    out = []
    for b in range(1, 4 * max(aw, ah) + 1):
        a = math.ceil(lo * b)
        if a >= hi * b or math.gcd(a, b) != 1 or a * sh >= 2 ** 32 or b * sw >= 2 ** 32:
            continue
        if vlc_place((cw, ch), (a * sh, b * sw), (aw, ah)) == (aw, ah):
            out.append((a, b))
            if len(out) >= count:
                break
    return out

def _saved_vlc_dir() -> str:
    """A VLC folder the user picked with "Locate VLC folder..." (stored in data.json)."""
    try:
        import json
        from .store import data_dir
        with open(os.path.join(data_dir(), "data.json"), encoding="utf-8") as f:
            return json.load(f).get("settings", {}).get("vlc_dir", "") or ""
    except Exception:
        return ""


def _windows_candidates() -> list[str]:
    """Folders where a Windows VLC might be, most specific first."""
    app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cands = [os.environ.get("PYLON_VLC_DIR", ""), _installer_vlc_dir()]
    # VLC inside Pylon's folder, or next to it, or next to any folder above it
    # (setup's Browse button adds "\Pylon", e.g. E:\Apps\Pylon-1.1\Pylon with E:\Apps\VLC).
    d = app_root
    for _ in range(4):
        cands += [os.path.join(d, "VLC"), os.path.join(d, "VideoLAN", "VLC")]
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    try:  # where the VLC installer says it lives
        import winreg
        keys = [(winreg.HKEY_LOCAL_MACHINE, r"Software\VideoLAN\VLC", "InstallDir"),
                (winreg.HKEY_CURRENT_USER, r"Software\VideoLAN\VLC", "InstallDir"),
                (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\App Paths\vlc.exe", ""),
                (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\App Paths\vlc.exe", "")]
        for hive, key, name in keys:
            try:
                with winreg.OpenKey(hive, key) as k:
                    v = winreg.QueryValueEx(k, name)[0]
                    cands.append(os.path.dirname(v) if v.lower().endswith(".exe") else v)
            except OSError:
                pass
    except ImportError:
        pass
    for env in ("ProgramFiles", "ProgramW6432", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            cands.append(os.path.join(base, "VideoLAN", "VLC"))
            cands.append(os.path.join(base, "Programs", "VideoLAN", "VLC"))
    for p in os.environ.get("PATH", "").split(os.pathsep):  # a VLC folder on PATH
        if p and os.path.isfile(os.path.join(p, "vlc.exe")):
            cands.append(p)
    return cands


def _installer_vlc_dir() -> str:
    """Setup writes the VLC folder it found to vlc-path.txt next to Pylon."""
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "vlc-path.txt"), encoding="utf-8-sig") as f:
            return f.read().strip().strip('"')
    except OSError:
        return ""


def _point_at(folder: str) -> bool:
    """Tell python-vlc to use the VLC in `folder`. True if it looks like VLC."""
    folder = os.path.normpath(folder) if folder else ""
    if sys.platform == "win32":
        lib = os.path.join(folder, "libvlc.dll")
        if not folder or not os.path.isfile(lib):
            return False
        try:
            _DLL_DIRS.append(os.add_dll_directory(folder))
        except (OSError, AttributeError):
            pass
        os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")
        os.environ["PYTHON_VLC_MODULE_PATH"] = os.path.join(folder, "plugins")
        os.environ["PYTHON_VLC_LIB_PATH"] = lib
        return True
    if sys.platform == "darwin":
        lib = os.path.join(folder, "Contents", "MacOS", "lib", "libvlc.dylib")
        if not folder or not os.path.isfile(lib):
            return False
        os.environ["PYTHON_VLC_LIB_PATH"] = lib
        os.environ["PYTHON_VLC_MODULE_PATH"] = os.path.join(folder, "Contents", "MacOS", "plugins")
        os.environ["VLC_PLUGIN_PATH"] = os.path.join(folder, "Contents", "MacOS", "plugins")
        return True
    # Linux: a folder holding libvlc.so.5 (rare; normally the system copy is used)
    for lib in (os.path.join(folder, "libvlc.so.5"), os.path.join(folder, "lib", "libvlc.so.5")):
        if folder and os.path.isfile(lib):
            os.environ["PYTHON_VLC_LIB_PATH"] = lib
            plug = os.path.join(os.path.dirname(lib), "vlc", "plugins")
            if os.path.isdir(plug):
                os.environ["PYTHON_VLC_MODULE_PATH"] = plug
                os.environ["VLC_PLUGIN_PATH"] = plug
            return True
    return False


_DLL_DIRS = []   # keep os.add_dll_directory handles alive
_MAC_LIBS = []   # keep the preloaded VLC core and engine alive on macOS
vlc = None
VLC_ERROR = "not loaded yet"
VLC_DIR = ""     # the folder libVLC was loaded from ("" = found by python-vlc itself)


def load_vlc(folder: str = "") -> bool:
    """Find and load libVLC. With `folder`, use exactly that VLC. Can be called
    again while Pylon runs (after "Locate VLC folder...") as long as no VLC was
    loaded yet."""
    global vlc, VLC_ERROR, VLC_DIR
    if vlc is not None:
        return True
    try:
        if folder:
            if not _point_at(folder):
                raise ImportError(f"{folder} doesn't contain VLC")
            VLC_DIR = folder
        elif "PYTHON_VLC_LIB_PATH" not in os.environ:
            saved = os.environ.get("PYLON_VLC_DIR") or _saved_vlc_dir()
            if saved:
                os.environ["PYLON_VLC_DIR"] = saved
            if sys.platform == "win32":
                cands = _windows_candidates()
            elif sys.platform == "darwin":
                cands = [saved, "/Applications/VLC.app", os.path.expanduser("~/Applications/VLC.app")]
            else:
                cands = [saved]
            seen = set()
            for cand in cands:
                key = os.path.normcase(os.path.normpath(cand)) if cand else ""
                if not key or key in seen:
                    continue
                seen.add(key)
                if _point_at(cand):
                    VLC_DIR = os.path.normpath(cand)
                    break
        if sys.platform == "darwin":
            lib = os.environ.get("PYTHON_VLC_LIB_PATH")
            if lib:
                # The environment override bypasses python-vlc's own macOS
                # core preload. Load both here so dependencies resolve in order
                # and retain the original dlopen error instead of SystemExit(1).
                core = os.path.join(os.path.dirname(lib), "libvlccore.dylib")
                mode = getattr(ctypes, "RTLD_GLOBAL", 0)
                _MAC_LIBS.append(ctypes.CDLL(core, mode=mode))
                _MAC_LIBS.append(ctypes.CDLL(lib, mode=mode))
                plugins = os.environ.get("PYTHON_VLC_MODULE_PATH")
                if plugins and not os.path.isdir(plugins):
                    raise ImportError(f"VLC plugin folder does not exist: {plugins}")
        sys.modules.pop("vlc", None)   # a failed earlier import may have left a module without libVLC
        import vlc as _vlc  # noqa: E402
        if getattr(_vlc, "dll", None) is None:
            raise ImportError("libVLC was not found")
        vlc = _vlc
        VLC_ERROR = None
        return True
    except (Exception, SystemExit) as e:  # pragma: no cover - depends on the machine
        sys.modules.pop("vlc", None)
        vlc = None
        VLC_ERROR = str(e) or e.__class__.__name__
        if isinstance(e, SystemExit):   # python-vlc exits when the DLL won't load
            VLC_ERROR = ("VLC's engine couldn't be loaded. Pylon needs VLC 3.0 for "
                         + ("64-bit Windows." if sys.platform == "win32" else "this computer."))
        return False


load_vlc()


def _pick_log_dir():
    from .store import data_dir
    for d in (os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs"),
              os.path.join(data_dir(), "logs")):
        try:
            os.makedirs(d, exist_ok=True)
            log = os.path.join(d, "vlc.log")
            if os.path.isfile(log) and os.path.getsize(log) > 2_000_000:
                os.remove(log)
            with open(os.path.join(d, ".write-test"), "w"):
                pass
            os.remove(os.path.join(d, ".write-test"))
            return d
        except OSError:
            continue
    return None


LOG_DIR = _pick_log_dir()


def _dec(b) -> str:
    if b is None:
        return ""
    if isinstance(b, bytes):
        return b.decode("utf-8", "replace")
    return str(b)


MAX_SHARPEN = 1.5  # strongest sharpening the slider offers (#36)
CUSTOM_EQ = -2     # live["eq"] value for the user's own 10-band curve (#38)
EQ_RANGE = 20.0    # VLC's equalizer works in -20..+20 dB
MAX_ZOOM = 8.0         # interactive zoom limit (#39)
AUDIO_WARMUP = 0.6     # seconds to wait before the first volume change on Linux (#28)

# DVD menus (libvlc_navigate_mode_t) and the flag VLC puts on a disc's menu title
NAV_ACTIVATE, NAV_UP, NAV_DOWN, NAV_LEFT, NAV_RIGHT = 0, 1, 2, 3, 4
TITLE_MENU = 1
RENDERER_SERVICES = ("microdns_renderer",)   # how VLC 3 finds Chromecasts on the network

DEFAULT_SUB_STYLE = {
    "size_mode": "relative",   # relative | precise
    "scale": 100,              # % for relative mode
    "px": 32,                  # pixels for precise mode
    "font": "",                # empty = VLC default
    "color": "#FFFFFF",
    "outline": 4,              # 0, 2, 4, 6
    "background": 0,           # 0-255 opacity of a box behind the text
    "bold": False,
    "margin": 0,               # px from bottom
}


class Engine(QObject):
    state_changed = Signal(str)        # opening, playing, paused, stopped, ended, error
    length_changed = Signal(int)
    media_changed = Signal(str)
    tracks_changed = Signal()
    vout_changed = Signal(int)
    wake_picture = Signal()           # Windows: give VLC's video area a nudge so the picture shows (#82)
    picture_changed = Signal()          # the picture's shape may have changed (aspect, crop, new video)
    renderers_changed = Signal()        # a cast device appeared or went away

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.instance = None
        self.player = None
        self.win_id = None
        self.current = None            # path or url currently loaded
        self.current_title = ""
        self.extra_subs: list[str] = []  # external subtitle files added to this media
        self.sub_style = dict(DEFAULT_SUB_STYLE)
        self.rotate, self.flip_h, self.flip_v = 0, False, False     # rotate and flip (#83)
        self.sharpen = 0.0             # 0 = off, else VLC sharpen strength (sigma, up to 1.5)
        self.live = {"rate": 1.0, "sub_delay": 0, "audio_delay": 0, "eq": -1, "eq_custom": None,
                     "aspect": "", "crop": "", "zoom": 0.0, "deinterlace": "",
                     "adjust": None}
        self._cb = []
        self._live_pending = False     # re-apply live settings once the new player plays
        self._held_ms = None           # position shown while a media is opened paused
        self._settle = None            # reopening paused: where to return once it plays (#36)
        self.izoom = None              # interactive zoom (#39): {"z", "x", "y", "w", "h"} in video pixels
        self.fit = None                # (w, h) device pixels of a video area sized to the picture (#42)
        self._fit_turn = 0             # which of the equivalent fill ratios is in use
        self._args_stale = False       # VLC options changed: start a new player at the next file
        self.vsr_paused = False        # Super Resolution set aside while the picture can't fill the screen (#42)
        self._last_seek_t = 0.0
        self._seek_target = None
        self._seek_timer = QTimer(self)
        self._seek_timer.setSingleShot(True)
        self._seek_timer.timeout.connect(self._seek_flush)
        self._discoverers = []           # renderer discoverers while looking for cast devices
        self._renderers = {}             # item pointer -> {"item", "name", "type"}
        self.renderer = None             # the cast device in use, or None for this computer
        # The picture filter (brightness, saturation...) only sticks once VLC has
        # made its video output, so apply it again whenever a new one appears.
        self.vout_changed.connect(self._on_vout, Qt.QueuedConnection)
        self.state_changed.connect(self._on_state_internal, Qt.QueuedConnection)
        if vlc is not None:
            self._build()

    # ------------------------------------------------------------------ rotate and flip
    @property
    def transform(self) -> str:
        """VLC's --transform-type for the rotation and flips together: "", 90, 180, 270, hflip, vflip,
        transpose or antitranspose."""
        return compose_transform(self.rotate, self.flip_h, self.flip_v)

    @transform.setter
    def transform(self, value: str):
        self.rotate, self.flip_h, self.flip_v = transform_parts(value)

    # ------------------------------------------------------------------ setup
    def _args(self) -> list[str]:
        st = self.sub_style
        args = ["--no-video-title-show", "--no-osd", "--no-snapshot-preview",
                "--avcodec-hw=" + ("any" if self.store.setting("hw_decoding") else "none")]
        if sys.platform.startswith("linux") and not any(a.startswith("--aout") for a in os.environ.get("PYLON_VLC_ARGS", "").split()):
            # Fedora's PipeWire add-on for VLC can crash when the volume is set before
            # playback starts (#28). Prefer VLC's PulseAudio output, which PipeWire also
            # serves on modern desktops, then ALSA, then whatever else is installed.
            args.append("--aout=pulse,alsa,any")
        if sys.platform == "win32" and self.store.setting("rtx_upscale") and not self.vsr_paused:
            # Lets NVIDIA RTX / Intel Video Super Resolution sharpen upscaled video (#42).
            # VLC falls back to its normal scaler on graphics that can't do it.
            args.append("--d3d11-upscale-mode=super")
        if st["size_mode"] == "precise":
            args.append(f"--freetype-fontsize={int(st['px'])}")
        else:
            args.append(f"--sub-text-scale={int(st['scale'])}")
        if st["font"]:
            args.append(f"--freetype-font={st['font']}")
        try:
            args.append(f"--freetype-color={int(st['color'].lstrip('#'), 16)}")
        except ValueError:
            pass
        args.append(f"--freetype-outline-thickness={int(st['outline'])}")
        if st["background"]:
            args += [f"--freetype-background-opacity={int(st['background'])}", "--freetype-background-color=0"]
        if st["bold"]:
            args.append("--freetype-bold")
        if st["margin"]:
            args.append(f"--sub-margin={int(st['margin'])}")
        args += VISUALIZERS.get(self.store.setting("visualizer"), VISUALIZERS[""])[1]
        filters = []
        if self.transform:
            filters.append("transform")
            args.append(f"--transform-type={self.transform}")
        if self.sharpen > 0:
            filters.append("sharpen")
            args.append(f"--sharpen-sigma={min(MAX_SHARPEN, float(self.sharpen)):.2f}")
        if filters:
            args.append("--video-filter=" + ":".join(filters))
        extra = os.environ.get("PYLON_VLC_ARGS", "").split()
        if extra:
            args += extra
        if LOG_DIR:
            args += ["--file-logging", f"--logfile={os.path.join(LOG_DIR, 'vlc.log')}", "--log-verbose=1"]
        return args

    def _build(self):
        self.instance = vlc.Instance(self._args())
        self.player = self.instance.media_player_new()
        self.player.video_set_mouse_input(False)
        self.player.video_set_key_input(False)
        # Fedora's PipeWire output for VLC can crash if the volume is set in the
        # first moments after the player is made (#28). On Linux, hold volume and
        # mute changes briefly and apply them once the output has settled.
        self._audio_ready_at = time.monotonic() + (AUDIO_WARMUP if sys.platform.startswith("linux") else 0)
        self._audio_pending = {}
        self._queue_audio(volume=int(self.store.setting("volume")))
        em = self.player.event_manager()
        E = vlc.EventType
        hooks = {
            E.MediaPlayerOpening: lambda e: self.state_changed.emit("opening"),
            E.MediaPlayerPlaying: lambda e: self.state_changed.emit("playing"),
            E.MediaPlayerPaused: lambda e: self.state_changed.emit("paused"),
            E.MediaPlayerStopped: lambda e: self.state_changed.emit("stopped"),
            E.MediaPlayerEndReached: lambda e: self.state_changed.emit("ended"),
            E.MediaPlayerEncounteredError: lambda e: self.state_changed.emit("error"),
            E.MediaPlayerLengthChanged: lambda e: self.length_changed.emit(0),
            E.MediaPlayerESAdded: lambda e: self.tracks_changed.emit(),
            E.MediaPlayerESDeleted: lambda e: self.tracks_changed.emit(),
            E.MediaPlayerVout: lambda e: self.vout_changed.emit(0),
        }
        # Never call back into libVLC from inside these handlers: they run on a
        # VLC thread and a nested call can deadlock playback. Only emit signals,
        # and don't trust event payloads (their layout differs between libVLC
        # builds); the GUI thread asks the player for the real values.
        self._cb = list(hooks.values())
        for ev, fn in hooks.items():
            em.event_attach(ev, fn)
        if self.win_id is not None:
            self._attach_window()
        if self.renderer is not None:       # a new player keeps casting to the same device
            self.player.set_renderer(self.renderer["item"])

    def _attach_window(self):
        if sys.platform == "win32":
            self.player.set_hwnd(self.win_id)
        elif sys.platform == "darwin":
            self.player.set_nsobject(self.win_id)
        else:
            self.player.set_xwindow(self.win_id)

    def set_window(self, win_id: int):
        self.win_id = int(win_id)
        if self.player:
            self._attach_window()

    @property
    def ok(self) -> bool:
        return self.player is not None

    def start_engine(self, folder: str = "") -> bool:
        """Load VLC now (after the user located it) and build the player."""
        if self.player is not None:
            return True
        if not load_vlc(folder):
            return False
        try:
            self._build()
        except Exception as e:
            global VLC_ERROR
            VLC_ERROR = str(e) or e.__class__.__name__
            self.instance = self.player = None
            return False
        return True

    # ------------------------------------------------------------------ media
    def open(self, target: str, start_ms: int = 0, subs: list[str] | None = None, title: str = "",
             paused: bool = False):
        if not self.ok:
            return
        if self._args_stale:          # an option VLC reads at start changed while a video played (#85)
            self._renew(self.volume())
        if not is_url(target):
            target = os.path.normpath(os.path.abspath(target))
        self.current = target
        self.current_title = title
        disc = is_disc(target)
        if is_url(target) or disc_mrl(target) != target:
            media = self.instance.media_new(disc_mrl(target))
        else:
            media = self.instance.media_new_path(target)
        if start_ms > 0 and not disc:     # a disc starts at its menu; the window resumes the title
            media.add_option(f":start-time={start_ms / 1000:.3f}")
        self._held_ms = None
        self._settle = None
        self.izoom = None              # each new file starts unzoomed
        if paused:
            # Come back to exactly the frame that was showing, without playing on (#36).
            # VLC on Windows draws nothing for a media opened with :start-paused, so
            # start it silently, pause as soon as it plays, then jump back to start_ms.
            self._held_ms = int(start_ms)
            self._settle = {"ms": int(start_ms), "vol": self.volume()}
            self._queue_audio(volume=0)
        self.player.set_media(media)
        self.extra_subs = []
        for s in subs or []:
            self.add_subtitle(s, select=True)
        self.player.play()
        self.media_changed.emit(target)

    def add_subtitle(self, path: str, select: bool = True):
        if not self.ok or not path:
            return
        uri = path if "://" in path else _file_uri(path)
        try:
            self.player.add_slave(vlc.MediaSlaveType.subtitle, uri, select)
        except Exception:
            self.player.video_set_subtitle_file(path)
        if path not in self.extra_subs:
            self.extra_subs.append(path)

    def rebuild(self):
        """Recreate the VLC instance (needed for subtitle font and rotate changes),
        then continue from the same point."""
        if vlc is None:
            return
        target, pos = self.current, self.time()
        was_playing = self.is_playing()
        subs = list(self.extra_subs)
        sub_id, audio_id = self.current_sub(), self.current_audio()
        vol = self.volume()
        self._renew(vol)
        if target:
            self._live_pending = True     # the new player starts with VLC defaults
            zoom = self.izoom
            def reopen():
                self.open(target, start_ms=pos, subs=subs, title=self.current_title, paused=not was_playing)
                self.izoom = zoom          # re-applied with the other live settings
                def restore():
                    if sub_id is not None:
                        self.set_sub(sub_id)
                    if audio_id is not None:
                        self.set_audio(audio_id)
                QTimer.singleShot(700, restore)
            wait = self._audio_wait_ms()
            if wait:       # reopening paused mutes the output, so let it settle first (#28)
                QTimer.singleShot(wait, reopen)
            else:
                reopen()

    def _renew(self, vol: int):
        """A new VLC instance and player with the current options, playing nothing yet."""
        self._args_stale = False
        looking = self._stop_discovery()
        try:
            self.player.stop()
            self.player.release()
            self.instance.release()
        except Exception:
            pass
        self._build()
        self._queue_audio(volume=vol)
        if looking:
            self.start_discovery()

    def video_track_count(self) -> int:
        if not self.ok:
            return 0
        try:
            return self.player.video_get_track_count() or 0
        except Exception:
            return 0

    def visualizing(self) -> bool:
        """True while VLC shows a visualization: a picture for sound with no video (#85)."""
        if not self.ok or not self.store.setting("visualizer"):
            return False
        try:
            return self.video_track_count() == 0 and bool(self.player.has_vout())
        except Exception:
            return False

    def set_visualizer(self, key: str) -> bool:
        """Pick a visualization (#85). VLC reads it only when the player starts, so sound that's playing
        now continues from the same spot with it; while a video plays, it's applied at the next file.
        True if the player was restarted."""
        if key not in VISUALIZERS:
            key = ""
        if key == (self.store.setting("visualizer") or ""):
            return False
        self.store.set_setting("visualizer", key)
        if self.current and self.video_track_count() == 0:
            self.rebuild()
            return True
        self._args_stale = True
        return False

    def set_vsr_paused(self, on: bool) -> bool:
        """Set Super Resolution aside, or bring it back (#42). VLC reads its upscaling mode only when the
        player is made, so this rebuilds the player and continues from the same point. Returns True if
        anything changed."""
        on = bool(on)
        if on == self.vsr_paused:
            return False
        self.vsr_paused = on
        if self.ok:
            self.rebuild()
        return True

    def recreate(self):
        """Rebuild the VLC instance without reopening anything (used when a
        preset with a different subtitle look is applied before playback)."""
        if vlc is None:
            return
        vol = self.volume()
        looking = self._stop_discovery()
        try:
            self.player.stop()
            self.player.release()
            self.instance.release()
        except Exception:
            pass
        self._build()
        self._queue_audio(volume=vol)
        if looking:
            self.start_discovery()

    def _on_vout(self, _n=0):
        if self.ok and self.live.get("adjust"):
            QTimer.singleShot(150, self._reapply_picture)
        self.picture_changed.emit()       # the video size is known now, or soon (a TS stream tells later)
        for ms in (400, 1500):
            QTimer.singleShot(ms, self.picture_changed.emit)
        if sys.platform == "win32":
            # Some Windows graphics drivers show subtitles but a black picture for hardware-decoded 10-bit
            # video (HEVC especially) until VLC's video area changes size (#82: opening a panel fixed it).
            # The window gives the area a one-off nudge once the first frames are out, and once more later.
            for ms in (300, 1200):
                QTimer.singleShot(ms, self.wake_picture.emit)

    def _reapply_picture(self):
        if not self.ok:
            return
        L = self.live
        if L.get("adjust"):
            self.set_adjust(L["adjust"], force=True)
        self._apply_crop()

    def _on_state_internal(self, state):
        if state == "playing":
            self._audio_ready_at = 0      # the output is running, so changes are safe now
            self._flush_audio()
        if state == "playing" and self._settle:
            settle, self._settle = self._settle, None
            self.player.set_pause(1)
            def back():
                self.player.set_time(settle["ms"])     # redraws the paused picture there
                QTimer.singleShot(150, lambda: self._queue_audio(volume=max(0, settle["vol"])))
            QTimer.singleShot(50, back)
        # a media reopened paused (#36) never reaches "playing", so apply there too
        if state in ("playing", "paused") and self._live_pending:
            self._live_pending = False
            self.apply_live()
            QTimer.singleShot(400, self._reapply_picture)

    def apply_live(self):
        """Re-apply per-session tweaks after a new media starts."""
        if not self.ok:
            return
        L = self.live
        self.player.set_rate(L["rate"])
        self.player.video_set_spu_delay(int(L["sub_delay"] * 1000))
        self.player.audio_set_delay(int(L["audio_delay"] * 1000))
        self.set_eq(L["eq"])
        self._apply_crop()
        self.player.video_set_deinterlace(L["deinterlace"] or None)
        if L["adjust"]:
            self.set_adjust(L["adjust"])

    # ------------------------------------------------------------------ transport
    def play(self):
        if self.ok:
            self.player.play()

    def pause(self):
        if self.ok and self.is_playing():
            self.player.set_pause(1)

    def toggle(self):
        if not self.ok:
            return
        if self.player.get_state() in (vlc.State.Ended, vlc.State.Stopped) and self.current:
            self.open(self.current, subs=self.extra_subs, title=self.current_title)
        else:
            self.player.pause()

    def stop(self):
        if self.ok:
            self.player.stop()

    def close(self):
        """Stop and let go of the file, so nothing is loaded any more (#61)."""
        if self.ok:
            self.player.stop()
            self.player.set_media(None)
        self.current = None
        self.current_title = ""
        self.extra_subs = []
        self.izoom = None
        self._held_ms = None
        self._settle = None

    def is_playing(self) -> bool:
        return bool(self.ok and self.player.is_playing())

    def state(self) -> str:
        if not self.ok:
            return "none"
        return str(self.player.get_state()).split(".")[-1].lower()

    def time(self) -> int:
        if not self.ok:
            return 0
        t = int(self.player.get_time() or 0)
        # VLC reports 0 for a media opened paused until it plays; show where it is
        if self._held_ms is not None:
            if t <= 0:
                return self._held_ms
            self._held_ms = None
        return t

    def length(self) -> int:
        return int(self.player.get_length() or 0) if self.ok else 0

    def finish(self):
        """End the file now, the way it ends by itself, so whatever comes next (the next song, a loop, the
        sleep timer) happens as usual. Used to skip the silence after a song (#86)."""
        if not self.ok:
            return
        self.player.set_position(1.0)

    def seek(self, ms: int):
        """Jump to ms. Requests that arrive while VLC is still finishing the last jump
        are merged, so only the latest one is applied (back-to-back jumps make the picture flicker)."""
        if not self.ok:
            return
        ln = self.length()
        ms = max(0, min(int(ms), ln - 500 if ln else int(ms)))
        if self._held_ms is not None:
            self._held_ms = ms
        now = time.monotonic()
        wait = 0.12 - (now - self._last_seek_t)
        if wait > 0:
            self._seek_target = ms
            if not self._seek_timer.isActive():
                self._seek_timer.start(int(wait * 1000) + 1)
            return
        self._do_seek(ms)

    def _do_seek(self, ms):
        self._seek_target = None
        self._last_seek_t = time.monotonic()
        if self.ok:
            self.player.set_time(int(ms))

    def _seek_flush(self):
        if self._seek_target is not None:
            self._do_seek(self._seek_target)

    def seek_by(self, delta_ms: int):
        self.seek(self.time() + delta_ms)

    def next_frame(self):
        if self.ok:
            self.player.next_frame()

    def frame_ms(self) -> int:
        """How long one frame of this video lasts, in ms (25 fps when VLC doesn't say)."""
        try:
            fps = float(self.player.get_fps() or 0) if self.ok else 0
        except Exception:
            fps = 0
        return max(1, round(1000 / fps)) if 1 <= fps <= 240 else 40

    def prev_frame(self):
        """Step back one frame. libVLC can only step forward, so pause and seek one frame back;
        VLC 3 seeks exactly, so the picture shows the frame before."""
        if not self.ok or not self.current:
            return
        if self.is_playing():
            self.player.set_pause(1)
        t = self._seek_target if self._seek_target is not None else self.time()
        self._seek_timer.stop()
        self._do_seek(max(0, int(t) - self.frame_ms()))

    def is_seekable(self) -> bool:
        return bool(self.ok and self.player.is_seekable())

    # ------------------------------------------------------------------ audio
    def _audio_wait_ms(self) -> int:
        return max(0, int((getattr(self, "_audio_ready_at", 0) - time.monotonic()) * 1000))

    def _queue_audio(self, **change):
        """Apply volume/mute now, or once the audio output has settled (#28)."""
        if not self.ok:
            return
        self._audio_pending.update(change)
        wait = self._audio_wait_ms()
        if wait:
            QTimer.singleShot(wait + 20, self._flush_audio)
        else:
            self._flush_audio()

    def _flush_audio(self):
        if not self.ok or not self._audio_pending or self._audio_wait_ms():
            return
        pending, self._audio_pending = self._audio_pending, {}
        if "volume" in pending:
            self.player.audio_set_volume(int(pending["volume"]))
        if "mute" in pending:
            self.player.audio_set_mute(bool(pending["mute"]))

    def volume(self) -> int:
        if self.ok and "volume" in self._audio_pending:
            return int(self._audio_pending["volume"])
        v = self.player.audio_get_volume() if self.ok else -1
        return int(v) if v is not None and v >= 0 else int(self.store.setting("volume"))

    def max_volume(self) -> int:
        m = self.store.setting("max_volume")
        return m if m in (125, 150, 200) else 125

    def set_volume(self, v: int):
        v = max(0, min(self.max_volume(), int(v)))
        self._queue_audio(volume=v)
        self.store.data["settings"]["volume"] = v
        self.store.save()

    def is_muted(self) -> bool:
        if self.ok and "mute" in self._audio_pending:
            return bool(self._audio_pending["mute"])
        return bool(self.ok and self.player.audio_get_mute() == 1)

    def set_muted(self, m: bool):
        self._queue_audio(mute=bool(m))

    def audio_tracks(self) -> list[tuple[int, str]]:
        if not self.ok:
            return []
        return [(i, _dec(n)) for i, n in (self.player.audio_get_track_description() or [])]

    def current_audio(self):
        return self.player.audio_get_track() if self.ok else None

    def set_audio(self, tid: int):
        if self.ok:
            self.player.audio_set_track(int(tid))

    def set_audio_delay(self, ms: int):
        self.live["audio_delay"] = int(ms)
        if self.ok:
            self.player.audio_set_delay(int(ms) * 1000)

    def audio_devices(self) -> list[tuple[str, str]]:
        if not self.ok:
            return []
        out = []
        head = self.player.audio_output_device_enum()
        if head:
            node = head
            while node:
                c = node.contents
                out.append((_dec(c.device), _dec(c.description)))
                node = c.next
            try:
                vlc.libvlc_audio_output_device_list_release(head)
            except Exception:
                pass
        return out

    def current_device(self) -> str:
        try:
            return _dec(self.player.audio_output_device_get()) if self.ok else ""
        except Exception:
            return ""

    def set_device(self, device_id: str):
        if self.ok:
            self.player.audio_output_device_set(None, device_id)

    def eq_presets(self) -> list[str]:
        if vlc is None:
            return []
        try:
            n = vlc.libvlc_audio_equalizer_get_preset_count()
            return [_dec(vlc.libvlc_audio_equalizer_get_preset_name(i)) for i in range(n)]
        except Exception:
            return []

    def eq_bands(self) -> list[float]:
        """Centre frequency (Hz) of each equalizer band; VLC always has 10."""
        if vlc is None:
            return []
        try:
            return [float(vlc.libvlc_audio_equalizer_get_band_frequency(i))
                    for i in range(vlc.libvlc_audio_equalizer_get_band_count())]
        except Exception:
            return []

    def eq_preset_curve(self, index: int) -> dict:
        """A preset's preamp and band gains, used as the starting point for a custom curve."""
        n = len(self.eq_bands()) or 10
        flat = {"preamp": 0.0, "bands": [0.0] * n}
        if vlc is None or index is None or index < 0:
            return flat
        eq = None
        try:
            eq = vlc.libvlc_audio_equalizer_new_from_preset(index)
            return {"preamp": round(float(vlc.libvlc_audio_equalizer_get_preamp(eq)), 1),
                    "bands": [round(float(vlc.libvlc_audio_equalizer_get_amp_at_index(eq, i)), 1) for i in range(n)]}
        except Exception:
            return flat
        finally:
            if eq:
                vlc.libvlc_audio_equalizer_release(eq)

    @staticmethod
    def clean_curve(curve) -> dict | None:
        """Validate a stored custom curve (from settings or a preset file)."""
        try:
            pre = max(-EQ_RANGE, min(EQ_RANGE, float(curve["preamp"])))
            bands = [max(-EQ_RANGE, min(EQ_RANGE, float(b))) for b in curve["bands"]][:10]
        except (TypeError, ValueError, KeyError):
            return None
        return {"preamp": pre, "bands": bands + [0.0] * (10 - len(bands))}

    def set_custom_eq(self, curve: dict):
        self.live["eq_custom"] = self.clean_curve(curve)
        self.set_eq(CUSTOM_EQ)

    def set_eq(self, index: int):
        self.live["eq"] = index
        if not self.ok:
            return
        if index is None or (index < 0 and index != CUSTOM_EQ):
            self.player.set_equalizer(None)
            return
        if index == CUSTOM_EQ:
            curve = self.clean_curve(self.live.get("eq_custom")) or self.eq_preset_curve(-1)
            eq = vlc.libvlc_audio_equalizer_new()
            vlc.libvlc_audio_equalizer_set_preamp(eq, curve["preamp"])
            for i, amp in enumerate(curve["bands"]):
                vlc.libvlc_audio_equalizer_set_amp_at_index(eq, amp, i)
        else:
            eq = vlc.libvlc_audio_equalizer_new_from_preset(index)
        # the player copies the settings, so the previous object can go
        self.player.set_equalizer(eq)
        old, self._eq = getattr(self, "_eq", None), eq
        if old:
            vlc.libvlc_audio_equalizer_release(old)

    # ------------------------------------------------------------------ subtitles
    def sub_tracks(self) -> list[tuple[int, str]]:
        if not self.ok:
            return []
        return [(i, _dec(n)) for i, n in (self.player.video_get_spu_description() or [])]

    def current_sub(self):
        return self.player.video_get_spu() if self.ok else None

    def set_sub(self, tid: int):
        if self.ok:
            self.player.video_set_spu(int(tid))

    def set_sub_delay(self, ms: int):
        self.live["sub_delay"] = int(ms)
        if self.ok:
            self.player.video_set_spu_delay(int(ms) * 1000)

    # ------------------------------------------------------------------ video
    def video_tracks(self) -> list[tuple[int, str]]:
        if not self.ok:
            return []
        return [(i, _dec(n)) for i, n in (self.player.video_get_track_description() or [])]

    def current_video(self):
        return self.player.video_get_track() if self.ok else None

    def set_video(self, tid: int):
        if self.ok:
            self.player.video_set_track(int(tid))

    def has_video(self) -> bool:
        if not self.ok:
            return False
        try:
            return (self.player.video_get_track_count() or 0) > 0 or bool(self.player.has_vout())
        except Exception:
            return False

    def set_rate(self, r: float):
        self.live["rate"] = float(r)
        if self.ok:
            self.player.set_rate(float(r))

    def rate(self) -> float:
        return float(self.live["rate"])

    def set_aspect(self, a: str):
        self.live["aspect"] = a
        if self.ok:
            self._apply_crop()
        self.picture_changed.emit()

    def set_crop(self, c: str):
        self.live["crop"] = c
        self.izoom = None
        if self.ok:
            self._apply_crop()
        self.picture_changed.emit()

    def set_zoom(self, z: float):
        self.live["zoom"] = float(z)
        self.izoom = None
        if self.ok:
            self._apply_crop()
        self.picture_changed.emit()

    # ------------------------------------------------------------------ interactive zoom (#39)
    def video_size(self) -> tuple[int, int]:
        if not self.ok:
            return 0, 0
        try:
            w, h = self.player.video_get_size(0)
            return int(w or 0), int(h or 0)
        except Exception:
            return 0, 0

    # ------------------------------------------------------------------ picture fitted to its area (#42)
    def _source_sar(self, vw: int, vh: int) -> Fraction:
        """The shape of one source pixel: from the aspect ratio the user picked, else the video's own."""
        a = self.live["aspect"]
        if a and ":" in a:
            try:
                num, den = (int(x) for x in a.split(":"))
                if num > 0 and den > 0:
                    return Fraction(num * vh, den * vw)
            except ValueError:
                pass
        try:
            tid = self.player.video_get_track()
            for t in self.player.get_media().tracks_get() or ():
                if t.type == vlc.TrackType.video and (t.id == tid or tid is None or tid < 0):
                    v = _video_track(t)
                    if v is not None and v.sar_num and v.sar_den:
                        return Fraction(v.sar_num, v.sar_den)
                    break
        except Exception:
            pass
        return Fraction(1)

    def _crop_borders(self, vw: int, vh: int, sar: Fraction):
        """(left, top, right, bottom) in video pixels for the crop or interactive zoom, (0, 0, 0, 0) for
        none, or None for a crop Pylon can't work out. A ratio is cut the way VLC does (VoutDisplayCropRatio)."""
        z = self.izoom
        if z:
            left, top = round(z["x"]), round(z["y"])
            return (left, top, max(0, vw - left - round(z["w"])), max(0, vh - top - round(z["h"])))
        c = self.live["crop"]
        if not c:
            return 0, 0, 0, 0
        try:
            num, den = (int(x) for x in c.split(":"))
        except ValueError:
            return None
        if num <= 0 or den <= 0:
            return None
        scaled_w = vh * num * sar.denominator // den // sar.numerator
        scaled_h = vw * den * sar.numerator // num // sar.denominator
        if scaled_w < vw:
            left = (vw - scaled_w) // 2
            return left, 0, vw - left - scaled_w, 0
        top = (vh - scaled_h) // 2
        return 0, top, 0, max(0, vh - top - scaled_h)

    def picture_shape(self):
        """How the picture will look, for sizing the video area to it: {"aspect": width / height as shown,
        "src", "crop": (l, t, r, b)}. None when VLC sizes the picture itself (a fixed zoom such as 1x),
        when the size isn't known yet, or for a turned picture with a crop."""
        if not self.ok or self.live["zoom"]:
            return None
        vw, vh = self.video_size()
        if vw <= 0 or vh <= 0:
            return None
        sar = self._source_sar(vw, vh)
        crop = self._crop_borders(vw, vh, sar)
        turned = self.transform in ("90", "270", "transpose", "antitranspose")
        if crop is None or (turned and any(crop)):
            return None
        cw, ch = vw - crop[0] - crop[2], vh - crop[1] - crop[3]
        if cw <= 0 or ch <= 0:
            return None
        aspect = Fraction(cw) * sar / ch
        return {"aspect": 1 / aspect if turned else aspect, "src": (vw, vh), "crop": crop}

    def set_fit(self, size):
        """With Super Resolution on, the window sizes VLC's video area to the picture and tells us its size
        in device pixels (None to stop). VLC is then given an aspect ratio that fills it to the pixel (#42)."""
        size = tuple(size) if size else None
        if size != self.fit:
            self.fit = size
            if self.ok:
                self._apply_crop()

    def _fit_plan(self):
        """(aspect "a:b", crop string or None) that fills self.fit exactly, or None."""
        shape = self.fit and self.picture_shape()
        if not shape:
            return None
        (vw, vh), borders = shape["src"], shape["crop"]
        left, top, right, bottom = borders
        crop = (vw - left - right, vh - top - bottom)
        if self.transform in ("90", "270", "transpose", "antitranspose"):
            vw, vh = vh, vw                 # VLC sees the turned picture (never cropped here)
            crop = (vw, vh)
        ratios = fill_aspects(self.fit, crop, (vw, vh))
        if not ratios:
            return None
        num, den = ratios[self._fit_turn % len(ratios)]
        return f"{num}:{den}", ("+".join(map(str, borders)) if any(borders) else None)

    def _apply_crop(self):
        """Interactive zoom is a moving crop window; without it, the sidebar's crop and zoom apply.
        The aspect ratio goes with it, since a video area sized to the picture needs both (#42)."""
        if not self.ok:
            return
        plan = self._fit_plan()
        if plan:
            aspect, crop = plan
            self.player.video_set_scale(0)
            self.player.video_set_crop_geometry(crop)
            self.player.video_set_aspect_ratio(aspect)
            return
        self.player.video_set_aspect_ratio(self.live["aspect"] or None)
        z = self.izoom
        if z:
            # Use VLC's border form "left+top+right+bottom". VLC 3 reads the window
            # form "WxH+X+Y" as edges rather than a size, which gave the wrong area (#41).
            vw, vh = self.video_size()
            left, top = round(z["x"]), round(z["y"])
            right = max(0, vw - left - round(z["w"]))
            bottom = max(0, vh - top - round(z["h"]))
            self.player.video_set_scale(0)
            self.player.video_set_crop_geometry(f"{left}+{top}+{right}+{bottom}")
        else:
            self.player.video_set_crop_geometry(self.live["crop"] or None)
            self.player.video_set_scale(self.live["zoom"])

    def refresh_upscaler(self):
        """VLC 3 only resizes its Super Resolution picture when the crop, aspect or zoom
        changes, not when the window does (#42). A brief 2-pixel crop, put straight back,
        makes it redraw at the current size without restarting playback."""
        if not self.ok:
            return
        if self._fit_plan():
            # The picture fills its area: switch to the other ratio that fills it just as exactly.
            # VLC sees a change and redraws, and there's never a letterbox, even for a moment.
            self._fit_turn += 1
            self._apply_crop()
            return
        vw, vh = self.video_size()
        if not vw or vh < 4:
            return
        self.player.video_set_crop_geometry("0+0+0+2")
        QTimer.singleShot(80, self._apply_crop)

    def zoom_level(self) -> float:
        return self.izoom["z"] if self.izoom else 1.0

    def zoom_at(self, factor: float, fx: float = 0.5, fy: float = 0.5) -> float:
        """Zoom by factor, keeping the point at (fx, fy) of the visible picture (0..1) still."""
        vw, vh = self.video_size()
        if not vw or not vh:
            return 1.0
        cur = self.izoom or {"z": 1.0, "x": 0.0, "y": 0.0, "w": float(vw), "h": float(vh)}
        z = max(1.0, min(MAX_ZOOM, cur["z"] * factor))
        if z < 1.01:
            self.reset_zoom()
            return 1.0
        fx, fy = max(0.0, min(1.0, fx)), max(0.0, min(1.0, fy))
        w, h = vw / z, vh / z
        sx, sy = cur["x"] + fx * cur["w"], cur["y"] + fy * cur["h"]
        x = max(0.0, min(vw - w, sx - fx * w))
        y = max(0.0, min(vh - h, sy - fy * h))
        self.izoom = {"z": z, "x": x, "y": y, "w": w, "h": h}
        self._apply_crop()
        return z

    def pan_by(self, dfx: float, dfy: float):
        """Move the zoomed view by a fraction of the visible picture (drag right = see more on the left)."""
        z = self.izoom
        if not z:
            return
        vw, vh = self.video_size()
        if not vw or not vh:
            return
        z["x"] = max(0.0, min(vw - z["w"], z["x"] - dfx * z["w"]))
        z["y"] = max(0.0, min(vh - z["h"], z["y"] - dfy * z["h"]))
        self._apply_crop()

    def reset_zoom(self):
        self.izoom = None
        if self.ok:
            self._apply_crop()

    def set_deinterlace(self, mode: str):
        self.live["deinterlace"] = mode
        if self.ok:
            self.player.video_set_deinterlace(mode or None)

    def set_adjust(self, adj: dict | None, force: bool = False):
        """adj: {brightness, contrast, saturation, hue, gamma} or None to disable."""
        self.live["adjust"] = adj
        if not self.ok:
            return
        A = vlc.VideoAdjustOption
        if not adj:
            self.player.video_set_adjust_int(A.Enable, 0)
            return
        if force:
            # a reused or brand-new video output can miss the filter; switch it off and on
            self.player.video_set_adjust_int(A.Enable, 0)
        self.player.video_set_adjust_int(A.Enable, 1)
        self.player.video_set_adjust_float(A.Brightness, float(adj.get("brightness", 1.0)))
        self.player.video_set_adjust_float(A.Contrast, float(adj.get("contrast", 1.0)))
        self.player.video_set_adjust_float(A.Saturation, float(adj.get("saturation", 1.0)))
        self.player.video_set_adjust_float(A.Hue, float(adj.get("hue", 0.0)))
        self.player.video_set_adjust_float(A.Gamma, float(adj.get("gamma", 1.0)))

    def snapshot(self, folder: str) -> bool:
        if not self.ok:
            return False
        return self.player.video_take_snapshot(0, folder, 0, 0) == 0

    # ------------------------------------------------------------------ chapters
    def chapters(self) -> list[tuple[int, str, int]]:
        """[(index, name, start_ms)]"""
        if not self.ok:
            return []
        out = []
        try:
            descs = self.player.get_full_chapter_descriptions(-1)
            for i, d in enumerate(descs or []):
                out.append((i, _dec(d.name) or f"Chapter {i + 1}", int(d.time_offset)))
        except Exception:
            try:
                for cid, name in self.player.video_get_chapter_description(-1) or []:
                    out.append((cid, _dec(name), -1))
            except Exception:
                pass
        return out

    def set_chapter(self, idx: int):
        if self.ok:
            self.player.set_chapter(int(idx))

    # ------------------------------------------------------------------ discs (DVD .iso and folders)
    def is_disc(self) -> bool:
        return bool(self.current) and is_disc(self.current)

    def titles(self) -> list[tuple[int, str, int, bool]]:
        """[(index, name, length_ms, is_menu)] for a disc; empty for anything else."""
        if not self.ok or not self.is_disc():
            return []
        out = []
        try:
            for i, t in enumerate(self.player.get_full_title_descriptions() or []):
                menu = bool(t.flags & TITLE_MENU)
                out.append((i, _dec(t.name) or ("Disc menu" if menu else f"Title {i}"), int(t.duration or 0), menu))
        except Exception:
            pass
        return out

    def title(self) -> int:
        try:
            return int(self.player.get_title()) if self.ok else -1
        except Exception:
            return -1

    def set_title(self, idx: int):
        if self.ok:
            self.player.set_title(int(idx))

    def in_menu(self) -> bool:
        """True while a disc shows one of its menus, where the arrow keys move between buttons."""
        if not self.is_disc():
            return False
        cur = self.title()
        return any(i == cur and menu for i, _n, _d, menu in self.titles())

    def navigate(self, mode: int):
        if self.ok:
            self.player.navigate(int(mode))

    def disc_menu(self) -> bool:
        """Go back to the disc's menu, if it has one."""
        menu = next((i for i, _n, _d, m in self.titles() if m), None)
        if menu is None:
            return False
        self.set_title(menu)
        return True

    # ------------------------------------------------------------------ casting (Chromecast)
    def start_discovery(self):
        """Look for cast devices on the local network. Only runs once you open the Cast menu."""
        if not self.ok or self._discoverers:
            return
        E = vlc.EventType
        for name in RENDERER_SERVICES:
            try:
                rd = self.instance.renderer_discoverer_new(name)
            except Exception:
                rd = None
            if rd is None:
                continue
            em = rd.event_manager()
            # These run on a VLC thread: only take a reference to the item and signal the GUI.
            cb_add = lambda e: self._renderer_event(e, True)
            cb_del = lambda e: self._renderer_event(e, False)
            em.event_attach(E.RendererDiscovererItemAdded, cb_add)
            em.event_attach(E.RendererDiscovererItemDeleted, cb_del)
            try:
                if rd.start() != 0:
                    rd.release()
                    continue
            except Exception:
                continue
            self._discoverers.append((rd, cb_add, cb_del))

    def _renderer_event(self, event, added):
        try:
            # python-vlc doesn't describe this event's payload; it is the item pointer
            ptr = ctypes.c_void_p.from_address(ctypes.addressof(event.u)).value
        except Exception:
            return
        if not ptr:
            return
        if added and ptr not in self._renderers:
            item = vlc._Constructor(vlc.Renderer, ptr)
            item.hold()
            self._renderers[ptr] = {"item": item, "name": _dec(item.name()) or "Cast device",
                                    "type": _dec(item.type()), "key": ptr}
        elif not added:
            gone = self._renderers.pop(ptr, None)
            if gone is not None and (self.renderer is None or self.renderer["key"] != ptr):
                self._dropped = getattr(self, "_dropped", []) + [gone]   # released on the GUI thread
        self.renderers_changed.emit()

    def renderers(self) -> list[dict]:
        for gone in getattr(self, "_dropped", []):
            try:
                gone["item"].release()
            except Exception:
                pass
        self._dropped = []
        return sorted(self._renderers.values(), key=lambda r: r["name"].casefold())

    def looking_for_renderers(self) -> bool:
        return bool(self._discoverers)

    def _stop_discovery(self) -> bool:
        was = bool(self._discoverers)
        for rd, _a, _d in self._discoverers:
            try:
                rd.stop()
                rd.release()
            except Exception:
                pass
        self._discoverers = []
        return was

    def cast_to(self, renderer: dict | None):
        """Send playback to a cast device, or back to this computer with None. VLC only uses a new
        device for the next play, so the current file is opened again at the same point."""
        if not self.ok:
            return
        self.renderer = renderer
        self.player.set_renderer(renderer["item"] if renderer else None)
        if self.current:
            pos, was_playing = self.time(), self.is_playing()
            self.open(self.current, start_ms=pos, subs=list(self.extra_subs), title=self.current_title,
                      paused=not was_playing)

    # ------------------------------------------------------------------ metadata
    def meta(self) -> dict:
        if not self.ok:
            return {}
        m = self.player.get_media()
        if not m:
            return {}
        M = vlc.Meta
        out = {}
        for key, k in (("title", M.Title), ("artist", M.Artist), ("album", M.Album),
                       ("genre", M.Genre), ("date", M.Date), ("art", M.ArtworkURL),
                       ("now_playing", M.NowPlaying)):
            try:
                v = m.get_meta(k)
            except Exception:
                v = None
            if v:
                out[key] = _dec(v)
        return out

    def shutdown(self):
        if self.ok:
            self._stop_discovery()
            try:
                self.player.stop()
                self.player.release()
                self.instance.release()
            except Exception:
                pass
            self.player = None


def _file_uri(path: str) -> str:
    from pathlib import Path
    return Path(os.path.abspath(path)).as_uri()
