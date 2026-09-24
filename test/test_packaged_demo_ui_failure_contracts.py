"""Headless demo UI contracts with temporary evidence and no provider calls."""

import hashlib
import json
import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from agilab.agent_runtime import notebook_adoption, notebook_agent
from agilab.demos import notebook_app_runtime


UI = Path(__file__).resolve().parents[1] / "src/agilab/demos/notebook_demo_ui.py"


def by_label(elements, label):
    return next(element for element in elements if element.label == label)


@pytest.fixture
def demo_ui(tmp_path, monkeypatch):
    output = tmp_path / "runs"
    output.mkdir()
    monkeypatch.setattr(sys, "argv", [str(UI), "--output", str(output)])
    monkeypatch.setattr(
        notebook_agent,
        "build",
        lambda **kwargs: pytest.fail("provider build forbidden"),
    )
    return output, AppTest.from_file(str(UI), default_timeout=30)


def completed_run(output, status="passed"):
    root = output / "20260924T120000Z-abcdef12"
    project = root / "example_project"
    project.mkdir(parents=True)
    (project / "solution.ipynb").write_text('{"cells":[]}')
    (project / "app.py").write_text("value = 42\n")
    report = {
        "status": status,
        "project": str(project),
        "seconds": 42,
        "workflow_stages": 3,
        "verification": {"checks": ["execution", "ui"], "scores": [{"accuracy": 1.0}]},
        "files": {
            "app.py": hashlib.sha256((project / "app.py").read_bytes()).hexdigest()
        },
        "error": "Model verification rejected the output",
    }
    (root / "result.json").write_text(json.dumps(report))
    (root / "events.jsonl").write_text(
        json.dumps(
            {
                "time": "2026-09-24T12:00:00Z",
                "phase": "verify",
                "message": "Verification finished",
            }
        )
        + "\n"
    )
    return root, project, report


@pytest.mark.parametrize("source", ["Local notebook", "Pinned GitHub notebook"])
def test_custom_notebook_requires_source_and_explicit_consent(demo_ui, source):
    _, at = demo_ui
    at.run()
    assert not at.exception
    assert not by_label(at.button, "Build my app").disabled
    by_label(at.radio, "Notebook source").set_value(source).run()
    assert not at.exception
    assert by_label(at.button, "Build my app").disabled
    label = (
        "Or use a local notebook path"
        if source == "Local notebook"
        else "GitHub notebook URL"
    )
    by_label(at.text_input, label).set_value(
        "/tmp/example.ipynb"
        if source == "Local notebook"
        else "https://github.com/example/repo/blob/" + "a" * 40 + "/demo.ipynb"
    ).run()
    assert by_label(at.button, "Build my app").disabled
    at.checkbox[0].check().run()
    assert not by_label(at.button, "Build my app").disabled
    at.text_area[0].set_value(" ").run()
    assert by_label(at.button, "Build my app").disabled


def test_running_query_restores_evidence_and_disables_duplicate_build(demo_ui):
    output, at = demo_ui
    root = output / "20260924T120000Z-abcdef12"
    root.mkdir()
    (root / "events.jsonl").write_text(
        json.dumps(
            {
                "time": "2026-09-24T12:00:00Z",
                "phase": "build",
                "message": "Building locally",
            }
        )
        + "\n"
    )
    at.query_params["run"] = root.name
    at.run()
    assert not at.exception
    assert at.session_state["run_root"] == str(root)
    assert by_label(at.button, "Build my app").disabled
    assert any("Building locally" in element.label for element in at.status)


@pytest.mark.parametrize(
    "query", ["../outside", "invalid", "20260924T120000Z-abcdef12"]
)
def test_run_query_never_follows_missing_or_symlink_run(demo_ui, tmp_path, query):
    output, at = demo_ui
    outside = tmp_path / "outside"
    outside.mkdir()
    if query.startswith("2026"):
        (output / query).symlink_to(outside, target_is_directory=True)
    at.query_params["run"] = query
    at.run()
    assert not at.exception
    assert "run_root" not in at.session_state
    assert any("One action" in element.value for element in at.subheader)


def test_failed_run_reports_bounded_execution_evidence(demo_ui):
    output, at = demo_ui
    root, _, _ = completed_run(output, "failed")
    (root / "agent").mkdir()
    (root / "agent/stderr.txt").write_text(
        "sensitive-old-prefix" + "x" * 7000 + "latest-error"
    )
    (root / "verification.log").write_text("acceptance failed")
    at.query_params["run"] = root.name
    at.run()
    assert not at.exception
    assert any("Model verification rejected" in error.value for error in at.error)
    codes = [code.value for code in at.code]
    assert len(codes[0]) == 6000 and codes[0].endswith("latest-error")
    assert "sensitive-old-prefix" not in codes[0]
    assert "acceptance failed" in codes
    assert not by_label(at.button, "Build my app").disabled


