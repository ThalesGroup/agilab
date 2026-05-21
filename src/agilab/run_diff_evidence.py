# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Run-diff and counterfactual evidence contract for AGILAB public reports."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


SCHEMA = "agilab.run_diff_evidence.v1"
DEFAULT_RUN_ID = "run-diff-counterfactual-proof"
CREATED_AT = "2026-04-25T00:00:31Z"
UPDATED_AT = "2026-04-25T00:00:31Z"


def _check_row(check: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": str(check.get("id", "")),
        "status": str(check.get("status", "unknown")),
        "summary": check.get("summary", ""),
        "details_summary": (
            check.get("details", {}).get("summary", {})
            if isinstance(check.get("details"), Mapping)
            else {}
        ),
    }


def _checks_by_id(bundle: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    checks = bundle.get("checks", [])
    if not isinstance(checks, Sequence) or isinstance(checks, (str, bytes)):
        return {}
    rows = [_check_row(check) for check in checks if isinstance(check, Mapping)]
    return {row["id"]: row for row in rows if row["id"]}


def _artifact_id(artifact: Mapping[str, Any]) -> str:
    for key in ("id", "artifact_id", "name", "path"):
        value = str(artifact.get(key, "") or "")
        if value:
            return value
    return ""


def _artifacts_by_id(
    artifacts: Sequence[Mapping[str, Any]] | Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    if isinstance(artifacts, Mapping):
        candidate = artifacts.get("artifacts", [])
        if isinstance(candidate, Sequence) and not isinstance(candidate, (str, bytes)):
            artifacts = candidate
        else:
            return {}
    rows: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            continue
        artifact_id = _artifact_id(artifact)
        if artifact_id:
            rows[artifact_id] = dict(artifact)
    return rows


def _manifest_artifact_count(manifest: Mapping[str, Any]) -> int:
    artifacts = manifest.get("artifacts", [])
    if isinstance(artifacts, Sequence) and not isinstance(artifacts, (str, bytes)):
        return len(artifacts)
    summary = manifest.get("summary", {})
    if isinstance(summary, Mapping):
        return int(summary.get("artifact_count", 0) or 0)
    return 0


def _validation_labels(manifest: Mapping[str, Any]) -> set[str]:
    validations = manifest.get("validations", [])
    if not isinstance(validations, Sequence) or isinstance(validations, (str, bytes)):
        return set()
    labels = set()
    for validation in validations:
        if isinstance(validation, Mapping):
            label = str(validation.get("label", "") or "")
            if label:
                labels.add(label)
    return labels


def _added_rows(
    baseline: Mapping[str, dict[str, Any]],
    candidate: Mapping[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    return [candidate[row_id] for row_id in sorted(set(candidate) - set(baseline))]


def _removed_rows(
    baseline: Mapping[str, dict[str, Any]],
    candidate: Mapping[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    return [baseline[row_id] for row_id in sorted(set(baseline) - set(candidate))]


def _status_changes(
    baseline: Mapping[str, dict[str, Any]],
    candidate: Mapping[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for check_id in sorted(set(baseline) & set(candidate)):
        baseline_status = baseline[check_id].get("status")
        candidate_status = candidate[check_id].get("status")
        if baseline_status != candidate_status:
            rows.append(
                {
                    "id": check_id,
                    "baseline_status": baseline_status,
                    "candidate_status": candidate_status,
                }
            )
    return rows


def _summary_changes(
    baseline: Mapping[str, dict[str, Any]],
    candidate: Mapping[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for check_id in sorted(set(baseline) & set(candidate)):
        baseline_summary = baseline[check_id].get("details_summary", {})
        candidate_summary = candidate[check_id].get("details_summary", {})
        if baseline_summary != candidate_summary:
            rows.append(
                {
                    "id": check_id,
                    "baseline": baseline_summary,
                    "candidate": candidate_summary,
                }
            )
    return rows


def _bundle_summary(
    baseline_bundle: Mapping[str, Any],
    candidate_bundle: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "baseline_status": baseline_bundle.get("status", "unknown"),
        "candidate_status": candidate_bundle.get("status", "unknown"),
        "baseline_supported_score": baseline_bundle.get("supported_score", ""),
        "candidate_supported_score": candidate_bundle.get("supported_score", ""),
        "baseline_total": (baseline_bundle.get("summary", {}) or {}).get("total"),
        "candidate_total": (candidate_bundle.get("summary", {}) or {}).get("total"),
    }


def _manifest_comparison(
    baseline_manifest: Mapping[str, Any],
    candidate_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    baseline_artifact_count = _manifest_artifact_count(baseline_manifest)
    candidate_artifact_count = _manifest_artifact_count(candidate_manifest)
    baseline_labels = _validation_labels(baseline_manifest)
    candidate_labels = _validation_labels(candidate_manifest)
    return {
        "baseline_path_id": baseline_manifest.get("path_id", ""),
        "candidate_path_id": candidate_manifest.get("path_id", ""),
        "same_path_id": baseline_manifest.get("path_id", "")
        == candidate_manifest.get("path_id", ""),
        "baseline_status": baseline_manifest.get("status", "unknown"),
        "candidate_status": candidate_manifest.get("status", "unknown"),
        "status_changed": baseline_manifest.get("status", "unknown")
        != candidate_manifest.get("status", "unknown"),
        "baseline_artifact_count": baseline_artifact_count,
        "candidate_artifact_count": candidate_artifact_count,
        "artifact_delta": candidate_artifact_count - baseline_artifact_count,
        "validation_labels_added": sorted(candidate_labels - baseline_labels),
        "validation_labels_removed": sorted(baseline_labels - candidate_labels),
    }


def _counterfactuals(
    *,
    checks_added: Sequence[Mapping[str, Any]],
    check_summary_changes: Sequence[Mapping[str, Any]],
    artifacts_added: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    added_check_ids = {str(check.get("id", "")) for check in checks_added}
    changed_check_ids = {str(check.get("id", "")) for check in check_summary_changes}
    added_artifact_ids = {_artifact_id(artifact) for artifact in artifacts_added}

    rows: list[dict[str, Any]] = []
    if "data_connector_runtime_adapters_report_contract" in added_check_ids:
        rows.append(
            {
                "id": "without_runtime_adapter_contract",
                "question": (
                    "What would change if runtime adapter evidence were absent?"
                ),
                "expected_effect": (
                    "The candidate would lose the connector runtime-binding "
                    "check and its adapter artifact, leaving health actions "
                    "planned but not tied to credentialed runtime operations."
                ),
                "affects_checks": ["data_connector_runtime_adapters_report_contract"],
                "affects_artifacts": sorted(
                    artifact_id
                    for artifact_id in added_artifact_ids
                    if "runtime_adapter" in artifact_id
                ),
            }
        )
    if "multi_app_dag_report_contract" in changed_check_ids:
        rows.append(
            {
                "id": "single_sample_multi_app_dag",
                "question": (
                    "What would change if only the original multi-app DAG "
                    "sample were validated?"
                ),
                "expected_effect": (
                    "The candidate would keep the queue-to-relay handoff but "
                    "lose the supplemental portfolio coverage across flight, "
                    "weather forecast, pandas, and polars apps."
                ),
                "affects_checks": ["multi_app_dag_report_contract"],
                "affects_artifacts": sorted(
                    artifact_id
                    for artifact_id in added_artifact_ids
                    if "forecast" in artifact_id
                ),
            }
        )
    return rows


def build_run_diff_evidence(
    *,
    baseline_bundle: Mapping[str, Any],
    candidate_bundle: Mapping[str, Any],
    baseline_manifest: Mapping[str, Any],
    candidate_manifest: Mapping[str, Any],
    baseline_artifacts: Sequence[Mapping[str, Any]] | Mapping[str, Any],
    candidate_artifacts: Sequence[Mapping[str, Any]] | Mapping[str, Any],
    run_id: str = DEFAULT_RUN_ID,
) -> dict[str, Any]:
    """Build a deterministic run-diff evidence payload without live execution."""

    baseline_checks = _checks_by_id(baseline_bundle)
    candidate_checks = _checks_by_id(candidate_bundle)
    baseline_artifact_rows = _artifacts_by_id(baseline_artifacts)
    candidate_artifact_rows = _artifacts_by_id(candidate_artifacts)

    checks_added = _added_rows(baseline_checks, candidate_checks)
    checks_removed = _removed_rows(baseline_checks, candidate_checks)
    check_status_changes = _status_changes(baseline_checks, candidate_checks)
    check_summary_changes = _summary_changes(baseline_checks, candidate_checks)
    artifacts_added = _added_rows(baseline_artifact_rows, candidate_artifact_rows)
    artifacts_removed = _removed_rows(baseline_artifact_rows, candidate_artifact_rows)
    manifest = _manifest_comparison(baseline_manifest, candidate_manifest)
    bundle = _bundle_summary(baseline_bundle, candidate_bundle)
    counterfactual_rows = _counterfactuals(
        checks_added=checks_added,
        check_summary_changes=check_summary_changes,
        artifacts_added=artifacts_added,
    )

    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "created_at": CREATED_AT,
        "updated_at": UPDATED_AT,
        "run_status": "diff_ready",
        "execution_mode": "run_diff_evidence_only",
        "summary": {
            "bundle_status_changed": bundle["baseline_status"]
            != bundle["candidate_status"],
            "supported_score_changed": bundle["baseline_supported_score"]
            != bundle["candidate_supported_score"],
            "check_added_count": len(checks_added),
            "check_removed_count": len(checks_removed),
            "check_status_changed_count": len(check_status_changes),
            "check_summary_changed_count": len(check_summary_changes),
            "artifact_added_count": len(artifacts_added),
            "artifact_removed_count": len(artifacts_removed),
            "manifest_status_changed": manifest["status_changed"],
            "manifest_artifact_delta": manifest["artifact_delta"],
            "manifest_validation_added_count": len(
                manifest["validation_labels_added"]
            ),
            "counterfactual_count": len(counterfactual_rows),
            "network_probe_count": 0,
            "live_execution_count": 0,
            "command_execution_count": 0,
        },
        "bundle": bundle,
        "manifest": manifest,
        "diff": {
            "checks_added": checks_added,
            "checks_removed": checks_removed,
            "check_status_changes": check_status_changes,
            "check_summary_changes": check_summary_changes,
            "artifacts_added": artifacts_added,
            "artifacts_removed": artifacts_removed,
        },
        "counterfactuals": counterfactual_rows,
        "narrative": [
            (
                "The candidate keeps the public KPI status stable while adding "
                "one contract check and two artifact evidence rows."
            ),
            (
                "The material changes are the runtime-adapter contract and the "
                "broader multi-app DAG sample-suite coverage."
            ),
        ],
        "provenance": {
            "executes_commands": False,
            "executes_network_probe": False,
            "uses_static_sample_evidence": True,
            "safe_for_public_evidence": True,
        },
    }


def _sample_check(
    check_id: str,
    *,
    summary: str,
    details_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": "pass",
        "summary": summary,
        "details": {"summary": dict(details_summary or {})},
    }


def sample_baseline_bundle() -> dict[str, Any]:
    return {
        "kpi": "Overall public evaluation",
        "status": "pass",
        "supported_score": "3.8 / 5",
        "summary": {"passed": 31, "failed": 0, "total": 31},
        "checks": [
            _sample_check(
                "workflow_compatibility_report",
                summary="compatibility report validates public status claims",
            ),
            _sample_check(
                "run_manifest_contract",
                summary="newcomer first proof emits run_manifest.json",
            ),
            _sample_check(
                "multi_app_dag_report_contract",
                summary="multi-app DAG report validates handoff contract",
                details_summary={
                    "sample_count": 1,
                    "supplemental_sample_count": 0,
                    "suite_app_count": 2,
                },
            ),
            _sample_check(
                "data_connector_health_actions_report_contract",
                summary="connector health actions are operator triggered",
            ),
            _sample_check(
                "reduce_contract_adoption_guardrail",
                summary="non-template apps expose reducer contracts",
            ),
        ],
    }


def sample_candidate_bundle() -> dict[str, Any]:
    bundle = sample_baseline_bundle()
    bundle["summary"] = {"passed": 32, "failed": 0, "total": 32}
    for check in bundle["checks"]:
        if check["id"] == "multi_app_dag_report_contract":
            check["details"]["summary"] = {
                "sample_count": 2,
                "supplemental_sample_count": 1,
                "suite_app_count": 6,
            }
    bundle["checks"].append(
        _sample_check(
            "data_connector_runtime_adapters_report_contract",
            summary=(
                "data connector runtime adapters expose credentialed bindings "
                "without network probes"
            ),
            details_summary={
                "adapter_count": 3,
                "network_probe_count": 0,
            },
        )
    )
    return bundle


def sample_baseline_manifest() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "agilab.run_manifest",
        "path_id": "source-checkout-first-proof",
        "status": "pass",
        "artifacts": [
            {"id": "run_manifest", "path": "run_manifest.json"},
            {
                "id": "queue_metrics",
                "path": "queue_analysis/uav_queue_summary_metrics.json",
            },
        ],
        "validations": [
            {"label": "proof_steps", "status": "pass"},
            {"label": "target_seconds", "status": "pass"},
            {"label": "recommended_project", "status": "pass"},
        ],
    }


def sample_candidate_manifest() -> dict[str, Any]:
    manifest = sample_baseline_manifest()
    manifest["artifacts"] = [
        *manifest["artifacts"],
        {
            "id": "runtime_adapter_bindings",
            "path": "data_connector_runtime_adapters.json",
        },
    ]
    manifest["validations"] = [
        *manifest["validations"],
        {"label": "runtime_adapter_contract", "status": "pass"},
    ]
    return manifest


def sample_baseline_artifacts() -> list[dict[str, Any]]:
    return [
        {"id": "run_manifest", "path": "run_manifest.json", "status": "present"},
        {
            "id": "queue_metrics",
            "path": "queue_analysis/uav_queue_summary_metrics.json",
            "status": "present",
        },
    ]


def sample_candidate_artifacts() -> list[dict[str, Any]]:
    return [
        *sample_baseline_artifacts(),
        {
            "id": "forecast_metrics",
            "path": "meteo_forecast/forecast_metrics.json",
            "status": "present",
        },
        {
            "id": "runtime_adapter_bindings",
            "path": "data_connector_runtime_adapters.json",
            "status": "present",
        },
    ]


def build_sample_run_diff() -> dict[str, Any]:
    return build_run_diff_evidence(
        baseline_bundle=sample_baseline_bundle(),
        candidate_bundle=sample_candidate_bundle(),
        baseline_manifest=sample_baseline_manifest(),
        candidate_manifest=sample_candidate_manifest(),
        baseline_artifacts=sample_baseline_artifacts(),
        candidate_artifacts=sample_candidate_artifacts(),
    )


def write_run_diff_evidence(path: Path, state: Mapping[str, Any]) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_run_diff_evidence(path: Path) -> dict[str, Any]:
    return json.loads(path.expanduser().read_text(encoding="utf-8"))


def persist_run_diff_evidence(
    *,
    output_path: Path,
    baseline_bundle: Mapping[str, Any] | None = None,
    candidate_bundle: Mapping[str, Any] | None = None,
    baseline_manifest: Mapping[str, Any] | None = None,
    candidate_manifest: Mapping[str, Any] | None = None,
    baseline_artifacts: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    candidate_artifacts: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    state = build_run_diff_evidence(
        baseline_bundle=baseline_bundle or sample_baseline_bundle(),
        candidate_bundle=candidate_bundle or sample_candidate_bundle(),
        baseline_manifest=baseline_manifest or sample_baseline_manifest(),
        candidate_manifest=candidate_manifest or sample_candidate_manifest(),
        baseline_artifacts=baseline_artifacts or sample_baseline_artifacts(),
        candidate_artifacts=candidate_artifacts or sample_candidate_artifacts(),
    )
    path = write_run_diff_evidence(output_path, state)
    reloaded = load_run_diff_evidence(path)
    return {
        "ok": state == reloaded and state.get("run_status") == "diff_ready",
        "path": str(path),
        "state": state,
        "reloaded_state": reloaded,
        "round_trip_ok": state == reloaded,
    }
