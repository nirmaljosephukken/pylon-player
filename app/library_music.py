"""Library panel: the Music tab (artists, albums and songs with cover art)."""
import random

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QListWidgetItem, QMenu, QPushButton,
                               QVBoxLayout, QWidget)

from . import theme
from .icons import icon
from .library_widgets import ROLE_KIND, ROLE_PATH, MediaList, TwoLineDelegate, reveal
from .util import fmt_time
from .widgets import IconButton


class MusicMixin:
    # ================================================================ music
    def _build_music(self):
        from .music import MusicLibrary
        from .sidebar import ChipGroup
        self.music = MusicLibrary(self.store, self)
        self.music.progress.connect(self._music_progress)
        self.music.finished.connect(self._music_done)
        self._music_stale = True
        self.music_mode = "artists"
        self.music_trail: list = []        # drill-down: [("artist", name) | ("album", key)]
        self._icons: dict = {}

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 0, 8, 4)
        lay.setSpacing(6)
        self.music_tabs = ChipGroup([("Artists", "artists"), ("Albums", "albums"), ("Songs", "songs")], cols=3)
        self.music_tabs.picked.connect(self._music_mode)
        self.music_tabs.select("artists")
        lay.addWidget(self.music_tabs)

        tools = QHBoxLayout()
        tools.setSpacing(4)
        self.music_back = IconButton("chevron_left", "Back", size=16)
        self.music_back.clicked.connect(self._music_up)
        self.music_search = QLineEdit()
        self.music_search.setPlaceholderText("Search music")
        self.music_search.addAction(icon("search", theme.MUTED, 16), QLineEdit.LeadingPosition)
        self.music_search.textChanged.connect(lambda _: self.refresh_music())
        rescan = IconButton("rotate", "Look for new music", size=16)
        rescan.clicked.connect(lambda: self._scan_music(force=True))
        self.music_shuffle = IconButton("shuffle", "Shuffle all: play the songs here in a random order", size=16)
        self.music_shuffle.clicked.connect(self.shuffle_songs)
        tools.addWidget(self.music_back)
        tools.addWidget(self.music_search, 1)
        tools.addWidget(self.music_shuffle)
        tools.addWidget(rescan)
        lay.addLayout(tools)

        self._sort_controls(lay, "music", self.refresh_music)
        self.music_crumb = QLabel("")
        self.music_crumb.setObjectName("Muted")
        self.music_crumb.setStyleSheet(f"color: {theme.MUTED}; font-size: 12px;")
        lay.addWidget(self.music_crumb)

        # album header: cover, name, details, play
        self.album_head = QWidget()
        ah = QHBoxLayout(self.album_head)
        ah.setContentsMargins(0, 2, 0, 4)
        ah.setSpacing(10)
        self.album_cover = QLabel()
        self.album_cover.setFixedSize(84, 84)
        ah.addWidget(self.album_cover)
        av = QVBoxLayout()
        av.setSpacing(2)
        self.album_name = QLabel()
        self.album_name.setWordWrap(True)
        self.album_name.setStyleSheet("font-size: 15px; font-weight: 700;")
        self.album_meta = QLabel()
        self.album_meta.setObjectName("Muted")
        self.album_meta.setWordWrap(True)
        self.album_meta.setStyleSheet(f"color: {theme.MUTED}; font-size: 12px;")
        self.album_play = QPushButton("Play")
        self.album_play.setObjectName("Primary")
        self.album_play.setIcon(icon("play", "#111111", 14))
        self.album_play.setCursor(Qt.PointingHandCursor)
        self.album_play.clicked.connect(lambda: self.play_songs(self._album_by_key(self._album_key)["tracks"])
                                        if self._album_by_key(self._album_key) else None)
        av.addWidget(self.album_name)
        av.addWidget(self.album_meta)
        av.addStretch(1)
        av.addWidget(self.album_play, 0, Qt.AlignLeft)
        ah.addLayout(av, 1)
        self.album_head.hide()
        self._album_key = None
        lay.addWidget(self.album_head)

        self.music_list = MediaList()
        self.music_list.setUniformItemSizes(False)
        self.music_list.setSpacing(1)
        self.music_list.setItemDelegate(TwoLineDelegate(self.music_list))
        self.music_list.setTextElideMode(Qt.ElideRight)
        self.music_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.music_list.itemDoubleClicked.connect(self._music_activate)
        self.music_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.music_list.customContextMenuRequested.connect(self._music_menu)
        lay.addWidget(self.music_list, 1)
        self.music_status = QLabel("")
        self.music_status.setObjectName("Muted")
        self.music_status.setWordWrap(True)
        self.music_status.setStyleSheet(f"color: {theme.FAINT}; font-size: 11px;")
        lay.addWidget(self.music_status)
        self.stack.addWidget(w)

    def _open_music(self):
        self._scan_music()
        self.refresh_music()

    def _scan_music(self, force=False):
        if self.music.scanning:
            return
        if force or self._music_stale:
            self._music_stale = False
            if not self.store.data["library_folders"]:
                return
            self.music.scan()
            self.music_status.setText("Looking for music in your library folders…")

    def _music_progress(self, done, total):
        if total:
            self.music_status.setText(f"Reading your music… {done} of {total}")

    def _music_done(self):
        n = len(self.music.songs)
        self.music_status.setText(f"{n} song{'s' if n != 1 else ''}" if n else "")
        if self.stack.currentIndex() == 4:
            self.refresh_music()
        self.win.home.refresh()                  # the home screen's Music section (#53)

    def _music_mode(self, mode):
        self.music_mode = mode
        self.music_trail = []
        self.refresh_music()

    def _music_up(self):
        if self.music_trail:
            self.music_trail.pop()
            self.refresh_music()

    def _cover(self, art, size):
        key = (art, size)
        if key not in self._icons:
            pm = QPixmap(art) if art else QPixmap()
            if pm.isNull():
                self._icons[key] = icon("music", theme.accent(), size)
            else:
                dpr = self.devicePixelRatioF() or 1.0
                side = int(size * dpr)
                pm = pm.scaled(side, side, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                pm = pm.copy((pm.width() - side) // 2, (pm.height() - side) // 2, side, side)
                pm.setDevicePixelRatio(dpr)
                self._icons[key] = QIcon(pm)
        return self._icons[key]

    def _music_item(self, text, kind, value, ic=None, tip=""):
        it = QListWidgetItem(text)
        if ic is not None:
            it.setIcon(ic)
        it.setData(ROLE_PATH, value)
        it.setData(ROLE_KIND, kind)
        if tip:
            it.setToolTip(tip)
        self.music_list.addItem(it)
        return it

    def _album_by_key(self, key):
        artist = next((value for kind, value in self.music_trail if kind == "artist"), None)
        if artist is not None:
            return next((a for a in dict(self.music.artists()).get(artist, []) if a["key"] == key), None)
        return next((a for a in self.music.albums() if a["key"] == key), None)

    def refresh_music(self):
        try:
            self._refresh_music_contents()
        finally:
            kinds = {"artist", "album", "file"}
            n = sum(self.music_list.item(i).data(ROLE_KIND) in kinds for i in range(self.music_list.count()))
            scope = "songs" if self.music_trail and self.music_trail[-1][0] == "album" else (
                "albums" if self.music_trail else self.music_mode)
            self.music_count.setText(f"{n} {scope}")

    def _refresh_music_contents(self):
        lst = self.music_list
        lst.clear()
        m = self.music
        scope = "songs" if self.music_trail and self.music_trail[-1][0] == "album" else (
            "albums" if self.music_trail else self.music_mode)
        self.music_search.setPlaceholderText("Search " + scope)
        self.music_sort.set_kind_enabled("count", scope != "songs")
        self.music_sort.combo.setToolTip("Items sorts artists and albums by their number of songs. "
                                         "Date modified uses the newest song file in each group.")
        q = self.music_search.text().strip().lower()
        current = self.win.engine.current
        self.music_back.setEnabled(bool(self.music_trail))
        self.album_head.hide()
        songs = m.songs

        def song_text(p, with_artist=True):
            s = songs.get(p, {})
            t = m.title_of(p, s)
            n = f"{s['track']}.  " if s.get("track") and not with_artist else ""
            dur = f"\t{fmt_time(s['dur'])}" if s.get("dur") else ""
            line2 = f"\n{m.artist_of(s)}  ·  {m.album_of(p, s)}" if with_artist else ""
            return f"{n}{t}{dur}{line2}"

        def add_song(p, with_artist=True):
            s = songs.get(p, {})
            it = self._music_item(song_text(p, with_artist), "file", p,
                                  self._cover(s.get("art", ""), 36) if with_artist else icon("music", theme.FAINT, 18), p)
            if p == current:
                f = it.font()
                f.setBold(True)
                it.setFont(f)
                it.setForeground(Qt.white)

        if not songs:
            lst.setIconSize(QSize(18, 18))
            self.music_crumb.setText("")
            msg = ("Add a folder with music to your library (Library tab,  + ) and it shows up here."
                   if not self.store.data["library_folders"] else
                   ("Reading your music…" if m.scanning else "No songs found in your library folders."))
            it = QListWidgetItem(msg)
            it.setFlags(Qt.NoItemFlags)
            lst.addItem(it)
            return

        trail = self.music_trail
        if trail and trail[-1][0] == "album":
            a = self._album_by_key(trail[-1][1])
            if not a:
                self.music_trail = []
                return self.refresh_music()
            self.music_crumb.setText(f"{a['artist']}  ›  {a['album']}")
            total = sum(songs.get(p, {}).get("dur", 0) for p in a["tracks"])
            self._album_key = a["key"]
            self.album_cover.setPixmap(self._cover(a["art"], 84).pixmap(84, 84))
            self.album_name.setText(a["album"])
            self.album_meta.setText(f"{a['artist']}{'  ·  ' + a['year'] if a['year'] else ''}\n"
                                    f"{len(a['tracks'])} song{'s' if len(a['tracks']) != 1 else ''}  ·  {fmt_time(total)}")
            self.album_head.show()
            lst.setIconSize(QSize(18, 18))
            for p in self._ordered(a["tracks"], "music", lambda p: m.title_of(p, songs.get(p, {})),
                                   modified=lambda p: songs.get(p, {}).get("mtime", 0),
                                   played=self._last_played, plays=self._play_count):
                if q and q not in song_text(p).lower():
                    continue
                add_song(p, with_artist=False)
            return

        if trail and trail[-1][0] == "artist":
            name = trail[-1][1]
            albums = dict(m.artists()).get(name, [])
            self.music_crumb.setText(f"Artists  ›  {name}")
            lst.setIconSize(QSize(44, 44))
            n = sum(len(a["tracks"]) for a in albums)
            self._music_item(f"Play all\n{n} songs", "play_artist", name, icon("play", theme.accent(), 44))
            for a in self._ordered(albums, "music", lambda a: a["album"], lambda a: len(a["tracks"]),
                                   lambda a: max((songs.get(p, {}).get("mtime", 0) for p in a["tracks"]), default=0),
                                   played=lambda a: self._last_played_of(a["tracks"]),
                                   plays=lambda a: self._play_count_of(a["tracks"])):
                if q and q not in a["album"].lower():
                    continue
                self._music_item(f"{a['album']}\n{a['year'] + '  ·  ' if a['year'] else ''}{len(a['tracks'])} songs",
                                 "album", a["key"], self._cover(a["art"], 44))
            return

        self.music_crumb.setText("")
        if self.music_mode == "artists":
            lst.setIconSize(QSize(44, 44))
            artists = [x for x in self._ordered(m.artists(), "music", lambda x: x[0],
                       lambda x: sum(len(a["tracks"]) for a in x[1]),
                       lambda x: max((songs.get(p, {}).get("mtime", 0) for a in x[1] for p in a["tracks"]), default=0),
                       played=lambda x: self._last_played_of(p for a in x[1] for p in a["tracks"]),
                       plays=lambda x: self._play_count_of(p for a in x[1] for p in a["tracks"]))
                       if not q or q in x[0].lower()]

            def add_artist(x, pinned):
                name, albums = x
                n = sum(len(a["tracks"]) for a in albums)
                art = next((a["art"] for a in albums if a["art"]), "")
                self._music_item(f"{name}\n{len(albums)} album{'s' if len(albums) != 1 else ''}  ·  {n} song{'s' if n != 1 else ''}",
                                 "artist", name, self._cover(art, 44))

            self._fill_with_pins(lst, *self.with_pins("artists", artists, lambda x: x[0]), "Artists", add_artist)
        elif self.music_mode == "albums":
            lst.setIconSize(QSize(44, 44))
            albums = [a for a in self._ordered(m.albums(), "music", lambda a: a["album"], lambda a: len(a["tracks"]),
                      lambda a: max((songs.get(p, {}).get("mtime", 0) for p in a["tracks"]), default=0),
                      played=lambda a: self._last_played_of(a["tracks"]),
                      plays=lambda a: self._play_count_of(a["tracks"]))
                      if not q or q in f"{a['album']} {a['artist']}".lower()]

            def add_album(a, pinned):
                self._music_item(f"{a['album']}\n{a['artist']}{'  ·  ' + a['year'] if a['year'] else ''}",
                                 "album", a["key"], self._cover(a["art"], 44))

            self._fill_with_pins(lst, *self.with_pins("albums", albums, lambda a: a["key"]), "Albums", add_album)
        else:
            lst.setIconSize(QSize(36, 36))
            for p in self._ordered(m.all_songs(), "music", lambda p: m.title_of(p, songs.get(p, {})),
                                   modified=lambda p: songs.get(p, {}).get("mtime", 0),
                                   played=self._last_played, plays=self._play_count):
                if q and q not in song_text(p).lower():
                    continue
                add_song(p)

    def _last_played(self, path):
        return self.store.plays(path).get("t", 0)

    def _play_count(self, path):
        return self.store.plays(path).get("n", 0)

    def _last_played_of(self, paths):
        return max((self._last_played(p) for p in paths), default=0)

    def _play_count_of(self, paths):
        return sum(self._play_count(p) for p in paths)

    def _scope_songs(self):
        """The songs the Music tab is showing: an album, an artist, or everything."""
        trail = self.music_trail
        if trail and trail[-1][0] == "album":
            a = self._album_by_key(trail[-1][1])
            return list(a["tracks"]) if a else []
        if trail and trail[-1][0] == "artist":
            return self._artist_tracks(trail[-1][1])
        return list(self.music.all_songs())

    def shuffle_songs(self):
        """Shuffle all: every song in the current view, in a random order."""
        paths = self._scope_songs()
        if not paths:
            self.win.toast("No songs to shuffle")
            return
        random.shuffle(paths)
        self.play_songs(paths)
        self.win.toast(f"Shuffling {len(paths)} song{'s' if len(paths) != 1 else ''}")

    def _visible_songs(self):
        return [self.music_list.item(i).data(ROLE_PATH) for i in range(self.music_list.count())
                if self.music_list.item(i).data(ROLE_KIND) == "file"]

    def _queue_items(self, paths):
        m = self.music
        out = []
        for p in paths:
            s = m.songs.get(p, {})
            out.append({"path": p, "title": f"{m.title_of(p, s)}  ·  {m.artist_of(s)}"})
        return out

    def _artist_tracks(self, name):
        return [p for a in dict(self.music.artists()).get(name, []) for p in a["tracks"]]

    def play_songs(self, paths, index=0):
        if paths:
            self.win.set_queue(self._queue_items(paths), index)

    def _music_activate(self, it):
        kind, val = it.data(ROLE_KIND), it.data(ROLE_PATH)
        if kind == "artist":
            self.music_trail.append(("artist", val))
            self.music_search.clear()
            self.refresh_music()
        elif kind == "album":
            self.music_trail.append(("album", val))
            self.music_search.clear()
            self.refresh_music()
        elif kind == "play_album":
            a = self._album_by_key(val)
            if a:
                self.play_songs(a["tracks"])
        elif kind == "play_artist":
            self.play_songs(self._artist_tracks(val))
        elif kind == "file":
            paths = self._visible_songs()
            self.play_songs(paths, paths.index(val) if val in paths else 0)

    def _music_menu(self, pos):
        it = self.music_list.itemAt(pos)
        if not it or not it.data(ROLE_KIND):
            return
        kind, val = it.data(ROLE_KIND), it.data(ROLE_PATH)
        if kind in ("album", "play_album"):
            a = self._album_by_key(val)
            paths = a["tracks"] if a else []
        elif kind in ("artist", "play_artist"):
            paths = self._artist_tracks(val)
        else:
            paths = self._selected_files(self.music_list) or [val]
        m = QMenu(self)
        m.addAction(icon("play", theme.TEXT, 16), "Play", lambda: self.play_songs(paths))
        m.addAction(icon("queue", theme.TEXT, 16), "Add to queue",
                    lambda: self.win.enqueue(paths))
        m.addAction("Play next", lambda: self.win.enqueue(paths, play_next=True))
        if len(paths) > 1:
            m.addAction(icon("shuffle", theme.TEXT, 16), "Shuffle",
                        lambda: self.play_songs(random.sample(paths, len(paths))))
        self._playlist_submenu(m, paths)
        if kind in ("artist", "album"):
            pin_kind = kind + "s"
            pinned = self.is_pinned(pin_kind, val)
            m.addAction(icon("pin", theme.TEXT, 16), "Unpin" if pinned else "Pin to top",
                        lambda: self.toggle_item_pin(pin_kind, val))
        if kind == "file":
            m.addSeparator()
            m.addAction("Show in Explorer", lambda: reveal(val))
        m.exec(self.music_list.mapToGlobal(pos))
