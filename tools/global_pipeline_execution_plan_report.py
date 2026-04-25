#!/usr/bin/env python3
"""Emit read-only execution-plan evidence for AGILAB global pipeline DAGs."""

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

from agilab.global_pipeline_execution_plan import SCHEMA, build_execution_plan


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
        "global DAG execution plan report",
        "tools/global_pipeline_execution_plan_report.py --compact",
        "pending/not_executed",
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
        "global_pipeline_execution_plan_docs_reference",
        "Global pipeline execution plan docs reference",
        ok,
        (
            "features docs expose the global DAG execution plan evidence command"
            if ok
            else "features docs do not expose the global DAG execution plan evidence command"
        ),
        evidence=[str(DOC_RELATIVE_PATH)],
        details=details,
    )


def _load_failure_report(dag_path: Path | None, exc: Exception) -> dict[str, Any]:
    check = _check_result(
        "global_pipeline_execution_plan_load",
        "Global pipeline execution plan load",
        False,
        "global pipeline execution plan could not be assembled",
        evidence=[str(dag_path or SAMPLE_DAG_RELATIVE_PATH)],
        details={"error": str(exc)},
    )
    return {
        "report": "Global pipeline execution plan report",
        "status": "fail",
        "scope": (
            "Builds a read-only execution plan from the global pipeline DAG. "
            "It assigns pending/not_executed state and dependency metadata but "
            "does not run apps."
        ),
        "dag_path": str(dag_path or SAMPLE_DAG_RELATIVE_PATH),
        "summary": {
            "passed": 0,
            "failed": 1,
            "total": 1,
            "issues": [{"level": "error", "location": "load", "message": str(exc)}],
        },
        "execution_plan": {},
        "checks": [check],
    }


def build_report(
    *,
    repo_root: Path = REPO_ROOT,
    dag_path: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    try:
        plan = build_execution_plan(repo_root=repo_root, dag_path=dag_path)
    except Exception as exc:
        return _load_failure_report(dag_path, exc)

    plan_details = plan.as_dict()
    units = plan_details["runnable_units"]
    provenance_rows = [
        unit.get("provenance", {})
        for unit in units
    ]
    relay_dependencies = units[1]["artifact_dependencies"] if len(units) > 1 else []

    checks = [
        _check_result(
            "global_pipeline_execution_plan_schema",
            "Global pipeline execution plan schema",
            plan.ok and plan.schema == SCHEMA and plan.unit_count > 0,
            "execution plan uses the supported schema and has runnable units"
            if plan.ok
            else "execution plan schema or source graph is invalid",
            evidence=["src/agilab/global_pipeline_execution_plan.py"],
            details={
                "schema": plan.schema,
                "expected_schema": SCHEMA,
                "graph_schema": plan.graph_schema,
                "issues": [issue.as_dict() for issue in plan.issues],
            },
        ),
        _check_result(
            "global_pipeline_execution_plan_order",
            "Global pipeline execution plan order",
            list(plan.execution_order) == ["queue_baseline", "relay_followup"]
            and [unit["id"] for unit in units] == ["queue_baseline", "relay_followup"],
            "execution plan preserves global DAG order",
            evidence=[plan.dag_path],
            details={
                "execution_order": list(plan.execution_order),
                "unit_ids": [unit["id"] for unit in units],
            },
        ),
        _check_result(
            "global_pipeline_execution_plan_state",
            "Global pipeline execution plan state",
            plan.pending_count == 2
            and plan.not_executed_count == 2
            and list(plan.ready_unit_ids) == ["queue_baseline"]
            and list(plan.blocked_unit_ids) == ["relay_followup"],
            "execution plan assigns pending/not_executed state and ready/blocked units",
            evidence=["src/agilab/global_pipeline_execution_plan.py"],
            details={
                "pending_count": plan.pending_count,
                "not_executed_count": plan.not_executed_count,
                "ready_unit_ids": list(plan.ready_unit_ids),
                "blocked_unit_ids": list(plan.blocked_unit_ids),
            },
        ),
        _check_result(
            "global_pipeline_execution_plan_artifact_dependencies",
            "Global pipeline execution plan artifact dependencies",
            plan.artifact_dependency_count == 1
            and bool(relay_dependencies)
            and relay_dependencies[0]["artifact"] == "queue_metrics",
            "execution plan records the queue_metrics handoff dependency",
            evidence=[plan.dag_path],
            details={
                "artifact_dependency_count": plan.artifact_dependency_count,
                "relay_dependencies": relay_dependencies,
            },
        ),
        _check_result(
            "global_pipeline_execution_plan_provenance",
            "Global pipeline execution plan provenance",
            len(provenance_rows) == plan.unit_count
            and all(row.get("source_dag") == plan.dag_path for row in provenance_rows)
            and all(row.get("pipeline_view") for row in provenance_rows),
            "execution plan keeps provenance for DAG and app-local pipeline views",
            evidence=[plan.dag_path, "src/agilab/apps/builtin/*/pipeline_view.dot"],
            details={"provenance": provenance_rows},
        ),
        _docs_check(repo_root),
    ]

    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "report": "Global pipeline execution plan report",
        "status": "pass" if failed == 0 else "fail",
        "scope": (
            "Builds a read-only execution plan from the global pipeline DAG. "
            "It assigns pending/not_executed state and dependency metadata but "
            "does not run apps."
        ),
        "dag_path": plan.dag_path,
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "schema": plan.schema,
            "runner_status": plan.runner_status,
            "unit_count": plan.unit_count,
            "pending_count": plan.pending_count,
            "not_executed_count": plan.not_executed_count,
            "ready_unit_ids": list(plan.ready_unit_ids),
            "blocked_unit_ids": list(plan.blocked_unit_ids),
            "artifact_dependency_count": plan.artifact_dependency_count,
            "execution_order": list(plan.execution_order),
            "issues": [issue.as_dict() for issue in plan.issues],
        },
        "execution_plan": plan_details,
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit read-only execution-plan evidence for AGILAB global pipeline DAGs."
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
