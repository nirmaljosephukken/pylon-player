"""Update check.

Once a day (and when you pick "Check for updates…") Pylon asks GitHub's public
API for the list of releases. Nothing about you or your files is sent: it is a
plain, anonymous request for the release list. Turn it off in Preferences >
Privacy.

On Windows, "Update now" downloads the new installer, starts it and closes
Pylon. The installer goes into the same folder as before, and your library,
presets and settings (kept in your user profile, not the install folder) stay
as they are. On Linux and macOS it opens the download page.
"""
import json
import os
import re
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

from PySide6.QtCore import QObject, Signal

from . import APP_VERSION

REPO = "nirmaljosephukken/pylon-player"
API = f"https://api.github.com/repos/{REPO}/releases?per_page=10"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
DAY = 24 * 3600


def parse_version(v: str) -> tuple:
    nums = re.findall(r"\d+", (v or "").split("-")[0])
    return tuple(int(n) for n in nums[:3]) + (0,) * (3 - len(nums[:3]))


def is_newer(remote: str, local: str = APP_VERSION) -> bool:
    return parse_version(remote) > parse_version(local)


def _ssl_context():
    ctx = ssl.create_default_context()
    # bundled Python on Linux and macOS may not know where the system keeps its certificates
    if not ctx.get_ca_certs():
        for f in ("/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt",
                  "/etc/ssl/ca-bundle.pem", "/etc/ssl/cert.pem", "/usr/local/etc/openssl/cert.pem"):
            if os.path.isfile(f):
                try:
                    ctx.load_verify_locations(f)
                    break
                except (OSError, ssl.SSLError):
                    pass
    return ctx


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": f"Pylon/{APP_VERSION}",
                                               "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout, context=_ssl_context())


def installer_asset(release: dict):
    """The Windows installer attached to a release, if any."""
    for a in release.get("assets", []):
        n = a.get("name", "")
        if n.lower().startswith("pylon-setup") and n.lower().endswith(".exe"):
            return a
    return None


class UpdateChecker(QObject):
    found = Signal(dict)            # newest release (GitHub's JSON), when newer than this copy
    none = Signal()                 # checked, already up to date
    failed = Signal(str)
    download_progress = Signal(int, int)
    downloaded = Signal(str)        # path to the installer
    download_failed = Signal(str)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.busy = False
        self._cancel = threading.Event()

    # ------------------------------------------------------------------ check
    def due(self) -> bool:
        if not self.store.setting("check_updates"):
            return False
        last = float(self.store.setting("last_update_check") or 0)
        return time.time() - last > DAY

    def check(self, manual=False):
        if self.busy:
            return
        self.busy = True
        self.store.set_setting("last_update_check", time.time())
        threading.Thread(target=self._check, args=(manual,), daemon=True).start()

    def _check(self, manual):
        try:
            with _get(API) as r:
                releases = json.loads(r.read().decode("utf-8"))
            best = None
            for rel in releases:
                if rel.get("draft"):
                    continue
                if best is None or parse_version(rel.get("tag_name", "")) > parse_version(best.get("tag_name", "")):
                    best = rel
            skipped = self.store.setting("skipped_version") or ""
            if best and is_newer(best.get("tag_name", "")):
                tag = best.get("tag_name", "").lstrip("vV")
                if manual or tag != skipped:
                    self.found.emit(best)
                    return
            self.none.emit()
        except Exception as e:      # offline, rate limited, blocked: try again tomorrow
            self.failed.emit(str(e) or e.__class__.__name__)
        finally:
            self.busy = False

    # ------------------------------------------------------------------ download (Windows)
    def download(self, asset: dict):
        self._cancel = threading.Event()
        threading.Thread(target=self._download, args=(asset, self._cancel), daemon=True).start()

    def cancel(self):
        self._cancel.set()

    def _download(self, asset, cancel):
        name = os.path.basename(asset.get("name") or "Pylon-Setup.exe")
        out = os.path.join(tempfile.gettempdir(), name)
        part = out + ".part"
        total = int(asset.get("size") or 0)
        try:
            with _get(asset["browser_download_url"], timeout=30) as r, open(part, "wb") as f:
                total = int(r.headers.get("Content-Length") or total)
                done = 0
                last = 0.0
                while True:
                    if cancel.is_set():
                        raise InterruptedError("cancelled")
                    chunk = r.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if time.time() - last > 0.1:
                        self.download_progress.emit(done, total)
                        last = time.time()
            if total and os.path.getsize(part) != total:
                raise IOError("the download was incomplete")
            os.replace(part, out)
            self.download_progress.emit(total, total)
            self.downloaded.emit(out)
        except Exception as e:
            try:
                os.remove(part)
            except OSError:
                pass
            if not cancel.is_set():
                self.download_failed.emit(str(e) or e.__class__.__name__)


def run_installer(path: str) -> bool:
    """Start the downloaded installer on its own, so Pylon can close and free its files."""
    try:
        if sys.platform == "win32":
            flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            subprocess.Popen([path], creationflags=flags, close_fds=True)
        else:
            return False
        return True
    except OSError:
        return False
