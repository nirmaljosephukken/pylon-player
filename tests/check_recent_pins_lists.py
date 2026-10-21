"""Recent tab right-click menu and accent progress bar (#51), Pin to top in other tabs (#52),
and .m3u channel lists saved in Streams (#44)."""
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QInputDialog, QMenu
from app import engine, theme
engine.vlc = None
from app.store import Store
from app.window import MainWindow

app = QApplication.instance() or QApplication([])


def wait(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def menu_labels(menu):
    out = []
    for a in menu.actions():
        if a.menu():
            out.append(a.text() + ":" + "|".join(x.text() for x in a.menu().actions() if x.text()))
        elif a.text():
            out.append(a.text())
    return out


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)
        self.store = Store(str(self.dir / "data.json"))
        self.store.set_setting("onboarded", True)
        with patch.object(MainWindow, "_welcome", lambda self: None), patch.object(MainWindow, "_vlc_missing"):
            self.win = MainWindow(self.store)
        self.win._vlc_missing = lambda: None
        self.win.play_path = lambda path, **kw: setattr(self.win.engine, "current", path)
        self.lib = self.win.library
        self.win.resize(1200, 700)
        self.win.show()
        self.win.toggle_library(True)
        wait(100)
        self.toasts = []
        self.win.toast = lambda msg, *a, **k: self.toasts.append(msg)

    def tearDown(self):
        self.win.close()
        self.temp.cleanup()

    def open_menu(self, fn, lst, row):
        """Run a context-menu handler for a row and return the menu it would show."""
        shown = []

        class RecordingMenu(QMenu):
            def exec(menu, *args):
                shown.append(menu)

        with patch("app.library.QMenu", RecordingMenu):
            fn(lst.visualItemRect(lst.item(row)).center())
        return shown[0] if shown else None

    @staticmethod
    def texts(lst):
        return [lst.item(i).text() for i in range(lst.count())]


class RecentMenu(Base):
    def fill_recent(self):
        f = str(self.dir / "Show S01E01.mkv")
        open(f, "w").close()
        self.store.data["recent"] = [{"path": f, "t": 1}, {"path": "http://tv.test/news.m3u8", "t": 2}]
        self.store.data["positions"][f] = {"pos": 10, "len": 100}
        self.lib.refresh_recent()
        return f

    def test_file_menu_matches_the_library(self):
        self.fill_recent()
        m = self.open_menu(self.lib._recent_menu, self.lib.recent_list, 0)
        labels = menu_labels(m)
        for want in ("Play", "Add to queue", "Play next", "Mark as watched", "Show in Explorer", "Remove from Recent"):
            self.assertIn(want, labels)
        self.assertTrue(any(x.startswith("Add to playlist:") for x in labels))

    def test_stream_menu(self):
        self.fill_recent()
        m = self.open_menu(self.lib._recent_menu, self.lib.recent_list, 1)
        labels = menu_labels(m)
        for want in ("Play", "Copy link", "Save to Streams", "Remove from Recent"):
            self.assertIn(want, labels)
        self.assertNotIn("Show in Explorer", labels)
        next(a for a in m.actions() if a.text() == "Save to Streams").trigger()
        self.assertEqual(self.store.data["streams"][0]["url"], "http://tv.test/news.m3u8")

    def test_remove_from_recent(self):
        f = self.fill_recent()
        m = self.open_menu(self.lib._recent_menu, self.lib.recent_list, 0)
        next(a for a in m.actions() if a.text() == "Remove from Recent").trigger()
        self.assertEqual([r["path"] for r in self.store.data["recent"]], ["http://tv.test/news.m3u8"])
        self.assertNotIn(f, self.store.data["positions"])
        self.assertEqual(self.lib.recent_list.count(), 1)

    def test_progress_bar_uses_the_accent(self):
        css = theme.stylesheet()
        self.assertIn("QProgressBar::chunk", css)
        chunk = css.split("QProgressBar::chunk")[1].split("}")[0]
        self.assertIn(theme.accent().lower(), chunk.lower())


