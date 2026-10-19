"""Custom 10-band equalizer and preset tooltips (#38)."""
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
from app.engine import CUSTOM_EQ, Engine
from app.sidebar import EQ_TIPS, EqualizerPanel
from app.store import Store
from app.window import MainWindow

app = QApplication.instance() or QApplication([])


def wait(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class Equalizer(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))
        self.store.set_setting("onboarded", True)
        with patch.object(MainWindow, "_welcome", lambda self: None), patch.object(MainWindow, "_vlc_missing"):
            self.win = MainWindow(self.store)
        self.win._vlc_missing = lambda: None
        self.sb = self.win.sidebar

    def tearDown(self):
        self.win.close()
        self.temp.cleanup()

    def test_clean_curve(self):
        self.assertIsNone(Engine.clean_curve(None))
        self.assertIsNone(Engine.clean_curve({"preamp": "x", "bands": []}))
        c = Engine.clean_curve({"preamp": 50, "bands": [-99, 3.5]})
        self.assertEqual(c["preamp"], 20.0)
        self.assertEqual(c["bands"][:2], [-20.0, 3.5])
        self.assertEqual(len(c["bands"]), 10)

    def test_every_vlc_preset_has_a_tip(self):
        names = ["Flat", "Classical", "Club", "Dance", "Full bass", "Full bass and treble", "Full treble",
                 "Headphones", "Large Hall", "Live", "Party", "Pop", "Reggae", "Rock", "Ska", "Soft",
                 "Soft rock", "Techno"]
        self.assertEqual(sorted(EQ_TIPS), sorted(names))

    def test_custom_panel_curve_and_persistence(self):
        sb = self.sb
        self.assertTrue(sb.eq_custom.isHidden())
        sb._set_eq(CUSTOM_EQ)
        self.assertFalse(sb.eq_custom.isHidden())
        self.assertEqual(self.win.engine.live["eq"], CUSTOM_EQ)
        sb.eq_custom.bands[0].setValue(12)          # +6 dB
        sb.eq_custom.preamp.slider.setValue(-4)
        wait(900)                                   # live apply (60 ms) and save (600 ms)
        curve = self.win.engine.live["eq_custom"]
        self.assertEqual(curve["bands"][0], 6.0)
        self.assertEqual(curve["preamp"], -2.0)
        self.assertEqual(self.store.setting("eq_custom")["bands"][0], 6.0)
        # presets remember the curve, and switching to a built-in preset hides the panel
        sb._set_eq(-1)
        self.assertTrue(sb.eq_custom.isHidden())
        # choosing Custom again brings back your saved curve
        sb._set_eq(CUSTOM_EQ)
        self.assertEqual(sb.eq_custom.curve()["bands"][0], 6.0)

    def test_preset_round_trip(self):
        sb = self.sb
        sb._set_eq(CUSTOM_EQ)
        sb.eq_custom.bands[3].setValue(-10)
        wait(150)
        saved = sb.current_settings()
        self.assertEqual(saved["eq"], CUSTOM_EQ)
        self.assertEqual(saved["eq_custom"]["bands"][3], -5.0)
        sb._set_eq(-1)
        self.win.apply_preset(saved, live=True)
        self.assertEqual(self.win.engine.live["eq"], CUSTOM_EQ)
        self.assertFalse(sb.eq_custom.isHidden())
        self.assertEqual(sb.eq_custom.curve()["bands"][3], -5.0)

    def test_flat_button(self):
        p = EqualizerPanel([])
        p.set_curve({"preamp": 3, "bands": [5] * 10})
        got = []
        p.changed.connect(got.append)
        from PySide6.QtWidgets import QPushButton
        flat = [b for b in p.findChildren(QPushButton) if b.text() == "Flat"][0]
        flat.click()
        wait(150)
        self.assertEqual(got[-1], {"preamp": 0.0, "bands": [0.0] * 10})


if __name__ == "__main__":
    unittest.main()
