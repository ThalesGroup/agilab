#!/usr/bin/env python3
"""Emit a generic AGILAB notebook import preflight report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]


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

from agilab.notebook_pipeline_import import (  # noqa: E402
    DEFAULT_NOTEBOOK_RELATIVE_PATH,
    build_lab_stages_preview,
    build_notebook_import_contract,
    build_notebook_import_preflight,
    build_notebook_import_pipeline_view,
    build_notebook_import_view_plan,
    build_notebook_pipeline_import,
    load_notebook_import_view_manifest,
    load_notebook,
    write_notebook_import_contract,
    write_notebook_import_pipeline_view,
    write_notebook_import_view_plan,
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


def _failure_report(notebook_path: Path, exc: Exception) -> dict[str, Any]:
    return {
        "report": "Notebook import preflight report",
        "status": "fail",
        "scope": (
            "Reads a notebook without executing cells, previews AGILAB pipeline "
            "metadata, and flags generic migration risks."
        ),
        "notebook_path": str(notebook_path),
        "summary": {
            "passed": 0,
            "failed": 1,
            "total": 1,
            "risk_status": "blocked",
            "safe_to_import": False,
            "issues": [{"level": "error", "location": "load", "message": str(exc)}],
        },
        "checks": [
            _check_result(
                "notebook_import_preflight_load",
                "Notebook import preflight load",
                False,
                "notebook could not be loaded for preflight",
                evidence=[str(notebook_path)],
                details={"error": str(exc)},
            )
        ],
    }


def build_report(
    *,
    repo_root: Path = REPO_ROOT,
    notebook_path: Path | None = None,
    output_path: Path | None = None,
    pipeline_view_output_path: Path | None = None,
    view_manifest_path: Path | None = None,
    view_plan_output_path: Path | None = None,
    module_name: str = "notebook_import_project",
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    resolved_notebook = notebook_path or repo_root / DEFAULT_NOTEBOOK_RELATIVE_PATH
    if not resolved_notebook.is_absolute():
        resolved_notebook = repo_root / resolved_notebook
    if output_path is not None and pipeline_view_output_path is None:
        pipeline_view_output_path = output_path.with_name("notebook_import_pipeline_view.json")
    if output_path is not None and view_plan_output_path is None:
        view_plan_output_path = output_path.with_name("notebook_import_view_plan.json")

    try:
        notebook = load_notebook(resolved_notebook)
        notebook_import = build_notebook_pipeline_import(
            notebook=notebook,
            source_notebook=resolved_notebook,
        )
        preflight = build_notebook_import_preflight(notebook_import)
        lab_stages_preview = build_lab_stages_preview(notebook_import, module_name=module_name)
        contract = build_notebook_import_contract(
            notebook_import,
            preflight=preflight,
            module_name=module_name,
        )
        pipeline_view = build_notebook_import_pipeline_view(
            notebook_import,
            preflight=preflight,
            module_name=module_name,
        )
        view_manifest = (
            load_notebook_import_view_manifest(view_manifest_path)
            if view_manifest_path
            else None
        )
        view_plan = build_notebook_import_view_plan(
            notebook_import,
            preflight=preflight,
            module_name=module_name,
            manifest=view_manifest,
            manifest_path=view_manifest_path,
        )
        written_contract = (
            write_notebook_import_contract(
                output_path,
                notebook_import,
                preflight=preflight,
                module_name=module_name,
            )
            if output_path
            else None
        )
        written_pipeline_view = (
            write_notebook_import_pipeline_view(
                pipeline_view_output_path,
                notebook_import,
                preflight=preflight,
                module_name=module_name,
            )
            if pipeline_view_output_path
            else None
        )
        written_view_plan = (
            write_notebook_import_view_plan(
                view_plan_output_path,
                notebook_import,
                preflight=preflight,
                module_name=module_name,
                manifest=view_manifest,
                manifest_path=view_manifest_path,
            )
            if view_plan_output_path
            else None
        )
    except Exception as exc:
        return _failure_report(resolved_notebook, exc)

    summary = preflight.get("summary", {})
    risk_counts = preflight.get("risk_counts", {})
    artifact_contract = preflight.get("artifact_contract", {})
    checks = [
        _check_result(
            "notebook_import_preflight_importable",
            "Notebook importable",
            bool(preflight.get("safe_to_import")),
            "notebook produces at least one importable pipeline stage",
            evidence=[str(resolved_notebook)],
            details={
                "pipeline_stage_count": summary.get("pipeline_stage_count"),
                "safe_to_import": preflight.get("safe_to_import"),
            },
        ),
        _check_result(
            "notebook_import_preflight_risks",
            "Notebook generic risk scan",
            int(risk_counts.get("error", 0) or 0) == 0,
            "preflight found no blocking generic migration risks",
            evidence=["src/agilab/notebook_pipeline_import.py"],
            details={
                "risk_status": preflight.get("status"),
                "risk_counts": risk_counts,
                "risks": preflight.get("risks", []),
            },
        ),
        _check_result(
            "notebook_import_preflight_artifacts",
            "Notebook artifact contract",
            (
                int(summary.get("artifact_reference_count", 0) or 0) == 0
                or bool(artifact_contract.get("inputs") or artifact_contract.get("outputs") or artifact_contract.get("unknown"))
            ),
            "preflight records artifact references without app-specific semantics",
            evidence=[str(resolved_notebook)],
            details=artifact_contract,
        ),
        _check_result(
            "notebook_import_preflight_lab_stages_preview",
            "Notebook lab_stages preview",
            bool(lab_stages_preview.get(module_name)),
            "preflight can project imported cells into lab_stages preview entries",
            evidence=["src/agilab/notebook_pipeline_import.py"],
            details={"module_name": module_name, "stage_count": len(lab_stages_preview.get(module_name, []))},
        ),
        _check_result(
            "notebook_import_preflight_pipeline_view",
            "Notebook import pipeline view",
            bool(pipeline_view.get("nodes")) and any(
                node.get("kind") == "analysis_consumer"
                for node in pipeline_view.get("nodes", [])
                if isinstance(node, dict)
            ),
            "preflight builds an app-neutral notebook import pipeline view",
            evidence=["src/agilab/notebook_pipeline_import.py"],
            details={
                "node_count": pipeline_view.get("summary", {}).get("node_count"),
                "edge_count": pipeline_view.get("summary", {}).get("edge_count"),
                "schema": pipeline_view.get("schema"),
            },
        ),
        _check_result(
            "notebook_import_preflight_view_plan",
            "Notebook import app view plan",
            view_plan.get("schema") == "agilab.notebook_import_view_plan.v1",
            "preflight builds an app-manifest-only view plan without inferring UI from cells",
            evidence=[
                str(view_manifest_path)
                if view_manifest_path
                else "no app-specific manifest provided"
            ],
            details={
                "status": view_plan.get("status"),
                "matching_policy": view_plan.get("matching_policy"),
                "ready_view_count": view_plan.get("summary", {}).get("ready_view_count"),
                "declared_view_count": view_plan.get("summary", {}).get("declared_view_count"),
            },
        ),
    ]
    if output_path:
        checks.append(
            _check_result(
                "notebook_import_preflight_contract_write",
                "Notebook import contract write",
                bool(written_contract and written_contract.is_file()),
                "preflight writes a generic notebook import contract sidecar",
                evidence=[str(output_path)],
                details={"path": str(written_contract) if written_contract else ""},
            )
        )
    if pipeline_view_output_path:
        checks.append(
            _check_result(
                "notebook_import_preflight_pipeline_view_write",
                "Notebook import pipeline view write",
                bool(written_pipeline_view and written_pipeline_view.is_file()),
                "preflight writes a generic notebook import pipeline view sidecar",
                evidence=[str(pipeline_view_output_path)],
                details={"path": str(written_pipeline_view) if written_pipeline_view else ""},
            )
        )
    if view_plan_output_path:
        checks.append(
            _check_result(
                "notebook_import_preflight_view_plan_write",
                "Notebook import view plan write",
                bool(written_view_plan and written_view_plan.is_file()),
                "preflight writes an app-manifest-only notebook import view plan sidecar",
                evidence=[str(view_plan_output_path)],
                details={"path": str(written_view_plan) if written_view_plan else ""},
            )
        )

    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "report": "Notebook import preflight report",
        "status": "pass" if failed == 0 else "fail",
        "scope": (
            "Reads a notebook without executing cells, previews AGILAB pipeline "
            "metadata, writes an app-neutral contract when requested, and flags "
            "generic migration risks."
        ),
        "notebook_path": str(resolved_notebook),
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "risk_status": preflight.get("status"),
            "safe_to_import": preflight.get("safe_to_import"),
            "cleanup_required": preflight.get("cleanup_required"),
            "risk_counts": risk_counts,
            "cell_count": summary.get("cell_count"),
            "code_cell_count": summary.get("code_cell_count"),
            "markdown_cell_count": summary.get("markdown_cell_count"),
            "pipeline_stage_count": summary.get("pipeline_stage_count"),
            "input_count": summary.get("input_count"),
            "output_count": summary.get("output_count"),
            "unknown_artifact_count": summary.get("unknown_artifact_count"),
            "contract_path": str(written_contract) if written_contract else "",
            "pipeline_view_path": str(written_pipeline_view) if written_pipeline_view else "",
            "view_plan_path": str(written_view_plan) if written_view_plan else "",
            "pipeline_view_node_count": pipeline_view.get("summary", {}).get("node_count"),
            "pipeline_view_edge_count": pipeline_view.get("summary", {}).get("edge_count"),
            "view_plan_status": view_plan.get("status"),
            "view_plan_ready_view_count": view_plan.get("summary", {}).get("ready_view_count"),
        },
        "preflight": preflight,
        "contract": contract,
        "pipeline_view": pipeline_view,
        "view_plan": view_plan,
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit a generic AGILAB notebook import preflight report."
    )
    parser.add_argument(
        "--notebook",
        type=Path,
        default=None,
        help=(
            "Notebook to preflight. Defaults to "
            "docs/source/data/notebook_pipeline_import_sample.ipynb."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional JSON contract output path.",
    )
    parser.add_argument(
        "--pipeline-view-output",
        type=Path,
        default=None,
        help="Optional JSON pipeline view output path.",
    )
    parser.add_argument(
        "--view-manifest",
        type=Path,
        default=None,
        help="Optional app-owned TOML manifest declaring notebook-import views.",
    )
    parser.add_argument(
        "--view-plan-output",
        type=Path,
        default=None,
        help="Optional JSON app view plan output path.",
    )
    parser.add_argument(
        "--module-name",
        default="notebook_import_project",
        help="Module key to use in the generated lab_stages preview.",
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
        notebook_path=args.notebook,
        output_path=args.output,
        pipeline_view_output_path=args.pipeline_view_output,
        view_manifest_path=args.view_manifest,
        view_plan_output_path=args.view_plan_output,
        module_name=args.module_name,
    )
    if args.compact:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
