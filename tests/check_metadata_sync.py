"""The version number and the "Open with" file types match app/ in every installer and desktop file."""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("sync_metadata", ROOT / "packaging/sync_metadata.py")
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)

from app import APP_VERSION  # noqa: E402
from app.util import ASSOCIATED_EXTS, MIME_TYPES, desktop_mime_types  # noqa: E402


class MetadataSync(unittest.TestCase):
    def test_files_are_in_sync(self):
        self.assertEqual(sync.out_of_date(), [], "run python packaging/sync_metadata.py")

    def test_every_type_has_a_mime_type_and_iso_is_left_out(self):
        self.assertEqual([e for e in ASSOCIATED_EXTS if e not in MIME_TYPES], [])
        self.assertNotIn(".iso", ASSOCIATED_EXTS)
        self.assertNotIn(".alac", ASSOCIATED_EXTS)
        self.assertIn("video/x-matroska", desktop_mime_types())

    def test_version_everywhere(self):
        texts = {p.name: p.read_text(encoding="utf-8") for p in sync.expected()}
        self.assertIn(f'!define VERSION "{APP_VERSION}"', texts["pylon.nsi"])
        self.assertIn(f'"FileVersion", "{APP_VERSION}', texts["pylon.rc"])
        self.assertTrue(texts["license-summary.txt"].startswith(f"Pylon {APP_VERSION}"))
        self.assertEqual(texts["Info.plist"].count(f"<string>{APP_VERSION}</string>"), 2)
        self.assertIn(f'<release version="{APP_VERSION}"', texts["io.github.nirmaljosephukken.pylon.appdata.xml"])

    def test_installer_lists_each_type(self):
        nsh = (ROOT / "packaging/windows/file-types.nsh").read_text(encoding="utf-8")
        for e in ASSOCIATED_EXTS:
            self.assertIn(f'!insertmacro ${{MACRO}} "{e}"', nsh)
        nsi = (ROOT / "packaging/windows/pylon.nsi").read_text(encoding="utf-8")
        self.assertIn('!include "file-types.nsh"', nsi)
        self.assertNotIn('Classes\\.mkv', nsi)          # no hand-written per-type lines left


if __name__ == "__main__":
    unittest.main()
