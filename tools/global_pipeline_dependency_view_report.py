#!/usr/bin/env python3
"""Emit dependency-view evidence for AGILAB global pipeline operator state."""

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

from agilab.global_pipeline_dependency_view import (
    DEFAULT_RUN_ID,
    PERSISTENCE_FORMAT,
    SCHEMA,
    persist_dependency_view,
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
        "global DAG dependency view report",
        "tools/global_pipeline_dependency_view_report.py --compact",
        "upstream/downstream dependency visualization",
        "queue_baseline -> relay_followup",
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
        "global_pipeline_dependency_view_docs_reference",
        "Global pipeline dependency view docs reference",
        ok,
        (
            "features docs expose the global DAG dependency view evidence command"
            if ok
            else "features docs do not expose the global DAG dependency view evidence command"
        ),
        evidence=[str(DOC_RELATIVE_PATH)],
        details=details,
    )


def _load_failure_report(
    operator_state_path: Path | None,
    dag_path: Path | None,
    exc: Exception,
) -> dict[str, Any]:
    evidence_path = operator_state_path or dag_path or SAMPLE_DAG_RELATIVE_PATH
    check = _check_result(
        "global_pipeline_dependency_view_load",
        "Global pipeline dependency view load",
        False,
        "global pipeline dependency view could not be persisted",
        evidence=[str(evidence_path)],
        details={"error": str(exc)},
    )
    return {
        "report": "Global pipeline dependency view report",
        "status": "fail",
        "scope": (
            "Reads a persisted operator-state JSON proof and projects "
            "cross-app upstream/downstream dependency visualization state."
        ),
        "dag_path": str(dag_path or SAMPLE_DAG_RELATIVE_PATH),
        "summary": {
            "passed": 0,
            "failed": 1,
            "total": 1,
            "issues": [{"level": "error", "location": "load", "message": str(exc)}],
        },
        "dependency_view": {},
        "checks": [check],
    }


def _build_proof(
    *,
    repo_root: Path,
    output_path: Path,
    operator_state_path: Path | None,
    workspace_path: Path | None,
    dag_path: Path | None,
):
    return persist_dependency_view(
        repo_root=repo_root,
        output_path=output_path,
        operator_state_path=operator_state_path,
        workspace_path=workspace_path,
        dag_path=dag_path,
    )


