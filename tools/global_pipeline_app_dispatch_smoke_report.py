#!/usr/bin/env python3
"""Emit real first-unit dispatch-smoke evidence for AGILAB global pipeline DAGs."""

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

from agilab.global_pipeline_app_dispatch_smoke import (
    DEFAULT_RUN_ID,
    READY_ONLY_UNIT_ID,
    REAL_UNIT_ID,
    SCHEMA as APP_DISPATCH_SMOKE_SCHEMA,
    persist_app_dispatch_smoke,
)
from agilab.global_pipeline_dispatch_state import (
    PERSISTENCE_FORMAT,
    SCHEMA as DISPATCH_STATE_SCHEMA,
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
        "global DAG app dispatch smoke report",
        "tools/global_pipeline_app_dispatch_smoke_report.py --compact",
        "real queue_baseline execution",
        "relay_followup readiness-only",
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
        "global_pipeline_app_dispatch_smoke_docs_reference",
        "Global pipeline app dispatch smoke docs reference",
        ok,
        (
            "features docs expose the real first-unit dispatch smoke command"
            if ok
            else "features docs do not expose the real first-unit dispatch smoke command"
        ),
        evidence=[str(DOC_RELATIVE_PATH)],
        details=details,
    )


def _load_failure_report(dag_path: Path | None, exc: Exception) -> dict[str, Any]:
    check = _check_result(
        "global_pipeline_app_dispatch_smoke_load",
        "Global pipeline app dispatch smoke load",
        False,
        "global pipeline app dispatch smoke could not be persisted",
        evidence=[str(dag_path or SAMPLE_DAG_RELATIVE_PATH)],
        details={"error": str(exc)},
    )
    return {
        "report": "Global pipeline app dispatch smoke report",
        "status": "fail",
        "scope": (
            "Executes queue_baseline through the real UAV queue app entry, "
            "persists dispatch state, and marks relay_followup readiness-only."
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


def _resolve_smoke_path(state: dict[str, Any], value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    for unit in state.get("units", []):
        if isinstance(unit, dict) and unit.get("id") == REAL_UNIT_ID:
            workspace = unit.get("real_execution", {}).get("workspace")
            if workspace:
                return Path(str(workspace)) / path
    return path


def _artifact_by_id(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    artifacts = state.get("artifacts", [])
    if not isinstance(artifacts, list):
        return {}
    return {
        str(artifact.get("artifact", "")): artifact
        for artifact in artifacts
        if isinstance(artifact, dict) and artifact.get("artifact")
    }


def _build_proof(
    *,
    repo_root: Path,
    output_path: Path,
    workspace_path: Path,
    dag_path: Path | None,
):
    return persist_app_dispatch_smoke(
        repo_root=repo_root,
        output_path=output_path,
        run_root=workspace_path,
        dag_path=dag_path,
    )


def build_report(
    *,
    repo_root: Path = REPO_ROOT,
    dag_path: Path | None = None,
    output_path: Path | None = None,
    workspace_path: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    if output_path is None:
        with tempfile.TemporaryDirectory(prefix="agilab-app-dispatch-smoke-") as tmp_dir:
            root = Path(tmp_dir)
            return _build_report_with_paths(
                repo_root=repo_root,
                dag_path=dag_path,
                output_path=root / "global_pipeline_app_dispatch_smoke.json",
                workspace_path=workspace_path or (root / "workspace"),
            )
    return _build_report_with_paths(
        repo_root=repo_root,
        dag_path=dag_path,
        output_path=output_path,
        workspace_path=workspace_path or (output_path.parent / "global_pipeline_app_dispatch_smoke_workspace"),
    )


def _build_report_with_paths(
    *,
    repo_root: Path,
    dag_path: Path | None,
    output_path: Path,
    workspace_path: Path,
) -> dict[str, Any]:
    try:
        proof = _build_proof(
            repo_root=repo_root,
            output_path=output_path,
            workspace_path=workspace_path,
            dag_path=dag_path,
        )
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
    queue = unit_by_id.get(REAL_UNIT_ID, {})
    relay = unit_by_id.get(READY_ONLY_UNIT_ID, {})
    queue_execution = queue.get("real_execution", {}) if isinstance(queue, dict) else {}
    metrics = queue_execution.get("summary_metrics", {}) if isinstance(queue_execution, dict) else {}
    artifacts = _artifact_by_id(state)
    queue_metrics_artifact = artifacts.get("queue_metrics", {})
    reduce_artifact = artifacts.get("queue_reduce_summary", {})
    queue_metrics_path = _resolve_smoke_path(state, str(queue_metrics_artifact.get("path", "")))
    reduce_artifact_path = _resolve_smoke_path(state, str(reduce_artifact.get("path", "")))

    checks = [
        _check_result(
            "global_pipeline_app_dispatch_smoke_schema",
            "Global pipeline app dispatch smoke schema",
            proof.ok
            and state.get("schema") == DISPATCH_STATE_SCHEMA
            and state.get("source", {}).get("smoke_schema") == APP_DISPATCH_SMOKE_SCHEMA
            and state.get("persistence_format") == PERSISTENCE_FORMAT
            and state.get("run_id") == DEFAULT_RUN_ID,
            "app dispatch smoke persists the supported dispatch-state JSON schema"
            if proof.ok
            else "app dispatch smoke schema or persistence proof is invalid",
            evidence=[
                "src/agilab/global_pipeline_app_dispatch_smoke.py",
                "src/agilab/global_pipeline_dispatch_state.py",
            ],
            details={
                "schema": state.get("schema"),
                "expected_schema": DISPATCH_STATE_SCHEMA,
                "smoke_schema": state.get("source", {}).get("smoke_schema"),
                "expected_smoke_schema": APP_DISPATCH_SMOKE_SCHEMA,
                "persistence_format": state.get("persistence_format"),
                "run_id": state.get("run_id"),
                "issues": [issue.as_dict() for issue in proof.issues],
            },
        ),
        _check_result(
            "global_pipeline_app_dispatch_smoke_real_queue",
            "Global pipeline app dispatch smoke real queue execution",
            summary.get("real_executed_unit_ids") == [REAL_UNIT_ID]
            and queue.get("dispatch_status") == "completed"
            and queue.get("execution_mode") == "real_app_entry"
            and int(metrics.get("packets_generated", 0) or 0) > 0
            and int(metrics.get("packets_delivered", 0) or 0) >= 0
            and metrics.get("routing_policy") == "queue_aware",
            "queue_baseline executed through the real UAV queue manager and worker",
            evidence=[
                "src/agilab/apps/builtin/uav_queue_project/src/uav_queue/uav_queue.py",
                "src/agilab/apps/builtin/uav_queue_project/src/uav_queue_worker/uav_queue_worker.py",
            ],
            details={
                "real_executed_unit_ids": summary.get("real_executed_unit_ids"),
                "queue_status": queue.get("dispatch_status"),
                "execution_mode": queue.get("execution_mode"),
                "app_entry": queue_execution.get("app_entry"),
                "summary_metrics": metrics,
            },
        ),
        _check_result(
            "global_pipeline_app_dispatch_smoke_artifacts",
            "Global pipeline app dispatch smoke artifacts",
            "queue_metrics" in proof.available_artifact_ids
            and "queue_reduce_summary" in proof.available_artifact_ids
            and queue_metrics_path.is_file()
            and reduce_artifact_path.is_file(),
            "real queue_metrics and reduce-summary artifacts exist on disk",
            evidence=[str(queue_metrics_path), str(reduce_artifact_path)],
            details={
                "available_artifact_ids": list(proof.available_artifact_ids),
                "queue_metrics_path": str(queue_metrics_path),
                "queue_reduce_summary_path": str(reduce_artifact_path),
                "queue_metrics_exists": queue_metrics_path.is_file(),
                "queue_reduce_summary_exists": reduce_artifact_path.is_file(),
            },
        ),
        _check_result(
            "global_pipeline_app_dispatch_smoke_relay_readiness",
            "Global pipeline app dispatch smoke relay readiness",
            summary.get("readiness_only_unit_ids") == [READY_ONLY_UNIT_ID]
            and relay.get("dispatch_status") == "runnable"
            and relay.get("execution_mode") == "readiness_only"
            and relay.get("unblocked_by") == ["queue_metrics"],
            "relay_followup is readiness-only and runnable after queue_metrics is available",
            evidence=["docs/source/data/multi_app_dag_sample.json"],
            details={
                "readiness_only_unit_ids": summary.get("readiness_only_unit_ids"),
                "relay_status": relay.get("dispatch_status"),
                "relay_execution_mode": relay.get("execution_mode"),
                "unblocked_by": relay.get("unblocked_by"),
            },
        ),
        _check_result(
            "global_pipeline_app_dispatch_smoke_persistence",
            "Global pipeline app dispatch smoke JSON round trip",
            proof.round_trip_ok and Path(proof.path).is_file(),
            "app dispatch smoke state is unchanged after JSON write/read",
            evidence=[proof.path],
            details={
                "path": proof.path,
                "path_exists": Path(proof.path).is_file(),
                "round_trip_ok": proof.round_trip_ok,
            },
        ),
        _check_result(
            "global_pipeline_app_dispatch_smoke_provenance",
            "Global pipeline app dispatch smoke provenance",
            state.get("provenance", {}).get("real_app_execution") is True
            and state.get("provenance", {}).get("real_execution_scope") == "first_unit_only"
            and summary.get("real_execution_scope") == "first_unit_only",
            "provenance records first-unit-only real app execution",
            evidence=["tools/global_pipeline_app_dispatch_smoke_report.py"],
            details={
                "provenance": state.get("provenance", {}),
                "summary_real_execution_scope": summary.get("real_execution_scope"),
            },
        ),
        _docs_check(repo_root),
    ]

    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "report": "Global pipeline app dispatch smoke report",
        "status": "pass" if failed == 0 else "fail",
        "scope": (
            "Executes queue_baseline through the real UAV queue app entry, "
            "persists dispatch state, and marks relay_followup readiness-only. "
            "It does not execute the full global DAG."
        ),
        "dag_path": state.get("source", {}).get("dag_path", str(dag_path or SAMPLE_DAG_RELATIVE_PATH)),
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "schema": state.get("schema"),
            "smoke_schema": state.get("source", {}).get("smoke_schema"),
            "run_id": state.get("run_id"),
            "run_status": state.get("run_status"),
            "persistence_format": state.get("persistence_format"),
            "round_trip_ok": proof.round_trip_ok,
            "path": proof.path,
            "unit_count": summary.get("unit_count"),
            "completed_unit_ids": list(proof.completed_unit_ids),
            "runnable_unit_ids": list(proof.runnable_unit_ids),
            "real_executed_unit_ids": list(proof.real_executed_unit_ids),
            "readiness_only_unit_ids": list(proof.readiness_only_unit_ids),
            "available_artifact_ids": list(proof.available_artifact_ids),
            "real_execution_scope": summary.get("real_execution_scope"),
            "event_count": proof.event_count,
            "packets_generated": summary.get("packets_generated"),
            "packets_delivered": summary.get("packets_delivered"),
            "queue_metrics_path": str(queue_metrics_path),
            "queue_reduce_summary_path": str(reduce_artifact_path),
            "issues": [issue.as_dict() for issue in proof.issues],
        },
        "persistence": proof_details,
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit real first-unit dispatch-smoke evidence for AGILAB global pipeline DAGs."
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
        help="Optional path for the persisted app-dispatch smoke JSON proof.",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Optional workspace root for real app artifacts. Defaults to a temp directory.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact JSON without indentation.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    report = build_report(dag_path=args.dag, output_path=args.output, workspace_path=args.workspace)
    if args.compact:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
