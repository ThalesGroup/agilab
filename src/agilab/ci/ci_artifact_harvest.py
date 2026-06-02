# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""CI artifact harvest contract for external-machine AGILAB evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


SCHEMA = "agilab.ci_artifact_harvest.v1"
DEFAULT_RUN_ID = "ci-artifact-harvest-proof"
DEFAULT_RELEASE_ID = "2026-04-25-ci-sample"
CREATED_AT = "2026-04-25T00:00:32Z"
UPDATED_AT = "2026-04-25T00:00:32Z"
REQUIRED_ARTIFACT_KINDS = (
    "run_manifest",
    "kpi_evidence_bundle",
    "compatibility_report",
    "promotion_decision",
)


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _payload_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _payload_status(kind: str, payload: Mapping[str, Any]) -> str:
    if kind == "run_manifest":
        if (
            payload.get("kind") == "agilab.run_manifest"
            and payload.get("path_id") == "source-checkout-first-proof"
            and payload.get("status") == "pass"
        ):
            return "validated"
        return "failed"
    if kind == "kpi_evidence_bundle":
        summary = payload.get("summary", {})
        if (
            payload.get("kpi") == "Overall public evaluation"
            and payload.get("status") == "pass"
            and isinstance(summary, Mapping)
            and int(summary.get("failed", 1) or 0) == 0
        ):
            return "validated"
        return "failed"
    if kind == "compatibility_report":
        if payload.get("report") == "Compatibility matrix report" and payload.get("status") == "pass":
            return "validated"
        return "failed"
    if kind == "promotion_decision":
        if (
            payload.get("schema") == "agilab.promotion.decision.v1"
            and payload.get("decision") == "promotable"
            and payload.get("gate_status") == "pass"
        ):
            return "validated"
        return "failed"
    return "not_required"