def build_report(
    *,
    repo_root: Path = REPO_ROOT,
    dag_path: Path | None = None,
    operator_state_path: Path | None = None,
    output_path: Path | None = None,
    workspace_path: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    if output_path is None:
        with tempfile.TemporaryDirectory(prefix="agilab-dependency-view-") as tmp_dir:
            root = Path(tmp_dir)
            return _build_report_with_paths(
                repo_root=repo_root,
                dag_path=dag_path,
                operator_state_path=operator_state_path,
                output_path=root / "global_pipeline_dependency_view.json",
                workspace_path=workspace_path or (root / "workspace"),
            )
    return _build_report_with_paths(
        repo_root=repo_root,
        dag_path=dag_path,
        operator_state_path=operator_state_path,
        output_path=output_path,
        workspace_path=workspace_path
        or (output_path.parent / "global_pipeline_dependency_view_workspace"),
    )


def _build_report_with_paths(
    *,
    repo_root: Path,
    dag_path: Path | None,
    operator_state_path: Path | None,
    output_path: Path,
    workspace_path: Path | None,
) -> dict[str, Any]:
    try:
        proof = _build_proof(
            repo_root=repo_root,
            output_path=output_path,
            operator_state_path=operator_state_path,
            workspace_path=workspace_path,
            dag_path=dag_path,
        )
    except Exception as exc:
        return _load_failure_report(operator_state_path, dag_path, exc)

    proof_details = proof.as_dict()
    view = proof.dependency_view
    summary = view.get("summary", {})
    source = view.get("source", {})
    nodes = view.get("nodes", [])
    edges = view.get("edges", [])
    adjacency = view.get("adjacency", {})
    upstream = adjacency.get("upstream_by_unit", {}) if isinstance(adjacency, dict) else {}
    downstream = (
        adjacency.get("downstream_by_unit", {}) if isinstance(adjacency, dict) else {}
    )
    node_by_id = {
        node.get("id"): node
        for node in nodes
        if isinstance(node, dict)
    }
    queue_node = node_by_id.get("queue_baseline", {})
    relay_node = node_by_id.get("relay_followup", {})
    queue_to_relay_edges = [
        edge
        for edge in edges
        if isinstance(edge, dict)
        and edge.get("from") == "queue_baseline"
        and edge.get("to") == "relay_followup"
        and edge.get("artifact") == "queue_metrics"
    ]
    artifact_flow = view.get("artifact_flow", [])

    checks = [
        _check_result(
            "global_pipeline_dependency_view_schema",
            "Global pipeline dependency view schema",
            proof.ok
            and view.get("schema") == SCHEMA
            and view.get("persistence_format") == PERSISTENCE_FORMAT
            and view.get("run_id") == DEFAULT_RUN_ID
            and source.get("operator_state_schema")
            == "agilab.global_pipeline_operator_state.v1",
            "dependency view uses the supported schema and reads operator-state JSON"
            if proof.ok
            else "dependency view schema or operator-state source is invalid",
            evidence=[
                "src/agilab/global_pipeline_dependency_view.py",
                proof.operator_state_path,
            ],
            details={
                "schema": view.get("schema"),
                "expected_schema": SCHEMA,
                "persistence_format": view.get("persistence_format"),
                "run_id": view.get("run_id"),
                "source": source,
                "issues": [issue.as_dict() for issue in proof.issues],
            },
        ),
        _check_result(
            "global_pipeline_dependency_view_nodes",
            "Global pipeline dependency view nodes",
            summary.get("node_count") == 2
            and queue_node.get("downstream_unit_ids") == ["relay_followup"]
            and queue_node.get("upstream_unit_ids") == []
            and relay_node.get("upstream_unit_ids") == ["queue_baseline"]
            and relay_node.get("downstream_unit_ids") == [],
            "dependency view exposes upstream/downstream unit adjacency",
            evidence=["tools/global_pipeline_operator_state_report.py"],
            details={
                "node_count": summary.get("node_count"),
                "queue_node": queue_node,
                "relay_node": relay_node,
                "upstream_by_unit": upstream,
                "downstream_by_unit": downstream,
            },
        ),
        _check_result(
            "global_pipeline_dependency_view_cross_app_edge",
            "Global pipeline dependency view cross-app edge",
            summary.get("edge_count") == 1
            and summary.get("cross_app_edge_count") == 1
            and any(
                edge.get("status") == "available"
                and edge.get("cross_app") is True
                and edge.get("producer_app") == "uav_queue_project"
                and edge.get("consumer_app") == "uav_relay_queue_project"
                for edge in queue_to_relay_edges
            ),
            "dependency view renders queue_baseline -> relay_followup as a cross-app artifact edge",
            evidence=["docs/source/data/multi_app_dag_sample.json"],
            details={"edges": edges},
        ),
        _check_result(
            "global_pipeline_dependency_view_artifact_flow",
            "Global pipeline dependency view artifact flow",
            any(
                flow.get("artifact") == "queue_metrics"
                and flow.get("producer_unit_id") == "queue_baseline"
                and flow.get("consumer_unit_ids") == ["relay_followup"]
                and flow.get("status") == "available"
                for flow in artifact_flow
                if isinstance(flow, dict)
            ),
            "dependency view maps queue_metrics from producer to consumer",
            evidence=["tools/global_pipeline_app_dispatch_smoke_report.py"],
            details={"artifact_flow": artifact_flow},
        ),
        _check_result(
            "global_pipeline_dependency_view_operator_linkage",
            "Global pipeline dependency view operator linkage",
            source.get("operator_state_run_status") == "ready_for_operator_review"
            and source.get("source_real_execution_scope") == "full_dag_smoke"
            and summary.get("available_artifact_ids", [])[:1] == ["queue_metrics"],
            "dependency view keeps linkage to the persisted full-DAG operator state",
            evidence=["tools/global_pipeline_operator_state_report.py"],
            details={
                "source": source,
                "available_artifact_ids": summary.get("available_artifact_ids"),
            },
        ),
        _check_result(
            "global_pipeline_dependency_view_persistence",
            "Global pipeline dependency view JSON round trip",
            proof.round_trip_ok and Path(proof.path).is_file(),
            "dependency view is unchanged after JSON write/read",
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
        "report": "Global pipeline dependency view report",
        "status": "pass" if failed == 0 else "fail",
        "scope": (
            "Reads a persisted operator-state JSON proof and projects "
            "upstream/downstream cross-app dependency visualization state. "
            "It is a state contract, not a live UI component."
        ),
        "dag_path": str(dag_path or SAMPLE_DAG_RELATIVE_PATH),
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "schema": view.get("schema"),
            "run_id": view.get("run_id"),
            "run_status": view.get("run_status"),
            "persistence_format": view.get("persistence_format"),
            "round_trip_ok": proof.round_trip_ok,
            "path": proof.path,
            "operator_state_path": proof.operator_state_path,
            "node_count": proof.node_count,
            "edge_count": proof.edge_count,
            "cross_app_edge_count": proof.cross_app_edge_count,
            "artifact_flow_count": summary.get("artifact_flow_count"),
            "upstream_dependency_count": summary.get("upstream_dependency_count"),
            "downstream_dependency_count": summary.get("downstream_dependency_count"),
            "visible_unit_ids": list(proof.visible_unit_ids),
            "available_artifact_ids": summary.get("available_artifact_ids"),
            "source_real_execution_scope": summary.get("source_real_execution_scope"),
            "issues": [issue.as_dict() for issue in proof.issues],
        },
        "dependency_view": proof_details,
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit dependency-view evidence for AGILAB global pipeline runs."
    )
    parser.add_argument(
        "--dag",
        type=Path,
        default=None,
        help=f"Path to a DAG JSON contract. Defaults to {SAMPLE_DAG_RELATIVE_PATH}.",
    )
    parser.add_argument(
        "--operator-state",
        type=Path,
        default=None,
        help="Optional existing persisted full-DAG operator-state JSON to read.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path for the persisted dependency-view JSON proof.",
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
        operator_state_path=args.operator_state,
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
