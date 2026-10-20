"""A broken stream doesn't skip ahead and the queue keeps its place (#50), queue search (#44),
Preferences shortcut (#49) and a higher maximum volume (#47)."""
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


class QueueVolumePrefs(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))
        self.store.set_setting("onboarded", True)
        with patch.object(MainWindow, "_welcome", lambda self: None), patch.object(MainWindow, "_vlc_missing"):
            self.win = MainWindow(self.store)
        self.win._vlc_missing = lambda: None
        self.win.resize(1200, 700)
        self.win.show()
        self.win.toggle_library(True)
        wait(100)

    def tearDown(self):
        self.win.close()
        self.temp.cleanup()

    def fill_queue(self, n, url=True):
        self.win.queue = [{"path": f"http://tv.test/ch{i}.m3u8" if url else f"C:/v/ep{i}.mkv",
                           "title": f"Channel {i}"} for i in range(n)]
        self.win.qindex = 3
        self.win.library.refresh_queue()

    def test_broken_stream_stays_put(self):
        self.fill_queue(5)
        self.win.engine.current = "http://tv.test/ch3.m3u8"
        nexts = []
        with patch.object(MainWindow, "play_next", lambda self, user=False: nexts.append(1)):
            self.win._on_state("error")
            wait(1700)
        self.assertEqual(nexts, [])

    def test_broken_file_still_moves_on(self):
        self.fill_queue(5, url=False)
        self.win.engine.current = "C:/v/ep3.mkv"
        nexts = []
        with patch.object(MainWindow, "play_next", lambda self, user=False: nexts.append(1)):
            self.win._on_state("error")
            wait(1700)
        self.assertEqual(nexts, [1])

    def test_queue_keeps_scroll_position(self):
        lib = self.win.library
        self.fill_queue(200)
        wait(50)
        bar = lib.queue.verticalScrollBar()
        bar.setValue(bar.maximum() // 2)
        before = bar.value()
        lib.refresh_queue()                       # same item still playing
        self.assertEqual(bar.value(), before)

    def test_queue_search(self):
        lib = self.win.library
        self.fill_queue(20)
        self.assertTrue(lib.queue_search.isVisibleTo(lib))
        lib.queue_search.setText("channel 1")
        shown = [lib.queue.item(i).text() for i in range(lib.queue.count()) if not lib.queue.item(i).isHidden()]
        self.assertEqual(shown, ["Channel 1"] + [f"Channel {i}" for i in range(10, 20)])
        lib.queue_search.setText("")
        self.fill_queue(3)
        self.assertFalse(lib.queue_search.isVisibleTo(lib))  # short queues don't need it

    def test_preferences_shortcut(self):
        self.assertEqual(DEFAULT_SHORTCUTS["preferences"][1], "Ctrl+,")
        seqs = [v[1] for v in DEFAULT_SHORTCUTS.values()]
        self.assertEqual(len(seqs), len(set(seqs)))
        opened = []
        with patch.object(MainWindow, "show_preferences", lambda self: opened.append(1)):
            self.win.do("preferences", key=False)
        self.assertEqual(opened, [1])

    def test_maximum_volume(self):
        e, cone = self.win.engine, self.win.bottom.cone
        self.assertEqual(e.max_volume(), 125)
        self.assertEqual(cone.MAX, 125)
        from app.dialogs import PreferencesDialog
        d = PreferencesDialog(self.win)
        d._set_max_volume(200)
        self.assertEqual(e.max_volume(), 200)
        self.assertEqual(cone.MAX, 200)
        e.set_volume(180)
        self.assertEqual(self.store.setting("volume"), 180)
        d._set_max_volume(125)                       # lowering the limit brings the volume down
        self.assertEqual(self.store.setting("volume"), 125)
        e.set_volume(300)
        self.assertEqual(self.store.setting("volume"), 125)
        d.close()


if __name__ == "__main__":
    unittest.main()
