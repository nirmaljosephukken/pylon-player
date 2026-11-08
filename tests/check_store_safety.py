"""Safety fixes from the 1.7.0 review: data.json is never lost, loaded values have the right types,
crash hooks chain, a subtitle pairing can be removed, VLC starts once and track changes refresh once."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from app import engine
engine.vlc = None
from app import store as store_mod
from app.store import DEFAULT_SETTINGS, Store
from app.window import MainWindow
from app.dialogs import SubtitleDialog

app = QApplication.instance() or QApplication([])


class StoreSafety(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / "data.json"

    def tearDown(self):
        self.temp.cleanup()

    def store(self):
        s = Store(str(self.path))
        s._save_timer.stop()
        return s

    def test_corrupt_file_is_kept_and_backup_used(self):
        s = self.store()
        s.data["library_folders"] = ["/films"]
        s.save_now()
        s.data["library_folders"] = ["/films", "/shows"]
        s.save_now()                                   # data.json.bak now holds ["/films"]
        self.assertTrue(os.path.exists(str(self.path) + ".bak"))
        self.path.write_text('{"library_folders": ["/films", "/sho', encoding="utf-8")   # cut off mid-write
        s2 = self.store()
        self.assertTrue(s2.load_error)
        kept = [p for p in os.listdir(self.root) if p.startswith("data.json.corrupt-")]
        self.assertEqual(len(kept), 1, os.listdir(self.root))
        self.assertIn('"/sho', (self.root / kept[0]).read_text(encoding="utf-8"))
        self.assertTrue(s2.restored_backup)
        self.assertEqual(s2.data["library_folders"], ["/films"])
        s2.save_now()                                  # saving now can't destroy the broken original
        self.assertTrue((self.root / kept[0]).exists())

    def test_corrupt_file_without_backup_loads_defaults(self):
        self.path.write_text("not json", encoding="utf-8")
        s = self.store()
        self.assertTrue(s.load_error)
        self.assertFalse(s.restored_backup)
        self.assertEqual(s.data["library_folders"], [])
        self.assertTrue(any(p.startswith("data.json.corrupt-") for p in os.listdir(self.root)))

    def test_wrong_types_fall_back_to_defaults(self):
        self.path.write_text(json.dumps({
            "recent": {}, "positions": [], "playlists": {"A": ["/a.mkv"]},
            "settings": {"volume": "80", "binge": 1, "hide_delay_ms": 2000.0, "accent": "#00FF00",
                         "eq_custom": [1, 2], "sub_style": "big", "unknown_key": 5},
        }), encoding="utf-8")
        s = self.store()
        self.assertEqual(s.data["recent"], [])
        self.assertEqual(s.data["positions"], {})
        self.assertEqual(s.data["playlists"], {"A": ["/a.mkv"]})
        self.assertEqual(s.setting("volume"), DEFAULT_SETTINGS["volume"])
        self.assertEqual(s.setting("binge"), DEFAULT_SETTINGS["binge"])      # 1 isn't a yes/no
        self.assertEqual(s.setting("hide_delay_ms"), 2000.0)                 # a number is a number
        self.assertEqual(s.setting("accent"), "#00FF00")
        self.assertEqual(s.setting("eq_custom"), [1, 2])                     # None default takes anything
        self.assertEqual(s.setting("sub_style"), {})
        self.assertEqual(s.setting("unknown_key"), 5)
        self.assertFalse(s.load_error)

    def test_history_and_queue_keep_only_media(self):
        self.path.write_text(json.dumps({
            "recent": [{"path": "/x/main.py"}, {"path": "/x/film.mkv"}, {"path": "https://a.b/live"}, "junk", {}],
            "queue": [{"path": "/x/notes.txt"}, {"path": "/x/song.flac"}],
        }), encoding="utf-8")
        s = self.store()
        self.assertEqual([r["path"] for r in s.data["recent"]], ["/x/film.mkv", "https://a.b/live"])
        self.assertEqual([q["path"] for q in s.data["queue"]], ["/x/song.flac"])

    def test_positions_and_plays_are_capped(self):
        s = self.store()
        with patch.object(store_mod, "MAX_POSITIONS", 3), patch.object(store_mod, "MAX_PLAYS", 2):
            for i in range(6):
                s.data["positions"][f"/v{i}.mkv"] = {"pos": 1, "len": 2, "watched": False, "t": i}
                s.data["plays"][f"/s{i}.mp3"] = {"n": 1, "t": i}
            s.data["positions"]["/odd.mkv"] = "broken"
            s.save_now()
        self.assertEqual(sorted(s.data["positions"]), ["/v3.mkv", "/v4.mkv", "/v5.mkv"])
        self.assertEqual(sorted(s.data["plays"]), ["/s4.mp3", "/s5.mp3"])

    def test_sub_style_has_a_default(self):
        self.assertIn("sub_style", DEFAULT_SETTINGS)


class WindowSafety(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))
        self.store.set_setting("onboarded", True)
        self.windows = []

    def window(self):
        with patch.object(MainWindow, "_vlc_missing"):
            win = MainWindow(self.store)
        win._vlc_missing = lambda: None
        win._ui_timer.stop()
        win._time_timer.stop()
        self.windows.append(win)
        return win

    def tearDown(self):
        for win in self.windows:
            win.store._save_timer.stop()
            win.thumbs.cancel()
            win.library.music.stop()
            for widget in (win.top, win.bottom, win.osd, win):
                widget.deleteLater()
        self.store._save_timer.stop()
        app.processEvents()
        self.temp.cleanup()

    def test_saved_subtitle_style_reaches_the_first_engine(self):
        self.store.data["settings"]["sub_style"] = {"scale": 140, "bold": True}
        builds = []
        with patch.object(engine.Engine, "_build", lambda e: builds.append(dict(e.sub_style))), \
                patch.object(engine, "vlc", object()):
            e = engine.Engine(self.store)
        self.assertEqual(len(builds), 1)
        self.assertEqual(builds[0]["scale"], 140)
        self.assertTrue(builds[0]["bold"])
        self.assertTrue(e.sub_style["bold"])

    def test_subtitle_pairing_can_be_removed(self):
        win = self.window()
        video = os.path.join(self.temp.name, "Show S01E01.mkv")
        open(video, "w").close()
        win.engine.current = video
        self.store.data["sub_map"][video] = os.path.join(self.temp.name, "old.srt")
        dlg = SubtitleDialog(win, scope="file")
        win.toast = lambda *a, **k: None
        combo = dlg.table.cellWidget(0, 1)
        self.assertEqual(combo.currentData(), self.store.data["sub_map"][video])
        combo.setCurrentIndex(combo.findData(""))
        dlg.save()
        self.assertNotIn(video, self.store.data["sub_map"])
        dlg.deleteLater()

    def test_track_change_refreshes_once_and_only_when_shown(self):
        self.store.data["settings"]["animate_panels"] = False
        win = self.window()
        win.resize(900, 600)
        win.show()
        app.processEvents()
        calls = []
        win.sidebar.refresh_tracks = lambda: calls.append(1)
        win.toggle_sidebar(False)
        win.engine.tracks_changed.emit()
        win._refresh_after_tracks()
        app.processEvents()
        self.assertEqual(calls, [])                        # hidden: only the seek bar's chapter ticks
        win.toggle_sidebar(True)
        self.assertEqual(len(calls), 1)                    # opening the panel catches up
        app.processEvents()
        self.assertTrue(win.sidebar.isVisible())
        calls.clear()
        win.engine.tracks_changed.emit()
        app.processEvents()
        win._refresh_after_tracks()
        self.assertEqual(len(calls), 1)                    # one rebuild per change, not two
        win.toggle_sidebar(False)


class ExceptHookChain(unittest.TestCase):
    def test_error_log_keeps_the_startup_hook(self):
        import main
        seen = []
        temp = tempfile.TemporaryDirectory()
        old_hook, old_err, old_out = sys.excepthook, sys.stderr, sys.stdout
        try:
            sys.excepthook = lambda *a: seen.append(a[0])
            with patch.object(main.os.path, "abspath", lambda p: os.path.join(temp.name, "main.py")):
                main._install_error_log()
            try:
                raise KeyError("boom")
            except KeyError:
                sys.excepthook(*sys.exc_info())
            self.assertEqual(seen, [KeyError])
            log = Path(temp.name, "logs", "error.log").read_text(encoding="utf-8")
            self.assertIn("KeyError: 'boom'", log)
        finally:
            sys.excepthook, sys.stderr, sys.stdout = old_hook, old_err, old_out
            temp.cleanup()


if __name__ == "__main__":
    unittest.main()
