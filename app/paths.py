"""Where Pylon keeps its files: the data folder and the logs. Standard library only, so the startup
log can use it before Qt is imported.

Logs (each kept below a size limit, with one older copy as <name>.previous):
    startup.log   the data folder's logs/, written from the first line of start-up (startup.py)
    error.log     Python errors, next to Pylon in logs/ when that folder is writable (main.py)
    vlc.log       VLC's own log, in the same folder as error.log (engine.py)"""
import os
import sys

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_dir() -> str:
    """Windows: %APPDATA%\\Pylon   macOS: ~/Library/Application Support/Pylon
    Linux: $XDG_DATA_HOME/pylon (~/.local/share/pylon)"""
    home = os.path.expanduser("~")
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or home
        path = os.path.join(base, "Pylon")
        legacy = os.path.join(base, "ConePlayer")   # Pylon's earlier name
        if not os.path.exists(path) and os.path.isdir(legacy):
            try:
                os.rename(legacy, path)
            except OSError:
                return legacy
    elif sys.platform == "darwin":
        path = os.path.join(home, "Library", "Application Support", "Pylon")
    else:
        path = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share"), "pylon")
    os.makedirs(path, exist_ok=True)
    return path


def _writable(folder: str) -> bool:
    try:
        os.makedirs(folder, exist_ok=True)
        test = os.path.join(folder, ".write-test")
        with open(test, "w"):
            pass
        os.remove(test)
        return True
    except OSError:
        return False


def log_dir(next_to_pylon: bool = True) -> str | None:
    """The logs folder: next to Pylon if asked and writable, otherwise in the data folder; None if
    neither can be written."""
    folders = [os.path.join(APP_ROOT, "logs")] if next_to_pylon else []
    try:
        folders.append(os.path.join(data_dir(), "logs"))
    except OSError:
        pass
    return next((d for d in folders if _writable(d)), None)


def open_log(name: str, max_bytes: int = 1_000_000, next_to_pylon: bool = True):
    """Open a log for appending (line-buffered), first moving it to <name>.previous if it has grown
    past max_bytes. None if there's nowhere to write it."""
    folder = log_dir(next_to_pylon)
    if folder is None:
        return None
    path = os.path.join(folder, name)
    try:
        rotate(path, max_bytes)
        return open(path, "a", encoding="utf-8", buffering=1)
    except OSError:
        return None


def rotate(path: str, max_bytes: int):
    """Keep one older copy of a log that has grown past max_bytes."""
    try:
        if os.path.getsize(path) > max_bytes:
            os.replace(path, path + ".previous")
    except OSError:
        pass