@pytest.mark.parametrize("tampered", [False, True])
def test_successful_run_rechecks_hashes_before_app_replay(
    demo_ui, monkeypatch, tampered
):
    output, at = demo_ui
    root, project, report = completed_run(output)
    notebook_adoption.write_completion_receipt(root, report)
    executed = []
    monkeypatch.setattr(
        notebook_app_runtime, "run_app", lambda path: executed.append(path)
    )
    at.query_params["run"] = root.name
    at.run()
    assert not at.exception
    assert {metric.label: metric.value for metric in at.metric} == {
        "Build time": "42 s",
        "Workflow stages": "3",
        "Acceptance checks": "2",
    }
    assert len(at.get("download_button")) == 2
    assert any(
        "Share this receipt" in element.label for element in at.get("link_button")
    )
    if tampered:
        (project / "app.py").write_text("value = 'changed'\n")
    by_label(at.button, "Try the app").click().run()
    assert not at.exception
    if tampered:
        assert executed == []
        assert any("changed after verification" in error.value for error in at.error)
    else:
        assert executed == [project]


def load_resource_module(bundle, name, monkeypatch):
    import importlib.util

    path = UI.parent / "resources" / bundle / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"ui_contract_{bundle}_{name}", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def milp_ui(monkeypatch):
    from types import SimpleNamespace

    core = load_resource_module("milp_energy_demo", "energy_core", monkeypatch)
    monkeypatch.setattr(
        core, "cpu_limits", lambda: {"effective_cpus": 2, "observed_caps": [2]}
    )
    monkeypatch.setattr(
        core, "model_artifact_text", lambda settings: "synthetic model for UI contract"
    )
    runner = SimpleNamespace(
        run_scenario=lambda settings: pytest.fail("solver boundary must be mocked"),
        run_benchmark=lambda *args: pytest.fail("benchmark boundary must be mocked"),
    )
    monkeypatch.setitem(sys.modules, "energy_core", core)
    monkeypatch.setitem(sys.modules, "energy_runner", runner)
    return (
        core,
        runner,
        AppTest.from_file(
            str(UI.parent / "resources/milp_energy_demo/app.py"), default_timeout=30
        ),
    )


def energy_result(settings, status="optimal"):
    n = settings["hours"]
    return {
        "status": status,
        "settings": dict(settings),
        "objective": 10.0,
        "solver": {"incumbent": status == "optimal"},
        "demand": [1.0] * n,
        "dispatch": [1.0] * n,
        "solar": [0.0] * n,
        "shed": [0.0] * n,
        "solar_available": [0.0] * n,
        "active_modules": [1] * n,
        "startup": [0] * n,
        "shutdown": [0] * n,
        "modules": 1,
        "capacity_mw": 200.0,
        "costs": {"fuel": 10.0},
        "elapsed_seconds": 0.1,
        "residuals": {"energy_balance": 0.0},
        "error": "fixture solver failure",
    }


@pytest.mark.parametrize("failure", ["validation", "solver", "infeasible"])
def test_milp_ui_failure_does_not_create_successful_schedule(
    milp_ui, monkeypatch, failure
):
    core, runner, at = milp_ui

    def fail(*args):
        raise ValueError("fixture rejected")

    if failure == "validation":
        monkeypatch.setattr(core, "validate_settings", fail)
    elif failure == "solver":
        runner.run_scenario = fail
    else:
        runner.run_scenario = lambda settings: energy_result(settings, "infeasible")
    at.run()
    by_label(at.button, "Run analysis").click().run()
    assert not at.exception
    assert at.error
    assert not any(
        element.label == "Download schedule CSV"
        for element in at.get("download_button")
    )
    if failure == "infeasible":
        assert any("No feasible solution" in warning.value for warning in at.warning)
    else:
        assert at.session_state["analysis"] is None


