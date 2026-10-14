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
import random
import subprocess
import sys
import time

from PySide6.QtCore import QMimeData, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDrag, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox,
                               QPushButton, QSplitter, QStackedWidget, QStyle, QStyledItemDelegate,
                               QVBoxLayout, QWidget)

from . import theme
from .icons import icon
from .util import (display_name, fmt_time, is_audio, is_media, is_url, list_media, natural_key,
                   to_path)
from .widgets import IconButton

ROLE_PATH = Qt.UserRole
ROLE_KIND = Qt.UserRole + 1   # "folder" | "file" | "root"


class MediaList(QListWidget):
    """List whose file items can be dragged out (to the queue) as file URLs."""

    def __init__(self):
        super().__init__()
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setIconSize(QSize(18, 18))
        self.setUniformItemSizes(True)

    def mimeData(self, items):
        md = QMimeData()
        urls = []
        for it in items:
            p = it.data(ROLE_PATH)
            if p and it.data(ROLE_KIND) == "file":
                urls.append(QUrl(p) if is_url(p) else QUrl.fromLocalFile(p))
        md.setUrls(urls)
        return md

    def mimeTypes(self):
        return ["text/uri-list"]


class TwoLineDelegate(QStyledItemDelegate):
    """Rows written as "title<TAB>right\nsubtitle": title in normal text, the
    right part (e.g. a song's length) right-aligned, the subtitle smaller and grey."""

    def paint(self, p, opt, idx):
        self.initStyleOption(opt, idx)
        style = opt.widget.style() if opt.widget else None
        if style:
            style.drawPrimitive(QStyle.PE_PanelItemViewItem, opt, p, opt.widget)
        r = opt.rect.adjusted(6, 0, -8, 0)
        ic = opt.icon
        isz = opt.decorationSize
        if not ic.isNull():
            ic.paint(p, r.left(), r.top() + (r.height() - isz.height()) // 2, isz.width(), isz.height())
            r.setLeft(r.left() + isz.width() + 10)
        text = idx.data(Qt.DisplayRole) or ""
        line1, _, line2 = text.partition("\n")
        left, _, right = line1.partition("\t")
        f1 = QFont(opt.font)
        fg = idx.data(Qt.ForegroundRole)
        c1 = fg.color() if fg is not None else QColor(theme.TEXT)
        if not (idx.flags() & Qt.ItemIsEnabled):
            c1 = QColor(theme.MUTED)
        f2 = QFont(opt.font)
        f2.setPointSizeF(max(7.5, f2.pointSizeF() - 0.8))
        fm1 = p.fontMetrics()
        h1 = fm1.height()
        h2 = int(h1 * 0.9) if line2 else 0
        top = r.top() + (r.height() - h1 - h2) // 2
        p.save()
        p.setFont(f1)
        rw = fm1.horizontalAdvance(right) + 8 if right else 0
        p.setPen(c1)
        p.drawText(r.left(), top, r.width() - rw, h1, Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(left, Qt.ElideRight, r.width() - rw))
        if right:
            p.setPen(QColor(theme.MUTED))
            p.drawText(r.left(), top, r.width(), h1, Qt.AlignRight | Qt.AlignVCenter, right)
        if line2:
            p.setFont(f2)
            p.setPen(QColor(theme.MUTED))
            p.drawText(r.left(), top + h1, r.width(), h2, Qt.AlignLeft | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(line2, Qt.ElideRight, r.width()))
        p.restore()

    def sizeHint(self, opt, idx):
        self.initStyleOption(opt, idx)
        text = idx.data(Qt.DisplayRole) or ""
        h1 = opt.fontMetrics.height()
        lines = h1 + (int(h1 * 0.9) if "\n" in text else 0)
        h = max(lines, opt.decorationSize.height() if not opt.icon.isNull() else 0) + 10
        return QSize(10, h)


class QueueList(QListWidget):
    """Reorderable queue that also accepts drops from the library and Explorer."""
    dropped_urls = Signal(list, int)   # paths, row
    reordered = Signal(list)           # new order of paths

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setIconSize(QSize(16, 16))

    def dragEnterEvent(self, e):
        if e.source() is self or e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if e.source() is self:
            super().dragMoveEvent(e)
        elif e.mimeData().hasUrls():
            e.setDropAction(Qt.CopyAction)
            e.accept()

    def dropEvent(self, e):
        if e.source() is self:
            super().dropEvent(e)
            self.reordered.emit([self.item(i).data(ROLE_PATH) for i in range(self.count())])
            return
        if e.mimeData().hasUrls():
            row = self.indexAt(e.position().toPoint()).row()
            paths = []
            for u in e.mimeData().urls():
                p = u.toLocalFile() if u.isLocalFile() else u.toString()
                if u.isLocalFile() and os.path.isdir(p):
                    paths.extend(list_media(p))
                elif p:
                    paths.append(p)
            e.setDropAction(Qt.CopyAction)
            e.accept()
            self.dropped_urls.emit(paths, row if row >= 0 else self.count())


class LibraryPanel(QWidget):
    WIDTH = 320

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
        self.sort_mode = "name"

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
            b.clicked.connect(lambda _=False, k=key: self.show_section(k))
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
        for ic, tip, fn in (("plus", "Add files to the queue", self._add_files_to_queue),
                            ("shuffle", "Shuffle", self._shuffle),
                            ("save", "Save queue as a playlist", self._save_queue_as_playlist),
                            ("trash", "Clear queue", lambda: win.set_queue([], -1))):
            b = IconButton(ic, tip, size=16)
            b.clicked.connect(fn)
            qh.addWidget(b)
        ql.addLayout(qh)
        self.queue = QueueList()
        self.queue.itemDoubleClicked.connect(lambda it: win.play_queue_index(self.queue.row(it)))
        self.queue.dropped_urls.connect(self._queue_drop)
        self.queue.reordered.connect(self._queue_reordered)
        self.queue.setContextMenuPolicy(Qt.CustomContextMenu)
        self.queue.customContextMenuRequested.connect(self._queue_menu)
        ql.addWidget(self.queue)
        hint = QLabel("Drag files here from the library or from your folders")
        hint.setObjectName("Muted")
        hint.setStyleSheet(f"color: {theme.FAINT}; font-size: 11px;")
        ql.addWidget(hint)
        split.addWidget(qw)
        split.setSizes([460, 260])

        self.show_section("library")
        self.store.changed.connect(self._store_changed)

    # ================================================================ sections
    def show_section(self, key):
        idx = {"library": 0, "recent": 1, "playlists": 2, "streams": 3, "music": 4}[key]
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
        self.sort_actions["name"].setChecked(True)
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
        for k, a in self.sort_actions.items():
            a.setChecked(k == key)
        self.refresh_library()

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
            folders = self.store.data["library_folders"]
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
        it = QListWidgetItem(icon("pin" if pinned else "folder", theme.accent(), 18),
                             os.path.basename(path.rstrip("\\/")) or path)
        it.setData(ROLE_PATH, path)
        it.setData(ROLE_KIND, "folder")
        it.setToolTip(path)
        self.lib_list.addItem(it)

    def _lib_activate(self, it):
        kind, path = it.data(ROLE_KIND), it.data(ROLE_PATH)
        if kind == "folder":
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
            m.addAction(icon("play", theme.TEXT, 16), "Play folder", lambda: self.win.play_folder(path))
            m.addAction(icon("queue", theme.TEXT, 16), "Add folder to queue", lambda: self.win.enqueue(list_media(path)))
            pinned = path in self.store.data["pinned"]
            m.addAction(icon("pin", theme.TEXT, 16), "Unpin" if pinned else "Pin to top", lambda: self.toggle_pin(path))
            m.addAction(icon("subtitles", theme.TEXT, 16), "Add subtitles for this folder…",
                        lambda: self.win.open_subtitle_dialog(scope="folder", folder=path))
            m.addAction("Show in Explorer", lambda: reveal(path))
            if path in self.store.data["library_folders"]:
                m.addSeparator()
                m.addAction(icon("trash", theme.TEXT, 16), "Remove from library", lambda: self.remove_library_folder(path))
        m.exec(self.lib_list.mapToGlobal(pos))

    def add_library_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Add a folder to the library")
        if d:
            d = os.path.normpath(d)
            if d not in self.store.data["library_folders"]:
                self.store.data["library_folders"].append(d)
                self.store.save("library")
                self._music_stale = True
            self.open_folder(None)
            self.win.home.refresh()

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
        lay.addWidget(self.recent_list, 1)
        clear = QPushButton("Clear history")
        clear.clicked.connect(self._clear_history)
        lay.addWidget(clear)
        self.stack.addWidget(w)

    def refresh_recent(self):
        self.recent_list.clear()
        for r in self.store.data["recent"]:
            p = r["path"]
            it = QListWidgetItem(icon("stream" if is_url(p) else ("music" if is_audio(p) else "video"),
                                      theme.MUTED, 18), display_name(p))
            it.setToolTip(f"{p}\n{time.strftime('%d %b, %H:%M', time.localtime(r['t']))}")
            it.setData(ROLE_PATH, p)
            it.setData(ROLE_KIND, "file")
            self.recent_list.addItem(it)

    def _clear_history(self):
        if QMessageBox.question(self, "Clear history", "Forget recent files and where you stopped in each?") == QMessageBox.Yes:
            self.store.clear_history()
            self.refresh_recent()
            self.win.home.refresh()

    # ---------------------------------------------------------------- playlists
    def _build_playlists(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 0, 8, 4)
        new = QPushButton("New playlist…")
        new.setIcon(icon("plus", theme.TEXT, 14))
        new.clicked.connect(lambda: self.new_playlist())
        lay.addWidget(new)
        self.pl_list = QListWidget()
        self.pl_list.setIconSize(QSize(18, 18))
        self.pl_list.itemDoubleClicked.connect(lambda it: self.win.play_playlist(it.data(ROLE_PATH)))
        self.pl_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.pl_list.customContextMenuRequested.connect(self._pl_menu)
        lay.addWidget(self.pl_list, 1)
        self.stack.addWidget(w)

    def refresh_playlists(self):
        self.pl_list.clear()
        for name, items in sorted(self.store.data["playlists"].items()):
            it = QListWidgetItem(icon("playlist", theme.accent(), 18), f"{name}   ({len(items)})")
            it.setData(ROLE_PATH, name)
            self.pl_list.addItem(it)
        if not self.store.data["playlists"]:
            it = QListWidgetItem("No playlists yet")
            it.setFlags(Qt.NoItemFlags)
            self.pl_list.addItem(it)

    def new_playlist(self, files=None):
        name, ok = QInputDialog.getText(self, "New playlist", "Name")
        if not ok or not name.strip():
            return
        name = name.strip()
        if files is None:
            picked, _ = QFileDialog.getOpenFileNames(self, f"Choose files for “{name}”", "", media_filter())
            files = picked
        self.store.data["playlists"][name] = list(files or [])
        self.store.save("playlists")
        self.refresh_playlists()
        self.win.toast(f"Playlist “{name}” created")

    def add_to_playlist(self, name, files):
        self.store.data["playlists"].setdefault(name, []).extend(files)
        self.store.save("playlists")
        self.win.toast(f"Added to “{name}”")

    def _pl_menu(self, pos):
        it = self.pl_list.itemAt(pos)
        if not it or not it.data(ROLE_PATH):
            return
        name = it.data(ROLE_PATH)
        m = QMenu(self)
        m.addAction("Play", lambda: self.win.play_playlist(name))
        m.addAction("Add to queue", lambda: self.win.enqueue(self.store.data["playlists"][name]))
        m.addAction("Add files…", lambda: self._pl_add_files(name))
        m.addAction("Rename…", lambda: self._pl_rename(name))
        m.addAction("Export as .m3u…", lambda: self._pl_export(name))
        m.addSeparator()
        m.addAction("Delete", lambda: self._pl_delete(name))
        m.exec(self.pl_list.mapToGlobal(pos))

    def _pl_add_files(self, name):
        picked, _ = QFileDialog.getOpenFileNames(self, "Add files", "", media_filter())
        if picked:
            self.add_to_playlist(name, picked)
            self.refresh_playlists()

    def _pl_rename(self, name):
        new, ok = QInputDialog.getText(self, "Rename playlist", "Name", text=name)
        if ok and new.strip() and new != name:
            self.store.data["playlists"][new.strip()] = self.store.data["playlists"].pop(name)
            self.store.save("playlists")
            self.refresh_playlists()

    def _pl_delete(self, name):
        if QMessageBox.question(self, "Delete playlist", f"Delete “{name}”? Your files stay where they are.") == QMessageBox.Yes:
            self.store.data["playlists"].pop(name, None)
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
    def _build_streams(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 0, 8, 4)
        add = QPushButton("Open a network stream…")
        add.setIcon(icon("plus", theme.TEXT, 14))
        add.clicked.connect(lambda: self.win.open_stream_dialog())
        lay.addWidget(add)
        self.st_list = QListWidget()
        self.st_list.setIconSize(QSize(18, 18))
        self.st_list.itemDoubleClicked.connect(lambda it: self.win.open_stream(it.data(ROLE_PATH), it.text()))
        self.st_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.st_list.customContextMenuRequested.connect(self._st_menu)
        lay.addWidget(self.st_list, 1)
        self.stack.addWidget(w)

    def refresh_streams(self):
        self.st_list.clear()
        for s in self.store.data["streams"]:
            it = QListWidgetItem(icon("stream", theme.accent(), 18), s["name"])
            it.setData(ROLE_PATH, s["url"])
            it.setToolTip(s["url"])
            self.st_list.addItem(it)
        if not self.store.data["streams"]:
            it = QListWidgetItem("Saved streams and channel lists appear here")
            it.setFlags(Qt.NoItemFlags)
            self.st_list.addItem(it)

    def _st_menu(self, pos):
        it = self.st_list.itemAt(pos)
        if not it or not it.data(ROLE_PATH):
            return
        url = it.data(ROLE_PATH)
        m = QMenu(self)
        m.addAction("Play", lambda: self.win.open_stream(url, it.text()))
        m.addAction("Remove", lambda: self._st_remove(url))
        m.exec(self.st_list.mapToGlobal(pos))

    def _st_remove(self, url):
        self.store.data["streams"] = [s for s in self.store.data["streams"] if s["url"] != url]
        self.store.save("streams")
        self.refresh_streams()


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
        tools.addWidget(self.music_back)
        tools.addWidget(self.music_search, 1)
        tools.addWidget(rescan)
        lay.addLayout(tools)

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
        return next((a for a in self.music.albums() if a["key"] == key), None)

    def refresh_music(self):
        lst = self.music_list
        lst.clear()
        m = self.music
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
            for p in a["tracks"]:
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
            for a in albums:
                if q and q not in a["album"].lower():
                    continue
                self._music_item(f"{a['album']}\n{a['year'] + '  ·  ' if a['year'] else ''}{len(a['tracks'])} songs",
                                 "album", a["key"], self._cover(a["art"], 44))
            return

        self.music_crumb.setText("")
        if self.music_mode == "artists":
            lst.setIconSize(QSize(44, 44))
            for name, albums in m.artists():
                if q and q not in name.lower():
                    continue
                n = sum(len(a["tracks"]) for a in albums)
                art = next((a["art"] for a in albums if a["art"]), "")
                self._music_item(f"{name}\n{len(albums)} album{'s' if len(albums) != 1 else ''}  ·  {n} song{'s' if n != 1 else ''}",
                                 "artist", name, self._cover(art, 44))
        elif self.music_mode == "albums":
            lst.setIconSize(QSize(44, 44))
            for a in m.albums():
                if q and q not in f"{a['album']} {a['artist']}".lower():
                    continue
                self._music_item(f"{a['album']}\n{a['artist']}{'  ·  ' + a['year'] if a['year'] else ''}",
                                 "album", a["key"], self._cover(a["art"], 44))
        else:
            lst.setIconSize(QSize(36, 36))
            for p in m.all_songs():
                if q and q not in song_text(p).lower():
                    continue
                add_song(p)

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
        pm = m.addMenu(icon("playlist", theme.TEXT, 16), "Add to playlist")
        for name in sorted(self.store.data["playlists"]):
            pm.addAction(name, lambda n=name: self.add_to_playlist(n, paths))
        pm.addSeparator()
        pm.addAction("New playlist…", lambda: self.new_playlist(paths))
        if kind == "file":
            m.addSeparator()
            m.addAction("Show in Explorer", lambda: reveal(val))
        m.exec(self.music_list.mapToGlobal(pos))

    # ================================================================ queue
    def refresh_queue(self):
        self.queue.clear()
        for i, item in enumerate(self.win.queue):
            p = item["path"]
            playing = i == self.win.qindex
            it = QListWidgetItem(item.get("title") or display_name(p))
            it.setIcon(icon("play" if playing else ("stream" if is_url(p) else "drag"),
                            theme.accent() if playing else theme.FAINT, 16))
            if playing:
                f = it.font()
                f.setBold(True)
                it.setFont(f)
            it.setData(ROLE_PATH, p)
            it.setToolTip(p)
            self.queue.addItem(it)
        n = len(self.win.queue)
        self.queue_count.setText(f"{n} item{'s' if n != 1 else ''}" if n else "")
        if 0 <= self.win.qindex < self.queue.count():
            self.queue.scrollToItem(self.queue.item(self.win.qindex))

    def _queue_drop(self, paths, row):
        self.win.insert_into_queue(paths, row)

    def _queue_reordered(self, order):
        self.win.reorder_queue(order)

    def _queue_menu(self, pos):
        it = self.queue.itemAt(pos)
        m = QMenu(self)
        if it:
            rows = sorted({self.queue.row(i) for i in self.queue.selectedItems()} | {self.queue.row(it)})
            m.addAction(icon("play", theme.TEXT, 16), "Play", lambda: self.win.play_queue_index(self.queue.row(it)))
            m.addAction(icon("trash", theme.TEXT, 16), "Remove from queue", lambda: self.win.remove_from_queue(rows))
            p = it.data(ROLE_PATH)
            if not is_url(p):
                m.addAction("Show in Explorer", lambda: reveal(p))
            m.addSeparator()
        m.addAction("Add files…", self._add_files_to_queue)
        m.addAction("Clear queue", lambda: self.win.set_queue([], -1))
        m.exec(self.queue.mapToGlobal(pos))

    def _add_files_to_queue(self):
        picked, _ = QFileDialog.getOpenFileNames(self, "Add to queue", "", media_filter())
        if picked:
            self.win.enqueue(picked)

    def _shuffle(self):
        q = self.win.queue
        if len(q) < 2:
            return
        cur = q[self.win.qindex] if 0 <= self.win.qindex < len(q) else None
        rest = [x for x in q if x is not cur]
        random.shuffle(rest)
        new = ([cur] if cur else []) + rest
        self.win.set_queue(new, 0 if cur else -1, keep_playing=True)
        self.win.toast("Queue shuffled")

    def _save_queue_as_playlist(self):
        if not self.win.queue:
            return
        self.new_playlist([x["path"] for x in self.win.queue])


def win_call(fn):
    fn()


def _mtime(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0


def reveal(path):
    path = to_path(path)
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)])


def media_filter():
    from .util import AUDIO_EXTS, PLAYLIST_EXTS, VIDEO_EXTS
    v = " ".join(f"*{e}" for e in sorted(VIDEO_EXTS))
    a = " ".join(f"*{e}" for e in sorted(AUDIO_EXTS))
    p = " ".join(f"*{e}" for e in sorted(PLAYLIST_EXTS))
    return f"Media ({v} {a} {p});;Video ({v});;Audio ({a});;Playlists ({p});;All files (*)"
