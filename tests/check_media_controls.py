"""1.8.0: media keys and the system's media controls.

* Every system: play/pause, next, previous and stop media keys while Pylon is in front.
* Linux: MPRIS on the session bus (desktop media widgets, headset buttons, playerctl). Checked with
  playerctl when it is installed; this check starts its own session bus with dbus-run-session if needed.
* Windows: the System Media Transport Controls overlay. On Windows this check makes the controls for a real
  window, shows a song and a video in them, and closes them, so a wrong COM method number fails here instead
  of in Pylon.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

if (sys.platform.startswith("linux") and not os.environ.get("DBUS_SESSION_BUS_ADDRESS")
        and shutil.which("dbus-run-session") and not os.environ.get("PYLON_CHECK_NO_BUS")):
    os.environ["PYLON_CHECK_NO_BUS"] = "1"          # only once
    sys.exit(subprocess.call(["dbus-run-session", "--", sys.executable] + sys.argv))

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QWidget
from app import engine, media_controls
engine.vlc = None
from app.media_controls import MediaControls
from app.store import Store
from app.window import MainWindow

app = QApplication.instance() or QApplication([])


def wait(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class Hub(unittest.TestCase):
    def setUp(self):
        self.hub = MediaControls()
        self.got = []
        self.hub.command.connect(self.got.append)

    def test_one_key_press_reaching_pylon_twice_counts_once(self):
        self.hub.from_key("toggle")
        self.hub._from_system("play")          # Windows hands the same key to the overlay too
        self.assertEqual(self.got, ["toggle"])
        self.hub.from_key("next")
        self.assertEqual(self.got, ["toggle", "next"])
        self.hub._last = ("next", time.monotonic() - 1)
        self.hub.from_key("next")
        self.assertEqual(self.got, ["toggle", "next", "next"])

    def test_unknown_commands_ignored(self):
        self.hub.from_key("format_disk")
        self.assertEqual(self.got, [])

    def test_state_kept_and_only_changes_sent(self):
        sent = []

        class Backend:
            def update(self, st):
                sent.append(dict(st))

            def close(self):
                pass
        self.hub.backend = Backend()
        self.hub.update(status="playing", title="Song", artist="Band", length=1000, audio=True)
        self.hub.update(status="playing", title="Song")
        self.hub.update(position=500)                  # position alone isn't pushed; it is read when asked
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["title"], "Song")
        self.hub.position_source = lambda: 1234
        self.assertEqual(self.hub.position(), 1234)
        self.hub.stop()
        self.assertIsNone(self.hub.backend)


class WindowCommands(unittest.TestCase):
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
        self.win.engine.current = None
        self.store._save_timer.stop()
        self.win.close()
        self.temp.cleanup()

    def test_commands_become_actions(self):
        w = self.win
        done = []
        w.engine.current = "/films/a.mkv"
        playing = [True]
        w.engine.is_playing = lambda: playing[0]
        with patch.object(w, "do", lambda a, key=True: done.append(a)):
            w.media_command("toggle")
            w.media_command("pause")             # playing: pause toggles
            w.media_command("play")              # playing already: nothing
            playing[0] = False
            w.media_command("play")
            w.media_command("next")
            w.media_command("previous")
            w.media_command("stop")
        self.assertEqual(done, ["play_pause", "play_pause", "play_pause", "next", "prev", "stop"])

    def test_nothing_open_nothing_queued(self):
        w = self.win
        done = []
        with patch.object(w, "do", lambda a, key=True: done.append(a)):
            w.media_command("toggle")
        self.assertEqual(done, [])               # no file dialog from a headset button

    def test_song_and_video_info(self):
        w = self.win
        info = w._media_info("/films/Show/ep1.mkv", "Ep 1", False)
        self.assertEqual(info, {"title": "Ep 1", "artist": "Show", "audio": False})
        self.assertTrue(w._media_info("/music/a.mp3", "a", True)["audio"])

    def test_setting_off_stops_them(self):
        from app.dialogs import PreferencesDialog
        from PySide6.QtWidgets import QCheckBox
        dlg = PreferencesDialog(self.win)
        box = dlg.findChild(QCheckBox, "media_controls")
        self.assertTrue(box.isChecked())
        box.setChecked(False)
        self.assertFalse(self.store.setting("media_controls"))
        self.assertIsNone(self.win.media_keys.backend)
        box.setChecked(True)
        dlg.close()


@unittest.skipUnless(sys.platform.startswith("linux") and media_controls.HAVE_DBUS
                     and os.environ.get("DBUS_SESSION_BUS_ADDRESS"), "Linux with a D-Bus session")
class Mpris(unittest.TestCase):
    def setUp(self):
        self.hub = MediaControls()
        self.got = []
        self.seeks = []
        self.hub.command.connect(self.got.append)
        self.hub.seek_to.connect(self.seeks.append)
        self.hub.position_source = lambda: 42_000
        self.assertEqual(self.hub.start(), "mpris")

    def tearDown(self):
        self.hub.stop()

    def ctl(self, *args):
        """Run playerctl while Qt keeps answering D-Bus calls."""
        out = {}
        t = threading.Thread(target=lambda: out.update(r=subprocess.run(
            ["playerctl", "-p", "pylon", *args], capture_output=True, text=True, timeout=10)))
        t.start()
        while t.is_alive():
            wait(20)
        wait(50)
        return out["r"].stdout.strip()

    @unittest.skipUnless(shutil.which("playerctl"), "playerctl")
    def test_desktop_sees_and_controls_pylon(self):
        self.hub.update(status="playing", title="Song", artist="Band", length=180_000, audio=True)
        self.assertEqual(self.ctl("status"), "Playing")
        self.assertEqual(self.ctl("metadata", "title"), "Song")
        self.assertEqual(self.ctl("metadata", "artist"), "Band")
        self.assertAlmostEqual(float(self.ctl("position")), 42.0, delta=0.5)   # playerctl adds a moment
        self.ctl("next")
        self.ctl("play-pause")
        self.ctl("position", "90")
        self.assertEqual(self.got, ["next", "toggle"])
        self.assertEqual(self.seeks, [90_000])
        self.hub.update(status="paused")
        self.assertEqual(self.ctl("status"), "Paused")

    def test_registered_on_the_bus(self):
        from PySide6.QtDBus import QDBusConnection
        names = QDBusConnection.sessionBus().interface().registeredServiceNames().value()
        self.assertIn(self.hub.backend.name, names)


@unittest.skipUnless(sys.platform == "win32", "Windows")
class WindowsOverlay(unittest.TestCase):
    def test_controls_for_a_real_window(self):
        w = QWidget()
        w.resize(200, 120)
        w.show()
        wait(100)
        hub = MediaControls()
        self.assertEqual(hub.start(int(w.winId())), "windows", "the Windows media controls couldn't start")
        hub.update(status="playing", title="Pylon check song", artist="Pylon", length=1000, audio=True)
        hub.update(status="paused", title="Pylon check video", artist="Folder", audio=False)
        hub.update(status="stopped", title="", artist="", length=0)
        hub.backend._pressed(1)               # Pause button
        wait(50)
        hub.stop()
        w.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
