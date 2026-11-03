"""Full screen with Super Resolution (#42). 1.5.1 kept the picture one pixel short of the bottom edge,
which turned it black as soon as full screen started, so that's gone. 1.6.0 to 1.6.4 opened panels in a
maximized window instead; since 1.6.5 the video area is sized to the picture (check_vsr_fit.py), so
panels open in full screen like they do without Super Resolution."""
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

    def test_panels_stay_in_full_screen_with_super_resolution(self):
        w = self.win
        self.store.set_setting("rtx_upscale", True)
        w.toggle_fullscreen()
        w.toggle_library(True)
        self.assertEqual(self.state, "full")
        w.toggle_sidebar(True)
        self.assertEqual(self.state, "full")
        w.toggle_library(False)
        w.toggle_sidebar(False)
        self.assertEqual(self.state, "full")
        self.assertFalse(hasattr(w, "_vsr_back_to_full"))

    def test_entering_full_screen_keeps_open_panels(self):
        w = self.win
        self.store.set_setting("rtx_upscale", True)
        w.toggle_library(True)
        w.toggle_fullscreen()
        self.assertEqual(self.state, "full")
        self.assertTrue(w.library.isVisibleTo(w))

    def test_esc_leaves_full_screen_with_a_panel_open(self):
        w = self.win
        self.store.set_setting("rtx_upscale", True)
        w.toggle_fullscreen()
        w.toggle_sidebar(True)
        w.do("exit_fullscreen")                # Esc
        self.assertEqual(self.state, "normal")

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
