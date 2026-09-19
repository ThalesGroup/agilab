"""Receipt integrity, public routing, and isolation for the fourth build-agent app."""
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
from types import ModuleType
import zipfile

import pytest
from streamlit.testing.v1 import AppTest

from agilab.agent_runtime import free_threading_showcase as showcase
from agilab.agent_runtime import notebook_showcase


def page():
    from agilab.agent_runtime.free_threading_showcase import render
    render()


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    destination = tmp_path / "bundle"
    shutil.copytree(showcase.DEMO_ROOT, destination, ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setattr(showcase, "DEMO_ROOT", destination)
    return destination


def test_bundle_matches_build_receipt_and_download():
    report = showcase.load_report()
    assert report["status"] == "passed" and report["seconds"] > 0
    assert report["workflow_stages"] >= 3
    assert report["files"]["agilab_pool.py"] == report["engine"]["sha256"]
    assert "/Users/" not in json.dumps(report)
    assert "agent" not in report and "request" not in report
    with zipfile.ZipFile(io.BytesIO(showcase.download_bundle())) as archive:
        assert set(archive.namelist()) == showcase.PUBLIC_FILES | {"result.json"}
        for name, expected in report["files"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == expected


@pytest.mark.parametrize("name", ["app.py", "benchmark.py", "free_threading_core.py", "agilab_pool.py", "source/original.ipynb"])
def test_changed_artifacts_cannot_execute_or_download(bundle, name, monkeypatch):
    (bundle / name).write_text("raise AssertionError('must not execute')")
    monkeypatch.setattr(showcase, "_run_verified_app", lambda _: pytest.fail("Unverified app executed"))
    at = AppTest.from_function(page).run()
    assert not at.exception and at.error and not at.title
    with pytest.raises(ValueError, match="changed"):
        showcase.download_bundle()


@pytest.mark.parametrize("change", ["duration", "stages", "checks", "manifest", "engine", "extra"])
def test_incomplete_or_unverified_receipt_is_rejected(bundle, change):
    receipt = bundle / "result.json"
    report = json.loads(receipt.read_text())
    if change == "duration":
        report["seconds"] = float("nan")
    elif change == "stages":
        report["workflow_stages"] = True
    elif change == "checks":
        report["verification"]["free_threading"]["checks"] = []
    elif change == "manifest":
        report["files"]["../secret"] = "0" * 64
    elif change == "engine":
        report["engine"]["sha256"] = "0" * 64
    else:
        (bundle / "unverified.py").write_text("unverified = True\n")
    receipt.write_text(json.dumps(report))
    with pytest.raises(ValueError):
        showcase.download_bundle()


def test_symlinked_source_is_rejected(bundle):
    original = bundle / "source/original.ipynb"
    target = bundle.parent / "outside.ipynb"
    original.rename(target)
    original.symlink_to(target)
    with pytest.raises(ValueError, match="Symlinked"):
        showcase.load_report()


def test_import_state_and_lock_are_restored_after_app_error(monkeypatch):
    previous = {name: ModuleType(name) for name in ("agilab_pool", "free_threading_core", "benchmark")}
    for name, module in previous.items():
        monkeypatch.setitem(sys.modules, name, module)
    payload = {f"{name}.py": b"" for name in previous}
    payload["app.py"] = b"raise RuntimeError('fixture failure')"
    with pytest.raises(RuntimeError, match="fixture failure"):
        showcase._run_verified_app(payload)
    assert all(sys.modules[name] is module for name, module in previous.items())
    assert showcase._APP_LOCK.acquire(blocking=False)
    showcase._APP_LOCK.release()


def test_fourth_demo_opens_without_running_a_benchmark():
    at = AppTest.from_file(notebook_showcase.__file__, default_timeout=30)
    at.query_params["demo"] = "threading"
    at.run()
    assert not at.exception and not at.error
    assert at.segmented_control(key="demo").value == "threading"
    assert any(title.value == "Free-threading lab" for title in at.title)
    assert sum(title.value == "Built by an autonomous agent" for title in at.title) == 1
    assert any(button.label == "Run analysis" for button in at.button)
    assert any(button.label == "Download the free-threading app and workflow" for button in at.get("download_button"))


def test_iris_only_distribution_reports_missing_fourth_demo(monkeypatch):
    monkeypatch.setitem(sys.modules, "agilab.agent_runtime.free_threading_showcase", None)
    at = AppTest.from_file(notebook_showcase.__file__, default_timeout=30)
    at.query_params["demo"] = "threading"
    at.run()
    assert not at.exception
    assert at.error[0].value == "Free-threading demo unavailable in this distribution."


def test_export_rejects_a_modified_agent_artifact(tmp_path):
    import importlib.util

    script = Path(__file__).parents[1] / "tools/demos/export_free_threading_demo.py"
    spec = importlib.util.spec_from_file_location("free_threading_export_test", script)
    exporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exporter)
    project = tmp_path / "notebook_app_project"
    shutil.copytree(showcase.DEMO_ROOT, project, ignore=shutil.ignore_patterns("__pycache__"))
    report = showcase.load_report()
    (tmp_path / "result.json").write_text(json.dumps(report))
    (project / "benchmark.py").write_text("tampered = True\n")
    with pytest.raises(ValueError, match="Autonomous-run artifact changed"):
        exporter.export_demo(tmp_path, tmp_path / "public")
    assert not (tmp_path / "public").exists()
