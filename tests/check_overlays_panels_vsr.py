"""1.6.6 fixes.
#81: on Wayland desktops (Pylon runs through XWayland) COSMIC's window manager placed the floating bars
     itself and ignored later moves, so they stacked in a corner and didn't follow the window. There the
     floating windows now bypass the window manager, and elsewhere Pylon checks where the bars really
     went and switches if the window manager moved them. Bypassing windows hide while Pylon isn't the
     active app. Pinned bars are now ordinary parts of the window, laid out above and below the video.
#42: RTX Super Resolution shows a picture only while VLC's video covers the whole screen. In full screen
     with it on, panels float over the video instead of shrinking it, and Super Resolution is set aside
     while the picture itself can't cover the screen (an aspect ratio, crop or fixed zoom), and comes back
     when it can.
#54/#63: the side panels slide in and out (Preferences > Interface can turn it off)."""
import os
import sys
import tempfile
import time
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer
from PySide6.QtWidgets import QApplication
from app import engine
engine.vlc = None
from app import overlay
from app import window as window_mod
from app.controls import BottomBar, TopBar
from app.stage import PAGE_VIDEO
from app.store import Store
from app.window import MainWindow
from app.window_panels import PANEL_SLIDE_MS

app = QApplication.instance() or QApplication([])


def wait(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class Base(unittest.TestCase):
    def setUp(self):
        overlay.reset_for_tests()
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))
        self.store.set_setting("onboarded", True)
        with patch.object(MainWindow, "_welcome", lambda self: None), patch.object(MainWindow, "_vlc_missing"):
            self.win = MainWindow(self.store)
        self.win._vlc_missing = lambda: None
        self.toasts = []
        self.win.toast = lambda text, *a, **k: self.toasts.append(text)
        self.win.resize(1200, 700)
        self.win.show()
        self.win._ui_timer.stop()
        wait(100)

    def tearDown(self):
        self.win.close()
        self.temp.cleanup()
        overlay.reset_for_tests()

    def tick(self):
        self.win._ui_tick()
        wait()


class OverlayMode(unittest.TestCase):
    def tearDown(self):
        overlay.reset_for_tests()

    def mode(self, platform, env):
        overlay.reset_for_tests()
        with patch.object(overlay, "_platform", lambda: platform), patch.dict(os.environ, env, clear=False), \
                patch.object(overlay.sys, "platform", "linux"):
            for k in ("WAYLAND_DISPLAY", "XDG_SESSION_TYPE", "PYLON_OVERLAYS"):
                if k not in env:
                    os.environ.pop(k, None)
            return overlay.bypass(), bool(overlay.flags() & Qt.X11BypassWindowManagerHint)

    def test_xwayland_bypasses_the_window_manager(self):
        self.assertEqual(self.mode("xcb", {"WAYLAND_DISPLAY": "wayland-1"}), (True, True))
        self.assertEqual(self.mode("xcb", {"XDG_SESSION_TYPE": "wayland"}), (True, True))

    def test_plain_x11_and_other_platforms_keep_the_window_manager(self):
        self.assertEqual(self.mode("xcb", {"XDG_SESSION_TYPE": "x11"}), (False, False))
        self.assertEqual(self.mode("windows", {}), (False, False))

    def test_environment_forces_either_mode(self):
        self.assertEqual(self.mode("xcb", {"PYLON_OVERLAYS": "bypass"}), (True, True))
        self.assertEqual(self.mode("xcb", {"WAYLAND_DISPLAY": "w", "PYLON_OVERLAYS": "managed"}), (False, False))


