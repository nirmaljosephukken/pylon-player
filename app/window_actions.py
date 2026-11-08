"""The window's named actions: what each shortcut, menu entry and button does, and the message it shows.
`do(action)` looks the action up in one table; the shortcut editor's list of actions is the same table."""
import os
import time

from PySide6.QtCore import QStandardPaths, Qt
from PySide6.QtWidgets import QAbstractItemView, QApplication, QLineEdit

from . import APP_NAME
from .engine import NAV_ACTIVATE, NAV_DOWN, NAV_LEFT, NAV_RIGHT, NAV_UP
from .sidebar import KeySlider
from .stage import PAGE_HOME
from .util import SPEED_STEPS, fmt_delay, fmt_time, short_path


def snapshot_dir() -> str:
    """Pylon's folder in the system's Pictures folder (made if missing)."""
    pictures = (QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
                or os.path.join(os.path.expanduser("~"), "Pictures"))
    folder = os.path.join(pictures, APP_NAME)
    os.makedirs(folder, exist_ok=True)
    return folder



class ActionsMixin:
    def _cycle_chip(self, chips, live_key, setter, what):
        """Step to the next choice in the settings panel's row for this (aspect ratio or crop, #56)."""
        values = chips.values
        cur = self.engine.live.get(live_key, "")
        i = (values.index(cur) + 1) % len(values) if cur in values else 1 % len(values)
        setter(values[i])
        chips.select(values[i])
        return f"{what}: {chips.group.button(i).text()}"

    # keys that move around a disc menu instead of seeking and changing the volume
    MENU_KEYS = {"seek_back": NAV_LEFT, "seek_fwd": NAV_RIGHT, "vol_up": NAV_UP, "vol_down": NAV_DOWN,
                 "play_pause": NAV_ACTIVATE, "fullscreen_enter": NAV_ACTIVATE}

    def do(self, action: str, key: bool = True):
        """Run a named action (a shortcut, a menu entry, a button) and show what it did."""
        e = self.engine
        if action in self.MENU_KEYS and e.in_menu() and not self._typing(action):
            e.navigate(self.MENU_KEYS[action])
            self._poke(1)
            return
        handler = self._actions().get(action)
        msg = handler(action) if handler else None
        if msg:
            hint = self.store.shortcut(action) if key and self.store.setting("osd_shortcuts") else ""
            self.toast(msg, hint)

    def _actions(self):
        """Each action's handler. A handler gets the action's name and returns the message to show, if any."""
        if self._action_table is None:
            self._action_table = self._build_actions()
        return self._action_table

    def _build_actions(self):
        def quiet(fn):                   # does the thing and shows no message
            return lambda _a: (fn(), None)[1]
        return {
            "play_pause": self._act_play_pause,
            "stop": self._act_stop,
            "close_media": quiet(self.close_media),
            "seek_fwd": self._act_seek, "seek_back": self._act_seek,
            "seek_fwd_long": self._act_seek, "seek_back_long": self._act_seek,
            "frame_next": self._act_frame_next,
            "frame_prev": self._act_frame_prev,
            "ab_loop": lambda _a: self.ab_step(),
            "vol_up": self._act_volume, "vol_down": self._act_volume,
            "mute": self._act_mute,
            "next": quiet(lambda: self.play_next(user=True)),
            "prev": quiet(self.play_prev),
            "fullscreen": quiet(self.toggle_fullscreen),
            "fullscreen_enter": quiet(self._act_enter),
            "exit_fullscreen": quiet(self._act_escape),
            "pip": quiet(self.toggle_pip),
            "hide_ui": self._act_hide_ui,
            "speed_up": self._act_speed, "speed_down": self._act_speed, "speed_reset": self._act_speed,
            "sub_delay_plus": self._act_sub_delay, "sub_delay_minus": self._act_sub_delay,
            "audio_delay_plus": self._act_audio_delay, "audio_delay_minus": self._act_audio_delay,
            "cycle_sub": lambda _a: self._cycle(self.engine.sub_tracks(), self.engine.current_sub(),
                                                self.engine.set_sub, "Subtitles"),
            "cycle_audio": lambda _a: self._cycle(self.engine.audio_tracks(), self.engine.current_audio(),
                                                  self.engine.set_audio, "Audio"),
            "cycle_aspect": self._act_cycle_chip, "cycle_crop": self._act_cycle_chip,
            "bookmark": self._act_bookmark,
            "library": quiet(self.toggle_library),
            "sidebar": quiet(self.toggle_sidebar),
            "queue": quiet(self.toggle_queue),
            "panels": quiet(self.toggle_panels),
            "zoom_in": quiet(lambda: self.zoom_video(1.25)),
            "zoom_out": quiet(lambda: self.zoom_video(0.8)),
            "zoom_reset": quiet(self.reset_zoom),
            "open_file": quiet(self.open_file_dialog),
            "open_folder": quiet(self.open_folder_dialog),
            "open_stream": quiet(self.open_stream_dialog),
            "snapshot": lambda _a: self.take_snapshot(),
            "shortcuts": quiet(self.show_shortcuts),
            "preferences": quiet(self.show_preferences),
        }

    def _act_play_pause(self, _a):
        e = self.engine
        if not e.current:
            if self.queue:
                self.play_queue_index(max(0, self.qindex))
            else:
                self.open_file_dialog()
            return None
        playing = e.is_playing()
        e.toggle()
        self._poke(1.5)
        return "Paused" if playing else "Playing"

    def _act_stop(self, _a):
        self._save_position()
        self.engine.stop()
        return "Stopped"

    def _act_seek(self, action):
        e = self.engine
        delta = {"seek_fwd": 10_000, "seek_back": -10_000, "seek_fwd_long": 60_000, "seek_back_long": -60_000}[action]
        e.seek_by(delta)
        self.bottom.set_time(max(0, e.time() + delta), e.length())
        return f"{'+' if delta > 0 else '-'}{abs(delta) // 1000}s   {fmt_time(max(0, e.time() + delta))}"

    def _act_frame_next(self, _a):
        self.engine.next_frame()
        return "Next frame"

    def _act_frame_prev(self, _a):
        e = self.engine
        if not e.current:
            return None
        if e.is_disc():
            # DVDs can only jump to about every half second, so a frame back isn't possible there
            return "Stepping back a frame doesn't work on DVDs"
        e.prev_frame()
        self.bottom.set_playing(False)
        return "Previous frame"

    def _act_volume(self, action):
        e = self.engine
        e.set_volume(e.volume() + (5 if action == "vol_up" else -5))
        e.set_muted(False)
        self.bottom.set_volume(e.volume(), False)
        return f"Volume {e.volume()}%"

    def _act_mute(self, _a):
        e = self.engine
        m = not e.is_muted()
        e.set_muted(m)
        self.bottom.set_volume(e.volume(), m)
        return "Muted" if m else f"Volume {e.volume()}%"

    def _act_enter(self):
        # Enter still works normally while typing or picking from a list
        fw = QApplication.focusWidget()
        if isinstance(fw, QLineEdit):
            fw.returnPressed.emit()
            return
        if isinstance(fw, QAbstractItemView) and fw.currentIndex().isValid():
            item_fn = getattr(fw, "itemDoubleClicked", None)
            if item_fn is not None and hasattr(fw, "currentItem") and fw.currentItem() is not None:
                item_fn.emit(fw.currentItem())
                return
        if self.stage.currentIndex() != PAGE_HOME:
            self.toggle_fullscreen()

    def _act_escape(self):
        self._drop_slider_focus()          # Esc gives the arrow keys back to the video too (#79)
        if self._pip:
            self.toggle_pip()
        elif self.isFullScreen():
            self.toggle_fullscreen()
        elif self.hide_ui:
            self.do("hide_ui")

    def _act_hide_ui(self, _a):
        self.hide_ui = not self.hide_ui
        if self.hide_ui:
            self._set_bars(False)
            self.toggle_library(False)
            self.toggle_sidebar(False)
        return "Interface hidden" if self.hide_ui else "Interface shown"

    def _act_speed(self, action):
        steps, r = SPEED_STEPS, self.engine.rate()
        if action == "speed_reset":
            r = 1.0
        elif action == "speed_up":
            r = next((s for s in steps if s > r + 1e-6), steps[-1])
        else:
            r = next((s for s in reversed(steps) if s < r - 1e-6), steps[0])
        self.set_rate(r, osd=False)
        return f"Speed {r:g}x"

    def _act_sub_delay(self, action):
        e = self.engine
        d = e.live["sub_delay"] + (50 if action == "sub_delay_plus" else -50)
        e.set_sub_delay(d)
        self.sidebar.set_sub_delay_ui(d)
        return f"Subtitle delay {fmt_delay(d)}"

    def _act_audio_delay(self, action):
        e = self.engine
        d = e.live["audio_delay"] + (50 if action == "audio_delay_plus" else -50)
        e.set_audio_delay(d)
        self.sidebar.audio_delay.set_value(d)
        return f"Audio delay {fmt_delay(d)}"

    def _act_cycle_chip(self, action):
        e = self.engine
        if not e.current:
            return None
        if action == "cycle_aspect":
            return self._cycle_chip(self.sidebar.aspect, "aspect", e.set_aspect, "Aspect ratio")
        return self._cycle_chip(self.sidebar.crop, "crop", e.set_crop, "Crop")

    def _act_bookmark(self, _a):
        e = self.engine
        if not e.current:
            return None
        items = list(self.store.bookmarks(e.current))
        t = e.time()
        items.append({"t": t, "name": f"Bookmark {len(items) + 1}"})
        self.store.set_bookmarks(e.current, items)
        self.sidebar.refresh_bookmarks()
        return f"Bookmark added at {fmt_time(t)}"

    def take_snapshot(self):
        """Save the current frame as a PNG in the system's Pictures folder, and say exactly where (M32)."""
        folder = snapshot_dir()
        path = os.path.join(folder, time.strftime("Pylon %Y-%m-%d %H.%M.%S.png"))
        if not self.engine.snapshot(path):
            return "Couldn't take a snapshot"
        return f"Snapshot saved to {short_path(folder)}"

    def _drop_slider_focus(self) -> bool:
        """A settings slider that was clicked keeps Left and Right (#79). Let go of them."""
        fw = QApplication.focusWidget()
        if isinstance(fw, KeySlider):
            fw.clearFocus()
            self.setFocus(Qt.OtherFocusReason)
            return True
        return False

    def _typing(self, action) -> bool:
        """The key belongs to a text box, or Enter to a list item, that has the focus."""
        fw = QApplication.focusWidget()
        if isinstance(fw, QLineEdit) and fw.isVisible():
            return True
        return (action == "fullscreen_enter" and isinstance(fw, QAbstractItemView) and fw.isVisible()
                and fw.currentIndex().isValid())

    def _cycle(self, tracks, current, setter, label):
        if not tracks:
            return f"No {label.lower()} tracks"
        ids = [t for t, _ in tracks]
        i = ids.index(current) if current in ids else -1
        tid, name = tracks[(i + 1) % len(tracks)]
        setter(tid)
        return f"{label}: {name}"
