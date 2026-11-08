"""1.7.0 fixes and features.
#82: on Windows, VLC's video area gets a two-pixel nudge once the first frames are out, the same thing that
     opening a panel did, so a black 10-bit HEVC picture shows. With Super Resolution it redraws without
     ever letterboxing instead.
#83: rotation and the flips are separate choices: Flip H goes with 90° and 270° (VLC's transpose and
     antitranspose), and all eight ways to turn and mirror a picture can be picked.
#84: Shuffle -> Stop or Loop keeps the shuffled queue. Only In order puts it back in order.
#85: VLC's visualizations, picked in the Audio tab. Sound that's playing restarts at the same spot with it;
     a video keeps playing and the next file gets it. A visualization shows on the video page.
#86: the silence before and after a song is found from the sound Pylon already reads for the waveform;
     playback skips past the first and ends the song at the second."""
import array
import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEventLoop, QRect, QTimer
from PySide6.QtWidgets import QApplication
from app import engine, waveform
engine.vlc = None
from app.engine import VISUALIZERS, VLC_TRANSFORMS, Engine, compose_transform, transform_parts
from app.stage import PAGE_AUDIO, PAGE_VIDEO
from app.store import Store
from app.window import MainWindow

app = QApplication.instance() or QApplication([])


def wait(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def fake_player(tracks=1, vout=0, size=(1920, 1080)):
    p = MagicMock()
    p.video_get_size.return_value = size
    p.video_get_track.return_value = 1
    p.video_get_track_count.return_value = tracks
    p.has_vout.return_value = vout
    p.get_media.return_value = None
    p.is_playing.return_value = 1
    p.get_time.return_value = 0
    p.get_length.return_value = 200000
    p.audio_get_volume.return_value = 80
    p.get_state.return_value = "State.Playing"
    return p


def corners(m):
    """Where the top-left, top-right and bottom-left corners of a picture end up under matrix m."""
    pts = {"TL": (-1, -1), "TR": (1, -1), "BL": (-1, 1)}
    return {k: (m[0] * x + m[1] * y, m[2] * x + m[3] * y) for k, (x, y) in pts.items()}


class RotateAndFlip(unittest.TestCase):
    """#83. The matrices were checked against real VLC 3.0 snapshots: 90 turns clockwise, transpose swaps
    the top-right and bottom-left corners."""

    def test_flip_h_goes_with_every_rotation(self):
        self.assertEqual(compose_transform(0, flip_h=True), "hflip")
        self.assertEqual(compose_transform(90, flip_h=True), "transpose")
        self.assertEqual(compose_transform(180, flip_h=True), "vflip")
        self.assertEqual(compose_transform(270, flip_h=True), "antitranspose")

    def test_all_eight_pictures_can_be_made(self):
        made = {compose_transform(r, h, v) for r in (0, 90, 180, 270) for h in (0, 1) for v in (0, 1)}
        self.assertEqual(made, set(VLC_TRANSFORMS))

    def test_flip_is_applied_to_the_turned_picture(self):
        # turned 90° clockwise, the top-left corner is at the top right; mirroring that puts it back top left
        c = corners(VLC_TRANSFORMS[compose_transform(90, flip_h=True)])
        self.assertEqual(c["TL"], (-1, -1))
        self.assertEqual(c["TR"], (-1, 1))          # what was top right is now bottom left: a transpose

    def test_every_value_reads_back(self):
        for value in VLC_TRANSFORMS:
            self.assertEqual(compose_transform(*transform_parts(value)), value)

    def test_engine_keeps_the_parts(self):
        with tempfile.TemporaryDirectory() as d:
            e = Engine(Store(str(Path(d) / "data.json")))
            e.rotate, e.flip_h = 270, True
            self.assertEqual(e.transform, "antitranspose")
            e.transform = "90"                       # older code and the checks still set the value
            self.assertEqual((e.rotate, e.flip_h, e.flip_v), (90, False, False))


class Window(unittest.TestCase):
    def make(self, **settings):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))
        self.store.set_setting("onboarded", True)
        for k, v in settings.items():
            self.store.set_setting(k, v)
        with patch.object(MainWindow, "_welcome", lambda self: None), patch.object(MainWindow, "_vlc_missing"):
            self.win = MainWindow(self.store)
        self.win._vlc_missing = lambda: None
        self.toasts = []
        self.win.toast = lambda text, *a, **k: self.toasts.append(text)
        self.win.resize(1100, 700)
        self.win.show()
        self.win._ui_timer.stop()
        wait(80)
        return self.win

    def tearDown(self):
        w = getattr(self, "win", None)
        if w is not None:
            w.engine.player = None
            w.close()
            self.temp.cleanup()


