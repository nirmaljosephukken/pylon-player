"""1.8.0, #91: links sent by browser extensions such as "Open in VLC".

The extension starts the player as
    Pylon.exe --http-referrer <page> --http-user-agent <browser> <stream.m3u8> :meta-title=<title>
Pylon used to drop the options but keep their values, so it queued the page and the user agent as items and
played the stream without the referrer the site's server wants. Now the options reach VLC as options of that
link (checked against a local server with real VLC), the title names it, and only the stream is queued.
"""
import http.server
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from app import engine
REAL_VLC = engine.vlc
engine.vlc = None
from app.engine import Engine
from app.store import Store
from app.util import parse_command_line
from app.window import MainWindow

app = QApplication.instance() or QApplication([])

PAGE = "https://anime.example/watch/episode-08/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
STREAM = "https://cdn.example/hls/ep08/master.m3u8?token=abc"


def wait(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class Parsing(unittest.TestCase):
    def test_open_in_vlc_arguments(self):
        targets, opts, titles = parse_command_line(
            ["--http-referrer", PAGE, "--http-user-agent", UA, STREAM, ":meta-title=Wangan Midnight 08"])
        self.assertEqual(targets, [STREAM])
        self.assertEqual(opts[STREAM], [f":http-referrer={PAGE}", f":http-user-agent={UA}"])
        self.assertEqual(titles[STREAM], "Wangan Midnight 08")

    def test_equals_form_and_options_after_the_link(self):
        targets, opts, titles = parse_command_line(
            ["--one-instance", "--http-referrer=" + PAGE, "--meta-title=Ep 8", STREAM, ":http-user-agent=" + UA])
        self.assertEqual(targets, [STREAM])
        self.assertEqual(opts[STREAM], [f":http-referrer={PAGE}", f":http-user-agent={UA}"])
        self.assertEqual(titles[STREAM], "Ep 8")

    def test_files_are_unchanged(self):
        args = [r"C:\Videos\Show\ep1.mkv", r"C:\Videos\Show\ep2.mkv"]
        self.assertEqual(parse_command_line(args), (args, {}, {}))
        self.assertEqual(parse_command_line(["--started-from-file", "a.mkv"]), (["a.mkv"], {}, {}))

    def test_unknown_options_are_ignored(self):
        targets, opts, _ = parse_command_line(["--fullscreen", ":no-video", STREAM, ":network-caching=1000"])
        self.assertEqual(targets, [STREAM])
        self.assertEqual(opts, {})


class Window(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))
        self.store.set_setting("onboarded", True)
        with patch.object(MainWindow, "_welcome", lambda self: None), patch.object(MainWindow, "_vlc_missing"):
            self.win = MainWindow(self.store)
        self.win._vlc_missing = lambda: None
        self.win.resize(900, 600)
        self.win.show()
        wait(100)

    def tearDown(self):
        self.store._save_timer.stop()
        self.win.close()
        self.temp.cleanup()

    def test_only_the_stream_is_queued_with_its_options(self):
        w = self.win
        with patch.object(w.stream_probe, "start") as probe, patch.object(w, "play_queue_index"):
            w.open_command_line(["--http-referrer", PAGE, "--http-user-agent", UA, STREAM,
                                 ":meta-title=Wangan Midnight 08"])
        probe.assert_not_called()                      # no channel-list check without the referrer
        self.assertEqual([q["path"] for q in w.queue], [STREAM])
        self.assertEqual(w.queue[0]["title"], "Wangan Midnight 08")
        self.assertEqual(w.engine.url_options[STREAM], [f":http-referrer={PAGE}", f":http-user-agent={UA}"])

    def test_plain_files_still_open(self):
        w = self.win
        with patch.object(w, "open_paths") as op:
            w.open_command_line(["a.mkv", "b.mkv"])
        op.assert_called_once_with(["a.mkv", "b.mkv"])

    def test_options_given_to_vlc_with_the_link(self):
        e = self.win.engine
        added = []

        class Media:
            def add_option(self, o):
                added.append(o)

        class Inst:
            def media_new(self, _url):
                return Media()

        class Player:
            def __getattr__(self, _name):
                return lambda *a, **k: None
        e.url_options[STREAM] = [f":http-referrer={PAGE}"]
        e.instance, e.player = Inst(), Player()
        try:
            e.open(STREAM)
            self.assertIn(f":http-referrer={PAGE}", added)
            added.clear()
            e.open("https://other.example/live.m3u8")
            self.assertEqual(added, [])
        finally:
            e.current = None
            e.instance = e.player = None


class Handler(http.server.BaseHTTPRequestHandler):
    seen = []

    def do_GET(self):
        Handler.seen.append((self.path, self.headers.get("Referer"), self.headers.get("User-Agent")))
        self.send_response(403)
        self.end_headers()

    def log_message(self, *a):
        pass


@unittest.skipIf(REAL_VLC is None, "needs VLC")
class RealVLC(unittest.TestCase):
    def test_server_receives_the_referrer_and_user_agent(self):
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{srv.server_port}/hls/master.m3u8"
        engine.vlc = REAL_VLC
        with tempfile.TemporaryDirectory() as d:
            store = Store(os.path.join(d, "data.json"))
            e = Engine(store)
            try:
                self.assertTrue(e.start_engine())
                e.url_options[url] = [f":http-referrer={PAGE}", f":http-user-agent={UA}"]
                e.open(url)
                end = time.time() + 10
                while not Handler.seen and time.time() < end:
                    wait(50)
                e.close()
            finally:
                engine.vlc = None
                store._save_timer.stop()
                srv.shutdown()
        self.assertTrue(Handler.seen, "VLC never asked the server for the stream")
        path, referer, agent = Handler.seen[0]
        self.assertEqual(path, "/hls/master.m3u8")
        self.assertEqual(referer, PAGE)
        self.assertEqual(agent, UA)


if __name__ == "__main__":
    unittest.main(verbosity=2)
