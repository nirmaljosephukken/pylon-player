"""Music: Shuffle all, and sorting by Recently played and Most played. Playlists: sorting by how
much of each you've watched. Plus the 1.6.0 split of the two biggest files into modules."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from app import engine
engine.vlc = None
from app.library import LibraryPanel, ROLE_KIND, ROLE_PATH
from app.store import Store
from app.window import MainWindow

app = QApplication.instance() or QApplication([])


class Sorting(unittest.TestCase):
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
        self.lib = self.win.library
        songs = {}
        for album, titles in (("Blue", ("Alpha", "Beta")), ("Red", ("Gamma", "Delta", "Epsilon"))):
            for i, t in enumerate(titles, 1):
                p = str(self.d / album / f"{i:02d} {t}.mp3")
                Path(p).parent.mkdir(exist_ok=True)
                Path(p).touch()
                songs[p] = {"title": t, "artist": "Band", "album": album, "track": i, "dur": 1000}
        self.songs = songs
        self.lib.music.songs = songs
        self.lib.music.scanning = False
        self.lib._music_stale = False

    def tearDown(self):
        self.win.close()
        self.temp.cleanup()

    def song(self, title):
        return next(p for p, s in self.songs.items() if s["title"] == title)

    def shown(self):
        lst = self.lib.music_list
        return [lst.item(i).data(ROLE_PATH) for i in range(lst.count()) if lst.item(i).data(ROLE_KIND)]

    def set_sort(self, value):
        combo = self.lib.music_sort
        combo.setCurrentIndex(combo.findData(value))

    def test_plays_are_counted_and_forgotten(self):
        s = self.store
        p = self.song("Beta")
        s.count_play(p)
        s.count_play(p)
        self.assertEqual(s.plays(p)["n"], 2)
        s.clear_history()
        self.assertEqual(s.plays(p), {})
        s.set_setting("remember_history", False)
        s.count_play(p)
        self.assertEqual(s.plays(p), {})

    def test_songs_by_recently_and_most_played(self):
        lib = self.lib
        self.store.data["plays"] = {self.song("Gamma"): {"n": 5, "t": 100}, self.song("Beta"): {"n": 1, "t": 300},
                                    self.song("Delta"): {"n": 2, "t": 200}}
        lib._music_mode("songs")
        self.set_sort("played")
        titles = [self.songs[p]["title"] for p in self.shown()]
        self.assertEqual(titles[:3], ["Beta", "Delta", "Gamma"])
        self.set_sort("plays")
        titles = [self.songs[p]["title"] for p in self.shown()]
        self.assertEqual(titles[:3], ["Gamma", "Delta", "Beta"])
        self.assertEqual(sorted(titles[3:]), ["Alpha", "Epsilon"])     # never played: after, by name

    def test_albums_by_most_played(self):
        lib = self.lib
        self.store.data["plays"] = {self.song("Alpha"): {"n": 1, "t": 900}, self.song("Gamma"): {"n": 4, "t": 10}}
        lib._music_mode("albums")
        self.set_sort("plays")
        self.assertTrue(self.shown()[0].endswith("red"))       # album keys are "artist\0album"
        self.set_sort("played")
        self.assertTrue(self.shown()[0].endswith("blue"))

    def test_shuffle_all_plays_every_song_in_the_view(self):
        lib = self.lib
        queued = []
        lib.play_songs = lambda paths, index=0: queued.append(list(paths))
        lib.shuffle_songs()
        self.assertEqual(sorted(queued[-1]), sorted(self.songs))
        self.assertIn("Shuffling 5 songs", self.toasts)
        red = next(a for a in lib.music.albums() if a["album"] == "Red")
        lib.music_trail = [("album", red["key"])]
        lib.shuffle_songs()
        self.assertEqual(sorted(queued[-1]), sorted(red["tracks"]))
        self.assertTrue(lib.music_shuffle.isEnabled())

    def test_playlists_by_how_much_is_watched(self):
        lib = self.lib
        files = {n: [str(self.d / n / f"e{i}.mkv") for i in range(4)] for n in ("Done", "Half", "New")}
        self.store.data["playlists"] = {k: v for k, v in files.items()}
        for p in files["Done"]:
            self.store.set_watched(p, True)
        for p in files["Half"][:2]:
            self.store.set_watched(p, True)
        combo = lib.playlists_sort
        combo.setCurrentIndex(combo.findData("unfinished"))
        names = [lib.pl_list.item(i).data(ROLE_PATH) for i in range(lib.pl_list.count())]
        self.assertEqual(names, ["New", "Half", "Done"])
        combo.setCurrentIndex(combo.findData("finished"))
        names = [lib.pl_list.item(i).data(ROLE_PATH) for i in range(lib.pl_list.count())]
        self.assertEqual(names, ["Done", "Half", "New"])
        half = next(lib.pl_list.item(i) for i in range(lib.pl_list.count()) if lib.pl_list.item(i).data(ROLE_PATH) == "Half")
        self.assertEqual(half.toolTip(), "2 of 4 watched")
        self.assertEqual(lib.playlist_progress(files["Half"] + ["https://example.test/s.m3u8"])[:2], (2, 4))

    def test_split_modules(self):
        import app.window as window, app.library as library
        names = [c.__name__ for c in MainWindow.__mro__]
        self.assertLess(names.index("SystemMixin"), names.index("QMainWindow"))
        for n in ("MenusMixin", "PlaybackMixin"):
            self.assertIn(n, names)
        self.assertIn("MusicMixin", [c.__name__ for c in LibraryPanel.__mro__])
        self.assertIn("QueueMixin", [c.__name__ for c in LibraryPanel.__mro__])
        for mod in (window, library):
            with open(mod.__file__, encoding="utf-8") as f:
                self.assertLess(sum(1 for _ in f), 1300)


if __name__ == "__main__":
    unittest.main()
