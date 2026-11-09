"""The shared pieces behind the window: the play queue model, one rule for fitting the picture, every
shortcut action having a handler, the snapshot naming its real folder, and file-manager wording per OS."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from app import engine, window_actions
engine.vlc = None
from app.library_widgets import REVEAL_LABEL
from app.play_queue import PlayQueue
from app.store import DEFAULT_SHORTCUTS, Store
from app.util import short_path
from app.window import MainWindow, fitted_size

app = QApplication.instance() or QApplication([])


def items(*names):
    return [{"path": f"/m/{n}.mkv"} for n in names]


class Queue(unittest.TestCase):
    def test_shuffle_round_trip_keeps_the_current_item(self):
        q = PlayQueue()
        q.items = items("a", "b", "c", "d", "e")
        q.index = 2
        cur = q.current()
        q.shuffle_on()
        self.assertTrue(q.shuffled)
        self.assertIs(q.current(), cur)
        self.assertEqual(q.index, 0)
        q.shuffle_in(items("f"))
        q.shuffle_off()
        self.assertFalse(q.shuffled)
        self.assertEqual([x["path"][3] for x in q.items], list("abcdef"))
        self.assertIs(q.current(), cur)

    def test_merge_in_name_order_follows_the_playing_item(self):
        q = PlayQueue()
        q.items = items("b", "d")
        q.index = 1
        q.merge_in_order(items("a", "c"))
        self.assertEqual([x["path"][3] for x in q.items], list("abcd"))
        self.assertEqual(q.current()["path"], "/m/d.mkv")


class PictureFit(unittest.TestCase):
    def test_one_rule(self):
        self.assertEqual(fitted_size(1920, 1080, 16 / 9), (1920, 1080))
        self.assertEqual(fitted_size(1920, 1080, 4 / 3), (1440, 1080))
        self.assertEqual(fitted_size(1000, 1000, 2.0), (1000, 500))
        w, h = fitted_size(1000, 1000, 3.0, whole=False)
        self.assertAlmostEqual(h, 1000 / 3)
        self.assertEqual(fitted_size(10, 10, 1000.0), (10, 1))      # never 0 pixels high


class Window(unittest.TestCase):
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

    def test_every_shortcut_has_a_handler(self):
        self.assertEqual(set(self.win._actions()), set(DEFAULT_SHORTCUTS))
        self.win.do("no_such_action")                      # unknown actions do nothing

    def test_quiet_actions_show_nothing(self):
        shown = []
        self.win.toast = lambda *a: shown.append(a)
        self.win.do("hide_ui")
        self.assertEqual(shown[-1][0], "Interface hidden")
        self.win.do("hide_ui")
        n = len(shown)
        self.win.do("panels")
        self.win.do("panels")
        self.assertEqual(len(shown), n)

    def test_snapshot_names_the_real_folder(self):
        pics = os.path.join(self.temp.name, "Pics")
        saved = []
        self.win.engine.snapshot = lambda path: saved.append(path) or True
        with patch.object(window_actions.QStandardPaths, "writableLocation", lambda *_: pics):
            msg = self.win.take_snapshot()
        self.assertTrue(os.path.isdir(os.path.join(pics, "Pylon")))
        self.assertEqual(os.path.dirname(saved[0]), os.path.join(pics, "Pylon"))
        self.assertTrue(saved[0].endswith(".png"))
        self.assertEqual(msg, f"Snapshot saved to {short_path(os.path.join(pics, 'Pylon'))}")
        self.assertNotIn("\\", msg if sys.platform != "win32" else "")

    def test_short_path(self):
        home = os.path.expanduser("~")
        self.assertEqual(short_path(os.path.join(home, "Pictures", "Pylon")), os.path.join("Pictures", "Pylon"))
        self.assertEqual(short_path(os.path.dirname(home) or "/"), os.path.dirname(home) or "/")

    def test_library_tab_sorts_like_the_others(self):
        lib = self.win.library
        root = Path(self.temp.name)
        a, z = root / "Alpha", root / "Zulu"
        for d in (a, z):
            d.mkdir()
        os.utime(a, (1_000_000, 1_000_000))
        lib.add_library_path(str(a))
        lib.add_library_path(str(z))
        self.store.set_setting("library_sort", "watched")          # a mode saved by 1.7.0
        self.assertEqual(lib.sort_mode, "finished")
        lib.library_sort.set_mode("name")
        self.assertEqual(lib.ordered_library_folders(), [str(a), str(z)])
        lib.library_sort.flip()
        self.assertEqual(self.store.setting("library_sort"), "reverse")
        self.assertEqual(lib.ordered_library_folders(), [str(z), str(a)])
        lib.library_sort.set_mode("date")
        self.assertEqual(lib.ordered_library_folders(), [str(z), str(a)])     # newest first
        lib.library_sort.flip()
        self.assertEqual(lib.ordered_library_folders(), [str(a), str(z)])
        self.store.data["pinned"] = [str(a)]
        lib.remove_library_folder(str(a) + os.sep)                    # spelled differently
        self.assertEqual(self.store.data["library_folders"], [str(z)])
        self.assertEqual(self.store.data["pinned"], [])                # its pin goes too

    def test_file_manager_wording(self):
        want = {"win32": "Show in Explorer", "darwin": "Show in Finder"}.get(sys.platform, "Show in folder")
        self.assertEqual(REVEAL_LABEL, want)


if __name__ == "__main__":
    unittest.main()
