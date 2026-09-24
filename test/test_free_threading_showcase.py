"""Receipt integrity, public routing, and isolation for the fourth build-agent app."""
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import tomllib
from types import ModuleType
import zipfile

import pytest
from streamlit.testing.v1 import AppTest

from agilab.demos import free_threading_showcase as showcase
from agilab.demos import notebook_showcase


def page():
    from agilab.demos.free_threading_showcase import render
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
    assert type(report["workflow_stages"]) is int and report["workflow_stages"] > 0
    stages = tomllib.loads((showcase.DEMO_ROOT / "lab_stages.toml").read_text())
    assert report["workflow_stages"] == len(stages["notebook_app_project"])
    workflow = report["verification"]["workflow"]
    assert workflow["status"] == "passed"
    assert workflow["stage_count"] == report["workflow_stages"]
    assert workflow["result_sha256"] == report["verification"]["result_sha256"]
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
    monkeypatch.setitem(sys.modules, "agilab.demos.free_threading_showcase", None)
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


@pytest.mark.parametrize("record_model", [False, True])
def test_build_model_visible_and_legacy_receipts_supported(bundle, monkeypatch, record_model):
    receipt = bundle / "result.json"
    report = json.loads(receipt.read_text())
    if record_model:
        report["build_model"] = {
            "id": "ddalcu/Qwen3.8-27B-MLX-Serve-4bit",
            "provider": "mlx-serve", "execution": "local",
        }
    else:
        report.pop("build_model", None)
    receipt.write_text(json.dumps(report))
    monkeypatch.setattr(showcase, "_run_verified_app", lambda _: None)
    at = AppTest.from_function(page).run()
    assert not at.exception and not at.error
    labels = [caption.value for caption in at.caption if "Build model:" in caption.value]
    assert bool(labels) is record_model
    if record_model:
        assert report["build_model"]["id"] in labels[0]


@pytest.mark.parametrize("model", [None, [], {}, {"id": "", "provider": "mlx", "execution": "local"}])
def test_invalid_build_model_cannot_execute(bundle, monkeypatch, model):
    receipt = bundle / "result.json"
    report = json.loads(receipt.read_text())
    report["build_model"] = model
    receipt.write_text(json.dumps(report))
    monkeypatch.setattr(showcase, "_run_verified_app", lambda _: pytest.fail("Invalid receipt executed"))
    at = AppTest.from_function(page).run()
    assert not at.exception and at.error and not at.title
    with pytest.raises(ValueError, match="build model"):
        showcase.download_bundle()


@pytest.mark.parametrize("record_model", [False, True])
def test_export_allows_only_public_model_metadata(bundle, tmp_path, monkeypatch, record_model):
    from tools.demos import export_free_threading_demo as exporter
    run = tmp_path / "finished-run"
    run.mkdir()
    shutil.copytree(bundle, run / "notebook_app_project")
    report = json.loads((bundle / "result.json").read_text())
    if record_model:
        report["build_model"] = {
            "id": "ddalcu/Qwen3.8-27B-MLX-Serve-4bit", "provider": "mlx-serve",
            "execution": "local", "revision": "b" * 40, "cloud_codegen_fallback": False,
            "tokki_agent_offload": False, "private_endpoint": "must-never-be-public",
        }
    else:
        report.pop("build_model", None)
    (run / "result.json").write_text(json.dumps(report))
    monkeypatch.setattr(exporter, "validate_analysis", lambda _: {"status": "passed", "checks": ["fixture"]})
    destination = tmp_path / "public-export"
    exported = exporter.export_demo(run, destination)
    assert ("build_model" in exported) is record_model
    if record_model:
        assert exported["build_model"]["id"] == report["build_model"]["id"]
        assert exported["build_model"]["cloud_codegen_fallback"] is False
        assert "private_endpoint" not in exported["build_model"]
    monkeypatch.setattr(showcase, "DEMO_ROOT", destination)
    assert showcase.load_report()["status"] == "passed"


