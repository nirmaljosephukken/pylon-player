"""1.8.1, #92: the installer that "Update now" downloaded doesn't stay in the temporary folder.

The installer can't delete itself while it runs, so Pylon removes it the next time it starts: installers for
this version or an older one, finished or not. A newer one (still downloading or installing) and other files
are left alone.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import updates


class Cleanup(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = self.temp.name

    def tearDown(self):
        self.temp.cleanup()

    def touch(self, name):
        with open(os.path.join(self.dir, name), "wb") as f:
            f.write(b"MZ")

    def left(self):
        return sorted(os.listdir(self.dir))

    def test_old_and_current_installers_go(self):
        for name in ("Pylon-Setup-1.8.0.exe", "Pylon-Setup-1.8.1.exe", "pylon-setup-1.7.1.exe",
                     "Pylon-Setup-1.8.1.exe.part", "Pylon-Setup-1.9.0.exe", "Pylon-Setup-1.9.0.exe.part",
                     "Pylon-Setup.exe", "Other-Setup-1.0.exe", "notes.txt"):
            self.touch(name)
        removed = updates.remove_old_installers(self.dir, current="1.8.1")
        self.assertEqual(len(removed), 4)
        self.assertEqual(self.left(), ["Other-Setup-1.0.exe", "Pylon-Setup-1.9.0.exe", "Pylon-Setup-1.9.0.exe.part",
                                       "Pylon-Setup.exe", "notes.txt"])

    def test_a_locked_file_is_tried_again_later(self):
        self.touch("Pylon-Setup-1.8.0.exe")
        real_remove = os.remove

        def busy(path):
            raise PermissionError("in use")
        with patch.object(updates.os, "remove", busy):
            self.assertEqual(updates.remove_old_installers(self.dir, current="1.8.1"), [])
        self.assertEqual(self.left(), ["Pylon-Setup-1.8.0.exe"])
        updates.os.remove = real_remove
        self.assertEqual(len(updates.remove_old_installers(self.dir, current="1.8.1")), 1)
        self.assertEqual(self.left(), [])

    def test_missing_folder_is_fine(self):
        self.assertEqual(updates.remove_old_installers(os.path.join(self.dir, "gone")), [])

    def test_default_is_the_temporary_folder_and_this_version(self):
        with patch.object(updates.tempfile, "gettempdir", return_value=self.dir):
            self.touch(f"Pylon-Setup-{updates.APP_VERSION}.exe")
            updates.remove_old_installers()
        self.assertEqual(self.left(), [])

    def test_the_download_goes_where_the_cleanup_looks(self):
        # _download names the file after the release asset in tempfile.gettempdir()
        name = "Pylon-Setup-1.8.1.exe"
        self.assertTrue(updates.INSTALLER_RE.match(name))
        self.assertTrue(updates.INSTALLER_RE.match(name + ".part"))

    def test_window_runs_it_at_startup_on_windows(self):
        src = (Path(__file__).resolve().parents[1] / "app" / "window.py").read_text(encoding="utf-8")
        self.assertIn("self.remove_old_installers", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
