"""Main window: stage (home / video / now playing) between the library on the
left and the settings sidebar on the right, with floating top and bottom
bars that appear when you move the mouse and vanish when you move away."""
import os
import sys
import time

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QCursor, QGuiApplication, QKeySequence, QShortcut, QRegion
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QHBoxLayout, QLineEdit, QMainWindow,
                               QStackedWidget, QVBoxLayout, QWidget)

from . import APP_NAME, overlay, theme
from .controls import BottomBar, TopBar
from .engine import NAV_ACTIVATE, NAV_DOWN, NAV_LEFT, NAV_RIGHT, NAV_UP, Engine
from .home import HomePage, NowPlayingPage
from .library import LibraryPanel
from .sidebar import SettingsSidebar
from .store import DEFAULT_SHORTCUTS, QUEUE_MODES
from .util import (SPEED_STEPS, fmt_delay, fmt_time, is_audio, is_disc, is_url, win_enable_close,
                   win_set_topmost)
from .stage import PAGE_AUDIO, PAGE_HOME, PAGE_VIDEO, VideoSurface  # noqa: F401  (tests import these from here)
from .thumbs import ThumbnailMaker
from .updates import UpdateChecker
from .waveform import WaveformMaker
from .widgets import IconButton, SeekPreview, Toast
from .window_menus import MenusMixin
from .window_panels import PanelsMixin
from .window_playback import PlaybackMixin
from .window_system import SystemMixin

VSR_FULLSCREEN_RETRIES_MS = (600, 1500)    # extra Super Resolution redraws in full screen (#42)
WINDOW_MOVE_HIDE_S = 0.25                   # floating bars stay hidden this long after the window moves (#59)

