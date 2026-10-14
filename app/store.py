"""JSON persistence in the per-OS data folder (see data_dir)."""
import json
import os
import sys
import time

from PySide6.QtCore import QObject, QTimer, Signal

DEFAULT_SHORTCUTS = {
    "play_pause": ("Play / pause", "Space"),
    "seek_fwd": ("Jump forward 10s", "Right"),
    "seek_back": ("Jump back 10s", "Left"),
    "seek_fwd_long": ("Jump forward 1 min", "Ctrl+Right"),
    "seek_back_long": ("Jump back 1 min", "Ctrl+Left"),
    "frame_next": ("Next frame", "E"),
    "vol_up": ("Volume up", "Up"),
    "vol_down": ("Volume down", "Down"),
    "mute": ("Mute", "M"),
    "next": ("Next in queue", "N"),
    "prev": ("Previous in queue", "P"),
    "fullscreen": ("Fullscreen", "F"),
    "fullscreen_enter": ("Fullscreen (second key)", "Return"),
    "exit_fullscreen": ("Leave fullscreen", "Esc"),
    "pip": ("Picture in picture", "Ctrl+P"),
    "hide_ui": ("Hide the interface", "H"),
    "speed_up": ("Faster", "]"),
    "speed_down": ("Slower", "["),
    "speed_reset": ("Normal speed", "="),
    "sub_delay_plus": ("Subtitles later (+50 ms)", "J"),
    "sub_delay_minus": ("Subtitles earlier (-50 ms)", "G"),
    "audio_delay_plus": ("Audio later (+50 ms)", "K"),
    "audio_delay_minus": ("Audio earlier (-50 ms)", "Shift+K"),
    "cycle_sub": ("Next subtitle track", "V"),
    "cycle_audio": ("Next audio track", "B"),
    "bookmark": ("Add bookmark", "Ctrl+B"),
    "library": ("Show library", "Ctrl+L"),
    "sidebar": ("Show settings sidebar", "Ctrl+T"),
    "queue": ("Show queue", "Ctrl+Q"),
    "open_file": ("Open file", "Ctrl+O"),
    "open_folder": ("Open folder", "Ctrl+F"),
    "open_stream": ("Open network stream", "Ctrl+N"),
    "snapshot": ("Take a snapshot", "Shift+S"),
    "shortcuts": ("Show keyboard shortcuts", "F1"),
    "stop": ("Stop", "S"),
}

DEFAULT_SETTINGS = {
    "accent": "#FF8800",
    "sub_match": "episode",
    "binge": True,              # play the next file in the folder when one ends
    "resume": "ask",            # ask | always | never
    "osd_shortcuts": True,      # show which key was pressed in on-screen messages
    "hide_delay_ms": 1600,
    "volume": 80,
    "remember_history": True,
    "sub_lang": "",             # preferred subtitle language, e.g. "eng"
    "audio_lang": "",
    "hw_decoding": True,
    "onboarded": False,
    "vlc_dir": "",
    "desktop_entry": "",
    "seek_previews": True,      # preview pictures when hovering the seek bar
    "theme": "dark",            # dark | black | warm | midnight | custom
    "theme_tint": "",           # colour for the custom theme
    "pin_controls": False,      # keep the bars shown (and the video clear of them) outside fullscreen
}


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


class Store(QObject):
    changed = Signal(str)  # section name

    def __init__(self, path: str | None = None):
        super().__init__()
        self.path = path or os.path.join(data_dir(), "data.json")
        self.data = {
            "settings": dict(DEFAULT_SETTINGS),
            "shortcuts": {},
            "library_folders": [],
            "pinned": [],
            "recent": [],            # [{path, t}]
            "positions": {},         # path -> {pos, len, watched, t}
            "presets": {},           # name -> settings dict
            "folder_preset": {},     # folder -> preset name
            "bookmarks": {},         # path -> [{t, name}]
            "playlists": {},         # name -> [paths]
            "sub_map": {},           # video path -> subtitle path
            "streams": [],           # [{name, url}]
            "queue": [],             # saved queue between sessions
        }
        self._load()
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(800)
        self._save_timer.timeout.connect(self.save_now)

    # ---------- io ----------
    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                loaded = json.load(f)
            for k, v in loaded.items():
                if k == "settings":
                    self.data["settings"].update(v)
                else:
                    self.data[k] = v
        except (OSError, ValueError):
            pass

    def save(self, section: str = ""):
        self._save_timer.start()
        if section:
            self.changed.emit(section)

    def save_now(self):
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            pass

    # ---------- settings ----------
    def setting(self, key):
        return self.data["settings"].get(key, DEFAULT_SETTINGS.get(key))

    def set_setting(self, key, value):
        self.data["settings"][key] = value
        self.save("settings")

    def shortcut(self, action: str) -> str:
        return self.data["shortcuts"].get(action, DEFAULT_SHORTCUTS[action][1])

    # ---------- history ----------
    def add_recent(self, path: str):
        if not self.setting("remember_history"):
            return
        rec = [r for r in self.data["recent"] if r["path"] != path]
        rec.insert(0, {"path": path, "t": time.time()})
        self.data["recent"] = rec[:60]
        self.save("recent")

    def set_position(self, path: str, pos: int, length: int):
        if not path or not self.setting("remember_history"):
            return
        entry = self.data["positions"].get(path, {})
        watched = entry.get("watched", False) or (length > 0 and pos / length > 0.9)
        self.data["positions"][path] = {"pos": int(pos), "len": int(length), "watched": watched, "t": time.time()}
        self.save()

    def position(self, path: str) -> dict:
        return self.data["positions"].get(path, {})

    def set_watched(self, path: str, watched: bool):
        e = self.data["positions"].setdefault(path, {"pos": 0, "len": 0, "t": time.time()})
        e["watched"] = watched
        if not watched:
            e["pos"] = 0
        self.save("library")

    def continue_watching(self, limit=12) -> list[dict]:
        out = []
        for p, e in self.data["positions"].items():
            ln = e.get("len", 0)
            if ln and 10_000 < e.get("pos", 0) < ln * 0.93 and not e.get("watched"):
                out.append({"path": p, **e})
        out.sort(key=lambda e: -e.get("t", 0))
        return out[:limit]

    def clear_history(self):
        self.data["recent"] = []
        self.data["positions"] = {}
        self.save("recent")

    # ---------- bookmarks ----------
    def bookmarks(self, path: str) -> list[dict]:
        return self.data["bookmarks"].get(path, [])

    def set_bookmarks(self, path: str, items: list[dict]):
        self.data["bookmarks"][path] = sorted(items, key=lambda b: b["t"])
        self.save("bookmarks")

    # ---------- presets ----------
    def preset_for_folder(self, folder: str):
        name = self.data["folder_preset"].get(folder)
        return (name, self.data["presets"].get(name)) if name else (None, None)
