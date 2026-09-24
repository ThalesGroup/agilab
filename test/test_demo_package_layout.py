"""Moving demos must preserve process isolation and existing launch contracts."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
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


def test_built_wheel_preserves_every_registered_demo_and_resource(tmp_path):
    # Copy tracked working-tree inputs: builds must not modify the checkout or
    # pick up ignored app installs, caches, and previous build products.
    source = tmp_path / "source"
    source.mkdir()
    tracked = subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=ROOT, text=True
    ).split("\0")
    for name in filter(None, tracked):
        origin = ROOT / name
        if origin.is_file():
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, target, follow_symlinks=False)

    dist = tmp_path / "dist"
    built = subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--no-isolation",
            "--outdir",
            str(dist),
        ],
        cwd=source,
        capture_output=True,
        text=True,
        timeout=120,
    )
    (tmp_path / "build.log").write_text(built.stdout + built.stderr, encoding="utf-8")
    assert built.returncode == 0, (built.stdout + built.stderr)[-6000:]
    (wheel,) = dist.glob("*.whl")
    extracted = tmp_path / "installed"
    resources = source / "src/agilab/demos/resources"
    expected = {
        path.relative_to(source / "src").as_posix(): path.read_bytes()
        for path in resources.rglob("*")
        if path.is_file()
    }
    assert expected
    with zipfile.ZipFile(wheel) as archive:
        missing = expected.keys() - set(archive.namelist())
        assert not missing, f"Demo resources missing from wheel: {sorted(missing)}"
        for name, content in expected.items():
            assert archive.read(name) == content, (
                f"Demo resource changed in wheel: {name}"
            )
        archive.extractall(extracted)

    # Import in a fresh process outside the checkout and call the same receipt
    # and artifact-hash validators used by each installed gallery variant.
    code = """
import importlib
import json
from pathlib import Path
import sys

installed = Path(sys.argv[1])
sys.path.insert(0, str(installed))
from agilab.demos import notebook_showcase as gallery
assert Path(gallery.__file__).is_relative_to(installed)
modules = {"text": "text", "forecast": "forecast",
           "threading": "free_threading", "milp": "milp_energy"}
validated = []
for variant in gallery.DEMO_LABELS:
    family, _, flavor = variant.partition("_")
    if family == "iris":
        root = {"": gallery.DEMO_ROOT, "local": gallery.LOCAL_DEMO_ROOT,
                "rtx": gallery.RTX_DEMO_ROOT}[flavor]
        report, payload = gallery._read_verified_bundle(root)
    else:
        module = importlib.import_module("agilab.demos." + modules[family] + "_showcase")
        assert Path(module.__file__).is_relative_to(installed)
        assert flavor in {"", "astra", "rtx"}, variant
        report, payload = module._read_verified_bundle(
            astra=flavor == "astra", rtx=flavor == "rtx")
    assert report["status"] == "passed", variant
    assert "result.json" in payload, variant
    validated.append(variant)
print(json.dumps(validated))
"""
    checked = subprocess.run(
        [sys.executable, "-c", code, str(extracted)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert set(json.loads(checked.stdout)) == set(notebook_showcase.DEMO_LABELS)
