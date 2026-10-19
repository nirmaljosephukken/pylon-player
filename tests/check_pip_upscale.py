"""Borderless picture in picture and the Windows Super Resolution option (#42)."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEvent, QEventLoop, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication
from app import engine
engine.vlc = None
from app.engine import Engine
from app.store import Store
from app.window import MainWindow

app = QApplication.instance() or QApplication([])


def wait(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def mouse(w, kind, pos, buttons):
    ev = QMouseEvent(kind, QPointF(*pos), w.mapToGlobal(QPointF(*pos)), Qt.LeftButton, buttons, Qt.NoModifier)
    QApplication.sendEvent(w, ev)


class PipUpscale(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))
        self.store.set_setting("onboarded", True)
        with patch.object(MainWindow, "_welcome", lambda self: None), patch.object(MainWindow, "_vlc_missing"):
            self.win = MainWindow(self.store)
        self.win._vlc_missing = lambda: None
        self.win.open_file_dialog = lambda *a, **k: None   # a click with nothing loaded opens it
        self.win.resize(1100, 700)
        self.win.show()
        wait(150)

    def tearDown(self):
        self.win.close()
        self.temp.cleanup()

    def test_upscale_argument(self):
        e = Engine(self.store)
        with patch.object(engine.sys, "platform", "win32"):
            self.assertNotIn("--d3d11-upscale-mode=super", e._args())
            self.store.set_setting("rtx_upscale", True)
            self.assertIn("--d3d11-upscale-mode=super", e._args())
        with patch.object(engine.sys, "platform", "linux"):
            self.assertNotIn("--d3d11-upscale-mode=super", e._args())   # Windows only

    def test_pip_is_borderless_and_restores(self):
        w = self.win
        w.toggle_pip(); wait(200)
        self.assertTrue(w.windowFlags() & Qt.FramelessWindowHint)
        self.assertTrue(w.video.pip)
        self.assertEqual(w.minimumSize().width(), 320)
        self.assertLess(w.width(), 640)          # the small size now applies
        w.toggle_pip(); wait(200)
        self.assertFalse(w.windowFlags() & Qt.FramelessWindowHint)
        self.assertFalse(w.video.pip)
        self.assertEqual(w.minimumSize().width(), 640)

    def test_edges(self):
        w = self.win
        w.toggle_pip(); wait(200)
        r = w.frameGeometry()
        self.assertEqual(w.pip_edges(QPoint(r.left() + 2, r.top() + 2)), Qt.LeftEdge | Qt.TopEdge)
        self.assertEqual(w.pip_edges(QPoint(r.right() - 2, r.center().y())), Qt.RightEdge)
        self.assertEqual(w.pip_edges(r.center()), Qt.Edges())
        self.assertEqual(w.edge_cursor(Qt.RightEdge | Qt.BottomEdge), Qt.SizeFDiagCursor)

    def test_drag_moves_window_and_is_not_a_click(self):
        w = self.win
        w.toggle_pip(); wait(200)
        v = w.video
        acts, grabs = [], []
        v.action.connect(acts.append)
        with patch.object(MainWindow, "pip_grab", lambda self, gpos, move=True: grabs.append(move) or True):
            c = (v.width() // 2, v.height() // 2)
            mouse(v, QEvent.MouseButtonPress, c, Qt.LeftButton)
            mouse(v, QEvent.MouseMove, (c[0] + 20, c[1]), Qt.LeftButton)
            mouse(v, QEvent.MouseButtonRelease, (c[0] + 20, c[1]), Qt.NoButton)
            wait(QApplication.doubleClickInterval() + 100)
        self.assertEqual(grabs, [True])
        self.assertEqual(acts, [])
        # a press and release far apart with no movement in between is not a click either
        mouse(v, QEvent.MouseButtonPress, c, Qt.LeftButton)
        mouse(v, QEvent.MouseButtonRelease, (c[0] + 30, c[1] + 10), Qt.NoButton)
        wait(QApplication.doubleClickInterval() + 100)
        self.assertEqual(acts, [])
        # a plain click still plays or pauses
        mouse(v, QEvent.MouseButtonPress, c, Qt.LeftButton)
        mouse(v, QEvent.MouseButtonRelease, c, Qt.NoButton)
        wait(QApplication.doubleClickInterval() + 100)
        self.assertEqual(acts, ["play_pause"])


if __name__ == "__main__":
    unittest.main()
