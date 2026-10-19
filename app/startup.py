"""Standard-library-only startup diagnostics, installed before importing Qt."""
import faulthandler
import os
import platform
import sys
import time
import traceback

_log = None  # faulthandler needs this descriptor to remain open until exit


def install():
    global _log
    if _log is not None:
        return
    home = os.path.expanduser("~")
    if sys.platform == "win32":
        root = os.path.join(os.environ.get("APPDATA") or home, "Pylon")
    elif sys.platform == "darwin":
        root = os.path.join(home, "Library", "Application Support", "Pylon")
    else:
        root = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share"), "pylon")
    try:
        folder = os.path.join(root, "logs")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "startup.log")
        if os.path.isfile(path) and os.path.getsize(path) > 1_000_000:
            os.replace(path, path + ".previous")
        _log = open(path, "a", encoding="utf-8", buffering=1)
        _log.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        _log.write(f"Python {sys.version.split()[0]} / {sys.platform} / {platform.machine()}\n")
        _log.write(f"Interpreter: {sys.executable}\n")
        _log.write(f"Desktop: {os.environ.get('XDG_CURRENT_DESKTOP', '')} {os.environ.get('XDG_SESSION_TYPE', '')}; "
                   f"Qt platform: {os.environ.get('QT_QPA_PLATFORM', 'automatic')}\n")
        qt_env = {k: v for k, v in os.environ.items()
                  if k in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORMTHEME", "QT_STYLE_OVERRIDE", "QT_IM_MODULE")}
        if qt_env:
            _log.write(f"Qt settings: {qt_env}\n")      # helps with startup crashes (#28)
        faulthandler.enable(file=_log, all_threads=True)
        previous = sys.excepthook
        def report(kind, value, trace):
            traceback.print_exception(kind, value, trace, file=_log)
            _log.flush()
            previous(kind, value, trace)
        sys.excepthook = report
    except (OSError, RuntimeError, ValueError):
        if _log:
            _log.close()
            _log = None


def mark(stage):
    if _log:
        _log.write(stage + "\n")

