from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP_SRC = ROOT / "src/agilab/apps/builtin/data_quality_gate_project/src"
if str(APP_SRC) not in sys.path:
    sys.path.insert(0, str(APP_SRC))

from data_quality_gate import (  # noqa: E402
    CONTRACT_SCHEMA,
    DataQualityGateArgs,
    THRESHOLDS_SCHEMA,
    build_data_quality_gate_artifacts,
    default_contract,
    validate_relative_data_out,
)
from data_quality_gate.reduction import write_reduce_artifact  # noqa: E402
from data_quality_gate_worker.data_quality_gate_worker import DataQualityGateWorker  # noqa: E402


def _make_env(tmp_path: Path) -> SimpleNamespace:
    share_root = tmp_path / "share"
    export_root = tmp_path / "export"
    share_root.mkdir(parents=True, exist_ok=True)
    export_root.mkdir(parents=True, exist_ok=True)

    def _resolve_share_path(path: str | Path) -> Path:
        candidate = Path(path)
        return candidate if candidate.is_absolute() else share_root / candidate

    return SimpleNamespace(
        AGILAB_EXPORT_ABS=export_root,
        AGI_LOCAL_SHARE=str(share_root),
        _is_managed_pc=False,
        home_abs=tmp_path,
        resolve_share_path=_resolve_share_path,
        target="data_quality_gate_project",
        verbose=0,
    )


