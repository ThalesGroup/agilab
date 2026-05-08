#!/usr/bin/env python3
"""Emit AGILAB notebook union-environment evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
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

from agilab.notebook_union_environment import (
    SCHEMA,
    build_union_environment_plan,
    build_union_notebook,
    write_union_environment_plan,
    write_union_notebook,
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


def compatible_lab_stages() -> dict[str, list[dict[str, Any]]]:
    return {
        "notebook_union_project": [
            {
                "D": "Prepare union notebook inputs",
                "Q": "Create a small in-kernel dataframe.",
                "M": "",
                "C": "import pandas as pd\ndf = pd.DataFrame({'x': [1, 2]})\n",
                "R": "runpy",
                "E": "",
            },
            {
                "D": "Summarize union notebook inputs",
                "Q": "Summarize the dataframe in the same kernel.",
                "M": "",
                "C": "summary = {'rows': len(df)}\nprint(summary)\n",
                "R": "runpy",
                "E": "",
            },
        ]
    }


def incompatible_lab_stages() -> dict[str, list[dict[str, Any]]]:
    return {
        "notebook_union_project": [
            {
                "D": "Run local stage",
                "Q": "",
                "M": "",
                "C": "print('local')\n",
                "R": "runpy",
                "E": "/env/a",
            },
            {
                "D": "Run isolated stage",
                "Q": "",
                "M": "",
                "C": "print('isolated')\n",
                "R": "agi.run",
                "E": "/env/b",
            },
        ]
    }


def _docs_check(repo_root: Path) -> dict[str, Any]:
    required = [
        "notebook union-environment report",
        "tools/notebook_union_environment_report.py --compact",
        "single-kernel union notebook",
        "supervisor_notebook_required",
    ]
    doc_path = repo_root / DOC_RELATIVE_PATH
    try:
        text = doc_path.read_text(encoding="utf-8")
        missing = [needle for needle in required if needle not in text]
        ok = not missing
        details = {"missing": missing}
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "notebook_union_environment_docs_reference",
        "Notebook union environment docs reference",
        ok,
        (
            "features docs expose the notebook union-environment command"
            if ok
            else "features docs do not expose the notebook union-environment command"
        ),
        evidence=[str(DOC_RELATIVE_PATH)],
        details=details,
    )


def build_report(
    *,
    repo_root: Path = REPO_ROOT,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    if output_dir is None:
        with tempfile.TemporaryDirectory(prefix="agilab-notebook-union-") as tmp_dir:
            return _build_report_with_dir(repo_root=repo_root, output_dir=Path(tmp_dir))
    return _build_report_with_dir(repo_root=repo_root, output_dir=output_dir)


def _build_report_with_dir(*, repo_root: Path, output_dir: Path) -> dict[str, Any]:
    output_dir = output_dir.expanduser()
    compatible_plan = build_union_environment_plan(compatible_lab_stages())
    incompatible_plan = build_union_environment_plan(incompatible_lab_stages())
    compatible_plan_path = write_union_environment_plan(
        output_dir / "compatible_union_plan.json",
        compatible_plan,
    )
    incompatible_plan_path = write_union_environment_plan(
        output_dir / "incompatible_union_plan.json",
        incompatible_plan,
    )
    notebook = build_union_notebook(compatible_plan)
    notebook_path = write_union_notebook(
        output_dir / "compatible_union_notebook.ipynb",
        notebook,
    )
    code_cells = [
        cell
        for cell in notebook.get("cells", [])
        if isinstance(cell, dict) and cell.get("cell_type") == "code"
    ]

    checks = [
        _check_result(
            "notebook_union_environment_compatible_plan",
            "Notebook union environment compatible plan",
            compatible_plan.get("schema") == SCHEMA
            and compatible_plan.get("run_status") == "union_candidate"
            and compatible_plan.get("union_mode") == "single_kernel_union_candidate"
            and compatible_plan.get("execution_mode") == "not_executed_union_plan"
            and compatible_plan.get("summary", {}).get("stage_count") == 2
            and compatible_plan.get("summary", {}).get("compatible") is True,
            "compatible runpy/current-kernel stages can produce a union notebook candidate",
            evidence=[str(compatible_plan_path)],
            details=compatible_plan,
        ),
        _check_result(
            "notebook_union_environment_notebook_render",
            "Notebook union environment notebook render",
            Path(notebook_path).is_file()
            and len(code_cells) == 2
            and notebook.get("metadata", {}).get("agilab", {}).get("union_mode")
            == "single_kernel_union_candidate",
            "compatible plan renders a non-executed single-kernel union notebook",
            evidence=[str(notebook_path)],
            details={
                "notebook_path": str(notebook_path),
                "code_cell_count": len(code_cells),
                "metadata": notebook.get("metadata", {}).get("agilab", {}),
            },
        ),
        _check_result(
            "notebook_union_environment_mixed_runtime_guard",
            "Notebook union environment mixed runtime guard",
            incompatible_plan.get("run_status") == "supervisor_required"
            and incompatible_plan.get("union_mode") == "supervisor_notebook_required"
            and incompatible_plan.get("summary", {}).get("compatible") is False
            and incompatible_plan.get("summary", {}).get("issue_count") >= 2,
            "mixed runtime or mixed environment stages stay on supervisor export",
            evidence=[str(incompatible_plan_path)],
            details=incompatible_plan,
        ),
        _check_result(
            "notebook_union_environment_execution_boundary",
            "Notebook union environment execution boundary",
            compatible_plan.get("provenance", {}).get("executes_notebook") is False
            and incompatible_plan.get("provenance", {}).get("executes_notebook") is False
            and compatible_plan.get("provenance", {}).get(
                "supervisor_fallback_for_mixed_runtime"
            )
            is True,
            "union planning never executes cells and keeps supervisor fallback explicit",
            evidence=["src/agilab/notebook_union_environment.py"],
            details={
                "compatible_provenance": compatible_plan.get("provenance", {}),
                "incompatible_provenance": incompatible_plan.get("provenance", {}),
            },
        ),
        _docs_check(repo_root),
    ]

    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "report": "Notebook union-environment report",
        "status": "pass" if failed == 0 else "fail",
        "scope": (
            "Plans a single-kernel union notebook only for compatible runpy "
            "stages and requires supervisor export for mixed runtimes or "
            "environments. It does not execute notebook cells."
        ),
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "compatible_union_mode": compatible_plan.get("union_mode"),
            "incompatible_union_mode": incompatible_plan.get("union_mode"),
            "compatible_stage_count": compatible_plan.get("summary", {}).get("stage_count"),
            "incompatible_issue_count": incompatible_plan.get("summary", {}).get("issue_count"),
            "notebook_path": str(notebook_path),
            "code_cell_count": len(code_cells),
        },
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit AGILAB notebook union-environment evidence."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional directory for generated union-environment artifacts.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact JSON without indentation.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    report = build_report(output_dir=args.output_dir)
    if args.compact:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
