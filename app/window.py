"""Main window: stage (home / video / now playing) between the library on the
left and the settings sidebar on the right, with floating top and bottom
bars that appear when you move the mouse and vanish when you move away."""
import os
import sys
import time

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QActionGroup, QCursor, QGuiApplication, QKeySequence, QShortcut, QRegion
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QMainWindow, QMenu,
                               QMessageBox, QStackedWidget, QWidget)

from . import APP_NAME, theme
from .controls import BottomBar, TopBar
from .dialogs import (PreferencesDialog, ShortcutsDialog, StreamDialog, SubtitleDialog,
                      WelcomeDialog)
from . import engine as engine_mod
from .engine import MAX_SHARPEN, Engine
from .home import HomePage, NowPlayingPage
from .icons import icon
from .library import LibraryPanel, media_filter
from .sidebar import SettingsSidebar
from .store import DEFAULT_SHORTCUTS
from .util import (SUB_EXTS, PLAYLIST_EXTS, display_name, norm, find_subtitle_candidates, fmt_delay,
                   fmt_time, is_audio, is_media, is_url, list_media, match_subtitle, natural_key,
                   parse_m3u, to_path)
from .thumbs import ThumbnailMaker
from .updates import UpdateChecker
from .widgets import IconButton, SeekPreview, Toast

PAGE_HOME, PAGE_VIDEO, PAGE_AUDIO = 0, 1, 2


class VideoSurface(QFrame):
    """Native window that VLC draws into. Mouse input is turned off in VLC so
    clicks and the wheel reach this widget."""
    action = Signal(str)
    context = Signal(QPoint)
    wheel = Signal(int)
    zoom_wheel = Signal(int, QPointF)    # Ctrl+scroll: delta, position (#39)
    pan = Signal(QPointF)               # drag while zoomed: movement in pixels

    def __init__(self, store):
        super().__init__()
        self.store = store
        self._double_release = False
        self._pending_action = "none"
        self.zoomed = False                 # set by the window; dragging pans only when zoomed
        self._drag_from = None
        self._panned = False
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setAttribute(Qt.WA_DontCreateNativeAncestors, True)
        self.setStyleSheet("background: #000;")
        self.setMouseTracking(True)
        self._click = QTimer(self)
        self._click.setSingleShot(True)
        self._click.setInterval(QApplication.doubleClickInterval() if QApplication.instance() else 250)
        self._click.timeout.connect(lambda: self._emit_action(self._pending_action))

    def _emit_action(self, action):
        if (QApplication.activeModalWidget() is None and QApplication.activePopupWidget() is None
                and action in ("play_pause", "fullscreen", "mute", "next", "prev", "seek_back", "seek_fwd")):
            self.action.emit(action)

    def cancel_click(self):
        self._click.stop()
        self._double_release = False

    def hideEvent(self, e):
        self.cancel_click()
        super().hideEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.zoomed:
            self._drag_from = e.position()
            self._panned = False
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag_from is not None and e.buttons() & Qt.LeftButton:
            d = e.position() - self._drag_from
            if self._panned or abs(d.x()) + abs(d.y()) > 4:
                if not self._panned:
                    self._panned = True
                    self.cancel_click()
                    self.setCursor(Qt.ClosedHandCursor)
                self._drag_from = e.position()
                self.pan.emit(d)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._drag_from is not None:
            self._drag_from = None
            if self._panned:                 # a drag is not a click
                self._panned = False
                self.setCursor(Qt.OpenHandCursor if self.zoomed else Qt.ArrowCursor)
                return
        if e.button() == Qt.LeftButton:
            if self._double_release:
                self._double_release = False
                return
            action = self.store.setting("mouse_single")
            if self.store.setting("mouse_double") == "none":
                self._emit_action(action)
            else:
                # Preserve the system's double-click interval; shortening it can
                # execute a single-click action before a valid double-click.
                self._pending_action = action
                self._click.start(QApplication.doubleClickInterval())
        else:
            key = {Qt.MiddleButton: "mouse_middle", Qt.BackButton: "mouse_back",
                   Qt.ForwardButton: "mouse_forward"}.get(e.button())
            if key:
                self._emit_action(self.store.setting(key))

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._click.stop()
            if self.store.setting("mouse_double") == "none":
                # Qt still reports a double-click event when no action is bound.
                self._emit_action(self.store.setting("mouse_single"))
            else:
                self._emit_action(self.store.setting("mouse_double"))
            # Fullscreen can hide/recreate the native surface while dispatching.
            self._double_release = True

    def contextMenuEvent(self, e):
        self.context.emit(e.globalPos())

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            self.zoom_wheel.emit(e.angleDelta().y(), e.position())
            return
        self.wheel.emit(e.angleDelta().y())

    def set_zoomed(self, on: bool):
        self.zoomed = on
        if not self._panned:
            self.setCursor(Qt.OpenHandCursor if on else Qt.ArrowCursor)


