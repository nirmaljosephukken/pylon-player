"""DVDs: .iso images and VIDEO_TS folders open with their menus, the arrow keys and Enter move
around a disc menu, titles can be picked, and Pylon picks up the title and time you stopped at."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from app import engine
engine.vlc = None
from app.engine import NAV_ACTIVATE, NAV_DOWN, NAV_LEFT, NAV_RIGHT, NAV_UP, Engine
from app.library import ROLE_PATH
from app.store import Store
from app.util import disc_mrl, is_disc, is_dvd_folder, is_media, list_media
from app.window import MainWindow

app = QApplication.instance() or QApplication([])


class Title:
    def __init__(self, duration, name, flags):
        self.duration, self.name, self.flags = duration, name, flags


class FakeDisc:
    """Stands in for libVLC's player with a disc open: title 0 is the menu."""
    def __init__(self):
        self.title, self.nav, self.time, self.paused = 0, [], 0, False
        self.titles = [Title(0, b"DVD Menu", 3), Title(30_000, None, 0), Title(20_000, None, 0)]

    def get_full_title_descriptions(self):
        return (t for t in self.titles)      # python-vlc hands back a generator

    def get_title(self): return self.title
    def set_title(self, i): self.title = i
    def navigate(self, mode): self.nav.append(mode)
    def get_time(self): return self.time
    def set_time(self, ms): self.time = ms
    def get_length(self): return self.titles[self.title].duration or 2000
    def is_playing(self): return not self.paused
    def get_state(self): return "playing"


class Media:
    def __init__(self, mrl): self.mrl, self.options = mrl, []
    def add_option(self, o): self.options.append(o)


class FakeInstance:
    def media_new(self, mrl): return Media(mrl)
    def media_new_path(self, p): return Media(("path", p))


class Helpers(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.d = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def dvd(self, name="Film", ifo="VIDEO_TS.IFO"):
        ts = self.d / name / "VIDEO_TS"
        ts.mkdir(parents=True)
        (ts / ifo).touch()
        (ts / "VTS_01_1.VOB").touch()
        return str(self.d / name)

    def test_iso_is_media_and_a_disc(self):
        iso = str(self.d / "Film.iso")
        Path(iso).touch()
        self.assertTrue(is_media(iso))
        self.assertTrue(is_disc(iso))
        self.assertIn(iso, list_media(str(self.d)))
        self.assertEqual(disc_mrl(iso), iso)          # VLC opens an .iso as a file

    def test_dvd_folders(self):
        film = self.dvd()
        self.assertTrue(is_dvd_folder(film))
        self.assertTrue(is_dvd_folder(os.path.join(film, "VIDEO_TS")))
        self.assertTrue(disc_mrl(film).startswith("dvd:///"))
        self.assertNotIn("\\", disc_mrl(film))
        lower = self.dvd("Lower", ifo="video_ts.ifo")    # Linux file systems keep case
        self.assertTrue(is_dvd_folder(lower))
        (self.d / "Plain").mkdir()
        self.assertFalse(is_dvd_folder(str(self.d / "Plain")))
        self.assertFalse(is_disc(str(self.d / "Plain")))
        self.assertFalse(is_disc("https://example.test/a.mp4"))
        self.assertTrue(is_disc("dvd:///E:/"))


class EngineDisc(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))
        self.e = Engine(self.store)
        self.iso = str(Path(self.temp.name) / "Film.iso")
        Path(self.iso).touch()

    def tearDown(self):
        self.temp.cleanup()

    def test_titles_menu_and_navigation(self):
        e = self.e
        e.player = FakeDisc()
        e.current = self.iso
        self.assertEqual([t[1:] for t in e.titles()],
                         [("DVD Menu", 0, True), ("Title 1", 30_000, False), ("Title 2", 20_000, False)])
        self.assertTrue(e.in_menu())
        e.navigate(NAV_DOWN)
        self.assertEqual(e.player.nav, [NAV_DOWN])
        e.set_title(2)
        self.assertFalse(e.in_menu())
        self.assertTrue(e.disc_menu())
        self.assertEqual(e.title(), 0)

    def test_not_a_disc(self):
        e = self.e
        e.player = FakeDisc()
        e.current = str(Path(self.temp.name) / "Film.mkv")
        self.assertEqual(e.titles(), [])
        self.assertFalse(e.in_menu())
        self.assertFalse(e.disc_menu())

    def test_open_starts_at_the_menu(self):
        e = self.e

        class Player(FakeDisc):
            def set_media(self, m): self.media = m
            def play(self): pass
        e.player, e.instance = Player(), FakeInstance()
        e.open(self.iso, start_ms=60_000)
        self.assertEqual(e.player.media.mrl, ("path", os.path.normpath(self.iso)))
        self.assertEqual(e.player.media.options, [])          # no start-time: that would skip into the menu
        folder = Path(self.temp.name) / "DVD" / "VIDEO_TS"
        folder.mkdir(parents=True)
        (folder / "VIDEO_TS.IFO").touch()
        e.open(str(folder.parent), start_ms=5000)
        self.assertTrue(e.player.media.mrl.startswith("dvd:///"))


