"""Keep the controls visible when not in fullscreen (#68): the video sits between the bars instead
of under them, and the resize redraws a Super Resolution picture (#42). (Since 1.6.5 a panel no
longer swaps full screen for a maximized window with Super Resolution on, so that case is gone.)"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEventLoop, QPoint, QTimer
from PySide6.QtWidgets import QApplication
from app import engine
engine.vlc = None
from app import window as window_mod
from app.controls import BottomBar, TopBar
from app.store import Store
from app.window import PAGE_VIDEO, MainWindow

app = QApplication.instance() or QApplication([])


def wait(ms=100):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class Pinned(unittest.TestCase):
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
        self.win.stage.setCurrentIndex(PAGE_VIDEO)
        wait(150)

    def tearDown(self):
        self.win.close()
        self.temp.cleanup()

    def tick(self):
        self.win._ui_tick()
        wait()

    def test_video_sits_between_the_bars(self):
        w = self.win
        self.tick()
        self.assertEqual(w.video.geometry(), w.stage.rect())        # off: the bars float over the video
        self.assertTrue(w.top.isWindow())
        self.store.set_setting("pin_controls", True)
        self.tick()
        top = w.top.mapTo(w, QPoint(0, 0)).y()
        self.assertFalse(w.top.isWindow())                     # part of the window since 1.6.6 (#81)
        self.assertEqual(w.video.mapTo(w, QPoint(0, 0)).y(), top + TopBar.HEIGHT)
        self.assertEqual(w.bottom.mapTo(w, QPoint(0, 0)).y(), top + TopBar.HEIGHT + w.video.height())
        self.assertEqual(w.video.height(), w.middle.height() - TopBar.HEIGHT - BottomBar.HEIGHT)
        self.assertEqual(w.video.width(), w.middle.width())
        self.store.set_setting("pin_controls", False)
        self.tick()
        self.assertEqual(w.video.geometry(), w.stage.rect())

    def test_full_screen_uses_the_whole_screen(self):
        w = self.win
        self.store.set_setting("pin_controls", True)
        self.tick()
        w.isFullScreen = lambda: True
        self.tick()
        self.assertEqual(w.video.geometry(), w.stage.rect())

    def test_pinning_redraws_super_resolution(self):
        w = self.win
        self.tick()
        w._vsr_active = lambda: True
        with patch.object(w.engine, "refresh_upscaler") as refresh:
            self.store.set_setting("pin_controls", True)
            self.tick()
            wait(300)                              # the 150 ms redraw timer
            self.assertTrue(refresh.called)


if __name__ == "__main__":
    unittest.main()
