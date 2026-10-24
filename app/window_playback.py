"""Main window: opening things, the queue, playing a file and what happens when it ends."""
import os
import time

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from . import APP_NAME
from .dialogs import StreamDialog, SubtitleDialog
from .engine import MAX_SHARPEN
from .library import media_filter
from .stage import PAGE_AUDIO, PAGE_HOME, PAGE_VIDEO
from .util import (SUB_EXTS, PLAYLIST_EXTS, display_name, norm, find_subtitle_candidates, is_disc, is_dvd_folder,
                   fmt_time, is_audio, is_media, is_url, list_media, match_subtitle, merge_in_name_order, natural_key,
                   sort_key_by_name, parse_m3u)


class PlaybackMixin:
    # ================================================================ opening
    def open_file_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Open", "", media_filter())
        if not files:
            return
        if len(files) == 1 and os.path.splitext(files[0])[1].lower() in PLAYLIST_EXTS:
            self.open_playlist_file(files[0])
        elif len(files) == 1:
            self.play_from_folder(files[0])
        else:
            files.sort(key=lambda p: natural_key(os.path.basename(p)))
            self.set_queue([{"path": f} for f in files], 0)

    def open_folder_dialog(self):
        d = QFileDialog.getExistingDirectory(self, "Open folder")
        if d:
            self.play_folder(os.path.normpath(d))

    def open_stream_dialog(self):
        d = StreamDialog(self)
        if d.exec() and d.url.text().strip():
            url = d.url.text().strip()
            name = d.name.text().strip() or display_name(url)
            if d.save.isChecked() and url not in [s["url"] for s in self.store.data["streams"]]:
                self.store.data["streams"].insert(0, {"name": name, "url": url})
                self.store.save("streams")
                self.library.refresh_streams()
            self.open_stream(url, name)

    def open_clipboard(self):
        text = QGuiApplication.clipboard().text().strip().strip('"')
        if not text:
            self.toast("Clipboard is empty")
        elif os.path.exists(text):
            self.play_folder(text) if os.path.isdir(text) else self.play_from_folder(text)
        elif "://" in text:
            self.open_stream(text)
        else:
            QMessageBox.information(self, "Clipboard", "The clipboard doesn't contain a link or a file path.")

    def open_stream(self, url: str, name: str = ""):
        low = url.lower().split("?")[0]
        if low.endswith((".m3u", ".m3u8")) and url.startswith("http"):
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                import urllib.request
                req = urllib.request.Request(url, headers={"User-Agent": "Pylon/1.0"})
                with urllib.request.urlopen(req, timeout=12) as r:
                    text = r.read(8_000_000).decode("utf-8", "replace")
                channels = parse_m3u(text)
            except Exception:
                channels = None
            finally:
                QApplication.restoreOverrideCursor()
            if channels:
                saved = self.library.stream_entry(url)
                if saved is not None and saved.get("count") != len(channels):
                    saved["count"] = len(channels)          # show the channel count in Streams (#44)
                    self.store.save("streams")
                    self.library.refresh_streams()
                self.set_queue([{"path": u, "title": n} for n, u in channels], 0)
                self.toggle_queue(True)
                self.toast(f"Loaded {len(channels)} channels into the queue")
                return
        self.set_queue([{"path": url, "title": name or display_name(url)}], 0)

    def open_playlist_file(self, path):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                items = parse_m3u(f.read()) or []
        except OSError:
            items = []
        base = os.path.dirname(path)
        q = []
        for n, p in items:
            if not is_url(p) and not os.path.isabs(p):
                p = os.path.normpath(os.path.join(base, p))
            q.append({"path": p, "title": n})
        if q:
            self.set_queue(q, 0)
            if len(q) > 1 and all(is_url(x["path"]) for x in q):
                self.toggle_queue(True)
                QTimer.singleShot(400, lambda: self.toast(
                    f"Loaded {len(q)} channels. To keep them, drop the file on the Streams tab"))
        else:
            self.set_queue([{"path": path}], 0)

    def play_saved_stream(self, url):
        """Play something saved in Streams: a channel list goes into the queue (#44)."""
        s = self.library.stream_entry(url)
        if s is None:
            self.open_stream(url)
        elif s.get("channels"):
            self.set_queue([{"path": c["url"], "title": c["name"]} for c in s["channels"]], 0)
            self.toggle_queue(True)
            self.toast(f"{s['name']}: {len(s['channels'])} channels")
        else:
            self.open_stream(s["url"], s["name"])

    def enqueue_items(self, items):
        """Add queue entries that keep their names, like channels from a list."""
        if not items:
            return
        self.queue.extend(dict(x) for x in items)
        self.library.refresh_queue()
        self.toast(f"Added {len(items)} to the queue")
        if not self.engine.current:
            self.play_queue_index(len(self.queue) - len(items))

    def play_folder(self, folder):
        folder = norm(folder)
        if is_dvd_folder(folder):          # a copied DVD plays as a disc, with its menu
            self.set_queue([{"path": folder}], 0)
            return
        files = list_media(folder)
        if not files:
            self.browse_folder(folder)
            self.toast("No media files directly in that folder")
            return
        self.set_queue([{"path": f} for f in files], 0)

    def play_playlist(self, name):
        items = self.store.data["playlists"].get(name, [])
        if not items:
            return
        # pick up where you left off: the first item you haven't finished
        start = next((i for i, p in enumerate(items)
                      if is_url(p) or not self.store.position(norm(p)).get("watched")), 0)
        self.set_queue([{"path": p} for p in items], start)
        self.toggle_queue(True)
        if start > 0:
            QTimer.singleShot(500, lambda: self.toast(f"Continuing “{name}” at item {start + 1} of {len(items)}"))

    def play_from_folder(self, path, start_ms=None):
        """Play a file and queue the rest of its folder so the next episode is ready."""
        path = norm(path)
        if is_url(path):
            self.open_stream(path)
            return
        if not os.path.exists(path):
            QMessageBox.warning(self, "File not found", f"Can't find:\n{path}")
            return
        if os.path.isdir(path):
            self.play_folder(path)
            return
        for i, q in enumerate(self.queue):
            if os.path.normcase(q["path"]) == os.path.normcase(path):
                self.play_queue_index(i, start_ms=start_ms)
                return
        files = list_media(os.path.dirname(path)) if self.store.setting("binge") else [path]
        if path not in files:
            files = [path]
        self.queue = [{"path": f} for f in files]
        self.library.reset_shuffle()
        self.qindex = files.index(path)
        if self.queue_mode == "shuffle":
            self.library.shuffle_on()
        self.play_queue_index(self.qindex, start_ms=start_ms)

    # ---------------------------------------------------------------- queue
    def set_queue(self, items, index, keep_playing=False):
        self.queue = [{**it, "path": norm(it["path"])} for it in items]
        self.library.reset_shuffle()
        self.qindex = index if 0 <= index < len(self.queue) else -1
        if self.queue_mode == "shuffle":
            self.library.shuffle_on()
        self.library.refresh_queue()
        if not keep_playing and self.qindex >= 0:
            self.play_queue_index(self.qindex)

    def enqueue(self, paths, play_next=False):
        items = [{"path": norm(p)} for p in paths if p]
        if not items:
            return
        if play_next and self.qindex >= 0:
            self.queue[self.qindex + 1:self.qindex + 1] = items
        else:
            # an episode joins the others from its folder in name order, not the end of the queue (#57)
            cur = self.queue[self.qindex] if 0 <= self.qindex < len(self.queue) else None
            self.queue = merge_in_name_order(self.queue, items, lambda q: q["path"])
            if cur is not None:
                self.qindex = next(i for i, q in enumerate(self.queue) if q is cur)
            if self.library.shuffled:      # so leaving Shuffle puts it in its place too
                self.library._unshuffled = merge_in_name_order(self.library._unshuffled, items,
                                                               lambda q: q["path"])
        self.library.refresh_queue()
        self.toast(f"Added {len(items)} to the queue" if len(items) > 1 else f"Added “{display_name(items[0]['path'])}” to the queue")
        if not self.engine.current:
            self.play_queue_index(max(0, self.qindex + 1) if play_next and self.qindex >= 0
                                  else next(i for i, q in enumerate(self.queue) if q is items[0]))

    def sort_queue_by_name(self):
        """Put the whole queue in name order (#57); what's playing keeps playing."""
        if len(self.queue) < 2:
            return
        if self.queue_mode == "shuffle":      # a sorted queue isn't a shuffled one
            self.set_queue_mode("next", announce=False)
        cur = self.queue[self.qindex] if 0 <= self.qindex < len(self.queue) else None
        self.queue.sort(key=lambda q: sort_key_by_name(q["path"], q.get("title", "")))
        if cur is not None:
            self.qindex = next(i for i, q in enumerate(self.queue) if q is cur)
        self.library.refresh_queue()
        self.toast("Queue sorted by name")

    def insert_into_queue(self, paths, row):
        items = [{"path": norm(p)} for p in paths if p and (is_url(p) or is_media(p) or
                                                      os.path.splitext(p)[1].lower() in PLAYLIST_EXTS)]
        if not items:
            return
        row = max(0, min(row, len(self.queue)))
        self.queue[row:row] = items
        if self.qindex >= row:
            self.qindex += len(items)
        self.library.refresh_queue()
        if not self.engine.current:
            self.play_queue_index(row)

    def reorder_queue(self, order):
        cur = self.queue[self.qindex]["path"] if 0 <= self.qindex < len(self.queue) else None
        by_path = {}
        for q in self.queue:
            by_path.setdefault(q["path"], []).append(q)
        new = []
        for p in order:
            lst = by_path.get(p)
            if lst:
                new.append(lst.pop(0))
        self.queue = new
        self.qindex = next((i for i, q in enumerate(new) if q["path"] == cur), -1)
        self.library.refresh_queue()

    def remove_from_queue(self, rows):
        cur = self.queue[self.qindex] if 0 <= self.qindex < len(self.queue) else None
        self.queue = [q for i, q in enumerate(self.queue) if i not in set(rows)]
        self.qindex = next((i for i, q in enumerate(self.queue) if q is cur), -1)
        self.library.refresh_queue()

    def play_queue_index(self, i, start_ms=None):
        if not (0 <= i < len(self.queue)):
            return
        self.qindex = i
        item = self.queue[i]
        self.play_path(item["path"], start_ms=start_ms, title=item.get("title", ""))
        self.library.refresh_queue()

    def play_next(self, user=False):
        if self.qindex + 1 < len(self.queue):
            self.play_queue_index(self.qindex + 1)
            return True
        if self.store.setting("repeat_queue") and self.queue:
            self.play_queue_index(0)
            return True
        cur = self.engine.current
        if cur and not is_url(cur) and (self.store.setting("binge") or user):
            files = list_media(os.path.dirname(cur))
            try:
                idx = files.index(cur)
            except ValueError:
                idx = -1
            if 0 <= idx < len(files) - 1:
                nxt = files[idx + 1]
                self.queue.append({"path": nxt})
                self.play_queue_index(len(self.queue) - 1)
                return True
        if user:
            self.toast("End of the queue")
        return False

    def play_prev(self):
        if self.engine.time() > 3000:
            self.engine.seek(0)
            self.toast("Back to the start")
            return
        if self.qindex > 0:
            self.play_queue_index(self.qindex - 1)
            return
        cur = self.engine.current
        if cur and not is_url(cur):
            files = list_media(os.path.dirname(cur))
            if cur in files and files.index(cur) > 0:
                prev = files[files.index(cur) - 1]
                self.queue.insert(0, {"path": prev})
                self.play_queue_index(0)

    # ---------------------------------------------------------------- playing
    def play_path(self, path, start_ms=None, title=""):
        path = norm(path)
        if not self.engine.ok:
            self._vlc_missing()
            return
        self._save_position()
        e = self.engine
        self._resume_until = 0.0
        self._resume_ms = 0
        self._resume_title = None
        self.bottom.resume.hide()
        if self.thumbs.path != path:
            self.thumbs.cancel()
        if e.current != path:
            self.ab_loop = [None, None]          # a repeat belongs to one file
            self._show_ab()
        if self.waves.path != path:
            self.waves.cancel()
            self.bottom.seek.set_wave([])
        disc = is_disc(path)

        # where to start
        if start_ms is None:
            start_ms = 0
            pos = self.store.position(path)
            ln, p = pos.get("len", 0), pos.get("pos", 0)
            if ln and 10_000 < p < ln * 0.93 and not pos.get("watched"):
                mode = self.store.setting("resume")
                if disc:
                    # a disc opens at its menu; its title and time are picked up once it plays
                    self._resume_title = pos.get("title")
                    if mode == "always" and self._resume_title is not None:
                        QTimer.singleShot(1500, lambda t=self._resume_title, ms=p: self._resume_disc(t, ms))
                    elif mode == "ask":
                        self._resume_ms = p
                elif mode == "always":
                    start_ms = p
                elif mode == "ask":
                    self._resume_ms = p

        # per-show preset, or a clean slate for timing
        folder = None if is_url(path) else os.path.dirname(path)
        name, preset = self.store.preset_for_folder(folder) if folder else (None, None)
        e.live["sub_delay"] = 0
        e.live["audio_delay"] = 0
        self._track_prefs = ("", "")
        if preset:
            self.apply_preset(preset, live=False)

        # subtitles we know about
        subs = []
        if not is_url(path) and not disc:
            mapped = self.store.data["sub_map"].get(path)
            if mapped and os.path.exists(mapped):
                subs.append(mapped)
            else:
                level = self.store.setting("sub_match")
                if level != "off":
                    best = match_subtitle(path, find_subtitle_candidates(path), level)
                    # VLC already loads same-name files next to the video by itself
                    if best and not (os.path.dirname(best) == os.path.dirname(path)
                                     and os.path.splitext(os.path.basename(best))[0] == os.path.splitext(os.path.basename(path))[0]):
                        subs.append(best)

        self._prefs_applied = False
        self._live_applied = False
        audio = is_audio(path)
        self.stage.setCurrentIndex(PAGE_AUDIO if audio else PAGE_VIDEO)
        self._overlay_geo = None
        e.open(path, start_ms=start_ms, subs=subs, title=title)
        self.store.add_recent(path)
        self.store.count_play(path)
        self._in_menu = False

        shown = title or display_name(path)
        self.top.set_title(shown)
        self.setWindowTitle(f"{shown}  ·  {APP_NAME}")
        self.top.set_folder(os.path.basename(folder) if folder else ("Stream" if is_url(path) else ""))
        self.bottom.set_time(start_ms, 0)
        if audio:
            self.now_playing.load(path, {})
        if self._resume_ms:
            self.bottom.resume.setText(f"Continue from {fmt_time(self._resume_ms)}")
            self._resume_until = time.monotonic() + 8
            self.bottom.resume.setVisible(self.stage.width() >= 900)
            self._poke(8)
            QTimer.singleShot(8000, self.bottom.resume.hide)
        else:
            self._poke(2)
        if preset:
            QTimer.singleShot(400, lambda: self.toast(f"Preset: {name}"))
        if self.library.isVisible():
            self.library.refresh_library()

    def _accept_resume(self):
        if self._resume_ms and getattr(self, "_resume_title", None) is not None:
            self._resume_disc(self._resume_title, self._resume_ms)
        elif self._resume_ms:
            self.engine.seek(self._resume_ms)
            self.toast(f"Continuing from {fmt_time(self._resume_ms)}")
        self._resume_until = 0.0
        self._resume_ms = 0
        self.bottom.resume.hide()

    def _resume_disc(self, title, ms):
        """Go back to the title you were watching on a disc, then to where you stopped in it."""
        e = self.engine
        if not e.is_disc():
            return
        e.set_title(int(title))
        QTimer.singleShot(800, lambda: e.seek(ms))

        def check():   # a jump made while a disc title is still starting can be lost; try once more
            if e.is_disc() and e.title() == int(title) and e.time() < ms - 3000:
                e.seek(ms)
        QTimer.singleShot(1800, check)
        self.toast(f"Continuing from {fmt_time(ms)}")

    def apply_preset(self, p: dict, live: bool):
        e = self.engine
        for k in ("sub_delay", "audio_delay", "rate", "eq", "aspect", "crop", "zoom", "adjust", "deinterlace"):
            if k in p:
                e.live[k] = p[k]
        if "eq_custom" in p:
            e.live["eq_custom"] = e.clean_curve(p["eq_custom"])
        style = p.get("sub_style")
        needs_new_player = bool(style) and style != e.sub_style
        if needs_new_player:
            e.sub_style = dict(style)
        # sharpen is a VLC filter, so a change needs a fresh player too
        if "sharpen" in p:
            try:
                sharpen = max(0.0, min(MAX_SHARPEN, float(p.get("sharpen") or 0)))
            except (TypeError, ValueError):
                sharpen = 0.0
            if abs(sharpen - e.sharpen) > 0.01:
                e.sharpen = sharpen
                needs_new_player = True
        self._track_prefs = (p.get("sub_track", ""), p.get("audio_track", ""))
        self.bottom.set_speed(e.live["rate"])
        self.sidebar.sync_from_engine()
        if live:
            if needs_new_player and e.current:
                e.rebuild()
            else:
                e.apply_live()
            self._apply_track_prefs()
        elif needs_new_player:
            e.recreate()

    def _apply_track_prefs(self):
        e = self.engine
        sub_name, audio_name = self._track_prefs
        sub_lang = self.store.setting("sub_lang") or ""
        audio_lang = self.store.setting("audio_lang") or ""

        def pick(tracks, exact, lang):
            real = [(t, n) for t, n in tracks if t != -1]
            if exact:
                for t, n in real:
                    if n == exact:
                        return t
            if lang:
                low = lang.lower()
                for t, n in real:
                    if low in n.lower():
                        return t
            return None

        if sub_name == "off" or (not sub_name and sub_lang.lower() == "off"):
            e.set_sub(-1)
        else:
            # an external file we added wins over language guessing
            if not (e.extra_subs and not sub_name):
                t = pick(e.sub_tracks(), sub_name, sub_lang)
                if t is not None:
                    e.set_sub(t)
        t = pick(e.audio_tracks(), audio_name, audio_lang)
        if t is not None:
            e.set_audio(t)
        self.sidebar.refresh_tracks()

    def _on_tracks(self):
        if not self._prefs_applied and self.engine.state() == "playing":
            self._prefs_applied = True
            QTimer.singleShot(350, self._apply_track_prefs)
        QTimer.singleShot(120, self._refresh_after_tracks)

    def _refresh_after_tracks(self):
        if self.sidebar.isVisible():
            self.sidebar.refresh_tracks()

    def _on_state(self, state):
        e = self.engine
        self.bottom.set_playing(state == "playing")
        if state == "playing":
            if not self._live_applied:
                self._live_applied = True
                e.apply_live()
                self.sidebar.sync_from_engine()
                QTimer.singleShot(900, self._after_start)
            if not self._prefs_applied:
                self._prefs_applied = True
                QTimer.singleShot(600, self._apply_track_prefs)
        elif state == "paused":
            self._save_position()
            self._poke(0.5)
        elif state == "ended":
            self._on_ended()
        elif state == "error":
            if e.current and is_url(e.current):
                # A dead channel shouldn't jump to the next one (#50): stay put so the
                # list doesn't move, and let the user pick another stream.
                self.toast("Couldn't play this stream")
            else:
                self.toast("Couldn't play this file")
                if self.queue_mode in ("next", "shuffle"):
                    QTimer.singleShot(1500, lambda: self.play_next() if self.qindex + 1 < len(self.queue) else None)

    # ---------------------------------------------------------------- seek previews
    def start_previews(self, tries=0):
        e = self.engine
        if not self.store.setting("seek_previews") or not e.current or is_url(e.current) or is_disc(e.current):
            return
        if self.thumbs.path == e.current:
            return
        if e.length() <= 0 and tries < 5:      # length not known yet
            QTimer.singleShot(1000, lambda: self.start_previews(tries + 1))
            return
        self.thumbs.start(e.current, e.length(), e.video_size())

    def _seek_hover(self, ms, x):
        seek = self.bottom.seek
        g = seek.mapToGlobal(QPoint(int(x), 0))
        img = None
        if self.store.setting("seek_previews") and self.thumbs.path == self.engine.current:
            img, captured_ms = self.thumbs.preview_at(ms)
            if captured_ms is not None:
                ms = captured_ms
        left = self.mapToGlobal(QPoint(0, 0)).x()
        line_top = g.y() + seek.height() - 10     # the visible bar sits at the bottom of the widget
        self.seek_preview.show_at(g.x(), line_top - 5, ms, img, left + 8, left + self.width() - 8)

    def _after_start(self):
        e = self.engine
        if e.current and self.stage.currentIndex() != PAGE_HOME:
            has_video = e.has_video()
            if not has_video:
                self.now_playing.load(e.current, e.meta())
                self.stage.setCurrentIndex(PAGE_AUDIO)
            elif self.stage.currentIndex() == PAGE_AUDIO:
                self.stage.setCurrentIndex(PAGE_VIDEO)
            if has_video:
                self.start_previews()
            self.start_waveform()
            meta_title = e.meta().get("now_playing") or ""
            if meta_title and is_url(e.current):
                self.top.set_title(f"{e.current_title or display_name(e.current)}  ·  {meta_title}")
        self.sidebar.refresh_tracks()

    def _on_ended(self):
        e = self.engine
        if e.current:
            ln = e.length()
            self.store.set_position(e.current, ln, ln)
            self.store.set_watched(e.current, True)
        if self._sleep_end_of_file:
            self._sleep_end_of_file = False
            self.sidebar.sleep.select(0)
            self.sidebar.sleep_label.setText("")
            self.toast("Sleep timer: stopped at the end of the file")
            return
        if self.queue_mode == "loop" and e.current:
            self.play_queue_index(self.qindex) if self.qindex >= 0 else self.play_path(e.current, start_ms=0)
            return
        if self.queue_mode == "none" or not self.play_next():
            self.bottom.set_playing(False)
            self._poke(4)

    def _save_position(self):
        e = self.engine
        if e.current and not is_url(e.current):
            ln, t = e.length(), e.time()
            disc = e.is_disc()
            if disc and e.in_menu():
                return                        # a menu loop isn't a place to come back to
            if ln > 0 and t > 0:
                self.store.set_position(e.current, t, ln)
                if disc:
                    self.store.data["positions"][e.current]["title"] = e.title()

    def _time_tick(self):
        e = self.engine
        if not e.current:
            return
        if self._bars_visible or self.stage.currentIndex() == PAGE_AUDIO:
            self.bottom.set_time(e.time(), e.length())
        if self.sidebar.isVisible():
            self.sidebar.tick()
        if e.is_disc():
            self._disc_tick()
        now = time.monotonic()
        if e.is_playing() and now - self._last_saved > 5:
            self._last_saved = now
            self._save_position()
        if self._sleep_deadline:
            left = self._sleep_deadline - now
            if left <= 0:
                self._sleep_deadline = None
                e.pause()
                self.sidebar.sleep.select(0)
                self.sidebar.sleep_label.setText("")
                self.toast("Sleep timer: paused")
            else:
                self.sidebar.sleep_label.setText(f"Pausing in {fmt_time(left * 1000)}")

    # ================================================================ subtitles
    def open_subtitle_dialog(self, scope=None, folder=None):
        if scope is None:
            scope = "file" if self.engine.current and not is_url(self.engine.current) else "folder"
        SubtitleDialog(self, scope=scope, folder=folder).exec()

    # ================================================================ drag and drop
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasText():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = []
        for u in e.mimeData().urls():
            paths.append(u.toLocalFile() if u.isLocalFile() else u.toString())
        if not paths and e.mimeData().hasText():
            paths = [e.mimeData().text().strip()]
        self.open_paths(paths)

    def open_paths(self, paths):
        paths = [norm(p) for p in paths if p]
        # only things Pylon can actually play: media, playlists, subtitles, folders, links
        ok_ext = SUB_EXTS | PLAYLIST_EXTS
        paths = [p for p in paths if is_url(p) or os.path.isdir(p) or is_media(p)
                 or os.path.splitext(p)[1].lower() in ok_ext]
        if not paths:
            return
        subs = [p for p in paths if os.path.splitext(p)[1].lower() in SUB_EXTS]
        if subs and len(subs) == len(paths):
            if self.engine.current and len(subs) == 1:
                self.engine.add_subtitle(subs[0])
                if not is_url(self.engine.current):
                    self.store.data["sub_map"][self.engine.current] = subs[0]
                    self.store.save()
                self.sidebar.load_cues()
                self.toast(f"Subtitles: {os.path.basename(subs[0])}")
            else:
                self.open_subtitle_dialog(scope="folder")
            return
        if len(paths) == 1:
            p = paths[0]
            if os.path.isdir(p):
                self.play_folder(p)
            elif os.path.splitext(p)[1].lower() in PLAYLIST_EXTS:
                self.open_playlist_file(p)
            elif is_url(p):
                self.open_stream(p)
            else:
                self.play_from_folder(p)
            return
        if not any(is_url(p) for p in paths):
            # Windows hands dropped or "Open with" files over in selection order,
            # so episodes could land out of order (#43). Sort them like a folder.
            paths.sort(key=lambda p: natural_key(os.path.basename(p)))
        files = []
        for p in paths:
            files.extend(list_media(p) if os.path.isdir(p) else [p])
        files = [f for f in files if is_url(f) or is_media(f)]
        if self.engine.current and self.engine.is_playing():
            self.enqueue(files)
        else:
            self.set_queue([{"path": f} for f in files], 0)
