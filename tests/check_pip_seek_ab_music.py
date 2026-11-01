"""1.6.4 fixes.
#71: leaving picture in picture gives the window back its frame with the close button, and on Windows
     turns the X on again directly.
#72: the seek bar stops following the pointer when the button goes up unseen, the window loses focus
     or the bars hide.
#73: Repeat a part jumps back to the start while the window is minimized or hidden.
#74: right-clicking the music page opens the menu, without the video-only items.
#75: in picture in picture the music page moves and resizes the window, so it works with the interface
     hidden.
#76: in Shuffle mode, Play folder and Play on an album or artist start on a random song, not always
     the first; picking a song still starts on that song."""
import ctypes
import ctypes.wintypes
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEvent, QEventLoop, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QContextMenuEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QMenu
from app import engine, util
engine.vlc = None
from app import window as window_mod
from app.stage import PAGE_AUDIO, PAGE_VIDEO
from app.store import Store
from app.window import MainWindow

app = QApplication.instance() or QApplication([])


def wait(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def mouse(kind, pos, button=Qt.LeftButton, buttons=None):
    buttons = button if buttons is None else buttons
    return QMouseEvent(kind, QPointF(pos), QPointF(pos), QPointF(pos), button, buttons, Qt.NoModifier)


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))
        self.store.set_setting("onboarded", True)
        with patch.object(MainWindow, "_welcome", lambda self: None), patch.object(MainWindow, "_vlc_missing"):
            self.win = MainWindow(self.store)
        self.win._vlc_missing = lambda: None
        self.win.toast = lambda *a, **k: None
        self.played = []
        self.win.play_queue_index = lambda i, **kw: self.played.append(i)

    def tearDown(self):
        self.win.close()
        self.temp.cleanup()


class CloseButtonAfterPip(Base):                       # #71
    def test_leaving_pip_restores_the_frame_and_turns_the_x_on(self):
        w = self.win
        w.show()
        wait()
        before = w.windowFlags()
        self.assertTrue(before & Qt.WindowCloseButtonHint)
        calls = []
        with patch.object(window_mod.sys, "platform", "win32"), \
                patch.object(window_mod, "win_set_topmost", lambda h, on: True), \
                patch.object(window_mod, "win_enable_close", lambda h: calls.append(h) or True):
            w.toggle_pip()
            self.assertTrue(w.windowFlags() & Qt.WindowStaysOnTopHint)
            self.assertEqual(calls, [])
            w.toggle_pip()
            self.assertEqual(calls, [int(w.winId())])
            wait(300)                                     # once more after the window settles
            self.assertEqual(len(calls), 2)
        flags = w.windowFlags()
        self.assertTrue(flags & Qt.WindowCloseButtonHint)
        self.assertFalse(flags & (Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint))
        self.assertEqual(flags, before)
        self.assertEqual(w.windowHandle().flags(), flags)

    def test_a_frame_that_lost_its_close_hint_gets_it_back(self):
        w = self.win
        w.show()
        wait()
        broken = (w.windowFlags() & ~Qt.WindowCloseButtonHint) | Qt.WindowStaysOnTopHint
        w._restore_frame(broken)
        self.assertTrue(w.windowFlags() & Qt.WindowCloseButtonHint)
        self.assertFalse(w.windowFlags() & Qt.WindowStaysOnTopHint)

    def test_windows_call_enables_the_close_item(self):
        windll = MagicMock()
        windll.user32.GetSystemMenu.return_value = 77
        with patch.object(util.sys, "platform", "win32"), patch.object(ctypes, "windll", windll, create=True):
            self.assertTrue(util.win_enable_close(1234))
            u = windll.user32
            self.assertEqual(u.GetSystemMenu.argtypes[0], ctypes.wintypes.HWND)
            self.assertEqual(u.EnableMenuItem.call_args[0], (77, 0xF060, 0))     # SC_CLOSE, MF_ENABLED
            self.assertTrue(u.SetWindowPos.call_args[0][6] & 0x0020)             # SWP_FRAMECHANGED
            u.GetSystemMenu.return_value = 0
            self.assertFalse(util.win_enable_close(1234))
        self.assertFalse(util.win_enable_close(1234))                            # nothing off Windows