def _payload_summary(kind: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    if kind == "run_manifest":
        return {
            "path_id": payload.get("path_id", ""),
            "status": payload.get("status", ""),
            "artifact_count": len(payload.get("artifacts", []) or []),
        }
    if kind == "kpi_evidence_bundle":
        summary = payload.get("summary", {})
        return {
            "status": payload.get("status", ""),
            "supported_score": payload.get("supported_score", ""),
            "passed": summary.get("passed") if isinstance(summary, Mapping) else None,
            "failed": summary.get("failed") if isinstance(summary, Mapping) else None,
            "total": summary.get("total") if isinstance(summary, Mapping) else None,
        }
    if kind == "compatibility_report":
        summary = payload.get("summary", {})
        return {
            "status": payload.get("status", ""),
            "validated_paths": (
                summary.get("validated_paths") if isinstance(summary, Mapping) else None
            ),
        }
    if kind == "promotion_decision":
        return {
            "schema": payload.get("schema", ""),
            "decision": payload.get("decision", ""),
            "gate_status": payload.get("gate_status", ""),
        }
    return {"status": payload.get("status", "")}


def _artifact_row(
    artifact: Mapping[str, Any],
    *,
    release_id: str,
) -> dict[str, Any]:
    payload = artifact.get("payload", {})
    if not isinstance(payload, Mapping):
        payload = {}
    kind = str(artifact.get("kind", "") or "")
    artifact_id = str(artifact.get("id", "") or f"{kind}_artifact")
    calculated_sha256 = _payload_sha256(payload)
    declared_sha256 = str(
        artifact.get("sha256")
        or artifact.get("content_sha256")
        or calculated_sha256
    )
    source_machine = str(artifact.get("source_machine", "") or "")
    workflow = str(artifact.get("workflow", "") or "")
    run_attempt = str(artifact.get("run_attempt", "") or "")
    provenance_tagged = bool(source_machine and workflow and run_attempt)
    return {
        "id": artifact_id,
        "release_id": str(artifact.get("release_id", "") or release_id),
        "kind": kind,
        "path": str(artifact.get("path", "") or ""),
        "required": kind in REQUIRED_ARTIFACT_KINDS,
        "payload_status": _payload_status(kind, payload),
        "payload_summary": _payload_summary(kind, payload),
        "content_sha256": declared_sha256,
        "calculated_sha256": calculated_sha256,
        "sha256_verified": declared_sha256 == calculated_sha256,
        "source_machine": source_machine,
        "workflow": workflow,
        "run_id": str(artifact.get("run_id", "") or ""),
        "run_attempt": run_attempt,
        "provenance_tagged": provenance_tagged,
        "attachment_status": (
            "provenance_tagged" if provenance_tagged else "missing_provenance"
        ),
    }


def _status_mapping(rows: Sequence[Mapping[str, Any]], release_id: str) -> dict[str, Any]:
    status_by_kind = {
        str(row.get("kind", "")): str(row.get("payload_status", "missing"))
        for row in rows
        if row.get("kind")
    }
    missing_required = [
        kind for kind in REQUIRED_ARTIFACT_KINDS if kind not in status_by_kind
    ]
    failed_kinds = [
        kind
        for kind in REQUIRED_ARTIFACT_KINDS
        if status_by_kind.get(kind) not in {"validated"}
    ]
    if missing_required:
        public_status = "missing_evidence"
    elif failed_kinds:
        public_status = "failed"
    else:
        public_status = "validated"
    return {
        "release_id": release_id,
        "public_status": public_status,
        "required_artifact_kinds": list(REQUIRED_ARTIFACT_KINDS),
        "artifact_statuses": {
            kind: status_by_kind.get(kind, "missing")
            for kind in REQUIRED_ARTIFACT_KINDS
        },
        "missing_required_artifact_kinds": missing_required,
        "failed_required_artifact_kinds": failed_kinds,
        "source_machines": sorted(
            {
                str(row.get("source_machine", ""))
                for row in rows
                if row.get("source_machine")
            }
        ),
    }


def _issues(rows: Sequence[Mapping[str, Any]], mapping: Mapping[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for kind in mapping.get("missing_required_artifact_kinds", []):
        issues.append(
            {
                "level": "error",
                "location": f"artifacts.{kind}",
                "message": "required CI artifact kind is missing",
            }
        )
    for row in rows:
        if row.get("sha256_verified") is not True:
            issues.append(
                {
                    "level": "error",
                    "location": f"artifacts.{row.get('id', '')}.content_sha256",
                    "message": "artifact checksum does not match payload",
                }
            )
        if row.get("required") and row.get("payload_status") != "validated":
            issues.append(
                {
                    "level": "error",
                    "location": f"artifacts.{row.get('id', '')}.payload",
                    "message": "required artifact payload is not validated",
                }
            )
        if row.get("provenance_tagged") is not True:
            issues.append(
                {
                    "level": "warning",
                    "location": f"artifacts.{row.get('id', '')}.provenance",
                    "message": "artifact is missing source-machine provenance",
                }
            )
    return issues


def build_ci_artifact_harvest(
    artifacts: Sequence[Mapping[str, Any]],
    *,
    release_id: str = DEFAULT_RELEASE_ID,
    run_id: str = DEFAULT_RUN_ID,
) -> dict[str, Any]:
    rows = [_artifact_row(artifact, release_id=release_id) for artifact in artifacts]
    mapping = _status_mapping(rows, release_id)
    issues = _issues(rows, mapping)
    checksum_mismatch_count = sum(1 for row in rows if row["sha256_verified"] is not True)
    required_rows = [row for row in rows if row["required"]]
    run_status = (
        "harvest_ready"
        if mapping["public_status"] == "validated" and checksum_mismatch_count == 0
        else "incomplete"
    )
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "created_at": CREATED_AT,
        "updated_at": UPDATED_AT,
        "run_status": run_status,
        "execution_mode": "ci_artifact_contract_only",
        "release": mapping,
        "summary": {
            "artifact_count": len(rows),
            "required_artifact_count": len(required_rows),
            "loaded_artifact_count": len(rows),
            "missing_required_count": len(mapping["missing_required_artifact_kinds"]),
            "checksum_verified_count": sum(1 for row in rows if row["sha256_verified"]),
            "checksum_mismatch_count": checksum_mismatch_count,
            "provenance_tagged_count": sum(1 for row in rows if row["provenance_tagged"]),
            "external_machine_evidence_count": sum(
                1 for row in rows if row["source_machine"]
            ),
            "release_status": mapping["public_status"],
            "live_ci_query_count": 0,
            "network_probe_count": 0,
            "command_execution_count": 0,
            "artifact_kinds": sorted({str(row.get("kind", "")) for row in rows}),
        },
        "artifacts": rows,
        "issues": issues,
        "provenance": {
            "executes_commands": False,
            "executes_network_probe": False,
            "queries_ci_provider": False,
            "uses_static_sample_archive": True,
            "safe_for_public_evidence": True,
        },
    }


def _sample_run_manifest() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "agilab.run_manifest",
        "path_id": "source-checkout-first-proof",
        "status": "pass",
        "environment": {
            "app_name": "flight_telemetry_project",
            "source_machine": "github-actions:macos-14-arm64",
        },
        "artifacts": [{"id": "first_proof_log", "path": "run_manifest.json"}],
        "validations": [
            {"label": "proof_steps", "status": "pass"},
            {"label": "target_seconds", "status": "pass"},
            {"label": "recommended_project", "status": "pass"},
        ],
    }


def _sample_kpi_bundle() -> dict[str, Any]:
    return {
        "kpi": "Overall public evaluation",
        "status": "pass",
        "supported_score": "3.8 / 5",
        "summary": {"passed": 42, "failed": 0, "total": 42},
        "checks": [
            {"id": "workflow_compatibility_report", "status": "pass"},
            {"id": "run_manifest_contract", "status": "pass"},
            {"id": "revision_traceability_report_contract", "status": "pass"},
            {"id": "public_certification_profile_report_contract", "status": "pass"},
            {"id": "supply_chain_attestation_report_contract", "status": "pass"},
            {"id": "repository_knowledge_report_contract", "status": "pass"},
            {"id": "run_diff_evidence_report_contract", "status": "pass"},
            {"id": "ci_artifact_harvest_report_contract", "status": "pass"},
            {"id": "github_actions_artifact_index_contract", "status": "pass"},
            {"id": "ci_provider_artifact_index_contract", "status": "pass"},
            {
                "id": "data_connector_live_endpoint_smoke_report_contract",
                "status": "pass",
            },
            {"id": "data_connector_view_surface_report_contract", "status": "pass"},
            {"id": "public_docs_evidence_links", "status": "pass"},
        ],
    }


def _sample_compatibility_report() -> dict[str, Any]:
    return {
        "report": "Compatibility matrix report",
        "status": "pass",
        "summary": {
            "validated_paths": 4,
            "documented_paths": 2,
            "failed": 0,
        },
    }


def _sample_promotion_decision() -> dict[str, Any]:
    return {
        "schema": "agilab.promotion.decision.v1",
        "decision": "promotable",
        "gate_status": "pass",
        "release_id": DEFAULT_RELEASE_ID,
        "run_manifest_path": "ci/source-checkout-first-proof/run_manifest.json",
    }


def sample_ci_artifacts() -> list[dict[str, Any]]:
    source_machine = "github-actions:macos-14-arm64"
    workflow = "public-evidence.yml"
    run_id = "ci-sample-20260425"
    run_attempt = "1"
    return [
        {
            "id": "first_proof_run_manifest",
            "kind": "run_manifest",
            "path": "ci/source-checkout-first-proof/run_manifest.json",
            "payload": _sample_run_manifest(),
            "source_machine": source_machine,
            "workflow": workflow,
            "run_id": run_id,
            "run_attempt": run_attempt,
        },
        {
            "id": "public_kpi_evidence_bundle",
            "kind": "kpi_evidence_bundle",
            "path": "ci/evidence/kpi_evidence_bundle.json",
            "payload": _sample_kpi_bundle(),
            "source_machine": source_machine,
            "workflow": workflow,
            "run_id": run_id,
            "run_attempt": run_attempt,
        },
        {
            "id": "compatibility_matrix_report",
            "kind": "compatibility_report",
            "path": "ci/evidence/compatibility_report.json",
            "payload": _sample_compatibility_report(),
            "source_machine": source_machine,
            "workflow": workflow,
            "run_id": run_id,
            "run_attempt": run_attempt,
        },
        {
            "id": "promotion_decision_export",
            "kind": "promotion_decision",
            "path": "ci/release/promotion_decision.json",
            "payload": _sample_promotion_decision(),
            "source_machine": source_machine,
            "workflow": workflow,
            "run_id": run_id,
            "run_attempt": run_attempt,
        },
    ]


def build_sample_ci_artifact_harvest() -> dict[str, Any]:
    return build_ci_artifact_harvest(sample_ci_artifacts())


def write_ci_artifact_harvest(path: Path, state: Mapping[str, Any]) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_ci_artifact_harvest(path: Path) -> dict[str, Any]:
    return json.loads(path.expanduser().read_text(encoding="utf-8"))


def persist_ci_artifact_harvest(
    *,
    output_path: Path,
    artifacts: Sequence[Mapping[str, Any]] | None = None,
    release_id: str = DEFAULT_RELEASE_ID,
) -> dict[str, Any]:
    state = build_ci_artifact_harvest(
        artifacts or sample_ci_artifacts(),
        release_id=release_id,
    )
    path = write_ci_artifact_harvest(output_path, state)
    reloaded = load_ci_artifact_harvest(path)
    return {
        "ok": state == reloaded and state.get("run_status") == "harvest_ready",
        "path": str(path),
        "state": state,
        "reloaded_state": reloaded,
        "round_trip_ok": state == reloaded,
    }
