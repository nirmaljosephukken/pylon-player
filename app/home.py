"""Home page (instead of a blank screen: continue watching, recent, your
library, playlists, streams) and the Now Playing page used for music."""
import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

from . import theme
from .icons import icon, pixmap
from .util import display_name, fmt_time, is_audio, is_url, pretty_title, to_path
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

        cont = self.store.continue_watching()
        if cont:
            lay.addWidget(self._section("Continue watching"))
            row = FlowRow()
            for e in cont:
                p = e["path"]
                title, _, code = pretty_title(p).partition("  ·  ")
                c = Card(title, f"{code + '  ·  ' if code else ''}{fmt_time(e['pos'])} of {fmt_time(e['len'])}"
                         f"{'' if code else '  ·  ' + _parent(p)}",
                         "music" if is_audio(p) else "play", progress=e["pos"] / max(1, e["len"]))
                c.setToolTip(p)
                c.clicked.connect(lambda p=p, t=e["pos"]: self.win.play_from_folder(p, start_ms=t))
                row.add(c)
            lay.addWidget(hscroll(row))

        recent = [r for r in self.store.data["recent"] if r["path"] not in {c["path"] for c in cont}][:12]
        if recent:
            lay.addWidget(self._section("Recently played"))
            row = FlowRow()
            for r in recent:
                p = r["path"]
                c = Card(pretty_title(p), "Stream" if is_url(p) else _parent(p),
                         "stream" if is_url(p) else ("music" if is_audio(p) else "video"))
                c.setToolTip(p)
                c.clicked.connect(lambda p=p: self.win.play_from_folder(p))
                row.add(c)
            lay.addWidget(hscroll(row))

        folders = self.store.data["pinned"] + [f for f in self.store.data["library_folders"]
                                               if f not in self.store.data["pinned"]]
        lay.addWidget(self._section("Your library"))
        if folders:
            row = FlowRow()
            for f in folders:
                c = Card(os.path.basename(f.rstrip("\\/")) or f, f, "folder")
                c.clicked.connect(lambda f=f: self.win.browse_folder(f))
                row.add(c)
            lay.addWidget(hscroll(row))
        else:
            lay.addWidget(self._muted("Add a folder (movies, shows, music) to see it here and in the library sidebar."))

        pls = self.store.data["playlists"]
        if pls:
            lay.addWidget(self._section("Playlists"))
            row = FlowRow()
            positions = self.store.data["positions"]
            for name, items in sorted(pls.items()):
                done = sum(1 for p in items if positions.get(p, {}).get("watched"))
                sub = f"{len(items)} item{'s' if len(items) != 1 else ''}"
                if done:
                    sub += f"  ·  {done} watched"
                c = Card(name, sub, "playlist", progress=done / len(items) if items and done else None)
                c.clicked.connect(lambda n=name: self.win.play_playlist(n))
                row.add(c)
            lay.addWidget(hscroll(row))

        streams = self.store.data["streams"]
        if streams:
            lay.addWidget(self._section("Streams"))
            row = FlowRow()
            for s in streams[:12]:
                c = Card(s["name"], s["url"], "stream")
                c.clicked.connect(lambda s=s: self.win.open_stream(s["url"], s["name"]))
                row.add(c)
            lay.addWidget(hscroll(row))

        lay.addStretch(1)
        keys = QLabel("Space play/pause  ·  ←/→ jump 10s  ·  F fullscreen  ·  H hide interface  ·  "
                      "Ctrl+B bookmark  ·  F1 all shortcuts")
        keys.setStyleSheet(f"color: {theme.FAINT}; font-size: 12px;")
        lay.addWidget(keys)
        old = self.takeWidget()
        if old:
            old.deleteLater()
        self.setWidget(inner)

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
