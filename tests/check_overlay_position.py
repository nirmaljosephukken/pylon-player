"""Top and bottom bars go back to the video's edges if the system moves them (#40)."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEventLoop, QPoint, QTimer
from PySide6.QtWidgets import QApplication
from app import engine
engine.vlc = None
from app.store import Store
from app.window import MainWindow

app = QApplication.instance() or QApplication([])


def wait(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class OverlayPosition(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))
        self.store.set_setting("onboarded", True)
        with patch.object(MainWindow, "_welcome", lambda self: None), patch.object(MainWindow, "_vlc_missing"):
            self.win = MainWindow(self.store)
        self.win._vlc_missing = lambda: None
        self.win.resize(1000, 700)
        self.win.show()
        self.win._ui_timer.stop()                # the test drives placement itself
        wait(150)

    def tearDown(self):
        self.win.close()
        self.temp.cleanup()

    def test_moved_bar_is_put_back(self):
        w = self.win
        w._set_bars(True)
        w._place_overlays()
        tl = w.stage.mapToGlobal(QPoint(0, 0))
        self.assertEqual(w.top.pos(), tl)
        w.top.move(tl.x(), tl.y() + 30)          # what macOS does when the bar is shown
        wait(50)
        w._place_overlays()
        self.assertEqual(w.top.pos(), tl)

    def test_gives_up_if_the_system_insists(self):
        w = self.win
        w._set_bars(True)
        w._place_overlays()
        tl = w.stage.mapToGlobal(QPoint(0, 0))
        calls = []
        real = w.top.setGeometry
        def stubborn(rect):
            calls.append(rect)
            real(rect)
            w.top.move(tl.x(), tl.y() + 30)
        w.top.setGeometry = stubborn
        w.top.move(tl.x(), tl.y() + 30)
        for _ in range(20):
            w._place_overlays()
        self.assertEqual(len(calls), 5)
        w._set_bars(False); w._set_bars(True)    # showing again allows new tries
        w._place_overlays()
        self.assertEqual(len(calls), 6)


if __name__ == "__main__":
    unittest.main()
