"""Subtitle site choices for Find online (#46), and redrawing after a resize with
RTX Video Super Resolution on (#42)."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from app import engine
engine.vlc = None
from app import window as window_mod
from app.store import Store
from app.util import SUBTITLE_SITES, subtitle_query, subtitle_search_url
from app.widgets import subtitle_search_menu
from app.window import PAGE_VIDEO, MainWindow

app = QApplication.instance() or QApplication([])


def wait(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class SubtitleSites(unittest.TestCase):
    def test_query_is_the_show_or_title(self):
        self.assertEqual(subtitle_query("E:/TV/House.of.the.Dragon.S03E05.1080p.WEB.H264-GRP.mkv"), "House of the Dragon")
        self.assertEqual(subtitle_query("Inception.2010.1080p.BluRay.x264.mkv"), "Inception")
        self.assertEqual(subtitle_query("Positively.Yours.E01.NF.720p.x265.mkv"), "Positively Yours")
        self.assertEqual(subtitle_query("Severance 2x03 Who Is Alive.mkv"), "Severance")
        self.assertEqual(subtitle_query(""), "")

    def test_urls(self):
        self.assertEqual([k for k, _n, _u in SUBTITLE_SITES],
                         ["opensubtitles.com", "opensubtitles.org", "subdl", "subsource", "addic7ed"])
        self.assertEqual(subtitle_search_url("subdl", "House of the Dragon"), "https://subdl.com/search/House%20of%20the%20Dragon")
        self.assertEqual(subtitle_search_url("subsource", "A&B"), "https://subsource.net/search?q=A%26B")
        self.assertIn("q-Inception/", subtitle_search_url("opensubtitles.com", "Inception"))
        self.assertTrue(subtitle_search_url("unknown", "x").startswith("https://www.opensubtitles.com/"))

    def test_menu_keeps_its_order_and_stars_the_preferred_site(self):
        temp = tempfile.TemporaryDirectory()
        store = Store(str(Path(temp.name) / "data.json"))
        opened = []
        names = ["OpenSubtitles.com", "OpenSubtitles.org", "SubDL", "SubSource", "Addic7ed (TV shows)"]
        with patch("PySide6.QtGui.QDesktopServices.openUrl", lambda url: opened.append(url.toString())):
            menu = subtitle_search_menu(None, store, lambda: "Inception")
            self.assertEqual([a.text() for a in menu.actions()], names)
            self.assertFalse(any("preferred" in a.toolTip() for a in menu.actions()))   # no star by default
            [a for a in menu.actions() if a.text() == "SubDL"][0].trigger()
            self.assertEqual(opened, ["https://subdl.com/search/Inception"])
            menu.aboutToShow.emit()
            self.assertEqual([a.text() for a in menu.actions()], names)        # using a site doesn't move it (#54)
            store.set_setting("sub_site_star", "subsource")
            menu.aboutToShow.emit()
            self.assertEqual([a.text() for a in menu.actions()], names)
            starred = [a.text() for a in menu.actions() if "preferred" in a.toolTip()]
            self.assertEqual(starred, ["SubSource"])
        temp.cleanup()


class CropNudge(unittest.TestCase):
    def test_brief_crop_then_restore(self):
        temp = tempfile.TemporaryDirectory()
        e = engine.Engine(Store(str(Path(temp.name) / "data.json")))
        e.player = MagicMock()
        e.video_size = lambda: (1280, 720)
        e.refresh_upscaler()
        e.player.video_set_crop_geometry.assert_called_with("0+0+0+2")
        wait(200)
        e.player.video_set_crop_geometry.assert_called_with(None)    # the normal crop is back
        e.izoom = {"z": 2.0, "x": 0.0, "y": 0.0, "w": 640.0, "h": 360.0}
        e.refresh_upscaler(); wait(200)
        e.player.video_set_crop_geometry.assert_called_with("0+0+640+360")   # and so is zoom
        e.player = None
        temp.cleanup()


class SuperResolutionResize(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))
        self.store.set_setting("onboarded", True)
        with patch.object(MainWindow, "_welcome", lambda self: None), patch.object(MainWindow, "_vlc_missing"):
            self.win = MainWindow(self.store)
        self.win._vlc_missing = lambda: None
        self.win.resize(1000, 650)
        self.win.show()
        wait(100)
        self.rebuilds = []
        e = self.win.engine
        e.player = MagicMock()                    # looks loaded
        e.player.is_playing.return_value = False
        e.current = "C:/v.mkv"
        e.has_video = lambda: True
        e.refresh_upscaler = lambda: self.rebuilds.append(1)
        self.win.stage.setCurrentIndex(PAGE_VIDEO)

    def tearDown(self):
        self.win.engine.player = None
        self.win.close()
        self.temp.cleanup()

    def resize_and_settle(self):
        self.win.video.resized.emit()
        self.win.video.resized.emit()             # several resizes while a panel slides in
        wait(600)

    def test_redraws_once_after_resize_when_on(self):
        self.store.set_setting("rtx_upscale", True)
        with patch.object(window_mod.sys, "platform", "win32"):
            self.resize_and_settle()
        self.assertEqual(len(self.rebuilds), 1)

    def test_full_screen_redraws_again_later(self):
        """Some GPUs are still settling in full screen, so it redraws twice more (#42)."""
        self.store.set_setting("rtx_upscale", True)
        with patch.object(window_mod.sys, "platform", "win32"), \
             patch.object(MainWindow, "isFullScreen", lambda self: True):
            self.win.toggle_library(True)         # opening a panel counts even if nothing resizes
            self.win.video.resized.emit()
            wait(350)
            self.assertEqual(len(self.rebuilds), 1)   # the usual redraw
            wait(1400)
        self.assertEqual(len(self.rebuilds), 3)

    def test_panel_toggle_in_a_window_redraws_once(self):
        self.store.set_setting("rtx_upscale", True)
        with patch.object(window_mod.sys, "platform", "win32"):
            self.win.toggle_library(True)
            wait(1700)
        self.assertEqual(len(self.rebuilds), 1)

    def test_nothing_happens_when_off(self):
        self.store.set_setting("rtx_upscale", False)
        with patch.object(window_mod.sys, "platform", "win32"):
            self.resize_and_settle()
        self.assertEqual(self.rebuilds, [])

    def test_nothing_happens_off_windows(self):
        self.store.set_setting("rtx_upscale", True)
        with patch.object(window_mod.sys, "platform", "linux"):
            self.resize_and_settle()
        self.assertEqual(self.rebuilds, [])


if __name__ == "__main__":
    unittest.main()
