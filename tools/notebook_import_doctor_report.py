#!/usr/bin/env python3
"""Emit Notebook Import Doctor evidence for AGILAB."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NOTEBOOK = REPO_ROOT / "docs/source/data/notebook_pipeline_import_sample.ipynb"


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

from agilab.notebook_import_doctor import SCHEMA, diagnose_notebook_file, write_doctor_report


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


def _load_failure_report(notebook_path: Path, exc: Exception) -> dict[str, Any]:
    return {
        "report": "Notebook Import Doctor report",
        "status": "fail",
        "scope": "Diagnoses notebook migration risks without executing cells.",
        "notebook_path": str(notebook_path),
        "summary": {"passed": 0, "failed": 1, "total": 1, "error": str(exc)},
        "doctor": {},
        "checks": [
            _check_result(
                "notebook_import_doctor_load",
                "Notebook Import Doctor load",
                False,
                "doctor could not load or parse the notebook",
                evidence=[str(notebook_path)],
                details={"error": str(exc)},
            )
        ],
    }


def build_report(
    *,
    notebook_path: Path = DEFAULT_NOTEBOOK,
    output_path: Path | None = None,
) -> dict[str, Any]:
    notebook_path = notebook_path.expanduser()
    if output_path is None:
        with tempfile.TemporaryDirectory(prefix="agilab-notebook-doctor-") as tmp_dir:
            return _build_report_with_output(
                notebook_path=notebook_path,
                output_path=Path(tmp_dir) / "notebook_import_doctor.json",
            )
    return _build_report_with_output(
        notebook_path=notebook_path,
        output_path=output_path.expanduser(),
    )


def _build_report_with_output(*, notebook_path: Path, output_path: Path) -> dict[str, Any]:
    try:
        doctor = diagnose_notebook_file(notebook_path)
        written = write_doctor_report(output_path, doctor)
    except Exception as exc:
        return _load_failure_report(notebook_path, exc)

    summary = doctor.get("summary", {})
    checks = [
        _check_result(
            "notebook_import_doctor_schema",
            "Notebook Import Doctor schema",
            doctor.get("schema") == SCHEMA and doctor.get("status") in {"pass", "warn", "fail"},
            "doctor emits the supported schema and migration status",
            evidence=["src/agilab/notebook_import_doctor.py", str(notebook_path)],
            details={"schema": doctor.get("schema"), "status": doctor.get("status")},
        ),
        _check_result(
            "notebook_import_doctor_artifacts",
            "Notebook Import Doctor artifacts",
            (
                summary.get("input_artifact_count", 0)
                + summary.get("output_artifact_count", 0)
                + summary.get("ambiguous_artifact_count", 0)
            )
            >= 1,
            "doctor classifies artifact references into migration buckets",
            evidence=[str(notebook_path)],
            details=doctor.get("artifact_contract", {}),
        ),
        _check_result(
            "notebook_import_doctor_hidden_state",
            "Notebook Import Doctor hidden state",
            summary.get("hidden_global_count", 0) >= 1,
            "doctor detects cross-cell globals that should become explicit AGILAB state",
            evidence=[str(notebook_path)],
            details={
                "issues": [
                    issue
                    for issue in doctor.get("issues", [])
                    if issue.get("code") == "hidden_global"
                ]
            },
        ),
        _check_result(
            "notebook_import_doctor_persistence",
            "Notebook Import Doctor persistence",
            written.is_file(),
            "doctor report is persisted as JSON",
            evidence=[str(written)],
            details={"path": str(written)},
        ),
    ]
    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "report": "Notebook Import Doctor report",
        "status": "pass" if failed == 0 else "fail",
        "scope": "Diagnoses notebook migration risks without executing cells.",
        "notebook_path": str(notebook_path),
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "doctor_status": doctor.get("status"),
            "readiness_score": doctor.get("readiness_score"),
            **summary,
        },
        "doctor": doctor,
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit AGILAB Notebook Import Doctor evidence."
    )
    parser.add_argument("--notebook", type=Path, default=DEFAULT_NOTEBOOK)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--compact", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    report = build_report(notebook_path=args.notebook, output_path=args.output)
    if args.compact:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
