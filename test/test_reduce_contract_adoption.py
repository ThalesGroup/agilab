from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BUILTIN_APPS_ROOT = REPO_ROOT / "src" / "agilab" / "apps" / "builtin"
TEMPLATE_ONLY_BUILTIN_APPS = {
    "global_dag_project": "cross-app DAG template preview with no concrete worker merge output",
    "mycode_project": "starter template with placeholder worker hooks and no concrete merge output",
}


def _load_kpi_bundle_module():
    module_path = REPO_ROOT / "tools" / "kpi_evidence_bundle.py"
    spec = importlib.util.spec_from_file_location("kpi_evidence_bundle_guardrail_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _builtin_projects() -> list[Path]:
    return sorted(
        path
        for path in BUILTIN_APPS_ROOT.glob("*_project")
        if (path / "pyproject.toml").is_file()
    )


def test_non_template_builtin_apps_expose_reduce_contracts() -> None:
    module = _load_kpi_bundle_module()

    check = module._check_reduce_contract_adoption_guardrail(REPO_ROOT)

    assert check["status"] == "pass", "\n".join(check["details"].get("failures", []))
    assert check["id"] == "reduce_contract_adoption_guardrail"
    assert check["details"]["checked_apps"] == sorted([
        "execution_pandas_project",
        "execution_polars_project",
        "flight_telemetry_project",
        "meteo_forecast_project",
        "mission_decision_project",
        "pytorch_playground_project",
        "sklearn_pipeline_project",
        "tescia_diagnostic_project",
        "uav_queue_project",
        "uav_relay_queue_project",
        "weather_forecast_project",
    ])
    assert check["details"]["template_only_exemptions"] == TEMPLATE_ONLY_BUILTIN_APPS


def test_mission_decision_reduce_contract_merges_decision_summaries(monkeypatch) -> None:
    app_src = BUILTIN_APPS_ROOT / "mission_decision_project" / "src"
    monkeypatch.syspath_prepend(str(app_src))
    from mission_decision.reduction import (
        REDUCE_ARTIFACT_NAME,
        REDUCER_NAME,
        build_reduce_artifact,
        partial_from_decision_summary,
    )

    base_summary = {
        "schema": "agilab.mission_decision.summary.v1",
        "scenario": "mission_alpha",
        "artifact_stem": "mission_alpha",
        "status": "pass",
        "selected_strategy": "route_b",
        "initial_strategy": "route_a",
        "degraded_initial_strategy": "route_a",
        "latency_ms_selected": 90.0,
        "cost_selected": 12.0,
        "reliability_selected": 0.98,
        "risk_selected": 0.05,
        "pipeline_stage_count": 6,
        "applied_event_count": 1,
    }
    second_summary = {
        **base_summary,
        "scenario": "mission_beta",
        "artifact_stem": "mission_beta",
        "selected_strategy": "route_c",
        "latency_ms_selected": 110.0,
        "cost_selected": 10.0,
        "reliability_selected": 0.94,
        "risk_selected": 0.07,
        "pipeline_stage_count": 5,
        "applied_event_count": 2,
    }

    artifact = build_reduce_artifact(
        (
            partial_from_decision_summary(base_summary, partial_id="first"),
            partial_from_decision_summary(second_summary, partial_id="second"),
        )
    )

    assert artifact.name == REDUCE_ARTIFACT_NAME
    assert artifact.reducer == REDUCER_NAME
    assert artifact.partial_count == 2
    assert artifact.payload["scenario_count"] == 2
    assert artifact.payload["scenarios"] == ["mission_alpha", "mission_beta"]
    assert artifact.payload["selected_strategies"] == ["route_b", "route_c"]
    assert artifact.payload["selected_latency_ms_mean"] == 100.0
    assert artifact.payload["selected_cost_mean"] == 11.0
    assert artifact.payload["selected_reliability_mean"] == 0.96
    assert artifact.payload["max_pipeline_stage_count"] == 6
    assert artifact.payload["applied_event_count"] == 3


def test_template_only_builtin_apps_are_explicitly_exempted() -> None:
    discovered = {path.name for path in _builtin_projects()}

    assert set(TEMPLATE_ONLY_BUILTIN_APPS) <= discovered

    mycode_docs = (REPO_ROOT / "docs" / "source" / "mycode-project.rst").read_text(
        encoding="utf-8"
    )
    normalized_docs = re.sub(r"\s+", " ", mycode_docs.lower())
    assert "template-only" in normalized_docs
    assert "no concrete merge output" in normalized_docs
    assert "reduce_summary_worker_<id>.json" in mycode_docs


def test_sklearn_pipeline_reduce_contract_merges_model_summaries(monkeypatch) -> None:
    app_src = BUILTIN_APPS_ROOT / "sklearn_pipeline_project" / "src"
    monkeypatch.syspath_prepend(str(app_src))
    from sklearn_pipeline.reduction import build_reduce_artifact, partial_from_sklearn_summary

    first = {
        "metrics": {"train_rows": 90, "test_rows": 30, "accuracy": 0.8, "f1": 0.75},
        "promotion_hint": "review",
        "artifacts": {"model": {"path": "model.joblib"}},
    }
    second = {
        "metrics": {"train_rows": 120, "test_rows": 40, "accuracy": 0.9, "f1": 0.85},
        "promotion_hint": "candidate",
        "artifacts": {"model": {"path": "model.joblib"}, "metrics": {"path": "metrics.json"}},
    }

    artifact = build_reduce_artifact(
        (
            partial_from_sklearn_summary(first, partial_id="first"),
            partial_from_sklearn_summary(second, partial_id="second"),
        )
    )

    assert artifact.payload["run_count"] == 2
    assert artifact.payload["train_rows"] == 210
    assert artifact.payload["test_rows"] == 70
    assert artifact.payload["accuracy_mean"] == 0.85
    assert artifact.payload["f1_mean"] == 0.8
    assert artifact.payload["promotion_candidate_count"] == 1
    assert artifact.payload["artifact_paths"] == ["metrics.json", "model.joblib"]


def test_pytorch_playground_reduce_contract_merges_training_summaries(monkeypatch) -> None:
    app_src = BUILTIN_APPS_ROOT / "pytorch_playground_project" / "src"
    monkeypatch.syspath_prepend(str(app_src))
    from pytorch_playground.reduction import build_reduce_artifact, partial_from_playground_summary

    first = {
        "backend": "torch",
        "samples": 320,
        "features": 5,
        "hidden_layers": [12, 12],
        "train_accuracy": 0.86,
        "validation_accuracy": 0.81,
        "validation_loss": 0.43,
        "loss_landscape_points": 441,
    }
    second = {
        "backend": "torch",
        "samples": 200,
        "features": 4,
        "hidden_layers": [16],
        "train_accuracy": 0.9,
        "validation_accuracy": 0.85,
        "validation_loss": 0.37,
        "loss_landscape_points": 225,
    }

    artifact = build_reduce_artifact(
        (
            partial_from_playground_summary(first, partial_id="first"),
            partial_from_playground_summary(second, partial_id="second"),
        )
    )

    assert artifact.payload["run_count"] == 2
    assert artifact.payload["sample_count"] == 520
    assert artifact.payload["feature_count"] == 5
    assert artifact.payload["train_accuracy_mean"] == 0.88
    assert artifact.payload["validation_accuracy_mean"] == 0.83
    assert artifact.payload["validation_loss_mean"] == 0.4
    assert artifact.payload["loss_landscape_point_count"] == 666
    assert artifact.payload["backends"] == ["torch"]
    assert artifact.payload["hidden_layers"] == ["12", "16"]