class SeekDrag(Base):                                   # #72
    def setUp(self):
        super().setUp()
        self.seek = self.win.bottom.seek
        self.seek.resize(400, 18)
        self.seek.set_length(100_000)
        self.sent = []
        self.seek.seek_requested.connect(self.sent.append)

    def press(self, x=100):
        self.seek.mousePressEvent(mouse(QEvent.MouseButtonPress, QPoint(x, 9)))
        self.assertTrue(self.seek._dragging)

    def test_move_without_the_button_ends_the_drag(self):
        self.press()
        self.seek.mouseMoveEvent(mouse(QEvent.MouseMove, QPoint(300, 9), Qt.NoButton, Qt.NoButton))
        self.assertFalse(self.seek._dragging)
        self.assertEqual(self.sent, [25_000])            # stays where the drag got to, no jump to 300
        self.seek.set_position(25_400)                   # and follows playback again
        self.assertEqual(self.seek.position, 25_400)

    def test_dragging_with_the_button_still_follows(self):
        self.press()
        self.seek.mouseMoveEvent(mouse(QEvent.MouseMove, QPoint(200, 9), Qt.NoButton, Qt.LeftButton))
        self.assertTrue(self.seek._dragging)
        self.assertEqual(self.seek.position, 50_000)

    def test_losing_the_window_or_hiding_ends_the_drag(self):
        for end in (lambda: QApplication.sendEvent(self.seek, QEvent(QEvent.WindowDeactivate)),
                    lambda: self.win._pip_app_state(Qt.ApplicationInactive)):
            self.press()
            end()
            self.assertFalse(self.seek._dragging)

    def test_hide_event_ends_the_drag(self):
        self.seek.show()
        self.press()
        self.seek.hide()
        self.assertFalse(self.seek._dragging)


class RepeatMinimized(Base):                            # #73
    def test_repeat_a_part_jumps_back_while_minimized(self):
        w = self.win
        e = w.engine
        seeks = []
        e.is_playing = lambda: True
        e.time = lambda: 9_000
        e.seek = seeks.append
        w.ab_loop = [2_000, 8_000]
        w.isMinimized = lambda: True
        w._ui_tick()
        self.assertEqual(seeks, [2_000])

    def test_repeat_a_part_jumps_back_while_hidden(self):
        w = self.win
        e = w.engine
        seeks = []
        e.is_playing = lambda: True
        e.time = lambda: 9_000
        e.seek = seeks.append
        w.ab_loop = [2_000, 8_000]
        self.assertFalse(w.isVisible())
        w._ui_tick()
        self.assertEqual(seeks, [2_000])


