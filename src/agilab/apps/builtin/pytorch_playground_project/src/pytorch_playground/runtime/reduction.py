"""Reduce-contract adoption for the built-in PyTorch playground app."""

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
    "validation_run_count",
    "train_accuracy_weighted_sum",
    "validation_accuracy_weighted_sum",
    "validation_loss_weighted_sum",
    "loss_landscape_points",
    "backends",
    "hidden_layer_shapes",
)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _strings(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return sorted(str(item) for item in value if str(item))
    if value is None or value == "":
        return []
    return [str(value)]


def _merge_pytorch_playground_partials(partials: Sequence[ReducePartial]) -> dict[str, Any]:
    backends: set[str] = set()
    hidden_layer_shapes: set[str] = set()
    run_count = 0
    sample_count = 0
    feature_count = 0
    validation_run_count = 0
    train_accuracy_weighted_sum = 0.0
    validation_accuracy_weighted_sum = 0.0
    validation_loss_weighted_sum = 0.0
    loss_landscape_points = 0

    for partial in partials:
        payload = partial.payload
        partial_runs = _as_int(payload["run_count"])
        partial_validation_runs = _as_int(payload["validation_run_count"])
        run_count += partial_runs
        sample_count += _as_int(payload["sample_count"])
        feature_count = max(feature_count, _as_int(payload["feature_count"]))
        validation_run_count += partial_validation_runs
        train_accuracy_weighted_sum += _as_float(payload["train_accuracy_weighted_sum"])
        validation_accuracy_weighted_sum += _as_float(payload["validation_accuracy_weighted_sum"])
        validation_loss_weighted_sum += _as_float(payload["validation_loss_weighted_sum"])
        loss_landscape_points += _as_int(payload["loss_landscape_points"])
        backends.update(str(item) for item in payload["backends"])
        hidden_layer_shapes.update(str(item) for item in payload["hidden_layer_shapes"])

    return {
        "run_count": run_count,
        "sample_count": sample_count,
        "feature_count": feature_count,
        "validation_run_count": validation_run_count,
        "train_accuracy": (
            round(train_accuracy_weighted_sum / validation_run_count, 6)
            if validation_run_count
            else None
        ),
        "validation_accuracy": (
            round(validation_accuracy_weighted_sum / validation_run_count, 6)
            if validation_run_count
            else None
        ),
        "validation_loss": (
            round(validation_loss_weighted_sum / validation_run_count, 6)
            if validation_run_count
            else None
        ),
        "loss_landscape_points": loss_landscape_points,
        "backends": sorted(backends),
        "hidden_layer_shapes": sorted(hidden_layer_shapes),
    }


def _validate_pytorch_playground_artifact(artifact: ReduceArtifact) -> None:
    payload = artifact.payload
    if int(payload["run_count"]) <= 0:
        raise ValueError("pytorch_playground reducer produced no runs")
    if int(payload["sample_count"]) <= 0:
        raise ValueError("pytorch_playground reducer produced no samples")
    if not payload["backends"]:
        raise ValueError("pytorch_playground reducer produced no backend metadata")


PYTORCH_PLAYGROUND_REDUCE_CONTRACT = ReduceContract(
    name=REDUCER_NAME,
    artifact_name=REDUCE_ARTIFACT_NAME,
    merge=_merge_pytorch_playground_partials,
    validate_partial=require_payload_keys(*_REQUIRED_PAYLOAD_KEYS),
    validate_artifact=_validate_pytorch_playground_artifact,
    metadata={
        "app": "pytorch_playground_project",
        "domain": "classifier-playground",
        "scope": "training-summary",
    },
)


def reduce_artifact_path(output_dir: Path | str, worker_id: int | str) -> Path:
    filename = REDUCE_ARTIFACT_FILENAME_TEMPLATE.format(worker_id=worker_id)
    return Path(output_dir) / filename


def partial_from_summary(
    summary: Mapping[str, Any],
    *,
    partial_id: str,
    artifact_path: Path | str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ReducePartial:
    validation_run_count = (
        1
        if "validation_accuracy" in summary
        and "validation_loss" in summary
        and summary.get("validation_accuracy") is not None
        else 0
    )
    payload = {
        "run_count": 1,
        "sample_count": _as_int(summary.get("samples")),
        "feature_count": _as_int(summary.get("features")),
        "validation_run_count": validation_run_count,
        "train_accuracy_weighted_sum": _as_float(summary.get("train_accuracy")) * validation_run_count,
        "validation_accuracy_weighted_sum": (
            _as_float(summary.get("validation_accuracy")) * validation_run_count
        ),
        "validation_loss_weighted_sum": _as_float(summary.get("validation_loss")) * validation_run_count,
        "loss_landscape_points": _as_int(summary.get("loss_landscape_points")),
        "backends": _strings(summary.get("backend", "unknown")),
        "hidden_layer_shapes": _strings(summary.get("hidden_layers")),
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
    summary: Mapping[str, Any],
    output_dir: Path | str,
    *,
    worker_id: int | str,
) -> Path:
    output_path = reduce_artifact_path(output_dir, worker_id)
    partial = partial_from_summary(
        summary,
        partial_id=f"pytorch_playground_worker_{worker_id}",
        artifact_path=output_path,
        metadata={"worker_id": str(worker_id)},
    )
    artifact = build_reduce_artifact((partial,))
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
    "partial_from_summary",
    "reduce_artifact_path",
    "write_reduce_artifact",
]
