"""1.8.0: subtitles from OpenSubtitles.com inside Pylon.

Nothing here goes to the internet: the API is answered by a fake. Checks the request (API key header, sorted
lower-case parameters, the file's hash), Pylon's own key used unless you set yours, that subtitles made for the exact file come first and other episodes
are dropped, downloading with and without an account, the messages for a missing or wrong key and no
downloads left, saving next to the video, and the dialogs.
"""
import io
import json
import os
import struct
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QLineEdit
from app import engine
engine.vlc = None
from app import opensubtitles as osub
from app.store import Store
from app.window import MainWindow

app = QApplication.instance() or QApplication([])


def wait(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_for(cond, timeout_ms=3000):
    end = time.time() + timeout_ms / 1000
    while not cond() and time.time() < end:
        wait(20)
    return cond()


def item(file_id, release, downloads, match=False, season=None, episode=None):
    return {"attributes": {"release": release, "download_count": downloads, "moviehash_match": match,
                           "language": "en", "files": [{"file_id": file_id, "file_name": release + ".srt"}],
                           "feature_details": {"season_number": season, "episode_number": episode}}}


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class FakeAPI:
    """Answers like api.opensubtitles.com and records each request."""

    def __init__(self, results=None, status=200, message=""):
        self.requests = []
        self.results = results or []
        self.status, self.message = status, message

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        url = req.full_url
        if self.status != 200:
            raise urllib.error.HTTPError(url, self.status, "error", {},
                                         io.BytesIO(json.dumps({"message": self.message}).encode()))
        if url.startswith("https://dl.test/"):
            return Response(b"1\n00:00:01,000 --> 00:00:02,000\nHello\n")
        if "/login" in url:
            return Response(json.dumps({"token": "TOKEN", "base_url": "vip-api.opensubtitles.com"}).encode())
        if "/download" in url:
            return Response(json.dumps({"link": "https://dl.test/sub.srt", "file_name": "sub.srt"}).encode())
        return Response(json.dumps({"data": self.results}).encode())


class Basics(unittest.TestCase):
    def test_languages(self):
        self.assertEqual(osub.api_language(""), "en")
        self.assertEqual(osub.api_language("eng"), "en")
        self.assertEqual(osub.api_language("Malayalam"), "ml")
        self.assertEqual(osub.api_language("pob"), "pt-br")
        self.assertEqual(osub.api_language("es"), "es")
        self.assertEqual(osub.api_language("jpn, eng"), "ja")
        self.assertEqual(osub.api_language("off"), "en")

    def test_hash_matches_opensubtitles_definition(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "film.mkv")
            data = bytes(range(256)) * 1024        # 256 KB
            Path(p).write_bytes(data)
            h = len(data)
            for chunk in (data[:65536], data[-65536:]):
                for (v,) in struct.iter_unpack("<Q", chunk):
                    h = (h + v) & 0xFFFFFFFFFFFFFFFF
            self.assertEqual(osub.movie_hash(p), f"{h:016x}")
            Path(p).write_bytes(b"x" * 1000)
            self.assertEqual(osub.movie_hash(p), "")             # too small to hash
            self.assertEqual(osub.movie_hash(os.path.join(d, "missing.mkv")), "")

    def test_pylons_key_unless_you_set_your_own(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(os.path.join(d, "data.json"))
            with patch.dict(os.environ, {osub.ENV_KEY: ""}), patch.object(osub, "PYLON_KEY", "PYLONKEY"):
                self.assertEqual(osub.api_key(store), "PYLONKEY")         # works with no setup
                store.set_setting("opensubtitles_key", " MYKEY ")
                self.assertEqual(osub.api_key(store), "MYKEY")            # your own key wins
                store.set_setting("opensubtitles_key", "")
            with patch.dict(os.environ, {osub.ENV_KEY: "ENVKEY"}), patch.object(osub, "PYLON_KEY", "PYLONKEY"):
                self.assertEqual(osub.api_key(store), "ENVKEY")
            with patch.dict(os.environ, {osub.ENV_KEY: ""}), patch.object(osub, "PYLON_KEY", ""):
                self.assertEqual(osub.api_key(store), "")
                with self.assertRaises(osub.OpenSubtitlesError) as ctx:
                    osub.Client("")
                self.assertIn("Preferences > Subtitles", str(ctx.exception))
            store._save_timer.stop()


class ClientCalls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.video = os.path.join(self.temp.name, "Show.S01E03.720p.mkv")
        Path(self.video).write_bytes(os.urandom(200_000))

    def tearDown(self):
        self.temp.cleanup()

    def test_search_request_and_order(self):
        api = FakeAPI([item(1, "Popular", 9000, season=1, episode=3),
                       item(2, "Exact", 10, match=True, season=1, episode=3),
                       item(3, "Wrong episode", 99999, season=1, episode=4),
                       item(4, "Less popular", 50, season=1, episode=3)])
        c = osub.Client("KEY", opener=api)
        found = c.search(self.video, language="en")
        self.assertEqual([x["file_id"] for x in found], [2, 1, 4])   # exact first, then downloads; E04 dropped
        self.assertTrue(found[0]["match"])
        req = api.requests[0]
        self.assertEqual(req.get_header("Api-key"), "KEY")
        self.assertTrue(req.get_header("User-agent").startswith("Pylon v"))
        query = urllib.parse.parse_qsl(urllib.parse.urlsplit(req.full_url).query)
        self.assertEqual([k for k, _ in query], sorted(k for k, _ in query))
        q = dict(query)
        self.assertEqual(q["moviehash"], osub.movie_hash(self.video))
        self.assertEqual((q["season_number"], q["episode_number"]), ("1", "3"))
        self.assertEqual(q["languages"], "en")
        self.assertTrue(all(v == v.lower() for v in q.values()))

    def test_typed_words(self):
        api = FakeAPI([item(5, "Something", 1)])
        c = osub.Client("KEY", opener=api)
        c.search(query="Some Film", language="es")
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(api.requests[0].full_url).query))
        self.assertEqual(q, {"languages": "es", "query": "some film"})

    def test_download_without_and_with_an_account(self):
        api = FakeAPI()
        data, name = osub.Client("KEY", opener=api).download(77)
        self.assertIn(b"Hello", data)
        self.assertEqual(name, "sub.srt")
        self.assertEqual(json.loads(api.requests[0].data), {"file_id": 77})
        self.assertIsNone(api.requests[0].get_header("Authorization"))

        api = FakeAPI()
        c = osub.Client("KEY", "me", "secret", opener=api)
        c.download(78)
        self.assertTrue(api.requests[0].full_url.endswith("/login"))
        self.assertEqual(api.requests[1].full_url, "https://vip-api.opensubtitles.com/api/v1/download")
        self.assertEqual(api.requests[1].get_header("Authorization"), "Bearer TOKEN")
        c.download(79)
        self.assertEqual(sum(r.full_url.endswith("/login") for r in api.requests), 1)   # signs in once

    def test_messages_people_can_act_on(self):
        cases = [(401, "", "API key"), (403, "", "API key"), (406, "allowed 5 downloads", "No downloads left"),
                 (429, "", "slow down"), (500, "oops", "500")]
        for status, message, expect in cases:
            with self.assertRaises(osub.OpenSubtitlesError) as ctx:
                osub.Client("KEY", opener=FakeAPI(status=status, message=message)).search(query="x")
            self.assertIn(expect, str(ctx.exception), status)

        def offline(req, timeout=None):
            raise urllib.error.URLError("no network")
        with self.assertRaises(osub.OpenSubtitlesError) as ctx:
            osub.Client("KEY", opener=offline).search(query="x")
        self.assertIn("Couldn't reach", str(ctx.exception))

    def test_saved_next_to_the_video_or_in_pylons_folder(self):
        p = osub.save_next_to(self.video, b"subs", "en", os.path.join(self.temp.name, "fallback"))
        self.assertEqual(p, os.path.join(self.temp.name, "Show.S01E03.720p.en.srt"))
        self.assertEqual(Path(p).read_bytes(), b"subs")
        blocker = os.path.join(self.temp.name, "blocker")
        Path(blocker).write_bytes(b"")              # a file where the folder should be: can't write there
        locked = os.path.join(blocker, "folder")
        fb = os.path.join(self.temp.name, "fallback")
        p2 = osub.save_next_to(os.path.join(locked, "film.mkv"), b"x", "en", fb)
        self.assertEqual(os.path.dirname(p2), fb)


