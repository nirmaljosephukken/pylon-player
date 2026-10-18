"""Execute launcher selection with simulated macOS tools, not a Mac runtime."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which('bash') or str(ROOT.parent / 'Git/bin/bash.exe')


def shell_path(path):
    text = str(path).replace('\\', '/')
    return '/' + text[0].lower() + text[2:] if len(text) > 1 and text[1] == ':' else text


class MacLauncher(unittest.TestCase):
    def launch(self, hardware, process, vlc, missing=False):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            executable = folder / 'Pylon.app/Contents/MacOS/Pylon'
            executable.parent.mkdir(parents=True)
            resources = executable.parent.parent / 'Resources'
            for arch in ('arm64', 'x86_64'):
                python = resources / f'python-{arch}/bin/python3'
                python.parent.mkdir(parents=True)
                if not missing:
                    python.write_text('#!/bin/sh\nexit 0\n', newline='\n')
                    python.chmod(0o755)
            vlc_folder = folder / 'VLC.app'
            lib = vlc_folder / 'Contents/MacOS/lib/libvlc.dylib'
            lib.parent.mkdir(parents=True)
            lib.touch()
            # Replace only OS tools; execute the actual launcher's control flow.
            script = (ROOT / 'packaging/macos/Pylon-launcher.sh').read_text()
            script = script.replace('$(uname -m)', f'$(printf %s {process})')
            script = script.replace('/usr/sbin/sysctl -n hw.optional.arm64', f'printf %s {hardware}')
            script = script.replace('/usr/bin/file "$VLC_LIB"', f'printf %s {vlc}')
            shim = folder / 'arch'
            shim.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n', newline='\n')
            shim.chmod(0o755)
            script = script.replace('/usr/bin/arch', '"' + shell_path(shim) + '"')
            executable.write_bytes(script.encode())
            env = dict(os.environ, PYLON_VLC_DIR=shell_path(vlc_folder))
            return subprocess.run([BASH, shell_path(executable), 'movie with spaces.mkv'],
                                  env=env, text=True, capture_output=True, timeout=15)

    def test_rosetta_uses_arm_for_arm_vlc(self):
        result = self.launch('1', 'x86_64', 'arm64')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[0], '-arm64')
        self.assertIn('/python-arm64/bin/python3', result.stdout)
        self.assertEqual(result.stdout.splitlines()[-1], 'movie with spaces.mkv')

    def test_intel_vlc_on_apple_silicon(self):
        result = self.launch('1', 'arm64', 'x86_64')
        self.assertEqual(result.stdout.splitlines()[0], '-x86_64')

    def test_universal_vlc_prefers_native_arm(self):
        result = self.launch('1', 'x86_64', 'arm64 x86_64')
        self.assertEqual(result.stdout.splitlines()[0], '-arm64')

    def test_intel_mac(self):
        result = self.launch('0', 'x86_64', 'x86_64')
        self.assertEqual(result.stdout.splitlines()[0], '-x86_64')

    def test_missing_matching_interpreter_is_not_silent_fallback(self):
        result = self.launch('1', 'x86_64', 'arm64', missing=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('arm64 Python is missing', result.stderr)


if __name__ == '__main__':
    unittest.main()
