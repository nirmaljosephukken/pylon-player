"""Work that can be slow stays off the window's thread: online channel lists are fetched in the background,
cast devices found on VLC's thread reach the device list on the GUI thread, and cancelling a background
reader doesn't wait for it."""
import ctypes
import io
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from app import background, engine
engine.vlc = None
from app.background import BackgroundJob
from app.engine import Engine
from app.store import Store
from app.waveform import clean_leftovers
from app.window import MainWindow

app = QApplication.instance() or QApplication([])


def wait(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_for(cond, timeout_ms=3000):
    end = time.time() + timeout_ms / 1000
    while not cond() and time.time() < end:
        wait(20)
    return cond()


class SlowResponse(io.BytesIO):
    def __init__(self, data, delay):
        time.sleep(delay)           # a slow server
        super().__init__(data)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class StreamProbe(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))
        self.store.set_setting("onboarded", True)
        with patch.object(MainWindow, "_vlc_missing"):
            self.win = MainWindow(self.store)
        self.win._vlc_missing = lambda: None
        self.win._ui_timer.stop()
        self.win._time_timer.stop()

    def tearDown(self):
        w = self.win
        w.store._save_timer.stop()
        w.thumbs.cancel()
        w.library.music.stop()
        for widget in (w.top, w.bottom, w.osd, w):
            widget.deleteLater()
        app.processEvents()
        self.temp.cleanup()

    def test_slow_channel_list_doesnt_freeze_the_window(self):
        body = b"#EXTM3U\n#EXTINF:-1,A\nhttp://a/1\n#EXTINF:-1,B\nhttp://a/2\n"
        with patch("urllib.request.urlopen", lambda *a, **k: SlowResponse(body, 0.6)):
            t0 = time.time()
            self.win.open_stream("https://example.test/list.m3u")
            self.assertLess(time.time() - t0, 0.3)            # returned at once
            self.assertEqual(self.win.queue, [])
            self.assertTrue(wait_for(lambda: len(self.win.queue) == 2))
        self.assertEqual([q["title"] for q in self.win.queue], ["A", "B"])

    def test_only_the_latest_request_counts(self):
        bodies = {"old": (b"#EXTM3U\n#EXTINF:-1,Old\nhttp://a/1\n", 0.5),
                  "new": (b"#EXTM3U\n#EXTINF:-1,New\nhttp://b/1\n", 0.0)}

        def urlopen(req, *a, **k):
            body, delay = bodies["old" if "old" in req.full_url else "new"]
            return SlowResponse(body, delay)
        with patch("urllib.request.urlopen", urlopen):
            self.win.open_stream("https://example.test/old.m3u")
            self.win.open_stream("https://example.test/new.m3u")
            self.assertTrue(wait_for(lambda: len(self.win.queue) == 1))
            wait(800)                                         # the slow first answer arrives late
        self.assertEqual(self.win.queue[0]["title"], "New")

    def test_plain_hls_stream_plays(self):
        with patch("urllib.request.urlopen", lambda *a, **k: SlowResponse(b"#EXTM3U\n#EXT-X-VERSION:3\n", 0)):
            self.win.open_stream("https://example.test/live.m3u8", "News")
            self.assertTrue(wait_for(lambda: len(self.win.queue) == 1))
        self.assertEqual(self.win.queue[0], {"path": "https://example.test/live.m3u8", "title": "News"})


class Item:
    def __init__(self, name):
        self._name, self.held, self.released = name, 0, 0
    def hold(self): self.held += 1
    def release(self): self.released += 1
    def name(self): return self._name.encode()
    def type(self): return b"chromecast"


class FakeVlc:
    class Renderer:
        pass

    def __init__(self, items):
        self.items = items

    def _Constructor(self, cls, ptr):
        return self.items[ptr]


def event_for(ptr):
    class U(ctypes.Structure):
        _fields_ = [("item", ctypes.c_void_p)]

    class Ev(ctypes.Structure):
        _fields_ = [("type", ctypes.c_int), ("obj", ctypes.c_void_p), ("u", U)]
    ev = Ev()
    ev.u.item = ptr
    return ev


class CastEvents(unittest.TestCase):
    def test_devices_from_vlcs_thread_reach_the_gui_thread(self):
        temp = tempfile.TemporaryDirectory()
        e = Engine(Store(str(Path(temp.name) / "data.json")))
        tv = Item("TV")
        seen_on = []
        e.renderers_changed.connect(lambda: seen_on.append(threading.get_ident()))
        with patch.object(engine, "vlc", FakeVlc({0x1000: tv})):
            t = threading.Thread(target=lambda: (e._renderer_event(event_for(0x1000), True),
                                                 e._renderer_event(event_for(0x1000), True)))
            t.start()
            t.join()
            self.assertEqual(e._renderers, {})                    # nothing touched on VLC's thread
            self.assertEqual(tv.held, 1)                          # but kept alive there, once
            self.assertTrue(wait_for(lambda: len(seen_on) == 2))
            self.assertEqual([r["name"] for r in e.renderers()], ["TV"])
        self.assertEqual(set(seen_on), {threading.get_ident()})
        temp.cleanup()


class Cancelling(unittest.TestCase):
    def test_cancel_doesnt_wait(self):
        job = BackgroundJob()
        stopped = threading.Event()
        job._start_worker(lambda stop: (stop.wait(5), time.sleep(0.5), stopped.set()))
        t0 = time.time()
        job._stop_worker()
        self.assertLess(time.time() - t0, 0.2)
        self.assertFalse(stopped.is_set())                     # still finishing on its own
        self.assertTrue(stopped.wait(2))

    def test_cancel_can_wait_when_closing(self):
        job = BackgroundJob()
        done = threading.Event()
        job._start_worker(lambda stop: (stop.wait(5), done.set()))
        job._stop_worker(wait=True)
        self.assertTrue(done.is_set())

    def test_leftover_waveform_files_are_removed(self):
        with tempfile.TemporaryDirectory() as d, patch.object(background, "data_dir", lambda: d):
            waves = Path(background.cache_dir("waves"))
            old, new = waves / "reading-abc-1.wav", waves / "reading-def-2.wav"
            old.write_bytes(b"x")
            new.write_bytes(b"x")
            os.utime(old, (time.time() - 3600, time.time() - 3600))
            clean_leftovers()
            self.assertFalse(old.exists())
            self.assertTrue(new.exists())                        # may belong to a reader still running


if __name__ == "__main__":
    unittest.main()