class MusicPage(Base):
    def capture_menu(self, trigger):
        shown = []

        class Menu(QMenu):
            def exec(self, *a):
                shown.extend(x.text() for x in self.actions())
        with patch("app.window_menus.QMenu", Menu):
            trigger()
        return shown

    def playing(self, page):
        w = self.win
        w.engine.current = "C:/music/song.flac"
        w.engine.is_playing = lambda: True
        w.engine.is_disc = lambda: False
        w.stage.setCurrentIndex(page)

    def test_right_click_on_music_opens_the_menu(self):          # #74
        self.playing(PAGE_AUDIO)
        page = self.win.now_playing
        ev = QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(10, 10), QPoint(10, 10))
        items = self.capture_menu(lambda: page.contextMenuEvent(ev))
        self.assertIn("Pause\tSpace", items)
        self.assertIn("Close\tCtrl+W", items)
        self.assertIn("Audio", items)
        self.assertIn("Add bookmark\tCtrl+B", items)
        for video_only in ("Video", "Take a snapshot", "Subtitles"):
            self.assertNotIn(video_only, items)

    def test_video_menu_is_unchanged(self):
        self.playing(PAGE_VIDEO)
        items = self.capture_menu(lambda: self.win.show_context_menu(QPoint(10, 10)))
        for item in ("Close the video\tCtrl+W", "Video", "Take a snapshot", "Subtitles"):
            self.assertIn(item, items)

    def test_music_page_moves_and_resizes_pip(self):              # #75
        w = self.win
        page = w.now_playing
        grabs = []
        w.pip_grab = lambda gpos, move=True: grabs.append((gpos, move)) or True
        page.mousePressEvent(mouse(QEvent.MouseButtonPress, QPoint(50, 50)))
        self.assertEqual(grabs, [])                       # not in picture in picture: nothing
        w._pip = {"geo": None}
        try:
            page.mousePressEvent(mouse(QEvent.MouseButtonPress, QPoint(50, 50)))
            self.assertEqual(len(grabs), 1)
            self.assertTrue(grabs[0][1])                  # moves, and pip_grab resizes from an edge
            w.pip_edges = lambda gpos: Qt.RightEdge
            page.mouseMoveEvent(mouse(QEvent.MouseMove, QPoint(50, 50), Qt.NoButton, Qt.NoButton))
            self.assertEqual(page.cursor().shape(), Qt.SizeHorCursor)
            w.hide_ui = True                              # with the interface hidden too
            page.mousePressEvent(mouse(QEvent.MouseButtonPress, QPoint(50, 50)))
            self.assertEqual(len(grabs), 2)
        finally:
            w._pip = None


class ShuffleFirstSong(Base):                            # #76
    def files(self, n):
        return [f"/music/album/{i:02d} song.flac" for i in range(n)]

    def test_play_folder_starts_on_a_random_song_in_shuffle(self):
        w = self.win
        w.set_queue_mode("shuffle", announce=False)
        firsts = set()
        with patch("app.window_playback.list_media", lambda f: self.files(12)), \
                patch("app.window_playback.is_dvd_folder", lambda f: False):
            for seed in range(30):
                random.seed(seed)
                self.played.clear()
                w.play_folder("/music/album")
                self.assertEqual(self.played, [0])         # what plays is the queue's first
                firsts.add(Path(w.queue[0]["path"]).name)
                self.assertEqual(sorted(q["path"] for q in w.queue), self.files(12))
        self.assertGreater(len(firsts), 3)                 # not always "00 song.flac"

    def test_play_folder_in_order_mode_starts_at_the_first(self):
        w = self.win
        w.set_queue_mode("next", announce=False)
        with patch("app.window_playback.list_media", lambda f: self.files(5)), \
                patch("app.window_playback.is_dvd_folder", lambda f: False):
            w.play_folder("/music/album")
        self.assertEqual(w.qindex, 0)
        self.assertEqual(w.queue[0]["path"], self.files(5)[0])

    def test_music_play_shuffles_the_first_but_a_picked_song_stays(self):
        w = self.win
        lib = w.library
        w.set_queue_mode("shuffle", announce=False)
        firsts = set()
        for seed in range(30):
            random.seed(seed)
            lib.play_songs(self.files(10))
            firsts.add(w.queue[w.qindex]["path"])
            self.assertEqual(w.qindex, 0)
        self.assertGreater(len(firsts), 3)
        for seed in range(10):
            random.seed(seed)
            lib.play_songs(self.files(10), 4)              # double-clicking a song plays that song
            self.assertEqual(w.queue[w.qindex]["path"], self.files(10)[4])

    def test_a_picked_start_like_a_playlist_resume_is_kept(self):
        w = self.win
        w.set_queue_mode("shuffle", announce=False)
        random.seed(3)
        w.set_queue([{"path": p} for p in self.files(8)], 5)
        self.assertEqual(w.queue[w.qindex]["path"], self.files(8)[5])


if __name__ == "__main__":
    unittest.main(verbosity=2)
