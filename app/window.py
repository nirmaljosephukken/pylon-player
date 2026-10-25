"""Main window: stage (home / video / now playing) between the library on the
left and the settings sidebar on the right, with floating top and bottom
bars that appear when you move the mouse and vanish when you move away."""
import os
import sys
import time

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QCursor, QGuiApplication, QKeySequence, QShortcut, QRegion
from PySide6.QtWidgets import QApplication, QHBoxLayout, QMainWindow, QStackedWidget, QWidget

from . import APP_NAME, theme
from .controls import BottomBar, TopBar
from .engine import NAV_ACTIVATE, NAV_DOWN, NAV_LEFT, NAV_RIGHT, NAV_UP, Engine
from .home import HomePage, NowPlayingPage
from .library import LibraryPanel
from .sidebar import SettingsSidebar
from .store import DEFAULT_SHORTCUTS, QUEUE_MODES
from .util import fmt_delay, fmt_time, is_audio, is_disc, is_url
from .stage import PAGE_AUDIO, PAGE_HOME, PAGE_VIDEO, VideoSurface  # noqa: F401  (tests import these from here)
from .thumbs import ThumbnailMaker
from .updates import UpdateChecker
from .waveform import WaveformMaker
from .widgets import IconButton, SeekPreview, Toast
from .window_menus import MenusMixin
from .window_playback import PlaybackMixin
from .window_system import SystemMixin

VSR_FULLSCREEN_RETRIES_MS = (600, 1500)    # extra Super Resolution redraws in full screen (#42)
WINDOW_MOVE_HIDE_S = 0.25                   # floating bars stay hidden this long after the window moves (#59)

