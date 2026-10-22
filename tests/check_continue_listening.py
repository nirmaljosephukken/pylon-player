"""Songs stay out of Continue watching; the Music section starts with Continue listening (#55):
an album you were partway through, or a song that isn't on an album, with a progress bar."""
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication, QLabel
from app import engine
engine.vlc = None
from app.store import Store
from app.widgets import Card
from app.window import MainWindow

app = QApplication.instance() or QApplication([])
MIN = 60_000


class ContinueListening(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        d = Path(self.temp.name)
        self.store = Store(str(d / "data.json"))
        self.store.set_setting("onboarded", True)
        album = d / "Night Bus"
        album.mkdir()
        self.tracks = []
        for i in range(1, 5):
            p = album / f"{i:02d} Song {i}.mp3"
            p.touch()
            self.tracks.append(str(p))
        self.single = str(d / "Loose Song.mp3")
        Path(self.single).touch()
        self.video = str(d / "Film.mkv")
        Path(self.video).touch()
        with patch.object(MainWindow, "_welcome", lambda self: None), patch.object(MainWindow, "_vlc_missing"):
            self.win = MainWindow(self.store)
        self.win._vlc_missing = lambda: None
        self.played = []
        self.win.play_path = lambda path, start_ms=None, **kw: (self.played.append((path, start_ms)),
                                                                 setattr(self.win.engine, "current", path))
        songs = {p: {"title": f"Song {i}", "artist": "Mira Vale", "album_artist": "", "album": "Night Bus",
                     "track": i, "disc": 0, "year": "2023", "genre": "", "dur": 4 * MIN, "art": "", "mtime": 1}
                 for i, p in enumerate(self.tracks, 1)}
        self.win.library.music.songs = songs
        self.t = time.time()

    def tearDown(self):
        self.win.close()
        self.temp.cleanup()

    def pos(self, path, pos, ln=4 * MIN, watched=False, ago=0):
        self.store.data["positions"][path] = {"pos": pos, "len": ln, "watched": watched, "t": self.t - ago}

    def items(self):
        return self.win.home.continue_listening()

    def test_songs_are_not_in_continue_watching(self):
        self.pos(self.tracks[1], MIN)
        self.pos(self.video, 10 * MIN, ln=90 * MIN)
        self.assertEqual([e["path"] for e in self.store.continue_watching()], [self.video])

    def test_album_partway_through_a_song(self):
        self.pos(self.tracks[1], 2 * MIN)                    # halfway through song 2 of 4
        [it] = self.items()
        self.assertEqual(it["album"]["album"], "Night Bus")
        self.assertEqual(it["index"], 1)
        self.assertEqual(it["pos"], 2 * MIN)
        self.assertAlmostEqual(it["progress"], 1.5 / 4)

    def test_finished_song_moves_on_to_the_next(self):
        self.pos(self.tracks[0], 4 * MIN - 1000, watched=True)
        [it] = self.items()
        self.assertEqual(it["path"], self.tracks[1])
        self.assertEqual(it["pos"], 0)
        self.assertAlmostEqual(it["progress"], 1 / 4)

    def test_only_the_newest_song_of_an_album_counts(self):
        self.pos(self.tracks[0], MIN, ago=100)
        self.pos(self.tracks[2], MIN)
        [it] = self.items()
        self.assertEqual(it["index"], 2)

    def test_finished_album_is_not_shown(self):
        self.pos(self.tracks[3], 4 * MIN, watched=True)
        self.assertEqual(self.items(), [])

    def test_barely_started_first_song_is_not_shown(self):
        self.pos(self.tracks[0], 3000)
        self.assertEqual(self.items(), [])

    def test_song_not_on_an_album_is_shown_on_its_own(self):
        self.pos(self.single, MIN)
        [it] = self.items()
        self.assertIsNone(it["album"])
        self.assertEqual(it["path"], self.single)
        self.assertAlmostEqual(it["progress"], 0.25)

    def test_clicking_the_album_queues_it_and_resumes_the_song(self):
        self.pos(self.tracks[1], 2 * MIN)
        self.win.home._resume_listening(self.items()[0])
        self.assertEqual([q["path"] for q in self.win.queue], self.tracks)
        self.assertEqual(self.win.qindex, 1)
        self.assertEqual(self.played[-1], (self.tracks[1], 2 * MIN))

    def test_remove_hides_it_until_played_again(self):
        self.pos(self.tracks[1], 2 * MIN, ago=10)
        self.win.home._hide_listening(self.items()[0]["key"])
        self.assertEqual(self.items(), [])
        self.pos(self.tracks[2], MIN, ago=-10)                # played again afterwards
        self.assertEqual(len(self.items()), 1)

    def test_home_shows_the_row_with_a_progress_bar(self):
        self.pos(self.tracks[1], 2 * MIN)
        self.pos(self.video, 10 * MIN, ln=90 * MIN)
        home = self.win.home
        home.refresh()
        labels = [l.text() for l in home.findChildren(QLabel)]
        self.assertIn("Continue listening", labels)
        self.assertIn("Continue watching", labels)
        cards = [c for c in home.findChildren(Card)]
        titles = [l.text() for c in cards for l in c.findChildren(QLabel)]
        self.assertIn("Night Bus", titles)
        self.assertNotIn("02 Song 2", titles)              # the song isn't under Continue watching


if __name__ == "__main__":
    unittest.main()
