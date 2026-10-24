"""Waveform for the seek bar.

A second libVLC instance converts the file's sound to a tiny mono WAV (2000
samples a second, no picture), which takes well under a second for a song and
a few seconds for a film, because VLC writes it as fast as it can decode. The
loudest sample in each slice becomes one bar. Bars are kept on disk, so a file
only has to be read once.
"""
import array
import hashlib
import json
import os
import threading
import time
import wave

from PySide6.QtCore import QObject, Signal

from . import engine as engine_mod
from .store import data_dir

BARS = 600             # slices along the bar; more than the bar is wide on most screens
RATE = 2000            # samples a second: plenty for an outline, tiny to write
MAX_SECONDS = 600      # give up on anything that takes longer than this to read
CACHE_FILES = 500


def _cache_dir() -> str:
    d = os.path.join(data_dir(), "waves")
    os.makedirs(d, exist_ok=True)
    return d


def _key(path: str) -> str:
    try:
        st = os.stat(path)
        sig = f"{os.path.normcase(os.path.abspath(path))}|{st.st_size}|{int(st.st_mtime)}"
    except OSError:
        sig = path
    return hashlib.sha1(sig.encode("utf-8", "replace")).hexdigest()[:20]


def peaks_from_wav(wav_path: str, bars: int = BARS) -> list[float]:
    """The loudest sample in each of `bars` slices, scaled so the loudest slice is 1.0."""
    with wave.open(wav_path, "rb") as w:
        if w.getsampwidth() != 2:
            return []
        channels = max(1, w.getnchannels())
        data = array.array("h", w.readframes(w.getnframes()))
    if channels > 1:
        data = data[::channels]
    n = len(data)
    if n == 0:
        return []
    bars = min(bars, n)
    out = []
    for i in range(bars):
        part = data[i * n // bars:(i + 1) * n // bars]
        out.append(max(max(part), -min(part)) if part else 0)
    top = max(out) or 1
    # square root so quiet passages still show, as in most audio editors
    return [round((v / top) ** 0.5, 3) for v in out]


def _prune_cache():
    try:
        d = _cache_dir()
        files = sorted((os.path.join(d, f) for f in os.listdir(d) if f.endswith(".json")), key=os.path.getmtime)
        for f in files[:-CACHE_FILES]:
            os.remove(f)
    except OSError:
        pass


class WaveformMaker(QObject):
    """Makes the waveform for one file at a time, in the background."""
    ready = Signal(str, list)        # path, bars (0..1)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.path = None
        self.peaks: list[float] = []
        self._thread = None
        self._stop = threading.Event()

    def start(self, path: str):
        if path == self.path:
            return
        self.cancel()
        if engine_mod.vlc is None or not path or not os.path.isfile(path):
            return
        self.path = path
        cached = self._load_cache(path)
        if cached:
            self.peaks = cached
            self.ready.emit(path, cached)
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
        self.peaks = []

    # ------------------------------------------------------------------ cache
    def _cache_path(self, path):
        return os.path.join(_cache_dir(), _key(path) + ".json")

    def _load_cache(self, path):
        try:
            with open(self._cache_path(path), encoding="utf-8") as f:
                info = json.load(f)
            if info.get("version") != 1:
                return None
            os.utime(self._cache_path(path))
            return [float(v) for v in info["peaks"]]
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _save_cache(self, path, peaks):
        try:
            with open(self._cache_path(path), "w", encoding="utf-8") as f:
                json.dump({"version": 1, "peaks": peaks}, f)
            _prune_cache()
        except OSError:
            pass

    # ------------------------------------------------------------------ worker
    def _run(self, path, stop):
        wav = os.path.join(_cache_dir(), f"reading-{_key(path)}.wav")
        try:
            if self._decode(path, wav, stop) and not stop.is_set():
                peaks = peaks_from_wav(wav)
                if peaks and not stop.is_set():
                    self._save_cache(path, peaks)
                    if self.path == path:
                        self.peaks = peaks
                        self.ready.emit(path, peaks)
        except Exception:
            pass
        finally:
            try:
                os.remove(wav)
            except OSError:
                pass

    @staticmethod
    def sout_chain(wav: str) -> str:
        # Forward slashes and quotes keep Windows paths (with spaces) intact in VLC's option syntax.
        dst = wav.replace("\\", "/")
        return (f':sout=#transcode{{vcodec=none,scodec=none,acodec=s16l,channels=1,samplerate={RATE}}}'
                f':std{{access=file,mux=wav,dst="{dst}"}}')

    def _decode(self, path, wav, stop) -> bool:
        vlc = engine_mod.vlc
        inst = player = None
        try:
            inst = vlc.Instance(["--no-video", "--no-spu", "--no-osd", "--no-sub-autodetect-file",
                                 "--no-sout-video", "--no-sout-spu", "--no-stats", "--quiet"])
            media = inst.media_new_path(path)
            media.add_option(self.sout_chain(wav))
            player = inst.media_player_new()
            player.set_media(media)
            player.play()
            t0 = time.time()
            done = (vlc.State.Ended, vlc.State.Error, vlc.State.Stopped)
            while not stop.is_set() and time.time() - t0 < MAX_SECONDS:
                if player.get_state() in done and time.time() - t0 > 0.2:
                    break
                time.sleep(0.05)
            ok = player.get_state() == vlc.State.Ended
        finally:
            try:
                if player is not None:
                    player.stop()
                    player.release()
                if inst is not None:
                    inst.release()
            except Exception:
                pass
        return ok and os.path.isfile(wav) and os.path.getsize(wav) > 44
