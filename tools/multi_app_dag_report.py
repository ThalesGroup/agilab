#!/usr/bin/env python3
"""Emit machine-readable evidence for AGILAB's multi-app DAG contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DAG_RELATIVE_PATH = Path("docs/source/data/multi_app_dag_sample.json")
SUPPLEMENTAL_DAG_RELATIVE_PATHS = (
    Path("docs/source/data/multi_app_dag_portfolio_sample.json"),
)
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

from agilab.multi_app_dag import SCHEMA, load_multi_app_dag, validate_multi_app_dag


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


def _relative(path: Path, repo_root: Path) -> str:
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)


def _load_payload(dag_path: Path) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    try:
        payload = load_multi_app_dag(dag_path)
        return payload, {}
    except Exception as exc:
        return None, {"error": str(exc)}


def _docs_check(repo_root: Path) -> dict[str, Any]:
    doc_path = repo_root / DOC_RELATIVE_PATH
    required = [
        "multi-app DAG contract",
        "tools/multi_app_dag_report.py --compact",
        "multi_app_dag_sample.json",
        "multi_app_dag_portfolio_sample.json",
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
        "multi_app_dag_docs_reference",
        "Multi-app DAG docs reference",
        ok,
        (
            "features docs expose the multi-app DAG evidence command and sample"
            if ok
            else "features docs do not expose the multi-app DAG evidence command"
        ),
        evidence=[str(DOC_RELATIVE_PATH)],
        details=details,
    )


def _apps_for_payload(payload: Mapping[str, Any]) -> set[str]:
    nodes = payload.get("nodes", [])
    if not isinstance(nodes, list):
        return set()
    return {
        str(node.get("app", "")).strip()
        for node in nodes
        if isinstance(node, dict) and str(node.get("app", "")).strip()
    }


def _sample_result(
    *,
    repo_root: Path,
    sample_path: Path,
) -> dict[str, Any]:
    payload, load_details = _load_payload(sample_path)
    if payload is None:
        return {
            "dag_path": _relative(sample_path, repo_root),
            "status": "fail",
            "load_details": load_details,
        }
    validation = validate_multi_app_dag(payload, repo_root=repo_root)
    return {
        "dag_path": _relative(sample_path, repo_root),
        "dag_id": payload.get("dag_id", ""),
        "status": "pass" if validation.ok else "fail",
        "apps": sorted(_apps_for_payload(payload)),
        "summary": validation.as_dict(),
    }


def _sample_suite_check(
    *,
    repo_root: Path,
    primary_payload: Mapping[str, Any] | None,
    primary_validation: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    supplemental = [
        _sample_result(repo_root=repo_root, sample_path=repo_root / sample_path)
        for sample_path in SUPPLEMENTAL_DAG_RELATIVE_PATHS
    ]
    primary_apps = _apps_for_payload(primary_payload or {})
    suite_apps = set(primary_apps)
    suite_node_count = int(primary_validation.get("node_count", 0) or 0)
    suite_edge_count = int(primary_validation.get("edge_count", 0) or 0)
    suite_cross_app_edge_count = int(
        primary_validation.get("cross_app_edge_count", 0) or 0
    )
    for result in supplemental:
        suite_apps.update(result.get("apps", []))
        summary = result.get("summary", {})
        if isinstance(summary, dict):
            suite_node_count += int(summary.get("node_count", 0) or 0)
            suite_edge_count += int(summary.get("edge_count", 0) or 0)
            suite_cross_app_edge_count += int(
                summary.get("cross_app_edge_count", 0) or 0
            )

    suite_summary = {
        "sample_count": 1 + len(supplemental),
        "supplemental_sample_count": len(supplemental),
        "validated_dag_paths": [
            str(SAMPLE_DAG_RELATIVE_PATH),
            *[str(path) for path in SUPPLEMENTAL_DAG_RELATIVE_PATHS],
        ],
        "supplemental_dag_paths": [
            str(path) for path in SUPPLEMENTAL_DAG_RELATIVE_PATHS
        ],
        "suite_app_count": len(suite_apps),
        "suite_apps": sorted(suite_apps),
        "suite_node_count": suite_node_count,
        "suite_edge_count": suite_edge_count,
        "suite_cross_app_edge_count": suite_cross_app_edge_count,
        "supplemental_results": supplemental,
    }
    ok = (
        primary_validation.get("ok") is True
        and len(supplemental) == 1
        and all(result.get("status") == "pass" for result in supplemental)
        and suite_summary["sample_count"] == 2
        and suite_summary["suite_app_count"] >= 6
        and suite_summary["suite_cross_app_edge_count"] >= 4
        and any(
            result.get("dag_id") == "flight-weather-execution-portfolio"
            for result in supplemental
        )
    )
    return (
        _check_result(
            "multi_app_dag_sample_suite",
            "Multi-app DAG sample suite",
            ok,
            (
                "multi-app DAG report validates the default executable sample "
                "and supplemental portfolio sample"
                if ok
                else "multi-app DAG sample suite is incomplete or failing"
            ),
            evidence=suite_summary["validated_dag_paths"],
            details=suite_summary,
        ),
        suite_summary,
    )


def build_report(
    *,
    repo_root: Path = REPO_ROOT,
    dag_path: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    dag_path = (dag_path or (repo_root / SAMPLE_DAG_RELATIVE_PATH)).expanduser()
    if not dag_path.is_absolute():
        dag_path = repo_root / dag_path
    payload, load_details = _load_payload(dag_path)

    checks: list[dict[str, Any]] = []
    validation_details: dict[str, Any] = {}
    suite_summary: dict[str, Any] = {}
    if payload is None:
        checks.append(
            _check_result(
                "multi_app_dag_load",
                "Multi-app DAG load",
                False,
                "multi-app DAG sample could not be loaded",
                evidence=[_relative(dag_path, repo_root)],
                details=load_details,
            )
        )
    else:
        validation = validate_multi_app_dag(payload, repo_root=repo_root)
        validation_details = validation.as_dict()
        checks.extend(
            [
                _check_result(
                    "multi_app_dag_schema",
                    "Multi-app DAG schema",
                    payload.get("schema") == SCHEMA and validation.node_count > 0,
                    "multi-app DAG uses the supported schema"
                    if payload.get("schema") == SCHEMA
                    else "multi-app DAG schema is unsupported",
                    evidence=[_relative(dag_path, repo_root), "src/agilab/multi_app_dag.py"],
                    details={
                        "schema": payload.get("schema"),
                        "expected_schema": SCHEMA,
                        "dag_id": payload.get("dag_id"),
                        "node_count": validation.node_count,
                    },
                ),
                _check_result(
                    "multi_app_dag_app_nodes",
                    "Multi-app DAG app nodes",
                    validation.app_count >= 2 and not [
                        issue.as_dict()
                        for issue in validation.issues
                        if issue.location.startswith("nodes")
                    ],
                    "DAG references multiple checked-in built-in apps",
                    evidence=["src/agilab/apps/builtin", _relative(dag_path, repo_root)],
                    details={
                        "app_count": validation.app_count,
                        "node_count": validation.node_count,
                        "issues": [
                            issue.as_dict()
                            for issue in validation.issues
                            if issue.location.startswith("nodes")
                        ],
                    },
                ),
                _check_result(
                    "multi_app_dag_dependencies",
                    "Multi-app DAG dependencies",
                    bool(validation.execution_order)
                    and len(validation.execution_order) == validation.node_count
                    and not [
                        issue.as_dict()
                        for issue in validation.issues
                        if issue.location.startswith("edges")
                    ],
                    "DAG dependency order is acyclic and resolves all nodes",
                    evidence=[_relative(dag_path, repo_root)],
                    details={
                        "execution_order": list(validation.execution_order),
                        "edge_count": validation.edge_count,
                        "issues": [
                            issue.as_dict()
                            for issue in validation.issues
                            if issue.location.startswith("edges")
                        ],
                    },
                ),
                _check_result(
                    "multi_app_dag_artifact_handoffs",
                    "Multi-app DAG artifact handoffs",
                    validation.cross_app_edge_count > 0
                    and bool(validation.artifact_handoffs)
                    and validation.ok,
                    "DAG declares cross-app artifact handoffs",
                    evidence=[_relative(dag_path, repo_root)],
                    details={
                        "cross_app_edge_count": validation.cross_app_edge_count,
                        "artifact_handoffs": list(validation.artifact_handoffs),
                        "issues": [issue.as_dict() for issue in validation.issues],
                    },
                ),
            ]
        )
        if dag_path == repo_root / SAMPLE_DAG_RELATIVE_PATH:
            suite_check, suite_summary = _sample_suite_check(
                repo_root=repo_root,
                primary_payload=payload,
                primary_validation=validation_details,
            )
            checks.append(suite_check)

    checks.append(_docs_check(repo_root))
    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "report": "Multi-app DAG report",
        "status": "pass" if failed == 0 else "fail",
        "scope": (
            "Validates the checked-in multi-app DAG contract, built-in app nodes, "
            "acyclic dependencies, and artifact handoffs. It does not execute the "
            "apps yet."
        ),
        "dag_path": _relative(dag_path, repo_root),
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            **validation_details,
            **suite_summary,
        },
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit machine-readable evidence for AGILAB's multi-app DAG contract."
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
