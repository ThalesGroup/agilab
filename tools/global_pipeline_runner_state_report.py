#!/usr/bin/env python3
"""Emit read-only runner-state evidence for AGILAB global pipeline DAGs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
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

from agilab.global_pipeline_runner_state import (
    RUNNER_MODE,
    RUN_STATUS,
    SCHEMA,
    build_runner_state,
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
        "global DAG runner state report",
        "tools/global_pipeline_runner_state_report.py --compact",
        "runnable/blocked",
        "retry and partial-rerun metadata",
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
        "global_pipeline_runner_state_docs_reference",
        "Global pipeline runner state docs reference",
        ok,
        (
            "features docs expose the global DAG runner state evidence command"
            if ok
            else "features docs do not expose the global DAG runner state evidence command"
        ),
        evidence=[str(DOC_RELATIVE_PATH)],
        details=details,
    )


def _load_failure_report(dag_path: Path | None, exc: Exception) -> dict[str, Any]:
    check = _check_result(
        "global_pipeline_runner_state_load",
        "Global pipeline runner state load",
        False,
        "global pipeline runner state could not be assembled",
        evidence=[str(dag_path or SAMPLE_DAG_RELATIVE_PATH)],
        details={"error": str(exc)},
    )
    return {
        "report": "Global pipeline runner state report",
        "status": "fail",
        "scope": (
            "Builds a read-only runner-state preview from the global pipeline "
            "execution plan. It exposes dispatch readiness, transitions, retry "
            "metadata, partial-rerun metadata, and operator UI state without "
            "running apps."
        ),
        "dag_path": str(dag_path or SAMPLE_DAG_RELATIVE_PATH),
        "summary": {
            "passed": 0,
            "failed": 1,
            "total": 1,
            "issues": [{"level": "error", "location": "load", "message": str(exc)}],
        },
        "runner_state": {},
        "checks": [check],
    }


def _transition_pairs(units: list[dict[str, Any]]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for unit in units:
        for transition in unit.get("transitions", []):
            if isinstance(transition, dict):
                pairs.add((str(transition.get("from", "")), str(transition.get("to", ""))))
    return pairs


def build_report(
    *,
    repo_root: Path = REPO_ROOT,
    dag_path: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    try:
        state = build_runner_state(repo_root=repo_root, dag_path=dag_path)
    except Exception as exc:
        return _load_failure_report(dag_path, exc)

    state_details = state.as_dict()
    units = state_details["state_units"]
    by_id = {unit["id"]: unit for unit in units}
    transitions = _transition_pairs(units)
    required_transitions = {
        ("pending", "runnable"),
        ("pending", "blocked"),
        ("blocked", "runnable"),
        ("runnable", "completed"),
        ("runnable", "failed"),
        ("failed", "runnable"),
        ("completed", "runnable"),
    }
    provenance_rows = [unit.get("provenance", {}) for unit in units]
    retry_rows = [unit.get("retry", {}) for unit in units]
    partial_rerun_rows = [unit.get("partial_rerun", {}) for unit in units]
    operator_rows = [unit.get("operator_ui", {}) for unit in units]

    checks = [
        _check_result(
            "global_pipeline_runner_state_schema",
            "Global pipeline runner state schema",
            state.ok
            and state.schema == SCHEMA
            and state.runner_mode == RUNNER_MODE
            and state.run_status == RUN_STATUS
            and state.unit_count > 0,
            "runner state uses the supported schema and read-only mode"
            if state.ok
            else "runner state schema or source plan is invalid",
            evidence=["src/agilab/global_pipeline_runner_state.py"],
            details={
                "schema": state.schema,
                "expected_schema": SCHEMA,
                "runner_mode": state.runner_mode,
                "run_status": state.run_status,
                "issues": [issue.as_dict() for issue in state.issues],
            },
        ),
        _check_result(
            "global_pipeline_runner_state_dispatch_queue",
            "Global pipeline runner state dispatch queue",
            state.runnable_count == 1
            and state.blocked_count == 1
            and list(state.runnable_unit_ids) == ["queue_baseline"]
            and list(state.blocked_unit_ids) == ["relay_followup"],
            "runner state exposes runnable and blocked units",
            evidence=["tools/global_pipeline_execution_plan_report.py"],
            details={
                "runnable_count": state.runnable_count,
                "blocked_count": state.blocked_count,
                "runnable_unit_ids": list(state.runnable_unit_ids),
                "blocked_unit_ids": list(state.blocked_unit_ids),
            },
        ),
        _check_result(
            "global_pipeline_runner_state_transitions",
            "Global pipeline runner state transitions",
            required_transitions.issubset(transitions),
            "runner state models pending/runnable/completed/blocked/failed transitions",
            evidence=["src/agilab/global_pipeline_runner_state.py"],
            details={
                "required_transitions": sorted(required_transitions),
                "transitions": sorted(transitions),
                "transition_count": state.transition_count,
            },
        ),
        _check_result(
            "global_pipeline_runner_state_retry_partial_rerun",
            "Global pipeline runner state retry and partial rerun metadata",
            state.retry_policy_count == 2
            and state.partial_rerun_record_count == 2
            and all(row.get("policy") == "metadata_only" for row in retry_rows)
            and all(row.get("policy") == "metadata_only" for row in partial_rerun_rows),
            "runner state records retry and partial-rerun metadata without dispatching apps",
            evidence=["src/agilab/global_pipeline_runner_state.py"],
            details={
                "retry_policy_count": state.retry_policy_count,
                "partial_rerun_record_count": state.partial_rerun_record_count,
                "retry": retry_rows,
                "partial_rerun": partial_rerun_rows,
            },
        ),
        _check_result(
            "global_pipeline_runner_state_operator_ui",
            "Global pipeline runner state operator UI projection",
            state.operator_state_count == 2
            and by_id.get("queue_baseline", {}).get("operator_ui", {}).get("state") == "ready_to_dispatch"
            and by_id.get("relay_followup", {}).get("operator_ui", {}).get("state") == "waiting_for_artifacts"
            and "queue_metrics" in by_id.get("relay_followup", {}).get("operator_ui", {}).get("message", ""),
            "runner state exposes operator-facing readiness messages",
            evidence=["src/agilab/global_pipeline_runner_state.py"],
            details={"operator_ui": operator_rows},
        ),
        _check_result(
            "global_pipeline_runner_state_provenance",
            "Global pipeline runner state provenance",
            len(provenance_rows) == state.unit_count
            and all(row.get("source_plan_schema") == state.plan_schema for row in provenance_rows)
            and all(row.get("source_dag") == state.dag_path for row in provenance_rows)
            and all(row.get("pipeline_view") for row in provenance_rows),
            "runner state keeps provenance back to the execution plan, DAG, and app-local views",
            evidence=[
                "tools/global_pipeline_execution_plan_report.py",
                "docs/source/data/multi_app_dag_sample.json",
                "src/agilab/apps/builtin/*/pipeline_view.dot",
            ],
            details={"provenance": provenance_rows},
        ),
        _docs_check(repo_root),
    ]

    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "report": "Global pipeline runner state report",
        "status": "pass" if failed == 0 else "fail",
        "scope": (
            "Builds a read-only runner-state preview from the global pipeline "
            "execution plan. It exposes dispatch readiness, transitions, retry "
            "metadata, partial-rerun metadata, and operator UI state without "
            "running apps."
        ),
        "dag_path": state.dag_path,
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "schema": state.schema,
            "runner_mode": state.runner_mode,
            "run_status": state.run_status,
            "plan_schema": state.plan_schema,
            "plan_runner_status": state.plan_runner_status,
            "unit_count": state.unit_count,
            "runnable_count": state.runnable_count,
            "blocked_count": state.blocked_count,
            "completed_count": state.completed_count,
            "failed_count": state.failed_count,
            "runnable_unit_ids": list(state.runnable_unit_ids),
            "blocked_unit_ids": list(state.blocked_unit_ids),
            "transition_count": state.transition_count,
            "retry_policy_count": state.retry_policy_count,
            "partial_rerun_record_count": state.partial_rerun_record_count,
            "operator_state_count": state.operator_state_count,
            "execution_order": list(state.execution_order),
            "issues": [issue.as_dict() for issue in state.issues],
        },
        "runner_state": state_details,
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit read-only runner-state evidence for AGILAB global pipeline DAGs."
    )
    parser.add_argument(
        "--dag",
        type=Path,
        default=None,
        help=f"Path to a DAG JSON contract. Defaults to {SAMPLE_DAG_RELATIVE_PATH}.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact JSON without indentation.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    report = build_report(dag_path=args.dag)
    if args.compact:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
