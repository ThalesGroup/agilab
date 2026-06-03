#!/usr/bin/env python3
"""Emit notebook-to-pipeline import evidence for AGILAB."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
import tomllib
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
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

from agilab.notebook_pipeline_import import (
    DEFAULT_NOTEBOOK_RELATIVE_PATH,
    DEFAULT_RUN_ID,
    PERSISTENCE_FORMAT,
    SCHEMA,
    build_lab_stages_preview,
    persist_notebook_pipeline_import,
    write_lab_stages_preview,
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
        "notebook-to-pipeline import report",
        "tools/notebook_pipeline_import_report.py --compact",
        "notebook-to-pipeline import",
        "not_executed_import",
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
        "notebook_pipeline_import_docs_reference",
        "Notebook pipeline import docs reference",
        ok,
        (
            "features docs expose the notebook-to-pipeline import command"
            if ok
            else "features docs do not expose the notebook-to-pipeline import command"
        ),
        evidence=[str(DOC_RELATIVE_PATH)],
        details=details,
    )


def _load_failure_report(notebook_path: Path | None, exc: Exception) -> dict[str, Any]:
    evidence_path = notebook_path or DEFAULT_NOTEBOOK_RELATIVE_PATH
    check = _check_result(
        "notebook_pipeline_import_load",
        "Notebook pipeline import load",
        False,
        "notebook-to-pipeline import could not be persisted",
        evidence=[str(evidence_path)],
        details={"error": str(exc)},
    )
    return {
        "report": "Notebook pipeline import report",
        "status": "fail",
        "scope": (
            "Reads a Jupyter notebook and projects it into AGILAB pipeline-stage "
            "metadata without executing notebook cells."
        ),
        "notebook_path": str(evidence_path),
        "summary": {
            "passed": 0,
            "failed": 1,
            "total": 1,
            "issues": [{"level": "error", "location": "load", "message": str(exc)}],
        },
        "notebook_import": {},
        "checks": [check],
    }


def build_report(
    *,
    repo_root: Path = REPO_ROOT,
    notebook_path: Path | None = None,
    output_path: Path | None = None,
    lab_stages_output_path: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    if output_path is None:
        with tempfile.TemporaryDirectory(prefix="agilab-notebook-import-") as tmp_dir:
            root = Path(tmp_dir)
            return _build_report_with_paths(
                repo_root=repo_root,
                notebook_path=notebook_path,
                output_path=root / "notebook_pipeline_import.json",
                lab_stages_output_path=lab_stages_output_path
                or (root / "lab_stages_preview.toml"),
            )
    return _build_report_with_paths(
        repo_root=repo_root,
        notebook_path=notebook_path,
        output_path=output_path,
        lab_stages_output_path=lab_stages_output_path
        or output_path.with_suffix(".lab_stages.toml"),
    )


def _build_report_with_paths(
    *,
    repo_root: Path,
    notebook_path: Path | None,
    output_path: Path,
    lab_stages_output_path: Path,
) -> dict[str, Any]:
    try:
        proof = persist_notebook_pipeline_import(
            repo_root=repo_root,
            output_path=output_path,
            notebook_path=notebook_path,
        )
    except Exception as exc:
        return _load_failure_report(notebook_path, exc)

    proof_details = proof.as_dict()
    state = proof.notebook_import
    summary = state.get("summary", {})
    provenance = state.get("provenance", {})
    stages = state.get("pipeline_stages", [])
    iterable_stages = stages if isinstance(stages, list) else []
    context_blocks = state.get("context_blocks", [])
    artifact_references = state.get("artifact_references", [])
    env_hints = state.get("env_hints", [])
    lab_stages_preview = build_lab_stages_preview(
        state,
        module_name="notebook_import_project",
    )
    lab_stages_path = write_lab_stages_preview(lab_stages_output_path, lab_stages_preview)
    reloaded_lab_stages = tomllib.loads(lab_stages_path.read_text(encoding="utf-8"))
    preview_stages = reloaded_lab_stages.get("notebook_import_project", [])
    iterable_preview_stages = preview_stages if isinstance(preview_stages, list) else []
    preview_code_cells = [stage.get("C") for stage in iterable_preview_stages]
    source_code_cells = [
        "".join(stage.get("source_lines", []))
        for stage in iterable_stages
    ]

    checks = [
        _check_result(
            "notebook_pipeline_import_schema",
            "Notebook pipeline import schema",
            proof.ok
            and state.get("schema") == SCHEMA
            and state.get("persistence_format") == PERSISTENCE_FORMAT
            and state.get("run_id") == DEFAULT_RUN_ID
            and state.get("run_status") == "imported"
            and state.get("execution_mode") == "not_executed_import",
            "notebook import uses the supported schema and non-executing mode"
            if proof.ok
            else "notebook import schema or execution mode is invalid",
            evidence=["src/agilab/notebook_pipeline_import.py", proof.notebook_path],
            details={
                "schema": state.get("schema"),
                "expected_schema": SCHEMA,
                "persistence_format": state.get("persistence_format"),
                "run_id": state.get("run_id"),
                "run_status": state.get("run_status"),
                "execution_mode": state.get("execution_mode"),
                "issues": [issue.as_dict() for issue in proof.issues],
            },
        ),
        _check_result(
            "notebook_pipeline_import_cells",
            "Notebook pipeline import cells",
            summary.get("cell_count") == 4
            and summary.get("code_cell_count") == 2
            and summary.get("markdown_cell_count") == 2
            and summary.get("pipeline_stage_count") == 2
            and summary.get("context_block_count") == 2,
            "notebook import preserves code cells as stages and markdown as context",
            evidence=[proof.notebook_path],
            details={
                "cell_count": summary.get("cell_count"),
                "code_cell_count": summary.get("code_cell_count"),
                "markdown_cell_count": summary.get("markdown_cell_count"),
                "pipeline_stage_count": summary.get("pipeline_stage_count"),
                "context_block_count": summary.get("context_block_count"),
                "stage_ids": summary.get("stage_ids"),
                "context_ids": summary.get("context_ids"),
            },
        ),
        _check_result(
            "notebook_pipeline_import_metadata",
            "Notebook pipeline import metadata",
            summary.get("env_hint_count", 0) >= 3
            and summary.get("artifact_reference_count", 0) >= 3
            and {"json", "pandas", "pathlib"}.issubset(set(env_hints))
            and {
                "data/flights.csv",
                "artifacts/summary.json",
                "artifacts/trajectory.png",
            }.issubset(
                {
                    str(reference.get("path", ""))
                    for reference in artifact_references
                    if isinstance(reference, dict)
                }
            ),
            "notebook import extracts environment hints and artifact references",
            evidence=["src/agilab/notebook_pipeline_import.py"],
            details={
                "env_hints": env_hints,
                "artifact_references": artifact_references,
                "stage_count": len(iterable_stages),
            },
        ),
        _check_result(
            "notebook_pipeline_import_context_links",
            "Notebook pipeline import context links",
            [stage.get("context_ids") for stage in iterable_stages]
            == [["markdown-1"], ["markdown-3"]]
            and all(stage.get("runnable") is True for stage in iterable_stages)
            and all(
                stage.get("pipeline_mapping", {}).get("code_field") == "C"
                for stage in iterable_stages
            ),
            "notebook import links markdown context to following pipeline stages",
            evidence=["src/agilab/notebook_pipeline_import.py"],
            details={"stages": iterable_stages, "context_blocks": context_blocks},
        ),
        _check_result(
            "notebook_pipeline_import_execution_boundary",
            "Notebook pipeline import execution boundary",
            state.get("execution_mode") == "not_executed_import"
            and provenance.get("executes_notebook") is False
            and provenance.get("preserves_execution_counts") is True
            and summary.get("execution_count_present_count") == 1,
            "notebook import records execution metadata without running notebook cells",
            evidence=[proof.notebook_path],
            details={"provenance": provenance, "summary": summary},
        ),
        _check_result(
            "notebook_pipeline_import_lab_stages_preview",
            "Notebook pipeline import lab_stages preview",
            Path(lab_stages_path).is_file()
            and lab_stages_preview == reloaded_lab_stages
            and len(iterable_preview_stages) == 2
            and preview_code_cells == source_code_cells
            and [stage.get("NB_CELL_ID") for stage in iterable_preview_stages]
            == ["cell-2", "cell-4"]
            and iterable_preview_stages[0].get("NB_CONTEXT_IDS") == ["markdown-1"]
            and iterable_preview_stages[1].get("NB_ARTIFACT_REFERENCES")
            == ["artifacts/summary.json", "artifacts/trajectory.png"],
            "notebook import writes a richer lab_stages.toml preview",
            evidence=[str(lab_stages_path)],
            details={
                "lab_stages_path": str(lab_stages_path),
                "lab_stages_preview": reloaded_lab_stages,
            },
        ),
        _check_result(
            "notebook_pipeline_import_persistence",
            "Notebook pipeline import JSON round trip",
            proof.round_trip_ok and Path(proof.path).is_file(),
            "notebook import model is unchanged after JSON write/read",
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
        "report": "Notebook pipeline import report",
        "status": "pass" if failed == 0 else "fail",
        "scope": (
            "Reads a Jupyter notebook and projects markdown, code, import hints, "
            "execution-count metadata, and artifact references into AGILAB "
            "pipeline-stage metadata. It does not execute notebook cells."
        ),
        "notebook_path": proof.notebook_path,
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "schema": state.get("schema"),
            "run_id": state.get("run_id"),
            "run_status": state.get("run_status"),
            "execution_mode": state.get("execution_mode"),
            "persistence_format": state.get("persistence_format"),
            "round_trip_ok": proof.round_trip_ok,
            "path": proof.path,
            "notebook_path": proof.notebook_path,
            "cell_count": summary.get("cell_count"),
            "code_cell_count": summary.get("code_cell_count"),
            "markdown_cell_count": summary.get("markdown_cell_count"),
            "pipeline_stage_count": summary.get("pipeline_stage_count"),
            "context_block_count": summary.get("context_block_count"),
            "env_hint_count": summary.get("env_hint_count"),
            "artifact_reference_count": summary.get("artifact_reference_count"),
            "execution_count_present_count": summary.get("execution_count_present_count"),
            "lab_stages_preview_path": str(lab_stages_path),
            "lab_stages_preview_stage_count": len(iterable_preview_stages),
            "stage_ids": summary.get("stage_ids"),
            "context_ids": summary.get("context_ids"),
            "issues": [issue.as_dict() for issue in proof.issues],
        },
        "proof": proof_details,
        "notebook_import": state,
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit AGILAB notebook-to-pipeline import evidence."
    )
    parser.add_argument(
        "--notebook",
        type=Path,
        default=None,
        help=(
            "Notebook to import. Defaults to "
            "docs/source/data/notebook_pipeline_import_sample.ipynb."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional JSON evidence output path.",
    )
    parser.add_argument(
        "--lab-stages-output",
        type=Path,
        default=None,
        help="Optional lab_stages.toml preview output path.",
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
        lab_stages_output_path=args.lab_stages_output,
    )
    if args.compact:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