class Pins(Base):
    def test_playlists(self):
        lib = self.lib
        self.store.data["playlists"] = {"Alpha": ["a"], "Beta": ["b", "c"], "Gamma": []}
        lib.refresh_playlists()
        self.assertEqual(self.texts(lib.pl_list)[0], "Gamma   (0)")            # newest first
        m = self.open_menu(lib._pl_menu, lib.pl_list, 2)
        next(a for a in m.actions() if a.text() == "Pin to top").trigger()
        self.assertEqual(self.texts(lib.pl_list), ["PINNED", "Alpha   (1)", "PLAYLISTS", "Gamma   (0)", "Beta   (2)"])
        self.assertEqual(lib.playlists_count.text(), "3 playlists")
        lib.playlists_sort.setCurrentIndex(lib.playlists_sort.findData("reverse"))   # pins ignore the sort
        self.assertEqual(self.texts(lib.pl_list)[1], "Alpha   (1)")
        with patch.object(QInputDialog, "getText", lambda *a, **k: ("Aardvark", True)):
            lib._pl_rename("Alpha")
        self.assertEqual(lib.pins("playlists"), ["Aardvark"])
        with patch("app.library.QMessageBox.question", lambda *a, **k: __import__("PySide6.QtWidgets", fromlist=["x"]).QMessageBox.Yes):
            lib._pl_delete("Aardvark")
        self.assertEqual(lib.pins("playlists"), [])
        self.assertNotIn("PINNED", self.texts(lib.pl_list))

    def test_streams_and_home(self):
        lib = self.lib
        self.store.data["streams"] = [{"name": "Three", "url": "http://t/3"}, {"name": "Two", "url": "http://t/2"},
                                      {"name": "One", "url": "http://t/1"}]
        lib.refresh_streams()
        m = self.open_menu(lib._st_menu, lib.st_list, 2)
        next(a for a in m.actions() if a.text() == "Pin to top").trigger()
        self.assertEqual(self.texts(lib.st_list), ["PINNED", "One", "STREAMS", "Three", "Two"])
        self.assertEqual(lib.streams_count.text(), "3 streams")
        m = self.open_menu(lib._st_menu, lib.st_list, 1)
        self.assertIn("Unpin", menu_labels(m))
        # the home page lists pinned streams first too
        self.win.home.refresh()
        from app.widgets import Card
        from PySide6.QtWidgets import QLabel
        names = [c.findChildren(QLabel)[1].toolTip() for c in self.win.home.findChildren(Card)]
        self.assertLess(names.index("One"), names.index("Three"))
        lib._st_remove("http://t/1")
        self.assertEqual(lib.pins("streams"), [])

    def test_music_pins(self):
        lib = self.lib
        lib.toggle_item_pin("albums", "x|y")
        lib.toggle_item_pin("artists", "Someone")
        self.assertEqual(lib.pins("albums"), ["x|y"])
        first, rest = lib.with_pins("artists", [("A", []), ("Someone", []), ("B", [])], lambda x: x[0])
        self.assertEqual([x[0] for x in first], ["Someone"])
        self.assertEqual([x[0] for x in rest], ["A", "B"])
        lib.toggle_item_pin("artists", "Someone")
        self.assertEqual(lib.pins("artists"), [])


