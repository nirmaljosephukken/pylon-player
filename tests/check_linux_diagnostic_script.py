"""Check diagnostic extraction and exit propagation using a fake AppImage."""
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


class LinuxDiagnosticScript(unittest.TestCase):
    def test_extracted_startup_preserves_success_and_crash_exit(self):
        for status in (0, 139):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                image = root / 'Pylon test.AppImage'
                # Simulate extraction, then verify the launcher's diagnostic env.
                image.write_text("""#!/bin/bash
test "$1" = '--appimage-extract' || exit 2
mkdir -p squashfs-root
cat > squashfs-root/AppRun <<'APP'
#!/bin/bash
test "$PYTHONFAULTHANDLER" = 1 || exit 3
test "$QT_DEBUG_PLUGINS" = 1 || exit 4
echo 'simulated player startup'
exit STATUS
APP
chmod +x squashfs-root/AppRun
""".replace('STATUS', str(status)), newline='\n')
                image.chmod(0o755)
                env = dict(os.environ, TMPDIR=shell_path(root))
                result = subprocess.run([BASH, shell_path(ROOT / 'packaging/linux/diagnose-startup.sh'),
                                         shell_path(image)], env=env, text=True, capture_output=True, timeout=15)
                self.assertEqual(result.returncode, status, result.stderr + result.stdout)
                reports = list(root.glob('pylon-startup-*'))
                self.assertEqual(len(reports), 1)
                self.assertIn('simulated player startup', (reports[0] / 'startup-console.txt').read_text())
                self.assertIn(f'Exit status: {status}', (reports[0] / 'exit-status.txt').read_text())
                self.assertTrue((reports[0] / 'system.txt').is_file())


if __name__ == '__main__':
    unittest.main()
