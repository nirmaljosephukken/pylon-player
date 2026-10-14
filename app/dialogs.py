"""Dialogs: add subtitles (file / folder / queue with auto-matching), network
stream, keyboard shortcuts, preferences, and the first-run welcome."""
import os

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout,
                               QHeaderView, QKeySequenceEdit, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QRadioButton, QSpinBox,
                               QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from . import theme
from .icons import icon, pixmap
from .store import DEFAULT_SHORTCUTS
from .util import MATCH_LEVELS, SUB_EXTS, auto_match_folder, display_name, is_url, list_media

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
        online.setToolTip("Opens OpenSubtitles in your browser. Download, unzip, then choose the files here.")
        online.clicked.connect(self.search_online)
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

    def search_online(self):
        vids = self.videos()
        name = display_name(vids[0]) if vids else ""
        if self.scope.checkedId() == 1 and self.folder:
            name = os.path.basename(self.folder)
        q = QUrl.toPercentEncoding(name).data().decode()
        QDesktopServices.openUrl(QUrl(f"https://www.opensubtitles.org/en/search2/moviename-{q}/sublanguageid-all"))

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

    def save(self):
        seen = {}
        for action, e in self.edits.items():
            k = e.keySequence().toString()
            if k and k in seen:
                QMessageBox.warning(self, "Same key used twice",
                                    f"“{k}” is set for both “{DEFAULT_SHORTCUTS[seen[k]][0]}” "
                                    f"and “{DEFAULT_SHORTCUTS[action][0]}”.")
                return
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
            self.pages.addWidget(page)
        nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        nav.setCurrentRow(0)

    def _general(self, f):
        f.addWidget(info_label("Accent color", "Changes the orange used for highlights, the seek bar and the cone."))
        grid = QGridLayout()
        grid.setSpacing(8)
        cur = self.store.setting("accent")
        for i, (name, col) in enumerate(ACCENTS):
            b = QPushButton(name)
            b.setStyleSheet(f"QPushButton {{ border-left: 16px solid {col}; text-align: left; padding-left: 10px; }}"
                            + (f"QPushButton {{ border-color: {col}; }}" if col.lower() == cur.lower() else ""))
            b.clicked.connect(lambda _=False, c=col: self._set_accent(c))
            grid.addWidget(b, i // 4, i % 4)
        custom = QPushButton("Custom…")
        custom.clicked.connect(self._custom_accent)
        grid.addWidget(custom, 2, 0)
        f.addLayout(grid)

    def _set_accent(self, c):
        self.store.set_setting("accent", c)
        self.win.apply_theme()
        self.accept()
        self.win.toast("Accent color changed")

    def _custom_accent(self):
        c = QColorDialog.getColor(QColor(self.store.setting("accent")), self, "Accent color")
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
        cb2 = QCheckBox("Show a preview picture when I hover over the seek bar")
        cb2.setToolTip("Pylon makes small previews of each video in the background and keeps them for next time.")
        cb2.setChecked(bool(self.store.setting("seek_previews")))
        cb2.toggled.connect(self._set_previews)
        f.addWidget(cb2)

    def _set_previews(self, on):
        self.store.set_setting("seek_previews", on)
        if on:
            self.win.start_previews()
        else:
            self.win.thumbs.cancel()

    def _playback(self, f):
        f.addWidget(info_label("When I open something I didn't finish", "Pylon remembers where you stopped in every file."))
        combo = QComboBox()
        for label, v in (("Ask me (a button appears next to the play controls)", "ask"),
                         ("Always continue where I left off", "always"), ("Always start from the beginning", "never")):
            combo.addItem(label, v)
        combo.setCurrentIndex(max(0, combo.findData(self.store.setting("resume"))))
        combo.currentIndexChanged.connect(lambda i: self.store.set_setting("resume", combo.itemData(i)))
        f.addWidget(combo)
        cb = QCheckBox("When a file ends, play the next file in the same folder")
        cb.setChecked(bool(self.store.setting("binge")))
        cb.toggled.connect(lambda v: self.store.set_setting("binge", v))
        f.addWidget(cb)

    def _subtitles(self, f):
        f.addWidget(info_label("Find subtitle files automatically",
                               "Looks in the video's folder and in Subs or Subtitles folders next to it."))
        combo = QComboBox()
        for v, label in MATCH_LEVELS:
            combo.addItem(label, v)
        combo.setCurrentIndex(max(0, combo.findData(self.store.setting("sub_match"))))
        combo.currentIndexChanged.connect(lambda i: self.store.set_setting("sub_match", combo.itemData(i)))
        f.addWidget(combo)
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
        lab = QLabel("Mouse: click the video to play or pause, double-click for fullscreen, scroll for volume, "
                     "right-click for the menu.")
        lab.setObjectName("Muted")
        lab.setWordWrap(True)
        f.addWidget(lab)

    def _privacy(self, f):
        cb = QCheckBox("Remember recent files and where I stopped")
        cb.setChecked(bool(self.store.setting("remember_history")))
        cb.toggled.connect(lambda v: self.store.set_setting("remember_history", v))
        f.addWidget(cb)
        b = QPushButton("Clear history now")
        b.clicked.connect(self._clear)
        f.addWidget(b)
        lab = QLabel(f"Your data is stored only on this computer:\n{self.store.path}")
        lab.setObjectName("Muted")
        lab.setWordWrap(True)
        lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
        f.addWidget(lab)

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
                ("Ctrl+B", "Bookmark this moment"), ("Ctrl+L", "Library"), ("Ctrl+T", "Settings sidebar"), ("F1", "All shortcuts")]
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