class MisplacedBars(Base):
    def show_bars(self):
        w = self.win
        w.stage.setCurrentIndex(PAGE_VIDEO)
        w._app_active = lambda: True
        w._force_show_until = time.monotonic() + 60
        w._moving_until = 0                          # showing the window counts as a move on X11 (#59)
        self.tick()

    def test_switches_when_the_window_manager_moves_the_bars(self):
        """Like COSMIC (#81): the window manager keeps the bars somewhere else."""
        w = self.win
        self.show_bars()
        self.assertTrue(w._bars_visible)
        with patch.object(overlay, "_platform", lambda: "xcb"), \
                patch.object(overlay, "real_position", lambda bar: (5, 5)):
            for _ in range(4):
                w._overlay_geo = None
                self.tick()
        self.assertTrue(overlay.bypass())
        for bar in (w.top, w.bottom, w.osd, w.seek_preview):
            self.assertTrue(bar.windowFlags() & Qt.X11BypassWindowManagerHint)
        w._moving_until = 0
        self.tick()
        self.assertTrue(w._bars_visible)             # shown again, now where Pylon puts them
        self.assertEqual(w.top.pos(), w.stage.mapToGlobal(QPoint(0, 0)))

    def test_bars_where_they_belong_keep_the_window_manager(self):
        w = self.win
        self.show_bars()
        with patch.object(overlay, "_platform", lambda: "xcb"), \
                patch.object(overlay, "real_position", lambda bar: (bar.x(), bar.y())):
            for _ in range(4):
                w._overlay_geo = None
                self.tick()
        self.assertFalse(overlay.bypass())

    def test_bypassing_bars_hide_while_another_app_is_active(self):
        w = self.win
        overlay._state["bypass"] = True
        w._overlay_mode_changed()
        self.show_bars()
        self.assertTrue(w._bars_visible)
        w._app_active = lambda: False
        self.tick()
        self.assertFalse(w._bars_visible)

    def test_managed_bars_ignore_the_active_app(self):
        w = self.win
        self.show_bars()
        w._app_active = lambda: False
        w.stage.setCurrentIndex(window_mod.PAGE_AUDIO)   # the audio page always shows its bars
        w._moving_until = 0
        self.tick()
        self.assertTrue(w._bars_visible)


class PinnedBars(Base):
    def test_pinned_bars_are_part_of_the_window(self):
        w = self.win
        w.stage.setCurrentIndex(PAGE_VIDEO)
        self.store.set_setting("pin_controls", True)
        self.tick()
        for bar in (w.top, w.bottom):
            self.assertFalse(bar.isWindow())
            self.assertTrue(bar.isVisible())
        self.assertEqual(w.top.height(), TopBar.HEIGHT)
        self.assertEqual(w.bottom.height(), BottomBar.HEIGHT)
        self.store.set_setting("pin_controls", False)
        self.tick()
        for bar in (w.top, w.bottom):
            self.assertTrue(bar.isWindow())

    def test_full_screen_floats_them_again(self):
        w = self.win
        w.stage.setCurrentIndex(PAGE_VIDEO)
        self.store.set_setting("pin_controls", True)
        self.tick()
        w.isFullScreen = lambda: True
        self.tick()
        self.assertTrue(w.top.isWindow())
        self.assertEqual(w.video.height(), w.middle.height())


