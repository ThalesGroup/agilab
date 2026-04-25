#!/usr/bin/env python3
"""Emit machine-readable evidence for AGILAB public compatibility claims."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence
import tomllib


REPO_ROOT = Path(__file__).resolve().parents[1]
MATRIX_RELATIVE_PATH = Path("docs/source/data/compatibility_matrix.toml")
COMPATIBILITY_DOC_RELATIVE_PATH = Path("docs/source/compatibility-matrix.rst")
SUPPORTED_STATUSES = {"validated", "documented"}
REQUIRED_ENTRY_FIELDS = {
    "id",
    "label",
    "status",
    "surface",
    "primary_proof",
    "python",
    "platforms",
    "scope",
    "limits",
}
REQUIRED_PUBLIC_STATUSES = {
    "source-checkout-first-proof": "validated",
    "web-ui-local-first-proof": "validated",
    "agilab-hf-demo": "validated",
    "service-mode-operator-surface": "validated",
    "notebook-quickstart": "documented",
    "published-package-route": "documented",
}
REQUIRED_VALIDATED_EVIDENCE = {
    "source-checkout-first-proof": ("tools/newcomer_first_proof.py",),
    "web-ui-local-first-proof": ("streamlit run", "src/agilab/About_agilab.py"),
    "agilab-hf-demo": ("tools/hf_space_smoke.py", "--json"),
    "service-mode-operator-surface": ("tools/service_health_check.py", "health"),
}
DOCUMENTED_BOUNDARY_IDS = {"notebook-quickstart", "published-package-route"}


def _check_result(
    check_id: str,
    label: str,
    passed: bool,
    summary: str,
    *,
    evidence: Sequence[str] = (),
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": "pass" if passed else "fail",
        "summary": summary,
        "evidence": list(evidence),
        "details": details or {},
    }


def _load_matrix(repo_root: Path) -> dict[str, Any]:
    matrix_path = repo_root / MATRIX_RELATIVE_PATH
    with matrix_path.open("rb") as stream:
        payload = tomllib.load(stream)
    entries = payload.get("entries", [])
    if not isinstance(entries, list):
        raise TypeError("compatibility matrix entries must be a list")
    payload["entries"] = [entry for entry in entries if isinstance(entry, dict)]
    return payload


def _entry_statuses(entries: Sequence[dict[str, Any]]) -> dict[str, str]:
    return {str(entry.get("id")): str(entry.get("status")) for entry in entries}


def _check_matrix_schema(repo_root: Path) -> dict[str, Any]:
    try:
        payload = _load_matrix(repo_root)
        metadata = payload.get("metadata", {})
        entries = payload["entries"]
        failures: list[str] = []
        seen_ids: set[str] = set()
        status_counts = {status: 0 for status in sorted(SUPPORTED_STATUSES)}

        if not isinstance(metadata, dict):
            failures.append("metadata must be a table")
        elif not metadata.get("version") or not metadata.get("updated"):
            failures.append("metadata must include version and updated")

        for index, entry in enumerate(entries):
            entry_id = str(entry.get("id") or f"<entry-{index}>")
            missing_fields = sorted(REQUIRED_ENTRY_FIELDS - set(entry))
            if missing_fields:
                failures.append(f"{entry_id}: missing fields {missing_fields}")
            if entry_id in seen_ids:
                failures.append(f"{entry_id}: duplicate id")
            seen_ids.add(entry_id)

            status = str(entry.get("status"))
            if status not in SUPPORTED_STATUSES:
                failures.append(f"{entry_id}: unsupported status {status!r}")
            else:
                status_counts[status] += 1

            for list_field in ("python", "platforms", "limits"):
                if not isinstance(entry.get(list_field), list) or not entry.get(list_field):
                    failures.append(f"{entry_id}: {list_field} must be a non-empty list")

        details = {
            "entry_count": len(entries),
            "status_counts": status_counts,
            "failures": failures,
            "metadata": metadata,
        }
        ok = not failures and len(entries) > 0
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "compatibility_matrix_schema",
        "Compatibility matrix schema",
        ok,
        (
            "compatibility matrix has typed entries, unique ids, and supported statuses"
            if ok
            else "compatibility matrix schema is incomplete"
        ),
        evidence=[str(MATRIX_RELATIVE_PATH)],
        details=details,
    )


def _check_required_public_statuses(repo_root: Path) -> dict[str, Any]:
    try:
        entries = _load_matrix(repo_root)["entries"]
        statuses = _entry_statuses(entries)
        missing = sorted(set(REQUIRED_PUBLIC_STATUSES) - set(statuses))
        mismatched = {
            entry_id: {"expected": expected, "actual": statuses.get(entry_id)}
            for entry_id, expected in REQUIRED_PUBLIC_STATUSES.items()
            if statuses.get(entry_id) != expected
        }
        ok = not missing and not mismatched
        details = {
            "required_statuses": REQUIRED_PUBLIC_STATUSES,
            "actual_statuses": {
                entry_id: statuses.get(entry_id)
                for entry_id in sorted(REQUIRED_PUBLIC_STATUSES)
            },
            "missing": missing,
            "mismatched": mismatched,
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "required_public_statuses",
        "Required public statuses",
        ok,
        (
            "public compatibility paths keep the required validated/documented boundaries"
            if ok
            else "public compatibility paths no longer match the evidence contract"
        ),
        evidence=[str(MATRIX_RELATIVE_PATH)],
        details=details,
    )


def _check_workflow_evidence_commands(repo_root: Path) -> dict[str, Any]:
    try:
        entries = _load_matrix(repo_root)["entries"]
        entry_by_id = {str(entry.get("id")): entry for entry in entries}
        missing: dict[str, list[str]] = {}
        missing_files: dict[str, list[str]] = {}

        for entry_id, required_snippets in REQUIRED_VALIDATED_EVIDENCE.items():
            entry = entry_by_id.get(entry_id, {})
            primary_proof = str(entry.get("primary_proof", ""))
            missing_snippets = [
                snippet for snippet in required_snippets if snippet not in primary_proof
            ]
            if missing_snippets:
                missing[entry_id] = missing_snippets

            missing_paths = [
                snippet
                for snippet in required_snippets
                if snippet.endswith(".py") and not (repo_root / snippet).is_file()
            ]
            if missing_paths:
                missing_files[entry_id] = missing_paths

        ok = not missing and not missing_files
        details = {
            "validated_entries": sorted(REQUIRED_VALIDATED_EVIDENCE),
            "required_evidence": REQUIRED_VALIDATED_EVIDENCE,
            "missing_snippets": missing,
            "missing_files": missing_files,
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "workflow_evidence_commands",
        "Workflow evidence commands",
        ok,
        (
            "validated compatibility paths reference executable public proof commands"
            if ok
            else "validated compatibility paths are missing proof command evidence"
        ),
        evidence=[
            str(MATRIX_RELATIVE_PATH),
            "tools/newcomer_first_proof.py",
            "tools/hf_space_smoke.py",
            "tools/service_health_check.py",
        ],
        details=details,
    )


def _check_documented_boundaries(repo_root: Path) -> dict[str, Any]:
    try:
        entries = _load_matrix(repo_root)["entries"]
        statuses = _entry_statuses(entries)
        missing_documented = sorted(
            entry_id
            for entry_id in DOCUMENTED_BOUNDARY_IDS
            if statuses.get(entry_id) != "documented"
        )
        validated_without_evidence = sorted(
            entry_id
            for entry_id, status in statuses.items()
            if status == "validated" and entry_id not in REQUIRED_VALIDATED_EVIDENCE
        )
        ok = not missing_documented and not validated_without_evidence
        details = {
            "documented_boundary_ids": sorted(DOCUMENTED_BOUNDARY_IDS),
            "missing_documented": missing_documented,
            "validated_without_evidence": validated_without_evidence,
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "documented_route_boundaries",
        "Documented route boundaries",
        ok,
        (
            "documented routes remain explicitly outside the validated compatibility slice"
            if ok
            else "documented routes or validation boundaries changed without evidence"
        ),
        evidence=[str(MATRIX_RELATIVE_PATH)],
        details=details,
    )


def _check_docs_report_reference(repo_root: Path) -> dict[str, Any]:
    try:
        doc_text = (repo_root / COMPATIBILITY_DOC_RELATIVE_PATH).read_text(encoding="utf-8")
        normalized_doc = " ".join(doc_text.split())
        required = [
            "tools/compatibility_report.py --compact",
            "workflow-backed compatibility report",
            "required public statuses",
        ]
        stale = [
            "broader promotion from this matrix to a "
            "workflow-backed compatibility report"
        ]
        missing = [needle for needle in required if needle not in normalized_doc]
        stale_present = [needle for needle in stale if needle in normalized_doc]
        ok = not missing and not stale_present
        details = {"missing": missing, "stale_present": stale_present}
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "compatibility_docs_report_reference",
        "Compatibility docs report reference",
        ok,
        (
            "compatibility docs expose the workflow-backed report command and updated boundary"
            if ok
            else "compatibility docs do not match the workflow-backed report contract"
        ),
        evidence=[str(COMPATIBILITY_DOC_RELATIVE_PATH)],
        details=details,
    )


def build_report(*, repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    checks = [
        _check_matrix_schema(repo_root),
        _check_required_public_statuses(repo_root),
        _check_workflow_evidence_commands(repo_root),
        _check_documented_boundaries(repo_root),
        _check_docs_report_reference(repo_root),
    ]
    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    try:
        entries = _load_matrix(repo_root)["entries"]
        status_counts = {
            status: sum(1 for entry in entries if entry.get("status") == status)
            for status in sorted(SUPPORTED_STATUSES)
        }
    except Exception:
        status_counts = {}
    return {
        "report": "Compatibility report",
        "status": "pass" if failed == 0 else "fail",
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "status_counts": status_counts,
            "required_public_paths": len(REQUIRED_PUBLIC_STATUSES),
            "workflow_backed_validated_paths": len(REQUIRED_VALIDATED_EVIDENCE),
        },
        "scope": (
            "Validates the public compatibility matrix schema, required public "
            "path statuses, and executable proof-command references. It does not "
            "claim broad OS, network, or remote-topology certification."
        ),
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit machine-readable evidence for AGILAB public compatibility claims."
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact JSON without indentation.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    report = build_report()
    if args.compact:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
