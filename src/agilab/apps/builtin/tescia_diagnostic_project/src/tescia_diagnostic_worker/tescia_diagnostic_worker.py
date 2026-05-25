"""Pandas-based worker for the TeSciA diagnostic app."""

from __future__ import annotations

import csv
import json
import logging
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd

from agi_node.pandas_worker import PandasWorker
from tescia_diagnostic.classroom import (
    CLASSROOM_SCHEMA,
    expand_classroom_submissions,
    write_classroom_artifacts,
    write_classroom_partial_artifacts,
)
from tescia_diagnostic.curriculum import build_math_program_2026_coverage_report
from tescia_diagnostic.diagnostic import diagnose_case, summarize_report, validate_case_payload
from tescia_diagnostic.exports import write_correction_index, write_correction_sheet
from tescia_diagnostic.reduction import write_reduce_artifact

logger = logging.getLogger(__name__)
_runtime: dict[str, object] = {}


def _artifact_dir(env: object, leaf: str) -> Path:
    export_root = getattr(env, "AGILAB_EXPORT_ABS", None)
    target = str(getattr(env, "target", "") or "")
    relative = Path(target) / leaf if target else Path(leaf)
    if export_root is not None:
        return Path(export_root) / relative
    resolve_share_path = getattr(env, "resolve_share_path", None)
    if callable(resolve_share_path):
        return Path(resolve_share_path(relative))
    return Path.home() / "export" / relative


def _sanitize_slug(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value.strip())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned or "tescia_case"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class TesciaDiagnosticWorker(PandasWorker):
    """Execute deterministic diagnostic scoring and export evidence artifacts."""

    pool_vars: dict[str, object] = {}

    def start(self):
        global _runtime
        if isinstance(self.args, dict):
            self.args = SimpleNamespace(**self.args)
        elif not isinstance(self.args, SimpleNamespace):
            self.args = SimpleNamespace(**vars(self.args))

        data_paths = self.setup_data_directories(
            source_path=self.args.data_in,
            target_path=self.args.data_out,
            target_subdir="reports",
            reset_target=bool(getattr(self.args, "reset_target", False)),
        )
        self.args.data_in = data_paths.normalized_input
        self.args.data_out = data_paths.normalized_output
        self.data_out = data_paths.output_path
        self.artifact_dir = _artifact_dir(self.env, "tescia_diagnostic")
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.pool_vars = {"args": self.args}
        _runtime = self.pool_vars

    def pool_init(self, worker_vars):
        global _runtime
        _runtime = worker_vars

    def _current_args(self) -> SimpleNamespace:
        args = _runtime.get("args", self.args)
        if isinstance(args, dict):
            return SimpleNamespace(**args)
        return args

    def work_init(self) -> None:
        return None

    def _load_cases(self, file_path: str | Path) -> list[dict[str, Any]]:
        source = Path(str(file_path)).expanduser()
        payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Diagnostic file must contain a JSON object: {source}")
        if payload.get("schema") == CLASSROOM_SCHEMA:
            try:
                return expand_classroom_submissions(payload)
            except ValueError as exc:
                raise ValueError(f"Invalid TeSciA classroom submission file {source}: {exc}") from exc
        try:
            validated = validate_case_payload(payload)
        except ValueError as exc:
            raise ValueError(f"Invalid TeSciA diagnostic file {source}: {exc}") from exc
        return validated["cases"]

    def work_pool(self, file_path):
        args = self._current_args()
        rows: list[dict[str, Any]] = []
        reports: list[dict[str, Any]] = []
        for case in self._load_cases(file_path):
            report = diagnose_case(
                case,
                minimum_evidence_confidence=float(getattr(args, "minimum_evidence_confidence", 0.65)),
                minimum_regression_coverage=float(getattr(args, "minimum_regression_coverage", 0.6)),
            )
            summary = summarize_report(
                report,
                worker_id=int(getattr(self, "_worker_id", 0)),
                source_file=str(file_path),
            )
            reports.append(report)
            row = {
                **summary,
                "report_json": json.dumps(report, sort_keys=True),
            }
            rows.append(row)
        if any(str(report.get("classroom", {}).get("student_ref", "")).strip() for report in reports):
            worker_id = int(getattr(self, "_worker_id", 0))
            write_classroom_partial_artifacts(
                reports,
                Path(self.data_out) / "classroom",
                worker_id=worker_id,
                source_file=file_path,
            )
            write_classroom_partial_artifacts(
                reports,
                self.artifact_dir / "classroom",
                worker_id=worker_id,
                source_file=file_path,
            )
        return pd.DataFrame(rows)

    def _write_artifact_bundle(self, root: Path, df: pd.DataFrame) -> None:
        root.mkdir(parents=True, exist_ok=True)
        summaries: list[dict[str, Any]] = []
        reports: list[dict[str, Any]] = []
        correction_paths: list[Path] = []
        for _, row in df.iterrows():
            report = json.loads(str(row["report_json"]))
            reports.append(report)
            summary = {
                key: row[key].item() if hasattr(row[key], "item") else row[key]
                for key in row.index
                if key != "report_json"
            }
            summaries.append(summary)
            stem = _sanitize_slug(str(summary["case_id"]))
            run_root = root / stem
            if run_root.exists() and bool(getattr(self._current_args(), "reset_target", False)):
                shutil.rmtree(run_root)
            run_root.mkdir(parents=True, exist_ok=True)
            _write_json(run_root / f"{stem}_diagnostic_report.json", report)
            _write_csv(run_root / f"{stem}_diagnostic_summary.csv", [summary])
            correction_paths.append(write_correction_sheet(report, root / "correction_sheets"))

        if summaries:
            _write_csv(root / "tescia_diagnostic_summary.csv", summaries)
            write_correction_index(correction_paths, root / "correction_sheets")
            coverage_cases = [
                {
                    "case_id": str(summary.get("case_id", "")),
                    "curriculum_ids": [
                        item.strip()
                        for item in str(summary.get("curriculum_ids", "")).split(",")
                        if item.strip()
                    ],
                }
                for summary in summaries
            ]
            _write_json(
                root / "math_program_2026_coverage.json",
                build_math_program_2026_coverage_report(coverage_cases),
            )
            if any(str(report.get("classroom", {}).get("student_ref", "")).strip() for report in reports):
                write_classroom_artifacts(reports, root / "classroom")
            write_reduce_artifact(
                summaries,
                root,
                worker_id=int(getattr(self, "_worker_id", 0)),
            )

    def work_done(self, df: pd.DataFrame | None = None) -> None:
        if df is None or df.empty:
            return
        self._write_artifact_bundle(Path(self.data_out), df)
        self._write_artifact_bundle(self.artifact_dir, df)
        logger.info("wrote TeSciA diagnostic artifacts for %s cases", len(df))


__all__ = ["TesciaDiagnosticWorker"]
