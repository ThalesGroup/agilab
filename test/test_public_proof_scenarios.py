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
        "meteo-forecast-hosted-proof",
        "mlflow-tracking-proof",
    ]
    rows = {scenario["id"]: scenario for scenario in report["scenarios"]}
    assert "agilab first-proof --json --max-seconds 60" in rows[
        "flight-local-first-proof"
    ]["commands"]
    assert "tools/hf_space_smoke.py --json" in " ".join(
        rows["meteo-forecast-hosted-proof"]["commands"]
    )
    assert "MLflow remains the tracking system" in " ".join(
        rows["mlflow-tracking-proof"]["limits"]
    )
    assert all(not scenario["missing_evidence_files"] for scenario in report["scenarios"])

    output = tmp_path / "public_proof_scenarios.json"
    assert module.main(["--output", str(output), "--compact"]) == 0
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["status"] == "pass"
