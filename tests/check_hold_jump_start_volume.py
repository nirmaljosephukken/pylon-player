"""1.8.0: hold for 2x speed, type a time to jump to, and the volume Pylon starts at.

* Holding the left button still on the video, or Shift+Space, plays at 2x until it is let go, then goes
  back to the speed you had. A hold is not a click (it doesn't pause), and moving the mouse is not a hold.
* Clicking the time (or Ctrl+G) opens a box to type 1:02:10, 62:10, 130 (1:30), +30, -10 or 50%.
* Preferences > Playback > Volume when Pylon starts.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEvent, QEventLoop, QPointF, Qt, QTimer
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QComboBox
from app import engine
engine.vlc = None
from app.engine import Engine
from app.store import START_VOLUMES, Store
from app.util import parse_jump
from app.window import MainWindow

app = QApplication.instance() or QApplication([])


def wait(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class Jump(unittest.TestCase):
    L = 2 * 3600 * 1000

    def test_clock_times(self):
        self.assertEqual(parse_jump("1:02:10", 0, self.L), 3730_000)
        self.assertEqual(parse_jump("62:10", 0, self.L), 3730_000)
        self.assertEqual(parse_jump("2:10", 0, self.L), 130_000)
        self.assertEqual(parse_jump("0:05.5", 0, self.L), 5500)

    def test_digits_read_like_a_clock(self):
        self.assertEqual(parse_jump("130", 0, self.L), 90_000)
        self.assertEqual(parse_jump("10230", 0, self.L), 3750_000)
        self.assertEqual(parse_jump("45", 0, self.L), 45_000)

    def test_relative_and_percent(self):
        self.assertEqual(parse_jump("+30", 60_000, self.L), 90_000)
        self.assertEqual(parse_jump("-10", 60_000, self.L), 50_000)
        self.assertEqual(parse_jump("-2:00", 60_000, self.L), 0)
        self.assertEqual(parse_jump("+1:00", 60_000, self.L), 120_000)
        self.assertEqual(parse_jump("50%", 0, self.L), self.L // 2)

    def test_stays_in_the_file_and_rejects_nonsense(self):
        self.assertEqual(parse_jump("9:00:00", 0, self.L), self.L - 500)
        for bad in ("", "abc", "1::2", "1:2:3:4", "%", "5%x"):
            self.assertIsNone(parse_jump(bad, 0, self.L), bad)
        self.assertIsNone(parse_jump("50%", 0, 0))


class StartVolume(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))

    def tearDown(self):
        self.store._save_timer.stop()
        self.temp.cleanup()

    def test_starts_at_the_chosen_volume(self):
        self.store.set_setting("volume", 140)
        self.store.set_setting("max_volume", 150)
        self.store.set_setting("start_volume", 50)
        Engine(self.store)
        self.assertEqual(self.store.setting("volume"), 50)

    def test_default_keeps_the_last_volume(self):
        self.store.set_setting("volume", 140)
        self.store.set_setting("max_volume", 150)
        Engine(self.store)
        self.assertEqual(self.store.setting("volume"), 140)
        self.assertIn(0, START_VOLUMES)

    def test_never_above_the_maximum(self):
        self.store.set_setting("max_volume", 85)
        self.store.set_setting("start_volume", 100)
        Engine(self.store)
        self.assertEqual(self.store.setting("volume"), 85)

    def test_unknown_value_ignored(self):
        self.store.set_setting("volume", 60)
        self.store.set_setting("start_volume", 37)
        Engine(self.store)
        self.assertEqual(self.store.setting("volume"), 60)


class WindowFeatures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))
        self.store.set_setting("onboarded", True)
        with patch.object(MainWindow, "_welcome", lambda self: None), patch.object(MainWindow, "_vlc_missing"):
            self.win = MainWindow(self.store)
        self.win._vlc_missing = lambda: None
        self.win.resize(900, 600)
        self.win.show()
        wait(100)
        e = self.win.engine
        e.current = str(Path(self.temp.name) / "film.mkv")
        self.playing = True
        e.is_playing = lambda: self.playing
        e.is_seekable = lambda: True
        e.length = lambda: 3600_000
        self.t = 600_000
        e.time = lambda: self.t
        self.seeks = []
        e.seek = lambda ms: self.seeks.append(ms)

    def tearDown(self):
        self.win.video.cancel_click()
        self.win.engine.current = None
        self.store._save_timer.stop()
        self.win.close()
        self.temp.cleanup()

    # ------------------------------------------------------------ hold for 2x
    def test_hold_and_let_go(self):
        w, e = self.win, self.win.engine
        e.set_rate(1.25)
        w.hold_fast(True)
        self.assertEqual(e.rate(), 2.0)
        w.hold_fast(True)                    # a second start changes nothing
        w.hold_fast(False)
        self.assertEqual(e.rate(), 1.25)     # back to the speed you had

    def test_not_while_paused(self):
        w, e = self.win, self.win.engine
        self.playing = False
        w.hold_fast(True)
        self.assertEqual(e.rate(), 1.0)

    def test_shortcut_ends_when_its_key_is_let_go(self):
        w, e = self.win, self.win.engine
        w.do("hold_fast", key=True)
        self.assertEqual(e.rate(), 2.0)
        app.sendEvent(w, QKeyEvent(QEvent.KeyRelease, Qt.Key_Space, Qt.ShiftModifier, "", True))
        self.assertEqual(e.rate(), 2.0)      # auto-repeat release: still held
        app.sendEvent(w, QKeyEvent(QEvent.KeyRelease, Qt.Key_Space, Qt.ShiftModifier))
        self.assertEqual(e.rate(), 1.0)

    def test_ends_when_pylon_loses_focus(self):
        w, e = self.win, self.win.engine
        w.do("hold_fast", key=True)
        w.eventFilter(app, QEvent(QEvent.ApplicationDeactivate))
        self.assertEqual(e.rate(), 1.0)

    def _mouse(self, target, kind, pos, buttons):
        ev = QMouseEvent(kind, QPointF(*pos), target.mapToGlobal(QPointF(*pos)), Qt.LeftButton, buttons,
                         Qt.NoModifier)
        app.sendEvent(target, ev)

    def test_holding_the_mouse_on_the_video(self):
        v = self.win.video
        seen = []
        v.hold.connect(seen.append)
        with patch.object(QApplication, "mouseButtons", staticmethod(lambda: Qt.LeftButton)):
            self._mouse(v, QEvent.MouseButtonPress, (100, 100), Qt.LeftButton)
            wait(v.HOLD_MS + 200)
            self.assertEqual(seen, [True])
            self.assertEqual(self.win.engine.rate(), 2.0)
            self._mouse(v, QEvent.MouseButtonRelease, (100, 100), Qt.NoButton)
        self.assertEqual(seen, [True, False])
        self.assertEqual(self.win.engine.rate(), 1.0)
        wait(500)
        self.assertTrue(self.playing)        # the release after a hold isn't a click

    def test_moving_is_not_holding(self):
        v = self.win.video
        seen = []
        v.hold.connect(seen.append)
        with patch.object(QApplication, "mouseButtons", staticmethod(lambda: Qt.LeftButton)):
            self._mouse(v, QEvent.MouseButtonPress, (100, 100), Qt.LeftButton)
            self._mouse(v, QEvent.MouseMove, (130, 100), Qt.LeftButton)
            wait(v.HOLD_MS + 200)
            self._mouse(v, QEvent.MouseButtonRelease, (130, 100), Qt.NoButton)
        v.cancel_click()                     # the release is an ordinary click; not this test's business
        self.assertEqual(seen, [])

    # ------------------------------------------------------------ type a time
    def test_clicking_the_time_opens_the_box(self):
        w = self.win
        w.bottom.time_clicked.emit()
        wait(50)
        box = w._jump_box
        self.assertIsNotNone(box)
        self.assertTrue(box.isVisible())
        self.assertEqual(box.text(), "10:00")
        box.setText("+30")
        box.returnPressed.emit()
        self.assertEqual(self.seeks, [630_000])
        self.assertFalse(box.isVisible())

    def test_typed_nonsense_says_how(self):
        w = self.win
        msgs = []
        with patch.object(w, "toast", msgs.append):
            w.jump_to_text("soon")
        self.assertEqual(self.seeks, [])
        self.assertIn("1:02:10", msgs[0])

    def test_shortcut_and_left_click(self):
        self.assertEqual(self.store.shortcut("go_to_time"), "Ctrl+G")
        self.assertEqual(self.store.shortcut("hold_fast"), "Shift+Space")
        self.win.do("go_to_time", key=False)
        self.assertTrue(self.win._jump_box.isVisible())
        self.win._jump_box.close()

    # ------------------------------------------------------------ preferences
    def test_start_volume_in_preferences(self):
        from app.dialogs import PreferencesDialog
        dlg = PreferencesDialog(self.win)
        combo = dlg.findChild(QComboBox, "start_volume")
        self.assertIsNotNone(combo)
        combo.setCurrentIndex(combo.findData(70))
        self.assertEqual(self.store.setting("start_volume"), 70)
        dlg.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