def test_milp_ui_committed_result_comparison_and_stale_benchmark(milp_ui):
    _, runner, at = milp_ui
    runner.run_scenario = energy_result
    benchmark_calls = []

    def benchmark(batch, workers):
        benchmark_calls.append((batch, workers))
        return {
            "sequential": {"workers": 1},
            "parallel": {
                "workers": workers,
                "rows": [
                    {
                        "case": 0,
                        "pid": 100,
                        "start_monotonic": 1.0,
                        "end_monotonic": 2.0,
                    }
                ],
            },
            "comparison": {
                "matches": True,
                "speedup": 1.0,
                "engine_speedup": 1.0,
                "scaling_available": False,
            },
        }

    runner.run_benchmark = benchmark
    at.run()
    by_label(at.button, "Run analysis").click().run()
    assert not at.exception
    assert any(
        element.label == "Download schedule CSV"
        for element in at.get("download_button")
    )
    by_label(at.button, "Keep scenario").click().run()
    assert len(at.session_state["comparisons"]) == 1
    by_label(at.button, "Run benchmark").click().run()
    assert not at.exception
    assert len(benchmark_calls) == 1
    assert any("matches current controls" in caption.value for caption in at.caption)
    by_label(at.selectbox, "Batch size").set_value(8).run()
    assert any("Controls changed" in warning.value for warning in at.warning)
    assert len(benchmark_calls) == 1
    at.session_state["comparisons"] = [at.session_state["analysis"]] * 10
    by_label(at.button, "Keep scenario").click().run()
    assert len(at.session_state["comparisons"]) == 10
    assert any("Comparison limit" in warning.value for warning in at.warning)
    by_label(at.button, "Clear comparisons").click().run()
    assert at.session_state["comparisons"] == []
    by_label(at.button, "Run analysis").click().run()
    assert at.session_state["benchmark_result"] is None


def test_milp_ui_benchmark_and_artifact_errors_preserve_committed_result(
    milp_ui, monkeypatch
):
    core, runner, at = milp_ui
    runner.run_scenario = energy_result

    def fail(*args):
        raise RuntimeError("fixture unavailable")

    runner.run_benchmark = fail
    monkeypatch.setattr(core, "model_artifact_text", fail)
    at.run()
    by_label(at.button, "Run analysis").click().run()
    committed = at.session_state["analysis"]
    assert any("Error generating artifact" in code.value for code in at.code)
    by_label(at.button, "Run benchmark").click().run()
    assert not at.exception
    assert any("Benchmark failed" in error.value for error in at.error)
    assert at.session_state["analysis"] == committed
    assert at.session_state["benchmark_result"] is None


@pytest.fixture
def threading_ui(monkeypatch):
    from types import SimpleNamespace
    import importlib

    monkeypatch.syspath_prepend(str(UI.parent / "resources/free_threading_demo"))
    monkeypatch.delitem(sys.modules, "agilab_pool", raising=False)
    pool = importlib.import_module("agilab_pool")
    monkeypatch.setitem(sys.modules, "agilab_pool", pool)
    core = load_resource_module(
        "free_threading_demo", "free_threading_core", monkeypatch
    )
    benchmark = SimpleNamespace(
        effective_cpus=lambda: {"effective_cpus": 1},
        run_benchmark=lambda **kwargs: pytest.fail("worker subprocess forbidden"),
    )
    monkeypatch.setitem(sys.modules, "free_threading_core", core)
    monkeypatch.setitem(sys.modules, "benchmark", benchmark)
    return benchmark, AppTest.from_file(
        str(UI.parent / "resources/free_threading_demo/app.py"), default_timeout=30
    )


def test_threading_ui_single_cpu_failure_keeps_analysis(threading_ui):
    benchmark, at = threading_ui

    def failed(**kwargs):
        kwargs["progress"](1, 2, "fixture progress")
        raise RuntimeError("fixture benchmark failed")

    benchmark.run_benchmark = failed
    at.run()
    assert not at.exception
    assert any(
        "Parallel scaling is unavailable" in warning.value for warning in at.warning
    )
    assert by_label(at.number_input, "Workers").disabled
    by_label(at.button, "Run analysis").click().run()
    assert not at.exception
    analysis = dict(at.session_state["analysis"])
    by_label(at.button, "Run benchmark").click().run()
    assert not at.exception
    assert any("fixture benchmark failed" in error.value for error in at.error)
    assert at.session_state["analysis"] == analysis
    assert "benchmark_result" not in at.session_state


