"""Pylon entry point.

    python main.py [file or folder or URL ...]
"""
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import APP_NAME, theme  # noqa: E402
from app.store import Store  # noqa: E402


def _install_error_log():
    """pythonw has no console, so write errors to logs\\error.log next to
    main.py (or in the data folder if this folder isn't writable)."""
    import time
    import traceback
    from app.store import data_dir
    f = None
    for log_dir in (os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs"),
                    os.path.join(data_dir(), "logs")):
        try:
            os.makedirs(log_dir, exist_ok=True)
            path = os.path.join(log_dir, "error.log")
            if os.path.isfile(path) and os.path.getsize(path) > 1_000_000:
                os.remove(path)
            f = open(path, "a", encoding="utf-8", buffering=1)
            break
        except OSError:
            continue
    if f is None:
        return
    f.write(f"\n===== started {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
    if sys.stderr is None or not hasattr(sys.stderr, "write"):
        sys.stderr = f
    if sys.stdout is None:
        sys.stdout = f

    def hook(t, v, tb):
        f.write("".join(traceback.format_exception(t, v, tb)))
        f.flush()
    sys.excepthook = hook


def main():
    _install_error_log()
    if sys.platform == "win32":
        try:  # own taskbar icon instead of python.exe's
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Pylon.App")
        except Exception:
            pass
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("Pylon")
    app.setStyle("Fusion")
    ico = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pylon.ico")
    if os.path.isfile(ico):
        from PySide6.QtGui import QIcon
        app.setWindowIcon(QIcon(ico))
    store = Store()
    # tidy history: drop anything that isn't media (e.g. main.py opened by mistake)
    from app.util import is_media, is_url
    store.data["recent"] = [r for r in store.data.get("recent", [])
                            if is_url(r.get("path", "")) or is_media(r.get("path", ""))]
    store.data["queue"] = [q for q in store.data.get("queue", [])
                           if is_url(q.get("path", "")) or is_media(q.get("path", ""))]
    theme.set_accent(store.setting("accent"))
    app.setStyleSheet(theme.stylesheet())
    f = QFont("Segoe UI", 10)
    app.setFont(f)

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

    from app.window import MainWindow
    win = MainWindow(store)
    win.show()

    QLocalServer.removeServer(server_name)
    server = QLocalServer(app)
    server.listen(server_name)

    def on_connection():
        conn = server.nextPendingConnection()
        if conn is None:
            return
        buf = bytearray()

        def read():
            buf.extend(bytes(conn.readAll()))

        def done():
            data = buf.decode("utf-8", "replace").strip()
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
        from PySide6.QtCore import QTimer
        QTimer.singleShot(300, lambda: win.open_paths(args))
    code = app.exec()
    store.save_now()
    sys.exit(code)


if __name__ == "__main__":
    main()
