"""Reduce-contract adoption for the built-in Mission Decision app."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from agi_node.reduction import (
    ReduceArtifact,
    ReduceContract,
    ReducePartial,
    require_payload_keys,
)


REDUCE_ARTIFACT_FILENAME_TEMPLATE = "reduce_summary_worker_{worker_id}.json"
REDUCE_ARTIFACT_NAME = "mission_decision_reduce_summary"
REDUCER_NAME = "mission_decision.mission-decision.v1"

_REQUIRED_SUMMARY_KEYS = (
    "schema",
    "scenario",
    "artifact_stem",
    "status",
    "selected_strategy",
    "initial_strategy",
    "degraded_initial_strategy",
    "latency_ms_selected",
    "cost_selected",
    "reliability_selected",
    "risk_selected",
    "pipeline_stage_count",
    "applied_event_count",
)
_REQUIRED_PAYLOAD_KEYS = (
    "scenario_count",
    "scenarios",
    "selected_strategies",
    "initial_strategies",
    "degraded_initial_strategies",
    "selected_latency_ms_sum",
    "selected_cost_sum",
    "selected_reliability_sum",
    "selected_risk_sum",
    "max_pipeline_stage_count",
    "applied_event_count",
)


def _as_float(metrics: Mapping[str, Any], key: str) -> float:
    return float(metrics.get(key, 0.0) or 0.0)


def _as_int(metrics: Mapping[str, Any], key: str) -> int:
    return int(metrics.get(key, 0) or 0)


def _sorted_strings(values: set[str]) -> list[str]:
    return sorted(value for value in values if value)


def _merge_data_io_2026_partials(partials: Sequence[ReducePartial]) -> dict[str, Any]:
    scenarios: set[str] = set()
    selected_strategies: set[str] = set()
    initial_strategies: set[str] = set()
    degraded_initial_strategies: set[str] = set()
    selected_latency_ms_sum = 0.0
    selected_cost_sum = 0.0
    selected_reliability_sum = 0.0
    selected_risk_sum = 0.0
    applied_event_count = 0
    max_pipeline_stage_count = 0

    for partial in partials:
        payload = partial.payload
        scenarios.update(str(item) for item in payload["scenarios"])
        selected_strategies.update(str(item) for item in payload["selected_strategies"])
        initial_strategies.update(str(item) for item in payload["initial_strategies"])
        degraded_initial_strategies.update(
            str(item) for item in payload["degraded_initial_strategies"]
        )
        selected_latency_ms_sum += float(payload["selected_latency_ms_sum"])
        selected_cost_sum += float(payload["selected_cost_sum"])
        selected_reliability_sum += float(payload["selected_reliability_sum"])
        selected_risk_sum += float(payload["selected_risk_sum"])
        applied_event_count += int(payload["applied_event_count"])
        max_pipeline_stage_count = max(
            max_pipeline_stage_count,
            int(payload["max_pipeline_stage_count"]),
        )

    scenario_count = len(scenarios)
    return {
        "scenario_count": scenario_count,
        "scenarios": _sorted_strings(scenarios),
        "selected_strategies": _sorted_strings(selected_strategies),
        "initial_strategies": _sorted_strings(initial_strategies),
        "degraded_initial_strategies": _sorted_strings(degraded_initial_strategies),
        "selected_latency_ms_mean": round(selected_latency_ms_sum / scenario_count, 3),
        "selected_cost_mean": round(selected_cost_sum / scenario_count, 3),
        "selected_reliability_mean": round(selected_reliability_sum / scenario_count, 4),
        "selected_risk_mean": round(selected_risk_sum / scenario_count, 4),
        "max_pipeline_stage_count": max_pipeline_stage_count,
        "applied_event_count": applied_event_count,
    }


def _validate_data_io_2026_artifact(artifact: ReduceArtifact) -> None:
    payload = artifact.payload
    if int(payload["scenario_count"]) <= 0:
        raise ValueError("mission_decision reducer produced no scenarios")
    if int(payload["max_pipeline_stage_count"]) <= 0:
        raise ValueError("mission_decision reducer produced no pipeline stages")


DATA_IO_2026_REDUCE_CONTRACT = ReduceContract(
    name=REDUCER_NAME,
    artifact_name=REDUCE_ARTIFACT_NAME,
    merge=_merge_data_io_2026_partials,
    validate_partial=require_payload_keys(*_REQUIRED_PAYLOAD_KEYS),
    validate_artifact=_validate_data_io_2026_artifact,
    metadata={
        "app": "mission_decision_project",
        "domain": "mission-decision",
        "scope": "scenario-summary",
    },
)


def reduce_artifact_path(output_dir: Path | str, worker_id: int | str) -> Path:
    filename = REDUCE_ARTIFACT_FILENAME_TEMPLATE.format(worker_id=worker_id)
    return Path(output_dir) / filename


def partial_from_decision_summary(
    metrics: Mapping[str, Any],
    *,
    partial_id: str,
    artifact_path: Path | str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ReducePartial:
    missing = [key for key in _REQUIRED_SUMMARY_KEYS if key not in metrics]
    if missing:
        missing_text = ", ".join(missing)
        raise ValueError(f"data_io_2026 summary metrics missing keys: {missing_text}")

    payload = {
        "scenario_count": 1,
        "scenarios": [str(metrics["scenario"])],
        "selected_strategies": [str(metrics["selected_strategy"])],
        "initial_strategies": [str(metrics["initial_strategy"])],
        "degraded_initial_strategies": [str(metrics["degraded_initial_strategy"])],
        "selected_latency_ms_sum": _as_float(metrics, "latency_ms_selected"),
        "selected_cost_sum": _as_float(metrics, "cost_selected"),
        "selected_reliability_sum": _as_float(metrics, "reliability_selected"),
        "selected_risk_sum": _as_float(metrics, "risk_selected"),
        "max_pipeline_stage_count": _as_int(metrics, "pipeline_stage_count"),
        "applied_event_count": _as_int(metrics, "applied_event_count"),
    }
    return ReducePartial(
        partial_id=partial_id,
        payload=payload,
        metadata=metadata or {},
        artifact_path=str(artifact_path) if artifact_path else None,
    )


def build_reduce_artifact(partials: Sequence[ReducePartial]) -> ReduceArtifact:
    return DATA_IO_2026_REDUCE_CONTRACT.build_artifact(partials)


def write_reduce_artifact(
    metrics: Mapping[str, Any],
    output_dir: Path | str,
    *,
    worker_id: int | str,
) -> Path:
    output_path = reduce_artifact_path(output_dir, worker_id)
    partial = partial_from_decision_summary(
        metrics,
        partial_id=f"mission_decision_worker_{worker_id}_{metrics['artifact_stem']}",
        artifact_path=output_path,
        metadata={
            "worker_id": str(worker_id),
            "artifact_stem": str(metrics.get("artifact_stem", "")),
        },
    )
    artifact = build_reduce_artifact((partial,))
    output_path.write_text(
        json.dumps(artifact.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


__all__ = [
    "DATA_IO_2026_REDUCE_CONTRACT",
    "REDUCE_ARTIFACT_FILENAME_TEMPLATE",
    "REDUCE_ARTIFACT_NAME",
    "REDUCER_NAME",
    "build_reduce_artifact",
    "partial_from_decision_summary",
    "reduce_artifact_path",
    "write_reduce_artifact",
]
