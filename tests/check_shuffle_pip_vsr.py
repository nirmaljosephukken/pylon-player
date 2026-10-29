"""1.6.3 fixes.
#65: in Shuffle mode, added items land at random places after what's playing, and leaving Shuffle puts
     them in name order; Play next and the other modes are unchanged.
#66: picture in picture tells Qt it stays on top as well as Windows, the Windows call has proper argument
     types, and switching to another app says it again.
#42: with Super Resolution on, a panel switching full screen and a window rebuilds the picture once the
     window has settled, and a window that came from full screen gets the later redraws too."""
import ctypes
import ctypes.wintypes
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtGui import QWindowStateChangeEvent
from PySide6.QtWidgets import QApplication
from app import engine, util
engine.vlc = None
from app import window as window_mod
from app.store import Store
from app.window import MainWindow

app = QApplication.instance() or QApplication([])


def wait(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))
        self.store.set_setting("onboarded", True)
        with patch.object(MainWindow, "_welcome", lambda self: None), patch.object(MainWindow, "_vlc_missing"):
            self.win = MainWindow(self.store)
        self.win._vlc_missing = lambda: None
        self.win.toast = lambda *a, **k: None
        self.win.play_path = lambda path, **kw: setattr(self.win.engine, "current", path)

    def tearDown(self):
        self.win.close()
        self.temp.cleanup()


class ShuffleAdd(Base):
    def names(self, q=None):
        return [Path(x["path"]).name for x in (self.win.queue if q is None else q)]

    def files(self, n, folder="show"):
        return [f"C:/{folder}/ep{i:02d}.mkv" for i in range(n)]

    def test_empty_queue_in_shuffle_mode_is_shuffled(self):
        w = self.win
        random.seed(1)
        w.set_queue_mode("shuffle", announce=False)
        w.enqueue(self.files(20))
        self.assertEqual(sorted(self.names()), [f"ep{i:02d}.mkv" for i in range(20)])
        self.assertNotEqual(self.names(), [f"ep{i:02d}.mkv" for i in range(20)])
        self.assertTrue(w.library.shuffled)
        w.set_queue_mode("next", announce=False)          # leaving Shuffle: name order again
        self.assertEqual(self.names(), [f"ep{i:02d}.mkv" for i in range(20)])

    def test_added_items_go_after_whats_playing_at_random_places(self):
        w = self.win
        random.seed(2)
        w.set_queue_mode("shuffle", announce=False)
        w.set_queue([{"path": p} for p in self.files(10)], 0)
        cur = w.queue[w.qindex]
        before = list(w.queue)
        w.enqueue(self.files(10, "other"))
        self.assertIs(w.queue[w.qindex], cur)              # what's playing keeps playing
        new_at = [i for i, q in enumerate(w.queue) if "other" in q["path"]]
        self.assertEqual(len(new_at), 10)
        self.assertTrue(all(i > w.qindex for i in new_at))
        self.assertNotEqual(new_at, list(range(10, 20)))   # not all stuck on the end
        self.assertEqual([q for q in w.queue if q in before], before)   # the rest keeps its order
        w.set_queue_mode("next", announce=False)
        self.assertEqual(self.names(), self.names([{"path": p} for p in self.files(10) + self.files(10, "other")]))

    def test_play_next_still_goes_right_after_whats_playing(self):
        w = self.win
        w.set_queue_mode("shuffle", announce=False)
        w.set_queue([{"path": p} for p in self.files(6)], 0)
        w.enqueue(["C:/x/next.mkv"], play_next=True)
        self.assertEqual(Path(w.queue[w.qindex + 1]["path"]).name, "next.mkv")

    def test_in_order_mode_is_unchanged(self):
        w = self.win
        w.set_queue_mode("next", announce=False)
        w.set_queue([{"path": p} for p in self.files(3)], 0)
        w.enqueue(self.files(3, "other"))
        self.assertEqual(self.names(), ["ep00.mkv", "ep01.mkv", "ep02.mkv"] * 2)

    def test_channels_are_shuffled_in_too(self):
        w = self.win
        random.seed(3)
        w.set_queue_mode("shuffle", announce=False)
        w.enqueue_items([{"path": f"http://tv/{i}", "title": f"Ch {i}"} for i in range(15)])
        titles = [q["title"] for q in w.queue]
        self.assertEqual(sorted(titles, key=lambda t: int(t[3:])), [f"Ch {i}" for i in range(15)])
        self.assertNotEqual(titles, [f"Ch {i}" for i in range(15)])
        w.set_queue_mode("next", announce=False)
        self.assertEqual([q["title"] for q in w.queue], [f"Ch {i}" for i in range(15)])


