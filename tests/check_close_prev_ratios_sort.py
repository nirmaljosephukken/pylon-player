"""Close the video (#61), new crop ratios and the ratio picker (#62), sorting with a direction
arrow and Recently played for Playlists and Streams (#63), and the Previous preference (#64)."""
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from app import engine
engine.vlc = None
from app import theme
from app.library import ROLE_PATH
from app.store import DEFAULT_SHORTCUTS, RATIOS, Store, ratio_label
from app.window import PAGE_HOME, MainWindow

app = QApplication.instance() or QApplication([])


def wait(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(str(self.root / "data.json"))
        self.store.set_setting("onboarded", True)
        with patch.object(MainWindow, "_welcome", lambda self: None), patch.object(MainWindow, "_vlc_missing"):
            self.win = MainWindow(self.store)
        self.win._vlc_missing = lambda: None
        self.win.resize(1300, 800)
        self.win.show()
        wait(100)
        self.toasts = []
        self.win.toast = lambda m, *a, **k: self.toasts.append(m)

    def tearDown(self):
        self.win.close()
        self.temp.cleanup()


class PreviousButton(Base):
    """#64: past 3 seconds Previous starts the file again first, unless Preferences turns that off."""

    def _playing_second_item(self, ms):
        w = self.win
        w.queue = [{"path": "/v/one.mkv"}, {"path": "/v/two.mkv"}]
        w.qindex = 1
        w.engine.current = "/v/two.mkv"
        played, seeks = [], []
        w.play_queue_index = lambda i, start_ms=None: played.append(i)
        w.engine.time = lambda: ms
        w.engine.seek = lambda t: seeks.append(t)
        return played, seeks

    def test_first_press_restarts_and_says_so(self):
        played, seeks = self._playing_second_item(60_000)
        self.win.play_prev()
        self.assertEqual((played, seeks), ([], [0]))
        self.assertIn("press again for the previous item", self.toasts[-1])

    def test_near_the_start_goes_to_the_previous_item(self):
        played, seeks = self._playing_second_item(1_000)
        self.win.play_prev()
        self.assertEqual((played, seeks), ([0], []))

    def test_turned_off_always_goes_to_the_previous_item(self):
        self.store.set_setting("prev_restarts", False)
        played, seeks = self._playing_second_item(60_000)
        self.win.play_prev()
        self.assertEqual((played, seeks), ([0], []))

    def test_nothing_before_it_starts_again(self):
        played, seeks = self._playing_second_item(60_000)
        self.win.qindex = 0
        self.win.engine.current = "http://example.com/live"
        self.win.play_prev()
        self.assertEqual((played, seeks), ([], [0]))
        self.assertEqual(self.toasts[-1], "Back to the start")

    def test_preferences_has_the_switch(self):
        from PySide6.QtWidgets import QCheckBox
        from app.dialogs import PreferencesDialog
        d = PreferencesDialog(self.win)
        cb = d.findChild(QCheckBox, "prev_restarts")
        self.assertTrue(cb.isChecked())
        cb.setChecked(False)
        self.assertFalse(self.store.setting("prev_restarts"))
        d.close()


class CloseVideo(Base):
    """#61: a button next to the menu and Ctrl+W unload the video and go home."""

    def test_shortcut_and_button(self):
        self.assertEqual(DEFAULT_SHORTCUTS["close_media"][1], "Ctrl+W")
        keys = [k for _, k in DEFAULT_SHORTCUTS.values() if k]
        self.assertEqual(len(keys), len(set(keys)))
        top = self.win.top.layout()
        order = [top.itemAt(i).widget() for i in range(top.count()) if top.itemAt(i).widget()]
        self.assertEqual(order[-2:], [self.win.top.btn_menu, self.win.top.btn_close])

    def test_close_unloads_and_keeps_the_queue(self):
        w = self.win
        w.queue = [{"path": "/v/one.mkv"}, {"path": "/v/two.mkv"}]
        w.qindex = 1
        w.engine.current = "/v/two.mkv"
        w.top.set_title("two")
        w.stage.setCurrentIndex(1)
        saved = []
        w._save_position = lambda: saved.append(w.engine.current)
        w.top.btn_close.click()
        self.assertIsNone(w.engine.current)
        self.assertEqual(saved, ["/v/two.mkv"])        # where you stopped is kept
        self.assertEqual(w.stage.currentIndex(), PAGE_HOME)
        self.assertEqual(len(w.queue), 2)
        self.assertEqual(w.top._full_title, "")

    def test_key_does_the_same(self):
        w = self.win
        w.engine.current = "/v/one.mkv"
        w.stage.setCurrentIndex(1)
        w.do("close_media")
        self.assertIsNone(w.engine.current)
        self.assertEqual(w.stage.currentIndex(), PAGE_HOME)


class Ratios(Base):
    """#62: 2.21:1 and 16:10 (and the rest of VLC's list), chosen in Preferences."""

    def test_new_crops_are_offered(self):
        crop = self.win.sidebar.crop.values
        self.assertIn("221:100", crop)
        self.assertIn("16:10", crop)
        self.assertNotIn("21:9", crop)                 # 2.21:1 takes its place; it can be turned back on
        self.assertIn("16:10", self.win.sidebar.aspect.values)
        self.assertEqual(ratio_label("221:100"), "2.21:1")
        self.assertEqual(ratio_label(""), "")
        self.assertEqual(len(RATIOS), 11)

    def test_picker_changes_the_rows(self):
        from app.dialogs import PreferencesDialog
        d = PreferencesDialog(self.win)
        d.ratios.buttons[("crop", "21:9")].click()
        d.ratios.buttons[("aspect", "1:1")].click()
        self.assertIn("21:9", self.store.setting("crop_choices"))
        self.assertIn("21:9", self.win.sidebar.crop.values)
        self.assertNotIn("1:1", self.win.sidebar.aspect.values)
        # the rows keep RATIOS order whatever order they were switched on in
        crop = self.win.sidebar.crop.values
        self.assertLess(crop.index("221:100"), crop.index("21:9"))
        d.close()

    def test_rebuilt_row_keeps_the_choice_and_c_still_cycles(self):
        w = self.win
        w.engine.current = "/v/film.mkv"
        w.sidebar.crop.select("221:100")
        w.engine.live["crop"] = "221:100"
        self.store.set_setting("crop_choices", ["2.21:1", "2.39:1"])
        w.sidebar.refresh_ratio_rows()
        self.assertEqual(w.sidebar.crop.values, ["", "221:100", "239:100"])
        self.assertTrue(w.sidebar.crop.group.button(1).isChecked())
        w.do("cycle_crop")
        self.assertEqual(w.engine.live["crop"], "239:100")
        self.assertEqual(self.toasts[-1], "Crop: 2.39:1")


class Sorting(Base):
    """#63: one entry per sort with an arrow for its direction; Recently played for Playlists and Streams."""

    def setUp(self):
        super().setUp()
        lib = self.win.library
        now = time.time()
        for n in ("Bravo", "alpha", "Charlie"):     # made in this order
            self.store.data["playlists"][n] = [f"/m/{n}.mkv"]
        self.store.data["plays"] = {
            lib_norm("/m/alpha.mkv"): {"n": 1, "t": now - 10},
            lib_norm("/m/Bravo.mkv"): {"n": 1, "t": now - 500},
            "http://a": {"n": 1, "t": now - 5},
        }
        self.store.data["streams"] = [{"name": "Zed", "url": "http://z"}, {"name": "Amy", "url": "http://a"}]
        self.lib = lib

    def names(self):
        return [self.lib.pl_list.item(i).data(ROLE_PATH) for i in range(self.lib.pl_list.count())]

    def test_one_entry_per_sort(self):
        c = self.lib.playlists_sort
        self.assertEqual([c.combo.itemText(i) for i in range(c.combo.count())],
                         ["Date added", "Name", "Recently played", "Items", "Watched"])
        s = self.lib.streams_sort
        self.assertEqual([s.combo.itemText(i) for i in range(s.combo.count())],
                         ["Date added", "Name", "Recently played"])

    def test_arrow_turns_the_order_round(self):
        lib = self.lib
        lib.show_section("playlists")
        c = lib.playlists_sort
        c.combo.setCurrentIndex(c.combo.findData("name"))
        self.assertEqual(self.store.setting("playlists_sort"), "name")
        self.assertEqual(self.names(), ["alpha", "Bravo", "Charlie"])
        c.arrow.click()
        self.assertEqual(self.store.setting("playlists_sort"), "reverse")
        self.assertEqual(self.names(), ["Charlie", "Bravo", "alpha"])
        self.assertIn("Z to A", c.arrow.toolTip())
        # a new kind starts in its usual direction
        c.combo.setCurrentIndex(c.combo.findData("added"))
        self.assertEqual(self.store.setting("playlists_sort"), "newest")
        self.assertEqual(self.names(), ["Charlie", "alpha", "Bravo"])

    def test_recently_played_playlists_and_home_follows(self):
        lib = self.lib
        lib.show_section("playlists")
        c = lib.playlists_sort
        c.combo.setCurrentIndex(c.combo.findData("played"))
        self.assertEqual(self.names(), ["alpha", "Bravo", "Charlie"])     # Charlie never played
        c.arrow.click()
        self.assertEqual(self.store.setting("playlists_sort"), "played_oldest")
        self.assertEqual(self.names(), ["Charlie", "Bravo", "alpha"])
        self.assertEqual([n for n, _ in lib.ordered_playlists()], ["Charlie", "Bravo", "alpha"])

    def test_recently_played_streams(self):
        lib = self.lib
        lib.show_section("streams")
        s = lib.streams_sort
        s.combo.setCurrentIndex(s.combo.findData("played"))
        urls = [lib.st_list.item(i).data(ROLE_PATH) for i in range(lib.st_list.count())]
        self.assertEqual(urls, ["http://a", "http://z"])

    def test_old_saved_modes_still_work(self):
        self.store.set_setting("playlists_sort", "finished")
        from app.library_widgets import SortControl
        c = SortControl("playlists", "finished")
        self.assertEqual(c.combo.currentData(), "watched")
        self.assertEqual(c.mode(), "finished")
        c = SortControl("music", "default")
        self.assertFalse(c.arrow.isEnabled())

    def test_text_on_a_light_accent_is_dark(self):
        theme.set_accent("#FFD84D")
        self.assertEqual(theme.on_accent(), "#111111")
        self.assertIn("selection-color: #111111", theme.stylesheet())
        theme.set_accent("#3D2BFF")
        self.assertEqual(theme.on_accent(), "#FFFFFF")
        theme.set_accent(self.store.setting("accent"))


def lib_norm(p):
    from app.util import norm
    return norm(p)


if __name__ == "__main__":
    unittest.main()
