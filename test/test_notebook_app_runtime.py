import sys
from pathlib import Path
from types import ModuleType

import pytest

from agilab.agent_runtime.notebook_app_runtime import run_app


def test_each_project_gets_fresh_imports_and_its_own_directory(tmp_path):
    original = ModuleType("analysis")
    old = sys.modules.get("analysis")
    sys.modules["analysis"] = original
    cwd = Path.cwd()
    try:
        for value in (10, 20):
            project = tmp_path / str(value)
            project.mkdir()
            (project / "analysis.py").write_text(f"value = {value}\n")
            (project / "app.py").write_text("from analysis import value\nfrom pathlib import Path\nPath('rendered.txt').write_text(str(value))\n")
            run_app(project)
            assert (project / "rendered.txt").read_text() == str(value)
            assert sys.modules["analysis"] is original
            assert Path.cwd() == cwd
    finally:
        sys.modules.pop("analysis", None)
        if old is not None:
            sys.modules["analysis"] = old


def test_render_failure_restores_process_state(tmp_path):
    (tmp_path / "app.py").write_text("raise RuntimeError('app failed')")
    cwd, paths = Path.cwd(), sys.path[:]
    with pytest.raises(RuntimeError, match="app failed"):
        run_app(tmp_path)
    assert Path.cwd() == cwd
    assert sys.path == paths
