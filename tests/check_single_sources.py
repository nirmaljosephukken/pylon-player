"""One place for each rule: the resume rule, speeds, episode markers, subtitle and cover files, colours on
the accent, and key labels that follow the user's shortcuts."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from app import engine, theme
engine.vlc = None
from app.music import folder_cover
from app.store import Store, is_finished, resume_point
from app.util import (AUDIO_EXTS, SPEED_PRESETS, SPEED_STEPS, SUB_EXTS, SUB_SIDECAR_EXTS, episode_key,
                      find_subtitle_candidates, pretty_title, subtitle_query)
from app.window import MainWindow

app = QApplication.instance() or QApplication([])


class Rules(unittest.TestCase):
    def test_resume_rule(self):
        self.assertEqual(resume_point({"pos": 5_000, "len": 100_000}), 0)          # barely started
        self.assertEqual(resume_point({"pos": 50_000, "len": 100_000}), 50_000)
        self.assertEqual(resume_point({"pos": 95_000, "len": 100_000}), 0)         # nearly done
        self.assertEqual(resume_point({"pos": 50_000, "len": 100_000, "watched": True}), 0)
        self.assertEqual(resume_point({"pos": 50_000, "len": 0}), 0)
        self.assertTrue(is_finished({"pos": 95_000, "len": 100_000}))
        self.assertFalse(is_finished({"pos": 50_000, "len": 100_000}))

    def test_speeds(self):
        self.assertEqual(list(SPEED_STEPS), sorted(SPEED_STEPS))
        self.assertTrue(set(SPEED_PRESETS) <= set(SPEED_STEPS))
        self.assertIn(1.0, SPEED_PRESETS)

    def test_episode_markers(self):
        self.assertEqual(pretty_title("Show.S02E01.1080p.mkv"), "Show  ·  S02E01")
        self.assertEqual(pretty_title("Show 1x02.mkv"), "Show  ·  S01E02")
        self.assertEqual(pretty_title("Show 4x4.mkv"), "Show 4x4")
        self.assertEqual(subtitle_query("Show.S02E01.1080p.mkv"), "Show")
        self.assertEqual(subtitle_query("Show EP05.mkv"), "Show")
        self.assertEqual(episode_key("Show.s01e02.mkv"), (1, 2))
        self.assertEqual(episode_key("Show 3x07.mkv"), (3, 7))

    def test_subtitle_and_audio_extensions(self):
        self.assertNotIn(".alac", AUDIO_EXTS)
        self.assertTrue({".txt", ".idx"} <= SUB_EXTS)
        self.assertFalse({".txt", ".idx"} & SUB_SIDECAR_EXTS)
        with tempfile.TemporaryDirectory() as d:
            video = os.path.join(d, "Film.mkv")
            for name in ("Film.mkv", "Film.srt", "Film.txt", "Film.idx", "AlbumArt.JPG"):
                open(os.path.join(d, name), "w").close()
            found = {os.path.basename(p) for p in find_subtitle_candidates(video)}
            self.assertEqual(found, {"Film.srt"})
            self.assertEqual(os.path.basename(folder_cover(d)), "AlbumArt.JPG")

    def test_text_on_the_accent_reads(self):
        old = theme.accent()
        try:
            theme.set_accent("#FFEE00")
            self.assertIn(f"color: {theme.on_accent()}", theme.stylesheet())
            self.assertEqual(theme.on_accent(), "#111111")
            theme.set_accent("#202080")
            self.assertEqual(theme.on_accent(), "#FFFFFF")
            self.assertNotIn("color: #111;", theme.stylesheet())
        finally:
            theme.set_accent(old)


class KeyLabels(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))
        self.store.set_setting("onboarded", True)
        with patch.object(MainWindow, "_vlc_missing"):
            self.win = MainWindow(self.store)
        self.win._vlc_missing = lambda: None
        self.win._ui_timer.stop()
        self.win._time_timer.stop()

    def tearDown(self):
        w = self.win
        w.store._save_timer.stop()
        w.thumbs.cancel()
        w.library.music.stop()
        for widget in (w.top, w.bottom, w.osd, w):
            widget.deleteLater()
        app.processEvents()
        self.temp.cleanup()

    def test_labels_follow_remapped_keys(self):
        w = self.win
        self.assertEqual(self.store.menu_label("Library", "library"), "Library\tCtrl+L")
        self.assertEqual(w.top.btn_library.toolTip(), "Library (Ctrl+L)")
        self.assertEqual(w.bottom.speed.toolTip(), "Playback speed ([ and ])")
        self.store.data["shortcuts"]["library"] = "Ctrl+Shift+Y"
        self.store.data["shortcuts"]["mute"] = ""
        w.install_shortcuts()
        self.assertEqual(self.store.menu_label("Library", "library"), "Library\tCtrl+Shift+Y")
        self.assertEqual(w.top.btn_library.toolTip(), "Library (Ctrl+Shift+Y)")
        self.assertEqual(w.bottom.btn_mute.toolTip(), "Mute")              # no key: no brackets
        w.top.set_fullscreen(True)
        self.assertEqual(w.top.btn_full.toolTip(), "Leave fullscreen (Esc)")
        w.top.set_fullscreen(False)
        self.assertEqual(w.top.btn_full.toolTip(), "Fullscreen (F)")
        self.store.data["shortcuts"]["bookmark"] = "Ctrl+K"
        w.sidebar.refresh_bookmarks()
        self.assertTrue(w.sidebar._bookmark_button.text().endswith("Ctrl+K"))


if __name__ == "__main__":
    unittest.main()
