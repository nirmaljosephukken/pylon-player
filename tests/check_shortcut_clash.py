"""A key that's already taken can be moved to the new action (#56), and A / C step through
aspect ratios and crops like in VLC."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QMessageBox
from app import engine
engine.vlc = None
from app.dialogs import ShortcutsDialog
from app.store import DEFAULT_SHORTCUTS, Store
from app.window import MainWindow

app = QApplication.instance() or QApplication([])


class Base(unittest.TestCase):
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


class Clash(Base):
    def dialog(self):
        d = ShortcutsDialog(self.win)
        d.show()
        return d

    def test_reported_case_shows_the_bar_and_moves_the_key(self):
        d = self.dialog()
        d.edits["sub_delay_plus"].setKeySequence(QKeySequence("="))
        self.assertTrue(d.clash.isVisible())
        self.assertIn("Normal speed", d.clash_text.text())
        d.clash_use.click()
        self.assertFalse(d.clash.isVisible())
        self.assertEqual(d._key("sub_delay_plus"), "=")
        self.assertEqual(d._key("speed_reset"), "")
        d.save()
        self.assertEqual(self.store.shortcut("sub_delay_plus"), "=")
        self.assertEqual(self.store.shortcut("speed_reset"), "")

    def test_undo_puts_the_old_key_back(self):
        d = self.dialog()
        d.edits["sub_delay_plus"].setKeySequence(QKeySequence("="))
        d.clash_undo.click()
        self.assertFalse(d.clash.isVisible())
        self.assertEqual(d._key("sub_delay_plus"), "J")
        self.assertEqual(d._key("speed_reset"), "=")

    def test_fixing_it_by_hand_hides_the_bar(self):
        d = self.dialog()
        d.edits["sub_delay_plus"].setKeySequence(QKeySequence("="))
        d.edits["speed_reset"].setKeySequence(QKeySequence("0"))
        self.assertFalse(d.clash.isVisible())

    def test_save_offers_to_use_it_for_the_one_just_changed(self):
        d = self.dialog()
        d.edits["sub_delay_plus"].setKeySequence(QKeySequence("="))
        seen = {}

        def fake_exec(box):
            seen["buttons"] = [b.text() for b in box.buttons()]
            box_use = next(b for b in box.buttons() if b.text().startswith("Use it for"))
            box.clickedButton = lambda: box_use
            return 0
        with patch.object(QMessageBox, "exec", fake_exec):
            d.save()
        self.assertIn("Use it for “Subtitles later (+50 ms)”", seen["buttons"])
        self.assertIn("Go back", seen["buttons"])
        self.assertEqual(self.store.shortcut("sub_delay_plus"), "=")
        self.assertEqual(self.store.shortcut("speed_reset"), "")

    def test_go_back_saves_nothing(self):
        d = self.dialog()
        d.edits["sub_delay_plus"].setKeySequence(QKeySequence("="))

        def fake_exec(box):
            back = next(b for b in box.buttons() if b.text() == "Go back")
            box.clickedButton = lambda: back
            return 0
        with patch.object(QMessageBox, "exec", fake_exec):
            d.save()
        self.assertEqual(self.store.shortcut("sub_delay_plus"), "J")
        self.assertTrue(d.isVisible())


class AspectCrop(Base):
    def test_new_keys_are_vlc_ones(self):
        self.assertEqual(DEFAULT_SHORTCUTS["cycle_aspect"][1], "A")
        self.assertEqual(DEFAULT_SHORTCUTS["cycle_crop"][1], "C")
        keys = [k for _, k in DEFAULT_SHORTCUTS.values() if k]
        self.assertEqual(len(keys), len(set(keys)), "every default key is used once")

    def test_a_key_already_given_to_something_else_wins(self):
        self.store.data["shortcuts"]["stop"] = "A"
        self.assertEqual(self.store.shortcut("cycle_aspect"), "")
        self.assertEqual(self.store.shortcut("cycle_crop"), "C")

    def test_a_steps_through_the_aspect_ratios_and_wraps(self):
        w = self.win
        w.engine.current = "/v/film.mkv"
        toasts = []
        w.toast = lambda m, *a, **k: toasts.append(m)
        values = w.sidebar.aspect.values
        for _ in range(len(values)):
            w.do("cycle_aspect")
        self.assertEqual(toasts[0], "Aspect ratio: 16:9")
        self.assertEqual(toasts[1], "Aspect ratio: 16:10")      # added in 1.6.2 (#62)
        self.assertEqual(toasts[4], "Aspect ratio: 2.35:1")
        self.assertEqual(w.engine.live["aspect"], "")            # back to Auto
        self.assertEqual(toasts[-1], "Aspect ratio: Auto")
        self.assertTrue(w.sidebar.aspect.group.button(0).isChecked())

    def test_c_steps_through_crops(self):
        w = self.win
        w.engine.current = "/v/film.mkv"
        toasts = []
        w.toast = lambda m, *a, **k: toasts.append(m)
        w.do("cycle_crop")
        self.assertEqual(w.engine.live["crop"], "16:9")
        self.assertEqual(toasts[-1], "Crop: 16:9")

    def test_nothing_playing_does_nothing(self):
        w = self.win
        w.engine.current = None
        w.do("cycle_aspect")
        self.assertEqual(w.engine.live["aspect"], "")


if __name__ == "__main__":
    unittest.main()
