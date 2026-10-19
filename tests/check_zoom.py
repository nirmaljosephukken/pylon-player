"""Interactive zoom (#39): zoom around a point, pan limits, reset, and drag not counting as a click."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication
from app import engine
engine.vlc = None
from app.engine import Engine, MAX_ZOOM
from app.store import DEFAULT_SHORTCUTS, Store
from app.window import VideoSurface

app = QApplication.instance() or QApplication([])


class Zoom(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))
        self.e = Engine(self.store)
        self.e.video_size = lambda: (1280, 720)

    def tearDown(self):
        self.temp.cleanup()

    def test_zoom_keeps_point_under_cursor(self):
        e = self.e
        e.zoom_at(2.0, 0.25, 0.75)
        z = e.izoom
        self.assertAlmostEqual(z["w"], 640); self.assertAlmostEqual(z["h"], 360)
        # the source point that was at 25%/75% is still at 25%/75% of the view
        self.assertAlmostEqual(z["x"] + 0.25 * z["w"], 0.25 * 1280)
        self.assertAlmostEqual(z["y"] + 0.75 * z["h"], 0.75 * 720)

    def test_limits_and_reset(self):
        e = self.e
        for _ in range(30):
            e.zoom_at(1.25, 1.0, 1.0)
        self.assertAlmostEqual(e.zoom_level(), MAX_ZOOM)
        z = e.izoom
        self.assertLessEqual(z["x"] + z["w"], 1280 + 1e-6)
        self.assertLessEqual(z["y"] + z["h"], 720 + 1e-6)
        e.pan_by(-50, -50)                       # can't pan past the edge
        self.assertAlmostEqual(e.izoom["x"] + e.izoom["w"], 1280)
        e.pan_by(50, 50)
        self.assertEqual((e.izoom["x"], e.izoom["y"]), (0.0, 0.0))
        for _ in range(30):
            e.zoom_at(0.8)
        self.assertIsNone(e.izoom)               # zooming all the way out turns it off
        e.zoom_at(2.0); e.set_zoom(0.0)
        self.assertIsNone(e.izoom)               # the sidebar's zoom choice replaces it

    def test_crop_uses_border_form(self):
        # VLC 3 misreads "WxH+X+Y" as edges (#41), so the crop is sent as left+top+right+bottom
        e = self.e
        sent = []
        class Player:
            def video_set_scale(self, s): pass
            def video_set_crop_geometry(self, g): sent.append(g)
        e.player = Player()
        e.zoom_at(2.0, 0.75, 0.25)
        self.assertEqual(sent[-1], "480+90+160+270")   # 640x360 area starting at 480,90
        l, t, r, b = map(int, sent[-1].split("+"))
        self.assertEqual((1280 - l - r, 720 - t - b), (640, 360))   # same shape as the video

    def test_shortcuts_are_unique(self):
        seqs = [v[1] for v in DEFAULT_SHORTCUTS.values()]
        self.assertEqual(len(seqs), len(set(seqs)))
        self.assertEqual(DEFAULT_SHORTCUTS["zoom_in"][1], "Ctrl+=")

    def _mouse(self, w, kind, pos, buttons=Qt.LeftButton):
        b = Qt.NoButton if kind == QEvent.MouseButtonRelease else Qt.LeftButton
        ev = QMouseEvent(kind, QPointF(*pos), QPointF(*pos), Qt.LeftButton,
                         Qt.NoButton if kind == QEvent.MouseButtonRelease else buttons, Qt.NoModifier)
        QApplication.sendEvent(w, ev)

    def test_drag_pans_and_is_not_a_click(self):
        self.store.set_setting("mouse_double", "none")      # single clicks act immediately
        s = VideoSurface(self.store)
        actions, pans = [], []
        s.action.connect(actions.append); s.pan.connect(pans.append)
        s.set_zoomed(True)
        self._mouse(s, QEvent.MouseButtonPress, (10, 10))
        self._mouse(s, QEvent.MouseMove, (40, 30))
        self._mouse(s, QEvent.MouseButtonRelease, (40, 30))
        self.assertEqual(actions, [])
        self.assertEqual(len(pans), 1)
        self._mouse(s, QEvent.MouseButtonPress, (10, 10))   # a plain click still works
        self._mouse(s, QEvent.MouseButtonRelease, (10, 10))
        self.assertEqual(actions, ["play_pause"])
        s.set_zoomed(False)                                  # not zoomed: dragging does nothing
        self._mouse(s, QEvent.MouseButtonPress, (10, 10))
        self._mouse(s, QEvent.MouseMove, (60, 60))
        self.assertEqual(len(pans), 1)

    def test_ctrl_wheel_zooms_plain_wheel_is_volume(self):
        s = VideoSurface(self.store)
        vols, zooms = [], []
        s.wheel.connect(vols.append); s.zoom_wheel.connect(lambda d, p: zooms.append(d))
        for mod in (Qt.NoModifier, Qt.ControlModifier):
            ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(), QPoint(0, 120), Qt.NoButton, mod,
                             Qt.NoScrollPhase, False)
            QApplication.sendEvent(s, ev)
        self.assertEqual(vols, [120]); self.assertEqual(zooms, [120])


if __name__ == "__main__":
    unittest.main()