class RotateFlipPanel(Window):
    def test_flip_h_stays_on_when_turning(self):
        w = self.make()
        e, sb = w.engine, w.sidebar
        e.rebuild = MagicMock()
        sb.flip_h.click()
        self.assertEqual(e.transform, "hflip")
        sb.rotate.group.button(1).click()            # 90°
        self.assertEqual(e.transform, "transpose")
        self.assertTrue(sb.flip_h.isChecked())
        sb.rotate.group.button(3).click()            # 270°
        self.assertEqual(e.transform, "antitranspose")
        self.assertEqual(self.toasts[-1], "Rotation: 270°, flipped")
        sb.flip_h.click()
        self.assertEqual(e.transform, "270")
        self.assertEqual(e.rebuild.call_count, 4)

    def test_panel_shows_what_the_engine_has(self):
        w = self.make()
        w.engine.transform = "transpose"
        w.sidebar.show_transform()
        self.assertTrue(w.sidebar.flip_h.isChecked())
        self.assertFalse(w.sidebar.flip_v.isChecked())
        self.assertTrue(w.sidebar.rotate.group.button(1).isChecked())


class QueueShuffle(Window):
    """#84"""

    def fill(self, n=30, at=4):
        w = self.win
        w.play_path = lambda path, **kw: setattr(w.engine, "current", path)
        w.play_queue_index = lambda i, **kw: setattr(w, "qindex", i)
        w.set_queue([{"path": f"C:/v/ep{i:02}.mkv"} for i in range(n)], at)

    def names(self):
        return [Path(q["path"]).name for q in self.win.queue]

    def test_stop_and_loop_keep_the_shuffled_queue(self):
        w = self.make()
        self.fill()
        ordered = self.names()
        for mode in ("none", "loop"):
            w.set_queue_mode("shuffle")
            mixed = self.names()
            self.assertNotEqual(mixed, ordered)
            w.set_queue_mode(mode)
            self.assertEqual(self.names(), mixed, mode)
            w.set_queue_mode("shuffle")                  # back to Shuffle: still the same order
            self.assertEqual(self.names(), mixed, mode)
            w.set_queue_mode("next")                     # In order puts it back
            self.assertEqual(self.names(), ordered, mode)
            self.assertEqual(self.names()[w.qindex], "ep04.mkv")

    def test_in_order_after_stop_remembers_the_order(self):
        w = self.make()
        self.fill()
        ordered = self.names()
        w.set_queue_mode("shuffle")
        w.set_queue_mode("none")
        w.set_queue_mode("loop")
        w.set_queue_mode("next")
        self.assertEqual(self.names(), ordered)

    def test_the_sidebar_buttons_do_the_same(self):
        w = self.make()
        self.fill()
        keys = w.sidebar.queue_mode.values
        w.sidebar.queue_mode.group.button(keys.index("shuffle")).click()
        mixed = self.names()
        w.sidebar.queue_mode.group.button(keys.index("none")).click()
        self.assertEqual(w.queue_mode, "none")
        self.assertEqual(self.names(), mixed)


class BlackPicture(Window):
    """#82"""

    def test_windows_nudges_the_video_area_once_it_plays(self):
        w = self.make()
        e = w.engine
        e.player = fake_player()
        e.current = "C:/v/hevc10.mkv"
        w.stage.setCurrentIndex(PAGE_VIDEO)
        wait(50)
        full = w.video.canvas.geometry()
        sizes = []
        w.video.canvas.resizeEvent = lambda ev: sizes.append((ev.size().width(), ev.size().height()))
        with patch.object(engine.sys, "platform", "win32"):
            e._on_vout()
        wait(1700)
        self.assertIn((full.width(), full.height() - 2), sizes)
        self.assertEqual(sizes[-1], (full.width(), full.height()))
        self.assertEqual(w.video.canvas.geometry(), full)
        self.assertEqual(sizes.count((full.width(), full.height() - 2)), 2)     # at 300 ms and at 1.2 s

    def test_other_systems_are_left_alone(self):
        w = self.make()
        fired = []
        w.engine.wake_picture.connect(lambda: fired.append(1))
        w.engine.player = fake_player()
        with patch.object(engine.sys, "platform", "linux"):
            w.engine._on_vout()
        wait(1400)
        self.assertEqual(fired, [])

    def test_super_resolution_redraws_without_letterboxing(self):
        w = self.make()
        w.engine.player = fake_player()
        w.engine.current = "C:/v/hevc10.mkv"
        w.stage.setCurrentIndex(PAGE_VIDEO)
        w.engine.refresh_upscaler = MagicMock()
        before = QRect(w.video.canvas.geometry())
        with patch.object(MainWindow, "_vsr_active", lambda self: True):
            w._wake_picture()
        self.assertEqual(w.engine.refresh_upscaler.call_count, 1)
        self.assertEqual(w.video.canvas.geometry(), before)

    def test_nothing_happens_on_the_music_page(self):
        w = self.make()
        w.engine.player = fake_player()
        w.engine.current = "C:/m/song.mp3"
        w.stage.setCurrentIndex(PAGE_AUDIO)
        before = QRect(w.video.canvas.geometry())
        w._wake_picture()
        self.assertEqual(w.video.canvas.geometry(), before)


