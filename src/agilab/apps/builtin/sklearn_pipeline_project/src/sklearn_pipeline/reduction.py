"""Reduce-contract adoption for sklearn pipeline evidence."""

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
REDUCE_ARTIFACT_NAME = "sklearn_pipeline_reduce_summary"
REDUCER_NAME = "sklearn_pipeline.model-evidence.v1"

_REQUIRED_PAYLOAD_KEYS = (
    "run_count",
    "train_rows",
    "test_rows",
    "accuracy_sum",
    "f1_sum",
    "promotion_candidate_count",
    "artifact_paths",
)


def _metrics_from_summary(summary: Mapping[str, Any]) -> Mapping[str, Any]:
    metrics = summary.get("metrics")
    if not isinstance(metrics, Mapping):
        raise ValueError("sklearn pipeline summary missing metrics")
    return metrics


def _artifact_paths_from_summary(summary: Mapping[str, Any]) -> list[str]:
    artifacts = summary.get("artifacts")
    if not isinstance(artifacts, Mapping):
        return []
    paths: list[str] = []
    for artifact in artifacts.values():
        if isinstance(artifact, Mapping) and artifact.get("path"):
            paths.append(str(artifact["path"]))
    return sorted(set(paths))


def _merge_sklearn_partials(partials: Sequence[ReducePartial]) -> dict[str, Any]:
    run_count = 0
    train_rows = 0
    test_rows = 0
    accuracy_sum = 0.0
    f1_sum = 0.0
    promotion_candidate_count = 0
    artifact_paths: set[str] = set()

    for partial in partials:
        payload = partial.payload
        partial_runs = int(payload["run_count"])
        run_count += partial_runs
        train_rows += int(payload["train_rows"])
        test_rows += int(payload["test_rows"])
        accuracy_sum += float(payload["accuracy_sum"])
        f1_sum += float(payload["f1_sum"])
        promotion_candidate_count += int(payload["promotion_candidate_count"])
        artifact_paths.update(str(item) for item in payload["artifact_paths"])

    return {
        "run_count": run_count,
        "train_rows": train_rows,
        "test_rows": test_rows,
        "accuracy_mean": round(accuracy_sum / run_count, 6) if run_count else 0.0,
        "f1_mean": round(f1_sum / run_count, 6) if run_count else 0.0,
        "promotion_candidate_count": promotion_candidate_count,
        "artifact_paths": sorted(artifact_paths),
    }


def _validate_sklearn_artifact(artifact: ReduceArtifact) -> None:
    if int(artifact.payload["run_count"]) <= 0:
        raise ValueError("sklearn pipeline reducer produced no runs")
    if int(artifact.payload["test_rows"]) <= 0:
        raise ValueError("sklearn pipeline reducer produced no test rows")


SKLEARN_PIPELINE_REDUCE_CONTRACT = ReduceContract(
    name=REDUCER_NAME,
    artifact_name=REDUCE_ARTIFACT_NAME,
    merge=_merge_sklearn_partials,
    validate_partial=require_payload_keys(*_REQUIRED_PAYLOAD_KEYS),
    validate_artifact=_validate_sklearn_artifact,
    metadata={
        "app": "sklearn_pipeline_project",
        "domain": "classic-ml",
        "scope": "model-evidence",
    },
)


def reduce_artifact_path(output_dir: Path | str, worker_id: int | str) -> Path:
    filename = REDUCE_ARTIFACT_FILENAME_TEMPLATE.format(worker_id=worker_id)
    return Path(output_dir) / filename


def partial_from_sklearn_summary(
    summary: Mapping[str, Any],
    *,
    partial_id: str,
    artifact_path: Path | str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ReducePartial:
    metrics = _metrics_from_summary(summary)
    promotion_hint = str(summary.get("promotion_hint") or summary.get("manifest", ""))
    payload = {
        "run_count": 1,
        "train_rows": int(metrics.get("train_rows", 0)),
        "test_rows": int(metrics.get("test_rows", 0)),
        "accuracy_sum": float(metrics.get("accuracy", 0.0)),
        "f1_sum": float(metrics.get("f1", 0.0)),
        "promotion_candidate_count": 1 if promotion_hint == "candidate" else 0,
        "artifact_paths": _artifact_paths_from_summary(summary),
    }
    return ReducePartial(
        partial_id=partial_id,
        payload=payload,
        metadata=metadata or {},
        artifact_path=str(artifact_path) if artifact_path else None,
    )


def build_reduce_artifact(partials: Sequence[ReducePartial]) -> ReduceArtifact:
    return SKLEARN_PIPELINE_REDUCE_CONTRACT.build_artifact(partials)


def write_reduce_artifact(
    summaries: Sequence[Mapping[str, Any]],
    output_dir: Path | str,
    *,
    worker_id: int | str,
) -> Path:
    output_path = reduce_artifact_path(output_dir, worker_id)
    partials = [
        partial_from_sklearn_summary(
            summary,
            partial_id=f"sklearn_pipeline_worker_{worker_id}_{index}",
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
    "SKLEARN_PIPELINE_REDUCE_CONTRACT",
    "build_reduce_artifact",
    "partial_from_sklearn_summary",
    "reduce_artifact_path",
    "write_reduce_artifact",
]
