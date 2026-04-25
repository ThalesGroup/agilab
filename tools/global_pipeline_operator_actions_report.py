#!/usr/bin/env python3
"""Emit operator action execution evidence for AGILAB global pipeline runs."""

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

from agilab.global_pipeline_operator_actions import (
    DEFAULT_RUN_ID,
    PERSISTENCE_FORMAT,
    SCHEMA,
    persist_operator_actions,
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
        "global DAG operator actions report",
        "tools/global_pipeline_operator_actions_report.py --compact",
        "retry and partial-rerun action execution",
        "real app-entry action replay",
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
        "global_pipeline_operator_actions_docs_reference",
        "Global pipeline operator actions docs reference",
        ok,
        (
            "features docs expose the global DAG operator action command"
            if ok
            else "features docs do not expose the global DAG operator action command"
        ),
        evidence=[str(DOC_RELATIVE_PATH)],
        details=details,
    )


def _load_failure_report(
    live_state_updates_path: Path | None,
    dag_path: Path | None,
    exc: Exception,
) -> dict[str, Any]:
    evidence_path = live_state_updates_path or dag_path or SAMPLE_DAG_RELATIVE_PATH
    check = _check_result(
        "global_pipeline_operator_actions_load",
        "Global pipeline operator actions load",
        False,
        "global pipeline operator actions could not be persisted",
        evidence=[str(evidence_path)],
        details={"error": str(exc)},
    )
    return {
        "report": "Global pipeline operator actions report",
        "status": "fail",
        "scope": (
            "Reads live-state update payloads, executes retry and partial-rerun "
            "operator requests through real app-entry action replays, and "
            "persists action outcomes."
        ),
        "dag_path": str(dag_path or SAMPLE_DAG_RELATIVE_PATH),
        "summary": {
            "passed": 0,
            "failed": 1,
            "total": 1,
            "issues": [{"level": "error", "location": "load", "message": str(exc)}],
        },
        "operator_actions": {},
        "checks": [check],
    }


def _build_proof(
    *,
    repo_root: Path,
    output_path: Path,
    live_state_updates_path: Path | None,
    workspace_path: Path | None,
    dag_path: Path | None,
):
    return persist_operator_actions(
        repo_root=repo_root,
        output_path=output_path,
        live_state_updates_path=live_state_updates_path,
        workspace_path=workspace_path,
        dag_path=dag_path,
    )


