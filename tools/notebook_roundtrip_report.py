#!/usr/bin/env python3
"""Emit notebook/lab_steps round-trip evidence for AGILAB."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
import tomllib
from typing import Any, Sequence

import tomli_w


REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_RELATIVE_PATH = Path("docs/source/features.rst")
MODULE_NAME = "notebook_roundtrip_project"


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

from agilab.notebook_export_support import (
    DEFAULT_NOTEBOOK_EXPORT_MODE,
    NotebookExportContext,
    build_notebook_document,
)
from agilab.notebook_pipeline_import import (
    build_lab_steps_preview,
    persist_notebook_pipeline_import,
    write_lab_steps_preview,
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


def sample_lab_steps() -> dict[str, list[dict[str, Any]]]:
    return {
        MODULE_NAME: [
            {
                "D": "Seed notebook round-trip inputs",
                "Q": "Create a compact dataframe and persist it for the next step.",
                "M": "gpt-5.5",
                "C": (
                    "from pathlib import Path\n"
                    "import pandas as pd\n"
                    "artifact = Path('artifacts/roundtrip_input.csv')\n"
                    "df = pd.DataFrame({'value': [1, 2, 3]})\n"
                    "df.to_csv(artifact, index=False)\n"
                ),
                "R": "runpy",
            },
            {
                "D": "Summarize notebook round-trip output",
                "Q": "Read the imported artifact and declare the JSON summary path.",
                "M": "",
                "C": (
                    "import json\n"
                    "summary_path = 'artifacts/roundtrip_summary.json'\n"
                    "summary = {'rows': 3, 'source': 'artifacts/roundtrip_input.csv'}\n"
                    "Path(summary_path).write_text(json.dumps(summary), encoding='utf-8')\n"
                ),
                "R": "runpy",
            },
        ]
    }


def _write_toml(path: Path, payload: dict[str, list[dict[str, Any]]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as stream:
        tomli_w.dump(payload, stream)
    return path


def _write_notebook(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _docs_check(repo_root: Path) -> dict[str, Any]:
    required = [
        "notebook round-trip report",
        "tools/notebook_roundtrip_report.py --compact",
        "lab_steps.toml -> supervisor notebook -> import -> lab_steps preview",
        "not_executed_import",
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
        "notebook_roundtrip_docs_reference",
        "Notebook round-trip docs reference",
        ok,
        (
            "features docs expose the notebook round-trip command"
            if ok
            else "features docs do not expose the notebook round-trip command"
        ),
        evidence=[str(DOC_RELATIVE_PATH)],
        details=details,
    )


def _step_projection(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "D": entry.get("D", ""),
        "Q": entry.get("Q", ""),
        "M": entry.get("M", ""),
        "C": entry.get("C", ""),
        "R": entry.get("R", ""),
    }


def _project_steps(payload: dict[str, Any]) -> list[dict[str, Any]]:
    steps = payload.get(MODULE_NAME, [])
    if not isinstance(steps, list):
        return []
    return [step for step in steps if isinstance(step, dict)]


def build_report(
    *,
    repo_root: Path = REPO_ROOT,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    if output_dir is None:
        with tempfile.TemporaryDirectory(prefix="agilab-notebook-roundtrip-") as tmp_dir:
            return _build_report_with_dir(repo_root=repo_root, output_dir=Path(tmp_dir))
    return _build_report_with_dir(repo_root=repo_root, output_dir=output_dir)


def _build_report_with_dir(*, repo_root: Path, output_dir: Path) -> dict[str, Any]:
    output_dir = output_dir.expanduser()
    original_lab_steps = sample_lab_steps()
    original_path = _write_toml(output_dir / "lab_steps.toml", original_lab_steps)
    context = NotebookExportContext(
        project_name=MODULE_NAME,
        module_path=MODULE_NAME,
        artifact_dir=str(output_dir / "artifacts"),
        repo_root=str(repo_root),
        export_mode=DEFAULT_NOTEBOOK_EXPORT_MODE,
    )
    notebook = build_notebook_document(
        original_lab_steps,
        original_path,
        export_context=context,
    )
    notebook_path = _write_notebook(output_dir / "lab_steps.ipynb", notebook)
    import_path = output_dir / "notebook_roundtrip_import.json"
    proof = persist_notebook_pipeline_import(
        repo_root=repo_root,
        output_path=import_path,
        notebook_path=notebook_path,
    )
    preview = build_lab_steps_preview(proof.notebook_import, module_name=MODULE_NAME)
    preview_path = write_lab_steps_preview(output_dir / "lab_steps_preview.toml", preview)
    preview_reloaded = tomllib.loads(preview_path.read_text(encoding="utf-8"))
    original_steps = [_step_projection(step) for step in _project_steps(original_lab_steps)]
    preview_steps = [_step_projection(step) for step in _project_steps(preview_reloaded)]
    state = proof.notebook_import
    summary = state.get("summary", {})
    source = state.get("source", {})

    checks = [
        _check_result(
            "notebook_roundtrip_supervisor_export",
            "Notebook round-trip supervisor export",
            notebook.get("metadata", {}).get("agilab", {}).get("export_mode")
            == DEFAULT_NOTEBOOK_EXPORT_MODE
            and len(notebook.get("metadata", {}).get("agilab", {}).get("steps", [])) == 2
            and Path(notebook_path).is_file(),
            "supervisor notebook export embeds AGILAB step metadata",
            evidence=["src/agilab/notebook_export_support.py", str(notebook_path)],
            details={"metadata": notebook.get("metadata", {}).get("agilab", {})},
        ),
        _check_result(
            "notebook_roundtrip_import_mode",
            "Notebook round-trip import mode",
            proof.ok
            and state.get("execution_mode") == "not_executed_import"
            and source.get("import_mode") == "agilab_supervisor_metadata"
            and summary.get("supervisor_step_count") == 2
            and summary.get("pipeline_step_count") == 2,
            "importer reconstructs pipeline steps from supervisor metadata",
            evidence=["src/agilab/notebook_pipeline_import.py", str(import_path)],
            details={
                "source": source,
                "summary": summary,
                "issues": [issue.as_dict() for issue in proof.issues],
            },
        ),
        _check_result(
            "notebook_roundtrip_lab_steps_fields",
            "Notebook round-trip lab_steps fields",
            original_steps == preview_steps
            and preview_reloaded == preview
            and Path(preview_path).is_file(),
            "lab_steps preview preserves D/Q/M/C/R fields through export/import",
            evidence=[str(original_path), str(preview_path)],
            details={
                "original_steps": original_steps,
                "preview_steps": preview_steps,
            },
        ),
        _check_result(
            "notebook_roundtrip_artifacts_env_hints",
            "Notebook round-trip artifact and environment hints",
            {"json", "pandas", "pathlib"}.issubset(set(state.get("env_hints", [])))
            and summary.get("artifact_reference_count", 0) >= 3
            and "artifacts/roundtrip_summary.json"
            in {
                reference.get("path", "")
                for reference in state.get("artifact_references", [])
                if isinstance(reference, dict)
            },
            "round-trip import preserves env hints and artifact references",
            evidence=[str(notebook_path)],
            details={
                "env_hints": state.get("env_hints", []),
                "artifact_references": state.get("artifact_references", []),
            },
        ),
        _docs_check(repo_root),
    ]

    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "report": "Notebook round-trip report",
        "status": "pass" if failed == 0 else "fail",
        "scope": (
            "Validates lab_steps.toml -> supervisor notebook -> import -> "
            "lab_steps preview without executing notebook cells."
        ),
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "execution_mode": state.get("execution_mode"),
            "import_mode": source.get("import_mode"),
            "supervisor_step_count": summary.get("supervisor_step_count"),
            "pipeline_step_count": summary.get("pipeline_step_count"),
            "lab_steps_round_trip_ok": original_steps == preview_steps,
            "env_hint_count": summary.get("env_hint_count"),
            "artifact_reference_count": summary.get("artifact_reference_count"),
            "original_lab_steps_path": str(original_path),
            "notebook_path": str(notebook_path),
            "preview_path": str(preview_path),
        },
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit AGILAB notebook/lab_steps round-trip evidence."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional directory for generated round-trip artifacts.",
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
