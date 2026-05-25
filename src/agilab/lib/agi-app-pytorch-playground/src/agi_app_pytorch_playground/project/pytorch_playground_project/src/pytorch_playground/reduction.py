"""Reduce-contract adoption for PyTorch playground training summaries."""

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
REDUCE_ARTIFACT_NAME = "pytorch_playground_reduce_summary"
REDUCER_NAME = "pytorch_playground.training-summary.v1"

_REQUIRED_PAYLOAD_KEYS = (
    "run_count",
    "sample_count",
    "feature_count",
    "train_accuracy_sum",
    "validation_accuracy_sum",
    "validation_loss_sum",
    "loss_landscape_point_count",
    "backends",
)


def _merge_playground_partials(partials: Sequence[ReducePartial]) -> dict[str, Any]:
    run_count = 0
    sample_count = 0
    feature_count = 0
    train_accuracy_sum = 0.0
    validation_accuracy_sum = 0.0
    validation_loss_sum = 0.0
    loss_landscape_point_count = 0
    backends: set[str] = set()
    hidden_layers: set[str] = set()

    for partial in partials:
        payload = partial.payload
        partial_runs = int(payload["run_count"])
        run_count += partial_runs
        sample_count += int(payload["sample_count"])
        feature_count = max(feature_count, int(payload["feature_count"]))
        train_accuracy_sum += float(payload["train_accuracy_sum"])
        validation_accuracy_sum += float(payload["validation_accuracy_sum"])
        validation_loss_sum += float(payload["validation_loss_sum"])
        loss_landscape_point_count += int(payload["loss_landscape_point_count"])
        backends.update(str(item) for item in payload["backends"])
        hidden_layers.update(str(item) for item in payload.get("hidden_layers", []))

    return {
        "run_count": run_count,
        "sample_count": sample_count,
        "feature_count": feature_count,
        "train_accuracy_mean": round(train_accuracy_sum / run_count, 6) if run_count else 0.0,
        "validation_accuracy_mean": round(validation_accuracy_sum / run_count, 6) if run_count else 0.0,
        "validation_loss_mean": round(validation_loss_sum / run_count, 6) if run_count else 0.0,
        "loss_landscape_point_count": loss_landscape_point_count,
        "backends": sorted(backends),
        "hidden_layers": sorted(hidden_layers),
    }


def _validate_playground_artifact(artifact: ReduceArtifact) -> None:
    if int(artifact.payload["run_count"]) <= 0:
        raise ValueError("pytorch playground reducer produced no runs")
    if int(artifact.payload["sample_count"]) <= 0:
        raise ValueError("pytorch playground reducer produced no samples")


PYTORCH_PLAYGROUND_REDUCE_CONTRACT = ReduceContract(
    name=REDUCER_NAME,
    artifact_name=REDUCE_ARTIFACT_NAME,
    merge=_merge_playground_partials,
    validate_partial=require_payload_keys(*_REQUIRED_PAYLOAD_KEYS),
    validate_artifact=_validate_playground_artifact,
    metadata={
        "app": "pytorch_playground_project",
        "domain": "neural-network-playground",
        "scope": "training-summary",
    },
)


def reduce_artifact_path(output_dir: Path | str, worker_id: int | str) -> Path:
    filename = REDUCE_ARTIFACT_FILENAME_TEMPLATE.format(worker_id=worker_id)
    return Path(output_dir) / filename


def partial_from_playground_summary(
    summary: Mapping[str, Any],
    *,
    partial_id: str,
    artifact_path: Path | str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ReducePartial:
    hidden_layers = summary.get("hidden_layers", [])
    if not isinstance(hidden_layers, Sequence) or isinstance(hidden_layers, (str, bytes)):
        hidden_layers = []
    payload = {
        "run_count": 1,
        "sample_count": int(summary.get("samples", 0)),
        "feature_count": int(summary.get("features", 0)),
        "train_accuracy_sum": float(summary.get("train_accuracy", 0.0)),
        "validation_accuracy_sum": float(summary.get("validation_accuracy", 0.0)),
        "validation_loss_sum": float(summary.get("validation_loss", 0.0)),
        "loss_landscape_point_count": int(summary.get("loss_landscape_points", 0)),
        "backends": [str(summary.get("backend", "unknown"))],
        "hidden_layers": [str(item) for item in hidden_layers],
    }
    return ReducePartial(
        partial_id=partial_id,
        payload=payload,
        metadata=metadata or {},
        artifact_path=str(artifact_path) if artifact_path else None,
    )


def build_reduce_artifact(partials: Sequence[ReducePartial]) -> ReduceArtifact:
    return PYTORCH_PLAYGROUND_REDUCE_CONTRACT.build_artifact(partials)


def write_reduce_artifact(
    summaries: Sequence[Mapping[str, Any]],
    output_dir: Path | str,
    *,
    worker_id: int | str,
) -> Path:
    output_path = reduce_artifact_path(output_dir, worker_id)
    partials = [
        partial_from_playground_summary(
            summary,
            partial_id=f"pytorch_playground_worker_{worker_id}_{index}",
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
    "PYTORCH_PLAYGROUND_REDUCE_CONTRACT",
    "REDUCE_ARTIFACT_FILENAME_TEMPLATE",
    "REDUCE_ARTIFACT_NAME",
    "REDUCER_NAME",
    "build_reduce_artifact",
    "partial_from_playground_summary",
    "reduce_artifact_path",
    "write_reduce_artifact",
]
