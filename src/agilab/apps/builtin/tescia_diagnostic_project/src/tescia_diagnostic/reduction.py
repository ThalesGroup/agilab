"""Reduce-contract adoption for TeSciA diagnostic summaries."""

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
REDUCE_ARTIFACT_NAME = "tescia_diagnostic_reduce_summary"
REDUCER_NAME = "tescia_diagnostic.case-summary.v1"

_REQUIRED_SUMMARY_KEYS = (
    "case_id",
    "status",
    "root_cause",
    "selected_fix_id",
    "evidence_quality",
    "regression_coverage",
    "weak_assumption_count",
    "regression_step_count",
)
_REQUIRED_PAYLOAD_KEYS = (
    "case_count",
    "actionable_count",
    "needs_more_evidence_count",
    "evidence_quality_sum",
    "regression_coverage_sum",
    "case_ids",
    "selected_fix_ids",
)


def _merge_tescia_partials(partials: Sequence[ReducePartial]) -> dict[str, Any]:
    case_ids: set[str] = set()
    selected_fix_ids: set[str] = set()
    evidence_sum = 0.0
    regression_sum = 0.0
    actionable_count = 0
    needs_more_evidence_count = 0

    for partial in partials:
        payload = partial.payload
        case_ids.update(str(item) for item in payload["case_ids"])
        selected_fix_ids.update(str(item) for item in payload["selected_fix_ids"] if item)
        evidence_sum += float(payload["evidence_quality_sum"])
        regression_sum += float(payload["regression_coverage_sum"])
        actionable_count += int(payload["actionable_count"])
        needs_more_evidence_count += int(payload["needs_more_evidence_count"])

    case_count = len(case_ids)
    return {
        "case_count": case_count,
        "actionable_count": actionable_count,
        "needs_more_evidence_count": needs_more_evidence_count,
        "evidence_quality_mean": round(evidence_sum / case_count, 4) if case_count else 0.0,
        "regression_coverage_mean": round(regression_sum / case_count, 4) if case_count else 0.0,
        "case_ids": sorted(case_ids),
        "selected_fix_ids": sorted(selected_fix_ids),
    }


def _validate_tescia_artifact(artifact: ReduceArtifact) -> None:
    if int(artifact.payload["case_count"]) <= 0:
        raise ValueError("tescia diagnostic reducer produced no cases")


TESCIA_DIAGNOSTIC_REDUCE_CONTRACT = ReduceContract(
    name=REDUCER_NAME,
    artifact_name=REDUCE_ARTIFACT_NAME,
    merge=_merge_tescia_partials,
    validate_partial=require_payload_keys(*_REQUIRED_PAYLOAD_KEYS),
    validate_artifact=_validate_tescia_artifact,
    metadata={
        "app": "tescia_diagnostic_project",
        "domain": "engineering-diagnostic",
        "scope": "case-summary",
    },
)


def reduce_artifact_path(output_dir: Path | str, worker_id: int | str) -> Path:
    filename = REDUCE_ARTIFACT_FILENAME_TEMPLATE.format(worker_id=worker_id)
    return Path(output_dir) / filename


def partial_from_diagnostic_summary(
    summary: Mapping[str, Any],
    *,
    partial_id: str,
    artifact_path: Path | str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ReducePartial:
    missing = [key for key in _REQUIRED_SUMMARY_KEYS if key not in summary]
    if missing:
        missing_text = ", ".join(missing)
        raise ValueError(f"tescia diagnostic summary missing columns: {missing_text}")

    status = str(summary["status"])
    payload = {
        "case_count": 1,
        "case_ids": [str(summary["case_id"])],
        "selected_fix_ids": [str(summary["selected_fix_id"])] if summary["selected_fix_id"] else [],
        "evidence_quality_sum": float(summary["evidence_quality"]),
        "regression_coverage_sum": float(summary["regression_coverage"]),
        "actionable_count": 1 if status == "actionable" else 0,
        "needs_more_evidence_count": 1 if status != "actionable" else 0,
    }
    return ReducePartial(
        partial_id=partial_id,
        payload=payload,
        metadata=metadata or {},
        artifact_path=str(artifact_path) if artifact_path else None,
    )


def build_reduce_artifact(partials: Sequence[ReducePartial]) -> ReduceArtifact:
    return TESCIA_DIAGNOSTIC_REDUCE_CONTRACT.build_artifact(partials)


def write_reduce_artifact(
    summaries: Sequence[Mapping[str, Any]],
    output_dir: Path | str,
    *,
    worker_id: int | str,
) -> Path:
    output_path = reduce_artifact_path(output_dir, worker_id)
    partials = [
        partial_from_diagnostic_summary(
            summary,
            partial_id=f"tescia_case_{summary['case_id']}",
            artifact_path=output_path,
            metadata={"worker_id": str(worker_id)},
        )
        for summary in summaries
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
    "TESCIA_DIAGNOSTIC_REDUCE_CONTRACT",
    "build_reduce_artifact",
    "partial_from_diagnostic_summary",
    "reduce_artifact_path",
    "write_reduce_artifact",
]
