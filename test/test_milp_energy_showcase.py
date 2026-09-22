"""Receipt integrity, public routing, and isolation for the fifth build-agent app."""
import hashlib
import io
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
from types import ModuleType
import zipfile

import pytest
from streamlit.testing.v1 import AppTest

from agilab.demos import milp_energy_showcase as showcase
from agilab.demos import notebook_showcase


def page():
    from agilab.demos.milp_energy_showcase import render
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
    assert report["source"]["license"] == "CC-BY-4.0"
    assert report["files"]["source/LICENSE"] == report["source"]["license_sha256"]
    assert "/Users/" not in json.dumps(report)
    assert "agent" not in report and "request" not in report
    with zipfile.ZipFile(io.BytesIO(showcase.download_bundle())) as archive:
        assert set(archive.namelist()) == showcase.PUBLIC_FILES | {"result.json"}
        for name, expected in report["files"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == expected


@pytest.mark.parametrize("name", ["app.py", "energy_runner.py", "energy_core.py", "agilab_pool.py", "source/original.ipynb", "source/LICENSE", "source/provenance.json"])
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
    monkeypatch.setitem(sys.modules, "agilab.demos.milp_energy_showcase", None)
    at = AppTest.from_file(notebook_showcase.__file__, default_timeout=30)
    at.query_params["demo"] = "milp"
    at.run()
    assert not at.exception
    assert at.error[0].value == "MILP energy lab unavailable in this distribution."


@pytest.mark.skipif(sys.platform == "win32", reason="The MILP replay runner targets POSIX")
def test_downloaded_milp_suite_can_verify_its_original_source(tmp_path):
    with zipfile.ZipFile(io.BytesIO(showcase.download_bundle())) as archive:
        archive.extractall(tmp_path)
    checked = subprocess.run(
        [sys.executable, "-B", str(tmp_path / "tests.py"), "Boundaries.test_source_integrity"],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr


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


@pytest.mark.parametrize("post_hoc_charges", [False, True])
def test_startup_costs_change_the_optimal_schedule(post_hoc_charges):
    from tools.demos.export_milp_energy_demo import validate_physics, validate_startup_optimum

    active = [20, 30, 25, 4] * 3 if post_hoc_charges else [20] + [30] * 9 + [25, 4]
    previous = [0] + active[:-1]
    starts = [max(0, a - b) for a, b in zip(active, previous)]
    result = {
        "status": "optimal", "modules": 30, "capacity_mw": 6000,
        "objective": 47400 + 6000 + 500 * sum(starts) + sum(active),
        "solver": {"name": "highs", "threads": 1},
        "settings": {"hours": 12, "max_modules": 50, "module_mw": 200, "demand_multiplier": 1,
                     "min_loading": 0.1, "solar_capacity": 0, "allow_shedding": False,
                     "investment_cost": 1, "marginal_cost": 1, "startup_cost": 500, "standby_cost": 1},
        "dispatch": [4000, 6000, 5000, 800] * 3, "active_modules": active,
        "solar": [0] * 12, "shed": [0] * 12, "startup": starts,
        "shutdown": [max(0, b - a) for a, b in zip(active, previous)],
    }
    # Both schedules have valid physics and accurately reconstructed costs.
    validate_physics(result)
    if post_hoc_charges:
        with pytest.raises(ValueError, match="Startup costs must affect"):
            validate_startup_optimum(result)
    else:
        validate_startup_optimum(result)
        result["settings"]["startup_cost"] = 0
        with pytest.raises(ValueError, match="settings changed"):
            validate_startup_optimum(result)


@pytest.fixture
def lab_controls(monkeypatch):
    """Exercise the sealed UI at deterministic solver boundaries."""
    for name in ("agilab_pool", "energy_core"):
        spec = importlib.util.spec_from_file_location(name, showcase.DEMO_ROOT / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
    core = sys.modules["energy_core"]
    monkeypatch.setattr(core, "cpu_limits", lambda: {"effective_cpus": 2, "observed_caps": [2]})
    runner = ModuleType("energy_runner")
    calls = []

    def unexpected_solve(*args, **kwargs):
        raise AssertionError("Saving, clearing and rendering must not solve a scenario")

    def bounded_failure(batch, workers):
        calls.append((batch, workers))
        raise TimeoutError("Fixture worker deadline reached")

    runner.run_scenario = unexpected_solve
    runner.run_benchmark = bounded_failure
    monkeypatch.setitem(sys.modules, "energy_runner", runner)
    return core, calls


def _unsolved_fixture(settings):
    return {
        "settings": settings, "status": "infeasible", "objective": None,
        "modules": None, "capacity_mw": None, "dispatch": [], "active_modules": [],
        "solar": [], "shed": [], "startup": [], "shutdown": [],
        "demand": [4000, 6000, 5000, 800], "solar_available": [0] * 4,
        "solver": {"name": "highs", "threads": 1, "incumbent": False},
    }


def test_milp_save_and_clear_keep_solved_inputs(lab_controls):
    core, calls = lab_controls
    at = AppTest.from_file(str(showcase.DEMO_ROOT / "app.py")).run()
    assert not at.exception and not any(b.label == "Keep scenario" for b in at.button)
    settings = core.default_settings() | {"max_modules": 20}
    at.session_state["analysis"] = _unsolved_fixture(settings)
    at.run()
    assert not at.exception
    at.button(key="milp_keep").click().run()
    saved = at.session_state["comparisons"]
    assert len(saved) == 1 and saved[0]["settings"]["max_modules"] == 20
    assert saved[0] is not at.session_state["analysis"]
    assert saved[0]["settings"] is not at.session_state["analysis"]["settings"]
    for _ in range(10):
        at.button(key="milp_keep").click().run()
    assert len(at.session_state["comparisons"]) == 10
    assert any("Comparison limit" in item.value for item in at.warning)
    at.button(key="milp_clear_cmp").click().run()
    assert not at.exception and at.session_state["comparisons"] == []
    assert at.session_state["analysis"]["settings"]["max_modules"] == 20
    assert calls == []


@pytest.mark.parametrize("cpus", [1, 2])
def test_milp_scaling_dispatch_and_cpu_gate(lab_controls, monkeypatch, cpus):
    core, calls = lab_controls
    monkeypatch.setattr(core, "cpu_limits", lambda: {"effective_cpus": cpus, "observed_caps": [cpus]})
    at = AppTest.from_file(str(showcase.DEMO_ROOT / "app.py")).run()
    assert not at.exception and calls == []
    assert not any(b.label == "Run benchmark" for b in at.button)
    assert [int(v) for v in at.selectbox(key="milp_workers").options] == list(range(1, cpus + 1))
    settings = core.default_settings() | {"max_modules": 20}
    at.session_state["analysis"] = _unsolved_fixture(settings)
    at.run()
    at.selectbox(key="milp_workers").set_value(cpus).run()
    at.button(key="milp_run_bench").click().run()
    assert not at.exception
    assert len(calls) == 1 and len(calls[0][0]) == 4 and calls[0][1] == cpus
    assert all(case["max_modules"] == 20 for case in calls[0][0])
    assert any("Fixture worker deadline reached" in item.value for item in at.error)
    at.run()
    assert not at.exception and len(calls) == 1


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
    from tools.demos import export_milp_energy_demo as exporter
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
    from tools.demos import export_milp_energy_demo as exporter
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


def test_generated_milp_state_is_scoped_and_persists(monkeypatch):
    state = {"analysis": {"owner": "other-app"}, "comparisons": ["other"], "benchmark_result": {"owner": "other-app"}}
    monkeypatch.setattr(showcase.st, "session_state", state)
    payload = {f"{name}.py": b"" for name in ("agilab_pool", "energy_core", "energy_runner")}
    payload["app.py"] = (
        b"import streamlit as st\n"
        b"old = st.session_state.get('benchmark_result', {}).get('runs', 0)\n"
        b"st.session_state['analysis'] = {'owner': 'milp'}\n"
        b"st.session_state['comparisons'] = ['milp']\n"
        b"st.session_state['benchmark_result'] = {'runs': old + 1}\n"
        b"st.session_state['benchmark_signature'] = 'milp'\n"
    )
    showcase._run_verified_app(payload)
    showcase._run_verified_app(payload)
    assert state["analysis"] == {"owner": "other-app"}
    assert state["comparisons"] == ["other"]
    assert state["benchmark_result"] == {"owner": "other-app"}
    assert state["_agilab_notebook_milp_state"]["benchmark_result"] == {"runs": 2}
    assert state["_agilab_notebook_milp_state"]["comparisons"] == ["milp"]
