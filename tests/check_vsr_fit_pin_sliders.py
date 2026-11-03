"""1.6.5 fixes.
#42: with Super Resolution on, VLC's video area is sized to the picture and Pylon draws the black bars,
     because Super Resolution goes black whenever VLC letterboxes an upscaled picture, even by a pixel.
     The aspect ratio sent to VLC makes its own sums (vout_display_PlacePicture) fill the area exactly,
     for any area, crop, zoom or aspect ratio. Panels open in full screen again, and the redraw nudge
     never letterboxes.
#68/#78: "Keep the controls visible" puts the video between the bars: the margins go on the stage
     itself, which a QStackedWidget's own layout ignored.
#79: a clicked settings slider takes Left and Right (one step each) instead of jumping the video, and
     clicking the video or pressing Esc gives the keys back."""
import random
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEvent, QEventLoop, QPoint, QPointF, QRect, Qt, QTimer
from PySide6.QtGui import QKeyEvent, QShowEvent, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app import engine
engine.vlc = None
from app.engine import Engine, fill_aspects, vlc_place
from app.sidebar import KeySlider, ValueSlider
from app.stage import PAGE_VIDEO
from app.store import Store
from app.controls import BottomBar, TopBar
from app.window import MainWindow

app = QApplication.instance() or QApplication([])


def wait(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def fake_player(size=(1920, 1080)):
    p = MagicMock()
    p.video_get_size.return_value = size
    p.video_get_track.return_value = 1
    p.get_media.return_value = None          # no track details: square pixels
    p.is_playing.return_value = 0
    p.get_time.return_value = 0
    p.get_length.return_value = 0
    return p


class PlaceMaths(unittest.TestCase):
    """fill_aspects() against Pylon's copy of VLC 3's own sums."""

    def test_vlc_place_letterboxes_like_vlc(self):
        # a 16:9 picture in an area one pixel short at the bottom: VLC leaves a pixel at the sides (1.5.1)
        self.assertEqual(vlc_place((1920, 1080), (1, 1), (3840, 2159)), (3838, 2159))
        self.assertEqual(vlc_place((1920, 1080), (1, 1), (3840, 2160)), (3840, 2160))
        self.assertIsNone(vlc_place((3840, 2160), (2 ** 21, 1), (100, 100)))   # VLC's 32-bit sums overflow

    def test_every_area_is_filled_exactly(self):
        rnd = random.Random(42)
        sources = [(1920, 1080), (3840, 2160), (1280, 720), (720, 576), (720, 480), (1920, 800), (1440, 1080)]
        for _ in range(3000):
            src = rnd.choice(sources)
            area = (rnd.randint(200, 7680), rnd.randint(150, 4320))
            ratios = fill_aspects(area, src, src)
            self.assertTrue(ratios, (area, src))
            if area[0] / area[1] < 4:                        # any real screen or window has a second one
                self.assertEqual(len(ratios), 2, (area, src))
            for a, b in ratios:
                self.assertEqual(vlc_place(src, (a * src[1], b * src[0]), area), area, (area, src, a, b))
                self.assertLess(a * src[1], 2 ** 32)

    def test_cropped_pictures_fill_too(self):
        rnd = random.Random(7)
        for _ in range(1000):
            src = (1920, 1080)
            crop = (rnd.randint(200, 1920), rnd.randint(100, 1080))
            area = (rnd.randint(300, 3840), rnd.randint(200, 2160))
            for a, b in fill_aspects(area, crop, src):
                self.assertEqual(vlc_place(crop, (a * src[1], b * src[0]), area), area)

    def test_the_picture_is_not_visibly_stretched(self):
        area = (3330, 1873)                               # full screen with a panel open
        a, b = fill_aspects(area, (1920, 1080), (1920, 1080))[0]
        self.assertAlmostEqual(a / b, 3330 / 1873, delta=1 / 1873)
        self.assertEqual(fill_aspects((3840, 2160), (1920, 1080), (1920, 1080))[0], (16, 9))


class Shape(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.e = Engine(Store(str(Path(self.temp.name) / "data.json")))
        self.e.player = fake_player()

    def tearDown(self):
        self.temp.cleanup()

    def test_plain_video(self):
        s = self.e.picture_shape()
        self.assertEqual(s["aspect"], Fraction(16, 9))
        self.assertEqual(s["crop"], (0, 0, 0, 0))

    def test_chosen_aspect_ratio(self):
        self.e.set_aspect("4:3")
        self.assertEqual(self.e.picture_shape()["aspect"], Fraction(4, 3))

    def test_crop_ratio_is_cut_like_vlc(self):
        self.e.set_crop("235:100")
        s = self.e.picture_shape()
        self.assertEqual(s["crop"], (0, 131, 0, 132))     # what VLC's VoutDisplayCropRatio gives
        self.assertAlmostEqual(float(s["aspect"]), 2.35, places=2)

    def test_fixed_zoom_and_turned_crops_are_left_to_vlc(self):
        self.e.set_zoom(1.0)
        self.assertIsNone(self.e.picture_shape())
        self.e.set_zoom(0.0)
        self.e.transform = "90"
        self.assertEqual(self.e.picture_shape()["aspect"], Fraction(9, 16))
        self.e.set_crop("4:3")
        self.assertIsNone(self.e.picture_shape())

    def test_fit_sends_an_exact_aspect_and_border_crop(self):
        p = self.e.player
        self.e.set_crop("235:100")
        self.e.set_fit((3330, 1417))
        aspect = p.video_set_aspect_ratio.call_args[0][0]
        crop = p.video_set_crop_geometry.call_args[0][0]
        self.assertEqual(crop, "0+131+0+132")
        a, b = map(int, aspect.split(":"))
        self.assertEqual(vlc_place((1920, 817), (a * 1080, b * 1920), (3330, 1417)), (3330, 1417))
        self.e.set_fit(None)                               # back to the user's own values
        self.assertEqual(p.video_set_crop_geometry.call_args[0][0], "235:100")
        self.assertIsNone(p.video_set_aspect_ratio.call_args[0][0])

    def test_redraw_nudge_swaps_ratio_and_never_letterboxes(self):
        p = self.e.player
        self.e.set_fit((3330, 1873))
        first = p.video_set_aspect_ratio.call_args[0][0]
        p.video_set_crop_geometry.reset_mock()
        self.e.refresh_upscaler()
        second = p.video_set_aspect_ratio.call_args[0][0]
        self.assertNotEqual(first, second)
        sent = [c[0][0] for c in p.video_set_crop_geometry.call_args_list]
        self.assertNotIn("0+0+0+2", sent)
        a, b = map(int, second.split(":"))
        self.assertEqual(vlc_place((1920, 1080), (a * 1080, b * 1920), (3330, 1873)), (3330, 1873))

    def test_without_fit_the_old_nudge_stays(self):
        p = self.e.player
        self.e.refresh_upscaler()
        self.assertEqual(p.video_set_crop_geometry.call_args[0][0], "0+0+0+2")

    def test_track_with_union_details(self):
        # python-vlc lists audio/video/subtitle one after another, but libvlc has them in a union
        self.assertIsNone(engine._video_track(object()))


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))
        self.store.set_setting("onboarded", True)
        with patch.object(MainWindow, "_welcome", lambda self: None), patch.object(MainWindow, "_vlc_missing"):
            self.win = MainWindow(self.store)
        self.win._vlc_missing = lambda: None
        self.win.toast = lambda *a, **k: None
        self.win.open_file_dialog = lambda *a, **k: None

    def tearDown(self):
        self.win.engine.player = None
        self.win.close()
        self.temp.cleanup()