@pytest.mark.parametrize(
    "records",
    [
        [],
        [
            {
                "row_start": 0,
                "row_stop": 2,
                "pid": 123,
                "runtime_before": {"gil": False},
                "runtime_after": {"gil": False},
            }
        ],
    ],
)
def test_threading_ui_reports_fixture_evidence_and_invalidates_changed_analysis(
    threading_ui, records
):
    benchmark, at = threading_ui
    benchmark.effective_cpus = lambda: {"effective_cpus": 2}
    report = {
        "summary": [
            {
                "mode": "gil_on_threads",
                "role": role,
                "workers": 1,
                "wall_seconds": 1.0,
                "engine_seconds": 0.8,
                "speedup": 1.0,
            }
            for role in ("baseline", "parallel")
        ],
        "runs": [
            {
                "mode": "gil_on_threads",
                "role": "baseline",
                "records": records,
                "before": {"gil_enabled": True, "free_threaded_build": True},
                "after": {"gil_enabled": True},
            }
        ],
        "hardware": {"effective_cpus": 2},
        "python_build": "synthetic UI fixture",
        "same_work_verified": True,
        "scaling_available": False,
        "digest": "fixture-digest",
    }
    calls = []

    def run(**kwargs):
        calls.append(kwargs)
        kwargs["progress"](1, 1, "fixture complete")
        return report

    benchmark.run_benchmark = run
    at.run()
    by_label(at.slider, "Width").set_value(4)
    by_label(at.slider, "Height").set_value(2)
    by_label(at.button, "Run analysis").click().run()
    by_label(at.button, "Run benchmark").click().run()
    assert not at.exception
    assert len(calls) == 1 and calls[0]["width"] == 4 and calls[0]["height"] == 2
    assert at.session_state["benchmark_result"] == report
    assert any(code.value == "fixture-digest" for code in at.code)
    assert {element.label for element in at.get("download_button")} == {
        "Download result JSON",
        "Download summary CSV",
    }
    if records:
        assert any("Total records: 1" in caption.value for caption in at.caption)
    else:
        assert any("No records available" in caption.value for caption in at.caption)
    by_label(at.slider, "Width").set_value(6)
    by_label(at.button, "Run analysis").click().run()
    assert not at.exception
    assert "benchmark_result" not in at.session_state
    assert at.session_state["analysis"]["width"] == 6
    assert len(calls) == 1


@pytest.mark.parametrize("error_kind", ["model", "runtime"])
def test_forecast_ui_failure_retry_uses_committed_controls_and_reports_scope(
    monkeypatch, error_kind
):
    from types import ModuleType

    # Prediction is replaced below; no tensor/model dependency is exercised.
    monkeypatch.setitem(sys.modules, "torch", ModuleType("torch"))
    core = load_resource_module(
        "forecast_notebook_demo_rtx", "forecast_core", monkeypatch
    )
    monkeypatch.setitem(sys.modules, "forecast_core", core)
    calls = []

    def unavailable(data, use_covariates=True):
        calls.append("unavailable")
        error = core.ModelUnavailableError if error_kind == "model" else RuntimeError
        raise error("fixture inference unavailable")

    monkeypatch.setattr(core, "predict", unavailable)
    at = AppTest.from_file(
        str(UI.parent / "resources/forecast_notebook_demo_rtx/app.py"),
        default_timeout=30,
    ).run()
    assert not at.exception
    assert calls == []
    assert len(at.dataframe) == 1
    by_label(at.selectbox, "Horizon (days)").set_value(14)
    by_label(at.number_input, "Random seed").set_value(17)
    by_label(at.button, "Run analysis").click().run()
    assert not at.exception
    assert calls == ["unavailable"]
    assert at.session_state["result"] is None
    assert any(
        "inference is unavailable" in error.value
        if error_kind == "model"
        else "Analysis failed" in error.value
        for error in at.error
    )

    def prediction(data, use_covariates=True):
        horizon = len(data["future_promotion"])
        value = float(data["context"][-1])
        return {
            "forecast": [value] * horizon,
            "lower": [value - 10] * horizon,
            "upper": [value + 10] * horizon,
        }

    monkeypatch.setattr(core, "predict", prediction)
    by_label(at.button, "Run analysis").click().run()
    assert not at.exception
    result = at.session_state["result"]
    assert result["horizon"] == 14 and result["seed"] == 17
    assert "error" not in at.session_state
    assert len(at.metric) == 3
    assert any("not calibrated" in markdown.value for markdown in at.markdown)
    assert any("not a causal estimate" in markdown.value for markdown in at.markdown)
    assert len(at.dataframe) == 2


