"""Reduce-contract adoption for the built-in Flight app."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from agi_node.reduction import (
    ReduceArtifact,
    ReduceContract,
    ReducePartial,
    require_payload_keys,
)


REDUCE_ARTIFACT_FILENAME_TEMPLATE = "reduce_summary_worker_{worker_id}.json"
REDUCE_ARTIFACT_NAME = "flight_reduce_summary"
REDUCER_NAME = "flight.trajectory-metrics.v1"

_REQUIRED_FRAME_COLUMNS = frozenset(
    {
        "aircraft",
        "date",
        "speed",
        "source_file",
    }
)
_REQUIRED_PAYLOAD_KEYS = (
    "flight_run_count",
    "row_count",
    "source_file_count",
    "aircraft_count",
    "speed_count",
    "speed_sum_m",
    "max_speed_m",
    "source_files",
    "aircraft",
    "output_file_count",
    "output_files",
    "output_formats",
    "time_start",
    "time_end",
)


def _sorted_unique_strings(values: pl.Series) -> list[str]:
    return sorted({str(value) for value in values.drop_nulls().to_list() if str(value)})


def _sorted_strings(values: set[str]) -> list[str]:
    return sorted(value for value in values if value)


def _timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value) if value is not None else ""


def _merge_flight_partials(partials: Sequence[ReducePartial]) -> dict[str, Any]:
    source_files: set[str] = set()
    aircraft: set[str] = set()
    output_files: set[str] = set()
    output_formats: set[str] = set()
    row_count = 0
    speed_count = 0
    speed_sum_m = 0.0
    max_speed_m = 0.0
    time_start = ""
    time_end = ""

    for partial in partials:
        payload = partial.payload
        row_count += int(payload["row_count"])
        speed_count += int(payload["speed_count"])
        speed_sum_m += float(payload["speed_sum_m"])
        max_speed_m = max(max_speed_m, float(payload["max_speed_m"]))
        source_files.update(str(item) for item in payload["source_files"])
        aircraft.update(str(item) for item in payload["aircraft"])
        output_files.update(str(item) for item in payload["output_files"])
        output_formats.update(str(item) for item in payload["output_formats"])
        candidate_start = str(payload["time_start"])
        candidate_end = str(payload["time_end"])
        if candidate_start and (not time_start or candidate_start < time_start):
            time_start = candidate_start
        if candidate_end and (not time_end or candidate_end > time_end):
            time_end = candidate_end

    return {
        "flight_run_count": len(partials),
        "row_count": row_count,
        "source_file_count": len(source_files),
        "source_files": _sorted_strings(source_files),
        "aircraft_count": len(aircraft),
        "aircraft": _sorted_strings(aircraft),
        "output_file_count": len(output_files),
        "output_files": _sorted_strings(output_files),
        "output_formats": _sorted_strings(output_formats),
        "speed_count": speed_count,
        "speed_sum_m": round(speed_sum_m, 3),
        "mean_speed_m": round(speed_sum_m / speed_count, 3) if speed_count else 0.0,
        "max_speed_m": round(max_speed_m, 3),
        "time_start": time_start,
        "time_end": time_end,
    }


def _validate_flight_artifact(artifact: ReduceArtifact) -> None:
    payload = artifact.payload
    if int(payload["row_count"]) <= 0:
        raise ValueError("flight reducer produced no trajectory rows")
    if int(payload["aircraft_count"]) <= 0:
        raise ValueError("flight reducer produced no aircraft metadata")
    if int(payload["source_file_count"]) <= 0:
        raise ValueError("flight reducer produced no source files")


FLIGHT_REDUCE_CONTRACT = ReduceContract(
    name=REDUCER_NAME,
    artifact_name=REDUCE_ARTIFACT_NAME,
    merge=_merge_flight_partials,
    validate_partial=require_payload_keys(*_REQUIRED_PAYLOAD_KEYS),
    validate_artifact=_validate_flight_artifact,
    metadata={
        "app": "flight_project",
        "domain": "flight-telemetry",
        "scope": "trajectory-summary",
    },
)


def reduce_artifact_path(output_dir: Path | str, worker_id: int | str) -> Path:
    filename = REDUCE_ARTIFACT_FILENAME_TEMPLATE.format(worker_id=worker_id)
    return Path(output_dir) / filename


def partial_from_flight_frame(
    df: pl.DataFrame,
    *,
    partial_id: str,
    output_files: Sequence[str | Path] = (),
    output_format: str = "",
    artifact_path: Path | str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ReducePartial:
    if df is None or df.is_empty():
        raise ValueError("flight reducer requires a non-empty trajectory frame")

    missing = sorted(_REQUIRED_FRAME_COLUMNS.difference(df.columns))
    if missing:
        raise ValueError(f"flight result frame missing columns: {', '.join(missing)}")

    speed_values = df["speed"].drop_nulls()
    speed_count = len(speed_values)
    output_file_names = sorted({Path(str(path)).name for path in output_files if str(path)})
    payload = {
        "flight_run_count": 1,
        "row_count": int(df.height),
        "source_file_count": len(_sorted_unique_strings(df["source_file"])),
        "source_files": _sorted_unique_strings(df["source_file"]),
        "aircraft_count": len(_sorted_unique_strings(df["aircraft"])),
        "aircraft": _sorted_unique_strings(df["aircraft"]),
        "output_file_count": len(output_file_names),
        "output_files": output_file_names,
        "output_formats": [str(output_format)] if output_format else [],
        "speed_count": speed_count,
        "speed_sum_m": float(speed_values.sum()) if speed_count else 0.0,
        "max_speed_m": float(speed_values.max()) if speed_count else 0.0,
        "time_start": _timestamp(df["date"].min()),
        "time_end": _timestamp(df["date"].max()),
    }
    return ReducePartial(
        partial_id=partial_id,
        payload=payload,
        metadata=metadata or {},
        artifact_path=str(artifact_path) if artifact_path else None,
    )


def build_reduce_artifact(partials: Sequence[ReducePartial]) -> ReduceArtifact:
    return FLIGHT_REDUCE_CONTRACT.build_artifact(partials)


def write_reduce_artifact(
    df: pl.DataFrame,
    output_dir: Path | str,
    *,
    worker_id: int | str,
    output_files: Sequence[str | Path] = (),
    output_format: str = "",
) -> Path:
    output_path = reduce_artifact_path(output_dir, worker_id)
    partial = partial_from_flight_frame(
        df,
        partial_id=f"flight_worker_{worker_id}",
        output_files=output_files,
        output_format=output_format,
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
    "FLIGHT_REDUCE_CONTRACT",
    "REDUCE_ARTIFACT_FILENAME_TEMPLATE",
    "REDUCE_ARTIFACT_NAME",
    "REDUCER_NAME",
    "build_reduce_artifact",
    "partial_from_flight_frame",
    "reduce_artifact_path",
    "write_reduce_artifact",
]
