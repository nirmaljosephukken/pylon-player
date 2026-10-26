"""Library panel building blocks: item roles, the list widgets and small helpers."""
import os
import subprocess
import sys

from PySide6.QtCore import QMimeData, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QListWidget, QStyle,
                               QStyledItemDelegate, QWidget)

from . import theme
from .util import is_url, list_media, natural_key, to_path

ROLE_PATH = Qt.UserRole
ROLE_KIND = Qt.UserRole + 1   # "folder" | "file" | "root"

# One entry per way of sorting, with an arrow for its direction (#63):
# kind -> (name, (mode, what it does), (reversed mode, what it does) or None).
# The modes are the values saved in the <section>_sort settings.
SORT_KINDS = {
    "default": ("Default order", ("default", "Default order"), None),
    "added": ("Date added", ("newest", "Newest first"), ("oldest", "Oldest first")),
    "name": ("Name", ("name", "A to Z"), ("reverse", "Z to A")),
    "played": ("Recently played", ("played", "Most recently played first"), ("played_oldest", "Least recently played first")),
    "count": ("Items", ("count", "Most items first"), ("count_fewest", "Fewest items first")),
    "watched": ("Watched", ("unfinished", "Least watched first"), ("finished", "Most watched first")),
    "date": ("Date modified", ("date", "Newest first"), ("date_oldest", "Oldest first")),
    "plays": ("Times played", ("plays", "Most played first"), ("plays_fewest", "Least played first")),
}
SECTION_SORTS = {
    "playlists": ("added", "name", "played", "count", "watched"),
    "streams": ("added", "name", "played"),
    "music": ("default", "name", "count", "date", "played", "plays"),
}


def sort_kind(mode):
    """(kind, reversed) for a saved sort mode."""
    for kind, (_name, first, second) in SORT_KINDS.items():
        if mode == first[0]:
            return kind, False
        if second and mode == second[0]:
            return kind, True
    return None, False


class SortControl(QWidget):
    """How a library tab is sorted: what by, and an arrow that turns the order round (#63)."""
    changed = Signal(str)

    def __init__(self, section, mode):
        super().__init__()
        from .widgets import IconButton
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.kinds = SECTION_SORTS[section]
        self.modes = [m[0] for k in self.kinds for m in SORT_KINDS[k][1:] if m]
        self.combo = QComboBox()
        self.combo.setObjectName(section + "_sort_by")
        self.combo.setToolTip("Sort this view")
        for k in self.kinds:
            self.combo.addItem(SORT_KINDS[k][0], k)
        self.arrow = IconButton("arrow_down", "", size=16)
        self.arrow.setObjectName(section + "_sort_direction")
        lay.addWidget(self.combo)
        lay.addWidget(self.arrow)
        self._mode = None
        self.set_mode(mode if mode in self.modes else self.modes[0], quiet=True)
        self.combo.currentIndexChanged.connect(lambda _: self.set_mode(SORT_KINDS[self.combo.currentData()][1][0]))
        self.arrow.clicked.connect(self.flip)

    def mode(self):
        return self._mode

    def set_mode(self, mode, quiet=False):
        kind, rev = sort_kind(mode)
        if kind not in self.kinds or mode == self._mode:
            return
        self._mode = mode
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(self.combo.findData(kind))
        self.combo.blockSignals(False)
        _name, first, second = SORT_KINDS[kind]
        self.arrow.setEnabled(second is not None)
        self.arrow.set_icon("arrow_up" if rev else "arrow_down")
        now = second if rev else first
        self.arrow.setToolTip(f"{now[1]}. Click to reverse" if second else now[1])
        if not quiet:
            self.changed.emit(mode)

    def flip(self):
        kind, rev = sort_kind(self._mode)
        second = SORT_KINDS[kind][2]
        if second:
            self.set_mode(SORT_KINDS[kind][1 if rev else 2][0])

    def set_kind_enabled(self, kind, on):
        item = self.combo.model().item(self.combo.findData(kind))
        if item is not None:
            item.setEnabled(on)

    # the QComboBox calls the older checks use: one index per mode, both directions
    def currentData(self):
        return self._mode

    def findData(self, mode):
        return self.modes.index(mode) if mode in self.modes else -1

    def setCurrentIndex(self, i):
        if 0 <= i < len(self.modes):
            self.set_mode(self.modes[i])


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


class ChannelListDrop(QListWidget):
    """The Streams list: dropping an .m3u channel list here saves it (#44)."""
    lists_dropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DropOnly)

    def _lists(self, e):
        md = e.mimeData()
        if not md.hasUrls():
            return []
        return [u.toLocalFile() for u in md.urls()
                if u.isLocalFile() and os.path.splitext(u.toLocalFile())[1].lower() in (".m3u", ".m3u8")]

    def dragEnterEvent(self, e):
        e.acceptProposedAction() if self._lists(e) else e.ignore()

    def dragMoveEvent(self, e):
        e.acceptProposedAction() if self._lists(e) else e.ignore()

    def dropEvent(self, e):
        paths = self._lists(e)
        if paths:
            e.acceptProposedAction()
            self.lists_dropped.emit(paths)
        else:
            e.ignore()


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


def pick_media(parent, caption):
    """Files chosen in an Open window, in name order. Windows hands them over in the order they
    were selected, so a whole folder picked with Ctrl+A could land out of order (#58, like #43)."""
    picked, _ = QFileDialog.getOpenFileNames(parent, caption, "", media_filter())
    return sorted(picked, key=lambda p: natural_key(os.path.basename(p)))