def build_report(
    *,
    repo_root: Path = REPO_ROOT,
    dag_path: Path | None = None,
    live_state_updates_path: Path | None = None,
    output_path: Path | None = None,
    workspace_path: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    if output_path is None:
        with tempfile.TemporaryDirectory(prefix="agilab-operator-actions-") as tmp_dir:
            root = Path(tmp_dir)
            return _build_report_with_paths(
                repo_root=repo_root,
                dag_path=dag_path,
                live_state_updates_path=live_state_updates_path,
                output_path=root / "global_pipeline_operator_actions.json",
                workspace_path=workspace_path or (root / "workspace"),
            )
    return _build_report_with_paths(
        repo_root=repo_root,
        dag_path=dag_path,
        live_state_updates_path=live_state_updates_path,
        output_path=output_path,
        workspace_path=workspace_path
        or (output_path.parent / "global_pipeline_operator_actions_workspace"),
    )


def _artifact_paths(artifacts: Sequence[dict[str, Any]]) -> list[str]:
    return [
        str(artifact.get("path", ""))
        for artifact in artifacts
        if isinstance(artifact, dict) and artifact.get("path")
    ]


def _build_report_with_paths(
    *,
    repo_root: Path,
    dag_path: Path | None,
    live_state_updates_path: Path | None,
    output_path: Path,
    workspace_path: Path | None,
) -> dict[str, Any]:
    try:
        proof = _build_proof(
            repo_root=repo_root,
            output_path=output_path,
            live_state_updates_path=live_state_updates_path,
            workspace_path=workspace_path,
            dag_path=dag_path,
        )
    except Exception as exc:
        return _load_failure_report(live_state_updates_path, dag_path, exc)

    proof_details = proof.as_dict()
    state = proof.operator_actions
    summary = state.get("summary", {})
    source = state.get("source", {})
    requests = state.get("requests", [])
    artifacts = state.get("artifacts", [])
    events = state.get("events", [])
    request_by_action = {
        request.get("action"): request
        for request in requests
        if isinstance(request, dict)
    }
    artifact_paths = _artifact_paths(artifacts)
    artifact_path_exists = {path: Path(path).is_file() for path in artifact_paths}
    queue_retry = request_by_action.get("retry", {})
    relay_partial = request_by_action.get("partial_rerun", {})

    checks = [
        _check_result(
            "global_pipeline_operator_actions_schema",
            "Global pipeline operator actions schema",
            proof.ok
            and state.get("schema") == SCHEMA
            and state.get("persistence_format") == PERSISTENCE_FORMAT
            and state.get("run_id") == DEFAULT_RUN_ID
            and source.get("live_state_updates_schema")
            == "agilab.global_pipeline_live_state_updates.v1",
            "operator actions use the supported schema and read live-state updates JSON"
            if proof.ok
            else "operator action schema or live-state update source is invalid",
            evidence=[
                "src/agilab/global_pipeline_operator_actions.py",
                proof.live_state_updates_path,
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
            "global_pipeline_operator_actions_requests",
            "Global pipeline operator actions requests",
            summary.get("action_request_count") == 2
            and summary.get("completed_action_count") == 2
            and queue_retry.get("action_id") == "queue_baseline:retry"
            and relay_partial.get("action_id") == "relay_followup:partial_rerun"
            and relay_partial.get("consumed_artifact_ids") == ["queue_metrics_retry"],
            "operator action execution accepts retry and partial-rerun requests",
            evidence=["tools/global_pipeline_live_state_updates_report.py"],
            details={
                "requests": requests,
                "event_kinds": [
                    event.get("kind")
                    for event in events
                    if isinstance(event, dict)
                ],
            },
        ),
        _check_result(
            "global_pipeline_operator_actions_real_replay",
            "Global pipeline operator actions real app-entry replay",
            summary.get("real_action_execution_count") == 2
            and summary.get("retry_execution_count") == 1
            and summary.get("partial_rerun_execution_count") == 1
            and all(artifact_path_exists.values())
            and all(
                int(artifact.get("packets_generated", 0) or 0) > 0
                for artifact in artifacts
                if isinstance(artifact, dict)
                and artifact.get("kind") == "summary_metrics"
            ),
            "retry and partial-rerun action execution produce real app-entry artifacts",
            evidence=artifact_paths,
            details={
                "artifact_paths": artifact_paths,
                "artifact_path_exists": artifact_path_exists,
                "artifacts": artifacts,
            },
        ),
        _check_result(
            "global_pipeline_operator_actions_live_update_source",
            "Global pipeline operator actions live-update source",
            source.get("live_state_updates_run_status") == "ready_for_operator_review"
            and source.get("source_real_execution_scope") == "full_dag_smoke"
            and state.get("operator_controls", {}).get("request_source") == "json_contract"
            and state.get("operator_controls", {}).get("ui_component") is False,
            "operator action execution keeps provenance to the live-update payload contract",
            evidence=["tools/global_pipeline_live_state_updates_report.py"],
            details={
                "source": source,
                "operator_controls": state.get("operator_controls", {}),
            },
        ),
        _check_result(
            "global_pipeline_operator_actions_persistence",
            "Global pipeline operator actions JSON round trip",
            proof.round_trip_ok and Path(proof.path).is_file(),
            "operator actions are unchanged after JSON write/read",
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
        "report": "Global pipeline operator actions report",
        "status": "pass" if failed == 0 else "fail",
        "scope": (
            "Reads live-state update payloads, executes retry and partial-rerun "
            "operator requests through real app-entry action replays, and "
            "persists action outcomes. It is not a UI control surface."
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
            "live_state_updates_path": proof.live_state_updates_path,
            "action_request_count": proof.action_request_count,
            "completed_action_count": proof.completed_action_count,
            "retry_execution_count": proof.retry_execution_count,
            "partial_rerun_execution_count": proof.partial_rerun_execution_count,
            "real_action_execution_count": proof.real_action_execution_count,
            "output_artifact_count": summary.get("output_artifact_count"),
            "event_count": summary.get("event_count"),
            "source_real_execution_scope": summary.get("source_real_execution_scope"),
            "issues": [issue.as_dict() for issue in proof.issues],
        },
        "operator_actions": proof_details,
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit operator action execution evidence for AGILAB global pipeline runs."
    )
    parser.add_argument(
        "--dag",
        type=Path,
        default=None,
        help=f"Path to a DAG JSON contract. Defaults to {SAMPLE_DAG_RELATIVE_PATH}.",
    )
    parser.add_argument(
        "--live-state-updates",
        type=Path,
        default=None,
        help="Optional existing persisted live-state update JSON to read.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path for the persisted operator-action JSON proof.",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Optional workspace root when generating upstream state and action replays.",
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
        live_state_updates_path=args.live_state_updates,
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
