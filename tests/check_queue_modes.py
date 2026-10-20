"""The queue button cycles through four modes (#48): stop, shuffle, in order, loop.
Nothing Pylon could do before is lost: repeating the whole queue is still there."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from app import engine, theme
engine.vlc = None
from app.store import QUEUE_MODES, Store
from app.window import MainWindow

app = QApplication.instance() or QApplication([])


def wait(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class QueueModes(unittest.TestCase):
    def make(self, **settings):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))
        self.store.set_setting("onboarded", True)
        for k, v in settings.items():
            self.store.set_setting(k, v)
        with patch.object(MainWindow, "_welcome", lambda self: None), patch.object(MainWindow, "_vlc_missing"):
            self.win = MainWindow(self.store)
        self.win._vlc_missing = lambda: None
        self.win.play_path = lambda path, **kw: setattr(self.win.engine, "current", path)
        return self.win

    def tearDown(self):
        self.win.close()
        self.temp.cleanup()

    def fill(self, n=6, at=0):
        w = self.win
        w.set_queue([{"path": f"C:/v/ep{i}.mkv"} for i in range(n)], at)

    def paths(self):
        return [Path(q["path"]).name for q in self.win.queue]

    def test_default_is_in_order_so_nothing_changes(self):
        w = self.make()
        self.assertEqual(w.queue_mode, "next")
        self.assertEqual(w.library.mode_btn._name, "mode_next")

    def test_button_cycles_in_the_requested_order(self):
        w = self.make(queue_mode="none")
        seen = [w.queue_mode]
        for _ in range(4):
            w.library.mode_btn.click()
            seen.append(w.queue_mode)
        self.assertEqual(seen, ["none", "shuffle", "next", "loop", "none"])
        self.assertEqual(list(QUEUE_MODES), ["none", "shuffle", "next", "loop"])

    def test_icon_and_colour_follow_the_mode(self):
        w = self.make(queue_mode="none")
        b = w.library.mode_btn
        self.assertEqual(b._name, "mode_stop")
        self.assertEqual(b._color(), theme.MUTED)          # grey when nothing special is on
        for mode, ic in (("shuffle", "shuffle"), ("next", "mode_next"), ("loop", "repeat_one")):
            w.set_queue_mode(mode)
            self.assertEqual(b._name, ic)
            self.assertEqual(b._color(), theme.accent())
            self.assertIn(QUEUE_MODES[mode][1], b.toolTip())
            self.assertEqual(w.sidebar.queue_mode.values[w.sidebar.queue_mode.group.checkedId()], mode)

    def test_settings_chips_change_the_mode(self):
        w = self.make()
        chips = w.sidebar.queue_mode
        chips.group.button(chips.values.index("loop")).click()
        self.assertEqual(w.queue_mode, "loop")
        self.assertEqual(w.library.mode_btn._name, "repeat_one")

    def test_stop_mode_stops_after_the_item(self):
        w = self.make(queue_mode="none")
        self.fill()
        w.engine.current = "C:/v/ep0.mkv"
        w._on_ended()
        self.assertEqual(w.qindex, 0)

    def test_in_order_moves_on(self):
        w = self.make()
        self.fill()
        w._on_ended()
        self.assertEqual(w.qindex, 1)

    def test_loop_replays_the_item(self):
        w = self.make(queue_mode="loop")
        self.fill(at=2)
        played = []
        w.play_queue_index = lambda i, **kw: played.append(i)
        w.engine.current = "C:/v/ep2.mkv"
        w._on_ended()
        self.assertEqual(played, [2])

    def test_shuffle_and_back_keeps_the_playing_item(self):
        w = self.make()
        self.fill(30, at=4)
        original = self.paths()
        w.set_queue_mode("shuffle")
        self.assertEqual(self.paths()[0], "ep4.mkv")            # what's playing stays first
        self.assertNotEqual(self.paths(), original)
        self.assertEqual(sorted(self.paths()), sorted(original))
        w.set_queue_mode("next")
        self.assertEqual(self.paths(), original)
        self.assertEqual(w.qindex, 4)

    def test_new_queue_in_shuffle_mode_is_shuffled(self):
        w = self.make(queue_mode="shuffle")
        self.fill(30, at=7)
        self.assertEqual(self.paths()[w.qindex], "ep7.mkv")
        self.assertEqual(w.qindex, 0)
        self.assertNotEqual(self.paths(), [f"ep{i}.mkv" for i in range(30)])

    def test_repeat_whole_queue_still_works(self):
        for mode in ("next", "shuffle"):
            w = self.make(queue_mode=mode, repeat_queue=True)
            self.fill(3, at=2)
            last = w.qindex if mode == "next" else len(w.queue) - 1
            w.qindex = last
            w._on_ended()
            self.assertEqual(w.qindex, 0)
            self.tearDown()
        self.make()

    def test_broken_file_only_moves_on_when_playing_through(self):
        for mode, expect in (("next", [1]), ("shuffle", [1]), ("none", []), ("loop", [])):
            w = self.make(queue_mode=mode)
            self.fill(5, at=1)
            w.engine.current = "C:/v/ep1.mkv"
            nexts = []
            with patch.object(MainWindow, "play_next", lambda self, user=False: nexts.append(1)):
                w._on_state("error")
                wait(1700)
            self.assertEqual(nexts, expect, mode)
            self.tearDown()
        self.make()

    def test_preferences_sets_the_starting_mode(self):
        w = self.make()
        from PySide6.QtWidgets import QComboBox
        from app.dialogs import PreferencesDialog
        d = PreferencesDialog(w)
        combos = [c for c in d.findChildren(QComboBox) if c.findData("loop") >= 0]
        self.assertEqual(len(combos), 1)
        combos[0].setCurrentIndex(combos[0].findData("shuffle"))
        self.assertEqual(self.store.setting("queue_mode"), "shuffle")
        d.close()


if __name__ == "__main__":
    unittest.main()
