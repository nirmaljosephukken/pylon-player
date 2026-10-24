"""Waveform seek bar: bars from the sound, kept on disk, drawn in the seek bar, and the
Preferences choice of music only, music and videos, or off."""
import array
import math
import os
import sys
import tempfile
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QComboBox
from app import engine
REAL_VLC = engine.vlc
engine.vlc = None
from app import waveform
from app.store import Store
from app.waveform import WaveformMaker, peaks_from_wav
from app.widgets import SeekBar
from app.window import MainWindow

app = QApplication.instance() or QApplication([])


def write_wav(path, seconds=4, rate=8000, quiet_first_half=True, channels=1):
    """A tone that is quiet for the first half and loud for the second."""
    data = array.array("h")
    for i in range(seconds * rate):
        loud = 0.05 if quiet_first_half and i < seconds * rate // 2 else 0.9
        v = int(32767 * loud * math.sin(2 * math.pi * 440 * i / rate))
        data.extend([v] * channels)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data.tobytes())


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class Peaks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.d = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_quiet_then_loud(self):
        write_wav(self.d / "a.wav")
        peaks = peaks_from_wav(str(self.d / "a.wav"), bars=10)
        self.assertEqual(len(peaks), 10)
        self.assertEqual(max(peaks), 1.0)
        self.assertTrue(all(p < 0.4 for p in peaks[:5]))
        self.assertTrue(all(p > 0.95 for p in peaks[5:]))

    def test_stereo_and_tiny_files(self):
        write_wav(self.d / "s.wav", channels=2)
        self.assertEqual(len(peaks_from_wav(str(self.d / "s.wav"), bars=8)), 8)
        with wave.open(str(self.d / "empty.wav"), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
        self.assertEqual(peaks_from_wav(str(self.d / "empty.wav")), [])

    def test_windows_paths_survive_vlcs_option_syntax(self):
        chain = WaveformMaker.sout_chain(r"C:\Users\Ann Lee\AppData\Roaming\Pylon\waves\x.wav")
        self.assertIn('dst="C:/Users/Ann Lee/AppData/Roaming/Pylon/waves/x.wav"', chain)
        self.assertIn("acodec=s16l", chain)
        self.assertIn("vcodec=none", chain)

    def test_cache(self):
        song = self.d / "song.mp3"
        song.write_bytes(b"x")
        with patch.object(waveform, "data_dir", lambda: str(self.d)):
            m = WaveformMaker()
            m._save_cache(str(song), [0.1, 0.5, 1.0])
            self.assertEqual(m._load_cache(str(song)), [0.1, 0.5, 1.0])
            time.sleep(1.1)
            song.write_bytes(b"changed")                 # a changed file is read again
            self.assertIsNone(m._load_cache(str(song)))

    @unittest.skipIf(REAL_VLC is None, "needs VLC")
    def test_real_vlc_reads_the_sound(self):
        src = self.d / "tone file.wav"
        write_wav(src, seconds=6)
        got = []
        with patch.object(waveform, "data_dir", lambda: str(self.d)), patch.object(engine, "vlc", REAL_VLC):
            m = WaveformMaker()
            m.ready.connect(lambda p, peaks: got.append(peaks))
            m.start(str(src))
            for _ in range(100):
                if got:
                    break
                wait(100)
            m.cancel()
        self.assertTrue(got, "no waveform within 10 s")
        peaks = got[0]
        half = len(peaks) // 2
        self.assertLess(max(peaks[: half - 5]), 0.5)
        self.assertGreater(min(peaks[half + 5:]), 0.8)
        self.assertEqual([f for f in os.listdir(self.d / "waves") if f.endswith(".wav")], [])  # temp file gone


class Drawing(unittest.TestCase):
    def test_paints_with_and_without_a_waveform(self):
        bar = SeekBar()
        bar.resize(400, 18)
        bar.set_length(60_000)
        bar.set_position(30_000)
        bar.markers, bar.chapters = [10_000], [20_000]
        for peaks, ab in (([], (None, None)), ([0.2, 1.0, 0.5] * 50, (None, None)), ([0.5] * 10, (5000, 15000)),
                          ([0.5] * 10, (5000, None))):
            bar.set_wave(peaks)
            bar.set_ab(*ab)
            img = QImage(400, 18, QImage.Format_ARGB32)
            img.fill(0)
            bar.render(img)
            self.assertFalse(img.isNull())
        # the waveform reaches higher up the bar than the plain 8-pixel track
        bar.set_ab(None, None)
        bar.set_wave([1.0] * 100)
        img = QImage(400, 18, QImage.Format_ARGB32)
        img.fill(0)
        bar.render(img)
        self.assertGreater(img.pixelColor(300, 3).alpha(), 0)


class WindowChoice(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.d = Path(self.temp.name)
        self.store = Store(str(self.d / "data.json"))
        self.store.set_setting("onboarded", True)
        with patch.object(MainWindow, "_welcome", lambda self: None), patch.object(MainWindow, "_vlc_missing"):
            self.win = MainWindow(self.store)
        self.started = []
        self.win.waves.start = lambda p: self.started.append(os.path.basename(p))
        self.song, self.film = str(self.d / "song.mp3"), str(self.d / "film.mkv")

    def tearDown(self):
        self.win.close()
        self.temp.cleanup()

    def start_for(self, path):
        self.win.engine.current = path
        self.win.start_waveform()

    def test_default_is_music_only(self):
        self.assertEqual(self.store.setting("seek_waveform"), "audio")
        self.start_for(self.song)
        self.start_for(self.film)
        self.start_for("https://example.test/live.mp3")
        self.assertEqual(self.started, ["song.mp3"])

    def test_all_and_off(self):
        self.store.set_setting("seek_waveform", "all")
        self.start_for(self.film)
        self.store.set_setting("seek_waveform", "off")
        self.win.bottom.seek.set_wave([1.0])
        self.start_for(self.song)
        self.assertEqual(self.started, ["film.mkv"])
        self.assertEqual(self.win.bottom.seek.wave, [])

    def test_only_the_current_file_is_drawn(self):
        self.win.engine.current = self.song
        self.win._wave_ready(self.film, [1.0, 0.5])
        self.assertEqual(self.win.bottom.seek.wave, [])
        self.win._wave_ready(self.song, [1.0, 0.5])
        self.assertEqual(self.win.bottom.seek.wave, [1.0, 0.5])

    def test_preferences_choice(self):
        from app.dialogs import PreferencesDialog
        d = PreferencesDialog(self.win)
        combo = d.findChild(QComboBox, "seek_waveform")
        self.assertEqual(combo.currentData(), "audio")
        combo.setCurrentIndex(combo.findData("all"))
        self.assertEqual(self.store.setting("seek_waveform"), "all")
        d.close()


if __name__ == "__main__":
    unittest.main()
