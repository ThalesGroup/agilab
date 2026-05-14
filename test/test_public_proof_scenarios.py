from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path("tools/public_proof_scenarios.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "public_proof_scenarios_test_module",
        MODULE_PATH,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_public_proof_scenarios_pass_static_contract(tmp_path: Path) -> None:
    module = _load_module()

    report = module.build_report(repo_root=Path.cwd())

    assert report["schema"] == "agilab.public_proof_scenarios.v1"
    assert report["status"] == "pass"
    assert report["summary"]["scenario_count"] == 3
    assert report["summary"]["first_proof_target_seconds"] == 60.0
    assert report["summary"]["full_install_target_seconds"] == 120.0
    assert report["summary"]["scenario_ids"] == [
        "flight-local-first-proof",
        "weather-forecast-hosted-proof",
        "mlflow-tracking-proof",
    ]
    rows = {scenario["id"]: scenario for scenario in report["scenarios"]}
    assert 'python -m pip install "agilab[examples]"' in rows[
        "flight-local-first-proof"
    ]["commands"]
    assert "python -m agilab.lab_run first-proof --json --max-seconds 60" in rows[
        "flight-local-first-proof"
    ]["commands"]
    assert "tools/hf_space_smoke.py --json" in " ".join(
        rows["weather-forecast-hosted-proof"]["commands"]
    )
    assert "MLflow remains the tracking system" in " ".join(
        rows["mlflow-tracking-proof"]["limits"]
    )
    assert all(not scenario["missing_evidence_files"] for scenario in report["scenarios"])

    output = tmp_path / "public_proof_scenarios.json"
    assert module.main(["--output", str(output), "--compact"]) == 0
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["status"] == "pass"


def test_public_proof_scenarios_attach_runtime_artifacts(tmp_path: Path) -> None:
    module = _load_module()
    first_proof = tmp_path / "first-proof.json"
    first_proof.write_text(
        json.dumps(
            {
                "success": True,
                "total_duration_seconds": 42.0,
                "target_seconds": 60.0,
                "within_target": True,
                "steps": [{"label": "package ui smoke"}],
            }
        ),
        encoding="utf-8",
    )
    hf_smoke = tmp_path / "hf-space-smoke.json"
    hf_smoke.write_text(
        json.dumps(
            {
                "success": True,
                "total_duration_seconds": 12.5,
                "target_seconds": 30.0,
                "within_target": True,
                "checks": [{"label": "weather forecast project"}],
            }
        ),
        encoding="utf-8",
    )

    report = module.build_report(
        repo_root=Path.cwd(),
        first_proof_json=first_proof,
        hf_smoke_json=hf_smoke,
    )

    assert report["status"] == "pass"
    assert report["summary"]["runtime_artifact_count"] == 2
    rows = {scenario["id"]: scenario for scenario in report["scenarios"]}
    assert rows["flight-local-first-proof"]["runtime_evidence"]["status"] == "pass"
    assert rows["flight-local-first-proof"]["runtime_evidence"]["check_labels"] == [
        "package ui smoke"
    ]
    assert rows["weather-forecast-hosted-proof"]["runtime_evidence"][
        "within_target"
    ] is True


def test_public_proof_scenarios_reject_slow_runtime_artifact(tmp_path: Path) -> None:
    module = _load_module()
    first_proof = tmp_path / "first-proof.json"
    first_proof.write_text(
        json.dumps(
            {
                "success": True,
                "total_duration_seconds": 99.0,
                "target_seconds": 60.0,
                "within_target": False,
            }
        ),
        encoding="utf-8",
    )

    report = module.build_report(repo_root=Path.cwd(), first_proof_json=first_proof)

    assert report["status"] == "fail"
    rows = {scenario["id"]: scenario for scenario in report["scenarios"]}
    assert rows["flight-local-first-proof"]["runtime_evidence"]["status"] == "fail"
