#!/usr/bin/env python3
"""Emit live-update payload evidence for AGILAB global pipeline runs."""

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

from agilab.global_pipeline_live_state_updates import (
    DEFAULT_RUN_ID,
    PERSISTENCE_FORMAT,
    SCHEMA,
    persist_live_state_updates,
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
        "global DAG live state updates report",
        "tools/global_pipeline_live_state_updates_report.py --compact",
        "live orchestration-state updates",
        "deterministic update stream",
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
        "global_pipeline_live_state_updates_docs_reference",
        "Global pipeline live state updates docs reference",
        ok,
        (
            "features docs expose the global DAG live-state update command"
            if ok
            else "features docs do not expose the global DAG live-state update command"
        ),
        evidence=[str(DOC_RELATIVE_PATH)],
        details=details,
    )


def _load_failure_report(
    dependency_view_path: Path | None,
    dag_path: Path | None,
    exc: Exception,
) -> dict[str, Any]:
    evidence_path = dependency_view_path or dag_path or SAMPLE_DAG_RELATIVE_PATH
    check = _check_result(
        "global_pipeline_live_state_updates_load",
        "Global pipeline live state updates load",
        False,
        "global pipeline live state updates could not be persisted",
        evidence=[str(evidence_path)],
        details={"error": str(exc)},
    )
    return {
        "report": "Global pipeline live state updates report",
        "status": "fail",
        "scope": (
            "Reads a persisted dependency-view JSON proof and projects a "
            "deterministic update stream for full-DAG operator refreshes."
        ),
        "dag_path": str(dag_path or SAMPLE_DAG_RELATIVE_PATH),
        "summary": {
            "passed": 0,
            "failed": 1,
            "total": 1,
            "issues": [{"level": "error", "location": "load", "message": str(exc)}],
        },
        "live_state_updates": {},
        "checks": [check],
    }


def _build_proof(
    *,
    repo_root: Path,
    output_path: Path,
    dependency_view_path: Path | None,
    workspace_path: Path | None,
    dag_path: Path | None,
):
    return persist_live_state_updates(
        repo_root=repo_root,
        output_path=output_path,
        dependency_view_path=dependency_view_path,
        workspace_path=workspace_path,
        dag_path=dag_path,
    )


