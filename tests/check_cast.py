"""Casting to a Chromecast: devices found on the network appear in the Cast menu, choosing one
sends the current file there from the same point, and This computer brings it back."""
import ctypes
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from app import engine
REAL_VLC = engine.vlc
engine.vlc = None
from app.engine import Engine
from app.store import Store
from app.window import MainWindow

app = QApplication.instance() or QApplication([])


class Item:
    def __init__(self, name):
        self._name, self.held, self.released = name, 0, 0
    def hold(self): self.held += 1
    def release(self): self.released += 1
    def name(self): return self._name.encode()
    def type(self): return b"chromecast"


class FakeVlc:
    """Just enough of python-vlc for the renderer event handler."""
    class Renderer:
        pass

    def __init__(self):
        self.items = {}

    def _Constructor(self, cls, ptr):
        return self.items[ptr]


def event_for(ptr):
    """An event whose payload starts with the item pointer, like libVLC's."""
    class U(ctypes.Structure):
        _fields_ = [("item", ctypes.c_void_p)]

    class Ev(ctypes.Structure):
        _fields_ = [("type", ctypes.c_int), ("obj", ctypes.c_void_p), ("u", U)]
    ev = Ev()
    ev.u.item = ptr
    return ev


class Player:
    def __init__(self):
        self.renderer, self.time, self.opened = "unset", 42_000, []
    def set_renderer(self, item): self.renderer = item
    def get_time(self): return self.time
    def is_playing(self): return True


class EngineCast(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.e = Engine(Store(str(Path(self.temp.name) / "data.json")))
        self.fake = FakeVlc()
        self.fake.items = {0x1000: Item("Living room TV"), 0x2000: Item("Bedroom")}

    def tearDown(self):
        self.temp.cleanup()

    def test_devices_come_and_go(self):
        e = self.e
        changed = []
        e.renderers_changed.connect(lambda: changed.append(1))
        with patch.object(engine, "vlc", self.fake):
            e._renderer_event(event_for(0x1000), True)
            e._renderer_event(event_for(0x2000), True)
            e._renderer_event(event_for(0x1000), True)       # announced twice: kept once
            self.assertEqual([r["name"] for r in e.renderers()], ["Bedroom", "Living room TV"])
            self.assertEqual(self.fake.items[0x1000].held, 1)
            e._renderer_event(event_for(0x2000), False)
            self.assertEqual([r["name"] for r in e.renderers()], ["Living room TV"])
            self.assertEqual(self.fake.items[0x2000].released, 1)   # let go of on the GUI side
        self.assertEqual(len(changed), 4)

    def test_cast_reopens_at_the_same_point(self):
        e = self.e
        e.player = Player()
        e.current = str(Path(self.temp.name) / "Film.mkv")
        opened = []
        e.open = lambda target, **kw: opened.append((target, kw["start_ms"], kw["paused"]))
        tv = {"item": "tv-item", "name": "Living room TV", "key": 1}
        e.cast_to(tv)
        self.assertEqual(e.player.renderer, "tv-item")
        self.assertEqual(opened, [(e.current, 42_000, False)])
        e.cast_to(None)
        self.assertIsNone(e.player.renderer)
        self.assertIsNone(e.renderer)

    def test_nothing_to_do_without_vlc(self):
        e = self.e
        e.start_discovery()
        self.assertFalse(e.looking_for_renderers())
        self.assertEqual(e.renderers(), [])

    @unittest.skipIf(REAL_VLC is None, "needs VLC")
    def test_real_vlc_discovery_starts_and_stops_cleanly(self):
        with patch.object(engine, "vlc", REAL_VLC):
            e = Engine(Store(str(Path(self.temp.name) / "real.json")))
            e.start_discovery()            # may find nothing, or have no Chromecast support at all
            e.renderers()
            e.recreate()                   # a rebuilt engine keeps looking if it was
            e.shutdown()
            self.assertFalse(e.looking_for_renderers())


class WindowCast(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))
        self.store.set_setting("onboarded", True)
        with patch.object(MainWindow, "_welcome", lambda self: None), patch.object(MainWindow, "_vlc_missing"):
            self.win = MainWindow(self.store)
        self.toasts = []
        self.win.toast = lambda msg, *a, **k: self.toasts.append(msg)

    def tearDown(self):
        self.win.close()
        self.temp.cleanup()

    def test_menu_lists_devices(self):
        w = self.win
        e = w.engine
        tv = {"item": None, "name": "Living room TV", "key": 1, "type": "chromecast"}
        e._renderers = {1: tv}
        m = w.build_cast_menu()
        w._fill_cast_menu(m)
        texts = [a.text() for a in m.actions() if a.text()]
        self.assertEqual(texts, ["This computer", "On your network", "Living room TV"])
        self.assertTrue(m.actions()[0].isChecked())
        casts = []
        e.cast_to = lambda r: casts.append(r)
        next(a for a in m.actions() if a.text() == "Living room TV").trigger()
        self.assertEqual(casts, [tv])
        self.assertIn("Casting to Living room TV", self.toasts)
        self.assertFalse(w.top.cast_chip.isHidden())
        self.assertIn("Living room TV", w.top.cast_chip.text())
        w.cast_to(None)
        self.assertTrue(w.top.cast_chip.isHidden())

    def test_menu_while_nothing_is_found(self):
        w = self.win
        m = w.build_cast_menu()
        w._fill_cast_menu(m)
        texts = [a.text() for a in m.actions() if a.text()]
        self.assertEqual(texts[0], "This computer")
        self.assertIn("isn't available", texts[-1])    # this test has no VLC, so no discovery
        w.engine._discoverers = ["looking"]
        w._fill_cast_menu(m)
        self.assertIn("Looking for Chromecasts", [a.text() for a in m.actions()][-1])
        w.engine._discoverers = []

    def test_new_devices_refresh_an_open_menu(self):
        w = self.win
        m = w.build_cast_menu()
        w._fill_cast_menu(m)
        w.engine._renderers = {7: {"item": None, "name": "Kitchen", "key": 7, "type": ""}}
        w._renderers_changed()
        self.assertIn("Kitchen", [a.text() for a in m.actions()])


if __name__ == "__main__":
    unittest.main()