class PipOnTop(Base):
    def test_pip_tells_qt_and_windows_it_stays_on_top(self):
        w = self.win
        w.show()
        wait()
        calls = []
        with patch.object(window_mod.sys, "platform", "win32"), \
                patch.object(window_mod, "win_set_topmost", lambda h, on: calls.append(on) or True):
            w._set_flag = lambda flag, on: None        # no native window rebuild offscreen
            w.toggle_pip()
            self.assertTrue(w.windowFlags() & Qt.WindowStaysOnTopHint)
            self.assertEqual(calls, [True])
            w._pip_app_state(Qt.ApplicationInactive)   # another app comes to the front
            self.assertEqual(calls, [True, True])
            w.toggle_pip()
            self.assertFalse(w.windowFlags() & Qt.WindowStaysOnTopHint)
            self.assertEqual(calls, [True, True, False])
            w._pip_app_state(Qt.ApplicationInactive)   # not in PiP: leave it alone
            self.assertEqual(calls, [True, True, False])

    def test_windows_call_uses_handle_sized_arguments(self):
        fn = MagicMock(return_value=1)
        windll = MagicMock()
        windll.user32.SetWindowPos = fn
        with patch.object(util.sys, "platform", "win32"), patch.object(ctypes, "windll", windll, create=True):
            self.assertTrue(util.win_set_topmost(1234, True))
            self.assertEqual(fn.argtypes[0], ctypes.wintypes.HWND)
            self.assertEqual(fn.argtypes[1], ctypes.wintypes.HWND)
            self.assertEqual(fn.call_args[0][1].value, ctypes.wintypes.HWND(-1).value)   # HWND_TOPMOST
            util.win_set_topmost(1234, False)
            self.assertEqual(fn.call_args[0][1].value, ctypes.wintypes.HWND(-2).value)   # HWND_NOTOPMOST
            fn.return_value = 0
            self.assertFalse(util.win_set_topmost(1234, True))   # a failed call is reported
        self.assertFalse(util.win_set_topmost(1234, True))       # and does nothing off Windows


class VsrRebuild(Base):
    def setUp(self):
        super().setUp()
        self.state = "normal"
        w = self.win
        for name, st in (("showFullScreen", "full"), ("showMaximized", "max"), ("showNormal", "normal")):
            setattr(w, name, lambda st=st: setattr(self, "state", st))
        w.isFullScreen = lambda: self.state == "full"
        w.isMaximized = lambda: self.state == "max"
        w._vsr_active = lambda: True
        w.engine.restart_video_output = MagicMock(return_value=True)
        self.platform = patch.object(window_mod.sys, "platform", "win32")
        self.platform.start()
        self.store.set_setting("rtx_upscale", True)

    def tearDown(self):
        self.platform.stop()
        super().tearDown()

    def settle(self):
        self.win.changeEvent(QWindowStateChangeEvent(Qt.WindowNoState))

    def test_opening_a_panel_in_full_screen_rebuilds_the_picture_once_settled(self):
        w = self.win
        w.toggle_fullscreen()
        w.toggle_library(True)
        self.assertEqual(self.state, "max")
        self.settle()
        self.assertTrue(w._vsr_restart.isActive())
        self.assertTrue(all(t.isActive() for t in w._vsr_late))   # a window from full screen gets them too
        w._vsr_restart.timeout.emit()
        w.engine.restart_video_output.assert_called_once()

    def test_closing_the_panel_rebuilds_it_again(self):
        w = self.win
        w.toggle_fullscreen()
        w.toggle_sidebar(True)
        self.settle()
        w._vsr_restart.stop()
        w.toggle_sidebar(False)
        self.assertEqual(self.state, "full")
        self.settle()
        self.assertTrue(w._vsr_restart.isActive())

    def test_ordinary_state_changes_dont_rebuild(self):
        w = self.win
        w.toggle_fullscreen()          # entering full screen worked already in 1.6.2: leave it be
        self.settle()
        self.assertFalse(w._vsr_restart.isActive())

    def test_restart_does_nothing_without_a_playing_video(self):
        self.assertFalse(self.win.engine.ok)                 # no VLC here
        self.assertFalse(engine.Engine.restart_video_output(self.win.engine))


if __name__ == "__main__":
    unittest.main()