def test_data_quality_gate_exports_policy_schema_helpers() -> None:
    contract = default_contract()

    assert CONTRACT_SCHEMA == "agilab.app.data_quality_gate.contract.v1"
    assert THRESHOLDS_SCHEMA == "agilab.app.data_quality_gate.thresholds.v1"
    assert contract["schema"] == CONTRACT_SCHEMA
    assert contract["columns"]["age"]["kind"] == "numeric"
    assert contract["columns"]["target"]["role"] == "target"


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
        "data_quality_dashboard.html",
        "drift_metrics.csv",
        "decision_card.json",
        "gate_decision.json",
        "input_sources.json",
        "data_quality_report.md",
        "run_manifest.json",
        "data_quality_gate_summary.json",
    }
    assert required <= {path.name for path in tmp_path.iterdir()}

    manifest = json.loads((tmp_path / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["app"] == "data_quality_gate_project"
    assert manifest["deterministic"] is True
    assert manifest["inputs"]["input_mode"] == "synthetic"
    assert manifest["promotion_hint"] == "manual-review"
    assert set(manifest["artifacts"]) >= {
        "baseline",
        "candidate",
        "dashboard",
        "decision_card",
        "drift_metrics",
        "gate_decision",
        "input_sources",
    }
    assert all(len(artifact["sha256"]) == 64 for artifact in manifest["artifacts"].values())

    with (tmp_path / "drift_metrics.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert {row["feature"] for row in rows} == {"age", "income", "risk_score", "segment", "region"}
    assert any(row["severity"] == "warn" for row in rows)

    decision_card = json.loads((tmp_path / "decision_card.json").read_text(encoding="utf-8"))
    assert decision_card["recommended_action"].startswith("Hold promotion")
    assert decision_card["risk_score"] > 0
    assert "manual-review" in (tmp_path / "data_quality_dashboard.html").read_text(encoding="utf-8")


def test_data_quality_gate_blocks_quality_and_leakage_issues(tmp_path: Path) -> None:
    summary = build_data_quality_gate_artifacts(output_dir=tmp_path, include_quality_issues=True)

    assert summary["decision"] == "block"
    assert summary["quality"]["candidate_null_rate_max"] > 0.02
    assert summary["quality"]["leakage_columns"] == ["target_proxy_leakage"]

    decision = json.loads((tmp_path / "gate_decision.json").read_text(encoding="utf-8"))
    assert any("potential leakage columns" in blocker for blocker in decision["blockers"])


def test_data_quality_gate_accepts_csv_contract_and_threshold_files(tmp_path: Path) -> None:
    baseline_csv = tmp_path / "baseline_input.csv"
    candidate_csv = tmp_path / "candidate_input.csv"
    contract_json = tmp_path / "contract.json"
    thresholds_json = tmp_path / "thresholds.json"
    output_dir = tmp_path / "evidence"

    baseline_csv.write_text(
        "customer_id,age,segment,target\n"
        + "\n".join(f"{idx},{20 + idx % 20},{'a' if idx % 2 else 'b'},{idx % 2}" for idx in range(1, 101))
        + "\n",
        encoding="utf-8",
    )
    candidate_csv.write_text(
        "customer_id,age,segment,target\n"
        + "\n".join(f"{idx},{60 + idx % 20},{'c' if idx % 3 else 'b'},{idx % 2}" for idx in range(1, 101))
        + "\n",
        encoding="utf-8",
    )
    contract_json.write_text(
        json.dumps(
            {
                "schema": "agilab.app.data_quality_gate.contract.v1",
                "allow_unexpected_columns": False,
                "columns": {
                    "customer_id": {"kind": "integer", "role": "identifier", "drift": False},
                    "age": {"kind": "numeric", "role": "feature", "drift": True},
                    "segment": {"kind": "categorical", "role": "feature", "drift": True},
                    "target": {"kind": "binary", "role": "target", "drift": False},
                },
            }
        ),
        encoding="utf-8",
    )
    thresholds_json.write_text(
        json.dumps({"schema": "agilab.app.data_quality_gate.thresholds.v1", "thresholds": {"psi_block": 0.01}}),
        encoding="utf-8",
    )

    summary = build_data_quality_gate_artifacts(
        output_dir=output_dir,
        baseline_csv=baseline_csv,
        candidate_csv=candidate_csv,
        contract_json=contract_json,
        thresholds_json=thresholds_json,
    )

    assert summary["input_mode"] == "csv"
    assert summary["decision"] == "block"
    manifest = json.loads((output_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["input_sources"]) == {"baseline_csv", "candidate_csv", "contract_json", "thresholds_json"}
    assert all(len(source["sha256"]) == 64 for source in manifest["input_sources"].values())
    contract = json.loads((output_dir / "data_contract.json").read_text(encoding="utf-8"))
    assert contract["thresholds"]["psi_block"] == 0.01
    assert contract["expected_columns"]["age"]["kind"] == "numeric"


def test_data_quality_gate_requires_csv_inputs_as_a_pair(tmp_path: Path) -> None:
    baseline_csv = tmp_path / "baseline_input.csv"
    baseline_csv.write_text("customer_id,age,target\n1,20,0\n", encoding="utf-8")

    with pytest.raises(ValueError, match="baseline_csv and candidate_csv"):
        build_data_quality_gate_artifacts(output_dir=tmp_path / "evidence", baseline_csv=baseline_csv)


def test_data_quality_gate_blocks_contract_type_issues(tmp_path: Path) -> None:
    baseline_csv = tmp_path / "baseline_input.csv"
    candidate_csv = tmp_path / "candidate_input.csv"
    contract_json = tmp_path / "contract.json"
    output_dir = tmp_path / "evidence"

    baseline_csv.write_text("customer_id,age,target\n1,20,0\n2,21,1\n", encoding="utf-8")
    candidate_csv.write_text("customer_id,age,target\n1,old,0\n2,older,1\n", encoding="utf-8")
    contract_json.write_text(
        json.dumps(
            {
                "columns": {
                    "customer_id": {"kind": "integer", "role": "identifier", "drift": False},
                    "age": {"kind": "numeric", "role": "feature", "drift": True},
                    "target": {"kind": "binary", "role": "target", "drift": False},
                }
            }
        ),
        encoding="utf-8",
    )

    summary = build_data_quality_gate_artifacts(
        output_dir=output_dir,
        baseline_csv=baseline_csv,
        candidate_csv=candidate_csv,
        contract_json=contract_json,
    )

    assert summary["decision"] == "block"
    decision = json.loads((output_dir / "gate_decision.json").read_text(encoding="utf-8"))
    assert any("candidate.age expected numeric-compatible data" in blocker for blocker in decision["blockers"])


def test_data_quality_gate_worker_runs_csv_gate_and_mirrors_analysis_artifacts(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    share_root = Path(env.AGI_LOCAL_SHARE)
    input_root = share_root / "data_quality_gate/input"
    input_root.mkdir(parents=True, exist_ok=True)
    (input_root / "baseline.csv").write_text("customer_id,age,target\n1,20,0\n2,21,1\n3,22,0\n", encoding="utf-8")
    (input_root / "candidate.csv").write_text("customer_id,age,target\n1,60,0\n2,61,1\n3,62,0\n", encoding="utf-8")

    args = DataQualityGateArgs(
        data_out="data_quality_gate/evidence",
        baseline_csv="data_quality_gate/input/baseline.csv",
        candidate_csv="data_quality_gate/input/candidate.csv",
        reset_target=True,
    )
    worker = DataQualityGateWorker()
    worker.env = env
    worker.args = args.model_dump(mode="json")
    worker._worker_id = 0
    worker.verbose = 0

    worker.start()
    result = worker.work_pool("data_quality_gate")

    assert set(result["input_mode"]) == {"csv"}
    assert {"decision", "recommended_action", "risk_score"} <= set(result.columns)
    evidence_root = share_root / "data_quality_gate/evidence"
    assert (evidence_root / "run_manifest.json").is_file()
    assert (evidence_root / "data_quality_dashboard.html").is_file()
    assert (Path(env.AGILAB_EXPORT_ABS) / "data_quality_gate_project/data_quality_gate/run_manifest.json").is_file()


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
    assert DataQualityGateArgs(baseline_csv="safe/baseline.csv").baseline_csv == Path("safe/baseline.csv")
    assert DataQualityGateArgs(baseline_csv="").baseline_csv is None

    for value in ("/tmp/out", "~/out", "../out", ".", "C:/temp/out"):
        with pytest.raises(ValueError):
            validate_relative_data_out(value)
        with pytest.raises(ValueError):
            DataQualityGateArgs(baseline_csv=value)