@pytest.mark.parametrize(
    "bundle",
    ["text_notebook_demo", "text_notebook_demo_astra", "text_notebook_demo_rtx"],
)
def test_text_ui_visual_changes_keep_committed_analysis(monkeypatch, bundle):
    import numpy as np
    import pandas as pd
    import streamlit as st
    from types import SimpleNamespace

    st.cache_data.clear()
    corpus = pd.DataFrame(
        {
            "text": ["A short article", "A longer article " * 20] * 3,
            "category": ["science", "world"] * 3,
        }
    )
    calls = []

    def analyze(**params):
        calls.append(dict(params))
        k = params["n_clusters"]
        return {
            "parameters": {**params, "n_components": 2, "n_samples": 6},
            "coordinates": np.array([[i, i / 2] for i in range(6)], dtype=float),
            "labels": np.array([i % k for i in range(6)]),
            "vocabulary": ["article", "science", "world"],
            "silhouette": 0.25,
            "displayed_variance": 0.2,
            "retained_variance": 0.5,
            "top_terms": {str(i): ["article", "science"] for i in range(k)},
        }

    monkeypatch.setitem(
        sys.modules,
        "text_core",
        SimpleNamespace(load_corpus=lambda: corpus.copy(), analyze=analyze),
    )
    at = AppTest.from_file(
        str(UI.parent / "resources" / bundle / "app.py"), default_timeout=30
    ).run()
    assert not at.exception
    assert calls == []
    by_label(at.button, "Run analysis").click().run()
    assert not at.exception
    assert len(calls) == 1
    color = next(radio for radio in at.radio if "Color" in radio.label)
    color.set_value(color.options[-1]).run()
    assert not at.exception
    assert len(calls) == 1
    article = at.selectbox[0]
    article.select_index(1).run()
    assert not at.exception
    assert len(calls) == 1
    assert any("A longer article" in element.value for element in at.text)
    assert len(at.metric) >= 2
    assert any(
        "not validated topics" in element.value
        or "not a measure of topical accuracy" in element.value
        for element in [*at.info, *at.markdown, *at.caption]
    )
    st.cache_data.clear()


@pytest.mark.parametrize(
    "bundle,state_key,preserve",
    [
        ("text_notebook_demo_astra", "analysis_result", True),
        ("text_notebook_demo_rtx", "last_result", False),
    ],
)
def test_text_ui_failure_obeys_variant_result_retention(
    monkeypatch, bundle, state_key, preserve
):
    import numpy as np
    import pandas as pd
    import streamlit as st
    from types import SimpleNamespace

    st.cache_data.clear()
    params = {
        "n_clusters": 5,
        "min_df": 5,
        "max_df": 0.8,
        "seed": 42,
        "n_components": 2,
        "n_samples": 6,
    }
    previous = {
        "parameters": params,
        "coordinates": np.zeros((6, 2)),
        "labels": np.zeros(6, dtype=int),
        "vocabulary": ["word"],
        "silhouette": 0.1,
        "displayed_variance": 0.1,
        "retained_variance": 0.2,
        "top_terms": {"0": ["word"]},
    }
    corpus = pd.DataFrame(
        {"text": ["Fixture article"] * 6, "category": ["fixture"] * 6}
    )

    def fail(**kwargs):
        raise ValueError("fixture vocabulary empty")

    monkeypatch.setitem(
        sys.modules,
        "text_core",
        SimpleNamespace(load_corpus=lambda: corpus, analyze=fail),
    )
    at = AppTest.from_file(
        str(UI.parent / "resources" / bundle / "app.py"), default_timeout=30
    )
    at.session_state[state_key] = previous
    at.run()
    by_label(at.button, "Run analysis").click().run()
    assert not at.exception
    assert any("fixture vocabulary empty" in error.value for error in at.error)
    assert (state_key in at.session_state) is preserve
    st.cache_data.clear()