class MainWindow(SystemMixin, MenusMixin, PanelsMixin, PlaybackMixin, QMainWindow):
    def __init__(self, store):
        super().__init__()
        self.store = store
        theme.set_accent(store.setting("accent"))
        self.setWindowTitle(APP_NAME)
        self.resize(1200, 740)
        self.setMinimumSize(640, 400)
        self.setAcceptDrops(True)

        self.engine = Engine(store, self)      # starts VLC once, with the saved subtitle style

        self.queue: list[dict] = []
        self.qindex = -1
        self.queue_mode = self.store.setting("queue_mode") if self.store.setting("queue_mode") in QUEUE_MODES else "next"
        self.hide_ui = False
        self._pip = None
        self._last_mouse = QPoint()
        self._last_move = 0.0
        self._force_show_until = 0.0
        self._resume_until = 0.0
        self._resume_ms = 0
        self._track_prefs = ("", "")
        self._prefs_applied = False
        self._live_applied = False
        self._sleep_deadline = None
        self._sleep_end_of_file = False
        self._last_saved = 0.0
        self._overlay_geo = None
        self._bars_visible = False
        self.ab_loop = [None, None]      # A–B repeat: start and end in ms
        self._ab_jumped = 0.0
        self._in_menu = False            # a disc is showing its menu

        # ---------------- layout
        central = QWidget()
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.setCentralWidget(central)

        self.stage = QStackedWidget()
        self.stage.setObjectName("Stage")
        self.stage.setMinimumWidth(240)
        self.home = None  # created after library (home uses it)
        self.video = VideoSurface(store)
        self.now_playing = NowPlayingPage(self)

        # overlays (separate translucent windows over the video)
        self.top = TopBar(self)
        self.bottom = BottomBar(self)
        self.bottom.cone.set_max(self.engine.max_volume())
        for bar in (self.top, self.bottom):
            bar.setMouseTracking(True)
            bar.installEventFilter(self)
        self.osd = Toast(self)
        self.seek_preview = SeekPreview(self)
        self.thumbs = ThumbnailMaker(self)
        self.waves = WaveformMaker(self)
        self.waves.ready.connect(self._wave_ready, Qt.QueuedConnection)
        self.waves.silence.connect(self._silence_ready, Qt.QueuedConnection)
        self._trim = None                # (start, end) ms of a song's sound without its silence (#86)
        self._trim_started = self._trim_ended = False
        self.updater = UpdateChecker(self.store, self)
        self.updater.found.connect(self._update_found)
        self.updater.none.connect(self._update_none)
        self.updater.failed.connect(self._update_failed)
        self._update_release = None      # a newer release we know about
        self._manual_update_check = False

        self.library = LibraryPanel(self)
        self.home = HomePage(self)
        self.stage.addWidget(self.home)
        self.stage.addWidget(self.video)
        self.stage.addWidget(self.now_playing)
        self.sidebar = SettingsSidebar(self)
        self._make_panel_slots()          # the panels slide in their slots (#54, #63)
        self.library.show_queue_mode(self.queue_mode)

        # The stage sits in a column of its own. Pinned bars are laid out above and below it there,
        # as ordinary parts of the window, instead of floating over the video (#81).
        self.middle = QWidget()
        self.middle_lay = QVBoxLayout(self.middle)
        self.middle_lay.setContentsMargins(0, 0, 0, 0)
        self.middle_lay.setSpacing(0)
        self.middle_lay.addWidget(self.stage, 1)
        lay.addWidget(self.lib_slot)
        lay.addWidget(self.middle, 1)
        lay.addWidget(self.side_slot)

        # ---------------- wiring
        self.video.action.connect(lambda action: self.do(action, key=False))
        self.video.pressed.connect(self._drop_slider_focus)
        self.video.context.connect(self.show_context_menu)
        self.video.wheel.connect(lambda d: self.do("vol_up" if d > 0 else "vol_down", key=False))
        self.video.zoom_wheel.connect(self._zoom_wheel)
        # VLC 3's Super Resolution mode doesn't redraw at a new size after the video
        # area is resized: the picture stays the old size, or goes black (#42).
        # Restart the video output once the resize has settled.
        self._vsr_timer = QTimer(self)
        self._vsr_timer.setSingleShot(True)
        self._vsr_timer.setInterval(150)
        self._vsr_timer.timeout.connect(self._vsr_refresh)
        # In full screen some GPUs are still settling after 150 ms, and the picture stays
        # black (#42), so redraw again a little later. Restarting these on every resize
        # means they run once the panel has finished moving.
        self._vsr_late = []
        for ms in VSR_FULLSCREEN_RETRIES_MS:
            t = QTimer(self)
            t.setSingleShot(True)
            t.setInterval(ms)
            t.timeout.connect(self._vsr_refresh)
            self._vsr_late.append(t)
        # Super Resolution goes black whenever VLC has to letterbox the picture in its video area (#42),
        # so with it on, Pylon draws the black bars itself and sizes VLC's area to the picture.
        self.video.resized.connect(self._fit_video)
        self.engine.picture_changed.connect(self._fit_video)
        self.engine.wake_picture.connect(self._wake_picture)
        self.engine.vout_changed.connect(lambda _n: QTimer.singleShot(250, self._sync_audio_page), Qt.QueuedConnection)
        # ...and in full screen it needs the picture to cover the whole screen, or it's set aside.
        self._vsr_policy_timer = QTimer(self)
        self._vsr_policy_timer.setSingleShot(True)
        self._vsr_policy_timer.setInterval(500)
        self._vsr_policy_timer.timeout.connect(self._vsr_policy)
        for sig in (self.video.resized, self.engine.picture_changed, self.stage.currentChanged):
            sig.connect(lambda *_: self._vsr_policy_timer.start())
        self.stage.currentChanged.connect(lambda _i: self._fit_video())
        self.video.resized.connect(self._vsr_resized)
        QGuiApplication.instance().applicationStateChanged.connect(self._pip_app_state)
        self.video.pan.connect(self._pan_video)
        # a new file starts unzoomed; the sidebar's crop and zoom choices end interactive zoom
        self.engine.media_changed.connect(
            lambda _t: QTimer.singleShot(0, lambda: self.video.set_zoomed(bool(self.engine.izoom))))
        self.sidebar.zoom.picked.connect(lambda _v: self.video.set_zoomed(False))
        self.sidebar.crop.picked.connect(lambda _v: self.video.set_zoomed(False))

        t, b = self.top, self.bottom
        t.library_clicked.connect(lambda: self.toggle_library())
        t.folder_clicked.connect(lambda: self.browse_folder(self.current_folder()))
        t.pip_clicked.connect(self.toggle_pip)
        t.fullscreen_clicked.connect(self.toggle_fullscreen)
        t.menu_clicked.connect(lambda: self.show_main_menu(self.top.btn_menu))
        t.close_clicked.connect(self.close_media)
        b.play_clicked.connect(lambda: self.do("play_pause", key=False))
        b.prev_clicked.connect(lambda: self.do("prev", key=False))
        b.next_clicked.connect(lambda: self.do("next", key=False))
        b.subs_clicked.connect(self.show_subs_menu)
        b.audio_clicked.connect(self.show_audio_menu)
        b.queue_clicked.connect(lambda: self.toggle_queue())
        b.sidebar_clicked.connect(lambda: self.toggle_sidebar())
        b.mute_clicked.connect(lambda: self.do("mute", key=False))
        b.resume_clicked.connect(self._accept_resume)
        b.speed_clicked.connect(lambda: self.open_sidebar_tab(3))
        b.seek.seek_requested.connect(self.engine.seek)
        b.seek.hovered.connect(self._seek_hover)
        b.seek.hover_left.connect(self.seek_preview.defer_hide)
        self.seek_preview.clicked.connect(self.engine.seek)
        b.cone.volume_changed.connect(self._cone_volume)
        b.set_volume(self.engine.volume(), False)

        e = self.engine
        # Queued: VLC can fire these from inside our own call into it (e.g. stop()),
        # and calling back into VLC from there would deadlock.
        e.state_changed.connect(self._on_state, Qt.QueuedConnection)
        e.length_changed.connect(lambda _: self.bottom.set_time(e.time(), e.length()), Qt.QueuedConnection)
        e.tracks_changed.connect(self._on_tracks, Qt.QueuedConnection)
        e.renderers_changed.connect(self._renderers_changed, Qt.QueuedConnection)

        self.install_shortcuts()

        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(50)
        self._ui_timer.timeout.connect(self._ui_tick)
        self._ui_timer.start()
        self._time_timer = QTimer(self)
        self._time_timer.setInterval(250)
        self._time_timer.timeout.connect(self._time_tick)
        self._time_timer.start()

        saved = [x for x in store.data.get("queue", []) if isinstance(x, dict) and x.get("path")]
        if saved:
            self.queue = saved
            self.library.refresh_queue()

        self.show_home()

    # ================================================================ startup
    def showEvent(self, e):
        super().showEvent(e)
        if not getattr(self, "_shown_once", False):
            self._shown_once = True
            self._dark_titlebar()
            self.engine.set_window(int(self.video.canvas.winId()))
            if self.can_integrate_desktop() and self.store.setting("desktop_entry") not in (None, "", os.environ.get("APPIMAGE")):
                self.install_desktop_entry(quiet=True)   # the AppImage was moved or updated
            if not self.engine.ok:
                QTimer.singleShot(200, self._vlc_missing)
            elif not self.store.setting("onboarded"):
                QTimer.singleShot(300, self._welcome)
            if not os.environ.get("PYLON_NO_UPDATE_CHECK"):
                QTimer.singleShot(8000, self._auto_update_check)


    def apply_theme(self):
        theme.set_theme(self.store.setting("theme"), self.store.setting("theme_tint"))
        theme.set_accent(self.store.setting("accent"))
        QApplication.instance().setStyleSheet(theme.stylesheet())
        widgets = self.findChildren(IconButton)
        for ov in (self.top, self.bottom):
            widgets += ov.findChildren(IconButton)
        for w in widgets:
            w.refresh()
        self.home.refresh()
        self.library.refresh_library()
        self.library.refresh_queue()
        self.bottom.update()
        self.bottom.cone.update()
        self.bottom.apply_glow()
        self.top.update()
        self.osd.update()
        if self.library.stack.currentIndex() == 4:
            self.library.refresh_music()

    # ================================================================ pages / panels
    def show_home(self):
        self.osd.hide()
        self.home.refresh()
        self.stage.setCurrentIndex(PAGE_HOME)
        self._set_bars(False)

    def close_media(self):
        """Unload what is playing and go back to the home page, keeping the queue (#61)."""
        e = self.engine
        if not e.current:
            self.show_home()
            return
        if self._pip:
            self.toggle_pip()
        if self.isFullScreen():
            self.toggle_fullscreen()
        self._save_position()
        self.thumbs.cancel()
        self.waves.cancel()
        self.bottom.seek.set_wave([])
        self.ab_loop = [None, None]
        self._show_ab()
        self.bottom.resume.hide()
        e.close()
        self.top.set_title("")
        self.top.set_folder("")
        self.bottom.set_playing(False)
        self.bottom.set_time(0, 0)
        self.setWindowTitle(APP_NAME)
        self.library.refresh_queue()
        self.library.refresh_library()
        self.show_home()

    def show_player(self):
        if not self.engine.current:
            return
        self.stage.setCurrentIndex(PAGE_VIDEO if self.engine.has_video() or not is_audio(self.engine.current) else PAGE_AUDIO)
        self._poke()

    # ---------------------------------------------------------------- interactive zoom (#39)
    def _picture_rect(self):
        """Where the (cropped) picture sits inside the video surface, letterboxed."""
        e = self.engine
        vw, vh = e.video_size()
        sw, sh = self.video.width(), self.video.height()
        if e.izoom:
            vw, vh = e.izoom["w"], e.izoom["h"]
        if not vw or not vh or not sw or not sh:
            return None
        k = min(sw / vw, sh / vh)
        w, h = vw * k, vh * k
        return QRectF((sw - w) / 2, (sh - h) / 2, w, h)

    def zoom_video(self, factor, pos=None):
        e = self.engine
        if not e.current or not e.video_size()[0]:
            return
        r = self._picture_rect()
        fx = fy = 0.5
        if pos is not None and r is not None:
            fx, fy = (pos.x() - r.x()) / r.width(), (pos.y() - r.y()) / r.height()
        z = e.zoom_at(factor, fx, fy)
        self.video.set_zoomed(z > 1.0)
        self.sidebar.zoom.select(None if z > 1.0 else e.live["zoom"])
        self.toast(f"Zoom: {round(z * 100)}%" if z > 1.0 else "Zoom: off")

    def reset_zoom(self):
        if self.engine.izoom:
            self.engine.reset_zoom()
            self.toast("Zoom: off")
        self.video.set_zoomed(False)
        self.sidebar.zoom.select(self.engine.live["zoom"])

    def _zoom_wheel(self, delta, pos):
        if delta:
            self.zoom_video(1.25 ** (delta / 120), pos)

    def _pan_video(self, d):
        r = self._picture_rect()
        if r is not None and r.width() and r.height():
            self.engine.pan_by(d.x() / r.width(), d.y() / r.height())

    def browse_folder(self, folder):
        if not folder:
            self.toggle_library(True)
            return
        self.toggle_library(True)
        self.library.open_folder(folder)

    def current_folder(self):
        cur = self.engine.current
        if cur and not is_url(cur):
            return os.path.dirname(cur)
        return None

    # ================================================================ overlays
    def _poke(self, seconds: float = 0):
        self._last_move = time.monotonic()
        if seconds:
            self._force_show_until = time.monotonic() + seconds

    def _set_bars(self, visible: bool):
        if visible == self._bars_visible:
            return
        self._bars_visible = visible
        self._overlay_fixes = 0          # each show may be moved again (#40)
        self._overlay_checks = 0         # and checked again against where the window manager put it (#81)
        if not visible:
            self.seek_preview.hide()
        for w in (self.top, self.bottom):
            if visible:
                w.show()
                w.raise_()
            else:
                w.hide()

    def _overlay_mode_changed(self):
        """The floating windows switched to bypassing the window manager (#81): rebuild them."""
        for w in (self.top, self.bottom, self.osd, self.seek_preview):
            w.follow_mode()
        self._bars_visible = None        # shown again on the next tick
        self._overlay_geo = None

    def _check_overlay_placement(self, tl: QPoint, h: int):
        """Floating bars must be where Pylon put them. Some window managers place such windows
        themselves and ignore later moves (COSMIC on Wayland, #81). Ask the X server where the bars
        really are, a couple of times after they're shown, and stop asking the window manager if it
        moved them."""
        if (not self._bars_visible or self.top.docked or overlay.bypass()
                or getattr(self, "_overlay_checks", 0) >= 3):
            return
        self._overlay_checks = getattr(self, "_overlay_checks", 0) + 1
        dpr = self.devicePixelRatioF() or 1.0
        want = {self.top: tl, self.bottom: QPoint(tl.x(), tl.y() + h - BottomBar.HEIGHT)}
        for bar, p in want.items():
            real = overlay.real_position(bar)
            if real is None:
                return
            if abs(real[0] / dpr - p.x()) > 2 or abs(real[1] / dpr - p.y()) > 2:
                if self._overlay_checks >= 2 and overlay.switch_to_bypass("the window manager moved the bars"):
                    self._overlay_mode_changed()
                return

    def _place_overlays(self, drift: QPoint = QPoint()):
        left, right = self._panel_cover()        # panels floating over the video (#42)
        tl = self.stage.mapToGlobal(QPoint(left, 0)) + drift
        w, h = max(1, self.stage.width() - left - right), self.stage.height()
        self.top.folder_chip.setVisible(w >= 480 and bool(self.top.folder_chip.text()))
        self.top.btn_pip.setVisible(w >= 260)
        self.top.title.setVisible(w >= 340)
        for button in (self.bottom.btn_prev, self.bottom.btn_next, self.bottom.time):
            button.setVisible(w >= 360)
        for button in (self.bottom.btn_subs, self.bottom.btn_audio, self.bottom.btn_mute, self.bottom.cone):
            button.setVisible(w >= 620)
        self.bottom.resume.setVisible(w >= 900 and time.monotonic() < self._resume_until)
        self.bottom.speed.setVisible(w >= 760 and abs(self.engine.live["rate"] - 1.0) > 1e-3)
        for bar in (self.top, self.bottom):
            bar.layout().activate()
            bar.setMinimumWidth(0 if bar.docked else bar.layout().minimumSize().width())
        self.osd.anchor = QPoint(tl.x() + 20, tl.y() + TopBar.HEIGHT + 10)
        if self.top.docked:              # pinned: the layout places the bars (#81)
            self._overlay_geo = None
            return
        self._check_overlay_placement(tl, h)
        geo = (tl.x(), tl.y(), w, h)
        if geo == self._overlay_geo and not self._bars_moved(tl, h):
            return
        if geo != self._overlay_geo:
            self._overlay_fixes = 0
        self._overlay_geo = geo
        self.top.setGeometry(QRect(tl.x(), tl.y(), w, TopBar.HEIGHT))
        self.bottom.setGeometry(QRect(tl.x(), tl.y() + h - BottomBar.HEIGHT, w, BottomBar.HEIGHT))
        # Layout minimum sizes can make a tool window wider than the stage.
        # Clip the actual native windows as well as setting their geometry.
        self.top.setMask(QRegion(0, 0, w, TopBar.HEIGHT))
        self.bottom.setMask(QRegion(0, 0, w, BottomBar.HEIGHT))
        if self.osd.isVisible():
            self.osd.move(self.osd.anchor)

    def _bars_moved(self, tl: QPoint, h: int) -> bool:
        """True when the system moved a visible bar away from where we put it.

        macOS keeps a window out of the menu bar strip when it is shown, even in full
        screen, which left a gap above the top bar (#40). Put it back, but give up after
        a few tries so a system that insists doesn't cost a move on every tick."""
        if not self._bars_visible or self.top.docked or getattr(self, "_overlay_fixes", 0) >= 5:
            return False
        moved = (self.top.pos() != tl or
                 self.bottom.pos() != QPoint(tl.x(), tl.y() + h - BottomBar.HEIGHT))
        if moved:
            self._overlay_fixes = getattr(self, "_overlay_fixes", 0) + 1
        return moved

    def _pinned(self) -> bool:
        """Controls stay put (and opaque) in a normal window when the user asked for it."""
        return (bool(self.store.setting("pin_controls")) and not self.isFullScreen() and not self._pip
                and self.stage.currentIndex() != PAGE_HOME)

    def _apply_pin(self):
        pinned = self._pinned()
        if pinned != getattr(self, "_pin_state", None):
            self._pin_state = pinned
            # Pinned bars are laid out above and below the video as ordinary parts of the window, so the
            # video sits between them (#68) and no window manager can put them anywhere else (#81).
            # Shrinking the video emits VideoSurface.resized, which redraws a Super Resolution picture
            # at the new size (#42).
            if pinned:
                self.top.dock(self.middle)
                self.bottom.dock(self.middle)
                self.middle_lay.insertWidget(0, self.top)
                self.middle_lay.addWidget(self.bottom)
            else:
                for bar in (self.top, self.bottom):
                    self.middle_lay.removeWidget(bar)
                    bar.undock()
            for bar in (self.top, self.bottom):
                bar.solid = pinned
                bar.update()
            self._bars_visible = None        # shown or hidden again by this tick
            self._overlay_geo = None

    def _ui_tick(self):
        page = self.stage.currentIndex()
        self._apply_pin()
        self._check_ab()                 # Repeat a part keeps going while minimized or hidden (#73)
        if page == PAGE_HOME or self.isMinimized() or not self.isVisible():
            self.video.unsetCursor()
            self._set_bars(False)
            if self.osd.isVisible() and (self.isMinimized() or not self.isVisible()):
                self.osd.hide()
            return
        now = time.monotonic()
        drift = self.video.x11_drift()
        if drift.manhattanLength() > 2:     # the window is being dragged and Qt hasn't been told (#59)
            self._moving_until = now + WINDOW_MOVE_HIDE_S
            self._overlay_geo = None
        else:
            drift = QPoint()
        self._place_overlays(drift)
        pos = QCursor.pos()
        if pos != self._last_mouse:
            self._last_mouse = pos
            self._last_move = now
        stage_rect = QRect(self.stage.mapToGlobal(QPoint(0, 0)), self.stage.size())
        inside = stage_rect.contains(pos)
        active = QApplication.activeWindow() is self or QApplication.activePopupWidget() is not None \
            or self.top.isActiveWindow() or self.bottom.isActiveWindow()
        delay = int(self.store.setting("hide_delay_ms")) / 1000
        near_bar = inside and (pos.y() - stage_rect.top() < TopBar.HEIGHT + 24
                               or stage_rect.bottom() - pos.y() < BottomBar.HEIGHT + 24)
        show = False
        if not self.hide_ui:
            if self._pinned():
                show = True
            elif QApplication.activePopupWidget() is not None:
                show = True
            elif now < self._force_show_until:
                show = True
            elif page == PAGE_AUDIO:
                show = True
            elif inside and active and (now - self._last_move < delay or near_bar):
                show = True
        if show and not self._pinned() and now < getattr(self, "_moving_until", 0):
            show = False                 # the window is being dragged (#59)
        if show and not self._pinned() and overlay.bypass() and not self._app_active():
            show = False                 # bars that bypass the window manager would float over other apps (#81)
        self._set_bars(show)
        if overlay.bypass() and not self._app_active():
            self.osd.hide()
            self.seek_preview.hide()
        self._update_video_cursor(page, inside, show)

    def _app_active(self) -> bool:
        return QGuiApplication.applicationState() == Qt.ApplicationActive

    def _update_video_cursor(self, page, inside, show):
        # hide the pointer over the video in fullscreen when bars are gone
        if (self.isFullScreen() and page == PAGE_VIDEO and inside and not show
                and QApplication.activeWindow() is self
                and QApplication.activeModalWidget() is None
                and QApplication.activePopupWidget() is None):
            self.video.setCursor(Qt.BlankCursor)
        else:
            self.video.unsetCursor()

    def moveEvent(self, e):
        super().moveEvent(e)
        self._overlay_geo = None
        if not hasattr(self, "_bars_visible") or not self.isVisible():
            return
        # The bars are separate windows that the 50 ms tick puts back over the video, so while the
        # window is dragged they trail behind it, more so when VLC keeps Pylon busy reading from a
        # network share (#59). Pinned bars are moved straight away; floating bars hide until the
        # window stops moving.
        if self._pinned():
            self._place_overlays()
        elif not self.windowState() & (Qt.WindowFullScreen | Qt.WindowMaximized | Qt.WindowMinimized):
            self._moving_until = time.monotonic() + WINDOW_MOVE_HIDE_S
            self._set_bars(False)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._overlay_geo = None
        self._place_floating_panels()

    def changeEvent(self, e):
        super().changeEvent(e)
        self._overlay_geo = None
        if e.type() == e.Type.WindowStateChange:
            self.top.set_fullscreen(self.isFullScreen())
            self._sync_panel_mode()

    def toast(self, text: str, key: str = ""):
        if self.stage.currentIndex() == PAGE_HOME or self.isMinimized():
            return
        self._place_overlays()
        self.osd.show_message(text, key)

    # ================================================================ shortcuts / actions
    def install_shortcuts(self):
        self.top.label_keys(self.store)
        self.bottom.label_keys(self.store)
        for sc in getattr(self, "_shortcuts", []):
            sc.setEnabled(False)
            sc.deleteLater()
        self._shortcuts = []
        for action in DEFAULT_SHORTCUTS:
            seq = self.store.shortcut(action)
            if not seq:
                continue
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.WindowShortcut)
            sc.setAutoRepeat(action in ("seek_fwd", "seek_back", "vol_up", "vol_down", "frame_next", "frame_prev",
                                        "sub_delay_plus", "sub_delay_minus", "audio_delay_plus",
                                        "audio_delay_minus", "speed_up", "speed_down"))
            sc.activated.connect(lambda a=action: self.do(a))
            self._shortcuts.append(sc)
            if seq == "Return":  # the keypad Enter key too
                sc2 = QShortcut(QKeySequence("Enter"), self)
                sc2.setContext(Qt.WindowShortcut)
                sc2.setAutoRepeat(False)
                sc2.activated.connect(lambda a=action: self.do(a))
                self._shortcuts.append(sc2)

    def _cycle_chip(self, chips, live_key, setter, what):
        """Step to the next choice in the settings panel's row for this (aspect ratio or crop, #56)."""
        values = chips.values
        cur = self.engine.live.get(live_key, "")
        i = (values.index(cur) + 1) % len(values) if cur in values else 1 % len(values)
        setter(values[i])
        chips.select(values[i])
        return f"{what}: {chips.group.button(i).text()}"

    # keys that move around a disc menu instead of seeking and changing the volume
    MENU_KEYS = {"seek_back": NAV_LEFT, "seek_fwd": NAV_RIGHT, "vol_up": NAV_UP, "vol_down": NAV_DOWN,
                 "play_pause": NAV_ACTIVATE, "fullscreen_enter": NAV_ACTIVATE}

    def do(self, action: str, key: bool = True):
        e = self.engine
        msg = None
        if action in self.MENU_KEYS and e.in_menu() and not self._typing(action):
            e.navigate(self.MENU_KEYS[action])
            self._poke(1)
            return
        if action == "play_pause":
            if not e.current:
                if self.queue:
                    self.play_queue_index(max(0, self.qindex))
                else:
                    self.open_file_dialog()
                return
            playing = e.is_playing()
            e.toggle()
            msg = "Paused" if playing else "Playing"
            self._poke(1.5)
        elif action == "stop":
            self._save_position()
            e.stop()
            msg = "Stopped"
        elif action == "close_media":
            self.close_media()
            return
        elif action in ("seek_fwd", "seek_back", "seek_fwd_long", "seek_back_long"):
            delta = {"seek_fwd": 10_000, "seek_back": -10_000, "seek_fwd_long": 60_000, "seek_back_long": -60_000}[action]
            e.seek_by(delta)
            msg = f"{'+' if delta > 0 else '-'}{abs(delta) // 1000}s   {fmt_time(max(0, e.time() + delta))}"
            self.bottom.set_time(max(0, e.time() + delta), e.length())
        elif action == "frame_next":
            e.next_frame()
            msg = "Next frame"
        elif action == "frame_prev":
            if not e.current:
                return
            if e.is_disc():
                # DVDs can only jump to about every half second, so a frame back isn't possible there
                msg = "Stepping back a frame doesn't work on DVDs"
            else:
                e.prev_frame()
                self.bottom.set_playing(False)
                msg = "Previous frame"
        elif action == "ab_loop":
            msg = self.ab_step()
        elif action in ("vol_up", "vol_down"):
            v = e.volume() + (5 if action == "vol_up" else -5)
            e.set_volume(v)
            e.set_muted(False)
            self.bottom.set_volume(e.volume(), False)
            msg = f"Volume {e.volume()}%"
        elif action == "mute":
            m = not e.is_muted()
            e.set_muted(m)
            self.bottom.set_volume(e.volume(), m)
            msg = "Muted" if m else f"Volume {e.volume()}%"
        elif action == "next":
            self.play_next(user=True)
            return
        elif action == "prev":
            self.play_prev()
            return
        elif action == "fullscreen":
            self.toggle_fullscreen()
            return
        elif action == "fullscreen_enter":
            # Enter still works normally while typing or picking from a list
            fw = QApplication.focusWidget()
            if isinstance(fw, QLineEdit):
                fw.returnPressed.emit()
                return
            if isinstance(fw, QAbstractItemView) and fw.currentIndex().isValid():
                item_fn = getattr(fw, "itemDoubleClicked", None)
                if item_fn is not None and hasattr(fw, "currentItem") and fw.currentItem() is not None:
                    item_fn.emit(fw.currentItem())
                    return
            if self.stage.currentIndex() == PAGE_HOME:
                return
            self.toggle_fullscreen()
            return
        elif action == "exit_fullscreen":
            self._drop_slider_focus()          # Esc gives the arrow keys back to the video too (#79)
            if self._pip:
                self.toggle_pip()
            elif self.isFullScreen():
                self.toggle_fullscreen()
            elif self.hide_ui:
                self.do("hide_ui")
            return
        elif action == "pip":
            self.toggle_pip()
            return
        elif action == "hide_ui":
            self.hide_ui = not self.hide_ui
            if self.hide_ui:
                self._set_bars(False)
                self.toggle_library(False)
                self.toggle_sidebar(False)
            msg = "Interface hidden" if self.hide_ui else "Interface shown"
        elif action in ("speed_up", "speed_down", "speed_reset"):
            steps = SPEED_STEPS
            r = e.rate()
            if action == "speed_reset":
                r = 1.0
            elif action == "speed_up":
                r = next((s for s in steps if s > r + 1e-6), steps[-1])
            else:
                r = next((s for s in reversed(steps) if s < r - 1e-6), steps[0])
            self.set_rate(r, osd=False)
            msg = f"Speed {r:g}x"
        elif action in ("sub_delay_plus", "sub_delay_minus"):
            d = e.live["sub_delay"] + (50 if action == "sub_delay_plus" else -50)
            e.set_sub_delay(d)
            self.sidebar.set_sub_delay_ui(d)
            msg = f"Subtitle delay {fmt_delay(d)}"
        elif action in ("audio_delay_plus", "audio_delay_minus"):
            d = e.live["audio_delay"] + (50 if action == "audio_delay_plus" else -50)
            e.set_audio_delay(d)
            self.sidebar.audio_delay.set_value(d)
            msg = f"Audio delay {fmt_delay(d)}"
        elif action == "cycle_sub":
            msg = self._cycle(e.sub_tracks(), e.current_sub(), e.set_sub, "Subtitles")
        elif action == "cycle_audio":
            msg = self._cycle(e.audio_tracks(), e.current_audio(), e.set_audio, "Audio")
        elif action in ("cycle_aspect", "cycle_crop"):
            if not e.current:
                return
            msg = self._cycle_chip(*((self.sidebar.aspect, "aspect", e.set_aspect, "Aspect ratio")
                                     if action == "cycle_aspect" else
                                     (self.sidebar.crop, "crop", e.set_crop, "Crop")))
        elif action == "bookmark":
            if not e.current:
                return
            items = list(self.store.bookmarks(e.current))
            t = e.time()
            items.append({"t": t, "name": f"Bookmark {len(items) + 1}"})
            self.store.set_bookmarks(e.current, items)
            self.sidebar.refresh_bookmarks()
            msg = f"Bookmark added at {fmt_time(t)}"
        elif action == "library":
            self.toggle_library()
            return
        elif action == "sidebar":
            self.toggle_sidebar()
            return
        elif action == "queue":
            self.toggle_queue()
            return
        elif action == "panels":
            self.toggle_panels()
            return
        elif action in ("zoom_in", "zoom_out", "zoom_reset"):
            if action == "zoom_reset":
                self.reset_zoom()
            else:
                self.zoom_video(1.25 if action == "zoom_in" else 0.8)
            return
        elif action == "open_file":
            self.open_file_dialog()
            return
        elif action == "open_folder":
            self.open_folder_dialog()
            return
        elif action == "open_stream":
            self.open_stream_dialog()
            return
        elif action == "snapshot":
            folder = os.path.join(os.path.expanduser("~"), "Pictures", "Pylon")
            os.makedirs(folder, exist_ok=True)
            msg = "Snapshot saved to Pictures\\Pylon" if e.snapshot(folder) else "Couldn't take a snapshot"
        elif action == "shortcuts":
            self.show_shortcuts()
            return
        elif action == "preferences":
            self.show_preferences()
            return
        if msg:
            hint = self.store.shortcut(action) if key and self.store.setting("osd_shortcuts") else ""
            self.toast(msg, hint)

    def _drop_slider_focus(self) -> bool:
        """A settings slider that was clicked keeps Left and Right (#79). Let go of them."""
        from .sidebar import KeySlider
        fw = QApplication.focusWidget()
        if isinstance(fw, KeySlider):
            fw.clearFocus()
            self.setFocus(Qt.OtherFocusReason)
            return True
        return False

    def _typing(self, action) -> bool:
        """The key belongs to a text box, or Enter to a list item, that has the focus."""
        fw = QApplication.focusWidget()
        if isinstance(fw, QLineEdit) and fw.isVisible():
            return True
        return (action == "fullscreen_enter" and isinstance(fw, QAbstractItemView) and fw.isVisible()
                and fw.currentIndex().isValid())

    # ---------------------------------------------------------------- A–B repeat
    def ab_step(self) -> str | None:
        """L: the first press marks the start, the second the end, the third switches the loop off."""
        a, b = self.ab_loop
        if not self.engine.current:
            return None
        if a is None:
            return self.set_ab_point("a")
        if b is None:
            return self.set_ab_point("b")
        return self.clear_ab()

    def set_ab_point(self, which: str, ms: int | None = None) -> str:
        e = self.engine
        t = e.time() if ms is None else int(ms)
        a, b = self.ab_loop
        if which == "a":
            a = t
            if b is not None and b <= a + 300:
                b = None
        else:
            if a is None:
                a = 0
            if t <= a + 300:
                return "The end of the part has to come after its start"
            b = t
        self.ab_loop = [a, b]
        self._show_ab()
        if b is None:
            key = self.store.shortcut("ab_loop")
            return f"Repeat from {fmt_time(a)}" + (f". Press {key} at the end of the part" if key else "")
        return f"Repeating {fmt_time(a)} – {fmt_time(b)}"

    def clear_ab(self) -> str:
        self.ab_loop = [None, None]
        self._show_ab()
        return "Repeat off"

    def _show_ab(self):
        self.bottom.seek.set_ab(*self.ab_loop)
        self.sidebar.show_ab(*self.ab_loop)

    def _check_ab(self):
        a, b = self.ab_loop
        e = self.engine
        if b is None or not e.is_playing() or time.monotonic() - self._ab_jumped < 0.6:
            return
        if e.time() >= b:
            self._ab_jumped = time.monotonic()
            e.seek(a)

    # ---------------------------------------------------------------- waveform
    def _wants_wave(self, cur) -> bool:
        mode = self.store.setting("seek_waveform")
        return mode != "off" and (mode == "all" or is_audio(cur))

    def _wants_trim(self, cur) -> bool:
        return bool(self.store.setting("trim_silence")) and is_audio(cur)

    def start_waveform(self):
        """Read the file's sound in the background, for the waveform in the seek bar and, for songs, for
        where their silence ends and starts (#86)."""
        e = self.engine
        cur = e.current
        if not cur or is_url(cur) or is_disc(cur) or not (self._wants_wave(cur) or self._wants_trim(cur)):
            self.waves.cancel()
            self.bottom.seek.set_wave([])
            return
        self.waves.start(cur)

    def _wave_ready(self, path, peaks):
        if path == self.engine.current:
            self.bottom.seek.set_wave(peaks if self._wants_wave(path) else [])

    # ---------------------------------------------------------------- trim silence (#86)
    def set_trim_silence(self, on: bool):
        self.store.set_setting("trim_silence", bool(on))
        cur = self.engine.current
        if on and cur and is_audio(cur):
            self.start_waveform()
            if self.waves.path == cur and self.waves.bounds:
                self._silence_ready(cur, *self.waves.bounds)
        elif not on:
            self._trim = None
        self.toast("Skipping silence at the start and end of songs" if on else "Songs play from start to end")

    def _silence_ready(self, path, start, end, total):
        if path != self.engine.current or not self._wants_trim(path):
            return
        # only worth it for a real gap: a short breath before the music or after it stays
        self._trim = (start if start >= 300 else 0, end if total - end >= 600 else None)
        if end - start < 1000:
            self._trim = None
        self._trim_start()

    def _trim_start(self):
        """Jump past the silence before the music, once, if playback is still in it."""
        e = self.engine
        if not self._trim or self._trim_started or not self._trim[0] or e.state() != "playing":
            return
        self._trim_started = True
        if e.time() < self._trim[0] - 100:
            e.seek(self._trim[0])

    def _trim_tick(self):
        """At the start of the silence after the music, end the song as if it had reached its end."""
        e = self.engine
        if not self._trim or self._trim_ended or self._trim[1] is None or not e.is_playing():
            return
        if self.ab_loop[1] is not None:
            return                          # a repeated part decides where playback goes
        if e.time() >= self._trim[1]:
            self._trim_ended = True
            e.finish()

    # ---------------------------------------------------------------- discs
    def _disc_tick(self):
        """Note when a disc enters or leaves its menu, and say how to use it."""
        menu = self.engine.in_menu()
        if menu != self._in_menu:
            self._in_menu = menu
            if menu:
                self.toast("Disc menu: choose with the arrow keys, Enter to play")
            self.sidebar.refresh_disc()

    def go_disc_menu(self):
        if self.engine.disc_menu():
            self.toast("Disc menu")

    def play_title(self, idx):
        self.engine.set_title(idx)
        self.sidebar.refresh_disc()

    # ---------------------------------------------------------------- casting
    def _renderers_changed(self):
        if getattr(self, "_cast_menu", None) is not None:
            self._fill_cast_menu(self._cast_menu)

    def cast_to(self, renderer):
        e = self.engine
        e.cast_to(renderer)
        self.top.set_casting(renderer["name"] if renderer else "")
        self.toast(f"Casting to {renderer['name']}" if renderer else "Playing on this computer")

    def _cycle(self, tracks, current, setter, label):
        if not tracks:
            return f"No {label.lower()} tracks"
        ids = [t for t, _ in tracks]
        i = ids.index(current) if current in ids else -1
        tid, name = tracks[(i + 1) % len(tracks)]
        setter(tid)
        return f"{label}: {name}"

    def set_rate(self, r: float, from_ui=False, osd=True):
        r = max(0.25, min(4.0, float(r)))
        self.engine.set_rate(r)
        self.bottom.set_speed(r)
        if not from_ui:
            self.sidebar.set_speed_ui(r)
        else:
            self.sidebar.speed_chips.select(int(round(r * 100)))
        if osd and not from_ui:
            self.toast(f"Speed {r:g}x")

    def _cone_volume(self, v):
        self.engine.set_volume(v)
        self.engine.set_muted(False)
        self.bottom.set_volume(v, False)

    def set_queue_mode(self, mode, announce=True):
        """What happens when an item ends (#48): stop, shuffle, play in order, or loop it."""
        if mode not in QUEUE_MODES:
            return
        was = self.queue_mode
        self.queue_mode = mode
        # Only In order puts the queue back in order. Stop and Loop leave a shuffled queue as it is
        # (#84), and Shuffle after them carries on with that order instead of mixing it again.
        if mode == "shuffle" and was != "shuffle" and not self.library.shuffled:
            self.library.shuffle_on()
        elif mode == "next":
            self.library.shuffle_off()
        self.library.show_queue_mode(mode)
        self.sidebar.queue_mode.select(mode)
        if announce:
            self.toast(QUEUE_MODES[mode][1])

    def cycle_queue_mode(self):
        order = list(QUEUE_MODES)
        self.set_queue_mode(order[(order.index(self.queue_mode) + 1) % len(order)])

    def set_sleep_timer(self, minutes):
        self._sleep_end_of_file = minutes == -1
        self._sleep_deadline = time.monotonic() + minutes * 60 if minutes and minutes > 0 else None
        if minutes == 0:
            self.sidebar.sleep_label.setText("")
            self.toast("Sleep timer off")
        elif minutes == -1:
            self.sidebar.sleep_label.setText("Pausing when this file ends")
            self.toast("Sleep at the end of this file")
        else:
            self.toast(f"Sleep in {minutes} min")

    # ================================================================ fullscreen / PiP
    def toggle_fullscreen(self):
        if self._pip:
            self.toggle_pip()
        if self.isFullScreen():
            if getattr(self, "_was_max", False):
                self.showMaximized()
            else:
                self.showNormal()
        else:
            self._was_max = self.isMaximized()
            self.showFullScreen()
        self.top.set_fullscreen(self.isFullScreen())
        self._overlay_geo = None

    def toggle_pip(self):
        if self._pip is None:
            if self.isFullScreen():
                self.showNormal()
            self._pip = {"geo": self.saveGeometry(), "lib": self.lib_slot.is_open,
                         "side": self.side_slot.is_open, "max": self.isMaximized(),
                         "flags": self.windowFlags()}
            self.lib_slot.set_open(False, False)
            self.side_slot.set_open(False, False)
            if self.isMaximized():
                self.showNormal()
            scr = (self.screen() or QGuiApplication.primaryScreen()).availableGeometry()
            w = 480
            h = 270
            self._set_frameless(True)          # borderless: drag to move, edges to resize (#42)
            self.setMinimumSize(320, 180)
            self.resize(w, h)
            self.move(scr.right() - w - 24, scr.bottom() - h - 56)
            self._topmost(True)
            self.video.pip = True
            self.top.btn_pip.setChecked(True)
            self.toast("Picture in picture   Esc to return")
        else:
            st = self._pip
            self._pip = None
            self.video.pip = False
            self.video.unsetCursor()
            self._set_frameless(False)
            self.setMinimumSize(640, 400)
            self._topmost(False)
            self._restore_frame(st["flags"])
            self.restoreGeometry(st["geo"])
            if st["max"]:
                self.showMaximized()
            self.lib_slot.set_open(st["lib"], False)
            self.side_slot.set_open(st["side"], False)
            self.top.btn_pip.setChecked(False)
        self._overlay_geo = None

    def _restore_frame(self, flags):
        """Give the window back exactly the frame it had before picture in picture, close button
        included (#71). On Windows the X could stay greyed out after the borderless window got its
        frame back, so Pylon also turns it on again directly, and once more after the window settles."""
        flags = Qt.WindowFlags(flags) & ~(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        flags |= Qt.WindowCloseButtonHint
        handle = self.windowHandle()
        if self.windowFlags() != flags or (handle is not None and handle.flags() != flags):
            self.overrideWindowFlags(flags)   # no rebuild: VLC keeps the window it draws into
            if handle is not None:
                handle.setFlags(flags)
        if sys.platform == "win32":
            win_enable_close(int(self.winId()))
            QTimer.singleShot(250, lambda: self._pip is None and win_enable_close(int(self.winId())))

    def _vsr_active(self) -> bool:
        e = self.engine
        return (sys.platform == "win32" and bool(self.store.setting("rtx_upscale")) and e.ok and not e.vsr_paused
                and bool(e.current) and self.stage.currentIndex() == PAGE_VIDEO and e.has_video())

    def _vsr_on(self) -> bool:
        return sys.platform == "win32" and bool(self.store.setting("rtx_upscale"))

    def _picture_fills_screen(self):
        """True if the picture, fitted to the video page, covers it to the pixel; None if not known yet."""
        e, v = self.engine, self.video
        sw, sh = v.width(), v.height()
        if sw <= 0 or sh <= 0 or not e.ok:
            return None
        if e.live["zoom"]:
            return False                 # a fixed zoom such as 1x: VLC sizes the picture itself
        shape = e.picture_shape()
        if shape is None:
            return None
        k = float(shape["aspect"])
        w, h = (round(sh * k), sh) if sw / sh > k else (sw, round(sw / k))
        return abs(w - sw) <= 2 and abs(h - sh) <= 2

    def _vsr_policy(self):
        """RTX Super Resolution shows a picture only while VLC's video covers the whole screen (#42: in full
        screen, a panel, a 4:3 aspect or a crop that leaves bars all go black, even with no bars inside
        VLC's own area). Panels float over the video for that reason. When the picture itself can't cover
        the screen, Super Resolution is set aside so the picture shows with normal scaling, and it comes
        back in full screen once the picture covers the screen again. Windowed playback is left as it is:
        Super Resolution doesn't engage there and the picture shows."""
        e = self.engine
        if not self._vsr_on() or not e.ok or not e.current or self.stage.currentIndex() != PAGE_VIDEO \
                or not e.has_video() or not self.isFullScreen() or self._pip:
            return
        fills = self._picture_fills_screen()
        if fills is None:
            return
        if e.set_vsr_paused(not fills):
            self.toast("Super Resolution is back" if fills else
                       "Super Resolution paused: it only works when the picture fills the screen")

    def _fit_video(self):
        """With Super Resolution on, size VLC's video area to the picture, centred, with Pylon's own black
        bars around it (#42). VLC goes black as soon as it has to letterbox an upscaled picture, even by
        one pixel: in full screen with a panel open, in a maximized window, or with an aspect ratio
        that doesn't match the screen. The engine then picks an aspect ratio that fills the area to the
        pixel. Without Super Resolution, VLC's area fills the page as before."""
        if not hasattr(self, "video"):
            return
        v, e = self.video, self.engine
        shape = e.picture_shape() if self._vsr_active() else None
        sw, sh = v.width(), v.height()
        if shape is None or sw <= 0 or sh <= 0:
            v.fit_canvas(None)
            e.set_fit(None)
            return
        k = float(shape["aspect"])
        if sw / sh > k:
            w, h = max(1, min(sw, round(sh * k))), sh
        else:
            w, h = sw, max(1, min(sh, round(sw / k)))
        v.fit_canvas(QRect((sw - w) // 2, (sh - h) // 2, w, h))
        e.set_fit(v.canvas.device_size())

    def _wake_picture(self):
        """Make VLC lay out its picture again without anything visible changing (#82). Some Windows drivers
        show subtitles over a black picture for hardware-decoded 10-bit HEVC until VLC's video area changes
        size, which is why opening a panel brought the picture back. Shrink the area by two pixels and put it
        straight back. With Super Resolution on, the area must never letterbox, so redraw that way instead."""
        e, v = self.engine, self.video
        if not e.ok or not e.current or self.stage.currentIndex() != PAGE_VIDEO or self.isMinimized():
            return
        if self._vsr_active():
            e.refresh_upscaler()
            return
        g = v.canvas.geometry()
        if g.width() < 8 or g.height() < 8:
            return
        v.canvas.setGeometry(g.adjusted(0, 0, 0, -2))
        QTimer.singleShot(150, lambda: v.fit_canvas(v.fit_rect))   # VLC checks its area each frame

    def _vsr_resized(self):
        if hasattr(self, "_vsr_late") and self._vsr_active():
            self._vsr_timer.start()
            if self.isFullScreen():
                for t in self._vsr_late:
                    t.start()

    def _vsr_refresh(self):
        if self._vsr_active() and not self.isMinimized():
            self.engine.refresh_upscaler()

    def _set_flag(self, flag, on: bool):
        """Change a window flag. On Linux, QWidget.setWindowFlag() rebuilds the X11 window when the
        stay-on-top flag changes, and VLC loses the video window it draws into, so the picture stays
        black until Pylon restarts (#60). The window itself can take the new flags without that."""
        handle = self.windowHandle()
        if sys.platform in ("win32", "darwin") or handle is None:
            self.setWindowFlag(flag, on)
            self.show()
            self.engine.set_window(int(self.video.canvas.winId()))
            return
        flags = (self.windowFlags() | flag) if on else (self.windowFlags() & ~flag)
        self.overrideWindowFlags(flags)       # keep Qt's record in step without rebuilding the window
        handle.setFlags(flags)

    def _set_frameless(self, on: bool):
        if bool(self.windowFlags() & Qt.FramelessWindowHint) == on:
            return
        self._set_flag(Qt.FramelessWindowHint, on)

    def pip_edges(self, gpos: QPoint):
        """Which window edges are under the pointer in borderless picture in picture."""
        if not self._pip:
            return Qt.Edges()
        r, m = self.frameGeometry(), 8
        edges = Qt.Edges()
        if gpos.x() - r.left() < m:
            edges |= Qt.LeftEdge
        elif r.right() - gpos.x() < m:
            edges |= Qt.RightEdge
        if gpos.y() - r.top() < m:
            edges |= Qt.TopEdge
        elif r.bottom() - gpos.y() < m:
            edges |= Qt.BottomEdge
        return edges

    @staticmethod
    def edge_cursor(edges):
        if edges in (Qt.LeftEdge | Qt.TopEdge, Qt.RightEdge | Qt.BottomEdge):
            return Qt.SizeFDiagCursor
        if edges in (Qt.RightEdge | Qt.TopEdge, Qt.LeftEdge | Qt.BottomEdge):
            return Qt.SizeBDiagCursor
        if edges & (Qt.LeftEdge | Qt.RightEdge):
            return Qt.SizeHorCursor
        if edges & (Qt.TopEdge | Qt.BottomEdge):
            return Qt.SizeVerCursor
        return None

    def pip_grab(self, gpos: QPoint, move: bool = True) -> bool:
        """Start resizing from an edge, or moving the window. Returns True if started."""
        handle = self.windowHandle()
        if not self._pip or handle is None:
            return False
        edges = self.pip_edges(gpos)
        if edges:
            return bool(handle.startSystemResize(edges))
        return bool(move and handle.startSystemMove())

    def eventFilter(self, obj, e):
        # In borderless picture in picture the bars' empty areas move the window,
        # and their outer edges resize it.
        if self._pip and obj in (self.top, self.bottom):
            t = e.type()
            if t == QEvent.MouseButtonPress and e.button() == Qt.LeftButton:
                if self.pip_grab(e.globalPosition().toPoint()):
                    return True
            elif t == QEvent.MouseMove and not e.buttons():
                cur = self.edge_cursor(self.pip_edges(e.globalPosition().toPoint()))
                if cur is not None:
                    obj.setCursor(cur)
                else:
                    obj.unsetCursor()
        return super().eventFilter(obj, e)

    def _topmost(self, on: bool):
        """Keep picture in picture above other apps (#66). On Windows Pylon used to set this only through
        the Windows API, so Qt still thought the window was an ordinary one, and the API call could quietly
        fail. Now Qt is told too, without rebuilding the window (VLC keeps the window it draws into), and
        the API call has proper argument types and is checked."""
        if sys.platform == "win32":
            handle = self.windowHandle()
            if handle is not None:
                flags = (self.windowFlags() | Qt.WindowStaysOnTopHint) if on else \
                    (self.windowFlags() & ~Qt.WindowStaysOnTopHint)
                self.overrideWindowFlags(flags)
                handle.setFlags(flags)
            if win_set_topmost(int(self.winId()), on) or handle is not None:
                return
        if bool(self.windowFlags() & Qt.WindowStaysOnTopHint) != on:
            self._set_flag(Qt.WindowStaysOnTopHint, on)

    def _pip_app_state(self, state):
        """Switching to another app must not push picture in picture behind it (#66): say so again.
        It also ends a drag on the seek bar, which Windows never tells us ended (#72)."""
        if state != Qt.ApplicationActive:
            self.bottom.seek.end_drag()
        if self._pip and state != Qt.ApplicationActive and sys.platform == "win32":
            win_set_topmost(int(self.winId()), True)

    # ================================================================ closing
    def closeEvent(self, e):
        self.thumbs.cancel()
        self.waves.cancel()
        self._save_position()
        self.store.data["queue"] = [{k: v for k, v in q.items() if k in ("path", "title")} for q in self.queue][:500]
        self.engine.shutdown()
        self.store.save_now()
        for w in (self.top, self.bottom, self.osd):
            w.close()
        self.video.unsetCursor()
        super().closeEvent(e)
