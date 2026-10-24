"""Main window: update checks, finding VLC, desktop integration and restarting."""
import os
import sys

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from . import engine as engine_mod
from . import theme
from .dialogs import WelcomeDialog


class SystemMixin:
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
