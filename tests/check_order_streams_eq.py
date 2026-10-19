"""Opened files sort by name (#43), stream rename and copy link (#44), equalizer
double-click reset and side panel wording (#45), AppImage ignores system Qt add-ons (#28)."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEvent, QEventLoop, QPointF, Qt, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication
from app import engine
engine.vlc = None
from app.engine import CUSTOM_EQ
from app.store import DEFAULT_SHORTCUTS, Store
from app.window import MainWindow

app = QApplication.instance() or QApplication([])
ROOT = Path(__file__).resolve().parents[1]


def wait(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def double_click(w):
    pos = QPointF(w.width() / 2, w.height() / 2)
    QApplication.sendEvent(w, QMouseEvent(QEvent.MouseButtonDblClick, pos, w.mapToGlobal(pos),
                                          Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))


class OrderStreamsEq(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.store = Store(str(root / "data.json"))
        self.store.set_setting("onboarded", True)
        with patch.object(MainWindow, "_welcome", lambda self: None), patch.object(MainWindow, "_vlc_missing"):
            self.win = MainWindow(self.store)
        self.win._vlc_missing = lambda: None
        self.show = root / "Show"
        self.show.mkdir()
        for n in (1, 2, 3, 4, 5, 6, 10):
            (self.show / f"House of the Dragon S03E{n:02d}.mkv").write_bytes(b"x")

    def tearDown(self):
        self.win.close()
        self.temp.cleanup()

    def test_dropped_files_play_in_episode_order(self):
        names = ["S03E01", "S03E02", "S03E05", "S03E03", "S03E10", "S03E04", "S03E06"]   # selection order
        paths = [str(self.show / f"House of the Dragon {n}.mkv") for n in names]
        got = []
        with patch.object(MainWindow, "set_queue", lambda self, items, i: got.extend(x["path"] for x in items)):
            self.win.open_paths(paths)
        self.assertEqual([Path(p).stem[-6:] for p in got],
                         ["S03E01", "S03E02", "S03E03", "S03E04", "S03E05", "S03E06", "S03E10"])

    def test_stream_rename_and_copy_link(self):
        lib = self.win.library
        self.store.data["streams"] = [{"name": "News", "url": "http://example.test/news.m3u8"}]
        self.win.queue = [{"path": "http://example.test/news.m3u8", "title": "News"}]
        lib.refresh_streams()
        with patch("app.library.QInputDialog.getText", return_value=("World news", True)):
            lib._st_rename("http://example.test/news.m3u8", "News")
        self.assertEqual(self.store.data["streams"][0], {"name": "World news", "url": "http://example.test/news.m3u8"})
        self.assertEqual(self.win.queue[0]["title"], "World news")
        self.assertEqual(lib.st_list.item(0).text(), "World news")
        with patch("app.library.QInputDialog.getText", return_value=("   ", True)):
            lib._st_rename("http://example.test/news.m3u8", "World news")   # blank names are ignored
        self.assertEqual(self.store.data["streams"][0]["name"], "World news")
        lib._copy_link("http://example.test/news.m3u8")
        self.assertEqual(QApplication.clipboard().text(), "http://example.test/news.m3u8")

    def test_equalizer_double_click_resets_one_slider(self):
        sb = self.win.sidebar
        sb._set_eq(CUSTOM_EQ)
        eq = sb.eq_custom
        eq.bands[2].setValue(10)
        eq.bands[5].setValue(-6)
        eq.preamp.slider.setValue(4)
        double_click(eq.bands[2])
        double_click(eq.preamp.slider)
        wait(150)
        c = eq.curve()
        self.assertEqual(c["bands"][2], 0.0)
        self.assertEqual(c["bands"][5], -3.0)          # the others are untouched
        self.assertEqual(c["preamp"], 0.0)
        self.assertEqual(self.win.engine.live["eq_custom"]["bands"][2], 0.0)

    def test_side_panel_wording(self):
        names = [DEFAULT_SHORTCUTS[k][0] for k in ("library", "sidebar", "panels")]
        self.assertEqual(names, ["Show or hide library panel", "Show or hide settings panel",
                                 "Show or hide both side panels"])
        self.assertFalse(any("sidebar" in v[0].lower() for v in DEFAULT_SHORTCUTS.values()))

    def test_appimage_ignores_system_qt_addons(self):
        apprun = (ROOT / "packaging/linux/AppRun").read_text()
        self.assertIn("QT_PLUGIN_PATH", apprun.split("exec ")[0].split("unset", 1)[1])


if __name__ == "__main__":
    unittest.main()
