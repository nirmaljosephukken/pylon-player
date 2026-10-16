"""Reject a filesystem the bundled AppImage runtime cannot mount."""
import importlib.util
import struct
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('repack', Path(__file__).resolve().parents[1] / 'packaging/repack_release.py')
repack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repack)


class Compression(unittest.TestCase):
    def test_runtime_compatibility(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'filesystem.sqfs'
            for compressor in (1, 2, 3, 4, 5, 6):
                header = bytearray(96)
                header[:4] = b'hsqs'
                struct.pack_into('<H', header, 20, compressor)
                path.write_bytes(header)
                if compressor in (1, 6):
                    repack.validate_squashfs(path)
                else:
                    with self.assertRaisesRegex(ValueError, 'unsupported'):
                        repack.validate_squashfs(path)
            path.write_bytes(b'hsqs')
            with self.assertRaisesRegex(ValueError, 'Invalid'):
                repack.validate_squashfs(path)


if __name__ == '__main__':
    unittest.main()
