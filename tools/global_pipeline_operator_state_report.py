#!/usr/bin/env python3
"""Emit operator-state evidence for AGILAB global pipeline dispatch runs."""

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

from agilab.global_pipeline_operator_state import (
    DEFAULT_RUN_ID,
    PERSISTENCE_FORMAT,
    SCHEMA,
    persist_operator_state,
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
        "global DAG operator state report",
        "tools/global_pipeline_operator_state_report.py --compact",
        "operator-visible state",
        "retry/partial-rerun actions",
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
        "global_pipeline_operator_state_docs_reference",
        "Global pipeline operator state docs reference",
        ok,
        (
            "features docs expose the global DAG operator state evidence command"
            if ok
            else "features docs do not expose the global DAG operator state evidence command"
        ),
        evidence=[str(DOC_RELATIVE_PATH)],
        details=details,
    )


def _load_failure_report(
    dispatch_state_path: Path | None,
    dag_path: Path | None,
    exc: Exception,
) -> dict[str, Any]:
    evidence_path = dispatch_state_path or dag_path or SAMPLE_DAG_RELATIVE_PATH
    check = _check_result(
        "global_pipeline_operator_state_load",
        "Global pipeline operator state load",
        False,
        "global pipeline operator state could not be persisted",
        evidence=[str(evidence_path)],
        details={"error": str(exc)},
    )
    return {
        "report": "Global pipeline operator state report",
        "status": "fail",
        "scope": (
            "Reads a persisted full-DAG dispatch smoke state and projects "
            "operator-visible unit state, handoffs, artifacts, retry actions, "
            "and partial-rerun actions."
        ),
        "dag_path": str(dag_path or SAMPLE_DAG_RELATIVE_PATH),
        "summary": {
            "passed": 0,
            "failed": 1,
            "total": 1,
            "issues": [{"level": "error", "location": "load", "message": str(exc)}],
        },
        "operator_state": {},
        "checks": [check],
    }


def _build_proof(
    *,
    repo_root: Path,
    output_path: Path,
    dispatch_state_path: Path | None,
    workspace_path: Path | None,
    dag_path: Path | None,
):
    return persist_operator_state(
        repo_root=repo_root,
        output_path=output_path,
        dispatch_state_path=dispatch_state_path,
        workspace_path=workspace_path,
        dag_path=dag_path,
    )


