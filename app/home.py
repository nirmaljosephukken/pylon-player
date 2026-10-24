"""Home page (instead of a blank screen: continue watching, recent, your
library, playlists, streams) and the Now Playing page used for music."""
import os
import time

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget, QMenu)

from . import theme
from .icons import icon, pixmap
from .util import display_name, fmt_time, is_audio, is_disc, is_url, natural_key, pretty_title, to_path, list_media
from .store import HOME_SECTIONS
from .widgets import Card, IconButton


class FlowRow(QWidget):
    """Horizontal scroller of cards."""

    def __init__(self):
        super().__init__()
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(12)
        self.lay.addStretch(1)

    def add(self, w):
        self.lay.insertWidget(self.lay.count() - 1, w)


def hscroll(row: QWidget) -> QScrollArea:
    sc = QScrollArea()
    sc.setWidget(row)
    sc.setWidgetResizable(True)
    sc.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    sc.setFixedHeight(146)
    sc.setFrameShape(QFrame.NoFrame)
    return sc


class HomePage(QScrollArea):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.store = win.store
        self.setObjectName("Home")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.refresh()

    def _mark_watched(self, path):
        self.store.set_watched(path, True)
        title = pretty_title(path)
        self.win.toast(f"Marked “{title}” as watched")
        QTimer.singleShot(0, self.refresh)     # rebuilding the page from inside a click
        if self.win.library.isVisible():
            self.win.library.refresh_queue()

    def refresh(self):
        inner = QWidget()
        inner.setObjectName("Home")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(36, 22, 36, 36)
        lay.setSpacing(10)

        # header row
        head = QHBoxLayout()
        lib = IconButton("sidebar_left", "Library (Ctrl+L)", size=20)
        lib.clicked.connect(lambda: self.win.toggle_library())
        logo = QLabel()
        logo.setPixmap(pixmap("cone", theme.accent(), 34))
        title = QLabel("Pylon")
        title.setObjectName("H1")
        head.addWidget(lib)
        head.addSpacing(6)
        head.addWidget(logo)
        head.addWidget(title)
        head.addStretch(1)
        if self.win.engine.current:
            back = QPushButton("Back to player  ›")
            back.setObjectName("Primary")
            back.clicked.connect(self.win.show_player)
            head.addWidget(back)
        menu = IconButton("menu", "Menu", size=20)
        menu.clicked.connect(lambda: self.win.show_main_menu(menu))
        head.addWidget(menu)
        lay.addLayout(head)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        for ic, text, fn in (("file", "Open file", self.win.open_file_dialog),
                             ("folder", "Open folder", self.win.open_folder_dialog),
                             ("stream", "Network stream", self.win.open_stream_dialog),
                             ("folder_add", "Add folder to library", self.win.library.add_library_folder)):
            b = QPushButton(text)
            b.setIcon(icon(ic, theme.TEXT, 16))
            b.clicked.connect(fn)
            actions.addWidget(b)
        actions.addStretch(1)
        lay.addLayout(actions)
        drop = QLabel("…or drop files and folders anywhere on this window")
        drop.setObjectName("Muted")
        lay.addWidget(drop)

        builders = {"continue": self._sec_continue, "recent": self._sec_recent, "library": self._sec_library,
                    "playlists": self._sec_playlists, "music": self._sec_music, "streams": self._sec_streams}
        self._cont = self.store.continue_watching()
        self._listen = self.continue_listening() if self.store.setting("home_music") else []
        for key in self.store.home_order():          # your order and choice of sections (#53)
            if self.store.setting(HOME_SECTIONS[key][1]):
                builders[key](lay)

        lay.addStretch(1)
        keys = QLabel("Space play/pause  ·  ←/→ jump 10s  ·  F fullscreen  ·  H hide interface  ·  "
                      "Ctrl+B bookmark  ·  F1 all shortcuts")
        keys.setStyleSheet(f"color: {theme.FAINT}; font-size: 12px;")
        lay.addWidget(keys)
        old = self.takeWidget()
        if old:
            old.deleteLater()
        self.setWidget(inner)

    def _sec_continue(self, lay):
        cont = self._cont
        if cont:
            lay.addWidget(self._section("Continue watching"))
            row = FlowRow()
            for e in cont:
                p = e["path"]
                title, _, code = pretty_title(p).partition("  ·  ")
                c = Card(title, f"{code + '  ·  ' if code else ''}{fmt_time(e['pos'])} of {fmt_time(e['len'])}"
                         f"{'' if code else '  ·  ' + _parent(p)}",
                         "music" if is_audio(p) else "play", progress=e["pos"] / max(1, e["len"]))
                self._bind_card_menu(c, "media", p)
                c.setToolTip(p)
                c.clicked.connect(lambda p=p, t=e["pos"]: self.win.play_from_folder(p, start_ms=t))
                c.add_corner_button("check_all", "Mark as watched", lambda p=p: self._mark_watched(p))
                row.add(c)
            lay.addWidget(hscroll(row))

    def _sec_recent(self, lay):
        shown = {c["path"] for c in self._cont} if self.store.setting("home_continue") else set()
        shown |= {c["path"] for c in self._listen}
        recent = [r for r in self.store.data["recent"] if r["path"] not in shown][:12]
        if recent:
            lay.addWidget(self._section("Recently played"))
            row = FlowRow()
            for r in recent:
                p = r["path"]
                c = Card(pretty_title(p), "Stream" if is_url(p) else _parent(p),
                         "stream" if is_url(p) else ("music" if is_audio(p) else ("disc" if is_disc(p) else "video")))
                self._bind_card_menu(c, "media", p)
                c.setToolTip(p)
                c.clicked.connect(lambda p=p: self.win.play_from_folder(p))
                row.add(c)
            lay.addWidget(hscroll(row))

    def _sec_library(self, lay):
        folders = self.store.data["pinned"] + [f for f in self.win.library.ordered_library_folders()
                                               if f not in self.store.data["pinned"]]
        lay.addWidget(self._section("Your library"))
        if folders:
            row = FlowRow()
            for f in folders:
                c = Card(os.path.basename(f.rstrip("\\/")) or f, f, "folder")
                self._bind_card_menu(c, "folder", f)
                c.clicked.connect(lambda f=f: self.win.browse_folder(f))
                row.add(c)
            lay.addWidget(hscroll(row))
        else:
            lay.addWidget(self._muted("Add a folder (movies, shows, music) to see it here and in the library panel."))

    def _sec_playlists(self, lay):
        lib = self.win.library
        pls = self.store.data["playlists"]
        if pls:
            lay.addWidget(self._section("Playlists"))
            row = FlowRow()
            positions = self.store.data["positions"]
            mode = self.store.setting("playlists_sort") or "default"
            ordered = list(pls.items())                 # kept in the order they were made
            if mode in ("default", "newest"):           # follow the Playlists tab (#37)
                ordered.reverse()
            elif mode in ("name", "reverse"):
                ordered.sort(key=lambda x: natural_key(x[0]), reverse=mode == "reverse")
            elif mode == "count":
                ordered.sort(key=lambda x: (-len(x[1]), natural_key(x[0])))
            first, rest = lib.with_pins("playlists", ordered, lambda x: x[0])     # pinned first (#52)
            for name, items in first + rest:
                done = sum(1 for p in items if positions.get(p, {}).get("watched"))
                sub = f"{len(items)} item{'s' if len(items) != 1 else ''}"
                if done:
                    sub += f"  ·  {done} watched"
                c = Card(name, sub, "playlist", progress=done / len(items) if items and done else None)
                self._bind_card_menu(c, "playlist", name)
                c.clicked.connect(lambda n=name: self.win.play_playlist(n))
                row.add(c)
            lay.addWidget(hscroll(row))

    def continue_listening(self, limit=12):
        """What to pick up again in Music (#55), newest first: an album you were partway through
        (where you left off, or the next song if you finished one) or a song that isn't on an album."""
        lib = self.win.library
        m = lib.music
        hidden = self.store.data.get("listen_hidden", {})
        key = lambda p: os.path.normcase(os.path.normpath(p))
        album_of = {}
        for a in (m.albums() if m.songs else []):
            if len(a["tracks"]) > 1:
                for i, p in enumerate(a["tracks"]):
                    album_of[key(p)] = (a, i)
        out, seen = [], set()
        positions = sorted(self.store.data["positions"].items(), key=lambda kv: -kv[1].get("t", 0))
        for p, e in positions:
            if is_url(p) or not is_audio(p) or not os.path.exists(p):
                continue
            ln, pos, t = e.get("len", 0), e.get("pos", 0), e.get("t", 0)
            done = e.get("watched") or (ln and pos >= ln * 0.93)
            found = album_of.get(key(p))
            k = found[0]["key"] if found else key(p)
            if k in seen:
                continue
            seen.add(k)                       # only the newest song from each album counts
            if hidden.get(k, 0) >= t:
                continue                      # removed, and not played since
            if found:
                a, i = found
                if done:
                    i, pos = i + 1, 0
                    if i >= len(a["tracks"]):
                        continue              # the whole album is finished
                elif i == 0 and pos < 10_000:
                    continue                  # barely started
                frac = (pos / ln) if (ln and not done) else 0
                out.append({"key": k, "album": a, "index": i, "path": a["tracks"][i], "pos": pos,
                            "progress": (i + frac) / len(a["tracks"])})
            elif not done and pos > 10_000 and ln:
                out.append({"key": k, "album": None, "index": 0, "path": p, "pos": pos, "progress": pos / ln})
            if len(out) >= limit:
                break
        return out

    def _resume_listening(self, item):
        lib = self.win.library
        if item["album"]:
            self.win.set_queue(lib._queue_items(item["album"]["tracks"]), item["index"], keep_playing=True)
            self.win.play_queue_index(item["index"], start_ms=item["pos"])
        else:
            self.win.play_from_folder(item["path"], start_ms=item["pos"])

    def _hide_listening(self, k):
        self.store.data.setdefault("listen_hidden", {})[k] = time.time()
        self.store.save("library")
        self.refresh()

    def _sec_listening(self, lay):
        items = self._listen
        if not items:
            return
        lib = self.win.library
        lay.addWidget(self._section("Continue listening"))
        row = FlowRow()
        for it in items:
            p, a = it["path"], it["album"]
            song = lib.music.title_of(p, lib.music.songs.get(p, {})) if a else pretty_title(p)
            if a:
                n = len(a["tracks"])
                cover = lib._cover(a["art"], 40).pixmap(40, 40) if a["art"] else None
                sub = f"Song {it['index'] + 1} of {n}  ·  {song}"
                c = Card(a["album"], sub, "music", progress=it["progress"], picture=cover)
                self._bind_card_menu(c, "album", a["key"])
                c.setToolTip(f"{a['artist']}  ·  {a['album']}\nNext: {song}")
            else:
                c = Card(song, f"{fmt_time(it['pos'])}  ·  {_parent(p)}", "music", progress=it["progress"])
                self._bind_card_menu(c, "media", p)
                c.setToolTip(p)
            c.clicked.connect(lambda it=it: self._resume_listening(it))
            c.add_corner_button("close", "Remove from Continue listening", lambda k=it["key"]: self._hide_listening(k))
            row.add(c)
        lay.addWidget(hscroll(row))

    def _sec_music(self, lay):
        """Continue listening (#55), then albums from your library: pinned ones first, then the newest (#53)."""
        self._sec_listening(lay)
        lib = self.win.library
        m = lib.music
        albums = m.albums() if m.songs else []
        if not albums:
            return
        newest = lambda a: max((m.songs.get(p, {}).get("mtime", 0) for p in a["tracks"]), default=0)
        first, rest = lib.with_pins("albums", albums, lambda a: a["key"])
        rest.sort(key=newest, reverse=True)
        lay.addWidget(self._section("Music"))
        row = FlowRow()
        for a in (first + rest)[:12]:
            n = len(a["tracks"])
            cover = lib._cover(a["art"], 40).pixmap(40, 40) if a["art"] else None
            c = Card(a["album"], f"{a['artist']}  ·  {n} song{'s' if n != 1 else ''}", "music", picture=cover)
            self._bind_card_menu(c, "album", a["key"])
            c.clicked.connect(lambda t=a["tracks"]: lib.play_songs(t))
            row.add(c)
        lay.addWidget(hscroll(row))

    def _sec_streams(self, lay):
        lib = self.win.library
        streams = self.store.data["streams"]
        if streams:
            lay.addWidget(self._section("Streams"))
            row = FlowRow()
            first, rest = lib.with_pins("streams", streams, lambda x: x["url"])  # pinned first (#52)
            for s in (first + rest)[:12]:
                n = lib.channel_count(s)
                c = Card(s["name"], f"{n} channels" if n > 1 else s["url"], "stream")
                self._bind_card_menu(c, "stream", s["url"])
                c.clicked.connect(lambda u=s["url"]: self.win.play_saved_stream(u))
                row.add(c)
            lay.addWidget(hscroll(row))

    def _remove_history_item(self, path):
        self.store.data["recent"] = [r for r in self.store.data["recent"] if r["path"] != path]
        self.store.data["positions"].pop(path, None)
        self.store.save("recent")
        self.win.library.refresh_recent()

    def _card_actions(self, kind, value):
        lib, win = self.win.library, self.win
        if kind == "media":
            watched = self.store.position(value).get("watched", False)
            return [("Play", lambda: win.play_from_folder(value)),
                    ("Add to queue", lambda: win.enqueue([value])),
                    ("Mark as unwatched" if watched else "Mark as watched",
                     lambda: self.store.set_watched(value, not watched)),
                    ("Remove from history (including resume position)", lambda: self._remove_history_item(value))]
        if kind == "folder":
            return [("Open folder", lambda: win.browse_folder(value)),
                    ("Play folder", lambda: win.play_folder(value)),
                    ("Add folder to queue", lambda: win.enqueue(list_media(value))),
                    ("Save folder to playlist…", lambda: lib.save_to_playlist(list_media(value), os.path.basename(os.path.normpath(value))))]
        if kind == "album":
            album = next((x for x in lib.music.albums() if x["key"] == value), None)
            tracks = album["tracks"] if album else []
            pinned = lib.is_pinned("albums", value)
            return [("Play", lambda: lib.play_songs(tracks)),
                    ("Add to queue", lambda: win.enqueue(tracks)),
                    ("Unpin" if pinned else "Pin to top", lambda: lib.toggle_item_pin("albums", value))]
        if kind == "playlist":
            return [("Play", lambda: win.play_playlist(value)),
                    ("Add to queue", lambda: win.enqueue(self.store.data["playlists"].get(value, []))),
                    ("Rename…", lambda: lib._pl_rename(value)),
                    ("Export as .m3u…", lambda: lib._pl_export(value))]
        s = lib.stream_entry(value) or {}
        add = ((lambda: win.enqueue_items([{"path": c["url"], "title": c["name"]} for c in s["channels"]]))
               if s.get("channels") else (lambda: win.enqueue([value])))
        return [("Play", lambda: win.play_saved_stream(value)),
                ("Add to queue", add),
                ("Remove saved stream", lambda: lib._st_remove(value))]

    def _bind_card_menu(self, card, kind, value):
        card.setContextMenuPolicy(Qt.CustomContextMenu)
        card.customContextMenuRequested.connect(lambda pos: self._card_menu(card, kind, value, pos))

    def _card_menu(self, card, kind, value, pos):
        menu = QMenu(self)
        for label, callback in self._card_actions(kind, value):
            def invoke(_=False, fn=callback):
                def run():
                    fn()
                    self.refresh()
                QTimer.singleShot(0, run)
            menu.addAction(label, invoke)
        menu.exec(card.mapToGlobal(pos))

    def _section(self, text):
        lab = QLabel(text)
        lab.setObjectName("H2")
        lab.setContentsMargins(0, 14, 0, 2)
        return lab

    def _muted(self, text):
        lab = QLabel(text)
        lab.setObjectName("Muted")
        lab.setWordWrap(True)
        return lab