class WindowFit(Base):
    def setUp(self):
        super().setUp()
        w = self.win
        w.engine.player = fake_player()
        w.engine.current = "/films/a.mkv"
        w.resize(1400, 800)
        w.show()
        w.stage.setCurrentIndex(PAGE_VIDEO)
        wait(50)
        self.active = True
        w._vsr_active = lambda: self.active
        w.sidebar.refresh_tracks = lambda: None       # the fake player has no real track lists

    def test_canvas_is_the_picture_centred(self):
        w = self.win
        w._fit_video()
        v, c = w.video, w.video.canvas
        r = c.geometry()
        self.assertAlmostEqual(r.width() / r.height(), 16 / 9, delta=0.01)
        self.assertTrue(r.width() == v.width() or r.height() == v.height())
        self.assertLessEqual(abs(r.center().x() - v.rect().center().x()), 1)
        self.assertLessEqual(abs(r.center().y() - v.rect().center().y()), 1)
        self.assertEqual(w.engine.fit, c.device_size())

    def test_panel_and_resize_refit(self):
        w = self.win
        w._fit_video()
        before = w.video.canvas.geometry()
        w.toggle_sidebar(True)
        wait(50)
        after = w.video.canvas.geometry()
        self.assertLess(after.width(), before.width())
        self.assertEqual(w.engine.fit, w.video.canvas.device_size())

    def test_aspect_change_refits(self):
        w = self.win
        w.engine.set_aspect("4:3")
        r = w.video.canvas.geometry()
        self.assertAlmostEqual(r.width() / r.height(), 4 / 3, delta=0.01)

    def test_off_fills_the_page(self):
        w = self.win
        w._fit_video()
        self.active = False
        w._fit_video()
        self.assertEqual(w.video.canvas.geometry(), w.video.rect())
        self.assertIsNone(w.engine.fit)

    def test_vlc_draws_into_the_canvas(self):
        w = self.win
        w.engine.set_window = MagicMock()
        w._shown_once = False
        w.showEvent(QShowEvent())
        w.engine.set_window.assert_called_with(int(w.video.canvas.winId()))


