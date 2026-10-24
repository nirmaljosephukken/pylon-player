"""A folder saved as a playlist plays in file name order, and Sort by name means file name (#58).

Entries from an .m3u carry the titles another player wrote from the files' tags. Sorting by those put a
folder in "tag" order, so Sort by name now uses the file name for files (titles still sort channels).
Files picked in an Open window come in selection order on Windows, so they're put in name order, and
sorting a playlist also sorts the queue when that playlist is what's playing."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog
from app import engine
engine.vlc = None
from app.store import Store
from app.util import sort_key_by_name
from app.window import MainWindow

app = QApplication.instance() or QApplication([])

NAMES = ["Ep 1 - Pilot.mkv", "Ep 2 - Zebra.mkv", "Ep 10 - Alpha.mkv", "Ep 11 - Beta.mkv"]


class NameOrder(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.d = Path(self.temp.name)
        self.store = Store(str(self.d / "data.json"))
        self.store.set_setting("onboarded", True)
        with patch.object(MainWindow, "_welcome", lambda self: None), patch.object(MainWindow, "_vlc_missing"):
            self.win = MainWindow(self.store)
        self.win._vlc_missing = lambda: None
        self.win.toast = lambda *a, **k: None
        self.win.engine.open = lambda *a, **k: None
        self.files = []
        for n in NAMES:
            p = self.d / "Show" / n
            p.parent.mkdir(exist_ok=True)
            p.touch()
            self.files.append(str(p))

    def tearDown(self):
        self.win.close()
        self.temp.cleanup()

    def names(self):
        return [Path(q["path"]).name for q in self.win.queue]

    def test_files_sort_by_file_name_not_their_title(self):
        tag_titles = ["Pilot", "Zebra", "Alpha", "Beta"]        # what another player wrote from the tags
        keys = sorted(zip(self.files, tag_titles), key=lambda ft: sort_key_by_name(*ft))
        self.assertEqual([Path(f).name for f, _ in keys], NAMES)
        chans = [("https://e.test/b.m3u8", "BBC"), ("https://e.test/a.m3u8", "Arte")]
        self.assertEqual([t for _, t in sorted(chans, key=lambda c: sort_key_by_name(*c))], ["Arte", "BBC"])

    def test_m3u_from_another_player_sorts_by_file_name(self):
        m3u = self.d / "Show" / "show.m3u"
        order = [3, 2, 0, 1]                                      # tag order: Alpha, Beta, Pilot, Zebra
        titles = ["Pilot", "Zebra", "Alpha", "Beta"]
        m3u.write_text("#EXTM3U\n" + "".join(f"#EXTINF:-1,{titles[i]}\n{NAMES[i]}\n" for i in sorted(order, key=lambda i: titles[i])),
                       encoding="utf-8")
        self.win.open_playlist_file(str(m3u))
        self.assertEqual(self.names(), [NAMES[i] for i in (2, 3, 0, 1)])
        self.win.sort_queue_by_name()
        self.assertEqual(self.names(), NAMES)
        self.assertEqual(self.win.queue[0].get("title"), "Pilot")   # the queue still shows the title

    def test_files_picked_in_an_open_window_are_in_name_order(self):
        picked = [self.files[i] for i in (3, 0, 2, 1)]          # selection order
        with patch.object(QFileDialog, "getOpenFileNames", return_value=(picked, "")), \
             patch.object(QInputDialog, "getText", return_value=("Show", True)):
            self.win.library.new_playlist()
        self.assertEqual([Path(p).name for p in self.store.data["playlists"]["Show"]], NAMES)
        with patch.object(QFileDialog, "getOpenFileNames", return_value=(picked, "")):
            self.win.library._add_files_to_queue()
        self.assertEqual(self.names(), NAMES)

    def test_sorting_a_playlist_sorts_its_queue_too(self):
        lib = self.win.library
        mixed = [self.files[i] for i in (3, 1, 0, 2)]
        self.store.data["playlists"]["Show"] = list(mixed)
        self.win.play_playlist("Show")
        self.assertEqual(self.names(), [Path(p).name for p in mixed])
        lib._pl_sort("Show")
        self.assertEqual([Path(p).name for p in self.store.data["playlists"]["Show"]], NAMES)
        self.assertEqual(self.names(), NAMES)

    def test_another_playlist_leaves_the_queue_alone(self):
        self.win.set_queue([{"path": self.files[3]}, {"path": self.files[0]}], 0)
        self.store.data["playlists"]["Other"] = [self.files[2], self.files[1]]
        self.win.library._pl_sort("Other")
        self.assertEqual(self.names(), [NAMES[3], NAMES[0]])


if __name__ == "__main__":
    unittest.main()