def _parent(p):
    if is_url(p):
        return ""
    return os.path.basename(os.path.dirname(p))


class NowPlayingPage(QWidget):
    """Shown for audio files: big cover art and track details."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setObjectName("NowPlaying")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 70, 40, 100)
        lay.setSpacing(14)
        lay.addStretch(1)
        self.art = QLabel()
        self.art.setAlignment(Qt.AlignCenter)
        self.art.setMinimumSize(160, 160)
        self.art.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        lay.addWidget(self.art, 6)
        self.title = QLabel("")
        self.title.setObjectName("H1")
        self.title.setAlignment(Qt.AlignCenter)
        self.sub = QLabel("")
        self.sub.setObjectName("Muted")
        self.sub.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.title)
        lay.addWidget(self.sub)
        lay.addStretch(1)
        self._pix = None

    def load(self, path: str, meta: dict):
        self.title.setText(meta.get("title") or display_name(path))
        parts = [meta.get(k) for k in ("artist", "album") if meta.get(k)]
        self.sub.setText("  ·  ".join(parts) or (os.path.dirname(path) if not is_url(path) else path))
        pix = None
        art = meta.get("art")
        if art:
            pix = QPixmap(to_path(art))
        if (pix is None or pix.isNull()) and not is_url(path):
            folder = os.path.dirname(path)
            for name in ("cover.jpg", "cover.png", "folder.jpg", "folder.png", "front.jpg", "AlbumArt.jpg"):
                p = os.path.join(folder, name)
                if os.path.isfile(p):
                    pix = QPixmap(p)
                    break
        self._pix = pix if pix is not None and not pix.isNull() else None
        self._render()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._render()

    def _render(self):
        side = max(120, min(self.art.width(), self.art.height(), 520))
        if self._pix:
            self.art.setPixmap(self._pix.scaled(side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.art.setPixmap(pixmap("music", theme.accent(), int(side * 0.45)))
