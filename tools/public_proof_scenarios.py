#!/usr/bin/env python3
"""Emit AGILAB public proof scenario evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "agilab.public_proof_scenarios.v1"
FIRST_PROOF_TARGET_SECONDS = 60.0
FULL_INSTALL_TARGET_SECONDS = 120.0


SCENARIOS: tuple[dict[str, Any], ...] = (
    {
        "id": "flight-local-first-proof",
        "label": "Local app proof",
        "route": "PROJECT -> ORCHESTRATE -> ANALYSIS with flight_project",
        "target_seconds": FIRST_PROOF_TARGET_SECONDS,
        "commands": [
            "python -m pip install agilab",
            "agilab first-proof --json --max-seconds 60",
        ],
        "evidence_files": [
            "src/agilab/apps/builtin/flight_project/pyproject.toml",
            "src/agilab/apps/builtin/flight_project/src/app_settings.toml",
            "src/agilab/apps/builtin/flight_project/pipeline_view.dot",
            "src/agilab/apps-pages/view_maps/src/view_maps/view_maps.py",
        ],
        "expected_artifacts": [
            "~/log/execute/flight/run_manifest.json",
            "~/log/execute/flight",
        ],
        "scope": "Clean local package proof and visible flight analysis route.",
        "limits": [
            "No remote cluster certification",
            "Released package proof is separate from unmerged branch validation",
        ],
    },
    {
        "id": "meteo-forecast-hosted-proof",
        "label": "Second public app proof",
        "route": "Hosted or local meteo_forecast_project forecast analysis",
        "target_seconds": FIRST_PROOF_TARGET_SECONDS,
        "commands": [
            "uv --preview-features extra-build-dependencies run python tools/hf_space_smoke.py --json",
        ],
        "evidence_files": [
            "src/agilab/apps/builtin/meteo_forecast_project/pyproject.toml",
            "src/agilab/apps/builtin/meteo_forecast_project/lab_steps.toml",
            "src/agilab/apps/builtin/meteo_forecast_project/pipeline_view.dot",
            "src/agilab/apps-pages/view_forecast_analysis/src/view_forecast_analysis/view_forecast_analysis.py",
            "src/agilab/apps-pages/view_release_decision/src/view_release_decision/view_release_decision.py",
            "tools/hf_space_smoke.py",
        ],
        "expected_artifacts": [
            "forecast_analysis summary",
            "release decision view evidence",
        ],
        "scope": "Second generic public demo route with forecast and release-decision views.",
        "limits": [
            "Hosted runtime availability depends on Hugging Face Spaces",
            "Does not prove private app repositories",
        ],
    },
    {
        "id": "mlflow-tracking-proof",
        "label": "MLflow tracking proof",
        "route": "PIPELINE run with MLflow-backed tracking enabled",
        "target_seconds": FULL_INSTALL_TARGET_SECONDS,
        "commands": [
            "uv --preview-features extra-build-dependencies run pytest -q test/test_tracking.py test/test_pipeline_run_controls.py",
        ],
        "evidence_files": [
            "src/agilab/tracking.py",
            "src/agilab/pipeline_runtime_mlflow_support.py",
            "src/agilab/pipeline_run_controls.py",
            "docs/source/diagrams/pipeline_mlflow_tracking.svg",
            "docs/source/experiment-help.rst",
        ],
        "expected_artifacts": [
            "parent MLflow run",
            "nested step MLflow runs",
            "pipeline artifacts",
        ],
        "scope": "Tracking contract for pipeline execution handoff into MLflow.",
        "limits": [
            "MLflow remains the tracking system, not an AGILAB replacement",
            "External MLflow server operations remain deployment-specific",
        ],
    },
)


def _file_status(repo_root: Path, relative_path: str) -> dict[str, Any]:
    path = repo_root / relative_path
    return {
        "path": relative_path,
        "exists": path.is_file(),
        "bytes": path.stat().st_size if path.is_file() else 0,
    }


def _scenario_row(repo_root: Path, scenario: dict[str, Any]) -> dict[str, Any]:
    evidence = [_file_status(repo_root, path) for path in scenario["evidence_files"]]
    missing = [row["path"] for row in evidence if not row["exists"]]
    row = dict(scenario)
    row["evidence"] = evidence
    row["missing_evidence_files"] = missing
    row["status"] = "pass" if not missing else "fail"
    return row


def build_report(*, repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    scenarios = [_scenario_row(repo_root, scenario) for scenario in SCENARIOS]
    failed = [scenario for scenario in scenarios if scenario["status"] != "pass"]
    return {
        "report": "Public proof scenario report",
        "schema": SCHEMA,
        "status": "pass" if not failed else "fail",
        "summary": {
            "scenario_count": len(scenarios),
            "passed": len(scenarios) - len(failed),
            "failed": len(failed),
            "scenario_ids": [scenario["id"] for scenario in scenarios],
            "first_proof_target_seconds": FIRST_PROOF_TARGET_SECONDS,
            "full_install_target_seconds": FULL_INSTALL_TARGET_SECONDS,
        },
        "scenarios": scenarios,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit static evidence for AGILAB public proof scenarios."
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--compact", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    report = build_report()
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.compact:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