class ChannelLists(Base):
    def write_list(self, name="Free TV.m3u", extra=""):
        p = self.dir / name
        p.write_text("#EXTM3U\n#EXTINF:-1 tvg-id=\"a\",News One\nhttp://tv.test/news.m3u8\n"
                     "#EXTINF:-1,Sports\nhttps://tv.test/sports.m3u8\n#EXTINF:-1,Local clip\nclips/local.mp4\n" + extra,
                     encoding="utf-8")
        return str(p)

    def test_import_saves_one_entry_with_a_count(self):
        lib = self.lib
        p = self.write_list()
        s = lib.import_channel_list(p)
        self.assertEqual(s["name"], "Free TV")
        self.assertEqual([c["name"] for c in s["channels"]], ["News One", "Sports", "Local clip"])
        self.assertEqual(s["channels"][2]["url"], os.path.normpath(str(self.dir / "clips/local.mp4")))
        self.assertEqual(self.texts(lib.st_list), ["Free TV   (3)"])
        self.assertIn("3 channels", self.toasts[-1])
        lib.import_channel_list(p)                                 # again: updated, not duplicated
        self.assertEqual(len(self.store.data["streams"]), 1)
        self.assertIn("Updated", self.toasts[-1])

    def test_not_a_list(self):
        p = self.dir / "empty.m3u"
        p.write_text("#EXTM3U\n", encoding="utf-8")
        self.assertIsNone(self.lib.import_channel_list(str(p)))
        self.assertEqual(self.store.data["streams"], [])

    def test_drop_on_streams_tab(self):
        p = self.write_list("dropped.m3u8")
        self.lib.st_list.lists_dropped.emit([p])
        self.assertEqual(self.store.data["streams"][0]["name"], "dropped")

    def test_play_add_and_export(self):
        lib, win = self.lib, self.win
        s = lib.import_channel_list(self.write_list())
        url = s["url"]
        win.play_saved_stream(url)
        self.assertEqual([q["title"] for q in win.queue], ["News One", "Sports", "Local clip"])
        self.assertEqual(win.qindex, 0)
        m = self.open_menu(lib._st_menu, lib.st_list, 0)
        labels = menu_labels(m)
        self.assertIn("Add more streams:A stream link…|From an .m3u file…", labels)
        self.assertIn("Export as .m3u…", labels)
        self.assertNotIn("Copy link", labels)                      # a file, not a link
        answers = iter([("http://tv.test/movies.m3u8", True), ("Movies", True)])
        with patch.object(QInputDialog, "getText", lambda *a, **k: next(answers)):
            lib._list_add_link(url)
        self.assertEqual(s["channels"][-1], {"name": "Movies", "url": "http://tv.test/movies.m3u8"})
        self.assertEqual(lib._add_channels(url, [{"name": "dup", "url": "http://tv.test/news.m3u8"}]), 0)
        out = self.dir / "out.m3u"
        with patch("app.library.QFileDialog.getSaveFileName", lambda *a, **k: (str(out), "")):
            lib._st_export(url)
        back = lib.read_channel_file(str(out))
        self.assertEqual([c["name"] for c in back], ["News One", "Sports", "Local clip", "Movies"])
        win.queue = []
        win.enqueue_items([{"path": c["url"], "title": c["name"]} for c in s["channels"]])
        self.assertEqual(win.queue[1]["title"], "Sports")

    def test_online_list_remembers_its_count(self):
        lib, win = self.lib, self.win
        url = "https://example.test/playlist.m3u8"
        self.store.data["streams"] = [{"name": "Free-TV", "url": url}]
        lib.refresh_streams()
        body = b"#EXTM3U\n#EXTINF:-1,A\nhttp://a/1\n#EXTINF:-1,B\nhttp://a/2\n"

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with patch("urllib.request.urlopen", lambda *a, **k: Resp(body)):
            win.play_saved_stream(url)
        self.assertEqual(len(win.queue), 2)
        self.assertEqual(self.store.data["streams"][0]["count"], 2)
        self.assertEqual(self.texts(lib.st_list), ["Free-TV   (2)"])

    def test_save_queue_as_channel_list(self):
        lib, win = self.lib, self.win
        win.queue = [{"path": "http://a/1", "title": "One"}, {"path": "http://a/2", "title": "Two"}]
        with patch.object(QInputDialog, "getItem", lambda *a, **k: ("Save to Streams as a channel list", True)), \
             patch.object(QInputDialog, "getText", lambda *a, **k: ("My channels", True)):
            lib._save_queue_as_playlist()
        s = self.store.data["streams"][0]
        self.assertEqual(s["name"], "My channels")
        self.assertEqual([c["name"] for c in s["channels"]], ["One", "Two"])
        self.assertTrue(s["url"].startswith("pylon-list:"))

    def test_opening_a_list_file_hints_at_saving(self):
        p = self.dir / "online.m3u"
        p.write_text("#EXTM3U\n#EXTINF:-1,A\nhttp://a/1\n#EXTINF:-1,B\nhttp://a/2\n", encoding="utf-8")
        self.win.open_playlist_file(str(p))
        wait(600)
        self.assertTrue(any("Streams tab" in t for t in self.toasts))


if __name__ == "__main__":
    unittest.main()
