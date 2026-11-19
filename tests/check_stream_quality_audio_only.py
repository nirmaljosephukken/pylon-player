"""1.8.1: stream quality (#94), audio only, network buffer and extra VLC options (#95), battery saver (#97).

- #94: the control bar shows the picture's quality (720p, 1080p, 4K) beside the time, and follows a stream that
  changes quality. "Highest stream quality" caps adaptive streams with VLC's :adaptive-maxheight.
- #95: "Audio only" stays on for every file until turned off: VLC gets :no-video, and Now Playing shows instead
  of a black picture. "Network buffer" gives links :network-caching (1 s, VLC's default, adds nothing).
  "Extra VLC options" are added to VLC's start options; if VLC won't start with them it starts without them.
- #97: "Battery saver" starts VLC with the H.264 loop filter skipped and fast decoding, and Super Resolution off.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLineEdit
from app import engine
REAL_VLC = engine.vlc
engine.vlc = None
from app.dialogs import PreferencesDialog
from app.engine import Engine
from app.store import Store
from app.util import quality_label, split_vlc_options
from app.window import PAGE_AUDIO, PAGE_VIDEO, MainWindow

app = QApplication.instance() or QApplication([])
STREAM = "https://cdn.example/hls/master.m3u8"


def wait(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class Pure(unittest.TestCase):
    def test_quality_names(self):
        for size, label in (((1920, 1080), "1080p"), ((1920, 800), "1080p"), ((1280, 720), "720p"),
                            ((1280, 534), "720p"), ((854, 480), "480p"), ((720, 576), "576p"), ((720, 480), "480p"),
                            ((640, 360), "360p"), ((3840, 2160), "4K"), ((3840, 1600), "4K"), ((2560, 1440), "1440p"),
                            ((1080, 1920), "1080p"), ((426, 240), "240p"), ((160, 120), "120p"), ((0, 0), ""),
                            ((1920, 1088), "1080p")):
            self.assertEqual(quality_label(*size), label, size)

    def test_split_options(self):
        self.assertEqual(split_vlc_options('--network-caching=5000  --freetype-font="Noto Sans"'),
                         ["--network-caching=5000", "--freetype-font=Noto Sans"])
        self.assertEqual(split_vlc_options("--no-audio-time-stretch stray C:\\file.mkv -v"),
                         ["--no-audio-time-stretch", "-v"])
        self.assertEqual(split_vlc_options(""), [])
        self.assertEqual(split_vlc_options(None), [])
        self.assertEqual(split_vlc_options("-- -"), [])


class Media:
    def __init__(self, added):
        self.added = added

    def add_option(self, o):
        self.added.append(o)


class Inst:
    def __init__(self, added):
        self.added = added

    def media_new(self, _url):
        return Media(self.added)

    media_new_path = media_new


class Player:
    def __getattr__(self, _name):
        return lambda *a, **k: None


class EngineOptions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))
        self.e = Engine(self.store)
        self.added = []
        self.e.instance, self.e.player = Inst(self.added), Player()

    def tearDown(self):
        self.e.current = None
        self.e.instance = self.e.player = None
        self.store._save_timer.stop()
        self.temp.cleanup()

    def opened(self, target):
        self.added.clear()
        self.e.open(target)
        return list(self.added)

    def test_defaults_add_nothing(self):
        self.assertEqual(self.opened(STREAM), [])
        self.assertEqual(self.opened(str(Path(self.temp.name) / "film.mkv")), [])

    def test_network_buffer_and_quality_cap_for_links_only(self):
        self.store.set_setting("network_buffer", 30)
        self.store.set_setting("max_stream_height", 720)
        self.assertEqual(self.opened(STREAM), [":network-caching=30000", ":adaptive-maxheight=720"])
        self.assertEqual(self.opened(str(Path(self.temp.name) / "film.mkv")), [])
        self.store.set_setting("network_buffer", 7)           # not a choice Preferences offers
        self.store.set_setting("max_stream_height", 0)
        self.assertEqual(self.opened(STREAM), [])

    def test_audio_only(self):
        self.store.set_setting("audio_only", True)
        self.assertEqual(self.opened(str(Path(self.temp.name) / "film.mkv")), [":no-video"])
        self.assertEqual(self.opened(STREAM), [":no-video"])
        self.assertFalse(self.e.has_video())

    def test_set_audio_only_reopens_what_plays(self):
        self.e.current = STREAM
        with patch.object(self.e, "rebuild") as rebuild:
            self.e.set_audio_only(True)
            self.e.set_audio_only(True)                        # no change: no restart
        rebuild.assert_called_once()
        self.assertTrue(self.store.setting("audio_only"))

    def test_start_options(self):
        args = self.e._args()
        self.assertNotIn("--avcodec-fast", args)
        self.store.set_setting("battery_saver", True)
        self.store.set_setting("vlc_extra_args", "--network-caching=5000 --no-sub-autodetect-file")
        self.store.set_setting("rtx_upscale", True)
        args = self.e._args()
        self.assertIn("--avcodec-skiploopfilter=4", args)
        self.assertIn("--avcodec-fast", args)
        self.assertNotIn("--d3d11-upscale-mode=super", args)   # battery saver turns Super Resolution off
        self.assertEqual(args[-2:] if "--file-logging" not in args else
                         [a for a in args if a in ("--network-caching=5000", "--no-sub-autodetect-file")],
                         ["--network-caching=5000", "--no-sub-autodetect-file"])
        self.assertNotIn("--network-caching=5000", self.e._args(typed=False))


@unittest.skipIf(REAL_VLC is None, "needs VLC")
class RealVLC(unittest.TestCase):
    def setUp(self):
        engine.vlc = REAL_VLC
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))

    def tearDown(self):
        engine.vlc = None
        self.store._save_timer.stop()
        self.temp.cleanup()

    def test_bad_extra_option_falls_back(self):
        self.store.set_setting("vlc_extra_args", "--this-option-does-not-exist=1")
        e = Engine(self.store)
        try:
            self.assertTrue(e.ok)
            self.assertTrue(e.extra_args_failed)
        finally:
            e.shutdown()

    def test_good_options_start(self):
        self.store.set_setting("vlc_extra_args", "--network-caching=5000")
        self.store.set_setting("battery_saver", True)
        e = Engine(self.store)
        try:
            self.assertTrue(e.ok)
            self.assertFalse(e.extra_args_failed)
        finally:
            e.shutdown()


class Window(unittest.TestCase):
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
        self.win.thumbs.cancel()
        self.win.close()
        app.processEvents()
        self.temp.cleanup()

    def test_quality_badge(self):
        b = self.win.bottom
        b.set_quality(1280, 720)
        self.assertEqual(b.quality.text(), "720p")
        self.assertFalse(b.quality.isHidden())
        self.assertIn("1280 × 720", b.quality.toolTip())
        b.set_quality(1920, 1080)                  # the stream switched up
        self.assertEqual(b.quality.text(), "1080p")
        b.set_quality(0, 0)
        self.assertTrue(b.quality.isHidden())

    def test_quality_follows_the_picture(self):
        w, e = self.win, self.win.engine
        w.stage.setCurrentIndex(PAGE_VIDEO)
        w._bars_visible = True
        e.current = STREAM
        try:
            with patch.object(e, "video_size", return_value=(854, 480)), patch.object(e, "visualizing", return_value=False):
                w._time_tick()
                self.assertEqual(w.bottom.quality.text(), "480p")
            with patch.object(e, "video_size", return_value=(1280, 720)), patch.object(e, "visualizing", return_value=False):
                w._time_tick()
                self.assertEqual(w.bottom.quality.text(), "720p")
            w.stage.setCurrentIndex(PAGE_AUDIO)
            w._time_tick()
            self.assertTrue(w.bottom.quality.isHidden())
        finally:
            e.current = None

    def test_audio_only_switch(self):
        w, e = self.win, self.win.engine
        box = w.sidebar.findChild(QCheckBox, "audio_only")
        self.assertFalse(box.isChecked())
        e.current = str(Path(self.temp.name) / "film.mkv")
        w.stage.setCurrentIndex(PAGE_VIDEO)
        try:
            with patch.object(e, "rebuild"), patch.object(w.now_playing, "load") as load:
                msg = w.set_audio_only(True)
            self.assertIn("Audio only", msg)
            self.assertTrue(self.store.setting("audio_only"))
            self.assertTrue(box.isChecked())
            self.assertEqual(w.stage.currentIndex(), PAGE_AUDIO)     # Now Playing, not a black picture
            load.assert_called_once()
            with patch.object(e, "rebuild"):
                box.setChecked(False)
            self.assertFalse(self.store.setting("audio_only"))
            w._action_table = None
            with patch.object(e, "rebuild"):
                w.do("audio_only", key=False)
            self.assertTrue(self.store.setting("audio_only"))
        finally:
            e.current = None

    def test_preferences(self):
        dialog = PreferencesDialog(self.win)
        try:
            buf = dialog.findChild(QComboBox, "network_buffer")
            self.assertEqual([buf.itemData(i) for i in range(buf.count())], [1, 3, 5, 10, 30, 60])
            buf.setCurrentIndex(buf.findData(60))
            self.assertEqual(self.store.setting("network_buffer"), 60)
            q = dialog.findChild(QComboBox, "max_stream_height")
            self.assertEqual(q.currentData(), 0)
            q.setCurrentIndex(q.findData(480))
            self.assertEqual(self.store.setting("max_stream_height"), 480)
            saver = dialog.findChild(QCheckBox, "battery_saver")
            extra = dialog.findChild(QLineEdit, "vlc_extra_args")
            e = self.win.engine
            with patch.object(e, "rebuild") as rebuild, patch.object(type(e), "ok", new=True):
                saver.setChecked(True)
                extra.setText("--network-caching=5000")
                dialog._set_vlc_extra_args(extra.text())
            self.assertTrue(self.store.setting("battery_saver"))
            self.assertEqual(self.store.setting("vlc_extra_args"), "--network-caching=5000")
            self.assertEqual(rebuild.call_count, 2)
            e.extra_args_failed = True
            dialog._show_extra_state()
            self.assertIn("wouldn't start", dialog.extra_note.text())
            e.extra_args_failed = False
        finally:
            dialog.deleteLater()


if __name__ == "__main__":
    unittest.main(verbosity=2)
