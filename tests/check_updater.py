"""The updater only offers full releases and only runs an installer whose SHA-256 matches the release's."""
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication
from app import updates
from app.store import Store

app = QCoreApplication.instance() or QCoreApplication([])
PAYLOAD = b"MZ fake installer " * 5000
GOOD = hashlib.sha256(PAYLOAD).hexdigest()


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def release(tag="v9.0.0", sums=None, digest=None, **flags):
    asset = {"name": f"Pylon-Setup-{tag[1:]}.exe", "size": len(PAYLOAD),
             "browser_download_url": "https://example.invalid/setup.exe"}
    if digest:
        asset["digest"] = digest
    assets = [asset]
    if sums is not None:
        assets.append({"name": "SHA256SUMS.txt", "browser_download_url": "https://example.invalid/sums"})
    return {"tag_name": tag, "assets": assets, "_sums": sums, **flags}


class Updater(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))
        self.store._save_timer.stop()
        self.checker = updates.UpdateChecker(self.store)
        self.events = []
        self.checker.found.connect(lambda r: self.events.append(("found", r["tag_name"])))
        self.checker.none.connect(lambda: self.events.append(("none",)))
        self.checker.downloaded.connect(lambda p: self.events.append(("downloaded", p)))
        self.checker.download_failed.connect(lambda why: self.events.append(("failed", why)))

    def tearDown(self):
        self.temp.cleanup()

    def serve(self, rel, payload=PAYLOAD):
        def get(url, timeout=15):
            if url.endswith("/sums"):
                return FakeResponse(rel["_sums"].encode())
            return FakeResponse(payload)
        return patch.object(updates, "_get", get)

    def download(self, rel, payload=PAYLOAD):
        asset = updates.installer_asset(rel)
        with self.serve(rel, payload), patch.object(updates.tempfile, "gettempdir", lambda: self.temp.name):
            self.checker._download(asset, updates.threading.Event(), rel)
        return os.path.join(self.temp.name, asset["name"])

    def test_parse_sums(self):
        sums = updates.parse_sums(f"{GOOD}  Pylon-Setup-9.0.0.exe\n{'a' * 64} *Pylon.zip\nnot a line\n")
        self.assertEqual(sums, {"Pylon-Setup-9.0.0.exe": GOOD, "Pylon.zip": "a" * 64})

    def test_matching_installer_is_kept(self):
        out = self.download(release(sums=f"{GOOD}  Pylon-Setup-9.0.0.exe\n"))
        self.assertEqual(self.events, [("downloaded", out)])
        self.assertEqual(Path(out).read_bytes(), PAYLOAD)

    def test_github_digest_is_used_without_sums_file(self):
        out = self.download(release(digest="sha256:" + GOOD))
        self.assertEqual(self.events, [("downloaded", out)])

    def test_tampered_installer_is_refused(self):
        out = self.download(release(sums=f"{GOOD}  Pylon-Setup-9.0.0.exe\n"), payload=PAYLOAD[:-1] + b"!")
        self.assertEqual(self.events[0][0], "failed")
        self.assertIn("checksum", self.events[0][1])
        self.assertFalse(os.path.exists(out))
        self.assertFalse(os.path.exists(out + ".part"))

    def test_no_checksum_means_no_install(self):
        out = self.download(release())
        self.assertEqual(self.events[0][0], "failed")
        self.assertFalse(os.path.exists(out))

    def test_prereleases_and_drafts_are_not_offered(self):
        listing = [release("v9.1.0", prerelease=True), release("v9.2.0", draft=True), release("v9.0.1")]
        for r in listing:
            r.pop("_sums")
        with patch.object(updates, "_get", lambda url, timeout=15: FakeResponse(json.dumps(listing).encode())):
            self.checker._check(manual=True)
        self.assertEqual(self.events, [("found", "v9.0.1")])

    def test_only_prereleases_means_up_to_date(self):
        listing = [release("v9.1.0", prerelease=True)]
        listing[0].pop("_sums")
        with patch.object(updates, "_get", lambda url, timeout=15: FakeResponse(json.dumps(listing).encode())):
            self.checker._check(manual=True)
        self.assertEqual(self.events, [("none",)])


if __name__ == "__main__":
    unittest.main()