class Slide(Base):
    def test_panels_slide_open_and_closed(self):
        w = self.win
        w.toggle_library(True)
        self.assertTrue(w.library.isVisible())
        wait(PANEL_SLIDE_MS // 3)
        self.assertLess(w.lib_slot.width(), w.library.WIDTH)       # on its way
        self.assertEqual(w.library.width(), w.library.WIDTH)       # the panel itself keeps its width
        wait(PANEL_SLIDE_MS * 2)
        self.assertEqual(w.lib_slot.width(), w.library.WIDTH)
        self.assertEqual(w.library.x(), 0)
        w.toggle_library(False)
        self.assertTrue(w.library.isVisible())                      # still sliding out
        wait(PANEL_SLIDE_MS * 2)
        self.assertFalse(w.library.isVisible())
        self.assertFalse(w.lib_slot.is_open)

    def test_toggling_again_mid_slide_turns_around(self):
        w = self.win
        w.toggle_sidebar(True)
        wait(PANEL_SLIDE_MS // 3)
        w.toggle_sidebar()                                          # close before it finished opening
        self.assertFalse(w.side_slot.is_open)
        wait(PANEL_SLIDE_MS * 2)
        self.assertFalse(w.sidebar.isVisible())

    def test_setting_turns_the_slide_off(self):
        w = self.win
        self.store.set_setting("animate_panels", False)
        w.toggle_sidebar(True)
        self.assertEqual(w.side_slot.width(), w.sidebar.WIDTH)
        w.toggle_sidebar(False)
        self.assertFalse(w.sidebar.isVisible())


class SuperResolution(Base):
    def setUp(self):
        super().setUp()
        self.platform = patch.object(window_mod.sys, "platform", "win32")
        self.platform.start()
        self.store.set_setting("rtx_upscale", True)
        w = self.win
        self.full = False
        w.isFullScreen = lambda: self.full
        e = w.engine
        p = MagicMock()
        p.video_get_size.return_value = (1920, 1080)
        p.is_playing.return_value = 0
        p.get_time.return_value = 0
        p.get_length.return_value = 0
        e.player = p
        w.sidebar.refresh_tracks = lambda: None    # a fake player has no track or device lists
        e.current = "/films/a.mkv"
        e.has_video = lambda: True
        e.rebuild = MagicMock()
        self.shape = {"aspect": Fraction(16, 9), "src": (1920, 1080), "crop": (0, 0, 0, 0)}
        e.picture_shape = lambda: self.shape
        w.stage.setCurrentIndex(PAGE_VIDEO)

    def tearDown(self):
        self.platform.stop()
        super().tearDown()

    def go_full(self):
        self.full = True
        self.win._sync_panel_mode()
        self.win.resize(1600, 900)                 # a 16:9 "screen"
        wait(100)

    def test_panels_float_over_the_video_in_full_screen(self):
        w = self.win
        self.go_full()
        self.assertTrue(w._panels_floating)
        before = w.video.size()
        w.toggle_library(True)
        w.toggle_sidebar(True)
        wait(PANEL_SLIDE_MS * 2)
        self.assertEqual(w.video.size(), before)               # the video keeps the whole screen
        self.assertEqual(w.lib_slot.geometry().left(), 0)
        self.assertEqual(w.side_slot.geometry().right(), w.centralWidget().width() - 1)
        self.assertTrue(w.lib_slot.testAttribute(Qt.WA_NativeWindow))   # above VLC's native window
        w._overlay_geo = None
        w._place_overlays()
        self.assertEqual(w.top.x(), w.stage.mapToGlobal(QPoint(w.library.WIDTH, 0)).x())   # bars clear of them
        self.assertEqual(w.top.width(), w.stage.width() - w.library.WIDTH - w.sidebar.WIDTH)

    def test_leaving_full_screen_lays_them_out_again(self):
        w = self.win
        self.go_full()
        w.toggle_library(True)
        wait(PANEL_SLIDE_MS * 2)
        self.full = False
        w._sync_panel_mode()
        w.resize(1200, 700)
        wait(100)
        self.assertFalse(w._panels_floating)
        self.assertEqual(w.centralWidget().layout().indexOf(w.lib_slot), 0)
        self.assertEqual(w.middle.x(), w.library.WIDTH)

    def test_no_floating_without_super_resolution(self):
        w = self.win
        self.store.set_setting("rtx_upscale", False)
        self.go_full()
        self.assertFalse(w._panels_floating)

    def test_set_aside_while_the_picture_cant_fill_the_screen(self):
        w, e = self.win, self.win.engine
        self.go_full()
        w._vsr_policy()
        self.assertFalse(e.vsr_paused)                     # 16:9 on a 16:9 screen
        self.shape = {"aspect": Fraction(4, 3), "src": (1440, 1080), "crop": (0, 0, 0, 0)}             # 4:3: bars at the sides
        w._vsr_policy()
        self.assertTrue(e.vsr_paused)
        e.rebuild.assert_called_once()
        self.assertIn("paused", self.toasts[-1])
        self.assertFalse(w._vsr_active())                  # no picture-sized area while it's aside
        self.shape = {"aspect": Fraction(16, 9), "src": (1920, 1080), "crop": (0, 0, 0, 0)}
        w._vsr_policy()
        self.assertFalse(e.vsr_paused)
        self.assertEqual(e.rebuild.call_count, 2)

    def test_a_window_leaves_it_alone(self):
        w, e = self.win, self.win.engine
        self.shape = {"aspect": Fraction(4, 3), "src": (1440, 1080), "crop": (0, 0, 0, 0)}
        w._vsr_policy()
        self.assertFalse(e.vsr_paused)
        e.rebuild.assert_not_called()

    def test_vlc_is_told_only_when_not_paused(self):
        e = self.win.engine
        with patch.object(engine.sys, "platform", "win32"):
            self.assertIn("--d3d11-upscale-mode=super", e._args())
            e.vsr_paused = True
            self.assertNotIn("--d3d11-upscale-mode=super", e._args())


if __name__ == "__main__":
    unittest.main()
