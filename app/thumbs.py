"""Seek-bar previews.

A second, silent libVLC player decodes the open video in the background and
grabs small frames at regular intervals (video callbacks write each frame into
a buffer we own). Frames are cached on disk as one JPEG "contact sheet" per
file, so reopening a file shows previews instantly.

libVLC 3 has no thumbnail API, which is why this uses its own player. It only
runs for local video files, and never touches the main player.
"""
import ctypes
import hashlib
import json
import os
import threading
import time

from PySide6.QtCore import QObject, QRect, Qt, Signal
from PySide6.QtGui import QImage, QPainter

from . import engine as engine_mod
from .store import data_dir

THUMB_W = 320          # pixels; shown at about half size on normal screens
MAX_THUMBS = 150
MIN_STEP_MS = 2000
COLS = 10
CACHE_FILES = 300      # keep at most this many sheets on disk


def _cache_dir() -> str:
    d = os.path.join(data_dir(), "thumbs")
    os.makedirs(d, exist_ok=True)
    return d


def _key(path: str) -> str:
    try:
        st = os.stat(path)
        sig = f"{os.path.normcase(os.path.abspath(path))}|{st.st_size}|{int(st.st_mtime)}"
    except OSError:
        sig = path
    return hashlib.sha1(sig.encode("utf-8", "replace")).hexdigest()[:20]


def _prune_cache():
    try:
        d = _cache_dir()
        files = sorted((os.path.join(d, f) for f in os.listdir(d) if f.endswith(".jpg")), key=os.path.getmtime)
        for f in files[:-CACHE_FILES]:
            for ext in (".jpg", ".json"):
                try:
                    os.remove(f[:-4] + ext)
                except OSError:
                    pass
    except OSError:
        pass


