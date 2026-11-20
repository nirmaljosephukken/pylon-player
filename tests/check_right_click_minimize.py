"""1.8.1, #93: right-click and the other mouse buttons can minimize or quit, and full screen has a minimize button.

- Preferences > Controls has a Right click row. Its default, Open menu, keeps the old behaviour; any other
  choice runs that action instead, and the menu button in the top bar (and the keyboard's menu key) still
  open the menu.
- Every mouse row offers Minimize and Quit Pylon; both are shortcuts too (no default key).
- The top bar shows a minimize button in full screen only; minimizing from full screen keeps full screen
  for when the window comes back.
- #39: Ctrl and + zooms in like Ctrl and = (the keypad's + and the + key of many keyboards).
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer
from PySide6.QtGui import QContextMenuEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QComboBox
from app import engine
engine.vlc = None
from app.dialogs import PreferencesDialog
from app.stage import MOUSE_ACTIONS
from app.store import DEFAULT_SHORTCUTS, Store
from app.window import PAGE_VIDEO, MainWindow, VideoSurface

app = QApplication.instance() or QApplication([])


def wait(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def right_click(widget, reason=QContextMenuEvent.Reason.Mouse):
    QApplication.sendEvent(widget, QContextMenuEvent(reason, QPoint(10, 10), widget.mapToGlobal(QPoint(10, 10))))


class Surface(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))
        self.surface = VideoSurface(self.store)
        self.actions, self.menus = [], []
        self.surface.action.connect(self.actions.append)
        self.surface.context.connect(self.menus.append)

    def tearDown(self):
        self.surface.deleteLater()
        self.store._save_timer.stop()
        app.processEvents()
        self.temp.cleanup()

    def test_right_click_opens_the_menu_by_default(self):
        self.assertEqual(self.store.setting("mouse_right"), "menu")
        right_click(self.surface)
        self.assertEqual(len(self.menus), 1)
        self.assertEqual(self.actions, [])

    def test_right_click_can_run_an_action_instead(self):
        for action in ("minimize", "quit", "fullscreen", "play_pause"):
            self.store.set_setting("mouse_right", action)
            right_click(self.surface)
        self.assertEqual(self.actions, ["minimize", "quit", "fullscreen", "play_pause"])
        self.assertEqual(self.menus, [])
        self.store.set_setting("mouse_right", "none")
        right_click(self.surface)
        self.assertEqual(self.menus, [])
        self.assertEqual(len(self.actions), 4)

    def test_menu_key_still_opens_the_menu(self):
        self.store.set_setting("mouse_right", "fullscreen")
        right_click(self.surface, QContextMenuEvent.Reason.Keyboard)
        self.assertEqual(len(self.menus), 1)
        self.assertEqual(self.actions, [])

    def test_other_buttons_can_minimize_and_quit(self):
        from PySide6.QtCore import QEvent, QPointF
        from PySide6.QtGui import QMouseEvent
        self.store.set_setting("mouse_middle", "quit")
        self.store.set_setting("mouse_back", "minimize")
        for button in (Qt.MiddleButton, Qt.BackButton):
            QApplication.sendEvent(self.surface, QMouseEvent(QEvent.MouseButtonRelease, QPointF(5, 5), QPointF(5, 5),
                                                             button, Qt.NoButton, Qt.NoModifier))
        self.assertEqual(self.actions, ["quit", "minimize"])


class WindowParts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))
        self.store.set_setting("onboarded", True)
        with patch.object(MainWindow, "_welcome", lambda self: None), patch.object(MainWindow, "_vlc_missing"):
            self.win = MainWindow(self.store)
        self.win._vlc_missing = lambda: None
        self.win.resize(900, 600)
        self.win.show()
        wait(100)

    def tearDown(self):
        self.store._save_timer.stop()
        self.win.thumbs.cancel()
        self.win.close()
        app.processEvents()
        self.temp.cleanup()

    def test_preferences_rows(self):
        dialog = PreferencesDialog(self.win)
        try:
            right = dialog.findChild(QComboBox, "mouse_right")
            self.assertEqual(right.itemData(0), "menu")
            self.assertEqual(right.currentData(), "menu")
            for key in ("mouse_single", "mouse_double", "mouse_right", "mouse_middle", "mouse_back", "mouse_forward"):
                combo = dialog.findChild(QComboBox, key)
                values = [combo.itemData(i) for i in range(combo.count())]
                self.assertIn("minimize", values, key)
                self.assertIn("quit", values, key)
            right.setCurrentIndex(right.findData("minimize"))
            self.assertEqual(self.store.setting("mouse_right"), "minimize")
            notes = " ".join(lab.text() for lab in dialog.findChildren(type(dialog.extra_note)))
            self.assertNotIn("right-click opens the menu", notes)
            self.assertIn("menu button in the top bar always opens the menu", notes)
        finally:
            dialog.deleteLater()

    def test_actions_and_shortcuts(self):
        self.assertEqual(DEFAULT_SHORTCUTS["minimize"][1], "")
        self.assertEqual(DEFAULT_SHORTCUTS["quit"][1], "")
        table = self.win._actions()
        for a in MOUSE_ACTIONS:
            if a != "none":
                self.assertIn(a, table, a)
        with patch.object(self.win, "minimize_window") as mini:
            self.win._action_table = None
            self.win.do("minimize", key=False)
        mini.assert_called_once()
        self.win._action_table = None

    def test_minimize_button_only_in_full_screen(self):
        w = self.win
        top = w.top
        top.set_fullscreen(False)
        self.assertTrue(top.btn_min.isHidden())
        top.set_fullscreen(True)
        self.assertFalse(top.btn_min.isHidden())
        with patch.object(w, "minimize_window") as mini:
            top.minimize_clicked.disconnect()
            top.minimize_clicked.connect(mini)
            top.btn_min.click()
        mini.assert_called_once()
        top.set_fullscreen(False)

    def test_minimize_keeps_full_screen(self):
        w = self.win
        w.stage.setCurrentIndex(PAGE_VIDEO)
        w.toggle_fullscreen()
        wait(200)
        self.assertTrue(w.isFullScreen())
        w.minimize_window()
        wait(200)
        self.assertTrue(w.windowState() & Qt.WindowMinimized)
        self.assertTrue(w.windowState() & Qt.WindowFullScreen)
        self.assertFalse(w.top.isVisible())
        w.setWindowState(w.windowState() & ~Qt.WindowMinimized)
        wait(200)
        self.assertTrue(w.isFullScreen())
        w.toggle_fullscreen()
        wait(100)

    def test_ctrl_plus_zooms_in(self):
        keys = {sc.key().toString() for sc in self.win.findChildren(QShortcut)}
        self.assertIn("Ctrl+=", keys)
        self.assertIn(QKeySequence("Ctrl++").toString(), keys)
        with patch.object(self.win, "zoom_video") as zoom:
            self.win._action_table = None
            sc = next(s for s in self.win.findChildren(QShortcut) if s.key() == QKeySequence("Ctrl++"))
            sc.activated.emit()
        zoom.assert_called_once_with(1.25)
        self.win._action_table = None

    def test_alias_not_added_when_the_key_is_taken(self):
        self.store.data["shortcuts"]["snapshot"] = "Ctrl++"
        self.win.install_shortcuts()
        matching = [s for s in self.win.findChildren(QShortcut)
                    if s.key() == QKeySequence("Ctrl++") and s.isEnabled()]
        self.assertEqual(len(matching), 1)          # the snapshot key only


if __name__ == "__main__":
    unittest.main(verbosity=2)
