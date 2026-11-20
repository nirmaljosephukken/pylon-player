"""1.8.1: folders left out of the music scan (#96), and library folders that aren't there any more.

- #96: right-click a folder in the library panel (or an album in the Music tab) to leave it out of the music
  scan. Its songs leave the Music tab at once, later scans skip it and the folders in it, and Preferences >
  Interface lists it with a button to take it back in.
- Home: "Your library" cards have "Remove from library" in their right-click menu. A card whose folder is
  gone is greyed out and says "Folder not found"; opening it offers "Remove from library".
"""
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QLabel, QListWidget, QMessageBox, QPushButton
from app import engine
engine.vlc = None
from app import music as music_mod
from app.dialogs import PreferencesDialog
from app.store import Store
from app.widgets import Card
from app.window import MainWindow

app = QApplication.instance() or QApplication([])


class FakeInstance:
    def __init__(self, *_a):
        pass

    def release(self):
        pass


class FakeVLC:
    Instance = FakeInstance


def fake_read(self, inst, p, st):
    return {"size": st.st_size, "mtime": int(st.st_mtime), "title": os.path.basename(p), "artist": "A",
            "album_artist": "", "album": os.path.basename(os.path.dirname(p)), "track": 0, "disc": 0, "year": "",
            "genre": "", "dur": 1000, "art": ""}


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.lib_dir = self.root / "Music"
        for sub in ("Albums/One", "Albums/Two", "Ringtones", "Ringtones/Old"):
            (self.lib_dir / sub).mkdir(parents=True)
        for f in ("Albums/One/a.mp3", "Albums/Two/b.mp3", "Ringtones/r.mp3", "Ringtones/Old/o.mp3"):
            (self.lib_dir / f).write_bytes(b"ID3")
        self.store = Store(str(self.root / "data.json"))
        self.store.set_setting("onboarded", True)
        self.store.data["library_folders"] = [str(self.lib_dir)]
        with patch.object(MainWindow, "_welcome", lambda self: None), patch.object(MainWindow, "_vlc_missing"):
            self.win = MainWindow(self.store)
        self.win._ui_timer.stop()
        self.win._time_timer.stop()
        self.lib = self.win.library
        self.music = self.lib.music
        self.music.path = str(self.root / "music.json")
        self.music.songs = {}

    def tearDown(self):
        self.store._save_timer.stop()
        self.win.thumbs.cancel()
        self.win.deleteLater()
        app.processEvents()
        self.temp.cleanup()

    def scan(self):
        with patch.object(music_mod.engine_mod, "vlc", FakeVLC), \
                patch.object(music_mod.MusicLibrary, "_read", fake_read):
            self.music._scan(list(self.store.data["library_folders"]), dict(self.music.songs),
                             threading.Event(), self.music.skipped_keys())

    def names(self):
        return sorted(os.path.basename(p) for p in self.music.songs)


