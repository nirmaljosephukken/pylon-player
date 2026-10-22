"""Full screen with Super Resolution keeps the picture one pixel short of the screen's bottom edge, so
opening a panel doesn't switch Windows' way of showing it and turn the picture black (#42)."""
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


class Margin(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))
        self.store.set_setting("onboarded", True)
        with patch.object(MainWindow, "_welcome", lambda self: None), patch.object(MainWindow, "_vlc_missing"):
            self.win = MainWindow(self.store)
        self.win._vlc_missing = lambda: None

    def tearDown(self):
        self.win.close()
        self.temp.cleanup()

    def margin(self, platform, upscale, full):
        self.store.set_setting("rtx_upscale", upscale)
        with patch.object(window_mod.sys, "platform", platform), \
             patch.object(MainWindow, "isFullScreen", lambda self: full):
            self.win.fit_vsr_margin()
        return self.win.stage.contentsMargins().bottom()

    def test_full_screen_with_super_resolution_on_windows(self):
        self.assertEqual(self.margin("win32", True, True), 1)
        self.assertIn("#000", self.win.stage.styleSheet())

    def test_no_margin_otherwise(self):
        for case in (("win32", True, False), ("win32", False, True), ("linux", True, True), ("darwin", True, True)):
            self.assertEqual(self.margin(*case), 0, case)
            self.assertEqual(self.win.stage.styleSheet(), "")

    def test_leaving_full_screen_removes_it(self):
        self.margin("win32", True, True)
        self.assertEqual(self.margin("win32", True, False), 0)


if __name__ == "__main__":
    unittest.main()
