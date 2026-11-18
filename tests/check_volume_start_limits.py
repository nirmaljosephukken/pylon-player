"""1.7.2 fixes.

#82 follow-up: on Windows, with the maximum volume at 150% or 200%, a file that started above 100% had no sound
until the volume went below 100%. VLC's Windows audio output applies a boost above 100% as a software gain,
which can leave a starting output silent, so each new audio output starts at 100% at most and goes up to the
real volume once playback has run for a moment.

#89: 85% and 100% are offered as the maximum volume, besides 125%, 150% and 200%.

README: the direct download links name the current release's files, kept so by packaging/sync_metadata.py.
"""
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from app import APP_VERSION, engine
engine.vlc = None
from app.engine import BOOST_DELAY_MS, Engine
from app.store import MAX_VOLUMES, Store
from app.widgets import ConeVolume
from app.window import MainWindow

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packaging"))
import sync_metadata  # noqa: E402

app = QApplication.instance() or QApplication([])
ROOT = Path(__file__).resolve().parents[1]


def wait(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_for(cond, timeout_ms=3000):
    end = time.time() + timeout_ms / 1000
    while not cond() and time.time() < end:
        wait(20)
    return cond()


class FakeMedia:
    def add_option(self, _o):
        pass


class FakeInstance:
    def media_new(self, _mrl):
        return FakeMedia()

    media_new_path = media_new


class FakePlayer:
    """Just enough of a libVLC media player to see which volumes Pylon gives it, and when."""
    def __init__(self):
        self.volumes = []
        self.track = None

    def audio_set_volume(self, v):
        self.volumes.append(int(v))

    def audio_get_volume(self):
        return self.volumes[-1] if self.volumes else -1

    def audio_set_mute(self, _m):
        pass

    def audio_get_mute(self):
        return 0

    def audio_set_track(self, t):
        self.track = t

    def audio_output_device_set(self, _module, device):
        self.device = device

    def stop(self):
        pass

    def set_media(self, _m):
        pass

    def play(self):
        pass

    def add_slave(self, *a):
        pass


class StartVolume(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))
        self.store.set_setting("max_volume", 200)
        self.store.set_setting("volume", 150)
        self.e = Engine(self.store)
        self.p = FakePlayer()
        self.e.player, self.e.instance = self.p, FakeInstance()
        self.e._audio_ready_at = 0
        self.media = str(Path(self.temp.name) / "film.mkv")

    def tearDown(self):
        self.store._save_timer.stop()
        self.temp.cleanup()

    def start(self, v=150):
        self.e.set_volume(v)
        self.p.volumes.clear()
        self.e.open(self.media)

    def test_windows_starts_at_100_then_boosts(self):
        with patch.object(Engine, "BOOST_HOLD", True):
            self.start(150)
            self.assertEqual(self.p.volumes, [100])            # the new output starts at 100%
            self.assertEqual(self.e.volume(), 150)             # the controls still show the real volume
            self.e.state_changed.emit("playing")
            wait(BOOST_DELAY_MS // 2)
            self.assertEqual(self.p.volumes, [100])            # not yet: the output is still starting
            self.assertTrue(wait_for(lambda: self.p.volumes[-1] == 150, BOOST_DELAY_MS + 1000))
            self.assertEqual(self.e.volume(), 150)
            self.assertEqual(self.store.setting("volume"), 150)

    def test_200_percent(self):
        with patch.object(Engine, "BOOST_HOLD", True):
            self.start(200)
            self.assertEqual(self.p.volumes, [100])
            self.e.state_changed.emit("playing")
            self.assertTrue(wait_for(lambda: self.p.volumes[-1] == 200, BOOST_DELAY_MS + 1000))

    def test_100_or_less_is_untouched(self):
        with patch.object(Engine, "BOOST_HOLD", True):
            self.start(80)
            self.e.state_changed.emit("playing")
            wait(BOOST_DELAY_MS + 200)
            self.assertNotIn(100, self.p.volumes)
            self.assertEqual(self.e.volume(), 80)

    def test_volume_changed_while_starting(self):
        with patch.object(Engine, "BOOST_HOLD", True):
            self.start(150)
            self.e.set_volume(180)                             # dragged while the file opens
            self.assertEqual(self.p.volumes[-1], 100)
            self.assertEqual(self.e.volume(), 180)
            self.e.set_volume(60)                              # below 100% goes through at once
            self.assertEqual(self.p.volumes[-1], 60)
            self.e.state_changed.emit("playing")
            wait(BOOST_DELAY_MS + 200)
            self.assertEqual(self.p.volumes[-1], 60)           # and isn't replaced by an older boost

    def test_changing_audio_track(self):
        with patch.object(Engine, "BOOST_HOLD", True):
            self.start(150)
            self.e.state_changed.emit("playing")
            self.assertTrue(wait_for(lambda: self.p.volumes[-1] == 150, BOOST_DELAY_MS + 1000))
            self.e.set_audio(2)                                # a new track starts a new audio output
            self.assertEqual(self.p.track, 2)
            self.assertEqual(self.p.volumes[-1], 100)
            self.assertTrue(wait_for(lambda: self.p.volumes[-1] == 150, BOOST_DELAY_MS + 1500))

    def test_next_file_soon_after_the_last_started(self):
        """The release set for the last file mustn't end the next file's hold (review H1)."""
        with patch.object(Engine, "BOOST_HOLD", True):
            self.start(150)
            self.e.state_changed.emit("playing")
            wait(200)
            self.e.open(self.media + "2")                      # Next, 0.2 s after the first file played
            self.assertEqual(self.p.volumes[-1], 100)
            wait(BOOST_DELAY_MS)                               # the first file's release time has passed
            self.assertEqual(self.p.volumes[-1], 100)          # still held: the new output hasn't started
            self.assertEqual(self.e.volume(), 150)
            self.e.state_changed.emit("playing")
            self.assertTrue(wait_for(lambda: self.p.volumes[-1] == 150, BOOST_DELAY_MS + 1000))

    def test_failed_file_doesnt_keep_the_cap(self):
        with patch.object(Engine, "BOOST_HOLD", True):
            self.start(150)
            self.e.state_changed.emit("error")                 # never plays
            wait(50)
            self.e.set_volume(140)
            self.assertEqual(self.p.volumes[-1], 140)

    def test_closing_ends_the_hold(self):
        with patch.object(Engine, "BOOST_HOLD", True):
            self.start(150)
            self.e.close()
            self.e.set_volume(130)
            self.assertEqual(self.p.volumes[-1], 130)

    def test_changing_audio_device(self):
        with patch.object(Engine, "BOOST_HOLD", True):
            self.start(150)
            self.e.state_changed.emit("playing")
            self.assertTrue(wait_for(lambda: self.p.volumes[-1] == 150, BOOST_DELAY_MS + 1000))
            self.e.set_device("headphones")                    # a new device starts a new output
            self.assertEqual(self.p.device, "headphones")
            self.assertEqual(self.p.volumes[-1], 100)
            self.assertTrue(wait_for(lambda: self.p.volumes[-1] == 150, BOOST_DELAY_MS + 1500))

    def test_other_systems_start_at_the_real_volume(self):
        with patch.object(Engine, "BOOST_HOLD", False):
            self.start(150)
            self.assertEqual(self.p.volumes, [])               # the player already has 150
            self.assertEqual(self.e.volume(), 150)


class MaximumVolume(unittest.TestCase):
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
        self.win.close()
        self.temp.cleanup()

    def test_85_and_100_offered(self):
        self.assertEqual(MAX_VOLUMES, (85, 100, 125, 150, 200))
        from PySide6.QtWidgets import QComboBox
        from app.dialogs import PreferencesDialog
        d = PreferencesDialog(self.win)
        offered = set()
        for combo in d.findChildren(QComboBox):
            items = [combo.itemData(i) for i in range(combo.count())]
            if 125 in items and 200 in items:
                offered = items
        self.assertEqual(offered, [85, 100, 125, 150, 200])
        e, cone = self.win.engine, self.win.bottom.cone
        e.set_volume(110)
        d._set_max_volume(85)
        self.assertEqual(e.max_volume(), 85)
        self.assertEqual(cone.MAX, 85)
        self.assertEqual(self.store.setting("volume"), 85)     # lowering the limit brings the volume down
        e.set_volume(120)
        self.assertEqual(self.store.setting("volume"), 85)
        d._set_max_volume(100)
        self.assertEqual(e.max_volume(), 100)
        d.close()

    def test_cone_with_85(self):
        cone = ConeVolume()
        cone.resize(84, 26)
        cone.set_max(85)
        got = []
        cone.volume_changed.connect(got.append)
        cone._set_from_x(cone.width())                        # the wide end is the limit
        self.assertEqual(got[-1], 85)
        cone._set_from_x(1 + (cone.width() - 2) * 0.98)       # near the end: no snapping to an unreachable 100%
        self.assertLessEqual(got[-1], 85)
        cone.grab()                                           # paints without the 100% mark

    def test_unknown_limit_falls_back(self):
        self.store.set_setting("max_volume", 90)
        self.assertEqual(self.win.engine.max_volume(), 125)


class DownloadLinks(unittest.TestCase):
    def test_readme_names_this_version(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        for name in ("Pylon-Setup-{v}.exe", "Pylon-{v}-x86_64.AppImage", "Pylon-{v}-macOS.zip"):
            self.assertIn("releases/latest/download/" + name.format(v=APP_VERSION), text)

    def test_sync_rewrites_old_names(self):
        old = ("[Windows](https://x/releases/latest/download/Pylon-Setup-1.7.0.exe) "
               "`Pylon-1.6.10-x86_64.AppImage` `Pylon-1.7.0-macOS.zip`")
        new = sync_metadata.download_names(old, "1.7.2", "test")
        self.assertEqual(new, "[Windows](https://x/releases/latest/download/Pylon-Setup-1.7.2.exe) "
                              "`Pylon-1.7.2-x86_64.AppImage` `Pylon-1.7.2-macOS.zip`")
        with self.assertRaises(ValueError):
            sync_metadata.download_names("no links here", "1.7.2", "test")

    def test_managed_files_in_sync(self):
        self.assertEqual(sync_metadata.out_of_date(), [])


if __name__ == "__main__":
    unittest.main()
