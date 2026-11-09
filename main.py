"""Pylon entry point.

    python main.py [file or folder or URL ...]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # find app/ when started from elsewhere

from app import startup  # noqa: E402
startup.install()
startup.mark("Importing Qt")
from PySide6.QtCore import QEvent, Qt, QTimer, Signal  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
startup.mark("Qt imported")

from app import APP_NAME, theme  # noqa: E402
from app.store import Store  # noqa: E402


class PylonApp(QApplication):
    """Catches macOS 'open this file' events (double-click in Finder)."""
    file_opened = Signal(str)

    def __init__(self, argv):
        super().__init__(argv)
        self.pending = []
        self._ready = False

    def event(self, e):
        if e.type() == QEvent.FileOpen:
            path = e.file() or e.url().toString()
            if path:
                if self._ready:
                    self.file_opened.emit(path)
                else:
                    self.pending.append(path)
            return True
        return super().event(e)


def _install_error_log():
    """pythonw has no console, so write errors to logs\\error.log next to
    main.py (or in the data folder if this folder isn't writable)."""
    import time
    import traceback
    from app.paths import open_log
    f = open_log("error.log")
    if f is None:
        return
    f.write(f"\n===== started {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
    if sys.stderr is None or not hasattr(sys.stderr, "write"):
        sys.stderr = f
    if sys.stdout is None:
        sys.stdout = f

    previous = sys.excepthook      # startup.py's hook writes startup.log; keep it working (H6)

    def hook(t, v, tb):
        f.write("".join(traceback.format_exception(t, v, tb)))
        f.flush()
        previous(t, v, tb)
    sys.excepthook = hook


def main():
    _install_error_log()
    if sys.platform == "win32":
        try:  # own taskbar icon instead of python.exe's
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Pylon.App")
        except Exception:
            pass
    if sys.platform.startswith("linux") and not os.environ.get("QT_QPA_PLATFORM"):
        # VLC draws video into an X11 window; under Wayland, run through XWayland
        os.environ["QT_QPA_PLATFORM"] = "xcb"
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = PylonApp(sys.argv)
    startup.mark("Qt application created")
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("Pylon")
    app.setStyle("Fusion")
    ico = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pylon.ico")
    if os.path.isfile(ico):
        from PySide6.QtGui import QIcon
        app.setWindowIcon(QIcon(ico))
    store = Store()       # also drops history and queue entries that aren't media
    if store.load_error:
        print(f"data.json was unreadable ({store.load_error}); kept as {store.corrupt_copy or 'is'}"
              + (", restored data.json.bak" if store.restored_backup else ""), file=sys.stderr, flush=True)
    theme.set_theme(store.setting("theme"), store.setting("theme_tint"))
    theme.set_accent(store.setting("accent"))
    app.setStyleSheet(theme.stylesheet())
    if sys.platform == "win32":
        app.setFont(QFont("Segoe UI", 10))

    me = os.path.normcase(os.path.abspath(__file__))
    args = [a for a in sys.argv[1:]
            if a and not a.startswith("-")
            and os.path.normcase(os.path.abspath(a)) != me      # never "play" Pylon itself
            and not a.lower().endswith((".py", ".pyw", ".exe", ".bat"))]
    print("argv:", sys.argv, "-> opening:", args, file=sys.stderr, flush=True)

    # One Pylon at a time: if it's already open, hand the files to it and quit.
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    server_name = "PylonMediaPlayer-" + (os.environ.get("USERNAME") or os.environ.get("USER") or "user")
    sock = QLocalSocket()
    sock.connectToServer(server_name)
    if sock.waitForConnected(400):
        sock.write(("\n".join(args) or "<show>").encode("utf-8"))
        sock.flush()
        sock.waitForBytesWritten(1000)
        sock.disconnectFromServer()
        return

    startup.mark("Importing player and VLC")
    from app.window import MainWindow
    startup.mark("Creating main window")
    win = MainWindow(store)
    win.show()
    startup.mark("Main window shown")
    app.file_opened.connect(lambda p: win.open_paths([p]))   # macOS: Finder "Open with"
    app._ready = True
    for p in app.pending:
        QTimer.singleShot(400, lambda p=p: win.open_paths([p]))

    server = QLocalServer(app)
    if not server.listen(server_name):
        # A socket file is left from a Pylon that crashed, or another Pylon started at the same moment.
        # Only remove it if nobody answers there, so a live Pylon keeps its socket.
        probe = QLocalSocket()
        probe.connectToServer(server_name)
        if not probe.waitForConnected(400):
            QLocalServer.removeServer(server_name)
            server.listen(server_name)
        else:
            probe.disconnectFromServer()

    def on_connection():
        conn = server.nextPendingConnection()
        if conn is None:
            return
        buf = bytearray()

        def read():
            buf.extend(bytes(conn.readAll()))

        def done():
            data = buf.decode("utf-8", "replace").strip()
            if not data:                 # another Pylon only checking that this one is alive
                conn.deleteLater()
                return
            paths = [p for p in data.splitlines() if p and p != "<show>"]
            if win.isMinimized():
                win.showNormal()
            win.raise_()
            win.activateWindow()
            if paths:
                win.open_paths(paths)
            conn.deleteLater()
        conn.readyRead.connect(read)
        conn.disconnected.connect(done)
    server.newConnection.connect(on_connection)

    if args:
        QTimer.singleShot(300, lambda: win.open_paths(args))
    app.aboutToQuit.connect(win.shutdown)        # does nothing if the window already closed
    code = app.exec()
    startup.mark(f"Event loop exited: {code}")
    store.save_now()
    sys.exit(code)


if __name__ == "__main__":
    main()
