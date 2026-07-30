"""Historical reducer identity backed by the current forecast merge semantics."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from agi_node.reduction import ReduceArtifact, ReduceContract, ReducePartial
from weather_forecast import reduction as current_reduction

REDUCE_ARTIFACT_FILENAME_TEMPLATE = (
    current_reduction.REDUCE_ARTIFACT_FILENAME_TEMPLATE
)
REDUCE_ARTIFACT_NAME = "weather_forecast_legacy_reduce_summary"
REDUCER_NAME = "weather_forecast_legacy.forecast-metrics.v1"
reduce_artifact_path = current_reduction.reduce_artifact_path


WEATHER_FORECAST_LEGACY_REDUCE_CONTRACT = ReduceContract(
    name=REDUCER_NAME,
    artifact_name=REDUCE_ARTIFACT_NAME,
    merge=current_reduction.WEATHER_FORECAST_REDUCE_CONTRACT.merge,
    validate_partial=(
        current_reduction.WEATHER_FORECAST_REDUCE_CONTRACT.validate_partial
    ),
    validate_artifact=(
        current_reduction.WEATHER_FORECAST_REDUCE_CONTRACT.validate_artifact
    ),
    metadata={
        "app": "weather_forecast_legacy_project",
        "domain": "weather-forecast",
        "scope": "forecast-metrics",
    },
)


def partial_from_forecast_metrics(
    metrics: Mapping[str, Any],
    *,
    partial_id: str,
    artifact_path: Path | str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ReducePartial:
    return current_reduction.partial_from_forecast_metrics(
        metrics,
        partial_id=partial_id,
        artifact_path=artifact_path,
        metadata=metadata,
    )


def build_reduce_artifact(partials: Sequence[ReducePartial]) -> ReduceArtifact:
    return WEATHER_FORECAST_LEGACY_REDUCE_CONTRACT.build_artifact(partials)


def write_reduce_artifact(
    metrics: Mapping[str, Any],
    output_dir: Path | str,
    *,
    worker_id: int | str,
) -> Path:
    output_path = reduce_artifact_path(output_dir, worker_id)
    partial = partial_from_forecast_metrics(
        metrics,
        partial_id=f"weather_forecast_legacy_worker_{worker_id}",
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
    "REDUCER_NAME",
    "REDUCE_ARTIFACT_FILENAME_TEMPLATE",
    "REDUCE_ARTIFACT_NAME",
    "WEATHER_FORECAST_LEGACY_REDUCE_CONTRACT",
    "build_reduce_artifact",
    "partial_from_forecast_metrics",
    "reduce_artifact_path",
    "write_reduce_artifact",
]
