"""Main window: the main menu, the right-click menu and the subtitle and audio menus."""

from PySide6.QtCore import QPoint
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import QMenu, QMessageBox

from . import theme
from .dialogs import PreferencesDialog, ShortcutsDialog
from .icons import icon
from .util import display_name, fmt_time


class MenusMixin:
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

    def build_cast_menu(self, parent=None) -> QMenu:
        """Cast to a Chromecast on your network. Looking for devices only starts when this menu opens."""
        m = QMenu("Cast to", parent or self)
        m.setIcon(icon("cast", theme.accent() if self.engine.renderer else theme.TEXT, 16))
        self._cast_menu = m
        m.aboutToShow.connect(lambda: (self.engine.start_discovery(), self._fill_cast_menu(m)))
        m.destroyed.connect(lambda *_: setattr(self, "_cast_menu", None))
        m.addAction("This computer").setEnabled(False)    # filled in when it opens
        return m

    def _fill_cast_menu(self, m):
        try:
            m.clear()
        except RuntimeError:          # the menu has already closed
            self._cast_menu = None
            return
        e = self.engine
        cur = e.renderer["key"] if e.renderer else None
        grp = QActionGroup(m)
        a = m.addAction("This computer")
        a.setCheckable(True)
        a.setChecked(cur is None)
        grp.addAction(a)
        a.triggered.connect(lambda: self.cast_to(None) if e.renderer else None)
        found = e.renderers()
        if found:
            m.addSection("On your network")
        for r in found:
            a = m.addAction(r["name"])
            a.setCheckable(True)
            a.setChecked(r["key"] == cur)
            grp.addAction(a)
            a.triggered.connect(lambda _=False, r=r: self.cast_to(r) if r["key"] != cur else None)
        if not found:
            a = m.addAction("Looking for Chromecasts on your network…" if e.looking_for_renderers()
                            else "Casting isn't available with this VLC")
            a.setEnabled(False)

    def build_disc_menu(self, parent=None) -> QMenu:
        e = self.engine
        m = QMenu("Disc", parent or self)
        m.setIcon(icon("disc", theme.TEXT, 16))
        titles = e.titles()
        if any(menu for *_x, menu in titles):
            m.addAction(icon("menu", theme.TEXT, 16), "Disc menu", self.go_disc_menu)
        cur = e.title()
        grp = QActionGroup(m)
        shown = [(i, n, d) for i, n, d, menu in titles if not menu]
        if shown:
            m.addSection("Titles")
        for i, name, dur in shown:
            a = m.addAction(f"{name}    {fmt_time(dur)}" if dur else name)
            a.setCheckable(True)
            a.setChecked(i == cur)
            grp.addAction(a)
            a.triggered.connect(lambda _=False, i=i: self.play_title(i))
        if not titles:
            m.addAction("No titles found").setEnabled(False)
        return m

    def build_repeat_menu(self, parent=None) -> QMenu:
        a, b = self.ab_loop
        key = self.store.shortcut("ab_loop")
        m = QMenu("Repeat a part", parent or self)
        m.setIcon(icon("ab", theme.accent() if b is not None else theme.TEXT, 16))
        m.addAction(f"Start here (A)\t{key}" if a is None else "Move the start here (A)",
                    lambda: self.toast(self.set_ab_point("a")))
        end = m.addAction("End here (B)" + (f"\t{key}" if a is not None and b is None else ""),
                          lambda: self.toast(self.set_ab_point("b")))
        end.setEnabled(a is not None)
        off = m.addAction("Stop repeating" + (f"\t{key}" if b is not None else ""), lambda: self.toast(self.clear_ab()))
        off.setEnabled(a is not None)
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
        if self.engine.ok:
            m.addMenu(self.build_cast_menu(m))
        if self.engine.current:
            m.addSeparator()
            if self.engine.is_disc():
                m.addMenu(self.build_disc_menu(m))
            m.addAction(icon("subtitles", theme.TEXT, 16), "Add subtitles…", lambda: self.open_subtitle_dialog())
            m.addAction(icon("bookmark_add", theme.TEXT, 16), "Add bookmark\tCtrl+B", lambda: self.do("bookmark", key=False))
            m.addAction(icon("snapshot", theme.TEXT, 16), "Take a snapshot", lambda: self.do("snapshot", key=False))
            m.addAction(icon("close", theme.TEXT, 16), "Close the video\tCtrl+W", self.close_media)
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
            m.addAction(icon("close", theme.TEXT, 16), "Close the video\tCtrl+W", self.close_media)
            m.addSeparator()
            if e.is_disc():
                m.addMenu(self.build_disc_menu(m))
            m.addMenu(self.build_subs_menu(m))
            m.addMenu(self.build_audio_menu(m))
            vm = m.addMenu(icon("video", theme.TEXT, 16), "Video")
            vm.addSection("Video track")
            self._track_actions(vm, e.video_tracks(), e.current_video(), e.set_video)
            vm.addSection("Aspect ratio")
            grp = QActionGroup(vm)
            for label, v in [("Auto", "")] + self.store.ratio_choices("aspect"):      # as in Preferences (#62)
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
            m.addMenu(self.build_repeat_menu(m))
            m.addMenu(self.build_cast_menu(m))
            m.addSeparator()
            m.addAction(icon("bookmark_add", theme.TEXT, 16), "Add bookmark\tCtrl+B", lambda: self.do("bookmark", key=False))
            m.addAction(icon("snapshot", theme.TEXT, 16), "Take a snapshot", lambda: self.do("snapshot", key=False))
            m.addSeparator()
        m.addAction(icon("sidebar_left", theme.TEXT, 16), "Library and queue\tCtrl+L", lambda: self.toggle_library())
        m.addAction(icon("sidebar_right", theme.TEXT, 16), "Settings panel\tCtrl+T", lambda: self.toggle_sidebar())
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