@pytest.mark.parametrize(
    "bundle,horizon_label,seed_label,result_key",
    [
        ("forecast_notebook_demo", "Forecast horizon", "Random seed", "fcst_result"),
        (
            "forecast_notebook_demo_astra",
            "Forecast horizon (days)",
            "Synthetic data seed",
            "analysis",
        ),
    ],
)
def test_forecast_sibling_ui_retries_and_retains_committed_result(
    monkeypatch, bundle, horizon_label, seed_label, result_key
):
    from types import ModuleType

    monkeypatch.setitem(sys.modules, "torch", ModuleType("torch"))
    core = load_resource_module(bundle, "forecast_core", monkeypatch)
    monkeypatch.setitem(sys.modules, "forecast_core", core)
    calls = []

    def unavailable(data, use_covariates=True):
        calls.append("unavailable")
        raise RuntimeError("fixture inference failure")

    monkeypatch.setattr(core, "predict", unavailable)
    at = AppTest.from_file(
        str(UI.parent / "resources" / bundle / "app.py"), default_timeout=30
    ).run()
    assert not at.exception
    assert calls == []
    by_label(at.selectbox, horizon_label).set_value(14)
    by_label(at.number_input, seed_label).set_value(19)
    by_label(at.button, "Run analysis").click().run()
    assert not at.exception and at.error
    assert result_key not in at.session_state

    def prediction(data, use_covariates=True):
        calls.append("success")
        horizon = len(data["future_promotion"])
        value = float(data["context"][-1])
        import numpy as np

        return {
            "forecast": np.full(horizon, value),
            "lower": np.full(horizon, value - 10),
            "upper": np.full(horizon, value + 10),
        }

    monkeypatch.setattr(core, "predict", prediction)
    by_label(at.button, "Run analysis").click().run()
    assert not at.exception
    assert len(at.metric) == 3
    before = len(calls)
    at.run()
    assert not at.exception
    assert len(calls) == before
    assert result_key in at.session_state
    assert any("not calibrated" in element.value for element in [*at.info, *at.caption])


@pytest.mark.parametrize(
    "bundle,key",
    [
        ("milp_energy_demo_astra", "milp_energy_result"),
        ("milp_energy_demo_rtx", "result"),
    ],
)
def test_milp_sibling_ui_solver_retry_and_saved_result_policy(monkeypatch, bundle, key):
    from types import SimpleNamespace

    core = load_resource_module(bundle, "energy_core", monkeypatch)
    monkeypatch.setattr(
        core, "cpu_limits", lambda: {"effective_cpus": 2, "observed_caps": [2]}
    )
    runner = SimpleNamespace()
    calls = []

    def fail(*args, **kwargs):
        if "progress" in kwargs:
            kwargs["progress"](1)
            kwargs["progress"](1.2)
        raise RuntimeError("fixture solver unavailable")

    def solve(settings, **kwargs):
        calls.append(dict(settings))
        if "progress" in kwargs:
            kwargs["progress"](1)
        result = energy_result(settings)
        result.update(input_sha256="a" * 64, model_text="fixture formulation")
        result["residuals"]["verified"] = True
        result["solver"].update(termination="optimal", gap=None, objective_bound=None)
        return result

    runner.run_scenario = fail
    runner.run_benchmark = fail
    monkeypatch.setattr(core, "solve_scenario", fail, raising=False)
    monkeypatch.setitem(sys.modules, "energy_core", core)
    monkeypatch.setitem(sys.modules, "energy_runner", runner)
    at = AppTest.from_file(
        str(UI.parent / "resources" / bundle / "app.py"), default_timeout=30
    ).run()
    assert not at.exception
    by_label(at.button, "Run analysis").click().run()
    assert not at.exception
    assert any("fixture solver unavailable" in error.value for error in at.error)
    assert key not in at.session_state
    runner.run_scenario = solve
    monkeypatch.setattr(core, "solve_scenario", solve)
    by_label(at.button, "Run analysis").click().run()
    assert not at.exception
    assert at.session_state[key]["status"] == "optimal"
    assert len(calls) == 1
    if bundle.endswith("astra"):
        by_label(at.text_input, "Scenario name").set_value("Saved fixture")
        by_label(at.button, "Save current scenario").click().run()
        assert not at.exception
        assert len(at.session_state["milp_energy_saved"]) == 1
        by_label(at.button, "Save current scenario").click().run()
        assert any("already saved" in warning.value for warning in at.warning)
        by_label(at.text_input, "Scenario name").set_value(" ")
        by_label(at.button, "Save current scenario").click().run()
        assert any("nonempty" in warning.value for warning in at.warning)
    runner.run_scenario = fail
    monkeypatch.setattr(core, "solve_scenario", fail)
    by_label(at.button, "Run analysis").click().run()
    assert not at.exception
    assert (key in at.session_state) is bundle.endswith("astra")