class MainWindow(SystemMixin, MenusMixin, PlaybackMixin, QMainWindow):
    def __init__(self, store):
        super().__init__()
        self.store = store
        theme.set_accent(store.setting("accent"))
        self.setWindowTitle(APP_NAME)
        self.resize(1200, 740)
        self.setMinimumSize(640, 400)
        self.setAcceptDrops(True)

        self.engine = Engine(store, self)
        st = store.setting("sub_style")
        if isinstance(st, dict):
            self.engine.sub_style.update(st)
            if self.engine.ok:
                self.engine.recreate()

        self.queue: list[dict] = []
        self.qindex = -1
        self.queue_mode = self.store.setting("queue_mode") if self.store.setting("queue_mode") in QUEUE_MODES else "next"
        self.hide_ui = False
        self._pip = None
        self._vsr_back_to_full = False     # a panel took full screen into a window (#42)
        self._vsr_told = False
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
        self.updater = UpdateChecker(self.store, self)
        self.updater.found.connect(self._update_found)
        self.updater.none.connect(self._update_none)
        self.updater.failed.connect(self._update_failed)
        self._update_release = None      # a newer release we know about
        self._manual_update_check = False

        self.library = LibraryPanel(self)
        self.library.hide()
        self.home = HomePage(self)
        self.stage.addWidget(self.home)
        self.stage.addWidget(self.video)
        self.stage.addWidget(self.now_playing)
        self.sidebar = SettingsSidebar(self)
        self.sidebar.hide()
        self.library.show_queue_mode(self.queue_mode)

        lay.addWidget(self.library)
        lay.addWidget(self.stage, 1)
        lay.addWidget(self.sidebar)

        # ---------------- wiring
        self.video.action.connect(lambda action: self.do(action, key=False))
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
        self.video.resized.connect(self._vsr_resized)
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
            self.engine.set_window(int(self.video.winId()))
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
        self.library.refresh_music() if self.library.stack.currentIndex() == 4 else None

    # ================================================================ pages / panels
    def show_home(self):
        self.osd.hide()
        self.home.refresh()
        self.stage.setCurrentIndex(PAGE_HOME)
        self._set_bars(False)

    def show_player(self):
        if not self.engine.current:
            return
        self.stage.setCurrentIndex(PAGE_VIDEO if self.engine.has_video() or not is_audio(self.engine.current) else PAGE_AUDIO)
        self._poke()

    def toggle_library(self, on=None):
        on = (not self.library.isVisible()) if on is None else on
        if self._pip and on:
            return
        if on:
            self._vsr_panel_opening()
        self.library.setVisible(on)
        if not on:
            self._vsr_panel_closed()
        self._update_panel_minimum()
        self._vsr_resized()           # the picture may not resize if the panel only covers it
        self.top.btn_library.setChecked(on)
        if on:
            self.library.refresh_library()
            self.library.refresh_queue()

    def toggle_queue(self, on=None):
        on = (not self.library.isVisible()) if on is None else on
        self.toggle_library(on)
        self.bottom.btn_queue.setChecked(on)

    def toggle_sidebar(self, on=None):
        on = (not self.sidebar.isVisible()) if on is None else on
        if self._pip and on:
            return
        if on:
            self._vsr_panel_opening()
        self.sidebar.setVisible(on)
        if not on:
            self._vsr_panel_closed()
        self._update_panel_minimum()
        self._vsr_resized()
        self.bottom.btn_tune.setChecked(on)
        if on:
            self.sidebar.refresh_tracks()

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

    def toggle_panels(self):
        """Library and settings together (#34): hide both if either is open, else show both."""
        on = self.library.isHidden() and self.sidebar.isHidden()
        if self._pip and on:
            return
        self.toggle_library(on)
        if not on:
            self.bottom.btn_queue.setChecked(False)
        self.toggle_sidebar(on)

    def open_sidebar_tab(self, idx):
        self.toggle_sidebar(True)
        self.sidebar.tabs.setCurrentIndex(idx)

    def _update_panel_minimum(self):
        """Keep both side panels and the compact player inside the window."""
        panel_width = (0 if self.library.isHidden() else self.library.WIDTH)
        panel_width += (0 if self.sidebar.isHidden() else self.sidebar.WIDTH)
        self.setMinimumWidth(max(640, panel_width + self.stage.minimumWidth()))
        self._overlay_geo = None

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
        if not visible:
            self.seek_preview.hide()
        for w in (self.top, self.bottom):
            if visible:
                w.show()
                w.raise_()
            else:
                w.hide()

    def _place_overlays(self, drift: QPoint = QPoint()):
        tl = self.stage.mapToGlobal(QPoint(0, 0)) + drift
        w, h = self.stage.width(), self.stage.height()
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
            bar.setMinimumWidth(bar.layout().minimumSize().width())
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
        self.osd.anchor = QPoint(tl.x() + 20, tl.y() + TopBar.HEIGHT + 10)
        if self.osd.isVisible():
            self.osd.move(self.osd.anchor)

    def _bars_moved(self, tl: QPoint, h: int) -> bool:
        """True when the system moved a visible bar away from where we put it.

        macOS keeps a window out of the menu bar strip when it is shown, even in full
        screen, which left a gap above the top bar (#40). Put it back, but give up after
        a few tries so a system that insists doesn't cost a move on every tick."""
        if not self._bars_visible or getattr(self, "_overlay_fixes", 0) >= 5:
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
            m = (0, TopBar.HEIGHT, 0, BottomBar.HEIGHT) if pinned else (0, 0, 0, 0)
            self.stage.layout().setContentsMargins(*m)    # the video sits between the bars
            for bar in (self.top, self.bottom):
                bar.solid = pinned
                bar.update()
            self._overlay_geo = None

    def _ui_tick(self):
        page = self.stage.currentIndex()
        self._apply_pin()
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
        self._check_ab()
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
        self._set_bars(show)
        self._update_video_cursor(page, inside, show)

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

    def changeEvent(self, e):
        super().changeEvent(e)
        self._overlay_geo = None
        if e.type() == e.Type.WindowStateChange:
            self.top.set_fullscreen(self.isFullScreen() or getattr(self, "_vsr_back_to_full", False))

    def toast(self, text: str, key: str = ""):
        if self.stage.currentIndex() == PAGE_HOME or self.isMinimized():
            return
        self._place_overlays()
        self.osd.show_message(text, key)

    # ================================================================ shortcuts / actions
    def install_shortcuts(self):
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
            from PySide6.QtWidgets import QAbstractItemView, QLineEdit
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
            if self._pip:
                self.toggle_pip()
            elif self.isFullScreen() or self._vsr_back_to_full:
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
            steps = [0.25, 0.5, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 4.0]
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

    def _typing(self, action) -> bool:
        """The key belongs to a text box, or Enter to a list item, that has the focus."""
        from PySide6.QtWidgets import QAbstractItemView, QLineEdit
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
    def start_waveform(self):
        e = self.engine
        mode = self.store.setting("seek_waveform")
        cur = e.current
        if (not cur or is_url(cur) or is_disc(cur) or mode == "off"
                or (mode != "all" and not is_audio(cur))):
            self.waves.cancel()
            self.bottom.seek.set_wave([])
            return
        self.waves.start(cur)

    def _wave_ready(self, path, peaks):
        if path == self.engine.current:
            self.bottom.seek.set_wave(peaks)

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
        if mode == "shuffle" and was != "shuffle":
            self.library.shuffle_on()
        elif was == "shuffle" and mode != "shuffle":
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
        if self._vsr_back_to_full:          # a panel took us out of full screen (#42): stay out
            self._vsr_back_to_full = False
            if not getattr(self, "_was_max", False):
                self.showNormal()
        elif self.isFullScreen():
            self.showMaximized() if getattr(self, "_was_max", False) else self.showNormal()
        else:
            self._was_max = self.isMaximized()
            if self._vsr_on() and not (self.library.isHidden() and self.sidebar.isHidden()):
                self.library.hide()          # a panel over full screen turns Super Resolution black
                self.sidebar.hide()
                self.top.btn_library.setChecked(False)
                self.bottom.btn_queue.setChecked(False)
                self.bottom.btn_tune.setChecked(False)
                self._update_panel_minimum()
            self.showFullScreen()
        self.top.set_fullscreen(self.isFullScreen())
        self._overlay_geo = None

    def toggle_pip(self):
        if self._pip is None:
            if self.isFullScreen():
                self.showNormal()
            self._pip = {"geo": self.saveGeometry(), "lib": self.library.isVisible(),
                         "side": self.sidebar.isVisible(), "max": self.isMaximized()}
            self.library.hide()
            self.sidebar.hide()
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
            self.restoreGeometry(st["geo"])
            if st["max"]:
                self.showMaximized()
            self.library.setVisible(st["lib"])
            self.sidebar.setVisible(st["side"])
            self.top.btn_pip.setChecked(False)
        self._overlay_geo = None

    def _vsr_active(self) -> bool:
        e = self.engine
        return (sys.platform == "win32" and bool(self.store.setting("rtx_upscale")) and e.ok
                and bool(e.current) and self.stage.currentIndex() == PAGE_VIDEO and e.has_video())

    def _vsr_on(self) -> bool:
        return sys.platform == "win32" and bool(self.store.setting("rtx_upscale"))

    def _vsr_panel_opening(self):
        """Opening a panel in full screen turns the Super Resolution picture black until the panel closes,
        whatever Pylon does to redraw it (#42), while panels work fine in a window. So with Super
        Resolution on, a panel opened in full screen opens in a maximized window instead, and closing
        the last panel goes back to full screen."""
        if not (self.isFullScreen() and self._vsr_on()) or self._pip:
            return
        self._vsr_back_to_full = True
        self.showMaximized()
        if not self._vsr_told:
            self._vsr_told = True
            QTimer.singleShot(300, lambda: self.toast("With Super Resolution on, panels open in a window. "
                                                      "Close the panel to go back to full screen"))

    def _vsr_panel_closed(self):
        if self._vsr_back_to_full and self.library.isHidden() and self.sidebar.isHidden():
            self._vsr_back_to_full = False
            self.showFullScreen()
            self.top.set_fullscreen(True)

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
            self.engine.set_window(int(self.video.winId()))
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
                obj.setCursor(cur) if cur is not None else obj.unsetCursor()
        return super().eventFilter(obj, e)

    def _topmost(self, on: bool):
        if sys.platform == "win32":
            try:
                import ctypes
                HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
                flags = 0x0001 | 0x0002 | 0x0010  # NOSIZE | NOMOVE | NOACTIVATE
                ctypes.windll.user32.SetWindowPos(int(self.winId()), HWND_TOPMOST if on else HWND_NOTOPMOST,
                                                  0, 0, 0, 0, flags)
                return
            except Exception:
                pass
        if bool(self.windowFlags() & Qt.WindowStaysOnTopHint) != on:
            self._set_flag(Qt.WindowStaysOnTopHint, on)


    # ================================================================ closing
    def closeEvent(self, e):
        self.thumbs.cancel()
        self.waves.cancel()
        self.waves.cancel()
        self._save_position()
        self.store.data["queue"] = [{k: v for k, v in q.items() if k in ("path", "title")} for q in self.queue][:500]
        self.engine.shutdown()
        self.store.save_now()
        for w in (self.top, self.bottom, self.osd):
            w.close()
        self.video.unsetCursor()
        super().closeEvent(e)
