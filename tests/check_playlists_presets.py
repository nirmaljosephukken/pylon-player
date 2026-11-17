"""1.7.2 review fixes for playlists, presets and smaller edge cases.

C1: .pls and .xspf playlists are read into their entries (they used to become lines of text).
C2: file:/// entries (VLC, foobar2000 exports) become local paths; relative entries are resolved against the
    playlist's folder; links stay links.
H2: a playlist dropped on the queue, picked with other files, added to the queue or to a saved playlist
    brings its entries, at that place, instead of sitting there as one item that can't play.
H3: a file from another folder with no preset starts with the default picture (aspect, crop, zoom, colours),
    not the last show's.
M2, M7, L3: a stream that ends records nothing; Home counts playlist progress as the Playlists tab does;
    after Close no queue item is marked as playing.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from app import engine
engine.vlc = None
from app.store import Store
from app.util import expand_playlists, parse_pls, parse_xspf, read_playlist
from app.window import MainWindow

app = QApplication.instance() or QApplication([])


def wait(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class Parsing(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.d = Path(self.temp.name)
        (self.d / "music").mkdir()
        for n in ("a b.mp3", "c.mp3", "d.flac"):
            (self.d / "music" / n).write_bytes(b"")

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, text, encoding="utf-8"):
        p = self.d / name
        p.write_text(text, encoding=encoding)
        return str(p)

    def music(self, name):
        return os.path.normpath(str(self.d / "music" / name))

    def test_m3u_with_file_uris_relative_paths_and_links(self):
        uri = (self.d / "music" / "a b.mp3").as_uri()               # file:///…/a%20b.mp3, as VLC writes it
        p = self.write("vlc.m3u8", f"#EXTM3U\n#EXTINF:120,Artist - Song A\n{uri}\n"
                                   "music/c.mp3\n#EXTINF:-1,Radio\nhttp://radio.test/live\n")
        got = read_playlist(p)
        self.assertEqual(got, [("Artist - Song A", self.music("a b.mp3")), ("c", self.music("c.mp3")),
                               ("Radio", "http://radio.test/live")])

    def test_pls(self):
        p = self.write("list.pls", "[playlist]\nFile1=music/c.mp3\nTitle1=Song C\n"
                                   f"File2={(self.d / 'music' / 'a b.mp3').as_uri()}\n"
                                   "File3=http://radio.test/stream\nTitle3=Radio\nNumberOfEntries=3\nVersion=2\n")
        self.assertEqual(read_playlist(p), [("Song C", self.music("c.mp3")), ("a b", self.music("a b.mp3")),
                                            ("Radio", "http://radio.test/stream")])
        # in File number order, whatever order the lines are in
        self.assertEqual([u for _n, u in parse_pls("[playlist]\nFile2=b\nFile1=a\n")], ["a", "b"])

    def test_xspf(self):
        uri = (self.d / "music" / "a b.mp3").as_uri()
        p = self.write("list.xspf", f"""<?xml version="1.0" encoding="UTF-8"?>
<playlist xmlns="http://xspf.org/ns/0/" version="1">
  <title>Mix</title>
  <trackList>
    <track><location>{uri}</location><title>Song A</title></track>
    <track><location>music/d.flac</location></track>
    <track><location>https://radio.test/x.mp3</location><title>Online</title></track>
  </trackList>
