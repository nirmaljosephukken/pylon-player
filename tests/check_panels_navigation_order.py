"""Both-panels shortcut (#34), tab click returns to start (#35), newest-first playlists/streams (#37)."""
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
from app.store import DEFAULT_SHORTCUTS, Store
from app.window import MainWindow

app = QApplication.instance() or QApplication([])


def wait(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class PanelsNavigationOrder(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.lib = root / "Shows"
        (self.lib / "Season 1").mkdir(parents=True)
        (self.lib / "Season 1" / "ep1.mkv").write_bytes(b"x")
        self.store = Store(str(root / "data.json"))
        self.store.data["library_folders"] = [str(self.lib)]
        self.store.set_setting("onboarded", True)
        with patch.object(MainWindow, "_welcome", lambda self: None), patch.object(MainWindow, "_vlc_missing"):
            self.win = MainWindow(self.store)
        self.win._vlc_missing = lambda: None
        self.win.resize(1400, 800)
        self.win.show()
        wait(100)

    def tearDown(self):
        self.win.close()
        self.temp.cleanup()

    def test_panels_shortcut(self):
        self.assertEqual(DEFAULT_SHORTCUTS["panels"][1], "Ctrl+Shift+L")
        seqs = [v[1] for v in DEFAULT_SHORTCUTS.values()]
        self.assertEqual(len(seqs), len(set(seqs)), "duplicate default shortcut")
        w = self.win
        w.toggle_library(False); w.toggle_sidebar(False)
        w.do("panels", key=False)
        self.assertTrue(w.library.isVisible() and w.sidebar.isVisible())
        w.do("panels", key=False)
        self.assertTrue(w.library.isHidden() and w.sidebar.isHidden())
        w.toggle_sidebar(True)                       # one open: the shortcut hides it
        w.do("panels", key=False)
        self.assertTrue(w.library.isHidden() and w.sidebar.isHidden())

    def test_tab_click_returns_to_start(self):
        lib = self.win.library
        self.win.toggle_library(True)
        lib.show_section("library")
        lib.open_folder(str(self.lib / "Season 1"))
        self.assertIsNotNone(lib.folder)
        lib.nav_buttons["library"].click()
        self.assertIsNone(lib.folder)
        self.assertTrue(lib.nav_buttons["library"].isChecked())
        lib.go_back()                                # Back still returns to the folder
        self.assertEqual(lib.folder, str(self.lib / "Season 1"))
        lib.nav_buttons["music"].click()             # switching tabs is unchanged
        self.assertEqual(lib.stack.currentIndex(), lib.SECTIONS.index("music"))
        lib.music_trail = [("artist", "Someone")]
        lib.nav_buttons["music"].click()
        self.assertEqual(lib.music_trail, [])
        self.assertTrue(lib.nav_buttons["music"].isChecked())

    def test_newest_first_default(self):
        lib = self.win.library
        for n in ("Bravo", "alpha", "Charlie"):     # created in this order
            self.store.data["playlists"][n] = ["a"] * (3 if n == "alpha" else 1)
        self.store.data["streams"] = [{"name": "Zed", "url": "http://z"}, {"name": "Amy", "url": "http://a"}]
        lib.show_section("playlists")
        from app.library import ROLE_PATH
        names = [lib.pl_list.item(i).data(ROLE_PATH) for i in range(lib.pl_list.count())]
        self.assertEqual(names, ["Charlie", "alpha", "Bravo"])
        self.assertEqual(lib.playlists_sort.currentData(), "newest")
        lib.playlists_sort.setCurrentIndex(lib.playlists_sort.findData("oldest"))
        names = [lib.pl_list.item(i).data(ROLE_PATH) for i in range(lib.pl_list.count())]
        self.assertEqual(names, ["Bravo", "alpha", "Charlie"])
        lib.playlists_sort.setCurrentIndex(lib.playlists_sort.findData("name"))
        names = [lib.pl_list.item(i).data(ROLE_PATH) for i in range(lib.pl_list.count())]
        self.assertEqual(names, ["alpha", "Bravo", "Charlie"])
        lib.show_section("streams")
        urls = [lib.st_list.item(i).data(ROLE_PATH) for i in range(lib.st_list.count())]
        self.assertEqual(urls, ["http://a", "http://z"])
        # renaming keeps a playlist's place by age, and can't overwrite another
        lib.playlists_sort.setCurrentIndex(lib.playlists_sort.findData("oldest"))
        with patch("app.library.QInputDialog.getText", return_value=("Aardvark", True)):
            lib._pl_rename("Bravo")
        self.assertEqual(list(self.store.data["playlists"]), ["Aardvark", "alpha", "Charlie"])
        with patch("app.library.QInputDialog.getText", return_value=("alpha", True)), \
             patch("app.library.QMessageBox.warning") as warn:
            lib._pl_rename("Charlie")
        warn.assert_called_once()
        self.assertEqual(len(self.store.data["playlists"]), 3)


if __name__ == "__main__":
    unittest.main()
