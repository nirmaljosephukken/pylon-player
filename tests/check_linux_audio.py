"""Linux startup crash on Fedora with PipeWire (#28): prefer the PulseAudio output,
and hold early volume and mute changes until the audio output has settled."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from app import engine
engine.vlc = None
from app.engine import AUDIO_WARMUP, Engine
from app.store import Store

app = QApplication.instance() or QApplication([])


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class LinuxAudio(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))
        self.store.set_setting("volume", 40)

    def tearDown(self):
        self.temp.cleanup()

    def make(self, platform):
        e = Engine(self.store)
        fake_vlc = MagicMock()
        player = fake_vlc.Instance.return_value.media_player_new.return_value
        player.audio_get_volume.return_value = 100        # VLC's own default before ours is applied
        with patch.object(engine, "vlc", fake_vlc), patch.object(engine.sys, "platform", platform):
            e._build()
        return e, player

    def test_pulse_output_preferred_on_linux_only(self):
        e = Engine(self.store)
        with patch.object(engine.sys, "platform", "linux"):
            self.assertIn("--aout=pulse,alsa,any", e._args())
            with patch.dict(engine.os.environ, {"PYLON_VLC_ARGS": "--aout=pipewire"}):
                self.assertNotIn("--aout=pulse,alsa,any", e._args())   # a user's own choice wins
        for other in ("win32", "darwin"):
            with patch.object(engine.sys, "platform", other):
                self.assertFalse(any(a.startswith("--aout") for a in e._args()))

    def test_linux_waits_before_touching_the_volume(self):
        e, player = self.make("linux")
        player.audio_set_volume.assert_not_called()            # nothing in the first moments
        self.assertEqual(e.volume(), 40)                       # but Pylon already reports the right value
        e.set_volume(55)
        e.set_muted(True)
        self.assertTrue(e.is_muted())
        player.audio_set_volume.assert_not_called()
        wait(int(AUDIO_WARMUP * 1000) + 200)
        player.audio_set_volume.assert_called_once_with(55)    # only the latest value is sent
        player.audio_set_mute.assert_called_once_with(True)
        e.set_volume(70)
        player.audio_set_volume.assert_called_with(70)          # later changes apply straight away

    def test_playback_starting_applies_at_once(self):
        e, player = self.make("linux")
        e._on_state_internal("playing")
        player.audio_set_volume.assert_called_once_with(40)

    def test_windows_applies_immediately(self):
        e, player = self.make("win32")
        player.audio_set_volume.assert_called_once_with(40)


if __name__ == "__main__":
    unittest.main()