</playlist>""")
        self.assertEqual(read_playlist(p), [("Song A", self.music("a b.mp3")), ("d", self.music("d.flac")),
                                            ("Online", "https://radio.test/x.mp3")])
        self.assertEqual(parse_xspf("<not xml"), [])

    def test_not_a_list(self):
        p = self.write("live.m3u8", "#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXTINF:6,\nseg1.ts\n")
        self.assertEqual(read_playlist(p), [])                     # an HLS stream: VLC plays it as one
        self.assertEqual(read_playlist(str(self.d / "missing.m3u")), [])

    def test_older_encoding(self):
        p = self.d / "old.m3u"
        p.write_bytes("#EXTINF:1,Caf\xe9\nmusic/c.mp3\n".encode("latin-1"))
        got = read_playlist(str(p))
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0][1], self.music("c.mp3"))

    def test_expand_in_place(self):
        pl = self.write("two.m3u", "music/c.mp3\nmusic/d.flac\n")
        a = self.music("a b.mp3")
        self.assertEqual([p for _n, p in expand_playlists([a, pl, "http://x.test/s"])],
                         [a, self.music("c.mp3"), self.music("d.flac"), "http://x.test/s"])


class WindowPlaylists(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.d = Path(self.temp.name)
        for show in ("ShowA", "ShowB"):
            (self.d / show).mkdir()
            for i in (1, 2):
                (self.d / show / f"ep{i}.mkv").write_bytes(b"")
        self.pl = self.d / "list.m3u"
        self.pl.write_text("ShowB/ep1.mkv\nShowB/ep2.mkv\n", encoding="utf-8")
        self.store = Store(str(self.d / "data.json"))
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

    def p(self, rel):
        return os.path.normpath(str(self.d / rel))

    def test_dropped_on_the_queue(self):
        w = self.win
        w.queue = [{"path": self.p("ShowA/ep1.mkv")}, {"path": self.p("ShowA/ep2.mkv")}]
        w.qindex = 0
        w.engine.current = self.p("ShowA/ep1.mkv")       # something plays, so nothing new starts
        w.insert_into_queue([str(self.pl)], 1)
        self.assertEqual([q["path"] for q in w.queue], [self.p("ShowA/ep1.mkv"), self.p("ShowB/ep1.mkv"),
                                                        self.p("ShowB/ep2.mkv"), self.p("ShowA/ep2.mkv")])

    def test_added_to_the_queue_and_opened_with_other_files(self):
        w = self.win
        played = []
        with patch.object(MainWindow, "play_queue_index", lambda self, i, **k: played.append(i)):
            w.open_paths([self.p("ShowA/ep1.mkv"), str(self.pl)])
            self.assertEqual(sorted(q["path"] for q in w.queue),
                             sorted([self.p("ShowA/ep1.mkv"), self.p("ShowB/ep1.mkv"), self.p("ShowB/ep2.mkv")]))
            w.engine.current = self.p("ShowA/ep1.mkv")
            w.enqueue([str(self.pl)])
        self.assertNotIn(self.p("list.m3u"), [q["path"] for q in w.queue])
        self.assertEqual(len(w.queue), 5)

    def test_saved_playlist_gets_the_entries(self):
        lib = self.win.library
        lib.add_to_playlist("Mine", [str(self.pl)])
        self.assertEqual(self.store.data["playlists"]["Mine"], [self.p("ShowB/ep1.mkv"), self.p("ShowB/ep2.mkv")])

    def test_another_show_without_a_preset_starts_clean(self):
        w, e = self.win, self.win.engine
        self.store.data["presets"]["Wide"] = {"aspect": "4:3", "crop": "16:9", "zoom": 1.5,
                                             "adjust": {"brightness": 1.2, "contrast": 1.0, "saturation": 1.0,
                                                        "hue": 0.0, "gamma": 1.0}}
        self.store.data["folder_preset"][self.p("ShowA")] = "Wide"
        from unittest.mock import MagicMock
        e.player = MagicMock()                           # just enough of a player; nothing is opened
        e.player.get_time.return_value = e.player.get_length.return_value = 0
        e.player.audio_get_volume.return_value, e.player.audio_get_mute.return_value = 80, 0
        with patch.object(engine.Engine, "open", lambda *a, **k: None), \
                patch.object(MainWindow, "_save_position", lambda self: None):
            w.play_path(self.p("ShowA/ep1.mkv"))
            self.assertEqual(e.live["aspect"], "4:3")
            e.live["rate"] = 1.25                        # a speed you picked yourself carries on
            w.play_path(self.p("ShowB/ep1.mkv"))
            self.assertEqual((e.live["aspect"], e.live["crop"], e.live["zoom"], e.live["adjust"]),
                             ("", "", 0.0, None))
            self.assertEqual(e.live["rate"], 1.25)
            e.live["aspect"] = "21:9"                    # set by hand in ShowB
            w.play_path(self.p("ShowB/ep2.mkv"))         # the next episode of the same show keeps it
            self.assertEqual(e.live["aspect"], "21:9")
            w.play_path(self.p("ShowA/ep2.mkv"))         # back to ShowA: its preset again
            self.assertEqual((e.live["aspect"], e.live["zoom"]), ("4:3", 1.5))

    def test_stream_end_records_nothing(self):
        w = self.win
        w.engine.current = "http://radio.test/live"
        with patch.object(MainWindow, "play_next", lambda self, user=False: False):
            w._on_ended()
        self.assertNotIn("http://radio.test/live", self.store.data["positions"])
        self.store.set_setting("remember_history", False)
        w.engine.current = self.p("ShowA/ep1.mkv")
        with patch.object(MainWindow, "play_next", lambda self, user=False: False):
            w._on_ended()
        self.assertNotIn(self.p("ShowA/ep1.mkv"), self.store.data["positions"])

    def test_home_and_library_count_alike(self):
        a, b = self.p("ShowA/ep1.mkv"), "http://radio.test/live"
        self.store.set_watched(a, True)
        self.assertEqual(self.win.library.playlist_progress([a, b]), (1, 1, 1.0))   # streams don't count

    def test_nothing_marked_playing_after_close(self):
        w = self.win
        w.queue = [{"path": self.p("ShowA/ep1.mkv")}]
        w.qindex = 0
        w.engine.current = self.p("ShowA/ep1.mkv")
        w.library.refresh_queue()
        self.assertTrue(w.library.queue.item(0).font().bold())        # playing
        w.engine.current = None                                         # after Close
        w.library.refresh_queue()
        self.assertFalse(w.library.queue.item(0).font().bold())


if __name__ == "__main__":
    unittest.main()
