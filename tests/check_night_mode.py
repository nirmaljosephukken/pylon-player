"""1.8.0: night mode.

libVLC 3 doesn't let an app switch on VLC's compressor (a media player resets "audio-filter"), so Pylon
levels the sound itself: the waveform reader measures how loud every quarter second is, and while night mode
is on Pylon turns VLC's volume down just before loud parts and brings quiet talk up, without changing the
volume you see.
"""
import array
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from app import engine, night
engine.vlc = None
from app.engine import Engine
from app.store import Store
from app.window import MainWindow

app = QApplication.instance() or QApplication([])


def wait(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def tone(seconds, amp, rate=2000):
    return [int(32767 * amp * math.sin(2 * math.pi * 200 * i / rate)) for i in range(int(seconds * rate))]


class Loudness(unittest.TestCase):
    def test_envelope_measures_each_quarter_second(self):
        samples = array.array("h", tone(1, 0.01) + tone(1, 0.7))
        env = night.envelope(samples, 2000)
        self.assertEqual(len(env), 8)
        self.assertTrue(all(55 <= v <= 63 for v in env[:4]), list(env))      # about -40 dB
        self.assertTrue(all(93 <= v <= 98 for v in env[4:]), list(env))      # about -6 dB
        self.assertEqual(night.envelope(array.array("h", [0] * 1000), 2000), bytes([0, 0]))

    def test_loud_turned_down_quiet_brought_up_silence_left_alone(self):
        self.assertLess(night.target_gain(-6), -10)
        self.assertGreaterEqual(night.target_gain(-6), -night.MAX_CUT_DB)
        self.assertGreater(night.target_gain(-38), 3)
        self.assertLessEqual(night.target_gain(-30), night.MAX_LIFT_DB)
        self.assertEqual(night.target_gain(-80), 0)
        self.assertEqual(night.target_gain(None), 0)
        self.assertLess(night.target_gain(-55), night.target_gain(-44))     # hiss isn't brought up as much

    def test_looks_ahead_and_comes_back_slowly(self):
        env = bytes([60] * 20 + [95] * 8 + [60] * 40)       # quiet, 2 s loud from 5 s, quiet again
        lv = night.Leveller()
        lv.load("film", env)
        gains = {ms: lv.step(ms) for ms in range(0, 17000, 250)}
        self.assertGreater(gains[2000], 0)                  # quiet talk brought up
        self.assertLess(gains[4000], -10)                   # turned down before the loud part arrives
        self.assertLess(gains[6500], -10)
        self.assertLess(gains[8250], gains[12000])          # comes back up gradually afterwards
        rises = [gains[ms + 250] - gains[ms] for ms in range(7000, 16500, 250)]
        self.assertLessEqual(max(rises), night.RELEASE_DB + 1e-9)

    def test_volume_scaling(self):
        self.assertEqual(night.scaled_volume(80, 0, cubic=False), 80)
        self.assertEqual(night.scaled_volume(100, -20, cubic=False), 10)
        self.assertEqual(night.scaled_volume(100, -20, cubic=True), 46)     # Windows: VLC's volume is cubic
        self.assertGreater(night.scaled_volume(50, 6, cubic=False), 99)


class FakePlayer:
    def __init__(self):
        self.volumes = []
        self.vol = 80

    def audio_set_volume(self, v):
        self.volumes.append(v)
        self.vol = v

    def audio_get_volume(self):
        return self.vol

    def audio_set_mute(self, m):
        pass

    def get_time(self):
        return self.t

    def is_playing(self):
        return 1


class EngineLevelling(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))
        self.store.set_setting("volume", 80)
        self.e = Engine(self.store)
        self.p = FakePlayer()
        self.e.player, self.e.instance = self.p, object()
        self.e._audio_ready_at = 0
        self.e.current = "/films/a.mkv"
        self.e.time = lambda: self.p.t
        self.e.is_playing = lambda: True
        self.e._boost_held = False

    def tearDown(self):
        self.store._save_timer.stop()
        self.temp.cleanup()

    def flush(self):
        self.e._flush_audio()

    def test_no_vlc_audio_filter_arguments(self):
        self.store.set_setting("night_mode", True)
        self.assertFalse([a for a in self.e._args() if "compressor" in a or "audio-filter" in a])

    def test_follows_the_loudness_and_shows_your_volume(self):
        with patch.object(type(self.e), "ok", True, create=True):
            self.e.set_night_mode(True)
            self.e.set_loudness("/films/a.mkv", bytes([95] * 40))
            self.p.t = 1000
            self.e.night_tick()
            self.flush()
            self.assertLess(self.p.vol, 80)                 # VLC plays it quieter...
            self.assertEqual(self.e.volume(), 80)           # ...but the volume you set is still 80
            self.e.set_volume(60)
            self.flush()
            self.assertLess(self.p.vol, 60)
            self.assertEqual(self.e.volume(), 60)
            self.e.set_night_mode(False)
            self.flush()
            self.assertEqual(self.p.vol, 60)                # off: back to the volume you set
            self.assertEqual(self.e.volume(), 60)

    def test_another_files_loudness_is_ignored_and_each_file_starts_level(self):
        with patch.object(type(self.e), "ok", True, create=True):
            self.e.set_night_mode(True)
            self.e.set_loudness("/films/other.mkv", bytes([95] * 40))
            self.p.t = 1000
            self.e.night_tick()
            self.flush()
            self.assertEqual(self.p.volumes, [])
            self.e.set_loudness("/films/a.mkv", bytes([95] * 40))
            self.e.night_tick()
            self.flush()
            self.assertLess(self.p.vol, 80)
            self.e.leveller.clear()          # what open() does for a new file
            self.assertEqual(self.e.leveller.gain_db, 0)

    def test_off_does_nothing(self):
        with patch.object(type(self.e), "ok", True, create=True):
            self.e.set_loudness("/films/a.mkv", bytes([95] * 40))
            self.p.t = 1000
            self.e.night_tick()
            self.flush()
            self.assertEqual(self.p.volumes, [])


class WindowSwitch(unittest.TestCase):
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

    def tearDown(self):
        self.store._save_timer.stop()
        self.win.close()
        self.temp.cleanup()

    def test_switch_shortcut_and_sidebar_agree(self):
        w = self.win
        msg = w.set_night_mode(True)
        self.assertIn("Night mode on", msg)
        self.assertTrue(self.store.setting("night_mode"))
        self.assertTrue(w.sidebar.night_mode.isChecked())
        w.do("night_mode", key=False)                   # Shift+N switches it off again
        self.assertFalse(self.store.setting("night_mode"))
        w.set_night_mode(False)
        self.assertFalse(w.sidebar.night_mode.isChecked())
        w.sidebar.night_mode.setChecked(True)
        self.assertTrue(self.store.setting("night_mode"))
        self.assertEqual(self.store.shortcut("night_mode"), "Shift+N")

    def test_reads_the_sound_for_night_mode(self):
        w = self.win
        self.store.set_setting("seek_waveform", "off")
        w.engine.current = str(Path(self.temp.name) / "film.mkv")
        with patch.object(w.waves, "start") as start:
            w.start_waveform()
            start.assert_not_called()
            w.set_night_mode(True)
            start.assert_called_with(w.engine.current)
        w.engine.current = None


if __name__ == "__main__":
    unittest.main(verbosity=2)
