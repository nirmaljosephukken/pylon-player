"""Left sidebar: the library in compact mode, with the queue underneath.

Library  : your folders, browsable with back / up / address line, search,
           sorting (incl. unwatched first) and drag-to-queue.
Music    : songs from those folders by artist, album and title, with cover art.
Recent   : recently played files.
Playlists: named collections; double-click to load into the queue.
Streams  : saved network streams and channel lists.
Queue    : what plays next. Drag in from the library or from Explorer.
"""
import os
import time

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox,
                               QPushButton, QSplitter, QStackedWidget, QVBoxLayout, QWidget)

from . import theme
from .icons import icon
from .util import (display_name, fmt_time, is_audio, is_disc, is_dvd_folder, is_media, is_url, list_media, merge_in_name_order,
                   natural_key, norm, parse_m3u, sort_key_by_name)
from .library_music import MusicMixin
from .library_queue import QueueMixin
from .library_widgets import (ROLE_KIND, ROLE_PATH, ChannelListDrop, MediaList, QueueList,  # noqa: F401
                              SortControl, TwoLineDelegate, _mtime, media_filter, pick_media, reveal, sort_kind,
                              win_call)
from .widgets import IconButton


class LibraryPanel(MusicMixin, QueueMixin, QWidget):
    WIDTH = 320
    SECTIONS = ("library", "recent", "playlists", "streams", "music")   # order of the stacked pages

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.store = win.store
        self.setObjectName("Panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(self.WIDTH)
        self.folder = None        # current folder in the browser (None = library root)
        self.history: list = []
        self.forward: list = []
        self.sort_mode = self.store.setting("library_sort") or "name"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- header: section switcher
        head = QHBoxLayout()
        head.setContentsMargins(8, 8, 8, 4)
        head.setSpacing(2)
        self.nav_buttons = {}
        for key, ic, tip in (("library", "library", "Library"), ("music", "music", "Music"), ("recent", "clock", "Recent"),
                             ("playlists", "playlist", "Playlists"), ("streams", "stream", "Network streams")):
            b = IconButton(ic, tip, size=18, checkable=True)
            b.clicked.connect(lambda _=False, k=key: self._nav_clicked(k))
            self.nav_buttons[key] = b
            head.addWidget(b)
        head.addStretch(1)
        home = IconButton("home", "Home page", size=18)
        home.clicked.connect(win.show_home)
        head.addWidget(home)
        close = IconButton("close", "Close", size=16)
        close.clicked.connect(lambda: win.toggle_library(False))
        head.addWidget(close)
        root.addLayout(head)

        self.section_title = QLabel("Library")
        self.section_title.setObjectName("H2")
        self.section_title.setContentsMargins(14, 2, 14, 4)
        root.addWidget(self.section_title)

        split = QSplitter(Qt.Vertical)
        split.setHandleWidth(1)
        split.setChildrenCollapsible(False)
        root.addWidget(split, 1)

        self.stack = QStackedWidget()
        split.addWidget(self.stack)
        self._build_library()
        self._build_recent()
        self._build_playlists()
        self._build_streams()
        self._build_music()

        # --- queue
        qw = QWidget()
        ql = QVBoxLayout(qw)
        ql.setContentsMargins(8, 6, 8, 8)
        ql.setSpacing(4)
        qh = QHBoxLayout()
        qt = QLabel("Queue")
        qt.setObjectName("H2")
        self.queue_count = QLabel("")
        self.queue_count.setObjectName("Muted")
        qh.addWidget(qt)
        qh.addWidget(self.queue_count)
        qh.addStretch(1)
        self._unshuffled = None          # the queue's order before shuffling (None = shuffle is off)
        for ic, tip, fn in (("plus", "Add files to the queue", self._add_files_to_queue),
                            ("mode_next", "", win.cycle_queue_mode),
                            ("save", "Save the queue as a playlist, or a list of streams as a channel list", self._save_queue_as_playlist),
                            ("trash", "Clear queue", lambda: win.set_queue([], -1))):
            b = IconButton(ic, tip, size=16)
            b.clicked.connect(lambda *_, fn=fn: fn())
            qh.addWidget(b)
            if ic == "mode_next":
                self.mode_btn = b
                b._color = self._mode_color
        ql.addLayout(qh)
        self.queue_search = QLineEdit()
        self.queue_search.setPlaceholderText("Search the queue")
        self.queue_search.setClearButtonEnabled(True)
        self.queue_search.textChanged.connect(lambda _: self._filter_queue())
        ql.addWidget(self.queue_search)
        self.queue = QueueList()
        self.queue.itemDoubleClicked.connect(lambda it: win.play_queue_index(self.queue.row(it)))
        self.queue.dropped_urls.connect(self._queue_drop)
        self.queue.reordered.connect(self._queue_reordered)
        self.queue.setContextMenuPolicy(Qt.CustomContextMenu)
        self.queue.customContextMenuRequested.connect(self._queue_menu)
        for seq in (QKeySequence.Delete, QKeySequence(Qt.Key_Backspace)):
            sc = QShortcut(seq, self.queue)
            sc.setContext(Qt.WidgetShortcut)
            sc.activated.connect(self._queue_delete_key)
        ql.addWidget(self.queue)
        hint = QLabel("Drag files here from the library or from your folders")
        hint.setObjectName("Muted")
        hint.setStyleSheet(f"color: {theme.FAINT}; font-size: 11px;")
        ql.addWidget(hint)
        split.addWidget(qw)
        split.setSizes([460, 260])

        selected = self.store.setting("library_startup_tab")
        if selected == "last":
            selected = self.store.setting("library_last_tab")
        self.show_section(selected if selected in self.nav_buttons else "library")
        self.store.changed.connect(self._store_changed)

    # ================================================================ sections
    def _nav_clicked(self, key):
        """Clicking the tab you're already on goes back to its start (#35)."""
        here = self.stack.currentIndex() == self.SECTIONS.index(key)
        if here and key == "library" and self.folder is not None:
            self.open_folder(None)      # recorded, so Back still returns to the folder
            return
        if here and key == "music" and self.music_trail:
            self.music_trail = []
        self.show_section(key)

    def show_section(self, key):
        self.store.set_setting("library_last_tab", key)
        idx = self.SECTIONS.index(key)
        self.stack.setCurrentIndex(idx)
        for k, b in self.nav_buttons.items():
            b.setChecked(k == key)
        self.section_title.setText({"library": "Library", "recent": "Recent", "playlists": "Playlists",
                                    "streams": "Network streams", "music": "Music"}[key])
        {"library": self.refresh_library, "recent": self.refresh_recent,
         "playlists": self.refresh_playlists, "streams": self.refresh_streams,
         "music": self._open_music}[key]()

    def _store_changed(self, section):
        if section in ("recent",) and self.stack.currentIndex() == 1:
            self.refresh_recent()
        elif section in ("library",) and self.stack.currentIndex() == 0:
            self.refresh_library()
        elif section == "playlists" and self.stack.currentIndex() == 2:
            self.refresh_playlists()

    # ---------------------------------------------------------------- library
    def _build_library(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 0, 8, 4)
        lay.setSpacing(6)
        nav = QHBoxLayout()
        nav.setSpacing(2)
        self.btn_back = IconButton("chevron_left", "Back", size=16)
        self.btn_fwd = IconButton("chevron_right", "Forward", size=16)
        self.btn_up = IconButton("arrow_up", "Up one folder", size=16)
        self.btn_back.clicked.connect(self.go_back)
        self.btn_fwd.clicked.connect(self.go_forward)
        self.btn_up.clicked.connect(self.go_up)
        self.address = QLineEdit()
        self.address.setPlaceholderText("Library")
        self.address.setToolTip("Type a folder path and press Enter")
        self.address.returnPressed.connect(lambda: self.open_folder(self.address.text().strip() or None))
        nav.addWidget(self.btn_back)
        nav.addWidget(self.btn_fwd)
        nav.addWidget(self.btn_up)
        nav.addWidget(self.address, 1)
        lay.addLayout(nav)

        tools = QHBoxLayout()
        tools.setSpacing(4)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search")
        self.search.addAction(icon("search", theme.MUTED, 16), QLineEdit.LeadingPosition)
        self.search.textChanged.connect(lambda _: self.refresh_library())
        self.btn_sort = IconButton("sort", "Sort", size=16)
        self.btn_sort.setPopupMode(IconButton.InstantPopup)
        sm = QMenu(self)
        self.sort_actions = {}
        for key, label in (("name", "Name"), ("date", "Date modified (newest)"),
                           ("unwatched", "Unwatched first"), ("watched", "Watched first")):
            a = QAction(label, sm, checkable=True)
            a.triggered.connect(lambda _=False, k=key: self._set_sort(k))
            sm.addAction(a)
            self.sort_actions[key] = a
        self.sort_actions.get(self.sort_mode, self.sort_actions["name"]).setChecked(True)
        self.btn_sort.setMenu(sm)
        self.btn_add = IconButton("plus", "Add", size=16)
        self.btn_add.setPopupMode(IconButton.InstantPopup)
        am = QMenu(self)
        am.addAction(icon("folder_add", theme.TEXT, 16), "Add a folder to the library…", self.add_library_folder)
        am.addAction(icon("file", theme.TEXT, 16), "Open a file…", lambda: win_call(self.win.open_file_dialog))
        am.addAction(icon("folder", theme.TEXT, 16), "Open a folder…", lambda: win_call(self.win.open_folder_dialog))
        self.btn_add.setMenu(am)
        tools.addWidget(self.search, 1)
        tools.addWidget(self.btn_sort)
        tools.addWidget(self.btn_add)
        lay.addLayout(tools)

        self.lib_list = MediaList()
        self.lib_list.itemDoubleClicked.connect(self._lib_activate)
        self.lib_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.lib_list.customContextMenuRequested.connect(self._lib_menu)
        lay.addWidget(self.lib_list, 1)
        self.stack.addWidget(w)

    def _set_sort(self, key):
        self.sort_mode = key
        self.store.set_setting("library_sort", key)
        for k, a in self.sort_actions.items():
            a.setChecked(k == key)
        self.refresh_library()
        if self.win.home is not None:
            self.win.home.refresh()

    def open_folder(self, folder, record=True):
        if folder:
            folder = os.path.normpath(folder)
        if folder and not os.path.isdir(folder):
            QMessageBox.warning(self, "Folder not found", f"Can't open:\n{folder}")
            return
        if record and folder != self.folder:
            self.history.append(self.folder)
            self.forward.clear()
        self.folder = folder
        self.show_section("library")

    def go_back(self):
        if self.history:
            self.forward.append(self.folder)
            self.open_folder(self.history.pop(), record=False)

    def go_forward(self):
        if self.forward:
            self.history.append(self.folder)
            self.open_folder(self.forward.pop(), record=False)

    def go_up(self):
        if not self.folder:
            return
        roots = [os.path.normcase(f) for f in self.store.data["library_folders"]]
        if os.path.normcase(self.folder) in roots:
            self.open_folder(None)
            return
        parent = os.path.dirname(self.folder.rstrip("\\/"))
        self.open_folder(parent if parent and parent != self.folder else None)

    def refresh_library(self):
        self.lib_list.clear()
        self.btn_back.setEnabled(bool(self.history))
        self.btn_fwd.setEnabled(bool(self.forward))
        self.btn_up.setEnabled(self.folder is not None)
        self.address.setText(self.folder or "")
        q = self.search.text().strip().lower()
        pos = self.store.data["positions"]
        current = self.win.engine.current

        if self.folder is None:
            pinned = self.store.data["pinned"]
            folders = self.ordered_library_folders()
            if pinned:
                self._header(self.lib_list, "Pinned")
                for p in pinned:
                    if q and q not in os.path.basename(p).lower():
                        continue
                    self._add_folder_item(p, pinned=True)
            self._header(self.lib_list, "Folders")
            for f in folders:
                if q and q not in os.path.basename(f).lower():
                    continue
                self._add_folder_item(f)
            if not folders:
                it = QListWidgetItem("Add a folder with  +  to build your library")
                it.setFlags(Qt.NoItemFlags)
                self.lib_list.addItem(it)
            return

        try:
            entries = os.listdir(self.folder)
        except OSError:
            entries = []
        dirs, files = [], []
        for name in entries:
            p = os.path.join(self.folder, name)
            if q and q not in name.lower():
                continue
            if os.path.isdir(p) and not name.startswith("."):
                dirs.append(p)
            elif is_media(p):
                files.append(p)
        dirs.sort(key=lambda p: natural_key(os.path.basename(p)))
        files.sort(key=lambda p: natural_key(os.path.basename(p)))
        if self.sort_mode == "date":
            files.sort(key=lambda p: -_mtime(p))
            dirs.sort(key=lambda p: -_mtime(p))
        elif self.sort_mode in ("unwatched", "watched"):
            want = self.sort_mode == "watched"
            files.sort(key=lambda p: (bool(pos.get(p, {}).get("watched")) != want))
        for d in dirs:
            self._add_folder_item(d)
        for f in files:
            e = pos.get(f, {})
            watched = e.get("watched")
            prog = ""
            if not watched and e.get("len") and e.get("pos", 0) > 10_000:
                prog = f"   {fmt_time(e['pos'])} / {fmt_time(e['len'])}"
            name = os.path.basename(f)
            it = QListWidgetItem(name + prog)
            ic_name = "check" if watched else ("music" if is_audio(f) else "video")
            color = theme.FAINT if watched else (theme.accent() if f == current else theme.MUTED)
            it.setIcon(icon(ic_name, color, 18))
            if f == current:
                it.setForeground(Qt.white)
                font = it.font()
                font.setBold(True)
                it.setFont(font)
            if watched:
                it.setForeground(Qt.gray)
            it.setData(ROLE_PATH, f)
            it.setData(ROLE_KIND, "file")
            it.setToolTip(f)
            self.lib_list.addItem(it)
        if not dirs and not files:
            it = QListWidgetItem("No media files here")
            it.setFlags(Qt.NoItemFlags)
            self.lib_list.addItem(it)

    def ordered_library_folders(self):
        folders = list(self.store.data["library_folders"])
        if self.sort_mode == "name":
            folders.sort(key=lambda p: natural_key(os.path.basename(p)))
        elif self.sort_mode == "date":
            folders.sort(key=lambda p: (-_mtime(p), natural_key(os.path.basename(p))))
        return folders

    def _header(self, lst, text):
        it = QListWidgetItem(text.upper())
        it.setFlags(Qt.NoItemFlags)
        f = it.font()
        f.setPointSizeF(max(7.0, f.pointSizeF() - 1.5))
        f.setBold(True)
        it.setFont(f)
        it.setForeground(Qt.gray)
        lst.addItem(it)

    def _add_folder_item(self, path, pinned=False):
        dvd = is_dvd_folder(path)
        it = QListWidgetItem(icon("pin" if pinned else ("disc" if dvd else "folder"), theme.accent(), 18),
                             os.path.basename(path.rstrip("\\/")) or path)
        it.setData(ROLE_PATH, path)
        it.setData(ROLE_KIND, "folder")
        it.setToolTip(f"{path}\nA DVD: double-click to play it with its menu" if dvd else path)
        self.lib_list.addItem(it)

    def _lib_activate(self, it):
        kind, path = it.data(ROLE_KIND), it.data(ROLE_PATH)
        if kind == "folder" and is_dvd_folder(path):
            self.win.play_folder(path)
        elif kind == "folder":
            self.open_folder(path)
        elif kind == "file":
            self.win.play_from_folder(path)

    def _selected_files(self, lst):
        return [i.data(ROLE_PATH) for i in lst.selectedItems() if i.data(ROLE_KIND) == "file"]

    def _lib_menu(self, pos):
        it = self.lib_list.itemAt(pos)
        if not it or not it.data(ROLE_PATH):
            m = QMenu(self)
            m.addAction(icon("folder_add", theme.TEXT, 16), "Add a folder to the library…", self.add_library_folder)
            m.exec(self.lib_list.mapToGlobal(pos))
            return
        kind, path = it.data(ROLE_KIND), it.data(ROLE_PATH)
        m = QMenu(self)
        if kind == "file":
            files = self._selected_files(self.lib_list) or [path]
            m.addAction(icon("play", theme.TEXT, 16), "Play", lambda: self.win.play_from_folder(path))
            m.addAction(icon("queue", theme.TEXT, 16), "Add to queue", lambda: self.win.enqueue(files))
            m.addAction("Play next", lambda: self.win.enqueue(files, play_next=True))
            pm = m.addMenu(icon("playlist", theme.TEXT, 16), "Add to playlist")
            for name in sorted(self.store.data["playlists"]):
                pm.addAction(name, lambda n=name: self.add_to_playlist(n, files))
            pm.addSeparator()
            pm.addAction("New playlist…", lambda: self.new_playlist(files))
            m.addSeparator()
            watched = self.store.position(path).get("watched")
            m.addAction("Mark as unwatched" if watched else "Mark as watched",
                        lambda: [self.store.set_watched(f, not watched) for f in files])
            m.addAction(icon("subtitles", theme.TEXT, 16), "Add subtitles for this folder…",
                        lambda: self.win.open_subtitle_dialog(scope="folder", folder=os.path.dirname(path)))
            m.addAction("Show in Explorer", lambda: reveal(path))
        else:
            m.addAction(icon("disc" if is_dvd_folder(path) else "play", theme.TEXT, 16),
                        "Play DVD" if is_dvd_folder(path) else "Play folder", lambda: self.win.play_folder(path))
            m.addAction(icon("queue", theme.TEXT, 16), "Add folder to queue", lambda: self.win.enqueue(list_media(path)))
            m.addAction(icon("save", theme.TEXT, 16), "Save folder to playlist…",
                        lambda: self.save_to_playlist(list_media(path), os.path.basename(os.path.normpath(path))))
            pinned = path in self.store.data["pinned"]
            m.addAction(icon("pin", theme.TEXT, 16), "Unpin" if pinned else "Pin to top", lambda: self.toggle_pin(path))
            m.addAction(icon("subtitles", theme.TEXT, 16), "Add subtitles for this folder…",
                        lambda: self.win.open_subtitle_dialog(scope="folder", folder=path))
            m.addAction("Show in Explorer", lambda: reveal(path))
            if not self.is_library_folder(path):
                m.addAction(icon("folder_add", theme.TEXT, 16), "Add to library",
                            lambda: self.add_library_path(path))
            if path in self.store.data["library_folders"]:
                m.addSeparator()
                m.addAction(icon("trash", theme.TEXT, 16), "Remove from library", lambda: self.remove_library_folder(path))
        m.exec(self.lib_list.mapToGlobal(pos))

    def add_library_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Add a folder to the library")
        if d:
            self.add_library_path(d)
            self.open_folder(None)

    def is_library_folder(self, path):
        key = os.path.normcase(os.path.realpath(path))
        return any(os.path.normcase(os.path.realpath(p)) == key for p in self.store.data["library_folders"])

    def add_library_path(self, path):
        path = os.path.normpath(os.path.abspath(path))
        if not os.path.isdir(path) or self.is_library_folder(path):
            return False
        self.store.data["library_folders"].append(path)
        self._music_stale = True
        self.store.save("library")
        self.win.home.refresh()
        return True

    def remove_library_folder(self, path):
        self.store.data["library_folders"] = [f for f in self.store.data["library_folders"] if f != path]
        self.store.save("library")
        self._music_stale = True
        self.refresh_library()
        self.win.home.refresh()

    def toggle_pin(self, path):
        pins = self.store.data["pinned"]
        if path in pins:
            pins.remove(path)
        else:
            pins.insert(0, path)
        self.store.save("library")
        self.refresh_library()

    # ---------------------------------------------------------------- recent
    def _build_recent(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 0, 8, 4)
        self.recent_list = MediaList()
        self.recent_list.itemDoubleClicked.connect(lambda it: self.win.play_from_folder(it.data(ROLE_PATH)))
        self.recent_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.recent_list.customContextMenuRequested.connect(self._recent_menu)
        lay.addWidget(self.recent_list, 1)
        clear = QPushButton("Clear history")
        clear.clicked.connect(self._clear_history)
        lay.addWidget(clear)
        self.stack.addWidget(w)

    def refresh_recent(self):
        self.recent_list.clear()
        for r in self.store.data["recent"]:
            p = r["path"]
            it = QListWidgetItem(icon("stream" if is_url(p) else ("music" if is_audio(p) else ("disc" if is_disc(p) else "video")),
                                      theme.MUTED, 18), self.store.recent_title(r))
            it.setToolTip(f"{p}\n{time.strftime('%d %b, %H:%M', time.localtime(r['t']))}")
            it.setData(ROLE_PATH, p)
            it.setData(ROLE_KIND, "file")
            self.recent_list.addItem(it)

    def _recent_menu(self, pos):
        """The same choices as files in the Library tab, plus removing items from Recent (#51)."""
        it = self.recent_list.itemAt(pos)
        if not it or not it.data(ROLE_PATH):
            return
        path = it.data(ROLE_PATH)
        paths = [i.data(ROLE_PATH) for i in self.recent_list.selectedItems() if i.data(ROLE_PATH)]
        if path not in paths:
            paths = [path]
        win = self.win
        m = QMenu(self)
        m.addAction(icon("play", theme.TEXT, 16), "Play", lambda: win.play_from_folder(path))
        m.addAction(icon("queue", theme.TEXT, 16), "Add to queue", lambda: win.enqueue(paths))
        m.addAction("Play next", lambda: win.enqueue(paths, play_next=True))
        self._playlist_submenu(m, paths)
        m.addSeparator()
        if is_url(path):
            m.addAction("Copy link", lambda: self._copy_link(path))
            if path not in [s["url"] for s in self.store.data["streams"]]:
                m.addAction(icon("stream", theme.TEXT, 16), "Save to Streams", lambda: self.save_stream(path))
        else:
            files = [p for p in paths if not is_url(p)]
            watched = self.store.position(path).get("watched")
            m.addAction("Mark as unwatched" if watched else "Mark as watched",
                        lambda: [self.store.set_watched(f, not watched) for f in files])
            m.addAction("Show in Explorer", lambda: reveal(path))
        m.addSeparator()
        m.addAction(icon("trash", theme.TEXT, 16),
                    "Remove from Recent" if len(paths) == 1 else f"Remove {len(paths)} from Recent",
                    lambda: self.remove_recent(paths))
        m.exec(self.recent_list.mapToGlobal(pos))

    def remove_recent(self, paths):
        """Forget these items in Recent, along with where you stopped in each."""
        gone = set(paths)
        self.store.data["recent"] = [r for r in self.store.data["recent"] if r["path"] not in gone]
        for p in gone:
            self.store.data["positions"].pop(p, None)
        self.store.save("recent")
        self.refresh_recent()
        self.win.home.refresh()

    def _playlist_submenu(self, m, paths):
        pm = m.addMenu(icon("playlist", theme.TEXT, 16), "Add to playlist")
        for name in sorted(self.store.data["playlists"]):
            pm.addAction(name, lambda n=name: self.add_to_playlist(n, paths))
        pm.addSeparator()
        pm.addAction("New playlist…", lambda: self.new_playlist(paths))

    def save_stream(self, url, name=""):
        if url in [s["url"] for s in self.store.data["streams"]]:
            return
        self.store.data["streams"].insert(0, {"name": name or display_name(url), "url": url})
        self.store.save("streams")
        self.refresh_streams()
        self.win.toast("Saved to Streams")

    def _clear_history(self):
        if QMessageBox.question(self, "Clear history", "Forget recent files and where you stopped in each?") == QMessageBox.Yes:
            self.store.clear_history()
            self.refresh_recent()
            self.win.home.refresh()

    def _sort_controls(self, layout, section, refresh):
        row = QHBoxLayout()
        count = QLabel("")
        count.setObjectName("Muted")
        row.addWidget(count, 1)
        choice = SortControl(section, self._sort_mode(section))

        def changed(mode):
            self.store.set_setting(section + "_sort", mode)
            refresh()
            if section == "playlists" and self.win.home is not None:
                self.win.home.refresh()              # Home follows the Playlists tab (#37)
        choice.changed.connect(changed)
        row.addWidget(choice)
        layout.addLayout(row)
        setattr(self, section + "_count", count)
        setattr(self, section + "_sort", choice)

    def _sort_mode(self, section):
        mode = self.store.setting(section + "_sort") or "default"
        if section in ("playlists", "streams") and mode == "default":
            mode = "newest"
        return mode

    def _ordered(self, items, section, name, count=None, modified=None, newest_first=False,
                 played=None, plays=None, done=None):
        """newest_first: the saved list already has the most recent item at the top.
        played: when an item was last played; plays: how often; done: how much is watched (0..1).
        Each sort has a reversed mode, from the arrow next to it (#63)."""
        mode = self._sort_mode(section)
        kind, rev = sort_kind(mode)
        items = list(items)
        if kind == "added":
            return items if newest_first != rev else items[::-1]
        if kind == "name":
            return sorted(items, key=lambda x: natural_key(name(x)), reverse=rev)
        # largest first, unless reversed; watched goes least watched first
        value = {"played": played, "plays": plays, "count": count, "date": modified}.get(kind)
        if kind == "watched" and done:
            value, rev = done, not rev
        if not value:
            return items
        sign = 1 if rev else -1
        return sorted(items, key=lambda x: (sign * value(x), natural_key(name(x))))

    def ordered_playlists(self):
        """(name, entries) in the Playlists tab's order, for the tab and the home page."""
        return self._ordered(self.store.data["playlists"].items(), "playlists", lambda x: x[0],
                             lambda x: len(x[1]), played=lambda x: self.last_played_of(x[1]),
                             done=lambda x: self.playlist_progress(x[1])[2])

    def last_played_of(self, paths):
        """When anything in this list of files or links last played (Recently played, #63)."""
        return max((self.store.plays(p if is_url(p) else norm(p)).get("t", 0) for p in paths), default=0)

    # ---------------------------------------------------------------- playlists
    def _build_playlists(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 0, 8, 4)
        new = QPushButton("New playlist…")
        new.setIcon(icon("plus", theme.TEXT, 14))
        new.clicked.connect(lambda: self.new_playlist())
        lay.addWidget(new)
        self.pl_search = QLineEdit()
        self.pl_search.setPlaceholderText("Search playlists")
        self.pl_search.textChanged.connect(lambda _: self.refresh_playlists())
        lay.addWidget(self.pl_search)
        self._sort_controls(lay, "playlists", self.refresh_playlists)
        self.pl_list = QListWidget()
        self.pl_list.setIconSize(QSize(18, 18))
        self.pl_list.itemDoubleClicked.connect(lambda it: self.win.play_playlist(it.data(ROLE_PATH)))
        self.pl_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.pl_list.customContextMenuRequested.connect(self._pl_menu)
        lay.addWidget(self.pl_list, 1)
        self.stack.addWidget(w)

    # ---------------------------------------------------------------- pins (#52)
    def pins(self, kind):
        """Pinned items for a tab, newest pin first: streams (by link), playlists, artists, albums."""
        return self.store.data.setdefault("pins", {}).setdefault(kind, [])

    def is_pinned(self, kind, key):
        return key in self.pins(kind)

    def toggle_item_pin(self, kind, key):
        ps = self.pins(kind)
        if key in ps:
            ps.remove(key)
        else:
            ps.insert(0, key)
        self.store.save("library")
        {"streams": self.refresh_streams, "playlists": self.refresh_playlists}.get(kind, self.refresh_music)()
        self.win.home.refresh()

    def _rename_pin(self, kind, old, new):
        ps = self.pins(kind)
        if old in ps:
            ps[ps.index(old)] = new

    def _drop_pin(self, kind, key):
        ps = self.pins(kind)
        if key in ps:
            ps.remove(key)

    def with_pins(self, kind, items, key):
        """Split items into (pinned, the rest). Pinned items keep their pin order, whatever the sort."""
        pinned = self.pins(kind)
        by_key = {key(x): x for x in items}
        first = [by_key[k] for k in pinned if k in by_key]
        keys = set(pinned)
        return first, [x for x in items if key(x) not in keys]

    def _fill_with_pins(self, lst, first, rest, label, add):
        """Add items to a list: a Pinned group at the top when anything is pinned."""
        if first:
            self._header(lst, "Pinned")
            for x in first:
                add(x, True)
            if rest:
                self._header(lst, label)
        for x in rest:
            add(x, False)

    def refresh_playlists(self):
        self.pl_list.clear()
        q = self.pl_search.text().strip().casefold()
        items = [x for x in self.ordered_playlists() if q in x[0].casefold()]
        first, rest = self.with_pins("playlists", items, lambda x: x[0])

        def add(x, pinned):
            name, entries = x
            it = QListWidgetItem(icon("pin" if pinned else "playlist", theme.accent(), 18), f"{name}   ({len(entries)})")
            seen, files, _frac = self.playlist_progress(entries)
            if files:
                it.setToolTip(f"{seen} of {files} watched")
            it.setData(ROLE_PATH, name)
            self.pl_list.addItem(it)

        self._fill_with_pins(self.pl_list, first, rest, "Playlists", add)
        self.playlists_count.setText(f"{len(items)} playlists")
        if not self.store.data["playlists"]:
            it = QListWidgetItem("No playlists yet")
            it.setFlags(Qt.NoItemFlags)
            self.pl_list.addItem(it)

    def playlist_progress(self, entries):
        """(watched, files, fraction) for a playlist's local files; streams don't count."""
        files = [p for p in entries if not is_url(p)]
        seen = sum(1 for p in files if self.store.position(norm(p)).get("watched"))
        return seen, len(files), (seen / len(files) if files else 0.0)

    def new_playlist(self, files=None, suggested_name=""):
        name, ok = QInputDialog.getText(self, "New playlist", "Name", text=suggested_name)
        if not ok or not name.strip():
            return
        name = name.strip()
        if name in self.store.data["playlists"]:
            if QMessageBox.question(self, "Playlist exists",
                                    f"Add these files to “{name}” instead of replacing it?") != QMessageBox.Yes:
                return
            if files is None:
                files = pick_media(self, "Add files")
            self.add_to_playlist(name, files)
            return
        if files is None:
            picked = pick_media(self, f"Choose files for “{name}”")
            files = picked
        self.store.data["playlists"][name] = list(files or [])
        self.store.save("playlists")
        self.refresh_playlists()
        self.win.toast(f"Playlist “{name}” created")

    def add_to_playlist(self, name, files):
        target = self.store.data["playlists"].setdefault(name, [])
        def identity(path):
            return path if is_url(path) else os.path.normcase(os.path.abspath(path))
        seen = {identity(path) for path in target}
        fresh = []
        for path in files:
            key = identity(path)
            if key not in seen:
                fresh.append(path)
                seen.add(key)
        added = len(fresh)
        # new episodes join the others from their folder in name order (#57)
        target[:] = merge_in_name_order(target, fresh)
        self.store.save("playlists")
        self.refresh_playlists()
        self.win.toast(f"Added {added} item{'s' if added != 1 else ''} to “{name}”")

    def save_to_playlist(self, files, suggested_name=""):
        """Save a folder/queue to a new playlist or append to an existing one."""
        if not files:
            self.win.toast("No playable files to add")
            return
        names = sorted(self.store.data["playlists"], key=str.casefold)
        if not names:
            self.new_playlist(files, suggested_name)
            return
        choices = ["Create a new playlist…"] + [f"Add to: {name}" for name in names]
        choice, ok = QInputDialog.getItem(self, "Save to playlist", "Destination", choices, 0, False)
        if not ok:
            return
        if choice == choices[0]:
            self.new_playlist(files, suggested_name)
        else:
            self.add_to_playlist(names[choices.index(choice) - 1], files)

    def _pl_menu(self, pos):
        it = self.pl_list.itemAt(pos)
        if not it or not it.data(ROLE_PATH):
            return
        name = it.data(ROLE_PATH)
        m = QMenu(self)
        m.addAction("Play", lambda: self.win.play_playlist(name))
        m.addAction("Add to queue", lambda: self.win.enqueue(self.store.data["playlists"][name]))
        pinned = self.is_pinned("playlists", name)
        m.addAction(icon("pin", theme.TEXT, 16), "Unpin" if pinned else "Pin to top",
                    lambda: self.toggle_item_pin("playlists", name))
        m.addAction("Add files…", lambda: self._pl_add_files(name))
        if len(self.store.data["playlists"].get(name, [])) > 1:
            m.addAction(icon("sort", theme.TEXT, 16), "Sort by name", lambda: self._pl_sort(name))
        m.addAction("Rename…", lambda: self._pl_rename(name))
        m.addAction("Export as .m3u…", lambda: self._pl_export(name))
        m.addSeparator()
        m.addAction("Delete", lambda: self._pl_delete(name))
        m.exec(self.pl_list.mapToGlobal(pos))

    def _pl_sort(self, name):
        """Put a playlist in name order (#57)."""
        items = self.store.data["playlists"].get(name, [])
        items.sort(key=sort_key_by_name)
        self.store.save("playlists")
        self.refresh_playlists()
        # if this playlist is what's queued, sort the queue too: that's where the order shows (#58)
        queued = sorted(os.path.normcase(norm(q["path"])) for q in self.win.queue)
        if queued and queued == sorted(os.path.normcase(norm(p)) for p in items):
            self.win.sort_queue_by_name()
        self.win.toast(f"“{name}” sorted by name")

    def _pl_add_files(self, name):
        picked = pick_media(self, "Add files")
        if picked:
            self.add_to_playlist(name, picked)
            self.refresh_playlists()

    def _pl_rename(self, name):
        new, ok = QInputDialog.getText(self, "Rename playlist", "Name", text=name)
        new = new.strip()
        if not ok or not new or new == name:
            return
        pls = self.store.data["playlists"]
        if new in pls:
            QMessageBox.warning(self, "Rename playlist", f"There's already a playlist called “{new}”.")
            return
        # rebuild in the same order, so a renamed playlist keeps its place by age (#37)
        self.store.data["playlists"] = {(new if k == name else k): v for k, v in pls.items()}
        self._rename_pin("playlists", name, new)
        self.store.save("playlists")
        self.refresh_playlists()

    def _pl_delete(self, name):
        if QMessageBox.question(self, "Delete playlist", f"Delete “{name}”? Your files stay where they are.") == QMessageBox.Yes:
            self.store.data["playlists"].pop(name, None)
            self._drop_pin("playlists", name)
            self.store.save("playlists")
            self.refresh_playlists()

    def _pl_export(self, name):
        path, _ = QFileDialog.getSaveFileName(self, "Export playlist", f"{name}.m3u", "M3U playlist (*.m3u)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write("#EXTM3U\n")
                for p in self.store.data["playlists"][name]:
                    f.write(f"#EXTINF:-1,{display_name(p)}\n{p}\n")

    # ---------------------------------------------------------------- streams
    # A saved stream is {"name", "url"}. A channel list (#44) also has "channels": [{"name", "url"}],
    # and its "url" is the file it came from, or a made-up "pylon-list:" key for a saved queue.
    # A saved link to an online list gets "count" once it has been opened.
    def _build_streams(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 0, 8, 4)
        row = QHBoxLayout()
        row.setSpacing(6)
        add = QPushButton("Open a stream…")
        add.setIcon(icon("plus", theme.TEXT, 14))
        add.setToolTip("Open a network stream, and save it here if you like")
        add.clicked.connect(lambda: self.win.open_stream_dialog())
        row.addWidget(add, 1)
        imp = QPushButton("Import list…")
        imp.setIcon(icon("playlist", theme.TEXT, 14))
        imp.setToolTip("Save an .m3u channel list here. You can also drop .m3u files on this list")
        imp.clicked.connect(self._import_dialog)
        row.addWidget(imp, 1)
        lay.addLayout(row)
        self.st_search = QLineEdit()
        self.st_search.setPlaceholderText("Search streams")
        self.st_search.textChanged.connect(lambda _: self.refresh_streams())
        lay.addWidget(self.st_search)
        self._sort_controls(lay, "streams", self.refresh_streams)
        self.st_list = ChannelListDrop()
        self.st_list.setIconSize(QSize(18, 18))
        self.st_list.itemDoubleClicked.connect(
            lambda it: self.win.play_saved_stream(it.data(ROLE_PATH)) if it.data(ROLE_PATH) else None)
        self.st_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.st_list.customContextMenuRequested.connect(self._st_menu)
        self.st_list.lists_dropped.connect(lambda paths: [self.import_channel_list(p) for p in paths])
        lay.addWidget(self.st_list, 1)
        self.stack.addWidget(w)

    def stream_entry(self, url):
        return next((s for s in self.store.data["streams"] if s["url"] == url), None)

    @staticmethod
    def channel_count(s):
        return len(s["channels"]) if s.get("channels") else s.get("count", 0)

    def refresh_streams(self):
        self.st_list.clear()
        q = self.st_search.text().strip().casefold()
        # new streams are saved at the top of the list, so it is newest first already (#44)
        items = [s for s in self._ordered(self.store.data["streams"], "streams", lambda x: x["name"], newest_first=True,
                                          played=lambda x: self.last_played_of([x["url"]] + [c["url"] for c in x.get("channels", [])]))
                 if q in (s["name"] + " " + s["url"]).casefold()]
        first, rest = self.with_pins("streams", items, lambda x: x["url"])

        def add(s, pinned):
            n = self.channel_count(s)
            is_list = bool(s.get("channels")) or n > 1
            it = QListWidgetItem(icon("pin" if pinned else ("playlist" if is_list else "stream"), theme.accent(), 18),
                                 f"{s['name']}   ({n})" if n > 1 else s["name"])
            it.setData(ROLE_PATH, s["url"])
            it.setToolTip(f"{n} channels" + (f"\n{s['url']}" if is_url(s["url"]) or os.path.isabs(s["url"]) else "")
                          if s.get("channels") else s["url"])
            self.st_list.addItem(it)

        self._fill_with_pins(self.st_list, first, rest, "Streams", add)
        self.streams_count.setText(f"{len(items)} streams")
        if not self.store.data["streams"]:
            it = QListWidgetItem("Saved streams and channel lists appear here. Drop an .m3u file to add one")
            it.setFlags(Qt.NoItemFlags)
            self.st_list.addItem(it)

    def _st_menu(self, pos):
        it = self.st_list.itemAt(pos)
        if not it or not it.data(ROLE_PATH):
            return
        url = it.data(ROLE_PATH)
        s = self.stream_entry(url)
        if not s:
            return
        m = QMenu(self)
        m.addAction(icon("play", theme.TEXT, 16), "Play", lambda: self.win.play_saved_stream(url))
        if s.get("channels"):
            m.addAction(icon("queue", theme.TEXT, 16), "Add to queue",
                        lambda: self.win.enqueue_items([{"path": c["url"], "title": c["name"]} for c in s["channels"]]))
        pinned = self.is_pinned("streams", url)
        m.addAction(icon("pin", theme.TEXT, 16), "Unpin" if pinned else "Pin to top",
                    lambda: self.toggle_item_pin("streams", url))
        m.addAction("Rename…", lambda: self._st_rename(url, s["name"]))
        if s.get("channels"):
            add = m.addMenu(icon("plus", theme.TEXT, 16), "Add more streams")
            add.addAction("A stream link…", lambda: self._list_add_link(url))
            add.addAction("From an .m3u file…", lambda: self._list_add_file(url))
            m.addAction("Export as .m3u…", lambda: self._st_export(url))
        if is_url(url):
            m.addAction("Copy link", lambda: self._copy_link(url))
        m.addSeparator()
        m.addAction(icon("trash", theme.TEXT, 16), "Remove", lambda: self._st_remove(url))
        m.exec(self.st_list.mapToGlobal(pos))

    def _st_rename(self, url, name):
        """Rename a saved stream (#44). The link stays the same."""
        new, ok = QInputDialog.getText(self, "Rename stream", "Name", text=name)
        new = new.strip()
        if not ok or not new or new == name:
            return
        for s in self.store.data["streams"]:
            if s["url"] == url:
                s["name"] = new
        for q in self.win.queue:                 # the queue shows the new name too
            if q.get("path") == url:
                q["title"] = new
        self.store.save("streams")
        self.refresh_streams()
        self.refresh_queue()

    def _copy_link(self, url):
        QApplication.clipboard().setText(url)
        self.win.toast("Link copied")

    def _st_remove(self, url):
        self.store.data["streams"] = [s for s in self.store.data["streams"] if s["url"] != url]
        self._drop_pin("streams", url)
        self.store.save("streams")
        self.refresh_streams()

    # ---- channel lists (#44)
    @staticmethod
    def read_channel_file(path):
        """[{name, url}] from an .m3u file, with paths made absolute. Empty if it isn't a list."""
        try:
            with open(path, encoding="utf-8-sig", errors="replace") as f:
                found = parse_m3u(f.read(8_000_000)) or []
        except OSError:
            return []
        base = os.path.dirname(path)
        out = []
        for n, u in found:
            if not is_url(u) and not os.path.isabs(u):
                u = os.path.normpath(os.path.join(base, u))
            out.append({"name": n, "url": u})
        return out

    def _import_dialog(self):
        picked, _ = QFileDialog.getOpenFileNames(self, "Import a channel list", "",
                                                 "Channel lists (*.m3u *.m3u8);;All files (*)")
        for p in picked:
            self.import_channel_list(p)

    def import_channel_list(self, path, name=""):
        """Save the channels in an .m3u file to Streams as one list. Importing the same file again updates it."""
        path = os.path.normpath(os.path.abspath(path))
        channels = self.read_channel_file(path)
        if not channels:
            self.win.toast(f"No streams found in “{os.path.basename(path)}”")
            return None
        s = self.stream_entry(path)
        if s:
            s["channels"] = channels
            msg = f"Updated “{s['name']}”: {len(channels)} channels"
        else:
            s = {"name": name or os.path.splitext(os.path.basename(path))[0], "url": path, "channels": channels}
            self.store.data["streams"].insert(0, s)
            msg = f"Saved “{s['name']}” to Streams: {len(channels)} channels"
        self.store.save("streams")
        self.refresh_streams()
        self.win.home.refresh()
        self.win.toast(msg)
        return s

    def save_channel_list(self, items, name):
        """Save queue items ({path, title}) as a channel list in Streams."""
        import time as _t
        s = {"name": name, "url": f"pylon-list:{int(_t.time() * 1000)}",
             "channels": [{"name": x.get("title") or display_name(x["path"]), "url": x["path"]} for x in items]}
        self.store.data["streams"].insert(0, s)
        self.store.save("streams")
        self.refresh_streams()
        self.win.home.refresh()
        self.win.toast(f"Saved “{name}” to Streams: {len(items)} channels")
        return s

    def _add_channels(self, url, new):
        s = self.stream_entry(url)
        if not s or not new:
            return 0
        have = {c["url"] for c in s["channels"]}
        added = [c for c in new if c["url"] not in have]
        s["channels"].extend(added)
        self.store.save("streams")
        self.refresh_streams()
        self.win.toast(f"Added {len(added)} stream{'s' if len(added) != 1 else ''} to “{s['name']}”")
        return len(added)

    def _list_add_link(self, url):
        link, ok = QInputDialog.getText(self, "Add a stream", "Stream link")
        link = link.strip()
        if not ok or not link:
            return
        name, ok = QInputDialog.getText(self, "Add a stream", "Name", text=display_name(link))
        if ok:
            self._add_channels(url, [{"name": name.strip() or display_name(link), "url": link}])

    def _list_add_file(self, url):
        p, _ = QFileDialog.getOpenFileName(self, "Add streams from a list", "", "Channel lists (*.m3u *.m3u8)")
        if p:
            self._add_channels(url, self.read_channel_file(p))

    def _st_export(self, url):
        s = self.stream_entry(url)
        if not s or not s.get("channels"):
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export channel list", f"{s['name']}.m3u", "M3U playlist (*.m3u)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write("#EXTM3U\n")
                for c in s["channels"]:
                    f.write(f"#EXTINF:-1,{c['name']}\n{c['url']}\n")
            self.win.toast("Channel list exported")
