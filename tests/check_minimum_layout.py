"""At the smallest window size (640 x 400), with the library and settings panels open or closed, the panels
stay inside the window, the video keeps at least 240 pixels, and the bars and their buttons stay over it."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ["PYLON_NO_UPDATE_CHECK"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from app import engine
engine.vlc = None
from app.store import Store
from app.window import PAGE_VIDEO, MainWindow

app = QApplication.instance() or QApplication([])


class MinimumLayout(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))
        self.store.set_setting("onboarded", True)
        w = self.win = MainWindow(self.store)
        w._vlc_missing = lambda: None
        w.show()
        app.processEvents()
        w._ui_timer.stop()
        w._time_timer.stop()
        w.stage.setCurrentIndex(PAGE_VIDEO)

    def tearDown(self):
        w = self.win
        self.store._save_timer.stop()
        for widget in (w, w.top, w.bottom):
            widget.hide()
        self.temp.cleanup()

    def layout(self, library, settings):
        w = self.win
        w.toggle_library(library)
        w.toggle_sidebar(settings)
        w.lib_slot.finish()
        w.side_slot.finish()
        w.resize(640, 400)
        app.processEvents()
        w._place_overlays()
        w._set_bars(True)
        app.processEvents()
        w._place_overlays()

    def test_panels_and_bars_fit(self):
        w = self.win
        for library, settings in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(library=library, settings=settings):
                self.layout(library, settings)
                rect = w.centralWidget().rect()
                for panel in (w.lib_slot, w.middle, w.side_slot):      # the panels slide in slots (#54)
                    if panel.isVisible():
                        self.assertTrue(rect.contains(panel.geometry()), (rect, panel.geometry()))
                self.assertGreaterEqual(w.stage.width(), 240)
                right = w.stage.mapToGlobal(w.stage.rect().topRight()).x()
                for bar in (w.top, w.bottom):
                    self.assertLessEqual(bar.x() + bar.mask().boundingRect().right(), right)
                self.assertLess(w.bottom.btn_tune.geometry().right(), w.stage.width())

    def test_back_to_the_smallest_size(self):
        self.layout(True, True)
        self.layout(False, False)
        self.assertEqual(self.win.width(), 640)


if __name__ == "__main__":
    unittest.main()
