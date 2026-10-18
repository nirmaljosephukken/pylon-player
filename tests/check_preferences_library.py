"""Persistence, startup choices, root sorting and the folder context menu."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QColorDialog, QLabel, QMenu, QScrollArea
from app import engine
engine.vlc = None
from app.store import Store
from app.window import MainWindow
from app.dialogs import PreferencesDialog
from app.colour_dialog import choose_colour
from app.library import ROLE_PATH, ROLE_KIND
from app.widgets import Card

app = QApplication.instance() or QApplication([])


class PreferencesLibrary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(str(self.root / 'data.json'))
        self.store.set_setting('onboarded', True)
        self.windows = []
        self.original_palette = [QColorDialog.customColor(i) for i in range(QColorDialog.customCount())]

    def window(self, store=None):
        with patch.object(MainWindow, '_vlc_missing'):
            win = MainWindow(store or self.store)
        win._vlc_missing = lambda: None
        win._ui_timer.stop()
        win._time_timer.stop()
        self.windows.append(win)
        return win

    def tearDown(self):
        for win in self.windows:
            win.store._save_timer.stop()
            win.thumbs.cancel()
            win.library.music.stop()
            for widget in (win.top, win.bottom, win.osd, win):
                widget.deleteLater()
        self.store._save_timer.stop()
        for i, colour in enumerate(self.original_palette):
            QColorDialog.setCustomColor(i, colour)
        app.processEvents()
        self.temp.cleanup()

    def test_custom_palette_survives_restart_and_cancel(self):
        original_accent = self.store.setting('accent')
        def edit(*args):
            QColorDialog.setCustomColor(3, QColor('#01fcb9'))
            return QColor()  # cancel selected colour; saved swatches still count
        with patch.object(QColorDialog, 'getColor', side_effect=edit):
            self.assertFalse(choose_colour(self.store, original_accent, None, 'Accent').isValid())
        self.store.save_now()
        loaded = Store(self.store.path)
        QColorDialog.setCustomColor(3, QColor('white'))
        def inspect(*args):
            self.assertEqual(QColorDialog.customColor(3).name(), '#01fcb9')
            self.assertEqual(args[3], QColorDialog.DontUseNativeDialog)
            return QColor('#123456')
        with patch.object(QColorDialog, 'getColor', side_effect=inspect):
            self.assertEqual(choose_colour(loaded, 'white', None, 'Subtitle').name(), '#123456')
        self.assertEqual(loaded.setting('accent'), original_accent)
        loaded._save_timer.stop()

    def test_startup_tabs_and_same_session_reopening(self):
        self.store.set_setting('library_startup_tab', 'playlists')
        self.store.set_setting('settings_startup_tab', 'audio')
        win = self.window()
        self.assertEqual(win.library.stack.currentIndex(), 2)
        self.assertEqual(win.sidebar.tabs.currentIndex(), 1)
        win.library.show_section('streams')
        win.sidebar.tabs.setCurrentIndex(4)
        win.toggle_library(False)
        win.toggle_library(True)
        win.toggle_sidebar(False)
        win.toggle_sidebar(True)
        self.assertEqual(win.library.stack.currentIndex(), 3)
        self.assertEqual(win.sidebar.tabs.currentIndex(), 4)
        self.store.set_setting('library_startup_tab', 'last')
        self.store.set_setting('settings_startup_tab', 'last')
        self.store.save_now()
        loaded = Store(self.store.path)
        second = self.window(loaded)
        self.assertEqual(second.library.stack.currentIndex(), 3)
        self.assertEqual(second.sidebar.tabs.currentIndex(), 4)
        second.open_sidebar_tab(0)
        self.assertEqual(second.sidebar.tabs.currentIndex(), 0)

    def test_root_folder_sorting_and_adding_without_pinning(self):
        a, z = self.root / 'Alpha', self.root / 'Zulu'
        a.mkdir()
        z.mkdir()
        os.utime(a, (100, 100))
        os.utime(z, (200, 200))
        win = self.window()
        lib = win.library
        self.assertTrue(lib.add_library_path(str(z)))
        self.assertTrue(lib.add_library_path(str(a)))
        self.assertFalse(lib.add_library_path(str(a / '.')))
        self.assertEqual(self.store.data['pinned'], [])
        def paths():
            return [lib.lib_list.item(i).data(ROLE_PATH) for i in range(lib.lib_list.count())
                    if lib.lib_list.item(i).data(ROLE_KIND) == 'folder']
        lib._set_sort('name')
        self.assertEqual(paths(), [str(a), str(z)])
        lib._set_sort('date')
        self.assertEqual(paths(), [str(z), str(a)])
        cards = win.home.widget().findChildren(Card)
        names = [lab.toolTip() for card in cards for lab in card.findChildren(QLabel)
                 if lab.toolTip() in ('Alpha', 'Zulu')]
        self.assertEqual(names, ['Zulu', 'Alpha'])
        child = a / 'Child'
        child.mkdir()
        lib.open_folder(str(a))
        win.show()
        win.toggle_library(True)
        app.processEvents()
        item = next(lib.lib_list.item(i) for i in range(lib.lib_list.count())
                    if lib.lib_list.item(i).data(ROLE_PATH) == str(child))
        menu_text = []
        class RecordingMenu(QMenu):
            def exec(menu, *args):
                menu_text.extend(action.text() for action in menu.actions())
        with patch('app.library.QMenu', RecordingMenu):
            lib._lib_menu(lib.lib_list.visualItemRect(item).center())
        self.assertIn('Add to library', menu_text)
        self.assertIn('Pin to top', menu_text)

    def test_privacy_path_is_reachable_at_small_size(self):
        self.store.path = str(self.root / ('long-folder-' * 12) / 'data.json')
        win = self.window()
        dialog = PreferencesDialog(win)
        dialog.resize(760, 520)
        dialog.pages.setCurrentIndex(5)
        dialog.show()
        app.processEvents()
        scroll = dialog.pages.currentWidget()
        self.assertIsInstance(scroll, QScrollArea)
        label = next(w for w in scroll.findChildren(QLabel) if 'Your data is stored' in w.text())
        self.assertIn(self.store.path, label.text())
        self.assertGreaterEqual(label.height(), label.heightForWidth(label.width()))
        scroll.ensureWidgetVisible(label)
        app.processEvents()
        rect = label.mapTo(scroll.viewport(), label.rect().bottomLeft())
        self.assertLessEqual(rect.y(), scroll.viewport().height())
        dialog.deleteLater()

    def test_music_group_count_and_modification_sort(self):
        win = self.window()
        lib = win.library
        lib.music.songs = {
            str(self.root / name): {'artist': artist, 'album': album, 'track': track, 'mtime': stamp}
            for name, artist, album, track, stamp in (
                ('one.mp3', 'Zulu', 'Older', 1, 10), ('two.mp3', 'Zulu', 'Older', 2, 11),
                ('three.mp3', 'Alpha', 'Newer', 1, 20))}
        for path in lib.music.songs:
            Path(path).touch()
        lib.music_sort.setCurrentIndex(lib.music_sort.findData('count'))
        lib._music_mode('artists')
        self.assertTrue(lib.music_list.item(0).text().startswith('Zulu'))
        lib.music_sort.setCurrentIndex(lib.music_sort.findData('date'))
        lib._music_mode('albums')
        self.assertTrue(lib.music_list.item(0).text().startswith('Newer'))
        lib._music_mode('songs')
        self.assertFalse(lib.music_sort.model().item(lib.music_sort.findData('count')).isEnabled())
        self.assertTrue(lib.music_list.item(0).data(ROLE_PATH).endswith('three.mp3'))


if __name__ == '__main__':
    unittest.main()
