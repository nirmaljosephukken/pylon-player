"""Thin wrapper around libVLC (python-vlc).

Everything VLC-specific lives here so the UI never touches the binding
directly. libVLC events arrive on a VLC thread; they are re-emitted as Qt
signals, which Qt delivers on the GUI thread.
"""
import os
import sys
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from .util import is_url

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
        self.transform = ""            # "", 90, 180, 270, hflip, vflip
        self.sharpen = 0.0             # 0 = off, else VLC sharpen strength (sigma, up to 2)
        self.live = {"rate": 1.0, "sub_delay": 0, "audio_delay": 0, "eq": -1,
                     "aspect": "", "crop": "", "zoom": 0.0, "deinterlace": "",
                     "adjust": None}
        self._cb = []
        self._live_pending = False     # re-apply live settings once the new player plays
        self._last_seek_t = 0.0
        self._seek_target = None
        self._seek_timer = QTimer(self)
        self._seek_timer.setSingleShot(True)
        self._seek_timer.timeout.connect(self._seek_flush)
        # The picture filter (brightness, saturation...) only sticks once VLC has
        # made its video output, so apply it again whenever a new one appears.
        self.vout_changed.connect(self._on_vout, Qt.QueuedConnection)
        self.state_changed.connect(self._on_state_internal, Qt.QueuedConnection)
        if vlc is not None:
            self._build()

    # ------------------------------------------------------------------ setup
    def _args(self) -> list[str]:
        st = self.sub_style
        args = ["--no-video-title-show", "--no-osd", "--no-snapshot-preview",
                "--avcodec-hw=" + ("any" if self.store.setting("hw_decoding") else "none")]
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
        filters = []
        if self.transform:
            filters.append("transform")
            args.append(f"--transform-type={self.transform}")
        if self.sharpen > 0:
            filters.append("sharpen")
            args.append(f"--sharpen-sigma={min(2.0, float(self.sharpen)):.2f}")
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
        self.player.audio_set_volume(int(self.store.setting("volume")))
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
    def open(self, target: str, start_ms: int = 0, subs: list[str] | None = None, title: str = ""):
        if not self.ok:
            return
        if not is_url(target):
            target = os.path.normpath(os.path.abspath(target))
        self.current = target
        self.current_title = title
        if is_url(target):
            media = self.instance.media_new(target)
        else:
            media = self.instance.media_new_path(target)
        if start_ms > 0:
            media.add_option(f":start-time={start_ms / 1000:.3f}")
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
        try:
            self.player.stop()
            self.player.release()
            self.instance.release()
        except Exception:
            pass
        self._build()
        self.player.audio_set_volume(vol)
        if target:
            self._live_pending = True     # the new player starts with VLC defaults
            self.open(target, start_ms=pos, subs=subs, title=self.current_title)
            def restore():
                if sub_id is not None:
                    self.set_sub(sub_id)
                if audio_id is not None:
                    self.set_audio(audio_id)
                if not was_playing:
                    self.pause()
            QTimer.singleShot(700, restore)

    def recreate(self):
        """Rebuild the VLC instance without reopening anything (used when a
        preset with a different subtitle look is applied before playback)."""
        if vlc is None:
            return
        vol = self.volume()
        try:
            self.player.stop()
            self.player.release()
            self.instance.release()
        except Exception:
            pass
        self._build()
        self.player.audio_set_volume(vol)

    def _on_vout(self, _n=0):
        if self.ok and self.live.get("adjust"):
            QTimer.singleShot(150, self._reapply_picture)

    def _reapply_picture(self):
        if not self.ok:
            return
        L = self.live
        if L.get("adjust"):
            self.set_adjust(L["adjust"], force=True)
        self.player.video_set_aspect_ratio(L["aspect"] or None)
        self.player.video_set_crop_geometry(L["crop"] or None)
        self.player.video_set_scale(L["zoom"])

    def _on_state_internal(self, state):
        if state == "playing" and self._live_pending:
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
        self.player.video_set_aspect_ratio(L["aspect"] or None)
        self.player.video_set_crop_geometry(L["crop"] or None)
        self.player.video_set_scale(L["zoom"])
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

    def is_playing(self) -> bool:
        return bool(self.ok and self.player.is_playing())

    def state(self) -> str:
        if not self.ok:
            return "none"
        return str(self.player.get_state()).split(".")[-1].lower()

    def time(self) -> int:
        return int(self.player.get_time() or 0) if self.ok else 0

    def length(self) -> int:
        return int(self.player.get_length() or 0) if self.ok else 0

    def seek(self, ms: int):
        """Jump to ms. Requests that arrive while VLC is still finishing the last jump
        are merged, so only the latest one is applied (back-to-back jumps make the picture flicker)."""
        if not self.ok:
            return
        ln = self.length()
        ms = max(0, min(int(ms), ln - 500 if ln else int(ms)))
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

    def is_seekable(self) -> bool:
        return bool(self.ok and self.player.is_seekable())

    # ------------------------------------------------------------------ audio
    def volume(self) -> int:
        v = self.player.audio_get_volume() if self.ok else -1
        return int(v) if v is not None and v >= 0 else int(self.store.setting("volume"))

    def set_volume(self, v: int):
        v = max(0, min(125, int(v)))
        if self.ok:
            self.player.audio_set_volume(v)
        self.store.data["settings"]["volume"] = v
        self.store.save()

    def is_muted(self) -> bool:
        return bool(self.ok and self.player.audio_get_mute() == 1)

    def set_muted(self, m: bool):
        if self.ok:
            self.player.audio_set_mute(bool(m))

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

    def set_eq(self, index: int):
        self.live["eq"] = index
        if not self.ok:
            return
        if index is None or index < 0:
            self.player.set_equalizer(None)
            return
        self._eq = vlc.libvlc_audio_equalizer_new_from_preset(index)
        self.player.set_equalizer(self._eq)

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
            self.player.video_set_aspect_ratio(a or None)

    def set_crop(self, c: str):
        self.live["crop"] = c
        if self.ok:
            self.player.video_set_crop_geometry(c or None)

    def set_zoom(self, z: float):
        self.live["zoom"] = float(z)
        if self.ok:
            self.player.video_set_scale(float(z))

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

    def video_size(self) -> tuple[int, int]:
        try:
            w, h = self.player.video_get_size(0)
            return int(w), int(h)
        except Exception:
            return 0, 0

    def shutdown(self):
        if self.ok:
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