def test_milp_rtx_scaling_error_retry_reports_observed_workers(monkeypatch):
    from types import SimpleNamespace

    core = load_resource_module("milp_energy_demo_rtx", "energy_core", monkeypatch)

    def fail(*args):
        raise RuntimeError("fixture pool unavailable")

    runner = SimpleNamespace(run_benchmark=fail)
    monkeypatch.setitem(sys.modules, "energy_core", core)
    monkeypatch.setitem(sys.modules, "energy_runner", runner)
    at = AppTest.from_file(
        str(UI.parent / "resources/milp_energy_demo_rtx/app.py"), default_timeout=30
    ).run()
    by_label(at.button, "Run scaling check").click().run()
    assert not at.exception
    assert any("fixture pool unavailable" in error.value for error in at.error)
    assert "benchmark" not in at.session_state
    runner.run_benchmark = lambda batch, workers: {
        "sequential": {"batch": batch, "wall_seconds": 2.0},
        "parallel": {
            "rows": [{"pid": 11}, {"pid": 11}, {"pid": 12}],
            "wall_seconds": 1.5,
        },
        "comparison": {"matches": True, "speedup": 2.0 / 1.5},
    }
    by_label(at.button, "Run scaling check").click().run()
    assert not at.exception
    assert "benchmark_error" not in at.session_state
    assert {metric.label: metric.value for metric in at.metric}["Workers"] == "2"


def threading_sibling_core(monkeypatch, bundle):
    import importlib
    import streamlit as st

    st.cache_data.clear()
    monkeypatch.syspath_prepend(str(UI.parent / "resources" / bundle))
    monkeypatch.delitem(sys.modules, "agilab_pool", raising=False)
    pool = importlib.import_module("agilab_pool")
    monkeypatch.setitem(sys.modules, "agilab_pool", pool)
    core = load_resource_module(bundle, "free_threading_core", monkeypatch)
    monkeypatch.setitem(sys.modules, "free_threading_core", core)
    return core


@pytest.mark.parametrize("failure", ["hardware", "busy", "runtime"])
def test_threading_astra_ui_refuses_unavailable_measurement(monkeypatch, failure):
    from types import SimpleNamespace

    threading_sibling_core(monkeypatch, "free_threading_demo_astra")

    class BusyError(RuntimeError):
        pass

    def hardware():
        if failure == "hardware":
            raise ValueError("fixture CPU quota unavailable")
        return {"effective_cpus": 1}

    def run(*args, **kwargs):
        kwargs["progress"](1, 2, "fixture phase")
        raise (
            BusyError("fixture busy")
            if failure == "busy"
            else RuntimeError("fixture measurement failed")
        )

    monkeypatch.setitem(
        sys.modules,
        "benchmark",
        SimpleNamespace(
            BusyError=BusyError, LABELS={}, effective_cpus=hardware, run_benchmark=run
        ),
    )
    at = AppTest.from_file(
        str(UI.parent / "resources/free_threading_demo_astra/app.py"),
        default_timeout=30,
    ).run()
    assert not at.exception
    if failure == "hardware":
        assert any("CPU quota unavailable" in error.value for error in at.error)
        assert not at.button
    else:
        assert any("parallel scaling is unavailable" in info.value for info in at.info)
        by_label(at.button, "Run analysis").click().run()
        assert not at.exception
        surface = at.warning if failure == "busy" else at.error
        assert any("fixture" in element.value for element in surface)
        assert "analysis" not in at.session_state


@pytest.mark.parametrize("failure", ["configuration", "interpreter"])
def test_threading_rtx_ui_failure_cannot_publish_result(monkeypatch, tmp_path, failure):
    import tempfile
    from types import SimpleNamespace

    core = threading_sibling_core(monkeypatch, "free_threading_demo_rtx")
    monkeypatch.setattr(core, "effective_cpu_allowance", lambda: 2)
    calls = []

    def validate(**kwargs):
        if failure == "configuration":
            raise ValueError("fixture invalid configuration")

    def run(**kwargs):
        calls.append(kwargs)
        kwargs["progress_cb"](1, 2, "fixture phase")
        raise core.FreeThreadingInterpreterError("fixture interpreter unavailable")

    monkeypatch.setattr(core, "validate_params", validate)
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **kwargs: str(tmp_path))
    monkeypatch.setitem(sys.modules, "benchmark", SimpleNamespace(run_benchmark=run))
    at = AppTest.from_file(
        str(UI.parent / "resources/free_threading_demo_rtx/app.py"), default_timeout=30
    ).run()
    by_label(at.button, "Run analysis").click().run()
    assert not at.exception
    assert at.error and "last_results" not in at.session_state
    assert len(calls) == (failure == "interpreter")


