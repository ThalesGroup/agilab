"""Exercise the declared agi-web coverage imports without ambient source paths."""

from __future__ import annotations

import json
from pathlib import Path
import shlex
import subprocess
import sys
import tomllib

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/coverage.yml"


def test_agi_web_coverage_environment_resolves_native_file_picker(tmp_path: Path) -> None:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["agi-web"]["steps"]
    coverage_step = next(step for step in steps if step["name"] == "Run agi-web coverage")
    command = str(coverage_step["run"])
    start = command.index("COVERAGE_FILE=.coverage.agi-web uv run")
    argv = shlex.split(command[start:].replace("\\\n", ""))
    assert "--no-project" in argv

    source_paths = []
    for index, arg in enumerate(argv[:-1]):
        if arg != "--with-editable":
            continue
        project_path = REPO_ROOT / argv[index + 1].split("[", 1)[0]
        metadata = tomllib.loads((project_path / "pyproject.toml").read_text(encoding="utf-8"))
        package_dir = metadata["tool"]["setuptools"]["package-dir"][""]
        source_paths.append(str(project_path / package_dir))

    # -I -S removes the repository, PYTHONPATH and installed packages. Only the
    # editable packages actually requested by this job are made importable.
    script = """
import json
import sys
sys.path.extend(json.loads(sys.argv[1]))
from agi_gui.file_picker import agi_file_picker
from agi_web import python_ui
assert callable(agi_file_picker)
assert callable(python_ui.text_input)
"""
    completed = subprocess.run(
        [sys.executable, "-I", "-S", "-c", script, json.dumps(source_paths)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr

    # Prove this guard cannot be satisfied by agi_gui already installed in the
    # maintainer environment or by the root pytest pythonpath configuration.
    without_helpers = [path for path in source_paths if Path(path).parent.name != "agi-gui"]
    missing = subprocess.run(
        [sys.executable, "-I", "-S", "-c", script, json.dumps(without_helpers)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing.returncode != 0
    assert "No module named 'agi_gui'" in missing.stderr
