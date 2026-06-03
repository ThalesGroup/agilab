"""Reduce-contract adoption for the built-in pandas execution app."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from agi_node.reduction import (
    ReduceArtifact,
    ReduceContract,
    ReducePartial,
    require_payload_keys,
)


REDUCE_ARTIFACT_FILENAME_TEMPLATE = "reduce_summary_worker_{worker_id}.json"
REDUCE_ARTIFACT_NAME = "execution_pandas_reduce_summary"
REDUCER_NAME = "execution_pandas.weighted-score.v1"

_REQUIRED_FRAME_COLUMNS = frozenset(
    {
        "row_count",
        "x_sum",
        "weight_sum",
        "weighted_score",
        "python_tail_checksum",
        "kernel_mode",
        "kernel_runtime",
        "dtype_contract",
        "source_file",
        "engine",
        "execution_model",
    }
)

_REQUIRED_PAYLOAD_KEYS = (
    "row_count",
    "result_rows",
    "source_file_count",
    "x_sum",
    "weight_sum",
    "weighted_score_sum",
    "python_tail_checksum",
    "kernel_modes",
    "kernel_runtimes",
    "dtype_contracts",
    "source_files",
    "engines",
    "execution_models",
)


def _sorted_unique_strings(values: pd.Series) -> list[str]:
    return sorted({str(value) for value in values.dropna().tolist()})


def _merge_execution_pandas_partials(partials: Sequence[ReducePartial]) -> dict[str, Any]:
    source_files: set[str] = set()
    engines: set[str] = set()
    execution_models: set[str] = set()
    kernel_modes: set[str] = set()
    kernel_runtimes: set[str] = set()
    dtype_contracts: set[str] = set()
    payload: dict[str, Any] = {
        "row_count": 0,
        "result_rows": 0,
        "source_file_count": 0,
        "x_sum": 0.0,
        "weight_sum": 0.0,
        "weighted_score_sum": 0.0,
        "python_tail_checksum": 0.0,
    }

    for partial in partials:
        partial_payload = partial.payload
        payload["row_count"] += int(partial_payload["row_count"])
        payload["result_rows"] += int(partial_payload["result_rows"])
        payload["x_sum"] += float(partial_payload["x_sum"])
        payload["weight_sum"] += float(partial_payload["weight_sum"])
        payload["weighted_score_sum"] += float(partial_payload["weighted_score_sum"])
        payload["python_tail_checksum"] += float(partial_payload["python_tail_checksum"])
        source_files.update(str(item) for item in partial_payload["source_files"])
        engines.update(str(item) for item in partial_payload["engines"])
        execution_models.update(str(item) for item in partial_payload["execution_models"])
        kernel_modes.update(str(item) for item in partial_payload["kernel_modes"])
        kernel_runtimes.update(str(item) for item in partial_payload["kernel_runtimes"])
        dtype_contracts.update(str(item) for item in partial_payload["dtype_contracts"])

    payload["source_files"] = sorted(source_files)
    payload["source_file_count"] = len(source_files)
    payload["engines"] = sorted(engines)
    payload["execution_models"] = sorted(execution_models)
    payload["kernel_modes"] = sorted(kernel_modes)
    payload["kernel_runtimes"] = sorted(kernel_runtimes)
    payload["dtype_contracts"] = sorted(dtype_contracts)
    return payload


def _validate_execution_pandas_artifact(artifact: ReduceArtifact) -> None:
    payload = artifact.payload
    if int(payload["row_count"]) <= 0:
        raise ValueError("execution_pandas reducer produced no source rows")
    if int(payload["source_file_count"]) <= 0:
        raise ValueError("execution_pandas reducer produced no source files")
    if not payload["engines"]:
        raise ValueError("execution_pandas reducer produced no engine metadata")
    if not payload["kernel_modes"]:
        raise ValueError("execution_pandas reducer produced no kernel metadata")


EXECUTION_PANDAS_REDUCE_CONTRACT = ReduceContract(
    name=REDUCER_NAME,
    artifact_name=REDUCE_ARTIFACT_NAME,
    merge=_merge_execution_pandas_partials,
    validate_partial=require_payload_keys(*_REQUIRED_PAYLOAD_KEYS),
    validate_artifact=_validate_execution_pandas_artifact,
    metadata={
        "app": "execution_pandas_project",
        "engine": "pandas",
        "scope": "worker-result",
    },
)


def reduce_artifact_path(output_dir: Path | str, worker_id: int | str) -> Path:
    filename = REDUCE_ARTIFACT_FILENAME_TEMPLATE.format(worker_id=worker_id)
    return Path(output_dir) / filename


def partial_from_result_frame(
    df: pd.DataFrame,
    *,
    partial_id: str,
    artifact_path: Path | str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ReducePartial:
    if df is None or df.empty:
        raise ValueError("execution_pandas reducer requires a non-empty result frame")

    missing = sorted(_REQUIRED_FRAME_COLUMNS.difference(df.columns))
    if missing:
        raise ValueError(f"execution_pandas result frame missing columns: {', '.join(missing)}")

    source_files = _sorted_unique_strings(df["source_file"])
    checksum_by_file = df.groupby("source_file", dropna=False)["python_tail_checksum"].first()
    payload = {
        "row_count": int(df["row_count"].sum()),
        "result_rows": int(len(df)),
        "source_file_count": len(source_files),
        "x_sum": float(df["x_sum"].sum()),
        "weight_sum": float(df["weight_sum"].sum()),
        "weighted_score_sum": float(df["weighted_score"].sum()),
        "python_tail_checksum": float(checksum_by_file.sum()),
        "kernel_modes": _sorted_unique_strings(df["kernel_mode"]),
        "kernel_runtimes": _sorted_unique_strings(df["kernel_runtime"]),
        "dtype_contracts": _sorted_unique_strings(df["dtype_contract"]),
        "source_files": source_files,
        "engines": _sorted_unique_strings(df["engine"]),
        "execution_models": _sorted_unique_strings(df["execution_model"]),
    }
    return ReducePartial(
        partial_id=partial_id,
        payload=payload,
        metadata=metadata or {},
        artifact_path=str(artifact_path) if artifact_path else None,
    )


def build_reduce_artifact(partials: Sequence[ReducePartial]) -> ReduceArtifact:
    return EXECUTION_PANDAS_REDUCE_CONTRACT.build_artifact(partials)


def write_reduce_artifact(
    df: pd.DataFrame,
    output_dir: Path | str,
    *,
    worker_id: int | str,
) -> Path:
    output_path = reduce_artifact_path(output_dir, worker_id)
    partial = partial_from_result_frame(
        df,
        partial_id=f"execution_pandas_worker_{worker_id}",
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
    "EXECUTION_PANDAS_REDUCE_CONTRACT",
    "REDUCE_ARTIFACT_FILENAME_TEMPLATE",
    "REDUCE_ARTIFACT_NAME",
    "REDUCER_NAME",
    "build_reduce_artifact",
    "partial_from_result_frame",
    "reduce_artifact_path",
    "write_reduce_artifact",
]
