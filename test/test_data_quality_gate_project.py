from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP_SRC = ROOT / "src/agilab/apps/builtin/data_quality_gate_project/src"
if str(APP_SRC) not in sys.path:
    sys.path.insert(0, str(APP_SRC))

from data_quality_gate import (  # noqa: E402
    DataQualityGateArgs,
    build_data_quality_gate_artifacts,
    validate_relative_data_out,
)
from data_quality_gate.reduction import write_reduce_artifact  # noqa: E402


def test_data_quality_gate_writes_replayable_evidence(tmp_path: Path) -> None:
    summary = build_data_quality_gate_artifacts(output_dir=tmp_path, drift_strength=0.35, seed=2026)

    assert summary["schema"] == "agilab.app.data_quality_gate.v1"
    assert summary["decision"] == "manual-review"
    assert summary["quality"] == {
        "candidate_duplicate_rate": 0.0,
        "candidate_null_rate_max": 0.0,
        "leakage_columns": [],
        "row_count_delta": 0.083333,
    }
    assert summary["drift"]["warn_feature_count"] == 1
    assert summary["drift"]["block_feature_count"] == 0
    assert summary["drift"]["max_psi"] == 0.12426

    required = {
        "baseline.csv",
        "candidate.csv",
        "baseline_profile.json",
        "candidate_profile.json",
        "data_contract.json",
        "drift_metrics.csv",
        "gate_decision.json",
        "data_quality_report.md",
        "run_manifest.json",
        "data_quality_gate_summary.json",
    }
    assert required <= {path.name for path in tmp_path.iterdir()}

    manifest = json.loads((tmp_path / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["app"] == "data_quality_gate_project"
    assert manifest["deterministic"] is True
    assert manifest["promotion_hint"] == "manual-review"
    assert set(manifest["artifacts"]) >= {"baseline", "candidate", "drift_metrics", "gate_decision"}
    assert all(len(artifact["sha256"]) == 64 for artifact in manifest["artifacts"].values())

    with (tmp_path / "drift_metrics.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert {row["feature"] for row in rows} == {"age", "income", "risk_score", "segment", "region"}
    assert any(row["severity"] == "warn" for row in rows)


def test_data_quality_gate_blocks_quality_and_leakage_issues(tmp_path: Path) -> None:
    summary = build_data_quality_gate_artifacts(output_dir=tmp_path, include_quality_issues=True)

    assert summary["decision"] == "block"
    assert summary["quality"]["candidate_null_rate_max"] > 0.02
    assert summary["quality"]["leakage_columns"] == ["target_proxy_leakage"]

    decision = json.loads((tmp_path / "gate_decision.json").read_text(encoding="utf-8"))
    assert any("potential leakage columns" in blocker for blocker in decision["blockers"])


def test_data_quality_gate_reduce_artifact_matches_public_contract(tmp_path: Path) -> None:
    summary = build_data_quality_gate_artifacts(output_dir=tmp_path)

    artifact_path = write_reduce_artifact([summary], tmp_path, worker_id=0)

    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["reducer"] == "data_quality_gate.evidence.v1"
    assert payload["name"] == "data_quality_gate_reduce_summary"
    assert payload["payload"]["run_count"] == 1
    assert payload["payload"]["manual_review_count"] == 1
    assert payload["payload"]["max_psi"] == summary["drift"]["max_psi"]
    assert "run_manifest.json" in payload["payload"]["artifact_paths"]


def test_data_quality_gate_args_reject_unsafe_output_paths() -> None:
    assert DataQualityGateArgs(data_out="safe/evidence").data_out == Path("safe/evidence")

    for value in ("/tmp/out", "~/out", "../out", ".", "C:/temp/out"):
        with pytest.raises(ValueError):
            validate_relative_data_out(value)
