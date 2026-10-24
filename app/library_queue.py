"""Library panel: the queue under the tabs, its menu, shuffle and the queue mode button."""
import random

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QInputDialog, QListWidgetItem, QMenu

from . import theme
from .icons import icon
from .library_widgets import ROLE_PATH, pick_media, reveal
from .store import QUEUE_MODES
from .util import display_name, is_audio, is_url, pretty_title


class QueueMixin:
    # ================================================================ queue
    def refresh_queue(self):
        # Rebuilding the list jumps it to the top. Keep the scroll position, and only
        # bring the playing item into view when a different one starts (#50).
        bar = self.queue.verticalScrollBar()
        keep = bar.value()
        moved = self.win.qindex != getattr(self, "_queue_shown_index", None)
        self._queue_shown_index = self.win.qindex
        self.queue.clear()
        for i, item in enumerate(self.win.queue):
            p = item["path"]
            playing = i == self.win.qindex
            watched = not is_url(p) and self.store.position(p).get("watched")
            title = item.get("title") or display_name(p)
            if self.store.setting("simple_queue_names") and not is_url(p) and not is_audio(p):
                title = pretty_title(p)
            it = QListWidgetItem(title)
            it.setIcon(icon("play" if playing else ("stream" if is_url(p) else ("check" if watched else "drag")),
                            theme.accent() if playing else theme.FAINT, 16))
            if watched and not playing:
                it.setForeground(QColor(theme.MUTED))
            if playing:
                f = it.font()
                f.setBold(True)
                it.setFont(f)
            it.setData(ROLE_PATH, p)
            it.setToolTip(p)
            self.queue.addItem(it)
        n = len(self.win.queue)
        self.queue_count.setText(f"{n} item{'s' if n != 1 else ''}" if n else "")
        self.queue_search.setVisible(n > 8 or bool(self.queue_search.text()))
        self._filter_queue()
        if moved and 0 <= self.win.qindex < self.queue.count() and not self.queue.item(self.win.qindex).isHidden():
            self.queue.scrollToItem(self.queue.item(self.win.qindex))
        else:
            bar.setValue(keep)

    def _filter_queue(self):
        """Search the queue by name (#44); the order and numbering stay the same."""
        text = self.queue_search.text().strip().casefold() if hasattr(self, "queue_search") else ""
        for i in range(self.queue.count()):
            it = self.queue.item(i)
            hay = (it.text() + " " + (it.data(ROLE_PATH) or "")).casefold()
            it.setHidden(bool(text) and text not in hay)

    def _queue_drop(self, paths, row):
        self.win.insert_into_queue(paths, row)

    def _queue_reordered(self, order):
        self.win.reorder_queue(order)

    def _queue_rows(self, it=None):
        """Rows the menu acts on: the selection if the clicked item is part of it, else just that item."""
        if it is not None and not it.isSelected():
            return [self.queue.row(it)]
        return sorted(self.queue.row(i) for i in self.queue.selectedItems())

    def _queue_menu(self, pos):
        it = self.queue.itemAt(pos)
        m = QMenu(self)
        if it:
            rows = self._queue_rows(it)
            n = len(rows)
            files = [self.win.queue[r]["path"] for r in rows
                     if 0 <= r < len(self.win.queue) and not is_url(self.win.queue[r]["path"])]
            if n == 1:
                m.addAction(icon("play", theme.TEXT, 16), "Play", lambda: self.win.play_queue_index(self.queue.row(it)))
            if files:
                seen = [f for f in files if self.store.position(f).get("watched")]
                unseen = [f for f in files if f not in seen]
                if unseen:
                    m.addAction(icon("check_all", theme.TEXT, 16),
                                f"Mark as watched ({len(unseen)})" if n > 1 else "Mark as watched",
                                lambda: self._mark_queue(unseen, True))
                if seen:
                    m.addAction(f"Mark as unwatched ({len(seen)})" if n > 1 else "Mark as unwatched",
                                lambda: self._mark_queue(seen, False))
            m.addAction(icon("trash", theme.TEXT, 16),
                        f"Remove {n} from queue\tDel" if n > 1 else "Remove from queue\tDel",
                        lambda: self.win.remove_from_queue(rows))
            p = it.data(ROLE_PATH)
            if n == 1 and not is_url(p):
                m.addAction("Show in Explorer", lambda: reveal(p))
            if n == 1 and is_url(p):
                m.addAction("Copy link", lambda: self._copy_link(p))
            m.addSeparator()
        if self.queue.count() > 1:
            m.addAction("Select all\tCtrl+A", self.queue.selectAll)
        m.addAction("Add files…", self._add_files_to_queue)
        if self.queue.count() > 1:
            m.addAction(icon("sort", theme.TEXT, 16), "Sort by name", self.win.sort_queue_by_name)
        m.addAction("Clear queue", lambda: self.win.set_queue([], -1))
        m.exec(self.queue.mapToGlobal(pos))

    def _mark_queue(self, files, watched):
        for f in files:
            self.store.set_watched(f, watched)
        n = len(files)
        what = f"{n} items" if n > 1 else f"“{display_name(files[0])}”"
        self.win.toast(f"Marked {what} as {'watched' if watched else 'unwatched'}")
        self.refresh_queue()
        if self.win.home.isVisible():
            self.win.home.refresh()

    def _queue_delete_key(self):
        rows = self._queue_rows()
        if rows:
            self.win.remove_from_queue(rows)

    def _add_files_to_queue(self):
        picked = pick_media(self, "Add to queue")
        if picked:
            self.win.enqueue(picked)

    @property
    def shuffled(self) -> bool:
        return self._unshuffled is not None

    def shuffle_on(self):
        """Mix up everything except what's playing, remembering the original order."""
        win = self.win
        q = win.queue
        cur = q[win.qindex] if 0 <= win.qindex < len(q) else None
        self._unshuffled = list(q)
        rest = [x for x in q if x is not cur]
        random.shuffle(rest)
        self._reorder(([cur] if cur else []) + rest, cur)

    def shuffle_off(self):
        """Put the original order back. Anything added while shuffled goes after it."""
        if not self.shuffled:
            return
        q = self.win.queue
        cur = q[self.win.qindex] if 0 <= self.win.qindex < len(q) else None
        ids = {id(x) for x in q}
        new = [x for x in self._unshuffled if id(x) in ids]
        kept = {id(x) for x in new}
        new += [x for x in q if id(x) not in kept]
        self._unshuffled = None
        self._reorder(new, cur)

    def _reorder(self, new, cur):
        win = self.win
        win.queue = new
        win.qindex = next((i for i, x in enumerate(new) if x is cur), -1)
        self.refresh_queue()

    def reset_shuffle(self):
        """A brand-new queue (a folder, a playlist, Clear) forgets the order from before."""
        self._unshuffled = None

    def _mode_color(self):
        return theme.MUTED if self.win.queue_mode == "none" else theme.accent()

    def show_queue_mode(self, mode):
        """The queue button shows the current mode: grey when it stops, accent colour otherwise (#48)."""
        name, what, ic = QUEUE_MODES[mode]
        order = list(QUEUE_MODES)
        after = QUEUE_MODES[order[(order.index(mode) + 1) % len(order)]][0]
        self.mode_btn.setToolTip(f"{what}. Click for {after}")
        self.mode_btn.set_icon(ic)

    def _save_queue_as_playlist(self):
        q = self.win.queue
        if not q:
            return
        if len(q) > 1 and all(is_url(x["path"]) for x in q):
            # a list of channels: keep it in Streams with its names, or as a normal playlist (#44)
            choices = ["Save to Streams as a channel list", "Save as a playlist"]
            choice, ok = QInputDialog.getItem(self, "Save the queue", "These are all streams.", choices, 0, False)
            if not ok:
                return
            if choice == choices[0]:
                name, ok = QInputDialog.getText(self, "Save to Streams", "Name", text="Channels")
                if ok and name.strip():
                    self.save_channel_list(q, name.strip())
                return
        self.save_to_playlist([x["path"] for x in q])
