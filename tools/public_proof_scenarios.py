#!/usr/bin/env python3
"""Emit AGILAB public proof scenario evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import platform
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "agilab.public_proof_scenarios.v1"
FIRST_PROOF_TARGET_SECONDS = 60.0
FULL_INSTALL_TARGET_SECONDS = 120.0


SCENARIOS: tuple[dict[str, Any], ...] = (
    {
        "id": "flight-local-first-proof",
        "label": "Local package proof",
        "route": "packaged examples-profile first-proof for flight_telemetry_project",
        "target_seconds": FIRST_PROOF_TARGET_SECONDS,
        "commands": [
            'python -m pip install "agilab[examples]"',
            "python -m agilab.lab_run first-proof --json --max-seconds 60",
        ],
        "evidence_files": [
            "src/agilab/apps/builtin/flight_telemetry_project/pyproject.toml",
            "src/agilab/apps/builtin/flight_telemetry_project/src/app_settings.toml",
            "src/agilab/apps/builtin/flight_telemetry_project/pipeline_view.dot",
            "src/agilab/apps-pages/view_maps/src/view_maps/view_maps.py",
        ],
        "expected_artifacts": [
            "~/log/execute/flight_telemetry/run_manifest.json",
            "~/log/execute/flight_telemetry",
        ],
        "scope": "Clean local package proof with the `agi-apps` public app umbrella and per-app payloads; install `agilab[ui]` for the visible flight analysis route and the `agi-pages` analysis views.",
        "limits": [
            "No remote cluster certification",
            "Examples-profile proof does not install optional UI, MLflow, visualization, or local-LLM extras",
            "Released package proof is separate from unmerged branch validation",
        ],
    },
    {
        "id": "weather-forecast-hosted-proof",
        "label": "Second public app proof",
        "route": "Hosted or local weather_forecast_project forecast analysis",
        "target_seconds": FIRST_PROOF_TARGET_SECONDS,
        "commands": [
            "uv --preview-features extra-build-dependencies run python tools/hf_space_smoke.py --json",
        ],
        "evidence_files": [
            "src/agilab/apps/builtin/weather_forecast_project/pyproject.toml",
            "src/agilab/apps/builtin/weather_forecast_project/lab_stages.toml",
            "src/agilab/apps/builtin/weather_forecast_project/pipeline_view.dot",
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
        "route": "WORKFLOW run with MLflow-backed tracking enabled",
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


def _load_runtime_json(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "success": False,
            "within_target": False,
            "artifact_error": str(exc),
        }
    if not isinstance(payload, dict):
        return {
            "success": False,
            "within_target": False,
            "artifact_error": "runtime artifact must contain a JSON object",
        }
    return payload


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _runtime_evidence(
    *,
    path: Path,
    payload: dict[str, Any],
    target_seconds: float,
) -> dict[str, Any]:
    total_seconds = _as_float(payload.get("total_duration_seconds"))
    payload_target = _as_float(payload.get("target_seconds"))
    effective_target = payload_target if payload_target is not None else target_seconds
    success = payload.get("success") is True
    within_target = payload.get("within_target")
    if within_target is None and total_seconds is not None:
        within_target = success and total_seconds <= effective_target
    check_labels: list[str] = []
    for check in payload.get("checks", []):
        if isinstance(check, dict) and check.get("label"):
            check_labels.append(str(check["label"]))
    for step in payload.get("steps", []):
        if isinstance(step, dict) and step.get("label"):
            check_labels.append(str(step["label"]))
    status = "pass" if success and within_target is True else "fail"
    return {
        "path": str(path),
        "status": status,
        "success": success,
        "within_target": within_target is True,
        "total_duration_seconds": total_seconds,
        "target_seconds": effective_target,
        "check_labels": check_labels,
        "artifact_error": payload.get("artifact_error"),
    }


def _scenario_row(
    repo_root: Path,
    scenario: dict[str, Any],
    *,
    runtime_payloads: dict[str, tuple[Path, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    evidence = [_file_status(repo_root, path) for path in scenario["evidence_files"]]
    missing = [row["path"] for row in evidence if not row["exists"]]
    row = dict(scenario)
    row["evidence"] = evidence
    row["missing_evidence_files"] = missing
    runtime_status = "pass"
    runtime_payload = (runtime_payloads or {}).get(str(scenario["id"]))
    if runtime_payload is not None:
        runtime_path, payload = runtime_payload
        runtime = _runtime_evidence(
            path=runtime_path,
            payload=payload,
            target_seconds=float(scenario["target_seconds"]),
        )
        row["runtime_evidence"] = runtime
        runtime_status = runtime["status"]
    row["status"] = "pass" if not missing and runtime_status == "pass" else "fail"
    return row


def build_report(
    *,
    repo_root: Path = REPO_ROOT,
    first_proof_json: Path | None = None,
    hf_smoke_json: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    runtime_payloads: dict[str, tuple[Path, dict[str, Any]]] = {}
    first_proof_payload = _load_runtime_json(first_proof_json)
    if first_proof_payload is not None and first_proof_json is not None:
        runtime_payloads["flight-local-first-proof"] = (
            first_proof_json,
            first_proof_payload,
        )
    hf_smoke_payload = _load_runtime_json(hf_smoke_json)
    if hf_smoke_payload is not None and hf_smoke_json is not None:
        runtime_payloads["weather-forecast-hosted-proof"] = (
            hf_smoke_json,
            hf_smoke_payload,
        )
    scenarios = [
        _scenario_row(repo_root, scenario, runtime_payloads=runtime_payloads)
        for scenario in SCENARIOS
    ]
    failed = [scenario for scenario in scenarios if scenario["status"] != "pass"]
    return {
        "report": "Public proof scenario report",
        "schema": SCHEMA,
        "status": "pass" if not failed else "fail",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "python": platform.python_version(),
        },
        "summary": {
            "scenario_count": len(scenarios),
            "passed": len(scenarios) - len(failed),
            "failed": len(failed),
            "scenario_ids": [scenario["id"] for scenario in scenarios],
            "first_proof_target_seconds": FIRST_PROOF_TARGET_SECONDS,
            "full_install_target_seconds": FULL_INSTALL_TARGET_SECONDS,
            "runtime_artifact_count": len(runtime_payloads),
        },
        "scenarios": scenarios,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit static evidence for AGILAB public proof scenarios."
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--compact", action="store_true")
    parser.add_argument(
        "--first-proof-json",
        type=Path,
        default=None,
        help="Optional agilab first-proof JSON artifact to attach as runtime evidence.",
    )
    parser.add_argument(
        "--hf-smoke-json",
        type=Path,
        default=None,
        help="Optional tools/hf_space_smoke.py --json artifact to attach as runtime evidence.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    report = build_report(
        first_proof_json=args.first_proof_json,
        hf_smoke_json=args.hf_smoke_json,
    )
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
