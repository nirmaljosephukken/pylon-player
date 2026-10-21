"""Home screen sections can be reordered and shown or hidden from Preferences, and there is
a Music section (#53)."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEvent, QEventLoop, QPointF, Qt, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QLabel
from app import engine
engine.vlc = None
from app.dialogs import PreferencesDialog
from app.store import HOME_SECTIONS, Store
from app.window import MainWindow

app = QApplication.instance() or QApplication([])
TITLES = {v[0] for v in HOME_SECTIONS.values()}


def wait(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class HomeSections(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)
        self.store = Store(str(self.dir / "data.json"))
        self.store.set_setting("onboarded", True)
        v = self.dir / "Film.mkv"
        v.touch()
        self.store.data["recent"] = [{"path": str(v), "t": 1}]
        self.store.data["playlists"] = {"Mix": [str(v)]}
        self.store.data["streams"] = [{"name": "News", "url": "http://tv/news"}]
        with patch.object(MainWindow, "_welcome", lambda self: None), patch.object(MainWindow, "_vlc_missing"):
            self.win = MainWindow(self.store)
        self.win._vlc_missing = lambda: None
        self.lib = self.win.library
        songs = {}
        for i, (album, artist, mtime) in enumerate((("Old Album", "Band A", 100), ("New Album", "Band B", 900))):
            for t in range(2):
                p = self.dir / f"{album} {t}.mp3"
                p.touch()
                songs[str(p)] = {"title": f"Song {t}", "artist": artist, "album": album, "track": t + 1, "mtime": mtime}
        self.lib.music.songs = songs
        self.win.home.refresh()

    def tearDown(self):
        self.win.close()
        self.temp.cleanup()

    def sections(self):
        return [w.text() for w in self.win.home.widget().findChildren(QLabel)
                if w.objectName() == "H2" and w.text() in TITLES]

    def test_default_order_has_music(self):
        self.assertEqual(self.sections(), ["Recently played", "Your library", "Playlists", "Music", "Streams"])

    def test_store_order_is_robust(self):
        self.store.set_setting("home_order", ["streams", "bogus", "music", "streams"])
        self.assertEqual(self.store.home_order(), ["streams", "music", "continue", "recent", "library", "playlists"])

    def test_music_section(self):
        from app.widgets import Card
        cards = [c for c in self.win.home.findChildren(Card) if c.findChildren(QLabel)[1].toolTip().endswith("Album")]
        self.assertEqual([c.findChildren(QLabel)[1].toolTip() for c in cards], ["New Album", "Old Album"])  # newest first
        played = []
        self.lib.play_songs = lambda paths, index=0: played.append(paths)
        cards[1].clicked.emit()
        self.assertEqual(len(played[0]), 2)
        key = next(a["key"] for a in self.lib.music.albums() if a["album"] == "Old Album")
        self.lib.toggle_item_pin("albums", key)                      # pinned albums come first
        cards = [c for c in self.win.home.findChildren(Card) if c.findChildren(QLabel)[1].toolTip().endswith("Album")]
        self.assertEqual(cards[0].findChildren(QLabel)[1].toolTip(), "Old Album")

    def test_preferences_reorder_and_hide(self):
        d = PreferencesDialog(self.win)
        hs = d.home_sections
        self.assertEqual(hs.keys(), list(HOME_SECTIONS))
        # drag Streams to the top
        model = hs.list.model()
        model.moveRow(model.index(0, 0).parent(), 5, model.index(0, 0).parent(), 0)
        self.assertEqual(self.store.setting("home_order")[0], "streams")
        self.assertEqual(self.sections()[0], "Streams")
        # click the eye on Playlists to hide it
        d.show()
        wait(100)
        row = hs.keys().index("playlists")
        pos = hs.eye_rect(hs.list.visualItemRect(hs.list.item(row))).center()
        for kind in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
            ev = QMouseEvent(kind, QPointF(pos), QPointF(hs.list.viewport().mapToGlobal(pos)),
                             Qt.LeftButton, Qt.LeftButton if kind == QEvent.MouseButtonPress else Qt.NoButton,
                             Qt.NoModifier)
            QApplication.sendEvent(hs.list.viewport(), ev)
        self.assertFalse(self.store.setting("home_playlists"))
        self.assertNotIn("Playlists", self.sections())
        self.assertEqual(self.store.data["playlists"], {"Mix": [str(self.dir / "Film.mkv")]})   # nothing deleted
        hs.toggle("playlists")
        self.assertIn("Playlists", self.sections())
        for key in ("library", "music", "streams"):                   # every section can be hidden
            hs.toggle(key)
        self.assertEqual(self.sections(), ["Recently played", "Playlists"])
        d.close()


if __name__ == "__main__":
    unittest.main()
