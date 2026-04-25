#!/usr/bin/env python3
"""Emit read-only evidence for AGILAB's global pipeline DAG shape."""

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

from agilab.global_pipeline_dag import SCHEMA, build_global_pipeline_dag


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
        "global pipeline DAG report",
        "tools/global_pipeline_dag_report.py --compact",
        "pipeline_view.dot",
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
        "global_pipeline_dag_docs_reference",
        "Global pipeline DAG docs reference",
        ok,
        (
            "features docs expose the global pipeline DAG evidence command"
            if ok
            else "features docs do not expose the global pipeline DAG evidence command"
        ),
        evidence=[str(DOC_RELATIVE_PATH)],
        details=details,
    )


def build_report(
    *,
    repo_root: Path = REPO_ROOT,
    dag_path: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    try:
        graph = build_global_pipeline_dag(repo_root=repo_root, dag_path=dag_path)
    except Exception as exc:
        check = _check_result(
            "global_pipeline_dag_load",
            "Global pipeline DAG load",
            False,
            "global pipeline DAG could not be assembled",
            evidence=[str(dag_path or SAMPLE_DAG_RELATIVE_PATH)],
            details={"error": str(exc)},
        )
        return {
            "report": "Global pipeline DAG report",
            "status": "fail",
            "scope": (
                "Assembles a read-only product-level DAG from the multi-app DAG "
                "contract and app-local pipeline_view.dot metadata. It does not run "
                "apps, schedule retries, or provide operator UI state yet."
            ),
            "dag_path": str(dag_path or SAMPLE_DAG_RELATIVE_PATH),
            "summary": {
                "passed": 0,
                "failed": 1,
                "total": 1,
                "issues": [{"level": "error", "location": "load", "message": str(exc)}],
            },
            "graph": {},
            "checks": [check],
        }
    graph_details = graph.as_dict()
    app_views = graph_details["app_pipeline_views"]
    handoff_edges = [
        edge for edge in graph_details["edges"] if edge.get("kind") == "artifact_handoff"
    ]

    checks = [
        _check_result(
            "global_pipeline_dag_source_contract",
            "Global pipeline DAG source contract",
            graph.ok and graph.schema == SCHEMA and graph.app_node_count >= 2,
            "global DAG uses the supported schema and multi-app source contract"
            if graph.ok
            else "global DAG source contract is invalid",
            evidence=[graph.dag_path, "src/agilab/global_pipeline_dag.py"],
            details={
                "schema": graph.schema,
                "expected_schema": SCHEMA,
                "runner_status": graph.runner_status,
                "issues": [issue.as_dict() for issue in graph.issues],
            },
        ),
        _check_result(
            "global_pipeline_dag_app_views",
            "Global pipeline DAG app-local views",
            graph.app_node_count > 0
            and len(app_views) == graph.app_node_count
            and all(view["local_node_count"] > 0 and view["local_edge_count"] > 0 for view in app_views),
            "global DAG includes app-local pipeline_view.dot expansions",
            evidence=["src/agilab/apps/builtin/*/pipeline_view.dot"],
            details={"app_pipeline_views": app_views},
        ),
        _check_result(
            "global_pipeline_dag_graph_shape",
            "Global pipeline DAG graph shape",
            graph.app_node_count == 2
            and graph.app_step_node_count == 8
            and graph.local_pipeline_edge_count == 6
            and graph.cross_app_edge_count == 1
            and list(graph.execution_order) == ["queue_baseline", "relay_followup"],
            "global DAG assembles app nodes, app-local steps, and one cross-app handoff",
            evidence=[graph.dag_path, "src/agilab/apps/builtin"],
            details={
                "app_node_count": graph.app_node_count,
                "app_step_node_count": graph.app_step_node_count,
                "local_pipeline_edge_count": graph.local_pipeline_edge_count,
                "cross_app_edge_count": graph.cross_app_edge_count,
                "execution_order": list(graph.execution_order),
            },
        ),
        _check_result(
            "global_pipeline_dag_artifact_edge",
            "Global pipeline DAG artifact edge",
            len(handoff_edges) == 1 and handoff_edges[0].get("artifact") == "queue_metrics",
            "global DAG preserves the queue_metrics artifact handoff edge",
            evidence=[graph.dag_path],
            details={"artifact_handoff_edges": handoff_edges},
        ),
        _docs_check(repo_root),
    ]

    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "report": "Global pipeline DAG report",
        "status": "pass" if failed == 0 else "fail",
        "scope": (
            "Assembles a read-only product-level DAG from the multi-app DAG "
            "contract and app-local pipeline_view.dot metadata. It does not run "
            "apps, schedule retries, or provide operator UI state yet."
        ),
        "dag_path": graph.dag_path,
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "schema": graph.schema,
            "runner_status": graph.runner_status,
            "app_node_count": graph.app_node_count,
            "app_step_node_count": graph.app_step_node_count,
            "local_pipeline_edge_count": graph.local_pipeline_edge_count,
            "cross_app_edge_count": graph.cross_app_edge_count,
            "global_node_count": len(graph.nodes),
            "global_edge_count": len(graph.edges),
            "execution_order": list(graph.execution_order),
            "issues": [issue.as_dict() for issue in graph.issues],
        },
        "graph": graph_details,
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit read-only evidence for AGILAB's global pipeline DAG shape."
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