class Dialogs(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))
        self.store.set_setting("onboarded", True)
        self.store.set_setting("opensubtitles_key", "KEY")
        with patch.object(MainWindow, "_welcome", lambda self: None), patch.object(MainWindow, "_vlc_missing"):
            self.win = MainWindow(self.store)
        self.win._vlc_missing = lambda: None
        self.win.resize(900, 600)
        self.win.show()
        wait(100)
        self.video = os.path.join(self.temp.name, "Film.2020.mkv")
        Path(self.video).write_bytes(os.urandom(200_000))

    def tearDown(self):
        self.win.engine.current = None
        self.store._save_timer.stop()
        self.win.close()
        self.temp.cleanup()

    def test_pick_one_and_save_it(self):
        from app.dialogs import OnlineSubtitlesDialog
        api = FakeAPI([item(1, "Popular", 900), item(2, "Exact", 1, match=True)])
        with patch.object(osub.urllib.request, "urlopen", api):
            dlg = OnlineSubtitlesDialog(self.win, self.video)
            self.assertTrue(wait_for(lambda: dlg.results.count() == 2))
            self.assertTrue(dlg.results.item(0).text().startswith("✓ Made for this file"))
            self.assertIn("1 made for this exact file", dlg.note.text())
            dlg.fetch()
            self.assertTrue(wait_for(lambda: bool(dlg.saved)))
        self.assertEqual(dlg.saved, os.path.join(self.temp.name, "Film.2020.en.srt"))
        self.assertTrue(os.path.isfile(dlg.saved))

    def test_no_key_says_where_to_get_one(self):
        from app.dialogs import OnlineSubtitlesDialog
        self.store.set_setting("opensubtitles_key", "")
        with patch.dict(os.environ, {osub.ENV_KEY: ""}), patch.object(osub, "PYLON_KEY", ""):
            dlg = OnlineSubtitlesDialog(self.win, self.video)
        self.assertIn("Preferences > Subtitles", dlg.note.text())
        self.assertIn(osub.KEY_PAGE, dlg.note.text())
        self.assertFalse(dlg.go.isEnabled())
        dlg.close()

    def test_bulk_download_pairs_every_video(self):
        from app.dialogs import SubtitleDialog
        vids = []
        for n in (1, 2, 3):
            v = os.path.join(self.temp.name, f"Show.S01E0{n}.mkv")
            Path(v).write_bytes(os.urandom(200_000))
            vids.append(v)
        dlg = SubtitleDialog(self.win, scope="folder", folder=self.temp.name)
        dlg.videos = lambda: vids
        api = FakeAPI([item(1, "Any", 5, season=1, episode=1), item(2, "Any", 5, season=1, episode=2),
                       item(3, "Any", 5, season=1, episode=3)])
        with patch.object(osub.urllib.request, "urlopen", api):
            dlg.download()
            self.assertTrue(wait_for(lambda: dlg.download_btn.isEnabled(), 5000))
        for v in vids:
            self.assertTrue(os.path.isfile(os.path.splitext(v)[0] + ".en.srt"))
        self.assertIn("Downloaded 3", dlg.note.text())
        dlg.close()

    def test_preferences_fields(self):
        from app.dialogs import PreferencesDialog
        dlg = PreferencesDialog(self.win)
        key = dlg.findChild(QLineEdit, "opensubtitles_key")
        pw = dlg.findChild(QLineEdit, "opensubtitles_password")
        self.assertIsNotNone(key)
        self.assertEqual(pw.echoMode(), QLineEdit.Password)
        key.setText("NEWKEY")
        self.assertEqual(self.store.setting("opensubtitles_key"), "NEWKEY")
        dlg.close()

    def test_find_online_menu_and_shortcut(self):
        from app.widgets import subtitle_search_menu
        called = []
        menu = subtitle_search_menu(None, self.store, lambda: "x", lambda: called.append(1))
        first = menu.actions()[0]
        self.assertIn("OpenSubtitles.com", first.text())
        first.trigger()
        self.assertEqual(called, [1])
        self.assertEqual(self.store.shortcut("download_subs"), "Shift+D")


if __name__ == "__main__":
    unittest.main(verbosity=2)
