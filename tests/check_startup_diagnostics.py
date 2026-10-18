"""Early diagnostics work without Qt and preserve normal error reporting."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class StartupDiagnostics(unittest.TestCase):
    def test_logs_before_qt_and_keeps_tracebacks(self):
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, APPDATA=directory, XDG_DATA_HOME=directory, HOME=directory)
            code = """
import sys, faulthandler
from app import startup
startup.install()
assert not any(name.startswith('PySide6') for name in sys.modules)
assert faulthandler.is_enabled()
startup.mark('before Qt: test marker')
faulthandler.dump_traceback(file=startup._log)
raise RuntimeError('diagnostic test error')
"""
            result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env,
                                    text=True, capture_output=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('diagnostic test error', result.stderr)
            logs = list(Path(directory).rglob('startup.log'))
            self.assertEqual(len(logs), 1)
            text = logs[0].read_text()
            self.assertIn('before Qt: test marker', text)
            self.assertIn('diagnostic test error', text)
            self.assertIn('Interpreter:', text)
            self.assertIn('most recent call first', text)


if __name__ == '__main__':
    unittest.main()
