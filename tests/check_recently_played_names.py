"""Recently played shows a stream's saved name, not the end of its address (#67): the Recent tab,
the Home section and the Open > Recent menu."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QLabel
from app import engine
engine.vlc = None
from app.store import Store
from app.widgets import Card
from app.window import MainWindow

app = QApplication.instance() or QApplication([])

SAVED = "http://tv.test/hbo/index.m3u8"
CHANNEL = "http://tv.test/news/index.m3u8"
PLAIN = "http://tv.test/other/live.m3u8"


def wait(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class Names(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)
        self.store = Store(str(self.dir / "data.json"))
        self.store.set_setting("onboarded", True)
        with patch.object(MainWindow, "_welcome", lambda self: None), patch.object(MainWindow, "_vlc_missing"):
            self.win = MainWindow(self.store)
        self.win._vlc_missing = lambda: None
        self.win.resize(1200, 700)
        self.win.show()
        wait(100)
        self.film = str(self.dir / "Movie.Name.2019.1080p.BluRay.mkv")
        open(self.film, "w").close()
        self.store.data["streams"] = [
            {"name": "HBO Hits", "url": SAVED},
            {"name": "My channels", "url": str(self.dir / "list.m3u"),
             "channels": [{"name": "World News", "url": CHANNEL}]},
        ]
        self.store.data["recent"] = [{"path": SAVED, "t": 4}, {"path": CHANNEL, "t": 3},
                                     {"path": PLAIN, "t": 2}, {"path": self.film, "t": 1}]

    def tearDown(self):
        self.win.close()
        self.temp.cleanup()

    def test_recent_tab(self):
        self.win.library.refresh_recent()
        lst = self.win.library.recent_list
        self.assertEqual([lst.item(i).text() for i in range(lst.count())],
                         ["HBO Hits", "World News", "live.m3u8", "Movie.Name.2019.1080p.BluRay"])

    def test_home_section(self):
        self.store.data["positions"] = {}
        self.win.home.refresh()
        wait()
        titles = {c.toolTip(): c.findChildren(QLabel)[1].toolTip() for c in self.win.home.findChildren(Card)}
        self.assertEqual(titles[SAVED], "HBO Hits")
        self.assertEqual(titles[CHANNEL], "World News")
        self.assertEqual(titles[PLAIN], "live.m3u8")
        self.assertEqual(titles[self.film], "Movie Name (2019)")

    def test_open_recent_menu(self):
        m = self.win._open_menu(self.win)
        rec = next(a.menu() for a in m.actions() if a.menu() and a.text() == "Recent")
        self.assertEqual([a.text() for a in rec.actions()][:3], ["HBO Hits", "World News", "live.m3u8"])

    def test_renamed_stream_updates(self):
        self.store.data["streams"][0]["name"] = "HBO Classics"
        self.assertEqual(self.store.recent_title({"path": SAVED}), "HBO Classics")

    def test_unsaved_stream_keeps_the_name_it_was_played_under(self):
        self.store.add_recent("http://tv.test/x/index.m3u8", "Sports One")
        self.assertEqual(self.store.data["recent"][0]["title"], "Sports One")
        self.assertEqual(self.store.recent_title(self.store.data["recent"][0]), "Sports One")
        self.store.add_recent(self.film, "Some tag title")      # files keep their file-name label
        self.assertNotIn("title", self.store.data["recent"][0])

    def test_play_path_records_the_title(self):
        with patch.object(type(self.win.engine), "ok", True), patch.object(self.win.engine, "open"):
            self.win.play_path("http://tv.test/y/index.m3u8", title="Movies 24")
        self.assertEqual(self.store.data["recent"][0], {"path": "http://tv.test/y/index.m3u8",
                                                        "t": self.store.data["recent"][0]["t"], "title": "Movies 24"})


if __name__ == "__main__":
    unittest.main()
