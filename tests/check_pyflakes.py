"""Keeps the code free of unused imports, unused variables and undefined names.

Uses pyflakes when it is installed (pip install pyflakes). Pylon's bundled Python doesn't have it, so
there a smaller built-in check runs instead: every file must compile and every import must be used."""
import ast
import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = sorted([ROOT / "main.py", *(ROOT / "app").glob("*.py"), *(ROOT / "tests").glob("*.py"),
                *(ROOT / "packaging").glob("*.py")])


def unused_imports(path: Path) -> list[str]:
    """Module-level imports whose name is never used in the file (a line with "noqa" is allowed)."""
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, str(path))
    lines = src.splitlines()
    imported = {}
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)) and "noqa" not in lines[node.end_lineno - 1]:
            for a in node.names:
                name = a.asname or a.name.split(".")[0]
                if name != "*":
                    imported[name] = node.lineno
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    exported = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "__all__" for t in node.targets):
            exported = {e.value for e in ast.walk(node.value) if isinstance(e, ast.Constant)}
    return [f"{path.relative_to(ROOT)}:{line}: '{name}' imported but unused"
            for name, line in imported.items() if name not in used and name not in exported]


class Pyflakes(unittest.TestCase):
    def test_clean(self):
        if importlib.util.find_spec("pyflakes") is None:
            problems = []
            for f in FILES:
                compile(f.read_text(encoding="utf-8"), str(f), "exec")
                problems += unused_imports(f)
            self.assertEqual(problems, [], "\n".join(problems))
            return
        out = subprocess.run([sys.executable, "-m", "pyflakes", *map(str, FILES)],
                             capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)


if __name__ == "__main__":
    unittest.main()
