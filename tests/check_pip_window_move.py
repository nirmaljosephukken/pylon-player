"""Picture in picture on Linux keeps the video (#60), and the bars don't trail behind a window
that is being moved (#59)."""
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer
from PySide6.QtWidgets import QApplication
from app import engine
engine.vlc = None
from app import window as window_mod
from app.stage import VideoSurface
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
        self.win.resize(1000, 700)
        self.win.show()
        self.win._ui_timer.stop()                # the test drives the ticks itself
        wait(150)

    def tearDown(self):
        self.win.close()
        self.temp.cleanup()


class PipOnLinux(Base):
    def setUp(self):
        super().setUp()
        self.platform = patch.object(window_mod.sys, "platform", "linux")
        self.platform.start()
        self.rebuilds = []
        self.win.setWindowFlag = lambda *a: self.rebuilds.append(a)    # rebuilds the X11 window

    def tearDown(self):
        self.platform.stop()
        super().tearDown()

    def test_pip_changes_the_flags_without_rebuilding_the_window(self):
        w = self.win
        attached = []
        w.engine.set_window = attached.append
        w.toggle_pip()
        handle = w.windowHandle().flags()
        self.assertTrue(handle & Qt.FramelessWindowHint)
        self.assertTrue(handle & Qt.WindowStaysOnTopHint)
        self.assertTrue(w.windowFlags() & Qt.FramelessWindowHint)     # Qt's record agrees
        self.assertTrue(w.windowFlags() & Qt.WindowStaysOnTopHint)
        w.toggle_pip()
        handle = w.windowHandle().flags()
        self.assertFalse(handle & Qt.FramelessWindowHint)
        self.assertFalse(handle & Qt.WindowStaysOnTopHint)
        self.assertFalse(w.windowFlags() & (Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint))
        self.assertEqual(self.rebuilds, [])
        self.assertEqual(attached, [])          # VLC keeps the window it draws into

    def test_pip_twice(self):
        w = self.win
        for _ in range(2):
            w.toggle_pip()
            self.assertTrue(w._pip)
            w.toggle_pip()
            self.assertIsNone(w._pip)
        self.assertEqual(self.rebuilds, [])
        self.assertFalse(w.windowFlags() & (Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint))


class PipElsewhere(Base):
    def test_windows_still_uses_set_window_flag(self):
        w = self.win
        calls = []
        real = w.setWindowFlag
        w.setWindowFlag = lambda flag, on: (calls.append((flag, on)), real(flag, on))
        w.engine.set_window = lambda wid: None
        w._topmost = lambda on: None
        with patch.object(window_mod.sys, "platform", "win32"):
            w.toggle_pip()
            w.toggle_pip()
        self.assertEqual(calls, [(Qt.FramelessWindowHint, True), (Qt.FramelessWindowHint, False)])


class MovingWindow(Base):
    def tick(self):
        self.win._ui_tick()

    def show_bars(self):
        w = self.win
        w.stage.setCurrentIndex(window_mod.PAGE_VIDEO)
        w._poke(30)                              # bars forced on
        w._moving_until = 0                      # the window manager placing the new window isn't a drag
        self.tick()
        self.assertTrue(w._bars_visible)

    def test_floating_bars_hide_while_the_window_moves(self):
        w = self.win
        self.show_bars()
        w.move(w.x() + 40, w.y() + 20)
        wait(100)
        self.assertFalse(w._bars_visible)
        self.tick()
        self.assertFalse(w._bars_visible)        # still moving
        w._moving_until = time.monotonic() - 0.01
        self.tick()
        self.assertTrue(w._bars_visible)         # back once it stops, over the video
        self.assertEqual(w.top.pos(), w.stage.mapToGlobal(QPoint(0, 0)))

    def test_pinned_bars_follow_straight_away(self):
        w = self.win
        self.store.set_setting("pin_controls", True)
        w.stage.setCurrentIndex(window_mod.PAGE_VIDEO)
        self.tick()
        self.tick()
        self.assertTrue(w._bars_visible)
        w.move(w.x() + 40, w.y() + 20)
        wait(100)
        self.assertTrue(w._bars_visible)
        self.assertEqual(w.top.pos(), w.stage.mapToGlobal(QPoint(0, 0)))

    def test_drag_that_qt_is_not_told_about(self):
        """While the window manager drags the window, only X11 knows where it is."""
        w = self.win
        self.show_bars()
        w.video.x11_drift = lambda: QPoint(60, 30)
        self.tick()
        self.assertFalse(w._bars_visible)
        w.video.x11_drift = lambda: QPoint()     # the drag ends and Qt hears about it
        w._moving_until = time.monotonic() - 0.01
        self.tick()
        self.assertTrue(w._bars_visible)

    def test_pinned_bars_follow_a_drag_qt_is_not_told_about(self):
        w = self.win
        self.store.set_setting("pin_controls", True)
        w.stage.setCurrentIndex(window_mod.PAGE_VIDEO)
        self.tick()
        w.video.x11_drift = lambda: QPoint(60, 30)
        self.tick()
        self.assertTrue(w._bars_visible)
        self.assertEqual(w.top.pos(), w.stage.mapToGlobal(QPoint(0, 0)) + QPoint(60, 30))

    def test_small_drift_is_ignored(self):
        w = self.win
        self.show_bars()
        w.video.x11_drift = lambda: QPoint(1, 1)      # rounding with display scaling
        self.tick()
        self.assertTrue(w._bars_visible)
        self.assertEqual(w.top.pos(), w.stage.mapToGlobal(QPoint(0, 0)))

    def test_no_drift_without_x11(self):
        self.assertEqual(VideoSurface.x11_drift(self.win.video), QPoint())

    def test_full_screen_does_not_hide_the_bars(self):
        w = self.win
        self.show_bars()
        w.windowState = lambda: Qt.WindowFullScreen
        w.move(w.x() + 40, w.y() + 20)
        wait(100)
        self.tick()
        self.assertTrue(w._bars_visible)


if __name__ == "__main__":
    unittest.main()
