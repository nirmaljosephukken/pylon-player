"""Dialogs: add subtitles (file / folder / queue with auto-matching), network
stream, keyboard shortcuts, preferences, and the first-run welcome."""
import os
import sys

from PySide6.QtCore import QSize, Qt, QUrl, QTimer
from PySide6.QtGui import QColor, QDesktopServices, QKeySequence, QIcon, QPixmap, QPainter
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QFrame,
                               QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout,
                               QHeaderView, QKeySequenceEdit, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QRadioButton, QSpinBox,
                               QScrollArea, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from . import theme
from .colour_dialog import choose_colour
from .icons import icon, pixmap
from .store import DEFAULT_SHORTCUTS, HOME_SECTIONS, QUEUE_MODES
from .util import MATCH_LEVELS, SUB_EXTS, auto_match_folder, display_name, is_url, list_media, subtitle_query
from .widgets import subtitle_search_menu

SUB_FILTER = "Subtitles (" + " ".join(f"*{e}" for e in sorted(SUB_EXTS)) + ");;All files (*)"


def info_label(text, tip):
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    lay.addWidget(QLabel(text))
    i = QLabel()
    i.setPixmap(pixmap("info", theme.MUTED, 14))
    i.setToolTip(tip)
    i.setCursor(Qt.WhatsThisCursor)
    lay.addWidget(i)
    lay.addStretch(1)
    return w


# ====================================================================== subtitles

class SubtitleDialog(QDialog):
    """Add subtitles to this file, a whole folder, or everything in the queue.
    For folders and queues, files are matched by name or episode number
    (S01E02, 1x02, E02) and you can fix any pairing before saving. Pairings
    are remembered for next time."""

    def __init__(self, win, scope="file", folder=None):
        super().__init__(win)
        self.win = win
        self.store = win.store
        self.setWindowTitle("Add subtitles")
        self.resize(760, 540)
        self.folder = folder or win.current_folder()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)
        t = QLabel("Add subtitles")
        t.setObjectName("H1")
        lay.addWidget(t)

        lay.addWidget(QLabel("Add them to"))
        srow = QHBoxLayout()
        self.scope = QButtonGroup(self)
        self.r_file = QRadioButton("This file")
        self.r_folder = QRadioButton("This folder")
        self.r_queue = QRadioButton("Everything in the queue")
        for i, r in enumerate((self.r_file, self.r_folder, self.r_queue)):
            self.scope.addButton(r, i)
            srow.addWidget(r)
        srow.addStretch(1)
        lay.addLayout(srow)
        self.r_file.setEnabled(bool(win.engine.current) and not is_url(win.engine.current or ""))
        self.r_folder.setEnabled(bool(self.folder))
        self.r_queue.setEnabled(bool(win.queue))
        {"file": self.r_file, "folder": self.r_folder, "queue": self.r_queue}.get(scope, self.r_file).setChecked(True)
        if not self.scope.checkedButton() or not self.scope.checkedButton().isEnabled():
            for r in (self.r_folder, self.r_queue, self.r_file):
                if r.isEnabled():
                    r.setChecked(True)
                    break

        lay.addWidget(QLabel("From"))
        frow = QHBoxLayout()
        pick_files = QPushButton("Files on this computer…")
        pick_files.setIcon(icon("file", theme.TEXT, 16))
        pick_files.clicked.connect(self.pick_files)
        pick_dir = QPushButton("A folder of subtitles…")
        pick_dir.setIcon(icon("folder", theme.TEXT, 16))
        pick_dir.clicked.connect(self.pick_dir)
        online = QPushButton("Search online")
        online.setIcon(icon("globe", theme.TEXT, 16))
        online.setToolTip("Opens a subtitle site in your browser. Download, unzip, then choose the files here.")
        online.setMenu(subtitle_search_menu(online, self.store, self.search_query))
        frow.addWidget(pick_files)
        frow.addWidget(pick_dir)
        frow.addWidget(online)
        frow.addStretch(1)
        lay.addLayout(frow)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Video", "Subtitle"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        self.table.setSelectionMode(QTableWidget.NoSelection)
        lay.addWidget(self.table, 1)
        self.note = QLabel("Choose subtitle files and they'll be matched to each video automatically. Fix any row by hand.")
        self.note.setObjectName("Muted")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)

        bb = QDialogButtonBox()
        self.ok = bb.addButton("Save and use", QDialogButtonBox.AcceptRole)
        self.ok.setObjectName("Primary")
        bb.addButton(QDialogButtonBox.Cancel)
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.subs: list[str] = []
        self.scope.idClicked.connect(lambda _: self.rematch())
        self.rematch()

    def videos(self) -> list[str]:
        sid = self.scope.checkedId()
        if sid == 0:
            return [self.win.engine.current] if self.win.engine.current else []
        if sid == 1:
            return list_media(self.folder) if self.folder else []
        return [q["path"] for q in self.win.queue if not is_url(q["path"])]

    def pick_files(self):
        start = self.folder or ""
        files, _ = QFileDialog.getOpenFileNames(self, "Choose subtitle files", start, SUB_FILTER)
        if files:
            self.subs = files
            self.rematch()

    def pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Choose a folder of subtitles", self.folder or "")
        if d:
            found = []
            for root, _, files in os.walk(d):
                for f in files:
                    if os.path.splitext(f)[1].lower() in SUB_EXTS - {".txt"}:
                        found.append(os.path.join(root, f))
            self.subs = found
            self.rematch()

    def search_query(self) -> str:
        vids = self.videos()
        if self.scope.checkedId() == 1 and self.folder:
            return subtitle_query(self.folder)      # the folder is usually the show's name
        return subtitle_query(vids[0]) if vids else ""

    def rematch(self):
        vids = self.videos()
        mapping = auto_match_folder(vids, self.subs) if self.subs else {}
        if self.scope.checkedId() == 0 and len(self.subs) == 1 and vids:
            mapping = {vids[0]: self.subs[0]}
        existing = self.store.data["sub_map"]
        self.table.setRowCount(0)
        self.table.setRowCount(len(vids))
        for r, v in enumerate(vids):
            it = QTableWidgetItem(os.path.basename(v))
            it.setToolTip(v)
            it.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(r, 0, it)
            combo = QComboBox()
            combo.addItem("(none)", "")
            for s in self.subs:
                combo.addItem(os.path.basename(s), s)
            cur = mapping.get(v) or existing.get(v)
            if cur and combo.findData(cur) < 0:
                combo.addItem(os.path.basename(cur) + "  (saved)", cur)
            idx = combo.findData(cur or "")
            combo.setCurrentIndex(max(0, idx))
            self.table.setCellWidget(r, 1, combo)
        matched = sum(1 for v in vids if mapping.get(v))
        if self.subs:
            self.note.setText(f"Matched {matched} of {len(vids)} videos automatically. Fix any row by hand, then save.")
        self.ok.setEnabled(bool(vids))

    def save(self):
        sm = self.store.data["sub_map"]
        cur = self.win.engine.current
        applied = 0
        for r in range(self.table.rowCount()):
            v = self.table.item(r, 0).toolTip()
            s = self.table.cellWidget(r, 1).currentData()
            if s:
                sm[v] = s
                applied += 1
                if v == cur:
                    self.win.engine.add_subtitle(s, select=True)
                    self.win.sidebar.load_cues()
            elif v in sm and self.scope.checkedId() != 0:
                pass
        self.store.save("subs")
        self.win.toast(f"Subtitles saved for {applied} file{'s' if applied != 1 else ''}")
        self.accept()