class MusicSkip(Base):
    def test_scan_skips_the_folder_and_its_subfolders(self):
        self.scan()
        self.assertEqual(self.names(), ["a.mp3", "b.mp3", "o.mp3", "r.mp3"])
        self.lib.leave_out_of_music(str(self.lib_dir / "Ringtones"))
        self.assertEqual(self.names(), ["a.mp3", "b.mp3"])          # gone at once, before any scan
        self.scan()
        self.assertEqual(self.names(), ["a.mp3", "b.mp3"])
        self.assertTrue(self.music.is_skipped(str(self.lib_dir / "Ringtones" / "Old")))
        self.assertFalse(self.music.is_skipped(str(self.lib_dir / "Albums")))
        self.store.save_now()
        loaded = Store(self.store.path)
        self.assertEqual(loaded.setting("music_skip_folders"), [os.path.normpath(str(self.lib_dir / "Ringtones"))])
        loaded._save_timer.stop()

    def test_taking_it_back_in(self):
        folder = str(self.lib_dir / "Ringtones")
        self.lib.leave_out_of_music(folder)
        with patch.object(self.lib, "_scan_music") as rescan:
            self.lib.leave_out_of_music(folder, False)
        rescan.assert_called_once()
        self.assertEqual(self.music.skipped(), [])
        self.scan()
        self.assertEqual(self.names(), ["a.mp3", "b.mp3", "o.mp3", "r.mp3"])

    def test_a_scan_already_running_drops_the_folder_too(self):
        self.store.set_setting("music_skip_folders", [str(self.lib_dir / "Albums" / "Two")])
        with patch.object(music_mod.engine_mod, "vlc", FakeVLC), \
                patch.object(music_mod.MusicLibrary, "_read", fake_read):
            # this scan started before the folder was left out
            self.music._scan([str(self.lib_dir)], {}, threading.Event(), frozenset())
        self.assertNotIn("b.mp3", self.names())

    def test_library_panel_menu(self):
        from PySide6.QtWidgets import QMenu
        from app import library as library_mod
        seen = []

        class Menu(QMenu):
            def exec(self, *_a):
                seen.append([a.text() for a in self.actions()])
        self.lib.open_folder(str(self.lib_dir))
        self.lib.refresh_library()
        lst = self.lib.lib_list
        row = next(i for i in range(lst.count()) if lst.item(i).text() == "Ringtones")
        pos = lst.visualItemRect(lst.item(row)).center()
        with patch.object(library_mod, "QMenu", Menu):
            self.lib._lib_menu(pos)
            self.lib.leave_out_of_music(str(self.lib_dir / "Ringtones"))
            self.lib._lib_menu(pos)
        self.assertIn("Leave out of the music scan", seen[0])
        self.assertIn("Include in the music scan", seen[1])

    def test_preferences_list(self):
        self.lib.leave_out_of_music(str(self.lib_dir / "Ringtones"))
        dlg = PreferencesDialog(self.win)
        try:
            lst = dlg.findChild(QListWidget, "music_skip_folders")
            self.assertEqual(lst.count(), 1)
            lst.setCurrentRow(0)
            with patch.object(self.lib, "_scan_music"):
                dlg.findChild(QPushButton, "music_skip_include").click()
            self.assertEqual(lst.count(), 0)
            self.assertEqual(self.music.skipped(), [])
        finally:
            dlg.deleteLater()


class HomeCards(Base):
    def cards(self):
        return {c.findChildren(QLabel)[1].toolTip(): c for c in self.win.home.widget().findChildren(Card)
                if c.findChildren(QLabel)[1].toolTip() in (os.path.basename(f) for f in
                                                           self.store.data["library_folders"])}

    def test_remove_from_library_in_card_menu(self):
        actions = dict(self.win.home._card_actions("folder", str(self.lib_dir)))
        self.assertIn("Remove from library", actions)
        self.assertIn("Open folder", actions)
        actions["Remove from library"]()
        self.assertEqual(self.store.data["library_folders"], [])

    def test_missing_folder_is_greyed_and_can_be_removed(self):
        gone = str(self.root / "Unplugged drive")
        self.store.data["library_folders"].append(gone)
        self.win.home.refresh()
        cards = self.cards()
        self.assertIn("Unplugged drive", cards)
        card = cards["Unplugged drive"]
        self.assertIsInstance(card.graphicsEffect(), QGraphicsOpacityEffect)
        self.assertIn("Folder not found", [lab.text() for lab in card.findChildren(QLabel)])
        self.assertIsNone(cards["Music"].graphicsEffect())
        actions = dict(self.win.home._card_actions("folder", gone))
        self.assertEqual(list(actions), ["Remove from library"])     # nothing to open or play
        # opening it offers to remove it
        clicked = {}

        def fake_exec(box):
            clicked["buttons"] = [b.text() for b in box.buttons()]
            box_button = next(b for b in box.buttons() if b.text() == "Remove from library")
            box.clickedButton = lambda: box_button
            return 0
        with patch.object(QMessageBox, "exec", fake_exec):
            self.lib.open_folder(gone)
        self.assertIn("Remove from library", clicked["buttons"])
        self.assertEqual(self.store.data["library_folders"], [str(self.lib_dir)])

    def test_panel_greys_missing_folders(self):
        gone = str(self.root / "Gone")
        self.store.data["library_folders"].append(gone)
        self.lib.open_folder(None)
        self.lib.refresh_library()
        lst = self.lib.lib_list
        item = next(lst.item(i) for i in range(lst.count()) if lst.item(i).text() == "Gone")
        self.assertIn("Folder not found", item.toolTip())


if __name__ == "__main__":
    unittest.main(verbosity=2)
