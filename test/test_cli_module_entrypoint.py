"""Exercise the documented module entrypoint without an installed UI stack."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (("--help",), "--no-browser"),
        (("first-proof", "--help"), "--dry-run"),
        (("--version",), "agilab "),
    ],
)
def test_module_cli_works_without_ui_dependencies(tmp_path, arguments, expected):
    (tmp_path / "sitecustomize.py").write_text(
        "import importlib.abc\n"
        "import sys\n"
        "class BlockUI(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, fullname, path=None, target=None):\n"
        "        if fullname.split('.')[0] in {'streamlit', 'agi_web'}:\n"
        "            raise ModuleNotFoundError('UI dependency is unavailable: ' + fullname)\n"
        "sys.meta_path.insert(0, BlockUI())\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(tmp_path), str(ROOT / "src")))
    result = subprocess.run(
        [sys.executable, "-m", "agilab", *arguments],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert expected in result.stdout