class ThumbnailMaker(QObject):
    """Makes and serves preview frames for one file at a time."""
    progress = Signal(str, int, int)    # path, done, total

    def __init__(self, parent=None):
        super().__init__(parent)
        self.path = None
        self.step = 0
        self.size = (THUMB_W, 180)
        self.timestamps: dict[int, int] = {}
        self.frames: dict[int, QImage] = {}   # index -> image
        self.total = 0
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ public
    def start(self, path: str, length_ms: int, video_size: tuple[int, int]):
        """Begin making previews for `path` (cancels any file in progress)."""
        self.cancel()
        vlc = engine_mod.vlc
        if vlc is None or not path or length_ms <= 0 or not os.path.isfile(path):
            return
        vw, vh = video_size if video_size and video_size[0] > 0 and video_size[1] > 0 else (16, 9)
        h = max(60, min(320, int(round(THUMB_W * vh / vw / 2)) * 2))
        self.path = path
        self.size = (THUMB_W, h)
        self.step = max(MIN_STEP_MS, length_ms // MAX_THUMBS)
        self.total = min(MAX_THUMBS, max(1, length_ms // self.step))
        self.frames = {}
        self.timestamps = {}
        if self._load_cache():
            self.progress.emit(path, self.total, self.total)
            return
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(path, self._stop), daemon=True)
        self._thread.start()

    def cancel(self):
        if self._thread and self._thread.is_alive():
            self._stop.set()
            self._thread.join(timeout=3)
        self._thread = None
        self.path = None
        self.frames = {}
        self.timestamps = {}

    def preview_at(self, ms: int):
        """Image and recorded playback time belonging to the same cached sample."""
        with self._lock:
            if not self.frames or self.step <= 0:
                return None, None
            i = min(self.frames, key=lambda k: abs(k * self.step - ms))
            if abs(i * self.step - ms) > max(30_000, self.step * 12):
                return None, None
            return self.frames[i], self.timestamps.get(i, i * self.step)

    def frame_at(self, ms: int):
        """Nearest finished preview to `ms`, or None."""
        return self.preview_at(ms)[0]

    # ------------------------------------------------------------------ cache
    def _sheet_paths(self, path):
        base = os.path.join(_cache_dir(), _key(path))
        return base + ".jpg", base + ".json"

    def _load_cache(self) -> bool:
        jpg, meta = self._sheet_paths(self.path)
        try:
            with open(meta, encoding="utf-8") as f:
                info = json.load(f)
            if info.get("version") != 2 or info.get("step") != self.step or info.get("w") != self.size[0]:
                return False
            sheet = QImage(jpg)
            if sheet.isNull():
                return False
        except (OSError, ValueError):
            return False
        w, h = info["w"], info["h"]
        for i in info["have"]:
            r, c = divmod(i, COLS)
            self.frames[i] = sheet.copy(QRect(c * w, r * h, w, h))
            self.timestamps[i] = int(info["timestamps"][str(i)])
        self.size = (w, h)
        try:
            os.utime(jpg)
        except OSError:
            pass
        return True

    def _save_cache(self, path, frames, size, step, timestamps):
        if not frames:
            return
        w, h = size
        rows = (max(frames) // COLS) + 1
        sheet = QImage(w * COLS, h * rows, QImage.Format_RGB32)
        sheet.fill(Qt.black)
        p = QPainter(sheet)
        for i, img in frames.items():
            r, c = divmod(i, COLS)
            p.drawImage(c * w, r * h, img)
        p.end()
        jpg, meta = self._sheet_paths(path)
        if sheet.save(jpg, "JPG", 82):
            with open(meta, "w", encoding="utf-8") as f:
                json.dump({"version": 2, "w": w, "h": h, "step": step,
                           "have": sorted(frames), "timestamps": timestamps}, f)
            _prune_cache()

    # ------------------------------------------------------------------ worker
    def _order(self):
        """Every 8th frame first (so the whole bar gets previews quickly), then the rest."""
        coarse = list(range(0, self.total, 8))
        return coarse + [i for i in range(self.total) if i % 8]

    def _run(self, path, stop):
        try:
            self._grab(path, stop)
        except Exception:
            pass

    def _grab(self, path, stop):
        vlc = engine_mod.vlc
        w, h = self.size
        step, total = self.step, self.total
        buf = (ctypes.c_ubyte * (w * h * 4))()
        count = [0]

        @vlc.CallbackDecorators.VideoLockCb
        def lock(opaque, planes):
            planes[0] = ctypes.cast(buf, ctypes.c_void_p).value
            return None

        @vlc.CallbackDecorators.VideoUnlockCb
        def unlock(opaque, picture, planes):
            pass

        @vlc.CallbackDecorators.VideoDisplayCb
        def display(opaque, picture):
            count[0] += 1

        inst = player = None
        frames = {}
        timestamps = {}
        try:
            inst = vlc.Instance(["--no-audio", "--no-spu", "--no-osd", "--no-sub-autodetect-file",
                                 "--no-video-title-show", "--no-snapshot-preview", "--avcodec-hw=none",
                                 "--no-stats", "--quiet"])
            player = inst.media_player_new()
            player.video_set_callbacks(lock, unlock, display, None)
            player.video_set_format("RV32", w, h, w * 4)
            media = inst.media_new_path(path)
            media.add_option(":no-audio")
            player.set_media(media)
            player.play()
            t0 = time.time()
            while count[0] == 0 and not stop.is_set() and time.time() - t0 < 8:
                time.sleep(0.02)
            if count[0] == 0:
                return
            done = 0
            for i in self._order():
                if stop.is_set():
                    break
                player.set_time(int(i * step))
                n0, ts = count[0], time.time()
                while count[0] < n0 + 2 and not stop.is_set() and time.time() - ts < 2.0:
                    time.sleep(0.01)
                if stop.is_set():
                    break
                time.sleep(0.02)
                captured_ms = max(0, player.get_time())
                img = QImage(bytes(buf), w, h, w * 4, QImage.Format_RGB32).copy()
                with self._lock:
                    if self.path == path:
                        self.frames[i] = img
                        self.timestamps[i] = captured_ms
                frames[i] = img
                timestamps[i] = captured_ms
                done += 1
                if done % 8 == 0 or done == total:
                    self.progress.emit(path, done, total)
                if player.get_state() in (vlc.State.Ended, vlc.State.Error):
                    player.stop()
                    player.play()
            if frames and not stop.is_set():
                self._save_cache(path, frames, (w, h), step, timestamps)
        except Exception:
            pass
        finally:
            try:
                if player is not None:
                    player.stop()
                    player.release()
                if inst is not None:
                    inst.release()
            except Exception:
                pass