class Visualizations(Window):
    """#85"""

    def test_vlc_options(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(str(Path(d) / "data.json"))
            e = Engine(s)
            self.assertFalse(any(a.startswith("--audio-visual") for a in e._args()))
            s.set_setting("visualizer", "spectrum")
            self.assertIn("--audio-visual=visual", e._args())
            self.assertIn("--effect-list=spectrum", e._args())
            s.set_setting("visualizer", "goom")
            self.assertIn("--audio-visual=goom", e._args())

    def test_audio_tab_lists_them(self):
        w = self.make()
        self.assertEqual(w.sidebar.visualizer.values, list(VISUALIZERS))
        self.assertTrue(w.sidebar.visualizer.group.button(0).isChecked())

    def test_a_song_restarts_with_it_and_a_video_waits(self):
        w = self.make()
        e = w.engine
        e.player = fake_player(tracks=0)
        e.current = "C:/m/song.mp3"
        e.rebuild = MagicMock()
        w.sidebar.visualizer.group.button(w.sidebar.visualizer.values.index("scope")).click()
        self.assertEqual(self.store.setting("visualizer"), "scope")
        self.assertEqual(e.rebuild.call_count, 1)
        self.assertEqual(self.toasts[-1], "Visualization: Scope")
        e.player = fake_player(tracks=1)
        e.current = "C:/v/film.mkv"
        w.sidebar.visualizer.group.button(w.sidebar.visualizer.values.index("spectrum")).click()
        self.assertEqual(e.rebuild.call_count, 1)                 # the film keeps playing
        self.assertTrue(e._args_stale)
        self.assertEqual(self.toasts[-1], "Visualization: Spectrum, from the next song")
        renewed = []
        e._renew = lambda vol: (renewed.append(vol), setattr(e, "_args_stale", False))
        e._audio_pending = {}                                    # set when a real player is built
        with patch.object(e, "instance", MagicMock(), create=True):
            e.open("/tmp/next-song.mp3")
        self.assertEqual(len(renewed), 1)

    def test_visualization_shows_on_the_video_page(self):
        w = self.make(visualizer="spectrum")
        e = w.engine
        e.player = fake_player(tracks=0, vout=1)
        e.current = "C:/m/song.mp3"
        w.stage.setCurrentIndex(PAGE_AUDIO)
        w._sync_audio_page()
        self.assertEqual(w.stage.currentIndex(), PAGE_VIDEO)
        self.store.set_setting("visualizer", "")              # turned off: VLC drops its video output
        e.player.has_vout.return_value = 0
        w._sync_audio_page()
        self.assertEqual(w.stage.currentIndex(), PAGE_AUDIO)

    def test_a_video_is_never_moved(self):
        w = self.make(visualizer="spectrum")
        w.engine.player = fake_player(tracks=1, vout=1)
        w.engine.current = "C:/v/film.mkv"
        w.stage.setCurrentIndex(PAGE_VIDEO)
        w._sync_audio_page()
        self.assertEqual(w.stage.currentIndex(), PAGE_VIDEO)
        self.assertFalse(w.engine.visualizing())


class SilenceBounds(unittest.TestCase):
    """#86: where the sound starts and ends."""

    def make_wav(self, d, parts, rate=2000):
        data = array.array("h")
        for seconds, level in parts:
            n = int(seconds * rate)
            data.extend((level if i % 2 else -level) for i in range(n))
        p = os.path.join(d, "s.wav")
        with wave.open(p, "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(rate)
            f.writeframes(data.tobytes())
        return p

    def test_leading_and_trailing_silence(self):
        with tempfile.TemporaryDirectory() as d:
            p = self.make_wav(d, [(2.0, 0), (5.0, 8000), (3.0, 20)])     # 20 is below -50 dB: silence
            self.assertEqual(waveform.silence_from_wav(p), (2000 - waveform.LEAD_IN_MS, 7000 + waveform.TAIL_MS, 10000))

    def test_all_silent_and_no_silence(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(waveform.silence_from_wav(self.make_wav(d, [(1.0, 0)])))
            self.assertEqual(waveform.silence_from_wav(self.make_wav(d, [(1.0, 9000)])), (0, 1000, 1000))

    def test_cache_keeps_it(self):
        with tempfile.TemporaryDirectory() as d:
            song = Path(d) / "a.mp3"
            song.write_bytes(b"x")
            with patch.object(waveform, "data_dir", lambda: d):
                m = waveform.WaveformMaker()
                m._save_cache(str(song), [0.5, 1.0], (1850, 7400, 10000))
                self.assertEqual(m._load_cache(str(song)), ([0.5, 1.0], (1850, 7400, 10000)))
                with open(m._cache_path(str(song)), "w") as f:
                    f.write('{"version": 1, "peaks": [1.0]}')        # 1.6 caches are read again
                self.assertIsNone(m._load_cache(str(song)))


class TrimSilence(Window):
    """#86: playback."""

    def play(self, w, now_ms=0):
        e = w.engine
        e.player = fake_player(tracks=0)
        e.player.get_time.return_value = now_ms
        e.current = "C:/m/song.mp3"
        e.seek = MagicMock()
        e.finish = MagicMock()

    def test_off_by_default(self):
        w = self.make()
        self.play(w)
        w._silence_ready("C:/m/song.mp3", 1850, 7400, 10000)
        self.assertIsNone(w._trim)
        self.assertFalse(w._wants_trim("C:/m/song.mp3"))

    def test_skips_the_start_and_ends_at_the_silence(self):
        w = self.make(trim_silence=True)
        self.play(w, now_ms=200)
        w._silence_ready("C:/m/song.mp3", 1850, 7400, 10000)
        w.engine.seek.assert_called_once_with(1850)
        w.engine.player.get_time.return_value = 7000
        w._trim_tick()
        w.engine.finish.assert_not_called()
        w.engine.player.get_time.return_value = 7450
        w._trim_tick()
        w._trim_tick()
        w.engine.finish.assert_called_once()

    def test_no_jump_back_once_past_the_start(self):
        w = self.make(trim_silence=True)
        self.play(w, now_ms=30000)                    # resumed later in the song
        w._silence_ready("C:/m/song.mp3", 1850, 70000, 90000)
        w.engine.seek.assert_not_called()

    def test_waits_for_playback_to_start(self):
        w = self.make(trim_silence=True)
        self.play(w)
        w.engine.player.get_state.return_value = "State.Opening"
        w._silence_ready("C:/m/song.mp3", 1850, 7400, 10000)       # from the cache, before VLC plays
        w.engine.seek.assert_not_called()
        w.engine.player.get_state.return_value = "State.Playing"
        w._on_state("playing")
        w.engine.seek.assert_called_once_with(1850)

    def test_short_gaps_and_videos_are_left_alone(self):
        w = self.make(trim_silence=True)
        self.play(w)
        w._silence_ready("C:/m/song.mp3", 100, 9700, 10000)        # a breath at each end
        self.assertEqual(w._trim, (0, None))
        w.engine.seek.assert_not_called()
        self.assertFalse(w._wants_trim("C:/v/film.mkv"))

    def test_a_repeated_part_wins(self):
        w = self.make(trim_silence=True)
        self.play(w)
        w._silence_ready("C:/m/song.mp3", 0, 7400, 10000)
        w.ab_loop = [5000, 9000]
        w.engine.player.get_time.return_value = 8000
        w._trim_tick()
        w.engine.finish.assert_not_called()

    def test_reads_the_sound_even_with_the_waveform_off(self):
        w = self.make(trim_silence=True, seek_waveform="off")
        self.play(w)
        started = []
        w.waves.start = lambda path: started.append(path)
        w.start_waveform()
        self.assertEqual(started, ["C:/m/song.mp3"])
        w._wave_ready("C:/m/song.mp3", [0.5, 1.0])
        self.assertEqual(w.bottom.seek.wave, [])           # no waveform shown, as asked

    def test_audio_tab_checkbox(self):
        w = self.make()
        self.play(w)
        w.start_waveform = MagicMock()
        w.sidebar.trim_silence.setChecked(True)
        self.assertTrue(self.store.setting("trim_silence"))
        w.start_waveform.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