def test_threading_rtx_ui_result_records_remain_visible_when_controls_change(
    monkeypatch, tmp_path
):
    import tempfile
    from types import SimpleNamespace

    core = threading_sibling_core(monkeypatch, "free_threading_demo_rtx")
    monkeypatch.setattr(core, "effective_cpu_allowance", lambda: 2)
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **kwargs: str(tmp_path))
    case = {
        "mode": core.MODES[0],
        "mode_label": "Fixture mode",
        "workers": 1,
        "throughput_pixels_per_s": 123.0,
        "status": "ok",
        "median_engine_seconds": 0.1,
        "engine_width": 1,
        "engine_backend": "thread",
        "repeats": [
            {
                "tiles": [
                    {
                        "start": 1.0,
                        "row_start": 0,
                        "row_end": 2,
                        "duration_seconds": 0.1,
                        "pid": 123,
                        "thread": 456,
                    }
                ]
            }
        ],
    }
    report = {
        "results": {
            "speedups": {mode: {"speedup": 1.0, "workers": 2} for mode in core.MODES},
            "hardware": {
                "effective_cpu_allowance": 2,
                "platform": "fixture",
                "cpu_count": 2,
                "process_cpu_count": 2,
                "affinity_size": 2,
            },
            "digest": "f" * 64,
            "same_work": True,
            "same_as_serial_reference": True,
            "cases": [case],
            "interpreter": {
                "executable": "fixture-python",
                "version": "fixture",
                "free_threaded_build": True,
                "py_gil_disabled_build": True,
            },
            "total_seconds": 1.0,
        }
    }
    calls = []

    def run(**kwargs):
        calls.append(kwargs)
        kwargs["progress_cb"](1, 1, "fixture complete")
        return report

    monkeypatch.setitem(sys.modules, "benchmark", SimpleNamespace(run_benchmark=run))
    at = AppTest.from_file(
        str(UI.parent / "resources/free_threading_demo_rtx/app.py"), default_timeout=30
    ).run()
    by_label(at.button, "Run analysis").click().run()
    assert not at.exception
    assert at.session_state["last_results"] == report
    assert any(
        button.label == "Download evidence JSON" for button in at.get("download_button")
    )
    by_label(at.slider, "Repeats").set_value(1).run()
    assert not at.exception
    assert len(calls) == 1
    assert any("results are stale" in warning.value for warning in at.warning)
    assert at.session_state["last_results"] == report


def test_threading_astra_ui_commits_evidence_and_marks_changed_controls(monkeypatch):
    from types import SimpleNamespace

    threading_sibling_core(monkeypatch, "free_threading_demo_astra")

    class BusyError(RuntimeError):
        pass

    report = {
        "created_utc": "2026-09-24T12:00:00Z",
        "parameters": {"repeats": 2, "width": 192, "height": 128, "iterations": 160},
        "summary": [
            {
                "role": role,
                "label": "Fixture threads",
                "workers": width,
                "speedup": 1.0,
                "pixels_per_second": 100,
                "wall_seconds": 1.0,
                "engine_seconds": 0.8,
                "engine_speedup": 1.0,
            }
            for role, width in [("baseline", 1), ("scaled", 2)]
        ],
        "runs": [
            {
                "mode": "fixture",
                "role": "scaled",
                "actual_workers": 2,
                "repeat": 0,
                "origin_ns": 100,
                "observed_workers": 1,
                "backend": "threads",
                "wall_seconds": 1.0,
                "engine_seconds": 0.8,
                "digest": "fixture-digest",
                "before": {"gil_enabled": False},
                "after": {"gil_enabled": False},
                "records": [
                    {
                        "pid": 10,
                        "thread_id": 20,
                        "tile": 0,
                        "start_ns": 100,
                        "end_ns": 200,
                    }
                ],
            }
        ],
        "digest": "fixture-digest",
        "hardware": {"effective_cpus": 2},
        "python_build": "fixture build",
    }
    calls = []

    def run(*args, **kwargs):
        calls.append((args, kwargs))
        kwargs["progress"](1, 1, "fixture complete")
        return report

    monkeypatch.setitem(
        sys.modules,
        "benchmark",
        SimpleNamespace(
            BusyError=BusyError,
            LABELS={"fixture": "Fixture mode"},
            effective_cpus=lambda: {"effective_cpus": 2},
            run_benchmark=run,
        ),
    )
    at = AppTest.from_file(
        str(UI.parent / "resources/free_threading_demo_astra/app.py"),
        default_timeout=30,
    ).run()
    by_label(at.button, "Run analysis").click().run()
    assert not at.exception
    assert at.session_state["analysis"] == report
    assert any("observed active workers: 1" in caption.value for caption in at.caption)
    by_label(at.selectbox, "Workers (N)").set_value(1).run()
    assert not at.exception
    assert len(calls) == 1
    assert any("Previous results" in warning.value for warning in at.warning)
    assert at.session_state["analysis"] == report
