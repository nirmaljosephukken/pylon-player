"""Shared pieces of the background readers (seek previews, waveforms, the music scan): their disk caches
and a worker thread that can be cancelled without making the window wait."""
import hashlib
import os
import threading

from .store import data_dir


def cache_dir(name: str) -> str:
    """A folder for one kind of cache in Pylon's data folder (made if missing)."""
    d = os.path.join(data_dir(), name)
    os.makedirs(d, exist_ok=True)
    return d


def file_key(path: str) -> str:
    """A short name for a file's cache entry; it changes when the file is replaced or edited."""
    try:
        st = os.stat(path)
        sig = f"{os.path.normcase(os.path.abspath(path))}|{st.st_size}|{int(st.st_mtime)}"
    except OSError:
        sig = path
    return hashlib.sha1(sig.encode("utf-8", "replace")).hexdigest()[:20]


def prune_cache(folder: str, suffix: str, keep: int, companions: tuple[str, ...] = ()):
    """Keep the `keep` most recently used `suffix` files in `folder`; the oldest go, with their
    companion files (the same name with another suffix)."""
    try:
        files = sorted((os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(suffix)),
                       key=os.path.getmtime)
        for f in files[:-keep] if keep else files:
            for ext in (suffix, *companions):
                try:
                    os.remove(f[:-len(suffix)] + ext)
                except OSError:
                    pass
    except OSError:
        pass


class BackgroundJob:
    """One worker thread at a time. cancel() only asks the worker to stop (each run gets its own stop
    flag), so the window never waits for it; pass wait=True when closing, so the worker's VLC instance is
    let go of before Pylon exits."""

    def __init__(self):
        self._thread = None
        self._stop = threading.Event()

    def _start_worker(self, target, *args):
        self._stop = threading.Event()
        self._thread = threading.Thread(target=target, args=(*args, self._stop), daemon=True)
        self._thread.start()

    def _stop_worker(self, wait: bool = False):
        self._stop.set()
        if wait and self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._thread = None

    def busy(self) -> bool:
        return bool(self._thread and self._thread.is_alive())
