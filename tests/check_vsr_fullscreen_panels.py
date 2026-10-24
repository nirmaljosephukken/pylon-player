"""Full screen with Super Resolution (#42). 1.5.1 kept the picture one pixel short of the bottom edge,
which turned it black as soon as full screen started, so that's gone. Instead, a panel opened in full
screen with Super Resolution on opens in a maximized window, where panels work, and closing it goes
back to full screen."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from app import engine
engine.vlc = None
from app import window as window_mod
from app.store import Store
from app.window import MainWindow

app = QApplication.instance() or QApplication([])


class Panels(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))
        self.store.set_setting("onboarded", True)
        with patch.object(MainWindow, "_welcome", lambda self: None), patch.object(MainWindow, "_vlc_missing"):
            self.win = MainWindow(self.store)
        self.win._vlc_missing = lambda: None
        self.win.toast = lambda *a, **k: None
        # offscreen Qt has no real window states, so record what the window is asked to do
        self.state = "normal"
        w = self.win
        for name, st in (("showFullScreen", "full"), ("showMaximized", "max"), ("showNormal", "normal")):
            setattr(w, name, lambda st=st: setattr(self, "state", st))
        w.isFullScreen = lambda: self.state == "full"
        w.isMaximized = lambda: self.state == "max"
        self.platform = patch.object(window_mod.sys, "platform", "win32")
        self.platform.start()

    def tearDown(self):
        self.platform.stop()
        self.win.close()
        self.temp.cleanup()

    def test_no_margin_in_full_screen(self):
        self.store.set_setting("rtx_upscale", True)
        self.win.toggle_fullscreen()
        self.assertEqual(self.state, "full")
        self.assertEqual(self.win.stage.contentsMargins().bottom(), 0)
        self.assertFalse(hasattr(window_mod, "VSR_FULLSCREEN_MARGIN"))

    def test_panel_opens_in_a_window_and_closing_returns_to_full_screen(self):
        w = self.win
        self.store.set_setting("rtx_upscale", True)
        w.toggle_fullscreen()
        w.toggle_library(True)
        self.assertEqual(self.state, "max")
        self.assertTrue(w.library.isVisibleTo(w))
        w.toggle_sidebar(True)                 # a second panel: still a window
        self.assertEqual(self.state, "max")
        w.toggle_library(False)
        self.assertEqual(self.state, "max")    # one panel still open
        w.toggle_sidebar(False)
        self.assertEqual(self.state, "full")
        self.assertFalse(w._vsr_back_to_full)

    def test_leaving_full_screen_while_a_panel_is_open_stays_in_a_window(self):
        w = self.win
        self.store.set_setting("rtx_upscale", True)
        w.toggle_fullscreen()
        w.toggle_sidebar(True)
        w.do("exit_fullscreen")                # Esc
        self.assertFalse(w._vsr_back_to_full)
        w.toggle_sidebar(False)
        self.assertNotEqual(self.state, "full")

    def test_entering_full_screen_closes_open_panels(self):
        w = self.win
        self.store.set_setting("rtx_upscale", True)
        w.toggle_library(True)
        w.toggle_fullscreen()
        self.assertEqual(self.state, "full")
        self.assertFalse(w.library.isVisibleTo(w))

    def test_without_super_resolution_panels_stay_in_full_screen(self):
        w = self.win
        for platform, upscale in (("win32", False), ("linux", True)):
            with patch.object(window_mod.sys, "platform", platform):
                self.store.set_setting("rtx_upscale", upscale)
                self.state = "normal"
                w.toggle_fullscreen()
                w.toggle_library(True)
                self.assertEqual(self.state, "full", platform)
                w.toggle_library(False)
                self.assertEqual(self.state, "full", platform)
                w.toggle_fullscreen()


if __name__ == "__main__":
    unittest.main()
