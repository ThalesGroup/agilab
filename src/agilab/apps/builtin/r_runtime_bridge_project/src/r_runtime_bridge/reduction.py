"""Reduce-contract adoption for R runtime bridge evidence."""

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
REDUCE_ARTIFACT_NAME = "r_runtime_bridge_reduce_summary"
REDUCER_NAME = "r_runtime_bridge.json-artifact.v1"

_REQUIRED_PAYLOAD_KEYS = (
    "run_count",
    "n_sum",
    "mean_sum",
    "sd_sum",
    "artifact_paths",
)


def _artifact_paths_from_summary(summary: Mapping[str, Any]) -> list[str]:
    artifacts = summary.get("artifacts")
    if not isinstance(artifacts, Mapping):
        return []
    paths: set[str] = set()
    for artifact in artifacts.values():
        if isinstance(artifact, Mapping) and artifact.get("path"):
            paths.add(str(artifact["path"]))
    return sorted(paths)


def _metrics_from_summary(summary: Mapping[str, Any]) -> Mapping[str, Any]:
    metrics = summary.get("metrics")
    if not isinstance(metrics, Mapping):
        raise ValueError("R runtime bridge summary missing metrics")
    return metrics


def _merge_r_runtime_bridge_partials(partials: Sequence[ReducePartial]) -> dict[str, Any]:
    run_count = 0
    n_sum = 0
    mean_sum = 0.0
    sd_sum = 0.0
    artifact_paths: set[str] = set()

    for partial in partials:
        payload = partial.payload
        partial_runs = int(payload["run_count"])
        run_count += partial_runs
        n_sum += int(payload["n_sum"])
        mean_sum += float(payload["mean_sum"])
        sd_sum += float(payload["sd_sum"])
        artifact_paths.update(str(item) for item in payload["artifact_paths"])

    return {
        "run_count": run_count,
        "n_sum": n_sum,
        "mean_mean": round(mean_sum / run_count, 6) if run_count else 0.0,
        "sd_mean": round(sd_sum / run_count, 6) if run_count else 0.0,
        "artifact_paths": sorted(artifact_paths),
    }


def _validate_r_runtime_bridge_artifact(artifact: ReduceArtifact) -> None:
    if int(artifact.payload["run_count"]) <= 0:
        raise ValueError("R runtime bridge reducer produced no runs")
    if int(artifact.payload["n_sum"]) <= 0:
        raise ValueError("R runtime bridge reducer produced no input observations")


R_RUNTIME_BRIDGE_REDUCE_CONTRACT = ReduceContract(
    name=REDUCER_NAME,
    artifact_name=REDUCE_ARTIFACT_NAME,
    merge=_merge_r_runtime_bridge_partials,
    validate_partial=require_payload_keys(*_REQUIRED_PAYLOAD_KEYS),
    validate_artifact=_validate_r_runtime_bridge_artifact,
    metadata={
        "app": "r_runtime_bridge_project",
        "runtime": "Rscript",
        "scope": "json-artifact-stage",
    },
)


def reduce_artifact_path(output_dir: Path | str, worker_id: int | str) -> Path:
    filename = REDUCE_ARTIFACT_FILENAME_TEMPLATE.format(worker_id=worker_id)
    return Path(output_dir) / filename


def partial_from_r_runtime_bridge_summary(
    summary: Mapping[str, Any],
    *,
    partial_id: str,
    artifact_path: Path | str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ReducePartial:
    metrics = _metrics_from_summary(summary)
    payload = {
        "run_count": 1,
        "n_sum": int(metrics.get("n", 0)),
        "mean_sum": float(metrics.get("mean", 0.0)),
        "sd_sum": float(metrics.get("sd", 0.0)),
        "artifact_paths": _artifact_paths_from_summary(summary),
    }
    return ReducePartial(
        partial_id=partial_id,
        payload=payload,
        metadata=metadata or {},
        artifact_path=str(artifact_path) if artifact_path else None,
    )


def build_reduce_artifact(partials: Sequence[ReducePartial]) -> ReduceArtifact:
    return R_RUNTIME_BRIDGE_REDUCE_CONTRACT.build_artifact(partials)


def write_reduce_artifact(
    summaries: Sequence[Mapping[str, Any]],
    output_dir: Path | str,
    *,
    worker_id: int | str,
) -> Path:
    output_path = reduce_artifact_path(output_dir, worker_id)
    partials = [
        partial_from_r_runtime_bridge_summary(
            summary,
            partial_id=f"r_runtime_bridge_worker_{worker_id}_{index}",
            artifact_path=output_path,
            metadata={"worker_id": str(worker_id)},
        )
        for index, summary in enumerate(summaries)
    ]
    artifact = build_reduce_artifact(partials)
    output_path.write_text(
        json.dumps(artifact.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


__all__ = [
    "REDUCE_ARTIFACT_FILENAME_TEMPLATE",
    "REDUCE_ARTIFACT_NAME",
    "REDUCER_NAME",
    "R_RUNTIME_BRIDGE_REDUCE_CONTRACT",
    "build_reduce_artifact",
    "partial_from_r_runtime_bridge_summary",
    "reduce_artifact_path",
    "write_reduce_artifact",
]
