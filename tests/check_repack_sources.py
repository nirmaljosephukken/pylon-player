"""A runtime-baseline repack must include newly added application modules."""
import importlib.util
import io
import stat
import struct
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('repack', ROOT / 'packaging/repack_release.py')
repack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repack)
NEW_MODULES = {'app/colour_dialog.py', 'app/startup.py'}


class RepackSources(unittest.TestCase):
    def test_new_mac_modules_and_existing_modes(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / 'base'
            out = Path(directory) / 'out'
            base.mkdir()
            out.mkdir()
            with zipfile.ZipFile(base / 'Pylon-1.3.2-macOS.zip', 'w') as archive:
                for name in repack.sources():
                    if name not in NEW_MODULES | {'diag.bat', 'pylon.ico'}:
                        archive.writestr('Pylon.app/Contents/Resources/pylon/' + name, b'old source')
                archive.writestr('Pylon.app/Contents/Info.plist', b'old plist')
                launcher = zipfile.ZipInfo('Pylon.app/Contents/MacOS/Pylon')
                launcher.create_system = 3
                launcher.external_attr = 0o100755 << 16
                archive.writestr(launcher, b'old launcher')
                link = zipfile.ZipInfo('runtime-link')
                link.create_system = 3
                link.external_attr = 0o120777 << 16
                archive.writestr(link, b'runtime-target')
            with patch.multiple(repack, BASE=base, OUT=out):
                repack.macos()
            with zipfile.ZipFile(out / f'Pylon-{repack.VERSION}-macOS.zip') as archive:
                self.assertIsNone(archive.testzip())
                for name in NEW_MODULES:
                    entry = 'Pylon.app/Contents/Resources/pylon/' + name
                    self.assertEqual(archive.read(entry), (ROOT / name).read_bytes())
                    self.assertEqual(stat.S_IMODE(archive.getinfo(entry).external_attr >> 16), 0o644)
                self.assertTrue(archive.getinfo('Pylon.app/Contents/MacOS/Pylon').external_attr >> 16 & 0o111)
                self.assertEqual(archive.read('runtime-link'), b'runtime-target')
                self.assertTrue(stat.S_ISLNK(archive.getinfo('runtime-link').external_attr >> 16))

    def test_new_linux_modules_and_existing_modes(self):
        with tempfile.TemporaryDirectory() as directory:
            build = Path(directory)
            with tarfile.open(build / 'linux-old.tar', 'w') as archive:
                names = ['usr/share/pylon/' + n for n in repack.sources()
                         if n not in NEW_MODULES | {'diag.bat', 'pylon.ico', 'pylon.png'}]
                names += ['usr/share/metainfo/io.github.nirmaljosephukken.pylon.appdata.xml', 'AppRun']
                for name in names:
                    info = tarfile.TarInfo(name)
                    info.mode = 0o755 if name == 'AppRun' else 0o644
                    info.size = 3
                    archive.addfile(info, io.BytesIO(b'old'))
                link = tarfile.TarInfo('runtime-link')
                link.type = tarfile.SYMTYPE
                link.linkname = 'runtime-target'
                archive.addfile(link)
            (build / 'linux-runtime').write_bytes(b'ELF-test-runtime')
            def squash(*args, **kwargs):
                header = bytearray(96)
                header[:4] = b'hsqs'
                struct.pack_into('<H', header, 20, 6)
                (build / 'linux-new.sqfs').write_bytes(header)
            with patch.multiple(repack, BUILD=build, OUT=build), patch.object(repack.subprocess, 'run', side_effect=squash):
                repack.linux()
            with tarfile.open(build / 'linux-new.tar') as archive:
                for name in NEW_MODULES:
                    entry = 'usr/share/pylon/' + name
                    self.assertEqual(archive.extractfile(entry).read(), (ROOT / name).read_bytes())
                    self.assertEqual(archive.getmember(entry).mode, 0o644)
                self.assertEqual(archive.getmember('AppRun').mode, 0o755)
                self.assertEqual(archive.getmember('runtime-link').linkname, 'runtime-target')


if __name__ == '__main__':
    unittest.main()
