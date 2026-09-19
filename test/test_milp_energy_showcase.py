"""Receipt integrity, public routing, and isolation for the fifth build-agent app."""
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

from agilab.agent_runtime import milp_energy_showcase as showcase
from agilab.agent_runtime import notebook_showcase


def page():
    from agilab.agent_runtime.milp_energy_showcase import render
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
    assert report["source"]["license"] == "CC-BY-4.0"
    assert report["files"]["source/LICENSE"] == report["source"]["license_sha256"]
    assert "/Users/" not in json.dumps(report)
    assert "agent" not in report and "request" not in report
    with zipfile.ZipFile(io.BytesIO(showcase.download_bundle())) as archive:
        assert set(archive.namelist()) == showcase.PUBLIC_FILES | {"result.json"}
        for name, expected in report["files"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == expected


@pytest.mark.parametrize("name", ["app.py", "energy_runner.py", "energy_core.py", "agilab_pool.py", "source/original.ipynb", "source/LICENSE"])
def test_changed_artifacts_cannot_execute_or_download(bundle, name, monkeypatch):
    (bundle / name).write_text("raise AssertionError('must not execute')")
    monkeypatch.setattr(showcase, "_run_verified_app", lambda _: pytest.fail("Unverified app executed"))
    at = AppTest.from_function(page).run()
    assert not at.exception and at.error and not at.title
    with pytest.raises(ValueError, match="changed"):
        showcase.download_bundle()


@pytest.mark.parametrize("change", ["duration", "stages", "checks", "manifest", "engine", "license", "source_url", "extra"])
def test_incomplete_or_unverified_receipt_is_rejected(bundle, change):
    receipt = bundle / "result.json"
    report = json.loads(receipt.read_text())
    if change == "duration":
        report["seconds"] = float("nan")
    elif change == "stages":
        report["workflow_stages"] = True
    elif change == "checks":
        report["verification"]["milp_energy"]["checks"] = []
    elif change == "manifest":
        report["files"]["../secret"] = "0" * 64
    elif change == "engine":
        report["engine"]["sha256"] = "0" * 64
    elif change == "license":
        report["source"]["license"] = "MIT"
    elif change == "source_url":
        report["source"]["url"] = "https://example.com/unpinned-notebook"
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
    previous = {name: ModuleType(name) for name in ("agilab_pool", "energy_core", "energy_runner")}
    for name, module in previous.items():
        monkeypatch.setitem(sys.modules, name, module)
    payload = {f"{name}.py": b"" for name in previous}
    payload["app.py"] = b"raise RuntimeError('fixture failure')"
    with pytest.raises(RuntimeError, match="fixture failure"):
        showcase._run_verified_app(payload)
    assert all(sys.modules[name] is module for name, module in previous.items())
    assert showcase._APP_LOCK.acquire(blocking=False)
    showcase._APP_LOCK.release()


def test_fifth_demo_opens_without_running_a_benchmark():
    at = AppTest.from_file(notebook_showcase.__file__, default_timeout=30)
    at.query_params["demo"] = "milp"
    at.run()
    assert not at.exception and not at.error
    assert at.segmented_control(key="demo").value == "milp"
    assert any(title.value == "MILP Energy Lab" for title in at.title)
    assert sum(title.value == "Built by an autonomous agent" for title in at.title) == 1
    assert any(button.label == "Run analysis" for button in at.button)
    assert any(button.label == "Download the MILP energy lab and workflow" for button in at.get("download_button"))


def test_iris_only_distribution_reports_missing_fifth_demo(monkeypatch):
    monkeypatch.setitem(sys.modules, "agilab.agent_runtime.milp_energy_showcase", None)
    at = AppTest.from_file(notebook_showcase.__file__, default_timeout=30)
    at.query_params["demo"] = "milp"
    at.run()
    assert not at.exception
    assert at.error[0].value == "MILP energy lab unavailable in this distribution."


def test_export_rejects_a_modified_agent_artifact(tmp_path):
    import importlib.util

    script = Path(__file__).parents[1] / "tools/demos/export_milp_energy_demo.py"
    spec = importlib.util.spec_from_file_location("milp_energy_export_test", script)
    exporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exporter)
    project = tmp_path / "notebook_app_project"
    shutil.copytree(showcase.DEMO_ROOT, project, ignore=shutil.ignore_patterns("__pycache__"))
    report = showcase.load_report()
    (tmp_path / "result.json").write_text(json.dumps(report))
    (project / "energy_runner.py").write_text("tampered = True\n")
    with pytest.raises(ValueError, match="Autonomous-run artifact changed"):
        exporter.export_demo(tmp_path, tmp_path / "public")
    assert not (tmp_path / "public").exists()


@pytest.mark.parametrize("defect", ["balance", "integrality", "capacity", "startup", "objective", "solver"])
def test_independent_physical_check_rejects_invalid_solutions(defect):
    from tools.demos.export_milp_energy_demo import validate_physics

    result = {
        "status": "optimal", "modules": 30, "capacity_mw": 6000, "objective": 21879,
        "solver": {"name": "highs", "threads": 1},
        "settings": {"hours": 4, "max_modules": 50, "module_mw": 200, "demand_multiplier": 1,
                     "min_loading": 0.1, "solar_capacity": 0, "allow_shedding": False,
                     "investment_cost": 1, "marginal_cost": 1, "startup_cost": 0, "standby_cost": 1},
        "dispatch": [4000, 6000, 5000, 800], "active_modules": [20, 30, 25, 4],
        "solar": [0, 0, 0, 0], "shed": [0, 0, 0, 0],
        "startup": [20, 10, 0, 0], "shutdown": [0, 0, 5, 21],
    }
    validate_physics(result)
    if defect == "balance":
        result["dispatch"][0] -= 10
    elif defect == "integrality":
        result["active_modules"][0] += 0.1
    elif defect == "capacity":
        result["capacity_mw"] -= 200
    elif defect == "startup":
        result["startup"][0] = 0
    elif defect == "objective":
        result["objective"] += 10
    else:
        result["solver"]["threads"] = 2
    with pytest.raises(ValueError):
        validate_physics(result)