class WindowDisc(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.d = Path(self.temp.name)
        self.store = Store(str(self.d / "data.json"))
        self.store.set_setting("onboarded", True)
        with patch.object(MainWindow, "_welcome", lambda self: None), patch.object(MainWindow, "_vlc_missing"):
            self.win = MainWindow(self.store)
        self.win._vlc_missing = lambda: None
        self.toasts = []
        self.win.toast = lambda msg, *a, **k: self.toasts.append(msg)
        self.iso = str(self.d / "Film.iso")
        Path(self.iso).touch()

    def tearDown(self):
        self.win.close()
        self.temp.cleanup()

    def playing_disc(self):
        e = self.win.engine
        e.player = FakeDisc()
        e.current = self.iso
        return e

    def test_keys_move_around_the_menu(self):
        e = self.playing_disc()
        w = self.win
        for action in ("vol_up", "vol_down", "seek_back", "seek_fwd", "play_pause", "fullscreen_enter"):
            w.do(action)
        self.assertEqual(e.player.nav, [NAV_UP, NAV_DOWN, NAV_LEFT, NAV_RIGHT, NAV_ACTIVATE, NAV_ACTIVATE])
        self.assertFalse(w.isFullScreen())

    def test_keys_work_normally_in_a_title(self):
        e = self.playing_disc()
        e.player.title = 1
        e.player.time = 20_000
        self.win.do("seek_back")
        self.assertEqual(e.player.nav, [])
        self.assertEqual(e.player.time, 10_000)

    def test_menu_hint_and_titles_in_the_panel(self):
        e = self.playing_disc()
        w = self.win
        w._disc_tick()
        self.assertTrue(any("Disc menu" in t for t in self.toasts))
        w.sidebar.refresh_disc()
        self.assertFalse(w.sidebar.disc_box.isHidden())
        combo = w.sidebar.title_combo
        self.assertEqual(combo.count(), 3)
        self.assertIn("0:30", combo.itemText(1))
        w.play_title(2)
        self.assertEqual(e.title(), 2)
        self.assertEqual(combo.currentData(), 2)
        e.current = str(self.d / "Film.mkv")
        w.sidebar.refresh_disc()
        self.assertTrue(w.sidebar.disc_box.isHidden())     # only shown for discs

    def test_disc_menu_in_the_right_click_menu(self):
        self.playing_disc()
        m = self.win.build_disc_menu()
        texts = [a.text() for a in m.actions() if a.text()]
        self.assertEqual(texts[0], "Disc menu")
        self.assertTrue(any(t.startswith("Title 1") for t in texts))

    def test_position_keeps_the_title_and_skips_menus(self):
        e = self.playing_disc()
        w = self.win
        e.player.time = 1500
        w._save_position()
        self.assertEqual(self.store.position(self.iso), {})     # the menu loop isn't saved
        e.player.title, e.player.time = 2, 12_000
        w._save_position()
        pos = self.store.position(self.iso)
        self.assertEqual((pos["title"], pos["pos"], pos["len"]), (2, 12_000, 20_000))

    def test_resume_goes_to_the_title_then_the_time(self):
        e = self.playing_disc()
        w = self.win
        seeks = []
        e.seek = lambda ms: seeks.append(ms)
        w._resume_title, w._resume_ms = 2, 12_000
        w._accept_resume()
        self.assertEqual(e.title(), 2)
        from PySide6.QtCore import QEventLoop, QTimer
        loop = QEventLoop()
        QTimer.singleShot(900, loop.quit)
        loop.exec()
        self.assertEqual(seeks, [12_000])

    def test_dvd_folder_plays_as_one_disc(self):
        ts = self.d / "Film" / "VIDEO_TS"
        ts.mkdir(parents=True)
        for f in ("VIDEO_TS.IFO", "VTS_01_1.VOB", "VTS_01_2.VOB"):
            (ts / f).touch()
        played = []
        w = self.win
        w.play_path = lambda path, **kw: played.append(path)
        w.play_folder(str(ts.parent))
        self.assertEqual(played, [os.path.normpath(str(ts.parent))])
        self.assertEqual(len(w.queue), 1)
        lib = w.library
        lib.store.data["library_folders"] = [str(self.d)]
        lib.open_folder(str(self.d))
        item = next(lib.lib_list.item(i) for i in range(lib.lib_list.count())
                    if lib.lib_list.item(i).data(ROLE_PATH) == str(ts.parent))
        lib._lib_activate(item)
        self.assertEqual(len(played), 2)                # double-click plays it instead of opening it

    def test_no_previews_or_waveform_for_discs(self):
        e = self.playing_disc()
        started = []
        self.win.thumbs.start = lambda *a: started.append("thumbs")
        self.win.waves.start = lambda *a: started.append("waves")
        self.store.set_setting("seek_waveform", "all")
        self.win.start_previews()
        self.win.start_waveform()
        self.assertEqual(started, [])
        self.assertTrue(e.is_disc())


if __name__ == "__main__":
    unittest.main()