def build_report(
    *,
    repo_root: Path = REPO_ROOT,
    dag_path: Path | None = None,
    dispatch_state_path: Path | None = None,
    output_path: Path | None = None,
    workspace_path: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    if output_path is None:
        with tempfile.TemporaryDirectory(prefix="agilab-operator-state-") as tmp_dir:
            root = Path(tmp_dir)
            return _build_report_with_paths(
                repo_root=repo_root,
                dag_path=dag_path,
                dispatch_state_path=dispatch_state_path,
                output_path=root / "global_pipeline_operator_state.json",
                workspace_path=workspace_path or (root / "workspace"),
            )
    return _build_report_with_paths(
        repo_root=repo_root,
        dag_path=dag_path,
        dispatch_state_path=dispatch_state_path,
        output_path=output_path,
        workspace_path=workspace_path
        or (output_path.parent / "global_pipeline_operator_state_workspace"),
    )


def _build_report_with_paths(
    *,
    repo_root: Path,
    dag_path: Path | None,
    dispatch_state_path: Path | None,
    output_path: Path,
    workspace_path: Path | None,
) -> dict[str, Any]:
    try:
        proof = _build_proof(
            repo_root=repo_root,
            output_path=output_path,
            dispatch_state_path=dispatch_state_path,
            workspace_path=workspace_path,
            dag_path=dag_path,
        )
    except Exception as exc:
        return _load_failure_report(dispatch_state_path, dag_path, exc)

    proof_details = proof.as_dict()
    state = proof.operator_state
    summary = state.get("summary", {})
    source = state.get("source", {})
    unit_by_id = {
        unit.get("id"): unit
        for unit in state.get("operator_units", [])
        if isinstance(unit, dict)
    }
    handoffs = state.get("handoffs", [])

    checks = [
        _check_result(
            "global_pipeline_operator_state_schema",
            "Global pipeline operator state schema",
            proof.ok
            and state.get("schema") == SCHEMA
            and state.get("persistence_format") == PERSISTENCE_FORMAT
            and state.get("run_id") == DEFAULT_RUN_ID
            and source.get("dispatch_state_schema") == "agilab.global_pipeline_dispatch_state.v1",
            "operator state uses the supported schema and reads persisted dispatch-state JSON"
            if proof.ok
            else "operator state schema or source dispatch-state proof is invalid",
            evidence=[
                "src/agilab/global_pipeline_operator_state.py",
                proof.dispatch_state_path,
            ],
            details={
                "schema": state.get("schema"),
                "expected_schema": SCHEMA,
                "persistence_format": state.get("persistence_format"),
                "run_id": state.get("run_id"),
                "source": source,
                "issues": [issue.as_dict() for issue in proof.issues],
            },
        ),
        _check_result(
            "global_pipeline_operator_state_units",
            "Global pipeline operator state units",
            summary.get("completed_unit_ids") == ["queue_baseline", "relay_followup"]
            and unit_by_id.get("queue_baseline", {}).get("operator_state") == "completed"
            and unit_by_id.get("relay_followup", {}).get("operator_state") == "completed"
            and summary.get("source_real_execution_scope") == "full_dag_smoke",
            "operator state exposes completed queue and relay units from the full dispatch smoke",
            evidence=["tools/global_pipeline_app_dispatch_smoke_report.py"],
            details={
                "completed_unit_ids": summary.get("completed_unit_ids"),
                "source_real_execution_scope": summary.get("source_real_execution_scope"),
                "unit_states": {
                    unit_id: unit.get("operator_state")
                    for unit_id, unit in unit_by_id.items()
                },
            },
        ),
        _check_result(
            "global_pipeline_operator_state_artifacts_handoffs",
            "Global pipeline operator state artifacts and handoffs",
            "queue_metrics" in summary.get("available_artifact_ids", [])
            and "relay_metrics" in summary.get("available_artifact_ids", [])
            and summary.get("handoff_count") == 1
            and any(
                handoff.get("from") == "queue_baseline"
                and handoff.get("to") == "relay_followup"
                and handoff.get("artifact") == "queue_metrics"
                and handoff.get("status") == "available"
                for handoff in handoffs
                if isinstance(handoff, dict)
            ),
            "operator state exposes queue-to-relay artifact handoff and available metrics",
            evidence=["docs/source/data/multi_app_dag_sample.json"],
            details={
                "available_artifact_ids": summary.get("available_artifact_ids"),
                "handoffs": handoffs,
            },
        ),
        _check_result(
            "global_pipeline_operator_state_actions",
            "Global pipeline operator state actions",
            summary.get("retry_action_count") == 2
            and summary.get("partial_rerun_action_count") == 2
            and all(
                any(
                    action.get("action") == "retry" and action.get("enabled")
                    for action in unit.get("actions", [])
                )
                for unit in unit_by_id.values()
            )
            and all(
                any(
                    action.get("action") == "partial_rerun"
                    and action.get("enabled")
                    for action in unit.get("actions", [])
                )
                for unit in unit_by_id.values()
            ),
            "operator state exposes retry and partial-rerun actions for completed real app runs",
            evidence=["src/agilab/global_pipeline_operator_state.py"],
            details={
                "retry_action_count": summary.get("retry_action_count"),
                "partial_rerun_action_count": summary.get("partial_rerun_action_count"),
                "actions": {
                    unit_id: unit.get("actions", [])
                    for unit_id, unit in unit_by_id.items()
                },
            },
        ),
        _check_result(
            "global_pipeline_operator_state_persistence",
            "Global pipeline operator state JSON round trip",
            proof.round_trip_ok and Path(proof.path).is_file(),
            "operator state is unchanged after JSON write/read",
            evidence=[proof.path],
            details={
                "path": proof.path,
                "path_exists": Path(proof.path).is_file(),
                "round_trip_ok": proof.round_trip_ok,
            },
        ),
        _docs_check(repo_root),
    ]

    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "report": "Global pipeline operator state report",
        "status": "pass" if failed == 0 else "fail",
        "scope": (
            "Reads a persisted full-DAG dispatch smoke state and projects "
            "operator-visible unit state, handoffs, artifacts, retry actions, "
            "and partial-rerun actions. It is a state contract, not a live UI."
        ),
        "dag_path": str(dag_path or SAMPLE_DAG_RELATIVE_PATH),
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
            "dispatch_state_path": proof.dispatch_state_path,
            "unit_count": summary.get("unit_count"),
            "visible_unit_count": proof.visible_unit_count,
            "completed_unit_ids": list(proof.completed_unit_ids),
            "operator_state_count": summary.get("operator_state_count"),
            "available_artifact_ids": summary.get("available_artifact_ids"),
            "handoff_count": proof.handoff_count,
            "retry_action_count": proof.retry_action_count,
            "partial_rerun_action_count": proof.partial_rerun_action_count,
            "operator_action_count": summary.get("operator_action_count"),
            "source_real_execution_scope": summary.get("source_real_execution_scope"),
            "issues": [issue.as_dict() for issue in proof.issues],
        },
        "operator_state": proof_details,
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit operator-state evidence for AGILAB global pipeline dispatch runs."
    )
    parser.add_argument(
        "--dag",
        type=Path,
        default=None,
        help=f"Path to a DAG JSON contract. Defaults to {SAMPLE_DAG_RELATIVE_PATH}.",
    )
    parser.add_argument(
        "--dispatch-state",
        type=Path,
        default=None,
        help="Optional existing persisted full-DAG dispatch smoke JSON state to read.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path for the persisted operator-state JSON proof.",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Optional workspace root when generating the dispatch smoke state.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact JSON without indentation.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    report = build_report(
        dag_path=args.dag,
        dispatch_state_path=args.dispatch_state,
        output_path=args.output,
        workspace_path=args.workspace,
    )
    if args.compact:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
