"""Waveform for the seek bar.

A second libVLC instance converts the file's sound to a tiny mono WAV (2000
samples a second, no picture), which takes well under a second for a song and
a few seconds for a film, because VLC writes it as fast as it can decode. The
loudest sample in each slice becomes one bar. The same sound tells where a song's
leading and trailing silence ends and starts (#86). Both are kept on disk, so a
file only has to be read once.
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
CACHE_VERSION = 2      # 2 adds the silence at both ends (#86)
SILENCE_DB = -50       # quieter than this, relative to full scale, counts as silence
LEAD_IN_MS = 150       # start this much before the sound, so its first note isn't clipped
TAIL_MS = 400          # and keep this much after it, so a fade ends naturally


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


def silence_from_wav(wav_path: str) -> tuple[int, int, int] | None:
    """(where the sound starts, where it ends, length), in ms, ignoring silence at both ends (#86).
    None for a file that is silent all through."""
    with wave.open(wav_path, "rb") as w:
        if w.getsampwidth() != 2:
            return None
        channels = max(1, w.getnchannels())
        rate = w.getframerate() or RATE
        data = array.array("h", w.readframes(w.getnframes()))
    if channels > 1:
        data = data[::channels]
    return silence_bounds(data, rate)


def silence_bounds(samples, rate: int = RATE, db: float = SILENCE_DB) -> tuple[int, int, int] | None:
    n = len(samples)
    if not n:
        return None
    limit = 32768 * 10 ** (db / 20)
    first = next((i for i in range(n) if abs(samples[i]) > limit), None)
    if first is None:
        return None
    last = next(i for i in range(n - 1, -1, -1) if abs(samples[i]) > limit)
    total = n * 1000 // rate
    start = max(0, first * 1000 // rate - LEAD_IN_MS)
    end = min(total, (last + 1) * 1000 // rate + TAIL_MS)
    return start, end, total


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
    silence = Signal(str, int, int, int)   # path, where the sound starts and ends, length (ms) (#86)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.path = None
        self.peaks: list[float] = []
        self.bounds = None               # (start, end, length) ms without the silence at both ends
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
            self.peaks, self.bounds = cached
            self.ready.emit(path, self.peaks)
            if self.bounds:
                self.silence.emit(path, *self.bounds)
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
        self.bounds = None

    # ------------------------------------------------------------------ cache
    def _cache_path(self, path):
        return os.path.join(_cache_dir(), _key(path) + ".json")

    def _load_cache(self, path):
        try:
            with open(self._cache_path(path), encoding="utf-8") as f:
                info = json.load(f)
            if info.get("version") != CACHE_VERSION:
                return None
            os.utime(self._cache_path(path))
            trim = info.get("trim")
            return [float(v) for v in info["peaks"]], (tuple(int(v) for v in trim) if trim else None)
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _save_cache(self, path, peaks, bounds=None):
        try:
            with open(self._cache_path(path), "w", encoding="utf-8") as f:
                json.dump({"version": CACHE_VERSION, "peaks": peaks, "trim": list(bounds) if bounds else None}, f)
            _prune_cache()
        except OSError:
            pass

    # ------------------------------------------------------------------ worker
    def _run(self, path, stop):
        wav = os.path.join(_cache_dir(), f"reading-{_key(path)}.wav")
        try:
            if self._decode(path, wav, stop) and not stop.is_set():
                peaks = peaks_from_wav(wav)
                bounds = silence_from_wav(wav)
                if peaks and not stop.is_set():
                    self._save_cache(path, peaks, bounds)
                    if self.path == path:
                        self.peaks, self.bounds = peaks, bounds
                        self.ready.emit(path, peaks)
                        if bounds:
                            self.silence.emit(path, *bounds)
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
