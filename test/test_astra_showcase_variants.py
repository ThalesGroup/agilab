"""Preserve the original app flavours, their receipts, and independent state."""
import hashlib
import importlib
import importlib.util
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

VARIANTS = [
    ("text", "text", "analysis_result", "20260919T144017Z-27f16038"),
    ("forecast", "forecast", "analysis", "20260918T201601Z-112cb07a"),
    ("free_threading", "threading", "analysis", "20260919T183137Z-c43b4d97"),
    ("milp_energy", "milp", "milp_energy_saved", "20260919T201404Z-d7538b18"),
]


@pytest.mark.parametrize("module_name,route,state_key,run_id", VARIANTS)
def test_astra_download_preserves_original_receipt_and_distinct_build(module_name, route, state_key, run_id):
    module = importlib.import_module(f"agilab.agent_runtime.{module_name}_showcase")
    astra, qwen = module.load_report(astra=True), module.load_report()
    assert astra["run_id"] == run_id and qwen["run_id"] != run_id
    assert "build_model" not in astra
    assert qwen["build_model"]["execution"] == "local"
    assert astra["files"]["app.py"] != qwen["files"]["app.py"]
    with zipfile.ZipFile(io.BytesIO(module.download_bundle(astra=True))) as archive:
        assert archive.read("result.json") == (module.ASTRA_DEMO_ROOT / "result.json").read_bytes()
        assert set(archive.namelist()) == set(astra["files"]) | {"result.json"}
        for name, digest in astra["files"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest


@pytest.mark.parametrize("module_name,route,state_key,run_id", VARIANTS)
def test_changed_astra_cannot_execute_or_download(module_name, route, state_key, run_id, monkeypatch, tmp_path):
    module = importlib.import_module(f"agilab.agent_runtime.{module_name}_showcase")
    destination = tmp_path / "astra"
    shutil.copytree(module.ASTRA_DEMO_ROOT, destination, ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setattr(module, "ASTRA_DEMO_ROOT", destination)
    (destination / "app.py").write_text("raise AssertionError('unverified app')")
    monkeypatch.setattr(module, "_run_verified_app", lambda *a, **kw: pytest.fail("Changed Astra app executed"))
    at = AppTest.from_string(
        f"from agilab.agent_runtime.{module_name}_showcase import render\nrender(astra=True)"
    ).run()
    assert not at.exception and at.error and not at.title
    with pytest.raises(ValueError, match="changed"):
        module.download_bundle(astra=True)
    # A rejected original must not make the independently verified local build unavailable.
    assert module.load_report()["build_model"]["execution"] == "local"


@pytest.mark.parametrize("module_name,route,state_key,run_id", VARIANTS)
def test_switching_flavours_preserves_independent_results_even_on_failure(module_name, route, state_key, run_id, monkeypatch):
    module = importlib.import_module(f"agilab.agent_runtime.{module_name}_showcase")
    state = {state_key: {"external": True}}
    monkeypatch.setattr(module.st, "session_state", state)
    payload = {f"{name}.py": b"" for name in (
        "text_core", "forecast_core", "agilab_pool", "free_threading_core", "benchmark", "energy_core", "energy_runner"
    )}

    def run(astra, expected, fail=False):
        root = module.ASTRA_DEMO_ROOT if astra else module.DEMO_ROOT
        code = (
            "import streamlit as st\n"
            f"assert __file__ == {str(root / 'app.py')!r}\n"
            f"assert st.session_state.get({state_key!r}, 0) == {expected}\n"
            f"st.session_state[{state_key!r}] = {expected + 1}\n"
        )
        if fail:
            code += "raise RuntimeError('interrupted app')\n"
        payload["app.py"] = code.encode()
        module._run_verified_app(payload, astra=astra)

    run(False, 0)
    run(True, 0)
    run(False, 1)
    with pytest.raises(RuntimeError, match="interrupted app"):
        run(True, 1, fail=True)
    run(False, 2)
    run(True, 2)
    assert state[state_key] == {"external": True}


@pytest.fixture
def lab_controls(monkeypatch):
    """Exercise the sealed UI with deterministic solver boundaries, without optional solvers."""
    for name in ("agilab_pool", "energy_core"):
        spec = importlib.util.spec_from_file_location(name, showcase.ASTRA_DEMO_ROOT / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
    core = sys.modules["energy_core"]
    monkeypatch.setattr(core, "cpu_limits", lambda: {"effective_cpus": 2, "limits": {"fixture": 2}})
    runner = ModuleType("energy_runner")
    calls = []

    def unexpected_solve(*args, **kwargs):
        raise AssertionError("Saving, clearing and rendering must not solve a scenario")

    def bounded_failure(batch, workers, *, progress):
        calls.append((batch, workers))
        raise TimeoutError("Fixture worker deadline reached")

    runner.run_scenario = unexpected_solve
    runner.run_benchmark = bounded_failure
    monkeypatch.setitem(sys.modules, "energy_runner", runner)
    return core, calls


def test_milp_save_and_clear_keep_solved_inputs(lab_controls):
    core, calls = lab_controls
    at = AppTest.from_file(str(showcase.ASTRA_DEMO_ROOT / "app.py")).run()
    assert not at.exception
    assert at.button(key="milp_energy_save").disabled
    settings = core.default_settings()
    settings["max_modules"] = 20
    result = core._empty_result(settings)
    result["status"] = "infeasible"
    at.session_state["milp_energy_result"] = result
    at.run()
    at.text_input(key="milp_energy_scenario_name").set_value("Capacity limited")
    at.button(key="milp_energy_save").click().run()
    assert not at.exception
    saved = at.session_state["milp_energy_saved"]
    assert len(saved) == 1 and saved[0]["name"] == "Capacity limited"
    assert saved[0]["result"]["settings"]["max_modules"] == 20
    assert saved[0]["result"] is not at.session_state["milp_energy_result"]
    assert saved[0]["result"]["settings"] is not at.session_state["milp_energy_result"]["settings"]
    at.button(key="milp_energy_save").click().run()
    assert len(at.session_state["milp_energy_saved"]) == 1
    assert any("already saved" in item.value for item in at.warning)
    at.button(key="milp_energy_clear").click().run()
    assert not at.exception
    assert at.session_state["milp_energy_saved"] == []
    assert at.session_state["milp_energy_result"]["settings"]["max_modules"] == 20
    assert calls == []


@pytest.mark.parametrize("cpus", [1, 2])
def test_milp_scaling_dispatch_and_cpu_gate(lab_controls, monkeypatch, cpus):
    core, calls = lab_controls
    monkeypatch.setattr(core, "cpu_limits", lambda: {"effective_cpus": cpus, "limits": {"fixture": cpus}})
    at = AppTest.from_file(str(showcase.ASTRA_DEMO_ROOT / "app.py")).run()
    assert not at.exception and calls == []
    button = at.button(key="milp_energy_scale_run")
    assert button.disabled is (cpus == 1)
    if cpus == 1:
        assert any("one effective CPU" in item.value for item in at.info)
        return
    button.click().run()
    assert not at.exception
    assert len(calls) == 1 and len(calls[0][0]) == 4 and calls[0][1] == 2
    assert any("Fixture worker deadline reached" in item.value for item in at.error)