class CanvasInput(Base):
    def test_clicks_and_wheel_reach_the_surface(self):
        v = self.win.video
        v.resize(800, 450)
        v.show()
        v.fit_canvas(QRect(100, 0, 600, 450))
        got = []
        v.action.connect(got.append)
        v.wheel.connect(lambda d: got.append(("wheel", d)))
        self.store.set_setting("mouse_double", "none")
        QTest.mouseClick(v.canvas, Qt.LeftButton, pos=QPoint(10, 10))
        ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(), QPoint(0, 120), Qt.NoButton, Qt.NoModifier,
                         Qt.NoScrollPhase, False)
        QApplication.sendEvent(v.canvas, ev)
        self.assertIn(self.store.setting("mouse_single"), got)
        self.assertIn(("wheel", 120), got)


class PinnedControls(Base):
    def test_video_sits_between_the_bars(self):
        w = self.win
        self.store.set_setting("pin_controls", True)
        w.engine.current = "/films/a.mkv"
        w.resize(1000, 700)
        w.show()
        w.stage.setCurrentIndex(PAGE_VIDEO)
        w._pin_state = None
        w._apply_pin()
        wait(50)
        self.assertEqual(w.video.height(), w.stage.height() - TopBar.HEIGHT - BottomBar.HEIGHT)
        self.assertEqual(w.video.y(), TopBar.HEIGHT)
        self.store.set_setting("pin_controls", False)
        w._apply_pin()
        wait(50)
        self.assertEqual(w.video.height(), w.stage.height())


class ArrowKeySliders(Base):
    def test_slider_takes_left_and_right_once_clicked(self):
        s = ValueSlider(0, 200, 1, 100)
        self.assertIsInstance(s.slider, KeySlider)
        self.assertEqual(s.slider.focusPolicy(), Qt.ClickFocus)
        got = []
        s.changed.connect(got.append)
        for key, want in ((Qt.Key_Right, 101), (Qt.Key_Left, 100), (Qt.Key_Left, 99)):
            over = QKeyEvent(QEvent.ShortcutOverride, key, Qt.NoModifier)
            QApplication.sendEvent(s.slider, over)
            self.assertTrue(over.isAccepted())             # the window's seek shortcut doesn't fire
            QApplication.sendEvent(s.slider, QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))
            self.assertEqual(s.value(), want)
        self.assertEqual(got, [101, 100, 99])
        over = QKeyEvent(QEvent.ShortcutOverride, Qt.Key_Right, Qt.ControlModifier)
        QApplication.sendEvent(s.slider, over)
        self.assertFalse(over.isAccepted())                 # Ctrl+Right still jumps a minute

    def test_steps_follow_the_slider(self):
        s = ValueSlider(-10000, 10000, 50, 0)
        QApplication.sendEvent(s.slider, QKeyEvent(QEvent.KeyPress, Qt.Key_Right, Qt.NoModifier))
        self.assertEqual(s.value(), 50)
        eq = KeySlider(Qt.Vertical)
        eq.setRange(-40, 40)
        QApplication.sendEvent(eq, QKeyEvent(QEvent.KeyPress, Qt.Key_Right, Qt.NoModifier))
        self.assertEqual(eq.value(), 1)                      # Right goes up on an equalizer band too

    def test_sidebar_sliders_and_equalizer_use_it(self):
        side = self.win.sidebar
        self.assertIsInstance(side.sharpen.slider, KeySlider)
        sliders = side.findChildren(KeySlider)
        self.assertGreaterEqual(len(sliders), 15)

    def test_clicking_the_video_or_esc_gives_the_keys_back(self):
        w = self.win
        w.resize(1200, 800)
        w.show()
        w.toggle_sidebar(True)
        wait(50)
        s = w.sidebar.sharpen.slider
        for drop in (lambda: w.video.pressed.emit(), lambda: w.do("exit_fullscreen")):
            s.setFocus(Qt.MouseFocusReason)
            w.activateWindow()
            wait(20)
            if QApplication.focusWidget() is not s:
                self.skipTest("no keyboard focus on this platform")
            drop()
            self.assertIsNot(QApplication.focusWidget(), s)


if __name__ == "__main__":
    unittest.main()
