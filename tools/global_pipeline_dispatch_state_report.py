#!/usr/bin/env python3
"""Emit persistent dispatch-state evidence for AGILAB global pipeline DAGs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DAG_RELATIVE_PATH = Path("docs/source/data/multi_app_dag_sample.json")
DOC_RELATIVE_PATH = Path("docs/source/features.rst")


def _ensure_repo_on_path(repo_root: Path) -> None:
    src_root = repo_root / "src"
    for entry in (str(src_root), str(repo_root)):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    package = sys.modules.get("agilab")
    package_path = str(src_root / "agilab")
    package_paths = getattr(package, "__path__", None)
    if package_paths is not None and package_path not in list(package_paths):
        try:
            package_paths.append(package_path)
        except AttributeError:
            package.__path__ = [*package_paths, package_path]


_ensure_repo_on_path(REPO_ROOT)

from agilab.global_pipeline_dispatch_state import (
    DEFAULT_RUN_ID,
    PERSISTENCE_FORMAT,
    SCHEMA,
    persist_dispatch_state,
)


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


def _docs_check(repo_root: Path) -> dict[str, Any]:
    doc_path = repo_root / DOC_RELATIVE_PATH
    required = [
        "global DAG dispatch state report",
        "tools/global_pipeline_dispatch_state_report.py --compact",
        "queue_baseline completed",
        "relay_followup runnable",
        "persisted run-state JSON",
    ]
    try:
        text = doc_path.read_text(encoding="utf-8")
        missing = [needle for needle in required if needle not in text]
        ok = not missing
        details = {"missing": missing}
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "global_pipeline_dispatch_state_docs_reference",
        "Global pipeline dispatch state docs reference",
        ok,
        (
            "features docs expose the global DAG dispatch state evidence command"
            if ok
            else "features docs do not expose the global DAG dispatch state evidence command"
        ),
        evidence=[str(DOC_RELATIVE_PATH)],
        details=details,
    )


def _load_failure_report(dag_path: Path | None, exc: Exception) -> dict[str, Any]:
    check = _check_result(
        "global_pipeline_dispatch_state_load",
        "Global pipeline dispatch state load",
        False,
        "global pipeline dispatch state could not be persisted",
        evidence=[str(dag_path or SAMPLE_DAG_RELATIVE_PATH)],
        details={"error": str(exc)},
    )
    return {
        "report": "Global pipeline dispatch state report",
        "status": "fail",
        "scope": (
            "Builds, writes, and reads back a persisted JSON dispatch-state "
            "proof for the global DAG. It simulates the first dispatch "
            "transition without executing apps."
        ),
        "dag_path": str(dag_path or SAMPLE_DAG_RELATIVE_PATH),
        "summary": {
            "passed": 0,
            "failed": 1,
            "total": 1,
            "issues": [{"level": "error", "location": "load", "message": str(exc)}],
        },
        "persistence": {},
        "checks": [check],
    }


def _build_proof(
    *,
    repo_root: Path,
    output_path: Path | None,
    dag_path: Path | None,
):
    if output_path is not None:
        return persist_dispatch_state(
            repo_root=repo_root,
            output_path=output_path,
            dag_path=dag_path,
        )
    with tempfile.TemporaryDirectory(prefix="agilab-dispatch-state-") as tmp_dir:
        return persist_dispatch_state(
            repo_root=repo_root,
            output_path=Path(tmp_dir) / "global_pipeline_dispatch_state.json",
            dag_path=dag_path,
        )


def build_report(
    *,
    repo_root: Path = REPO_ROOT,
    dag_path: Path | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    try:
        proof = _build_proof(repo_root=repo_root, output_path=output_path, dag_path=dag_path)
    except Exception as exc:
        return _load_failure_report(dag_path, exc)

    proof_details = proof.as_dict()
    state = proof.dispatch_state
    summary = state.get("summary", {})
    units = state.get("units", [])
    unit_by_id = {
        unit.get("id"): unit
        for unit in units
        if isinstance(unit, dict)
    }
    events = state.get("events", [])
    event_kinds = [
        event.get("kind")
        for event in events
        if isinstance(event, dict)
    ]

    checks = [
        _check_result(
            "global_pipeline_dispatch_state_schema",
            "Global pipeline dispatch state schema",
            proof.ok
            and state.get("schema") == SCHEMA
            and state.get("persistence_format") == PERSISTENCE_FORMAT
            and state.get("run_id") == DEFAULT_RUN_ID,
            "dispatch state uses the supported schema and JSON persistence format"
            if proof.ok
            else "dispatch state schema or persistence proof is invalid",
            evidence=["src/agilab/global_pipeline_dispatch_state.py"],
            details={
                "schema": state.get("schema"),
                "expected_schema": SCHEMA,
                "persistence_format": state.get("persistence_format"),
                "run_id": state.get("run_id"),
                "issues": [issue.as_dict() for issue in proof.issues],
            },
        ),
        _check_result(
            "global_pipeline_dispatch_state_round_trip",
            "Global pipeline dispatch state JSON round trip",
            proof.round_trip_ok,
            "dispatch state is unchanged after JSON write/read",
            evidence=[proof.path],
            details={
                "path": proof.path,
                "round_trip_ok": proof.round_trip_ok,
            },
        ),
        _check_result(
            "global_pipeline_dispatch_state_progress",
            "Global pipeline dispatch state progress",
            summary.get("completed_unit_ids") == ["queue_baseline"]
            and summary.get("runnable_unit_ids") == ["relay_followup"]
            and summary.get("blocked_unit_ids") == [],
            "dispatch state completes queue_baseline and makes relay_followup runnable",
            evidence=["tools/global_pipeline_runner_state_report.py"],
            details={
                "completed_unit_ids": summary.get("completed_unit_ids"),
                "runnable_unit_ids": summary.get("runnable_unit_ids"),
                "blocked_unit_ids": summary.get("blocked_unit_ids"),
                "run_status": state.get("run_status"),
            },
        ),
        _check_result(
            "global_pipeline_dispatch_state_artifact_unblock",
            "Global pipeline dispatch state artifact unblock",
            "queue_metrics" in proof.available_artifact_ids
            and unit_by_id.get("relay_followup", {}).get("dispatch_status") == "runnable"
            and "unit_unblocked" in event_kinds,
            "dispatch state persists queue_metrics availability and downstream unblock",
            evidence=["docs/source/data/multi_app_dag_sample.json"],
            details={
                "available_artifact_ids": list(proof.available_artifact_ids),
                "relay_status": unit_by_id.get("relay_followup", {}).get("dispatch_status"),
                "event_kinds": event_kinds,
            },
        ),
        _check_result(
            "global_pipeline_dispatch_state_retry_partial_rerun",
            "Global pipeline dispatch state retry and partial-rerun counters",
            proof.retry_counter_count == 2
            and proof.partial_rerun_flag_count == 2
            and unit_by_id.get("queue_baseline", {}).get("retry", {}).get("attempt") == 1
            and unit_by_id.get("queue_baseline", {}).get("partial_rerun", {}).get("requested") is False,
            "dispatch state persists retry counters and partial-rerun flags",
            evidence=["src/agilab/global_pipeline_dispatch_state.py"],
            details={
                "retry_counter_count": proof.retry_counter_count,
                "partial_rerun_flag_count": proof.partial_rerun_flag_count,
                "queue_retry": unit_by_id.get("queue_baseline", {}).get("retry", {}),
                "queue_partial_rerun": unit_by_id.get("queue_baseline", {}).get("partial_rerun", {}),
            },
        ),
        _check_result(
            "global_pipeline_dispatch_state_timestamps_provenance",
            "Global pipeline dispatch state timestamps and provenance",
            state.get("created_at") == "2026-04-25T00:00:00Z"
            and state.get("updated_at") == "2026-04-25T00:00:03Z"
            and summary.get("event_count") == proof.event_count
            and state.get("provenance", {}).get("source_runner_state_schema")
            == "agilab.global_pipeline_runner_state.v1"
            and state.get("provenance", {}).get("real_app_execution") is False,
            "dispatch state persists timestamps and provenance without claiming app execution",
            evidence=["tools/global_pipeline_runner_state_report.py"],
            details={
                "created_at": state.get("created_at"),
                "updated_at": state.get("updated_at"),
                "event_count": proof.event_count,
                "provenance": state.get("provenance", {}),
            },
        ),
        _docs_check(repo_root),
    ]

    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "report": "Global pipeline dispatch state report",
        "status": "pass" if failed == 0 else "fail",
        "scope": (
            "Builds, writes, and reads back a persisted JSON dispatch-state "
            "proof for the global DAG. It simulates queue_baseline completion "
            "and relay_followup unblocking without executing apps."
        ),
        "dag_path": state.get("source", {}).get("dag_path", str(dag_path or SAMPLE_DAG_RELATIVE_PATH)),
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "schema": state.get("schema"),
            "run_id": state.get("run_id"),
            "run_status": state.get("run_status"),
            "persistence_format": state.get("persistence_format"),
            "round_trip_ok": proof.round_trip_ok,
            "path": proof.path,
            "unit_count": proof.unit_count,
            "completed_unit_ids": list(proof.completed_unit_ids),
            "runnable_unit_ids": list(proof.runnable_unit_ids),
            "blocked_unit_ids": list(proof.blocked_unit_ids),
            "available_artifact_ids": list(proof.available_artifact_ids),
            "event_count": proof.event_count,
            "retry_counter_count": proof.retry_counter_count,
            "partial_rerun_flag_count": proof.partial_rerun_flag_count,
            "issues": [issue.as_dict() for issue in proof.issues],
        },
        "persistence": proof_details,
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit persistent dispatch-state evidence for AGILAB global pipeline DAGs."
    )
    parser.add_argument(
        "--dag",
        type=Path,
        default=None,
        help=f"Path to a DAG JSON contract. Defaults to {SAMPLE_DAG_RELATIVE_PATH}.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path for the persisted dispatch-state JSON proof.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact JSON without indentation.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    report = build_report(dag_path=args.dag, output_path=args.output)
    if args.compact:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
