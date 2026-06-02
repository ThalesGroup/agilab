"""Reduce-contract adoption for data quality gate evidence."""

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
REDUCE_ARTIFACT_NAME = "data_quality_gate_reduce_summary"
REDUCER_NAME = "data_quality_gate.evidence.v1"

_REQUIRED_PAYLOAD_KEYS = (
    "run_count",
    "promote_count",
    "manual_review_count",
    "block_count",
    "max_psi",
    "max_ks_statistic",
    "warn_feature_count",
    "block_feature_count",
    "artifact_paths",
)


def _artifact_paths_from_summary(summary: Mapping[str, Any]) -> list[str]:
    artifacts = summary.get("artifacts")
    if not isinstance(artifacts, Mapping):
        return []
    paths: list[str] = []
    for artifact in artifacts.values():
        if isinstance(artifact, Mapping) and artifact.get("path"):
            paths.append(str(artifact["path"]))
    return sorted(set(paths))


def _merge_gate_partials(partials: Sequence[ReducePartial]) -> dict[str, Any]:
    run_count = 0
    promote_count = 0
    manual_review_count = 0
    block_count = 0
    max_psi = 0.0
    max_ks_statistic = 0.0
    warn_feature_count = 0
    block_feature_count = 0
    artifact_paths: set[str] = set()

    for partial in partials:
        payload = partial.payload
        run_count += int(payload["run_count"])
        promote_count += int(payload["promote_count"])
        manual_review_count += int(payload["manual_review_count"])
        block_count += int(payload["block_count"])
        max_psi = max(max_psi, float(payload["max_psi"]))
        max_ks_statistic = max(max_ks_statistic, float(payload["max_ks_statistic"]))
        warn_feature_count += int(payload["warn_feature_count"])
        block_feature_count += int(payload["block_feature_count"])
        artifact_paths.update(str(item) for item in payload["artifact_paths"])

    return {
        "run_count": run_count,
        "promote_count": promote_count,
        "manual_review_count": manual_review_count,
        "block_count": block_count,
        "max_psi": round(max_psi, 6),
        "max_ks_statistic": round(max_ks_statistic, 6),
        "warn_feature_count": warn_feature_count,
        "block_feature_count": block_feature_count,
        "artifact_paths": sorted(artifact_paths),
    }


def _validate_gate_artifact(artifact: ReduceArtifact) -> None:
    if int(artifact.payload["run_count"]) <= 0:
        raise ValueError("data quality gate reducer produced no runs")


DATA_QUALITY_GATE_REDUCE_CONTRACT = ReduceContract(
    name=REDUCER_NAME,
    artifact_name=REDUCE_ARTIFACT_NAME,
    merge=_merge_gate_partials,
    validate_partial=require_payload_keys(*_REQUIRED_PAYLOAD_KEYS),
    validate_artifact=_validate_gate_artifact,
    metadata={
        "app": "data_quality_gate_project",
        "domain": "data-quality",
        "scope": "contract-drift-gate",
    },
)


def reduce_artifact_path(output_dir: Path | str, worker_id: int | str) -> Path:
    filename = REDUCE_ARTIFACT_FILENAME_TEMPLATE.format(worker_id=worker_id)
    return Path(output_dir) / filename


def partial_from_gate_summary(
    summary: Mapping[str, Any],
    *,
    partial_id: str,
    artifact_path: Path | str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ReducePartial:
    decision = str(summary.get("decision") or "")
    drift = summary.get("drift") if isinstance(summary.get("drift"), Mapping) else {}
    payload = {
        "run_count": 1,
        "promote_count": 1 if decision == "promote" else 0,
        "manual_review_count": 1 if decision == "manual-review" else 0,
        "block_count": 1 if decision == "block" else 0,
        "max_psi": float(drift.get("max_psi", 0.0)),
        "max_ks_statistic": float(drift.get("max_ks_statistic", 0.0)),
        "warn_feature_count": int(drift.get("warn_feature_count", 0)),
        "block_feature_count": int(drift.get("block_feature_count", 0)),
        "artifact_paths": _artifact_paths_from_summary(summary),
    }
    return ReducePartial(
        partial_id=partial_id,
        payload=payload,
        metadata=metadata or {},
        artifact_path=str(artifact_path) if artifact_path else None,
    )


def build_reduce_artifact(partials: Sequence[ReducePartial]) -> ReduceArtifact:
    return DATA_QUALITY_GATE_REDUCE_CONTRACT.build_artifact(partials)


def write_reduce_artifact(
    summaries: Sequence[Mapping[str, Any]],
    output_dir: Path | str,
    *,
    worker_id: int | str,
) -> Path:
    output_path = reduce_artifact_path(output_dir, worker_id)
    partials = [
        partial_from_gate_summary(
            summary,
            partial_id=f"data_quality_gate_worker_{worker_id}_{index}",
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
    "DATA_QUALITY_GATE_REDUCE_CONTRACT",
    "REDUCE_ARTIFACT_FILENAME_TEMPLATE",
    "REDUCE_ARTIFACT_NAME",
    "REDUCER_NAME",
    "build_reduce_artifact",
    "partial_from_gate_summary",
    "reduce_artifact_path",
    "write_reduce_artifact",
]