def build_report(
    *,
    repo_root: Path = REPO_ROOT,
    dag_path: Path | None = None,
    dependency_view_path: Path | None = None,
    output_path: Path | None = None,
    workspace_path: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    if output_path is None:
        with tempfile.TemporaryDirectory(prefix="agilab-live-state-updates-") as tmp_dir:
            root = Path(tmp_dir)
            return _build_report_with_paths(
                repo_root=repo_root,
                dag_path=dag_path,
                dependency_view_path=dependency_view_path,
                output_path=root / "global_pipeline_live_state_updates.json",
                workspace_path=workspace_path or (root / "workspace"),
            )
    return _build_report_with_paths(
        repo_root=repo_root,
        dag_path=dag_path,
        dependency_view_path=dependency_view_path,
        output_path=output_path,
        workspace_path=workspace_path
        or (output_path.parent / "global_pipeline_live_state_updates_workspace"),
    )


def _build_report_with_paths(
    *,
    repo_root: Path,
    dag_path: Path | None,
    dependency_view_path: Path | None,
    output_path: Path,
    workspace_path: Path | None,
) -> dict[str, Any]:
    try:
        proof = _build_proof(
            repo_root=repo_root,
            output_path=output_path,
            dependency_view_path=dependency_view_path,
            workspace_path=workspace_path,
            dag_path=dag_path,
        )
    except Exception as exc:
        return _load_failure_report(dependency_view_path, dag_path, exc)

    proof_details = proof.as_dict()
    state = proof.live_state_updates
    summary = state.get("summary", {})
    source = state.get("source", {})
    stream = state.get("update_stream", {})
    updates = state.get("updates", [])
    kinds = [
        update.get("kind")
        for update in updates
        if isinstance(update, dict)
    ]
    sequences = [
        update.get("sequence")
        for update in updates
        if isinstance(update, dict)
    ]
    update_by_kind = {
        update.get("kind"): update
        for update in updates
        if isinstance(update, dict)
    }
    action_update = update_by_kind.get("operator_actions_update", {})
    dependency_update = update_by_kind.get("dependency_state_update", {})
    artifact_update = update_by_kind.get("artifact_state_update", {})

    checks = [
        _check_result(
            "global_pipeline_live_state_updates_schema",
            "Global pipeline live state updates schema",
            proof.ok
            and state.get("schema") == SCHEMA
            and state.get("persistence_format") == PERSISTENCE_FORMAT
            and state.get("run_id") == DEFAULT_RUN_ID
            and source.get("dependency_view_schema")
            == "agilab.global_pipeline_dependency_view.v1",
            "live state updates use the supported schema and read dependency-view JSON"
            if proof.ok
            else "live state update schema or dependency-view source is invalid",
            evidence=[
                "src/agilab/global_pipeline_live_state_updates.py",
                proof.dependency_view_path,
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
            "global_pipeline_live_state_updates_sequence",
            "Global pipeline live state updates sequence",
            sequences == [1, 2, 3, 4, 5, 6]
            and kinds == [
                "dependency_graph_ready",
                "unit_state_update",
                "artifact_state_update",
                "dependency_state_update",
                "unit_state_update",
                "operator_actions_update",
            ]
            and stream.get("mode") == "deterministic_replay_contract"
            and stream.get("live_runtime_service") is False,
            "live state update stream is deterministic and ordered",
            evidence=["src/agilab/global_pipeline_live_state_updates.py"],
            details={
                "sequences": sequences,
                "kinds": kinds,
                "update_stream": stream,
            },
        ),
        _check_result(
            "global_pipeline_live_state_updates_units",
            "Global pipeline live state updates unit states",
            summary.get("unit_update_count") == 2
            and state.get("latest_state", {}).get("unit_states", {})
            == {
                "queue_baseline": "completed",
                "relay_followup": "completed",
            },
            "live state updates carry completed queue and relay unit states",
            evidence=["tools/global_pipeline_operator_state_report.py"],
            details={
                "unit_update_count": summary.get("unit_update_count"),
                "unit_states": state.get("latest_state", {}).get("unit_states", {}),
            },
        ),
        _check_result(
            "global_pipeline_live_state_updates_dependency",
            "Global pipeline live state updates dependency state",
            summary.get("artifact_update_count") == 1
            and summary.get("dependency_update_count") == 1
            and artifact_update.get("target_id") == "queue_metrics"
            and artifact_update.get("status") == "available"
            and dependency_update.get("payload", {}).get("from") == "queue_baseline"
            and dependency_update.get("payload", {}).get("to") == "relay_followup"
            and dependency_update.get("payload", {}).get("artifact") == "queue_metrics",
            "live state updates include artifact and cross-app dependency refreshes",
            evidence=["tools/global_pipeline_dependency_view_report.py"],
            details={
                "artifact_update": artifact_update,
                "dependency_update": dependency_update,
            },
        ),
        _check_result(
            "global_pipeline_live_state_updates_actions",
            "Global pipeline live state updates operator actions",
            summary.get("action_update_count") == 1
            and summary.get("retry_action_count") == 2
            and summary.get("partial_rerun_action_count") == 2
            and action_update.get("status") == "ready_for_operator_review",
            "live state updates expose retry and partial-rerun action refreshes",
            evidence=["tools/global_pipeline_operator_state_report.py"],
            details={"action_update": action_update},
        ),
        _check_result(
            "global_pipeline_live_state_updates_persistence",
            "Global pipeline live state updates JSON round trip",
            proof.round_trip_ok and Path(proof.path).is_file(),
            "live state updates are unchanged after JSON write/read",
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
        "report": "Global pipeline live state updates report",
        "status": "pass" if failed == 0 else "fail",
        "scope": (
            "Reads a persisted dependency-view JSON proof and projects live "
            "orchestration-state updates as a deterministic JSON stream. "
            "It is an update payload contract, not a streaming service or UI."
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
            "dependency_view_path": proof.dependency_view_path,
            "update_count": proof.update_count,
            "graph_update_count": summary.get("graph_update_count"),
            "unit_update_count": proof.unit_update_count,
            "artifact_update_count": proof.artifact_update_count,
            "dependency_update_count": proof.dependency_update_count,
            "action_update_count": proof.action_update_count,
            "retry_action_count": summary.get("retry_action_count"),
            "partial_rerun_action_count": summary.get("partial_rerun_action_count"),
            "visible_unit_ids": summary.get("visible_unit_ids"),
            "cross_app_edge_count": summary.get("cross_app_edge_count"),
            "source_real_execution_scope": summary.get("source_real_execution_scope"),
            "issues": [issue.as_dict() for issue in proof.issues],
        },
        "live_state_updates": proof_details,
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit live-update payload evidence for AGILAB global pipeline runs."
    )
    parser.add_argument(
        "--dag",
        type=Path,
        default=None,
        help=f"Path to a DAG JSON contract. Defaults to {SAMPLE_DAG_RELATIVE_PATH}.",
    )
    parser.add_argument(
        "--dependency-view",
        type=Path,
        default=None,
        help="Optional existing persisted dependency-view JSON to read.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path for the persisted live-state update JSON proof.",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Optional workspace root when generating upstream state.",
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
        dependency_view_path=args.dependency_view,
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