class MainWindow(QMainWindow):
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
        self.repeat = "off"
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

        # ---------------- layout
        central = QWidget()
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.setCentralWidget(central)

        self.stage = QStackedWidget()
        self.stage.setMinimumWidth(240)
        self.home = None  # created after library (home uses it)
        self.video = VideoSurface(store)
        self.now_playing = NowPlayingPage(self)

        # overlays (separate translucent windows over the video)
        self.top = TopBar(self)
        self.bottom = BottomBar(self)
        self.osd = Toast(self)
        self.seek_preview = SeekPreview(self)
        self.thumbs = ThumbnailMaker(self)
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

        lay.addWidget(self.library)
        lay.addWidget(self.stage, 1)
        lay.addWidget(self.sidebar)

        # ---------------- wiring
        self.video.action.connect(lambda action: self.do(action, key=False))
        self.video.context.connect(self.show_context_menu)
        self.video.wheel.connect(lambda d: self.do("vol_up" if d > 0 else "vol_down", key=False))
        self.video.zoom_wheel.connect(self._zoom_wheel)
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

    # ================================================================ updates
    def _auto_update_check(self):
        if self.updater.due():
            self._manual_update_check = False
            self.updater.check(manual=False)

    def check_for_updates(self, manual=True):
        self._manual_update_check = manual
        if manual:
            self.toast("Checking for updates…")
        self.updater.check(manual=manual)

    def _update_found(self, release):
        self._update_release = release
        tag = (release.get("tag_name") or "").lstrip("vV")
        if self._manual_update_check or not (self.engine.current and self.engine.is_playing()):
            self.show_update(release)
        else:   # don't interrupt a video; the menu offers it
            self.toast(f"Pylon {tag} is out. Open the menu to update.")

    def _update_none(self):
        if self._manual_update_check:
            from . import APP_VERSION
            QMessageBox.information(self, "No updates", f"You have the latest version of Pylon ({APP_VERSION}).")

    def _update_failed(self, why):
        if self._manual_update_check:
            QMessageBox.warning(self, "Couldn't check for updates",
                                f"Pylon couldn't reach GitHub to check for a new version.\n\n{why}")

    def show_update(self, release=None):
        from .dialogs import UpdateDialog
        release = release or self._update_release
        if release:
            UpdateDialog(self, release).exec()

    def quit_for_update(self):
        """Close Pylon so the installer can replace its files."""
        self._save_position()
        self.store.save_now()
        self.close()
        QApplication.instance().quit()

    def _vlc_missing(self):
        if sys.platform == "win32":
            how = "Install VLC 3.0 (64-bit) from videolan.org, then start Pylon again."
            url = "https://www.videolan.org/vlc/download-windows.html"
        elif sys.platform == "darwin":
            how = "Install VLC from videolan.org (drag it into Applications), then start Pylon again."
            url = "https://www.videolan.org/vlc/download-macosx.html"
        else:
            how = ("Install VLC's engine from your package manager, then start Pylon again:\n"
                   "  Ubuntu / Debian / Mint:  sudo apt install vlc\n"
                   "  Fedora:  sudo dnf install vlc  (from RPM Fusion)\n"
                   "  Arch:  sudo pacman -S vlc\n\n"
                   "The Flatpak and Snap versions of VLC can't be used by other apps.")
            url = "https://www.videolan.org/vlc/#download"
        box = QMessageBox(QMessageBox.Critical, "VLC not found",
                          "Pylon uses the VLC engine to play media, but it couldn't be found.\n\n"
                          f"{how}\n\nDetails: {engine_mod.VLC_ERROR}", parent=self)
        get = box.addButton("Get VLC", QMessageBox.AcceptRole)
        locate = box.addButton("Locate VLC folder…", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Close)
        box.exec()
        if box.clickedButton() is get:
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl(url))
        elif box.clickedButton() is locate:
            self.locate_vlc()

    # ---------------------------------------------------------------- Linux desktop integration
    def can_integrate_desktop(self) -> bool:
        return sys.platform.startswith("linux") and bool(os.environ.get("APPIMAGE"))

    def install_desktop_entry(self, quiet=False):
        """Add the AppImage to the app menu and 'Open with' (per user, no root)."""
        from .util import AUDIO_EXTS, VIDEO_EXTS
        appimage = os.environ.get("APPIMAGE")
        if not appimage:
            return
        home = os.path.expanduser("~")
        data = os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
        apps = os.path.join(data, "applications")
        icons = os.path.join(data, "icons", "hicolor", "256x256", "apps")
        os.makedirs(apps, exist_ok=True)
        os.makedirs(icons, exist_ok=True)
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        png = os.path.join(here, "pylon.png")
        if os.path.isfile(png):
            import shutil
            shutil.copyfile(png, os.path.join(icons, "pylon.png"))
        mimes = sorted({"video/mp4", "video/x-matroska", "video/webm", "video/x-msvideo", "video/quicktime",
                        "video/x-flv", "video/mpeg", "video/mp2t", "video/x-ms-wmv", "video/3gpp", "video/ogg",
                        "audio/mpeg", "audio/flac", "audio/x-wav", "audio/mp4", "audio/aac", "audio/ogg",
                        "audio/x-ms-wma", "audio/x-matroska", "audio/opus", "audio/x-mpegurl", "application/vnd.apple.mpegurl"})
        entry = ("[Desktop Entry]\nType=Application\nName=Pylon\nGenericName=Media Player\n"
                 "Comment=Calmer interface for the VLC engine\n"
                 f"Exec=\"{appimage}\" %F\nIcon=pylon\nTerminal=false\nCategories=AudioVideo;Player;Video;Audio;\n"
                 f"MimeType={';'.join(mimes)};\nStartupWMClass=Pylon\n")
        with open(os.path.join(apps, "pylon.desktop"), "w", encoding="utf-8") as f:
            f.write(entry)
        for cmd in (["update-desktop-database", apps], ["gtk-update-icon-cache", "-q", os.path.join(data, "icons", "hicolor")]):
            try:
                import subprocess
                subprocess.run(cmd, timeout=10, capture_output=True)
            except Exception:
                pass
        self.store.set_setting("desktop_entry", appimage)
        if not quiet:
            QMessageBox.information(self, "Added to your apps",
                                    "Pylon is now in your applications menu and under \"Open with\" for videos and music.\n\n"
                                    "If you move the Pylon file, choose this again.")

    def locate_vlc(self):
        """Let the user point Pylon at a VLC folder (portable VLC, unusual install place)."""
        if sys.platform == "darwin":
            folder, _ = QFileDialog.getOpenFileName(self, "Choose VLC.app", "/Applications", "Applications (*.app)")
            folder = folder or QFileDialog.getExistingDirectory(self, "Choose VLC.app", "/Applications")
            lib = os.path.join(folder, "Contents", "MacOS", "lib", "libvlc.dylib")
        else:
            folder = QFileDialog.getExistingDirectory(self, "Choose the folder that contains VLC")
            lib = os.path.join(folder, "libvlc.dll" if sys.platform == "win32" else "libvlc.so.5")
        if not folder:
            return
        if not os.path.isfile(lib) and sys.platform != "linux":
            QMessageBox.warning(self, "That's not VLC",
                                f"{folder}\ndoesn't contain VLC's engine ({os.path.basename(lib)}). "
                                "Pick the folder VLC is installed in" + (" (it has vlc.exe in it)." if sys.platform == "win32" else "."))
            return
        self.store.set_setting("vlc_dir", folder)
        self.store.save_now()
        if not self.engine.ok:
            if self.engine.start_engine(folder):   # no restart needed
                QMessageBox.information(self, "VLC found", f"Pylon will use the VLC in\n{folder}")
                if not self.store.setting("onboarded"):
                    QTimer.singleShot(300, self._welcome)
            else:
                QMessageBox.warning(self, "VLC couldn't start",
                                    f"Pylon found VLC in\n{folder}\nbut couldn't start it.\n\n"
                                    f"Details: {engine_mod.VLC_ERROR}")
            return
        self.ask_restart("Pylon will use this VLC after it restarts.")

    def ask_restart(self, why: str):
        box = QMessageBox(QMessageBox.Information, "Restart Pylon", why, parent=self)
        now = box.addButton("Restart now", QMessageBox.AcceptRole)
        box.addButton("Later", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is now:
            self.restart_app()

    def restart_app(self):
        """Start a fresh Pylon and close this one (keeps the current file and position)."""
        from PySide6.QtCore import QProcess
        from PySide6.QtNetwork import QLocalServer
        from PySide6.QtWidgets import QApplication
        self._save_position()
        self.store.save_now()
        app = QApplication.instance()
        for srv in app.findChildren(QLocalServer):   # let the new Pylon be the only one
            srv.close()
        appimage = os.environ.get("APPIMAGE")
        if appimage:
            prog, args = appimage, []
        else:
            main_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
            prog, args = sys.executable, [main_py]
        if self.engine.current:
            args.append(self.engine.current)
        if QProcess.startDetached(prog, args):
            app.quit()
        else:
            QMessageBox.warning(self, "Restart Pylon", "Couldn't restart Pylon. Please close it and open it again.")

    def _welcome(self):
        if self.can_integrate_desktop():
            self.install_desktop_entry(quiet=True)
        d = WelcomeDialog(self)
        if d.exec():
            if d.color != theme.user_accent():
                self.store.set_setting("accent", d.color)
                self.apply_theme()
        self.store.set_setting("onboarded", True)

    def _dark_titlebar(self):
        if sys.platform != "win32":
            return
        try:
            import ctypes
            hwnd = int(self.winId())
            val = ctypes.c_int(1)
            for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new / old builds)
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val)) == 0:
                    break
        except Exception:
            pass

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
        self.library.setVisible(on)
        self._update_panel_minimum()
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
        self.sidebar.setVisible(on)
        self._update_panel_minimum()
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
        if not visible:
            self.seek_preview.hide()
        for w in (self.top, self.bottom):
            if visible:
                w.show()
                w.raise_()
            else:
                w.hide()

    def _place_overlays(self):
        tl = self.stage.mapToGlobal(QPoint(0, 0))
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
        if geo == self._overlay_geo:
            return
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
        self._place_overlays()
        now = time.monotonic()
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

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._overlay_geo = None

    def changeEvent(self, e):
        super().changeEvent(e)
        self._overlay_geo = None
        if e.type() == e.Type.WindowStateChange:
            self.top.set_fullscreen(self.isFullScreen())

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
            sc.setAutoRepeat(action in ("seek_fwd", "seek_back", "vol_up", "vol_down", "frame_next",
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

    def do(self, action: str, key: bool = True):
        e = self.engine
        msg = None
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
        elif action in ("vol_up", "vol_down"):
            v = e.volume() + (5 if action == "vol_up" else -5)
            e.set_volume(v)
            e.set_muted(False)
            self.bottom.set_volume(e.volume(), False)
            msg = f"Volume {max(0, min(125, v))}%"
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
        if msg:
            hint = self.store.shortcut(action) if key and self.store.setting("osd_shortcuts") else ""
            self.toast(msg, hint)

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

    def set_repeat(self, mode):
        self.repeat = mode
        self.toast({"off": "Repeat off", "all": "Repeat the queue", "one": "Repeat this file"}[mode])

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
            self.showMaximized() if getattr(self, "_was_max", False) else self.showNormal()
        else:
            self._was_max = self.isMaximized()
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
            self.resize(w, h)
            self.move(scr.right() - w - 24, scr.bottom() - h - 56)
            self._topmost(True)
            self.top.btn_pip.setChecked(True)
            self.toast("Picture in picture   Esc to return")
        else:
            st = self._pip
            self._pip = None
            self._topmost(False)
            self.restoreGeometry(st["geo"])
            if st["max"]:
                self.showMaximized()
            self.library.setVisible(st["lib"])
            self.sidebar.setVisible(st["side"])
            self.top.btn_pip.setChecked(False)
        self._overlay_geo = None

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
        self.setWindowFlag(Qt.WindowStaysOnTopHint, on)
        self.show()
        self.engine.set_window(int(self.video.winId()))

    # ================================================================ menus
    def _popup_above(self, menu: QMenu, btn):
        menu.adjustSize()
        g = btn.mapToGlobal(QPoint(0, 0))
        menu.exec(QPoint(g.x(), g.y() - menu.sizeHint().height() - 4))

    def _track_actions(self, menu, tracks, current, setter):
        grp = QActionGroup(menu)
        for tid, name in tracks:
            a = menu.addAction(name or f"Track {tid}")
            a.setCheckable(True)
            a.setChecked(tid == current)
            grp.addAction(a)
            a.triggered.connect(lambda _=False, t=tid: setter(t))
        if not tracks:
            a = menu.addAction("None available")
            a.setEnabled(False)

    def build_subs_menu(self, parent=None) -> QMenu:
        m = QMenu("Subtitles", parent or self)
        m.setIcon(icon("subtitles", theme.TEXT, 16))
        m.addSection("Subtitle track")
        self._track_actions(m, self.engine.sub_tracks(), self.engine.current_sub(), self.engine.set_sub)
        m.addSeparator()
        m.addAction(icon("plus", theme.TEXT, 16), "Add subtitles…", lambda: self.open_subtitle_dialog())
        m.addAction(icon("tune", theme.TEXT, 16), "Timing and look…", lambda: self.open_sidebar_tab(0))
        return m

    def build_audio_menu(self, parent=None) -> QMenu:
        m = QMenu("Audio", parent or self)
        m.setIcon(icon("audio", theme.TEXT, 16))
        m.addSection("Audio track")
        self._track_actions(m, self.engine.audio_tracks(), self.engine.current_audio(), self.engine.set_audio)
        m.addSection("Play through")
        devs = self.engine.audio_devices()
        cur = self.engine.current_device()
        self._track_actions(m, [(d, desc or d or "Default") for d, desc in devs] or [("", "Default output")],
                            cur, self.engine.set_device)
        m.addSeparator()
        m.addAction(icon("tune", theme.TEXT, 16), "Audio settings…", lambda: self.open_sidebar_tab(1))
        return m

    def show_subs_menu(self):
        self._poke(30)
        self._popup_above(self.build_subs_menu(), self.bottom.btn_subs)
        self._poke(1)

    def show_audio_menu(self):
        self._poke(30)
        self._popup_above(self.build_audio_menu(), self.bottom.btn_audio)
        self._poke(1)

    def _open_menu(self, parent) -> QMenu:
        m = QMenu("Open", parent)
        m.setIcon(icon("folder", theme.TEXT, 16))
        m.addAction(icon("file", theme.TEXT, 16), "File…\tCtrl+O", self.open_file_dialog)
        m.addAction(icon("folder", theme.TEXT, 16), "Folder…\tCtrl+F", self.open_folder_dialog)
        m.addAction(icon("stream", theme.TEXT, 16), "Network stream…\tCtrl+N", self.open_stream_dialog)
        m.addAction(icon("globe", theme.TEXT, 16), "Link from clipboard", self.open_clipboard)
        rec = m.addMenu(icon("clock", theme.TEXT, 16), "Recent")
        for r in self.store.data["recent"][:15]:
            rec.addAction(display_name(r["path"]), lambda p=r["path"]: self.play_from_folder(p))
        if not self.store.data["recent"]:
            rec.addAction("Nothing yet").setEnabled(False)
        return m

    def show_main_menu(self, anchor):
        self._poke(30)
        m = QMenu(self)
        m.addMenu(self._open_menu(m))
        m.addSeparator()
        m.addAction(icon("home", theme.TEXT, 16), "Home", self.show_home)
        m.addAction(icon("library", theme.TEXT, 16), "Library\tCtrl+L", lambda: self.toggle_library(True))
        if self.engine.current:
            m.addSeparator()
            m.addAction(icon("subtitles", theme.TEXT, 16), "Add subtitles…", lambda: self.open_subtitle_dialog())
            m.addAction(icon("bookmark_add", theme.TEXT, 16), "Add bookmark\tCtrl+B", lambda: self.do("bookmark", key=False))
            m.addAction(icon("snapshot", theme.TEXT, 16), "Take a snapshot", lambda: self.do("snapshot", key=False))
        m.addSeparator()
        m.addAction(icon("settings", theme.TEXT, 16), "Preferences…", self.show_preferences)
        if self.can_integrate_desktop():
            m.addAction(icon("plus", theme.TEXT, 16), "Add Pylon to the applications menu", self.install_desktop_entry)
        m.addAction(icon("keyboard", theme.TEXT, 16), "Keyboard shortcuts\tF1", self.show_shortcuts)
        if self._update_release:
            tag = (self._update_release.get("tag_name") or "").lstrip("vV")
            m.addAction(icon("arrow_up", theme.accent(), 16), f"Update to Pylon {tag}…", lambda: self.show_update())
        else:
            m.addAction(icon("arrow_up", theme.TEXT, 16), "Check for updates…", lambda: self.check_for_updates(True))
        m.addAction(icon("info", theme.TEXT, 16), "About", self.show_about)
        m.addSeparator()
        m.addAction("Quit", self.close)
        g = anchor.mapToGlobal(QPoint(anchor.width(), anchor.height()))
        m.exec(QPoint(g.x() - m.sizeHint().width(), g.y() + 4))
        self._poke(1)

    def show_context_menu(self, gpos):
        self._poke(30)
        e = self.engine
        m = QMenu(self)
        if e.current:
            m.addAction(icon("pause" if e.is_playing() else "play", theme.TEXT, 16),
                        ("Pause" if e.is_playing() else "Play") + "\tSpace", lambda: self.do("play_pause", key=False))
            m.addAction(icon("stop", theme.TEXT, 16), "Stop", lambda: self.do("stop", key=False))
            m.addSeparator()
            m.addMenu(self.build_subs_menu(m))
            m.addMenu(self.build_audio_menu(m))
            vm = m.addMenu(icon("video", theme.TEXT, 16), "Video")
            vm.addSection("Video track")
            self._track_actions(vm, e.video_tracks(), e.current_video(), e.set_video)
            vm.addSection("Aspect ratio")
            grp = QActionGroup(vm)
            for label, v in (("Auto", ""), ("16:9", "16:9"), ("4:3", "4:3"), ("21:9", "21:9"), ("1:1", "1:1")):
                a = vm.addAction(label)
                a.setCheckable(True)
                a.setChecked(e.live["aspect"] == v)
                grp.addAction(a)
                a.triggered.connect(lambda _=False, v=v: (e.set_aspect(v), self.sidebar.aspect.select(v)))
            vm.addSeparator()
            vm.addAction("Video settings…", lambda: self.open_sidebar_tab(2))
            sm = m.addMenu(icon("speed", theme.TEXT, 16), "Speed")
            grp2 = QActionGroup(sm)
            for r in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0):
                a = sm.addAction(f"{r:g}x")
                a.setCheckable(True)
                a.setChecked(abs(e.rate() - r) < 1e-3)
                grp2.addAction(a)
                a.triggered.connect(lambda _=False, r=r: self.set_rate(r))
            m.addSeparator()
            m.addAction(icon("bookmark_add", theme.TEXT, 16), "Add bookmark\tCtrl+B", lambda: self.do("bookmark", key=False))
            m.addAction(icon("snapshot", theme.TEXT, 16), "Take a snapshot", lambda: self.do("snapshot", key=False))
            m.addSeparator()
        m.addAction(icon("sidebar_left", theme.TEXT, 16), "Library and queue\tCtrl+L", lambda: self.toggle_library())
        m.addAction(icon("sidebar_right", theme.TEXT, 16), "Settings sidebar\tCtrl+T", lambda: self.toggle_sidebar())
        m.addAction(icon("eye_off", theme.TEXT, 16),
                    ("Show the interface" if self.hide_ui else "Hide the interface") + "\tH", lambda: self.do("hide_ui", key=False))
        m.addAction(icon("exit_fullscreen" if self.isFullScreen() else "fullscreen", theme.TEXT, 16),
                    ("Leave fullscreen" if self.isFullScreen() else "Fullscreen") + "\tF", self.toggle_fullscreen)
        m.addAction(icon("pip", theme.TEXT, 16), "Picture in picture\tCtrl+P", self.toggle_pip)
        m.addSeparator()
        m.addMenu(self._open_menu(m))
        m.addAction(icon("settings", theme.TEXT, 16), "Preferences…", self.show_preferences)
        m.exec(gpos)
        self._poke(1)

    def show_preferences(self):
        PreferencesDialog(self).exec()

    def show_shortcuts(self):
        ShortcutsDialog(self).exec()

    def show_about(self):
        from . import APP_VERSION
        QMessageBox.about(self, "About Pylon",
                          f"<b>Pylon {APP_VERSION}</b><br>A redesigned interface on top of the VLC engine "
                          "(libVLC). Playback, codecs and streaming are all VLC.<br><br>"
                          "Interface based on the VLC redesign concept by "
                          "<a href='https://www.youtube.com/@juxtopposed'>Juxtopposed</a>.<br><br>"
                          "MIT licence &copy; 2026 Nirmal Joseph Ukken.<br>"
                          "VLC is a trademark of VideoLAN. Pylon isn't affiliated with VideoLAN.")

    # ================================================================ opening
    def open_file_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Open", "", media_filter())
        if not files:
            return
        if len(files) == 1 and os.path.splitext(files[0])[1].lower() in PLAYLIST_EXTS:
            self.open_playlist_file(files[0])
        elif len(files) == 1:
            self.play_from_folder(files[0])
        else:
            files.sort(key=lambda p: natural_key(os.path.basename(p)))
            self.set_queue([{"path": f} for f in files], 0)

    def open_folder_dialog(self):
        d = QFileDialog.getExistingDirectory(self, "Open folder")
        if d:
            self.play_folder(os.path.normpath(d))

    def open_stream_dialog(self):
        d = StreamDialog(self)
        if d.exec() and d.url.text().strip():
            url = d.url.text().strip()
            name = d.name.text().strip() or display_name(url)
            if d.save.isChecked() and url not in [s["url"] for s in self.store.data["streams"]]:
                self.store.data["streams"].insert(0, {"name": name, "url": url})
                self.store.save("streams")
                self.library.refresh_streams()
            self.open_stream(url, name)

    def open_clipboard(self):
        text = QGuiApplication.clipboard().text().strip().strip('"')
        if not text:
            self.toast("Clipboard is empty")
        elif os.path.exists(text):
            self.play_folder(text) if os.path.isdir(text) else self.play_from_folder(text)
        elif "://" in text:
            self.open_stream(text)
        else:
            QMessageBox.information(self, "Clipboard", "The clipboard doesn't contain a link or a file path.")

    def open_stream(self, url: str, name: str = ""):
        low = url.lower().split("?")[0]
        if low.endswith((".m3u", ".m3u8")) and url.startswith("http"):
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                import urllib.request
                req = urllib.request.Request(url, headers={"User-Agent": "Pylon/1.0"})
                with urllib.request.urlopen(req, timeout=12) as r:
                    text = r.read(8_000_000).decode("utf-8", "replace")
                channels = parse_m3u(text)
            except Exception:
                channels = None
            finally:
                QApplication.restoreOverrideCursor()
            if channels:
                self.set_queue([{"path": u, "title": n} for n, u in channels], 0)
                self.toggle_queue(True)
                self.toast(f"Loaded {len(channels)} channels into the queue")
                return
        self.set_queue([{"path": url, "title": name or display_name(url)}], 0)

    def open_playlist_file(self, path):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                items = parse_m3u(f.read()) or []
        except OSError:
            items = []
        base = os.path.dirname(path)
        q = []
        for n, p in items:
            if not is_url(p) and not os.path.isabs(p):
                p = os.path.normpath(os.path.join(base, p))
            q.append({"path": p, "title": n})
        if q:
            self.set_queue(q, 0)
        else:
            self.set_queue([{"path": path}], 0)

    def play_folder(self, folder):
        folder = norm(folder)
        files = list_media(folder)
        if not files:
            self.browse_folder(folder)
            self.toast("No media files directly in that folder")
            return
        self.set_queue([{"path": f} for f in files], 0)

    def play_playlist(self, name):
        items = self.store.data["playlists"].get(name, [])
        if not items:
            return
        # pick up where you left off: the first item you haven't finished
        start = next((i for i, p in enumerate(items)
                      if is_url(p) or not self.store.position(norm(p)).get("watched")), 0)
        self.set_queue([{"path": p} for p in items], start)
        self.toggle_queue(True)
        if start > 0:
            QTimer.singleShot(500, lambda: self.toast(f"Continuing “{name}” at item {start + 1} of {len(items)}"))

    def play_from_folder(self, path, start_ms=None):
        """Play a file and queue the rest of its folder so the next episode is ready."""
        path = norm(path)
        if is_url(path):
            self.open_stream(path)
            return
        if not os.path.exists(path):
            QMessageBox.warning(self, "File not found", f"Can't find:\n{path}")
            return
        for i, q in enumerate(self.queue):
            if os.path.normcase(q["path"]) == os.path.normcase(path):
                self.play_queue_index(i, start_ms=start_ms)
                return
        files = list_media(os.path.dirname(path)) if self.store.setting("binge") else [path]
        if path not in files:
            files = [path]
        self.queue = [{"path": f} for f in files]
        self.library.reset_shuffle()
        self.play_queue_index(files.index(path), start_ms=start_ms)

    # ---------------------------------------------------------------- queue
    def set_queue(self, items, index, keep_playing=False):
        self.queue = [{**it, "path": norm(it["path"])} for it in items]
        self.library.reset_shuffle()
        self.qindex = index if 0 <= index < len(self.queue) else -1
        self.library.refresh_queue()
        if not keep_playing and self.qindex >= 0:
            self.play_queue_index(self.qindex)

    def enqueue(self, paths, play_next=False):
        items = [{"path": norm(p)} for p in paths if p]
        if not items:
            return
        if play_next and self.qindex >= 0:
            self.queue[self.qindex + 1:self.qindex + 1] = items
        else:
            self.queue.extend(items)
        self.library.refresh_queue()
        self.toast(f"Added {len(items)} to the queue" if len(items) > 1 else f"Added “{display_name(items[0]['path'])}” to the queue")
        if not self.engine.current:
            self.play_queue_index(len(self.queue) - len(items) if not play_next else max(0, self.qindex + 1))

    def insert_into_queue(self, paths, row):
        items = [{"path": norm(p)} for p in paths if p and (is_url(p) or is_media(p) or
                                                      os.path.splitext(p)[1].lower() in PLAYLIST_EXTS)]
        if not items:
            return
        row = max(0, min(row, len(self.queue)))
        self.queue[row:row] = items
        if self.qindex >= row:
            self.qindex += len(items)
        self.library.refresh_queue()
        if not self.engine.current:
            self.play_queue_index(row)

    def reorder_queue(self, order):
        cur = self.queue[self.qindex]["path"] if 0 <= self.qindex < len(self.queue) else None
        by_path = {}
        for q in self.queue:
            by_path.setdefault(q["path"], []).append(q)
        new = []
        for p in order:
            lst = by_path.get(p)
            if lst:
                new.append(lst.pop(0))
        self.queue = new
        self.qindex = next((i for i, q in enumerate(new) if q["path"] == cur), -1)
        self.library.refresh_queue()

    def remove_from_queue(self, rows):
        cur = self.queue[self.qindex] if 0 <= self.qindex < len(self.queue) else None
        self.queue = [q for i, q in enumerate(self.queue) if i not in set(rows)]
        self.qindex = next((i for i, q in enumerate(self.queue) if q is cur), -1)
        self.library.refresh_queue()

    def play_queue_index(self, i, start_ms=None):
        if not (0 <= i < len(self.queue)):
            return
        self.qindex = i
        item = self.queue[i]
        self.play_path(item["path"], start_ms=start_ms, title=item.get("title", ""))
        self.library.refresh_queue()

    def play_next(self, user=False):
        if self.qindex + 1 < len(self.queue):
            self.play_queue_index(self.qindex + 1)
            return True
        if self.repeat == "all" and self.queue:
            self.play_queue_index(0)
            return True
        cur = self.engine.current
        if cur and not is_url(cur) and (self.store.setting("binge") or user):
            files = list_media(os.path.dirname(cur))
            try:
                idx = files.index(cur)
            except ValueError:
                idx = -1
            if 0 <= idx < len(files) - 1:
                nxt = files[idx + 1]
                self.queue.append({"path": nxt})
                self.play_queue_index(len(self.queue) - 1)
                return True
        if user:
            self.toast("End of the queue")
        return False

    def play_prev(self):
        if self.engine.time() > 3000:
            self.engine.seek(0)
            self.toast("Back to the start")
            return
        if self.qindex > 0:
            self.play_queue_index(self.qindex - 1)
            return
        cur = self.engine.current
        if cur and not is_url(cur):
            files = list_media(os.path.dirname(cur))
            if cur in files and files.index(cur) > 0:
                prev = files[files.index(cur) - 1]
                self.queue.insert(0, {"path": prev})
                self.play_queue_index(0)

    # ---------------------------------------------------------------- playing
    def play_path(self, path, start_ms=None, title=""):
        path = norm(path)
        if not self.engine.ok:
            self._vlc_missing()
            return
        self._save_position()
        e = self.engine
        self._resume_until = 0.0
        self._resume_ms = 0
        self.bottom.resume.hide()
        if self.thumbs.path != path:
            self.thumbs.cancel()

        # where to start
        if start_ms is None:
            start_ms = 0
            pos = self.store.position(path)
            ln, p = pos.get("len", 0), pos.get("pos", 0)
            if ln and 10_000 < p < ln * 0.93 and not pos.get("watched"):
                mode = self.store.setting("resume")
                if mode == "always":
                    start_ms = p
                elif mode == "ask":
                    self._resume_ms = p

        # per-show preset, or a clean slate for timing
        folder = None if is_url(path) else os.path.dirname(path)
        name, preset = self.store.preset_for_folder(folder) if folder else (None, None)
        e.live["sub_delay"] = 0
        e.live["audio_delay"] = 0
        self._track_prefs = ("", "")
        if preset:
            self.apply_preset(preset, live=False)

        # subtitles we know about
        subs = []
        if not is_url(path):
            mapped = self.store.data["sub_map"].get(path)
            if mapped and os.path.exists(mapped):
                subs.append(mapped)
            else:
                level = self.store.setting("sub_match")
                if level != "off":
                    best = match_subtitle(path, find_subtitle_candidates(path), level)
                    # VLC already loads same-name files next to the video by itself
                    if best and not (os.path.dirname(best) == os.path.dirname(path)
                                     and os.path.splitext(os.path.basename(best))[0] == os.path.splitext(os.path.basename(path))[0]):
                        subs.append(best)

        self._prefs_applied = False
        self._live_applied = False
        audio = is_audio(path)
        self.stage.setCurrentIndex(PAGE_AUDIO if audio else PAGE_VIDEO)
        self._overlay_geo = None
        e.open(path, start_ms=start_ms, subs=subs, title=title)
        self.store.add_recent(path)

        shown = title or display_name(path)
        self.top.set_title(shown)
        self.setWindowTitle(f"{shown}  ·  {APP_NAME}")
        self.top.set_folder(os.path.basename(folder) if folder else ("Stream" if is_url(path) else ""))
        self.bottom.set_time(start_ms, 0)
        if audio:
            self.now_playing.load(path, {})
        if self._resume_ms:
            self.bottom.resume.setText(f"Continue from {fmt_time(self._resume_ms)}")
            self._resume_until = time.monotonic() + 8
            self.bottom.resume.setVisible(self.stage.width() >= 900)
            self._poke(8)
            QTimer.singleShot(8000, self.bottom.resume.hide)
        else:
            self._poke(2)
        if preset:
            QTimer.singleShot(400, lambda: self.toast(f"Preset: {name}"))
        if self.library.isVisible():
            self.library.refresh_library()

    def _accept_resume(self):
        if self._resume_ms:
            self.engine.seek(self._resume_ms)
            self.toast(f"Continuing from {fmt_time(self._resume_ms)}")
        self._resume_until = 0.0
        self._resume_ms = 0
        self.bottom.resume.hide()

    def apply_preset(self, p: dict, live: bool):
        e = self.engine
        for k in ("sub_delay", "audio_delay", "rate", "eq", "aspect", "crop", "zoom", "adjust", "deinterlace"):
            if k in p:
                e.live[k] = p[k]
        if "eq_custom" in p:
            e.live["eq_custom"] = e.clean_curve(p["eq_custom"])
        style = p.get("sub_style")
        needs_new_player = bool(style) and style != e.sub_style
        if needs_new_player:
            e.sub_style = dict(style)
        # sharpen is a VLC filter, so a change needs a fresh player too
        if "sharpen" in p:
            try:
                sharpen = max(0.0, min(MAX_SHARPEN, float(p.get("sharpen") or 0)))
            except (TypeError, ValueError):
                sharpen = 0.0
            if abs(sharpen - e.sharpen) > 0.01:
                e.sharpen = sharpen
                needs_new_player = True
        self._track_prefs = (p.get("sub_track", ""), p.get("audio_track", ""))
        self.bottom.set_speed(e.live["rate"])
        self.sidebar.sync_from_engine()
        if live:
            if needs_new_player and e.current:
                e.rebuild()
            else:
                e.apply_live()
            self._apply_track_prefs()
        elif needs_new_player:
            e.recreate()

    def _apply_track_prefs(self):
        e = self.engine
        sub_name, audio_name = self._track_prefs
        sub_lang = self.store.setting("sub_lang") or ""
        audio_lang = self.store.setting("audio_lang") or ""

        def pick(tracks, exact, lang):
            real = [(t, n) for t, n in tracks if t != -1]
            if exact:
                for t, n in real:
                    if n == exact:
                        return t
            if lang:
                low = lang.lower()
                for t, n in real:
                    if low in n.lower():
                        return t
            return None

        if sub_name == "off" or (not sub_name and sub_lang.lower() == "off"):
            e.set_sub(-1)
        else:
            # an external file we added wins over language guessing
            if not (e.extra_subs and not sub_name):
                t = pick(e.sub_tracks(), sub_name, sub_lang)
                if t is not None:
                    e.set_sub(t)
        t = pick(e.audio_tracks(), audio_name, audio_lang)
        if t is not None:
            e.set_audio(t)
        self.sidebar.refresh_tracks()

    def _on_tracks(self):
        if not self._prefs_applied and self.engine.state() == "playing":
            self._prefs_applied = True
            QTimer.singleShot(350, self._apply_track_prefs)
        QTimer.singleShot(120, self._refresh_after_tracks)

    def _refresh_after_tracks(self):
        if self.sidebar.isVisible():
            self.sidebar.refresh_tracks()

    def _on_state(self, state):
        e = self.engine
        self.bottom.set_playing(state == "playing")
        if state == "playing":
            if not self._live_applied:
                self._live_applied = True
                e.apply_live()
                self.sidebar.sync_from_engine()
                QTimer.singleShot(900, self._after_start)
            if not self._prefs_applied:
                self._prefs_applied = True
                QTimer.singleShot(600, self._apply_track_prefs)
        elif state == "paused":
            self._save_position()
            self._poke(0.5)
        elif state == "ended":
            self._on_ended()
        elif state == "error":
            self.toast("Couldn't play this file")
            QTimer.singleShot(1500, lambda: self.play_next() if self.qindex + 1 < len(self.queue) else None)

    # ---------------------------------------------------------------- seek previews
    def start_previews(self, tries=0):
        e = self.engine
        if not self.store.setting("seek_previews") or not e.current or is_url(e.current):
            return
        if self.thumbs.path == e.current:
            return
        if e.length() <= 0 and tries < 5:      # length not known yet
            QTimer.singleShot(1000, lambda: self.start_previews(tries + 1))
            return
        self.thumbs.start(e.current, e.length(), e.video_size())

    def _seek_hover(self, ms, x):
        seek = self.bottom.seek
        g = seek.mapToGlobal(QPoint(int(x), 0))
        img = None
        if self.store.setting("seek_previews") and self.thumbs.path == self.engine.current:
            img, captured_ms = self.thumbs.preview_at(ms)
            if captured_ms is not None:
                ms = captured_ms
        left = self.mapToGlobal(QPoint(0, 0)).x()
        line_top = g.y() + seek.height() - 10     # the visible bar sits at the bottom of the widget
        self.seek_preview.show_at(g.x(), line_top - 5, ms, img, left + 8, left + self.width() - 8)

    def _after_start(self):
        e = self.engine
        if e.current and self.stage.currentIndex() != PAGE_HOME:
            has_video = e.has_video()
            if not has_video:
                self.now_playing.load(e.current, e.meta())
                self.stage.setCurrentIndex(PAGE_AUDIO)
            elif self.stage.currentIndex() == PAGE_AUDIO:
                self.stage.setCurrentIndex(PAGE_VIDEO)
            if has_video:
                self.start_previews()
            meta_title = e.meta().get("now_playing") or ""
            if meta_title and is_url(e.current):
                self.top.set_title(f"{e.current_title or display_name(e.current)}  ·  {meta_title}")
        self.sidebar.refresh_tracks()

    def _on_ended(self):
        e = self.engine
        if e.current:
            ln = e.length()
            self.store.set_position(e.current, ln, ln)
            self.store.set_watched(e.current, True)
        if self._sleep_end_of_file:
            self._sleep_end_of_file = False
            self.sidebar.sleep.select(0)
            self.sidebar.sleep_label.setText("")
            self.toast("Sleep timer: stopped at the end of the file")
            return
        if self.repeat == "one" and e.current:
            self.play_queue_index(self.qindex) if self.qindex >= 0 else self.play_path(e.current, start_ms=0)
            return
        if not self.play_next():
            self.bottom.set_playing(False)
            self._poke(4)

    def _save_position(self):
        e = self.engine
        if e.current and not is_url(e.current):
            ln, t = e.length(), e.time()
            if ln > 0 and t > 0:
                self.store.set_position(e.current, t, ln)

    def _time_tick(self):
        e = self.engine
        if not e.current:
            return
        if self._bars_visible or self.stage.currentIndex() == PAGE_AUDIO:
            self.bottom.set_time(e.time(), e.length())
        if self.sidebar.isVisible():
            self.sidebar.tick()
        now = time.monotonic()
        if e.is_playing() and now - self._last_saved > 5:
            self._last_saved = now
            self._save_position()
        if self._sleep_deadline:
            left = self._sleep_deadline - now
            if left <= 0:
                self._sleep_deadline = None
                e.pause()
                self.sidebar.sleep.select(0)
                self.sidebar.sleep_label.setText("")
                self.toast("Sleep timer: paused")
            else:
                self.sidebar.sleep_label.setText(f"Pausing in {fmt_time(left * 1000)}")

    # ================================================================ subtitles
    def open_subtitle_dialog(self, scope=None, folder=None):
        if scope is None:
            scope = "file" if self.engine.current and not is_url(self.engine.current) else "folder"
        SubtitleDialog(self, scope=scope, folder=folder).exec()

    # ================================================================ drag and drop
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasText():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = []
        for u in e.mimeData().urls():
            paths.append(u.toLocalFile() if u.isLocalFile() else u.toString())
        if not paths and e.mimeData().hasText():
            paths = [e.mimeData().text().strip()]
        self.open_paths(paths)

    def open_paths(self, paths):
        paths = [norm(p) for p in paths if p]
        # only things Pylon can actually play: media, playlists, subtitles, folders, links
        ok_ext = SUB_EXTS | PLAYLIST_EXTS
        paths = [p for p in paths if is_url(p) or os.path.isdir(p) or is_media(p)
                 or os.path.splitext(p)[1].lower() in ok_ext]
        if not paths:
            return
        subs = [p for p in paths if os.path.splitext(p)[1].lower() in SUB_EXTS]
        if subs and len(subs) == len(paths):
            if self.engine.current and len(subs) == 1:
                self.engine.add_subtitle(subs[0])
                if not is_url(self.engine.current):
                    self.store.data["sub_map"][self.engine.current] = subs[0]
                    self.store.save()
                self.sidebar.load_cues()
                self.toast(f"Subtitles: {os.path.basename(subs[0])}")
            else:
                self.open_subtitle_dialog(scope="folder")
            return
        if len(paths) == 1:
            p = paths[0]
            if os.path.isdir(p):
                self.play_folder(p)
            elif os.path.splitext(p)[1].lower() in PLAYLIST_EXTS:
                self.open_playlist_file(p)
            elif is_url(p):
                self.open_stream(p)
            else:
                self.play_from_folder(p)
            return
        files = []
        for p in paths:
            files.extend(list_media(p) if os.path.isdir(p) else [p])
        files = [f for f in files if is_url(f) or is_media(f)]
        if self.engine.current and self.engine.is_playing():
            self.enqueue(files)
        else:
            self.set_queue([{"path": f} for f in files], 0)

    # ================================================================ closing
    def closeEvent(self, e):
        self.thumbs.cancel()
        self._save_position()
        self.store.data["queue"] = [{k: v for k, v in q.items() if k in ("path", "title")} for q in self.queue][:500]
        self.engine.shutdown()
        self.store.save_now()
        for w in (self.top, self.bottom, self.osd):
            w.close()
        self.video.unsetCursor()
        super().closeEvent(e)
