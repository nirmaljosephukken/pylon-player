"""Mouse event sequences, preference persistence and dialog cursor isolation."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEvent, QEventLoop, QPointF, Qt, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QComboBox, QDialog
from app import engine
engine.vlc = None
from app.store import Store
from app.window import MainWindow, VideoSurface, PAGE_VIDEO, PAGE_HOME
from app.dialogs import PreferencesDialog

app = QApplication.instance() or QApplication([])


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def mouse(widget, kind, button=Qt.LeftButton):
    buttons = Qt.NoButton if kind == QEvent.MouseButtonRelease else button
    event = QMouseEvent(kind, QPointF(10, 10), QPointF(10, 10), button, buttons, Qt.NoModifier)
    QApplication.sendEvent(widget, event)


class MouseControls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / 'data.json'))
        self.surface = VideoSurface(self.store)
        self.actions = []
        self.surface.action.connect(self.actions.append)
        self.interval = QApplication.doubleClickInterval()
        QApplication.setDoubleClickInterval(60)

    def tearDown(self):
        self.surface.cancel_click()
        self.surface.deleteLater()
        self.store._save_timer.stop()
        QApplication.setDoubleClickInterval(self.interval)
        app.processEvents()
        self.temp.cleanup()

    def test_single_waits_only_when_double_is_bound(self):
        mouse(self.surface, QEvent.MouseButtonRelease)
        self.assertEqual(self.actions, [])
        wait(100)
        self.assertEqual(self.actions, ['play_pause'])
        self.store.set_setting('mouse_double', 'none')
        mouse(self.surface, QEvent.MouseButtonRelease)
        self.assertEqual(self.actions, ['play_pause', 'play_pause'])

    def test_double_has_no_delayed_pause_after_final_release(self):
        mouse(self.surface, QEvent.MouseButtonRelease)
        mouse(self.surface, QEvent.MouseButtonDblClick)
        mouse(self.surface, QEvent.MouseButtonRelease)
        wait(100)
        self.assertEqual(self.actions, ['fullscreen'])

    def test_unbound_double_produces_two_immediate_singles(self):
        self.store.set_setting('mouse_double', 'none')
        mouse(self.surface, QEvent.MouseButtonRelease)
        mouse(self.surface, QEvent.MouseButtonDblClick)
        mouse(self.surface, QEvent.MouseButtonRelease)
        self.assertEqual(self.actions, ['play_pause', 'play_pause'])
        self.assertFalse(self.surface._click.isActive())

    def test_standard_extra_buttons_and_disabled_actions(self):
        for button, key, action in ((Qt.MiddleButton, 'mouse_middle', 'mute'),
                                    (Qt.BackButton, 'mouse_back', 'prev'),
                                    (Qt.ForwardButton, 'mouse_forward', 'next')):
            mouse(self.surface, QEvent.MouseButtonRelease, button)
            self.assertEqual(self.actions, [])
            self.store.set_setting(key, action)
        for button in (Qt.MiddleButton, Qt.BackButton, Qt.ForwardButton):
            mouse(self.surface, QEvent.MouseButtonRelease, button)
        self.assertEqual(self.actions, ['mute', 'prev', 'next'])

    def test_pending_click_does_not_act_inside_modal(self):
        mouse(self.surface, QEvent.MouseButtonRelease)
        dialog = QDialog()
        dialog.setModal(True)
        dialog.show()
        app.processEvents()
        wait(100)
        self.assertEqual(self.actions, [])
        dialog.close()

    def test_preferences_persist_and_cursor_is_local(self):
        self.store.set_setting('onboarded', True)
        # Engine is intentionally absent: don't let the delayed startup prompt
        # open a file chooser when a slower build machine runs this event loop.
        with patch.object(MainWindow, '_vlc_missing'):
            win = MainWindow(self.store)
        win._ui_timer.stop()
        win._time_timer.stop()
        dialog = PreferencesDialog(win)
        try:
            combo = dialog.findChild(QComboBox, 'mouse_double')
            combo.setCurrentIndex(combo.findData('none'))
            self.store.save_now()
            loaded = Store(self.store.path)
            self.assertEqual(loaded.setting('mouse_double'), 'none')
            loaded._save_timer.stop()
            with patch.object(win, 'isFullScreen', return_value=True), \
                    patch.object(QApplication, 'activeWindow', return_value=win):
                win._update_video_cursor(PAGE_VIDEO, True, False)
                self.assertEqual(win.video.cursor().shape(), Qt.BlankCursor)
                self.assertIsNone(QApplication.overrideCursor())
                self.assertNotEqual(dialog.cursor().shape(), Qt.BlankCursor)
                with patch.object(QApplication, 'activeModalWidget', return_value=dialog):
                    win._update_video_cursor(PAGE_VIDEO, True, False)
                    self.assertNotEqual(win.video.cursor().shape(), Qt.BlankCursor)
                win._update_video_cursor(PAGE_HOME, True, False)
                self.assertNotEqual(win.video.cursor().shape(), Qt.BlankCursor)
            self.store.set_setting('mouse_double', 'fullscreen')
            win.show()
            win.stage.setCurrentIndex(PAGE_VIDEO)
            app.processEvents()
            dispatched = []
            win.video.action.connect(dispatched.append)
            mouse(win.video, QEvent.MouseButtonRelease)
            mouse(win.video, QEvent.MouseButtonDblClick)
            mouse(win.video, QEvent.MouseButtonRelease)
            wait(100)
            self.assertEqual(dispatched, ['fullscreen'])
            self.assertTrue(win.isFullScreen())
        finally:
            dialog.deleteLater()
            win.thumbs.cancel()
            for widget in (win.top, win.bottom, win.osd, win):
                widget.deleteLater()
            app.processEvents()


if __name__ == '__main__':
    unittest.main()
