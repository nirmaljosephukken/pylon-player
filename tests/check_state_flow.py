"""Changes flow through the store: settings edited in one place show everywhere, Home rebuilds once per
burst of changes, panels are addressed by name, and the music views don't re-check every file each time."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from app import engine, music
engine.vlc = None
from app.store import Store
from app.window import MainWindow

app = QApplication.instance() or QApplication([])


class StateFlow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(str(self.root / "data.json"))
        self.store.set_setting("onboarded", True)
        self.store.set_setting("animate_panels", False)
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

    def test_settings_edited_elsewhere_show_in_the_panel(self):
        sb = self.win.sidebar
        self.store.set_setting("binge", False)
        self.assertFalse(sb.binge.isChecked())
        self.store.set_setting("repeat_queue", True)
        self.assertTrue(sb.repeat_queue.isChecked())
        self.store.set_setting("sub_lang", "spa")
        self.assertEqual(sb.sub_lang.currentText(), "spa")
        self.store.set_setting("audio_lang", "jpn")
        self.assertEqual(sb.audio_lang.currentText(), "jpn")
        seen = []
        self.store.setting_changed.connect(lambda k, v: seen.append((k, v)))
        self.win.engine.set_volume(42)
        self.assertIn(("volume", 42), seen)
        self.assertEqual(self.store.setting("volume"), 42)

    def test_home_rebuilds_once_per_burst(self):
        home = self.win.home
        calls = []
        real = home.refresh
        home.refresh = lambda: (calls.append(1), real())
        home._refresh_timer.timeout.disconnect()
        home._refresh_timer.timeout.connect(home.refresh)
        for i in range(5):
            self.store.add_recent(str(self.root / f"film{i}.mkv"))
        self.store.save("library")
        self.store.save("settings")              # not something Home shows
        self.assertEqual(calls, [])
        app.processEvents()
        self.assertEqual(len(calls), 1)

    def test_tabs_by_name(self):
        w = self.win
        w.open_sidebar_tab("video")
        self.assertEqual(w.sidebar.tabs.currentIndex(), w.sidebar.TABS.index("video"))
        w.open_sidebar_tab(0)
        self.assertEqual(w.sidebar.tabs.currentIndex(), 0)
        w.library.show_section("playlists")
        self.assertEqual(w.library.current_section(), "playlists")
        w.library.show_section("library")
        self.assertEqual(w.library.current_section(), "library")


class MusicPresence(unittest.TestCase):
    def test_files_are_checked_once_per_refresh(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(os.path.join(d, "data.json"))
            store._save_timer.stop()
            with patch.object(music, "data_dir", lambda: d):
                m = music.MusicLibrary(store)
            songs = {}
            for i in range(3):
                p = os.path.join(d, f"{i}.mp3")
                open(p, "w").close()
                songs[p] = {"artist": "A", "album": "B", "track": i + 1}
            m.songs = songs
            checks = []
            real = os.path.exists

            def counting(p):
                checks.append(p)
                return real(p)
            with patch.object(music.os.path, "exists", counting):
                m.albums()
                m.artists()
                m.all_songs()
            self.assertEqual(len(checks), 3)
            os.remove(next(iter(songs)))
            m.forget_presence()
            self.assertEqual(len(m.all_songs()), 2)


if __name__ == "__main__":
    unittest.main()
