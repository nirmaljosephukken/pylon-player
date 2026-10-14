"""Music library: songs from your library folders, grouped by artist and album.

Tags (title, artist, album, track number, year) and embedded cover art are
read by libVLC in a background thread. Results are cached in music.json in
Pylon's data folder, so only new or changed files are read again.
"""
import hashlib
import json
import os
import threading
import time
from urllib.parse import unquote, urlparse

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from . import engine as engine_mod
from .store import data_dir
from .util import is_audio, natural_key

UNKNOWN_ARTIST = "Unknown artist"
COVER_NAMES = ("cover", "folder", "front", "album", "albumart")


def _art_dir():
    d = os.path.join(data_dir(), "art")
    os.makedirs(d, exist_ok=True)
    return d


def _int(v):
    try:
        return int(str(v).split("/")[0].strip())
    except (TypeError, ValueError):
        return 0


def _year(v):
    v = (v or "").strip()
    return v[:4] if v[:4].isdigit() else ""


def _url_to_path(u):
    if not u:
        return ""
    if u.startswith("file:"):
        p = unquote(urlparse(u).path)
        if os.name == "nt" and p.startswith("/") and len(p) > 2 and p[2] == ":":
            p = p[1:]
        return os.path.normpath(p)
    return ""


def _folder_cover(folder):
    try:
        names = os.listdir(folder)
    except OSError:
        return ""
    for n in sorted(names):
        stem, ext = os.path.splitext(n.lower())
        if ext in (".jpg", ".jpeg", ".png", ".webp") and stem in COVER_NAMES:
            return os.path.join(folder, n)
    return ""


def _store_art(src, artist, album):
    """Copy cover art into Pylon's own folder at a small size (VLC's cache can be cleared)."""
    if not src or not os.path.isfile(src):
        return ""
    key = hashlib.sha1(f"{artist}|{album}|{src}".encode("utf-8", "replace")).hexdigest()[:20]
    out = os.path.join(_art_dir(), key + ".jpg")
    if os.path.isfile(out):
        return out
    img = QImage(src)
    if img.isNull():
        return ""
    if img.width() > 400:
        img = img.scaledToWidth(400)
    return out if img.save(out, "JPG", 88) else ""


class MusicLibrary(QObject):
    progress = Signal(int, int)    # done, total
    finished = Signal()

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.path = os.path.join(data_dir(), "music.json")
        self.songs: dict[str, dict] = {}
        self._thread = None
        self._stop = threading.Event()
        self.scanning = False
        self._load()

    # ------------------------------------------------------------------ cache
    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                self.songs = json.load(f).get("songs", {})
        except (OSError, ValueError):
            self.songs = {}

    def _save(self, songs):
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "songs": songs}, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError:
            pass

    # ------------------------------------------------------------------ scan
    def scan(self):
        """Look for new, changed and removed songs in the library folders (background)."""
        if self.scanning or engine_mod.vlc is None:
            return
        self.scanning = True
        self._stop = threading.Event()
        folders = list(self.store.data.get("library_folders", []))
        self._thread = threading.Thread(target=self._run, args=(folders, dict(self.songs), self._stop), daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def _run(self, folders, old, stop):
        try:
            self._scan(folders, old, stop)
        finally:
            self.scanning = False
            self.finished.emit()

    def _scan(self, folders, old, stop):
        files = []
        for root in folders:
            for dirpath, dirnames, names in os.walk(root):
                if stop.is_set():
                    return
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                files += [os.path.join(dirpath, n) for n in names if is_audio(n)]
        total = len(files)
        self.progress.emit(0, total)
        vlc = engine_mod.vlc
        inst = None
        songs = {}
        last_emit = time.time()
        try:
            for i, p in enumerate(files):
                if stop.is_set():
                    return
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                prev = old.get(p)
                if prev and prev.get("size") == st.st_size and prev.get("mtime") == int(st.st_mtime):
                    songs[p] = prev
                    continue
                if inst is None:
                    inst = vlc.Instance(["--no-video", "--quiet", "--no-stats"])
                songs[p] = self._read(inst, p, st)
                if time.time() - last_emit > 0.3:
                    self.progress.emit(i + 1, total)
                    last_emit = time.time()
        finally:
            if inst is not None:
                try:
                    inst.release()
                except Exception:
                    pass
        self.songs = songs
        self._save(songs)
        self.progress.emit(total, total)

    def _read(self, inst, p, st):
        vlc = engine_mod.vlc
        folder = os.path.dirname(p)
        info = {"size": st.st_size, "mtime": int(st.st_mtime), "title": "", "artist": "", "album_artist": "",
                "album": "", "track": 0, "disc": 0, "year": "", "genre": "", "dur": 0, "art": ""}
        try:
            m = inst.media_new_path(p)
            m.parse()
            g = lambda k: (m.get_meta(k) or "").strip()
            title = g(vlc.Meta.Title)
            if title == os.path.basename(p):      # VLC falls back to the file name
                title = ""
            info.update(title=title, artist=g(vlc.Meta.Artist), album_artist=g(vlc.Meta.AlbumArtist),
                        album=g(vlc.Meta.Album), track=_int(g(vlc.Meta.TrackNumber)),
                        disc=_int(g(vlc.Meta.DiscNumber)), year=_year(g(vlc.Meta.Date)),
                        genre=g(vlc.Meta.Genre), dur=max(0, int(m.get_duration() or 0)))
            art = _url_to_path(g(vlc.Meta.ArtworkURL))
            m.release()
        except Exception:
            art = ""
        art = art if art and os.path.isfile(art) else _folder_cover(folder)
        info["art"] = _store_art(art, info["album_artist"] or info["artist"], info["album"] or folder)
        return info

    # ------------------------------------------------------------------ views
    @staticmethod
    def title_of(p, s):
        if s.get("title"):
            return s["title"]
        name = os.path.splitext(os.path.basename(p))[0]
        return name

    @staticmethod
    def artist_of(s):
        return s.get("album_artist") or s.get("artist") or UNKNOWN_ARTIST

    @staticmethod
    def album_of(p, s):
        return s.get("album") or os.path.basename(os.path.dirname(p)) or "Unknown album"

    def albums(self):
        """[{key, artist, album, year, art, tracks:[path]}] sorted by artist then year."""
        groups = {}
        for p, s in self.songs.items():
            if not os.path.exists(p):
                continue
            artist, album = self.artist_of(s), self.album_of(p, s)
            key = f"{artist.lower()}\x00{album.lower()}"
            g = groups.setdefault(key, {"key": key, "artist": artist, "album": album, "year": "", "art": "", "tracks": []})
            g["tracks"].append(p)
            g["year"] = g["year"] or s.get("year", "")
            g["art"] = g["art"] or s.get("art", "")
        for g in groups.values():
            g["tracks"].sort(key=lambda p: (self.songs[p].get("disc") or 1, self.songs[p].get("track") or 999,
                                            natural_key(os.path.basename(p))))
        return sorted(groups.values(), key=lambda g: (g["artist"] == UNKNOWN_ARTIST, natural_key(g["artist"]),
                                                      g["year"] or "9999", natural_key(g["album"])))

    def artists(self):
        """[(artist, [albums])]"""
        out = {}
        for a in self.albums():
            out.setdefault(a["artist"], []).append(a)
        return sorted(out.items(), key=lambda kv: (kv[0] == UNKNOWN_ARTIST, natural_key(kv[0])))

    def all_songs(self):
        return [p for a in self.albums() for p in a["tracks"]]