@pytest.mark.parametrize("model", [
    None, {}, {"id": "qwen", "provider": "mlx", "execution": "local", "cloud_codegen_fallback": "false"},
])
def test_export_rejects_invalid_model_without_publishing(bundle, tmp_path, monkeypatch, model):
    from tools.demos import export_free_threading_demo as exporter
    run = tmp_path / "finished-run"
    run.mkdir()
    shutil.copytree(bundle, run / "notebook_app_project")
    report = json.loads((bundle / "result.json").read_text())
    report["build_model"] = model
    (run / "result.json").write_text(json.dumps(report))
    monkeypatch.setattr(exporter, "validate_analysis", lambda _: {"status": "passed", "checks": ["fixture"]})
    destination = tmp_path / "public-export"
    with pytest.raises(ValueError, match="build model"):
        exporter.export_demo(run, destination)
    assert not destination.exists()


def test_generated_benchmark_state_is_scoped_and_persists(monkeypatch):
    state = {"benchmark_result": {"owner": "other-app"}, "benchmark_signature": "other"}
    monkeypatch.setattr(showcase.st, "session_state", state)
    payload = {f"{name}.py": b"" for name in ("agilab_pool", "free_threading_core", "benchmark")}
    payload["app.py"] = (
        b"import streamlit as st\n"
        b"old = st.session_state.get('benchmark_result', {}).get('runs', 0)\n"
        b"st.session_state['benchmark_result'] = {'runs': old + 1}\n"
        b"st.session_state['benchmark_signature'] = 'threading'\n"
    )
    showcase._run_verified_app(payload)
    showcase._run_verified_app(payload)
    assert state["benchmark_result"] == {"owner": "other-app"}
    assert state["benchmark_signature"] == "other"
    assert state["_agilab_notebook_threading_state"]["benchmark_result"] == {"runs": 2}


def test_busy_demo_can_retry_after_other_session_releases_lock():
    from threading import Event, Thread

    ready, release = Event(), Event()

    def hold_execution_lock():
        with showcase._APP_LOCK:
            ready.set()
            release.wait(timeout=30)

    holder = Thread(target=hold_execution_lock)
    holder.start()
    try:
        assert ready.wait(timeout=5)
        at = AppTest.from_function(page, default_timeout=30).run()
        assert not at.exception
        assert any("Another notebook demo session" in info.value for info in at.info)
        assert at.button(key="threading_retry").label == "Retry demo"
    finally:
        release.set()
        holder.join(timeout=5)
    assert not holder.is_alive()
    at.button(key="threading_retry").click().run()
    assert not at.exception and not at.error
    assert any(title.value == "Free-threading lab" for title in at.title)
    assert any(button.label == "Run analysis" for button in at.button)
    assert not any("Another notebook demo session" in info.value for info in at.info)


def test_benchmark_requires_explicit_action_and_reports_runner_failure(monkeypatch):
    calls = []
    fake = ModuleType("benchmark")
    fake.effective_cpus = lambda: {"effective_cpus": 1}

    def unavailable(**parameters):
        calls.append(parameters)
        raise RuntimeError("fixture interpreter unavailable")

    fake.run_benchmark = unavailable
    monkeypatch.setitem(sys.modules, "benchmark", fake)
    monkeypatch.syspath_prepend(str(showcase.DEMO_ROOT))
    at = AppTest.from_file(str(showcase.DEMO_ROOT / "app.py"), default_timeout=30).run()
    assert not at.exception and not calls
    assert not any(button.label == "Run benchmark" for button in at.button)
    next(button for button in at.button if button.label == "Run analysis").click().run()
    assert not at.exception and not calls
    next(button for button in at.button if button.label == "Run benchmark").click().run()
    assert not at.exception and len(calls) == 1
    assert calls[0]["workers"] == 1
    assert any("fixture interpreter unavailable" in error.value for error in at.error)
    at.run()
    assert not at.exception and len(calls) == 1