# ====================================================================== streams

class StreamDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.setWindowTitle("Open a network stream")
        self.resize(560, 230)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)
        t = QLabel("Network stream")
        t.setObjectName("H1")
        lay.addWidget(t)
        lay.addWidget(QLabel("Paste a link to a video, a live stream, or a channel list (.m3u)"))
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://…   rtsp://…   or a link to a .m3u channel list")
        lay.addWidget(self.url)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Name (optional)")
        lay.addWidget(self.name)
        self.save = QCheckBox("Save it to Streams in the library")
        self.save.setChecked(True)
        lay.addWidget(self.save)
        bb = QDialogButtonBox()
        ok = bb.addButton("Play", QDialogButtonBox.AcceptRole)
        ok.setObjectName("Primary")
        bb.addButton(QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        from PySide6.QtGui import QGuiApplication
        clip = QGuiApplication.clipboard().text().strip()
        if "://" in clip and " " not in clip:
            self.url.setText(clip)


# ====================================================================== shortcuts

class ShortcutsDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.store = win.store
        self.setWindowTitle("Keyboard shortcuts")
        self.resize(560, 640)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        t = QLabel("Keyboard shortcuts")
        t.setObjectName("H1")
        lay.addWidget(t)
        sub = QLabel("Click a key to change it, then press the new key. Esc inside the box clears it.")
        sub.setObjectName("Muted")
        lay.addWidget(sub)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Search actions")
        self.filter.textChanged.connect(self._filter)
        lay.addWidget(self.filter)
        self.table = QTableWidget(len(DEFAULT_SHORTCUTS), 2)
        self.table.setHorizontalHeaderLabels(["Action", "Key"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 170)
        self.table.verticalHeader().hide()
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.edits = {}
        for r, (action, (label, default)) in enumerate(DEFAULT_SHORTCUTS.items()):
            it = QTableWidgetItem(label)
            it.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(r, 0, it)
            e = QKeySequenceEdit(QKeySequence(self.store.shortcut(action)))
            try:
                e.setMaximumSequenceLength(1)
            except AttributeError:
                pass
            e.setClearButtonEnabled(True) if hasattr(e, "setClearButtonEnabled") else None
            self.table.setCellWidget(r, 1, e)
            self.edits[action] = e
            self.table.setRowHeight(r, 34)
        lay.addWidget(self.table, 1)
        # a key that's already taken says so straight away, with a way to move it here (#56)
        self._prev = {a: self._key(a) for a in self.edits}
        self._last = None
        self.clash = QFrame()
        self.clash.setObjectName("ClashBar")
        self.clash.setStyleSheet(f"#ClashBar {{ background: {theme.SURFACE}; border: 1px solid {theme.accent()};"
                                 f" border-radius: 10px; }}")
        cl = QHBoxLayout(self.clash)
        cl.setContentsMargins(12, 8, 8, 8)
        self.clash_text = QLabel()
        self.clash_text.setWordWrap(True)
        self.clash_text.setStyleSheet(f"color: {theme.TEXT}; background: transparent;")
        cl.addWidget(self.clash_text, 1)
        self.clash_use = QPushButton("Use it here")
        self.clash_use.setObjectName("Primary")
        self.clash_use.clicked.connect(self._use_here)
        self.clash_undo = QPushButton("Undo")
        self.clash_undo.clicked.connect(self._undo)
        cl.addWidget(self.clash_use)
        cl.addWidget(self.clash_undo)
        self.clash.hide()
        lay.addWidget(self.clash)
        for action, e in self.edits.items():
            e.keySequenceChanged.connect(lambda _seq, a=action: self._changed(a))
        bb = QDialogButtonBox()
        reset = bb.addButton("Reset to defaults", QDialogButtonBox.ResetRole)
        reset.clicked.connect(self._reset)
        ok = bb.addButton("Save", QDialogButtonBox.AcceptRole)
        ok.setObjectName("Primary")
        bb.addButton(QDialogButtonBox.Cancel)
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _filter(self, text):
        text = text.lower()
        for r in range(self.table.rowCount()):
            label = self.table.item(r, 0).text().lower()
            key = list(self.edits.values())[r].keySequence().toString().lower()
            self.table.setRowHidden(r, bool(text) and text not in label and text not in key)

    def _reset(self):
        for action, e in self.edits.items():
            e.setKeySequence(QKeySequence(DEFAULT_SHORTCUTS[action][1]))
        self.clash.hide()

    def _key(self, action):
        return self.edits[action].keySequence().toString()

    def _other_with(self, action):
        k = self._key(action)
        return next((b for b in self.edits if b != action and k and self._key(b) == k), None)

    def _changed(self, action):
        other = self._other_with(action)
        if other:
            self._last = action
            self._clash = (action, other)
            self.clash_text.setText(f"“{self._key(action)}” is already used by “{DEFAULT_SHORTCUTS[other][0]}”. "
                                    f"Use it for “{DEFAULT_SHORTCUTS[action][0]}” instead?")
            self.clash.show()
        else:
            self._prev[action] = self._key(action)
            if self.clash.isVisible() and not any(self._other_with(a) for a in self._clash):
                self.clash.hide()

    def _use_here(self):
        action, other = self._clash
        self.edits[other].clear()          # the other action is left without a key
        self._prev[other] = ""
        self._prev[action] = self._key(action)
        self.clash.hide()

    def _undo(self):
        action, _ = self._clash
        self.clash.hide()
        self.edits[action].setKeySequence(QKeySequence(self._prev.get(action, "")))

    def save(self):
        seen = {}
        for action, e in self.edits.items():
            k = e.keySequence().toString()
            if k and k in seen:
                first = seen[k]
                keep = first if self._last == first else action      # the one you just changed keeps it
                drop = action if keep == first else first
                box = QMessageBox(QMessageBox.Warning, "Same key used twice",
                                  f"“{k}” is set for both “{DEFAULT_SHORTCUTS[first][0]}” "
                                  f"and “{DEFAULT_SHORTCUTS[action][0]}”.", parent=self)
                use = box.addButton(f"Use it for “{DEFAULT_SHORTCUTS[keep][0]}”", QMessageBox.AcceptRole)
                box.addButton("Go back", QMessageBox.RejectRole)
                box.exec()
                if box.clickedButton() is not use:
                    return
                self.edits[drop].clear()
                return self.save()
            if k:
                seen[k] = action
        sc = {}
        for action, e in self.edits.items():
            k = e.keySequence().toString()
            if k != DEFAULT_SHORTCUTS[action][1]:
                sc[action] = k
        self.store.data["shortcuts"] = sc
        self.store.save("shortcuts")
        self.win.install_shortcuts()
        self.accept()


# ====================================================================== preferences

ACCENTS = [("Cone orange", "#FF8800"), ("Amber", "#FFB300"), ("Red", "#F0483E"), ("Pink", "#F2558F"),
           ("Violet", "#9B6BFF"), ("Blue", "#3D8BFF"), ("Teal", "#1EC7B2"), ("Green", "#52C35A")]


def muted_note(text):
    lab = QLabel(text)
    lab.setObjectName("Muted")
    lab.setWordWrap(True)
    return lab


class HomeSectionList(QWidget):
    """Home screen sections (#53): drag the handle to reorder, click the eye to show or hide."""
    ROW = 34

    def __init__(self, store, on_change):
        super().__init__()
        from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem, QStyledItemDelegate
        self.store, self.on_change = store, on_change
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setObjectName("HomeSections")
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setDefaultDropAction(Qt.MoveAction)
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setFixedHeight(self.ROW * len(HOME_SECTIONS) + 6)
        for key in store.home_order():
            it = QListWidgetItem(HOME_SECTIONS[key][0])
            it.setData(Qt.UserRole, key)
            it.setSizeHint(QSize(10, self.ROW))
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled)
            self.list.addItem(it)
        owner = self

        class Rows(QStyledItemDelegate):
            def paint(self, p, opt, index):
                r = opt.rect
                shown = owner.is_shown(index.data(Qt.UserRole))
                p.save()
                from PySide6.QtWidgets import QStyle
                if opt.state & QStyle.State_MouseOver:
                    p.fillRect(r, QColor(theme.SURFACE_HI))
                p.drawPixmap(r.x() + 6, r.y() + (r.height() - 16) // 2, pixmap("drag", theme.FAINT, 16))
                p.drawPixmap(owner.eye_rect(r).topLeft(), pixmap("eye" if shown else "eye_off",
                                                                 theme.accent() if shown else theme.FAINT, 18))
                p.setPen(QColor(theme.TEXT if shown else theme.FAINT))
                p.drawText(r.adjusted(58, 0, -8, 0), Qt.AlignVCenter | Qt.AlignLeft, index.data())
                p.restore()

        self.list.setItemDelegate(Rows(self.list))
        self.list.viewport().installEventFilter(self)
        self.list.setMouseTracking(True)
        self.list.model().rowsMoved.connect(lambda *_: self._save_order())
        lay.addWidget(self.list)

    @staticmethod
    def eye_rect(r):
        from PySide6.QtCore import QRect
        return QRect(r.x() + 30, r.y() + (r.height() - 18) // 2, 18, 18)

    def is_shown(self, key):
        return bool(self.store.setting(HOME_SECTIONS[key][1]))

    def keys(self):
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]

    def toggle(self, key):
        self.on_change(HOME_SECTIONS[key][1], not self.is_shown(key))
        self.list.viewport().update()

    def _save_order(self):
        self.store.set_setting("home_order", self.keys())
        self.on_change(None, None)

    def eventFilter(self, obj, e):
        from PySide6.QtCore import QEvent
        if e.type() == QEvent.MouseButtonRelease and e.button() == Qt.LeftButton:
            pos = e.position().toPoint()
            it = self.list.itemAt(pos)
            if it and self.eye_rect(self.list.visualItemRect(it)).adjusted(-6, -6, 6, 6).contains(pos):
                self.toggle(it.data(Qt.UserRole))
                return True
        return False


class PreferencesDialog(QDialog):
    """Settings grouped in plain words, each with an info icon."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.store = win.store
        self.setWindowTitle("Preferences")
        self.resize(760, 520)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        nav = QListWidget()
        nav.setFixedWidth(190)
        nav.setObjectName("Panel")
        nav.setStyleSheet(f"QListWidget {{ background: {theme.PANEL}; padding: 12px 8px; }}")
        nav.setIconSize(QSize(18, 18))
        self.pages = QStackedWidget()
        outer.addWidget(nav)
        right = QVBoxLayout()
        right.setContentsMargins(24, 20, 24, 16)
        right.addWidget(self.pages, 1)
        bb = QDialogButtonBox()
        ok = bb.addButton("Done", QDialogButtonBox.AcceptRole)
        ok.setObjectName("Primary")
        bb.accepted.connect(self.accept)
        right.addWidget(bb)
        outer.addLayout(right, 1)

        for ic, name, builder in (("settings", "General", self._general), ("eye_off", "Interface", self._interface),
                                  ("play", "Playback", self._playback), ("subtitles", "Subtitles", self._subtitles),
                                  ("keyboard", "Controls", self._controls), ("clock", "Privacy", self._privacy),
                                  ("speed", "Performance", self._performance)):
            it = QListWidgetItem(icon(ic, theme.MUTED, 18), name)
            nav.addItem(it)
            page = QWidget()
            form = QVBoxLayout(page)
            form.setSpacing(10)
            h = QLabel(name)
            h.setObjectName("H1")
            form.addWidget(h)
            builder(form)
            form.addStretch(1)
            self.pages.addWidget(self._scroll_page(page))
        nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        nav.setCurrentRow(0)

    def _scroll_page(self, page):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        return scroll

    def _colour_button(self, name, colours, selected, callback):
        b = QPushButton(name)
        b.setCheckable(True)
        b.setChecked(selected)
        b.setMinimumHeight(32)
        swatch = QPixmap(24, 20)
        swatch.fill(Qt.transparent)
        p = QPainter(swatch)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        for i, colour in enumerate(colours):
            p.setBrush(QColor(colour))
            p.drawEllipse(2 + i * 8, 4, 12, 12)
        p.end()
        b.setIcon(QIcon(swatch))
        b.setIconSize(QSize(24, 20))
        b.setStyleSheet("QPushButton { text-align: left; padding: 5px 8px; }"
                       f"QPushButton:checked {{ border: 1px solid {theme.accent()}; }}")
        b.clicked.connect(callback)
        return b

    def _refresh_general(self):
        # Rebuild only this page so theme-dependent styles and selections stay current.
        old = self.pages.widget(0)
        page = QWidget()
        form = QVBoxLayout(page)
        form.setSpacing(10)
        h = QLabel("General")
        h.setObjectName("H1")
        form.addWidget(h)
        self._general(form)
        form.addStretch(1)
        self.pages.removeWidget(old)
        self.pages.insertWidget(0, self._scroll_page(page))
        self.pages.setCurrentIndex(0)
        old.deleteLater()

    def _general(self, f):
        f.addWidget(info_label("Accent color", "Changes the orange used for highlights, the seek bar and the cone."))
        grid = QGridLayout()
        grid.setSpacing(8)
        cur = self.store.setting("accent")
        if theme.is_vibe(self.store.setting("theme")):
            f.addWidget(muted_note("The current neon theme uses its own colours. Your accent colour returns when you pick a non-neon theme."))
        for i, (name, col) in enumerate(ACCENTS):
            b = self._colour_button(name, [col], col.lower() == cur.lower(),
                                    lambda _=False, c=col: self._set_accent(c))
            grid.addWidget(b, i // 4, i % 4)
        custom = self._colour_button("Custom…", [cur] if cur.lower() not in {c.lower() for _, c in ACCENTS} else [],
                                     False, lambda _=False: self._custom_accent())
        grid.addWidget(custom, 2, 0)
        f.addLayout(grid)
        f.addSpacing(10)
        self._theme_section(f)

    def _theme_section(self, f):
        f.addWidget(info_label("Theme", "The background colours of Pylon. Text always stays light, so it's easy to read."))
        cur = self.store.setting("theme") or "dark"

        def chip(key, pal):
            v = pal.get("vibe")
            colours = [v["stops"][0], v["stops"][-1]] if v else [pal["BG"]]
            b = self._colour_button(pal["name"], colours, key == cur,
                                    lambda _=False, k=key: self._set_theme(k))
            return b

        grid = QGridLayout()
        grid.setSpacing(8)
        plain = [(k, t) for k, t in theme.THEMES.items() if "vibe" not in t]
        neon = [(k, t) for k, t in theme.THEMES.items() if "vibe" in t]
        for i, (k, t) in enumerate(plain):
            grid.addWidget(chip(k, t), i // 4, i % 4)
        tint = self.store.setting("theme_tint")
        custom = self._colour_button("Tint…",
                                     [tint] if tint else [], cur == "custom", self._custom_theme)
        custom.setToolTip("Pick any colour; Pylon uses dark shades of it for the background.")
        row = (len(plain) + 3) // 4
        grid.addWidget(custom, row, 0)
        f.addLayout(grid)
        f.addSpacing(6)
        f.addWidget(info_label("Neon", "Black or deep-tinted backgrounds with glowing gradient highlights. "
                                       "These use their own colours instead of your accent colour."))
        g2 = QGridLayout()
        g2.setSpacing(8)
        for i, (k, t) in enumerate(neon):
            g2.addWidget(chip(k, t), i // 4, i % 4)
        f.addLayout(g2)

    def _set_theme(self, key, tint=None):
        self.store.set_setting("theme", key)
        if tint is not None:
            self.store.set_setting("theme_tint", tint)
        self.win.apply_theme()
        QTimer.singleShot(0, self._refresh_general)
        self.win.toast("Theme: " + (theme.THEMES[key]["name"] if key in theme.THEMES else "Custom tint"))

    def _custom_theme(self, checked=False):
        start = self.store.setting("theme_tint") or "#3D5A80"
        c = choose_colour(self.store, start, self, "Background tint")
        if c.isValid():
            self._set_theme("custom", c.name())

    def _set_accent(self, c):
        self.store.set_setting("accent", c)
        self.win.apply_theme()
        QTimer.singleShot(0, self._refresh_general)
        self.win.toast("Accent color changed")

    def _custom_accent(self):
        c = choose_colour(self.store, self.store.setting("accent"), self, "Accent color")
        if c.isValid():
            self._set_accent(c.name())

    def _interface(self, f):
        f.addWidget(info_label("Hide the controls after", "How long the top and bottom bars stay after the mouse stops moving."))
        sp = QSpinBox()
        sp.setRange(500, 10000)
        sp.setSingleStep(250)
        sp.setSuffix(" ms")
        sp.setValue(int(self.store.setting("hide_delay_ms")))
        sp.valueChanged.connect(lambda v: self.store.set_setting("hide_delay_ms", v))
        f.addWidget(sp)
        cb = QCheckBox("Show which key I pressed in on-screen messages")
        cb.setChecked(bool(self.store.setting("osd_shortcuts")))
        cb.toggled.connect(lambda v: self.store.set_setting("osd_shortcuts", v))
        f.addWidget(cb)
        cb3 = QCheckBox("Keep the controls visible when not in fullscreen")
        cb3.setToolTip("The top and bottom bars stay on screen in a normal window, and the video sits between them. "
                       "In fullscreen they still hide when you stop moving the mouse.")
        cb3.setChecked(bool(self.store.setting("pin_controls")))
        cb3.toggled.connect(lambda v: self.store.set_setting("pin_controls", v))
        f.addWidget(cb3)
        simple = QCheckBox("Show simplified names in the queue")
        simple.setChecked(bool(self.store.setting("simple_queue_names")))
        simple.setToolTip("Changes displayed titles only. Hover an item to see its original path.")
        simple.toggled.connect(self._set_simple_queue)
        f.addWidget(simple)
        cb2 = QCheckBox("Show a preview picture when I hover over the seek bar")
        cb2.setToolTip("Pylon makes small previews of each video in the background and keeps them for next time.")
        cb2.setChecked(bool(self.store.setting("seek_previews")))
        cb2.toggled.connect(self._set_previews)
        f.addWidget(cb2)
        f.addWidget(info_label("Waveform in the seek bar",
                               "Draws the sound's loud and quiet parts along the seek bar, so you can find the start "
                               "of a song or a scene. Pylon reads the sound in the background and keeps the result."))
        wave = QComboBox()
        wave.setObjectName("seek_waveform")
        for label, v in (("For music", "audio"), ("For music and videos", "all"), ("Off", "off")):
            wave.addItem(label, v)
        wave.setCurrentIndex(max(0, wave.findData(self.store.setting("seek_waveform"))))
        wave.currentIndexChanged.connect(lambda i: self._set_waveform(wave.itemData(i)))
        f.addWidget(wave)
        tabs = QFormLayout()
        for key, label, options in (
                ("library_startup_tab", "Library tab at startup", (("Library", "library"), ("Music", "music"),
                 ("Recent", "recent"), ("Playlists", "playlists"), ("Streams", "streams"))),
                ("settings_startup_tab", "Settings tab at startup", (("Subtitles", "subtitles"), ("Audio", "audio"),
                 ("Video", "video"), ("Playback", "playback"), ("Bookmarks", "bookmarks")))):
            choice = QComboBox()
            choice.setObjectName(key)
            for text, value in options:
                choice.addItem(text, value)
            choice.addItem("Last used", "last")
            choice.setCurrentIndex(max(0, choice.findData(self.store.setting(key))))
            choice.setToolTip("Applies next time Pylon starts. Reopening a side panel keeps its current tab.")
            choice.currentIndexChanged.connect(
                lambda _, c=choice, k=key: self.store.set_setting(k, c.currentData()))
            tabs.addRow(label, choice)
        f.addLayout(tabs)
        f.addWidget(info_label("Home screen sections",
                               "Drag a section by its handle to move it. Click the eye to show or hide it. "
                               "Hiding a section doesn't delete anything."))
        self.home_sections = HomeSectionList(self.store, self._set_home_section)
        f.addWidget(self.home_sections)

    def _set_simple_queue(self, on):
        self.store.set_setting("simple_queue_names", on)
        self.win.library.refresh_queue()

    def _set_home_section(self, key, on):
        if key:
            self.store.set_setting(key, on)
        self.win.home.refresh()

    def _set_previews(self, on):
        self.store.set_setting("seek_previews", on)
        if on:
            self.win.start_previews()
        else:
            self.win.thumbs.cancel()

    def _set_waveform(self, mode):
        self.store.set_setting("seek_waveform", mode)
        self.win.start_waveform()

    def _playback(self, f):
        f.addWidget(info_label("When I open something I didn't finish", "Pylon remembers where you stopped in every file."))
        combo = QComboBox()
        for label, v in (("Ask me (a button appears next to the play controls)", "ask"),
                         ("Always continue where I left off", "always"), ("Always start from the beginning", "never")):
            combo.addItem(label, v)
        combo.setCurrentIndex(max(0, combo.findData(self.store.setting("resume"))))
        combo.currentIndexChanged.connect(lambda i: self.store.set_setting("resume", combo.itemData(i)))
        f.addWidget(combo)
        f.addWidget(info_label("Maximum volume", "Above 100% Pylon boosts quiet audio, like VLC. Very loud sound can distort."))
        vol = QComboBox()
        for v in (125, 150, 200):
            vol.addItem(f"{v}%", v)
        vol.setCurrentIndex(max(0, vol.findData(self.win.engine.max_volume())))
        vol.currentIndexChanged.connect(lambda i: self._set_max_volume(vol.itemData(i)))
        f.addWidget(vol)
        f.addWidget(info_label("Queue mode when Pylon starts",
                               "The button above the queue changes it while you watch: stop, shuffle, in order or loop."))
        qm = QComboBox()
        for k, v in QUEUE_MODES.items():
            qm.addItem(v[1], k)
        qm.setCurrentIndex(max(0, qm.findData(self.store.setting("queue_mode"))))
        qm.currentIndexChanged.connect(lambda i: self.store.set_setting("queue_mode", qm.itemData(i)))
        f.addWidget(qm)
        cb = QCheckBox("When a file ends, play the next file in the same folder")
        cb.setChecked(bool(self.store.setting("binge")))
        cb.toggled.connect(lambda v: self.store.set_setting("binge", v))
        f.addWidget(cb)

    def _set_max_volume(self, m: int):
        self.store.set_setting("max_volume", int(m))
        e = self.win.engine
        self.win.bottom.cone.set_max(int(m))
        if e.volume() > m:
            e.set_volume(m)
        self.win.bottom.set_volume(e.volume(), e.is_muted())

    def _subtitles(self, f):
        f.addWidget(info_label("Find subtitle files automatically",
                               "Looks in the video's folder and in Subs or Subtitles folders next to it."))
        combo = QComboBox()
        for v, label in MATCH_LEVELS:
            combo.addItem(label, v)
        combo.setCurrentIndex(max(0, combo.findData(self.store.setting("sub_match"))))
        combo.currentIndexChanged.connect(lambda i: self.store.set_setting("sub_match", combo.itemData(i)))
        f.addWidget(combo)
        f.addWidget(info_label("Preferred subtitle site", "Marked with a star in the Find online menu. The menu keeps the same order."))
        from .util import SUBTITLE_SITES
        site = QComboBox()
        site.addItem("No preference", "")
        for key, name, _u in SUBTITLE_SITES:
            site.addItem(name, key)
        site.setCurrentIndex(max(0, site.findData(self.store.setting("sub_site_star"))))
        site.currentIndexChanged.connect(lambda i: self.store.set_setting("sub_site_star", site.itemData(i)))
        f.addWidget(site)
        f.addWidget(info_label("Preferred subtitle language", "Used for every file unless a preset says otherwise. e.g. eng, English, off"))
        le = QLineEdit(self.store.setting("sub_lang"))
        le.textChanged.connect(lambda t: self.store.set_setting("sub_lang", t.strip()))
        f.addWidget(le)
        f.addWidget(info_label("Preferred audio language", "e.g. jpn, eng, Hindi"))
        le2 = QLineEdit(self.store.setting("audio_lang"))
        le2.textChanged.connect(lambda t: self.store.set_setting("audio_lang", t.strip()))
        f.addWidget(le2)

    def _controls(self, f):
        b = QPushButton("Edit keyboard shortcuts…")
        b.setIcon(icon("keyboard", theme.TEXT, 16))
        b.clicked.connect(lambda: (self.accept(), self.win.show_shortcuts()))
        f.addWidget(b)
        form = QFormLayout()
        actions = (("Disabled", "none"), ("Play / pause", "play_pause"),
                   ("Fullscreen", "fullscreen"), ("Mute", "mute"),
                   ("Next in queue", "next"), ("Previous in queue", "prev"),
                   ("Jump back 10s", "seek_back"), ("Jump forward 10s", "seek_fwd"))
        for key, label in (("mouse_single", "Left click"), ("mouse_double", "Left double-click"),
                           ("mouse_middle", "Middle click"), ("mouse_back", "Back button"),
                           ("mouse_forward", "Forward button")):
            combo = QComboBox()
            combo.setObjectName(key)
            for text, value in actions:
                combo.addItem(text, value)
            combo.setCurrentIndex(max(0, combo.findData(self.store.setting(key))))
            combo.currentIndexChanged.connect(
                lambda _, c=combo, k=key: self.store.set_setting(k, c.currentData()))
            form.addRow(label, combo)
        f.addLayout(form)
        f.addWidget(muted_note("These bindings apply over the video. Disable Left double-click for immediate "
                               "single clicks; otherwise Pylon waits for your system's double-click interval. "
                               "Scroll changes volume; right-click opens the menu. Extra buttons must be "
                               "reported by the mouse driver as standard mouse buttons."))

    def _privacy(self, f):
        f.addWidget(muted_note("To hide Continue watching or Recently played from the home screen, use "
                               "Home screen sections in the Interface tab. Hiding them doesn't delete your history."))
        cb = QCheckBox("Remember recent files and where I stopped")
        cb.setChecked(bool(self.store.setting("remember_history")))
        cb.toggled.connect(lambda v: self.store.set_setting("remember_history", v))
        f.addWidget(cb)
        b = QPushButton("Clear history now")
        b.clicked.connect(self._clear)
        f.addWidget(b)
        cb_up = QCheckBox("Check for new versions of Pylon once a day")
        cb_up.setToolTip("Pylon asks GitHub for its list of releases. Nothing about you or your files is sent.")
        cb_up.setChecked(bool(self.store.setting("check_updates")))
        cb_up.toggled.connect(lambda v: self.store.set_setting("check_updates", v))
        f.addWidget(cb_up)
        up_row = QHBoxLayout()
        up_now = QPushButton("Check now")
        up_now.clicked.connect(lambda: self.win.check_for_updates(manual=True))
        up_row.addWidget(up_now)
        up_row.addStretch(1)
        f.addLayout(up_row)
        f.addWidget(muted_note("This is the only time Pylon goes online by itself. It's an anonymous request "
                               "for the release list on GitHub; nothing about you or your files is sent."))
        lab = QLabel(f"Your data is stored only on this computer:\n{self.store.path}")
        lab.setObjectName("Muted")
        lab.setWordWrap(True)
        lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lab.setTextFormat(Qt.PlainText)
        lab.setMinimumWidth(0)
        lab.setToolTip(self.store.path)
        f.addWidget(lab)
        folder = QPushButton("Open data folder")
        folder.setIcon(icon("folder", theme.TEXT, 16))
        folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(self.store.path))))
        f.addWidget(folder)

    def _set_rtx_upscale(self, on: bool):
        self.store.set_setting("rtx_upscale", on)
        engine = self.win.engine
        if engine.ok:
            engine.rebuild()            # applies now and continues from the same point

    def _clear(self):
        self.store.clear_history()
        self.win.home.refresh()
        self.win.toast("History cleared")

    def _performance(self, f):
        cb = QCheckBox("Use the graphics card to decode video (hardware decoding)")
        cb.setChecked(bool(self.store.setting("hw_decoding")))
        cb.toggled.connect(lambda v: self.store.set_setting("hw_decoding", v))
        f.addWidget(cb)
        lab = QLabel("Turn this off if you see green frames or glitches. Takes effect the next time the engine restarts.")
        lab.setObjectName("Muted")
        lab.setWordWrap(True)
        f.addWidget(lab)
        if sys.platform == "win32":
            up = QCheckBox("Use RTX Video Super Resolution to upscale video (NVIDIA RTX and Intel graphics)")
            up.setChecked(bool(self.store.setting("rtx_upscale")))
            up.toggled.connect(self._set_rtx_upscale)
            f.addWidget(up)
            note = QLabel("Makes lower-resolution video sharper on a bigger screen. On NVIDIA, also turn on "
                          "Video Super Resolution in the NVIDIA app. Other graphics cards play normally.")
            note.setObjectName("Muted")
            note.setWordWrap(True)
            f.addWidget(note)
        f.addWidget(info_label("VLC engine", "Pylon finds an installed VLC automatically. Use this for a portable VLC "
                                             "or one installed somewhere unusual."))
        cur = self.store.setting("vlc_dir") or "Found automatically"
        where = QLabel(cur)
        where.setObjectName("Muted")
        where.setWordWrap(True)
        f.addWidget(where)
        row = QHBoxLayout()
        pick = QPushButton("Use VLC from a folder…")
        pick.clicked.connect(lambda: (self.win.locate_vlc(), where.setText(self.store.setting("vlc_dir") or "Found automatically")))
        auto = QPushButton("Find automatically")
        def find_auto():
            changed = bool(self.store.setting("vlc_dir"))
            self.store.set_setting("vlc_dir", "")
            where.setText("Found automatically")
            if changed and self.win.engine.ok:
                self.win.ask_restart("Pylon will look for VLC by itself after it restarts.")
        auto.clicked.connect(find_auto)
        row.addWidget(pick)
        row.addWidget(auto)
        row.addStretch(1)
        f.addLayout(row)


# ====================================================================== welcome

class WelcomeDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.setWindowTitle("Welcome")
        self.resize(560, 470)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(10)
        row = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(pixmap("cone", theme.accent(), 44))
        row.addWidget(logo)
        t = QLabel("Welcome to Pylon")
        t.setObjectName("H1")
        row.addWidget(t)
        row.addStretch(1)
        lay.addLayout(row)
        sub = QLabel("The VLC engine you know, with a calmer interface. A few keys worth knowing:")
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        lay.addWidget(sub)
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        keys = [("Space", "Play / pause"), ("← →", "Jump 10 seconds"), ("F", "Fullscreen"),
                ("H", "Hide the interface"), ("G  J", "Move subtitles earlier / later"), ("[  ]", "Slower / faster"),
                ("Ctrl+B", "Bookmark this moment"), ("Ctrl+L", "Library"), ("Ctrl+T", "Settings panel"), ("F1", "All shortcuts")]
        for i, (k, d) in enumerate(keys):
            kl = QLabel(k)
            kl.setStyleSheet(f"background: {theme.SURFACE}; border: 1px solid {theme.BORDER}; border-radius: 3px;"
                             f" padding: 2px 8px; font-weight: 600;")
            kl.setAlignment(Qt.AlignCenter)
            grid.addWidget(kl, i // 2, (i % 2) * 2)
            grid.addWidget(QLabel(d), i // 2, (i % 2) * 2 + 1)
        lay.addLayout(grid)
        lay.addStretch(1)
        lay.addWidget(QLabel("Pick a color (you can change it later in Preferences)"))
        crow = QHBoxLayout()
        self.color = theme.accent()
        for name, col in ACCENTS:
            b = QPushButton()
            b.setFixedSize(30, 30)
            b.setToolTip(name)
            b.setStyleSheet(f"QPushButton {{ background: {col}; border: 2px solid {theme.BORDER}; border-radius: 4px; }}"
                            f"QPushButton:hover {{ border-color: white; }}")
            b.clicked.connect(lambda _=False, c=col: self._pick(c))
            crow.addWidget(b)
        crow.addStretch(1)
        lay.addLayout(crow)
        bb = QDialogButtonBox()
        ok = bb.addButton("Start watching", QDialogButtonBox.AcceptRole)
        ok.setObjectName("Primary")
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)

    def _pick(self, c):
        self.color = c


# ====================================================================== updates

class UpdateDialog(QDialog):
    """Shown when a newer Pylon is out: what's new, and Update now / Later / Skip."""

    def __init__(self, win, release: dict):
        super().__init__(win)
        from PySide6.QtWidgets import QProgressBar, QTextBrowser
        from . import APP_VERSION
        from .updates import installer_asset, RELEASES_PAGE
        self.win = win
        self.release = release
        self.checker = win.updater
        self.tag = (release.get("tag_name") or "").lstrip("vV")
        self.asset = installer_asset(release) if sys.platform == "win32" else None
        self.page = release.get("html_url") or RELEASES_PAGE
        self.setWindowTitle("Update available")
        self.resize(560, 440)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)
        t = QLabel(f"Pylon {self.tag} is out")
        t.setObjectName("H1")
        lay.addWidget(t)
        how = ("Update now downloads the installer and closes Pylon so it can install. "
               "Your library, presets and settings are kept.") if self.asset else \
              "Download it from the release page. Your library, presets and settings are kept."
        sub = QLabel(f"You have {APP_VERSION}. {how}")
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        lay.addWidget(sub)
        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        body = (release.get("body") or "").strip()
        # the downloads table and checksums aren't useful here
        body = body.split("### Downloads")[0].split("## Downloads")[0].strip()
        if body.startswith("#"):            # the release title repeats the heading above
            body = body.split("\n", 1)[1].strip() if "\n" in body else ""
        notes.setMarkdown(body or "See the release page for what's new.")
        lay.addWidget(notes, 1)
        self.bar = QProgressBar()
        self.bar.setTextVisible(True)
        self.bar.hide()
        lay.addWidget(self.bar)
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        self.status.hide()
        lay.addWidget(self.status)

        row = QHBoxLayout()
        self.skip = QPushButton("Skip this version")
        self.skip.clicked.connect(self._skip)
        row.addWidget(self.skip)
        row.addStretch(1)
        self.later = QPushButton("Later")
        self.later.clicked.connect(self.reject)
        row.addWidget(self.later)
        self.go = QPushButton("Update now" if self.asset else "Open download page")
        self.go.setObjectName("Primary")
        self.go.setDefault(True)
        self.go.clicked.connect(self._go)
        row.addWidget(self.go)
        lay.addLayout(row)

        c = self.checker
        c.download_progress.connect(self._progress)
        c.downloaded.connect(self._downloaded)
        c.download_failed.connect(self._failed)
        self._downloading = False

    def _skip(self):
        self.win.store.set_setting("skipped_version", self.tag)
        self.reject()

    def _go(self):
        if not self.asset:
            QDesktopServices.openUrl(QUrl(self.page))
            self.accept()
            return
        self._downloading = True
        self.go.setEnabled(False)
        self.skip.setEnabled(False)
        self.later.setText("Cancel")
        self.bar.setRange(0, 0)
        self.bar.show()
        self.status.setText("Downloading the installer…")
        self.status.show()
        self.checker.download(self.asset)

    def _progress(self, done, total):
        if total > 0:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(done * 1000 / total))
            self.bar.setFormat(f"{done / 1048576:.1f} of {total / 1048576:.1f} MB")

    def _downloaded(self, path):
        from .updates import run_installer
        self._downloading = False
        self.status.setText("Starting the installer. Pylon will close now.")
        if run_installer(path):
            self.accept()
            self.win.quit_for_update()
        else:
            self._failed("Couldn't start the installer")

    def _failed(self, why):
        self._downloading = False
        self.bar.hide()
        self.go.setEnabled(True)
        self.go.setText("Open download page")
        self.asset = None
        self.later.setText("Later")
        self.status.setText(f"The download didn't work ({why}). You can get the installer from the release page instead.")
        self.status.show()

    def reject(self):
        if self._downloading:
            self.checker.cancel()
            self._downloading = False
        super().reject()

    def done(self, r):
        c = self.checker
        for sig, fn in ((c.download_progress, self._progress), (c.downloaded, self._downloaded),
                        (c.download_failed, self._failed)):
            try:
                sig.disconnect(fn)
            except (RuntimeError, TypeError):
                pass
        super().done(r)
