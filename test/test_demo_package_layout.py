"""Moving demos must preserve process isolation and existing launch contracts."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from agilab.demos import notebook_showcase

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("legacy_first", [True, False])
def test_demo_import_paths_share_one_runtime_in_a_fresh_process(legacy_first, tmp_path):
    code = f"""
import importlib
from pathlib import Path
import sys
sys.path.insert(0, {str(ROOT / "src")!r})
prefixes = ["agilab.agent_runtime", "agilab.demos"]
if not {legacy_first!r}:
    prefixes.reverse()
for name in ("notebook_app_runtime", "notebook_demo_evidence", "notebook_demo_ui",
             "notebook_showcase", "forecast_showcase", "text_showcase",
             "free_threading_showcase", "milp_energy_showcase"):
    first, second = [importlib.import_module(prefix + "." + name) for prefix in prefixes]
    if name == "notebook_app_runtime":
        lock = first.APP_EXECUTION_LOCK
        assert lock is second.APP_EXECUTION_LOCK
        assert first.run_app is second.run_app
    elif name.endswith("_showcase"):
        assert first._APP_LOCK is second._APP_LOCK is lock
        assert first.render is second.render
        first._layout_probe = object()
        assert first._layout_probe is second._layout_probe
        assert first.DEMO_ROOT.is_relative_to(Path({str(ROOT / "src/agilab/demos/resources")!r}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("entrypoint", ["notebook_showcase", "notebook_demo_ui"])
def test_legacy_streamlit_paths_still_render_once(entrypoint):
    app = ROOT / "src/agilab/agent_runtime" / f"{entrypoint}.py"
    at = AppTest.from_file(str(app), default_timeout=60).run()
    assert not at.exception and not at.error
    if entrypoint == "notebook_showcase":
        assert sum(title.value == "Iris decision lab" for title in at.title) == 1
        assert len(at.segmented_control) == 1
    else:
        assert sum(button.label == "Build my app" for button in at.button) == 1
        assert "run_root" not in at.session_state


def test_relocated_gallery_keeps_the_packaged_verifier_path(monkeypatch):
    calls = []

    def verify(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout='{"status": "passed"}\n')

    monkeypatch.setattr(notebook_showcase.subprocess, "run", verify)
    at = AppTest.from_file(notebook_showcase.__file__, default_timeout=60).run()
    next(
        button for button in at.button if button.label == "Run model and app checks"
    ).click().run()
    assert not at.exception and not at.error
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert Path(command[1]) == ROOT / "src/agilab/agent_runtime/notebook_verifier.py"
    assert Path(command[1]).is_file()
    assert kwargs["cwd"] == notebook_showcase.DEMO_ROOT
    assert any("checks passed" in message.value for message in at.success)
