"""Repeat a part (A–B) with L or the Playback panel, and step back a frame with Shift+E."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from app import engine
engine.vlc = None
from app.engine import Engine
from app.store import DEFAULT_SHORTCUTS, Store
from app.window import MainWindow

app = QApplication.instance() or QApplication([])


class Player:
    def __init__(self):
        self.time, self.paused, self.fps = 0, False, 25.0

    def get_time(self): return self.time
    def set_time(self, ms): self.time = int(ms)
    def get_length(self): return 600_000
    def is_playing(self): return not self.paused
    def set_pause(self, on): self.paused = bool(on)
    def get_fps(self): return self.fps


class FrameBack(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.e = Engine(Store(str(Path(self.temp.name) / "data.json")))
        self.e.player = Player()
        self.e.current = str(Path(self.temp.name) / "Film.mkv")

    def tearDown(self):
        self.temp.cleanup()

    def test_steps_back_one_frame_and_pauses(self):
        e = self.e
        e.player.time = 10_000
        e.prev_frame()
        self.assertTrue(e.player.paused)
        self.assertEqual(e.player.time, 9_960)          # 25 fps: 40 ms a frame
        e.player.fps = 50
        e.prev_frame()
        self.assertEqual(e.player.time, 9_940)

    def test_frame_length_without_a_rate(self):
        e = self.e
        e.player.fps = 0
        self.assertEqual(e.frame_ms(), 40)
        e.player.time = 10
        e.prev_frame()
        self.assertEqual(e.player.time, 0)              # never before the start

    def test_keys(self):
        self.assertEqual(DEFAULT_SHORTCUTS["frame_prev"][1], "Shift+E")
        self.assertEqual(DEFAULT_SHORTCUTS["ab_loop"][1], "L")
        seqs = [v[1] for v in DEFAULT_SHORTCUTS.values()]
        self.assertEqual(len(seqs), len(set(seqs)))


class ABRepeat(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))
        self.store.set_setting("onboarded", True)
        with patch.object(MainWindow, "_welcome", lambda self: None), patch.object(MainWindow, "_vlc_missing"):
            self.win = MainWindow(self.store)
        self.win._vlc_missing = lambda: None
        self.toasts = []
        self.win.toast = lambda msg, *a, **k: self.toasts.append(msg)
        e = self.win.engine
        e.player = Player()
        e.current = str(Path(self.temp.name) / "Song.mp3")

    def tearDown(self):
        self.win.close()
        self.temp.cleanup()

    def test_l_sets_start_end_then_off(self):
        w, p = self.win, self.win.engine.player
        p.time = 30_000
        w.do("ab_loop")
        self.assertEqual(w.ab_loop, [30_000, None])
        self.assertIn("Press L", self.toasts[-1])
        p.time = 45_000
        w.do("ab_loop")
        self.assertEqual(w.ab_loop, [30_000, 45_000])
        self.assertEqual(self.toasts[-1], "Repeating 0:30 – 0:45")
        self.assertEqual(w.bottom.seek.ab, (30_000, 45_000))
        self.assertIn("0:30 – 0:45", w.sidebar.ab_label.text())
        w.do("ab_loop")
        self.assertEqual(w.ab_loop, [None, None])
        self.assertEqual(self.toasts[-1], "Repeat off")
        self.assertFalse(w.sidebar.ab_end.isEnabled())

    def test_end_must_come_after_start(self):
        w, p = self.win, self.win.engine.player
        p.time = 30_000
        w.set_ab_point("a")
        p.time = 30_100
        msg = w.set_ab_point("b")
        self.assertIn("after its start", msg)
        self.assertEqual(w.ab_loop, [30_000, None])
        w.set_ab_point("b", 50_000)
        w.set_ab_point("a", 60_000)                     # a start after the end drops the end
        self.assertEqual(w.ab_loop, [60_000, None])

    def test_reaching_the_end_jumps_back(self):
        w, p = self.win, self.win.engine.player
        w.set_ab_point("a", 30_000)
        w.set_ab_point("b", 45_000)
        p.time = 44_000
        w._check_ab()
        self.assertEqual(p.time, 44_000)
        p.time = 45_050
        w._check_ab()
        self.assertEqual(p.time, 30_000)
        p.time = 46_000                                 # VLC still reporting the old time: no second jump
        w._check_ab()
        self.assertEqual(p.time, 46_000)
        p.paused = True
        w._ab_jumped = 0
        w._check_ab()
        self.assertEqual(p.time, 46_000)               # paused: nothing happens

    def test_panel_buttons(self):
        w, p = self.win, self.win.engine.player
        p.time = 10_000
        w.sidebar.ab_start.click()
        p.time = 20_000
        w.sidebar.ab_end.click()
        self.assertEqual(w.ab_loop, [10_000, 20_000])
        w.sidebar.ab_off.click()
        self.assertEqual(w.ab_loop, [None, None])

    def test_repeat_menu(self):
        w = self.win
        m = w.build_repeat_menu()
        acts = [a for a in m.actions() if a.text()]
        self.assertTrue(acts[0].isEnabled())
        self.assertFalse(acts[1].isEnabled())           # no end before a start
        w.set_ab_point("a", 1000)
        acts = [a for a in w.build_repeat_menu().actions() if a.text()]
        self.assertTrue(all(a.isEnabled() for a in acts))

    def test_new_file_clears_the_repeat(self):
        w = self.win
        w.set_ab_point("a", 1000)
        w.set_ab_point("b", 9000)
        other = str(Path(self.temp.name) / "Other.mp3")
        Path(other).touch()
        w.engine.open = lambda *a, **k: None
        w.play_path(other)
        self.assertEqual(w.ab_loop, [None, None])
        self.assertEqual(w.bottom.seek.ab, (None, None))

    def test_frame_back_key_on_a_video(self):
        w, p = self.win, self.win.engine.player
        p.time = 5000
        w.do("frame_prev")
        self.assertEqual(p.time, 4960)
        self.assertEqual(self.toasts[-1], "Previous frame")


if __name__ == "__main__":
    unittest.main()
