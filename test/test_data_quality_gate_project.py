from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_SRC = ROOT / "src/agilab/apps/builtin/data_quality_gate_project/src"
if str(APP_SRC) not in sys.path:
    sys.path.insert(0, str(APP_SRC))

from data_quality_gate import (  # noqa: E402
    CONTRACT_SCHEMA,
    DataQualityGate,
    DataQualityGateArgs,
    THRESHOLDS_SCHEMA,
    build_data_quality_gate_artifacts,
    default_contract,
    validate_relative_data_out,
)
from data_quality_gate.reduction import write_reduce_artifact  # noqa: E402
from data_quality_gate_worker.data_quality_gate_worker import DataQualityGateWorker  # noqa: E402
from data_quality_gate.domain.quality_rules import evaluate_rules, normalize_rules  # noqa: E402


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
        "rule_results.json",
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
    assert (
        Path(env.AGILAB_EXPORT_ABS)
        / "data_quality_gate_project/data_quality_gate/rule_results.json"
    ).read_bytes() == (evidence_root / "rule_results.json").read_bytes()


def _rules_result(frame: pd.DataFrame, rules: list[dict]) -> dict:
    return evaluate_rules(
        frame, normalize_rules(rules, {name: {} for name in frame.columns})
    )


def test_quality_rules_evaluate_each_supported_check_and_keep_values_private() -> None:
    frame = pd.DataFrame(
        {
            "age": [18, 17, None, 65],
            "minimum": [18, 18, 18, 18],
            "segment": ["a", "PRIVATE-CELL", "b", "a"],
            "day": ["2024-02-29", "2023-02-29", None, "2024-2-01"],
            "email": ["a@example.org", "bad", None, "b@example.org"],
        }
    )
    result = _rules_result(
        frame,
        [
            {"id": "range", "column": "age", "kind": "range", "min": 18, "max": 65},
            {"id": "required", "column": "age", "kind": "required"},
            {
                "id": "allowed",
                "column": "segment",
                "kind": "allowed_values",
                "values": ["a", "b"],
            },
            {
                "id": "date",
                "column": "day",
                "kind": "format",
                "format": "iso_date",
                "on_null": "skip",
            },
            {"id": "email", "column": "email", "kind": "format", "format": "email"},
            {
                "id": "compare",
                "column": "age",
                "kind": "compare",
                "other_column": "minimum",
                "operator": "ge",
            },
        ],
    )
    rows = {row["id"]: row for row in result["rules"]}
    assert rows["range"]["failure_counts"] == {"missing_value": 1, "out_of_range": 1}
    assert rows["required"]["failed_row_positions"] == [2]
    assert rows["allowed"]["failed_row_positions"] == [1]
    assert rows["date"]["checked_count"] == 3
    assert rows["date"]["skipped_count"] == 1
    assert rows["date"]["pass_rate"] == 1 / 3
    assert rows["email"]["failed_count"] == 2
    assert rows["compare"]["failure_counts"] == {
        "comparison_failed": 1,
        "missing_value": 1,
    }
    assert "PRIVATE-CELL" not in json.dumps(result)
    assert [row["id"] for row in result["rules"]] == sorted(rows)
    for row in result["rules"]:
        assert row["row_count"] == row["checked_count"] + row["skipped_count"]
        assert row["checked_count"] == row["passed_count"] + row["failed_count"]
        assert sum(row["failure_counts"].values()) == row["failed_count"]


@pytest.mark.parametrize(
    "rule,match",
    [
        ({"kind": "unknown"}, "unsupported kind"),
        ({"kind": "required", "id": ""}, "unique id"),
        ({"kind": "required", "column": "undeclared"}, "declared column"),
        ({"kind": "required", "on_null": "skip"}, "cannot skip nulls"),
        ({"kind": "required", "severity": "pass"}, "severity"),
        ({"kind": "required", "optional": True}, "unsupported fields"),
        ({"kind": "range"}, "finite numeric"),
        ({"kind": "range", "min": True}, "finite numeric"),
        ({"kind": "range", "min": float("inf")}, "finite numeric"),
        ({"kind": "range", "min": 3, "max": 2}, "min must not exceed"),
        ({"kind": "allowed_values", "values": []}, "non-empty list"),
        ({"kind": "allowed_values", "values": [None]}, "non-empty list"),
        ({"kind": "format", "format": "custom_expression"}, "supports format"),
        (
            {"kind": "compare", "other_column": "absent", "operator": "eq"},
            "declared other_column",
        ),
        (
            {"kind": "compare", "other_column": "age", "operator": "eval"},
            "requires operator",
        ),
    ],
)
def test_quality_rule_contract_rejects_ambiguous_configuration(
    rule: dict, match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        normalize_rules([{"id": "check", "column": "age", **rule}], {"age": {}})


@pytest.mark.parametrize("raw", [None, {}, "required", [None]])
def test_quality_rule_contract_requires_rule_objects(raw: object) -> None:
    with pytest.raises(ValueError):
        normalize_rules(raw, {"age": {}})


def test_quality_rule_contract_rejects_duplicate_ids() -> None:
    rule = {"id": "same", "column": "age", "kind": "required"}
    with pytest.raises(ValueError, match="Duplicate"):
        normalize_rules([rule, rule], {"age": {}})


@pytest.mark.parametrize(
    "payload",
    [
        '{"rules":[{"id":"adult","kind":"range","column":"age","min":200}],"rules":[]}',
        '{"rules":[{"id":"adult","kind":"range","column":"age","min":200,"min":0}]}',
        '{"rules":[{"id":"adult","kind":"required","column":"age","severity":"block","severity":"warn"}]}',
        '{"rules":[{"id":"adult","kind":"range","column":"age","min":NaN}]}',
    ],
)
def test_invalid_json_contract_cannot_silently_disable_gate_rules(
    tmp_path: Path, payload: str
) -> None:
    config = tmp_path / "contract.json"
    config.write_text(payload)
    output = tmp_path / "out"
    with pytest.raises(ValueError, match="Invalid contract JSON"):
        build_data_quality_gate_artifacts(
            output_dir=output, contract_json=config, drift_strength=0
        )
    assert not (output / "run_manifest.json").exists()
    assert not (output / "rule_results.json").exists()


def test_quality_rules_support_large_integer_bounds_and_values() -> None:
    large = 10**500
    frame = pd.DataFrame({"value": [large, large - 1]}, dtype=object)
    result = _rules_result(
        frame,
        [
            {"id": "large-bound", "kind": "range", "column": "value", "min": large},
            {
                "id": "large-value",
                "kind": "allowed_values",
                "column": "value",
                "values": [large],
            },
        ],
    )
    assert all(row["failed_row_positions"] == [1] for row in result["rules"])


def test_quality_rules_preserve_scalar_types_and_bound_failure_positions() -> None:
    frame = pd.DataFrame(
        {"value": [True, "1", float("inf"), float("nan"), *([-1] * 20)]}, dtype=object
    )
    result = _rules_result(
        frame, [{"id": "range", "column": "value", "kind": "range", "min": 0}]
    )
    row = result["rules"][0]
    assert row["failure_counts"] == {
        "invalid_type": 3,
        "missing_value": 1,
        "out_of_range": 20,
    }
    assert row["failed_row_positions"] == list(range(10))
    assert row["omitted_failure_positions"] == 14
    allowed = _rules_result(
        pd.DataFrame({"v": [True, 1, "1"]}, dtype=object),
        [
            {"id": "allow", "kind": "allowed_values", "column": "v", "values": [1]},
        ],
    )
    assert allowed["rules"][0]["failed_row_positions"] == [0, 2]


@pytest.mark.parametrize(
    "operator,passed",
    [("eq", 1), ("ne", 2), ("lt", 1), ("le", 2), ("gt", 1), ("ge", 2)],
)
def test_quality_comparison_operators(operator: str, passed: int) -> None:
    result = _rules_result(
        pd.DataFrame({"a": [1, 2, 3], "b": [2, 2, 2]}),
        [
            {
                "id": "compare",
                "kind": "compare",
                "column": "a",
                "other_column": "b",
                "operator": operator,
            },
        ],
    )
    assert result["rules"][0]["passed_count"] == passed


def test_quality_rules_distinguish_missing_empty_and_null_only_inputs() -> None:
    rules = normalize_rules(
        [{"id": "age", "column": "age", "kind": "range", "min": 0, "on_null": "skip"}],
        {"age": {}},
    )
    missing = evaluate_rules(pd.DataFrame({"other": [1, 2]}), rules)["rules"][0]
    assert missing["status"] == "missing"
    assert missing["missing_columns"] == ["age"]
    assert missing["checked_count"] == 0 and missing["skipped_count"] == 2
    for frame in (pd.DataFrame({"age": []}), pd.DataFrame({"age": [None, None]})):
        row = evaluate_rules(frame, rules)["rules"][0]
        assert row["status"] == "skipped" and row["pass_rate"] is None
        assert row["checked_count"] == 0 and row["skipped_count"] == len(frame)


def test_quality_rule_evidence_is_bound_to_inputs_and_controls_gate(
    tmp_path: Path,
) -> None:
    config = tmp_path / "contract.json"
    config.write_text(
        json.dumps(
            {
                "rules": [
                    {
                        "id": "adult",
                        "kind": "range",
                        "column": "age",
                        "min": 200,
                        "severity": "warn",
                    },
                ]
            }
        )
    )
    output = tmp_path / "evidence"
    build_data_quality_gate_artifacts(
        output_dir=output, contract_json=config, drift_strength=0
    )
    decision = json.loads((output / "gate_decision.json").read_text())
    assert decision["decision"] == "manual-review"
    assert any("rule adult" in warning for warning in decision["warnings"])
    receipt_bytes = (output / "rule_results.json").read_bytes()
    receipt = json.loads(receipt_bytes)
    assert receipt["schema"] == "agilab.app.data_quality_gate.rule_results.v1"
    assert receipt["rules"][0]["failed_count"] == 220
    for ref in receipt["inputs"].values():
        data = (output / ref["path"]).read_bytes()
        assert len(data) == ref["bytes"]
        assert hashlib.sha256(data).hexdigest() == ref["sha256"]
    manifest = json.loads((output / "run_manifest.json").read_text())
    assert (
        manifest["artifacts"]["rule_results"]["sha256"]
        == hashlib.sha256(receipt_bytes).hexdigest()
    )
    assert "adult" in (output / "data_quality_report.md").read_text()
    assert "<td>adult</td>" in (output / "data_quality_dashboard.html").read_text()
    second = tmp_path / "replay"
    build_data_quality_gate_artifacts(
        output_dir=second, contract_json=config, drift_strength=0
    )
    assert (second / "rule_results.json").read_bytes() == receipt_bytes
    # A reused output directory must not retain results from an earlier contract.
    build_data_quality_gate_artifacts(output_dir=output, drift_strength=0)
    assert json.loads((output / "rule_results.json").read_text())["rules"] == []


@pytest.mark.parametrize(
    "severity,expected", [("block", "block"), ("warn", "manual-review")]
)
def test_unevaluated_quality_rule_prevents_silent_promotion(
    tmp_path: Path, severity: str, expected: str
) -> None:
    config = tmp_path / "contract.json"
    config.write_text(
        json.dumps(
            {
                "columns": {"missing": {"kind": "numeric", "required": False}},
                "rules": [
                    {
                        "id": "missing",
                        "kind": "range",
                        "column": "missing",
                        "min": 0,
                        "severity": severity,
                    },
                ],
                "allow_unexpected_columns": True,
            }
        )
    )
    summary = build_data_quality_gate_artifacts(
        output_dir=tmp_path / "out", contract_json=config, drift_strength=0
    )
    assert summary["decision"] == expected


def test_data_quality_gate_worker_rejects_absolute_output_outside_share(
    tmp_path: Path,
) -> None:
    env = _make_env(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "important.txt"
    marker.write_text("keep", encoding="utf-8")
    worker = DataQualityGateWorker()
    worker.env = env
    worker.args = DataQualityGateArgs.model_construct(
        data_out=outside,
        reset_target=True,
    )

    with pytest.raises(ValueError, match="active share root"):
        worker.start()

    assert marker.read_text(encoding="utf-8") == "keep"


def test_data_quality_gate_manager_rejects_reset_containing_input(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    input_root = Path(env.AGI_LOCAL_SHARE) / "data_quality_gate/input"
    input_root.mkdir(parents=True)
    baseline = input_root / "baseline.csv"
    baseline.write_text("customer_id,target\n1,0\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must not overlap protected input"):
        DataQualityGate(
            env,
            args=DataQualityGateArgs(
                data_out="data_quality_gate",
                baseline_csv="data_quality_gate/input/baseline.csv",
                reset_target=True,
            ),
        )

    assert baseline.read_text(encoding="utf-8") == "customer_id,target\n1,0\n"


def test_data_quality_gate_worker_rejects_reset_containing_input(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    input_root = Path(env.AGI_LOCAL_SHARE) / "data_quality_gate/input"
    input_root.mkdir(parents=True)
    baseline = input_root / "baseline.csv"
    baseline.write_text("customer_id,target\n1,0\n", encoding="utf-8")
    worker = DataQualityGateWorker()
    worker.env = env
    worker.args = DataQualityGateArgs(
        data_out="data_quality_gate",
        baseline_csv="data_quality_gate/input/baseline.csv",
        reset_target=True,
    )

    with pytest.raises(ValueError, match="must not overlap protected input"):
        worker.start()

    assert baseline.read_text(encoding="utf-8") == "customer_id,target\n1,0\n"


@pytest.mark.parametrize("surface", ("manager", "worker"))
def test_data_quality_gate_validates_absolute_inputs_with_canonical_resolver(
    monkeypatch, tmp_path: Path, surface: str
) -> None:
    env = _make_env(tmp_path)
    outside = tmp_path / "outside.csv"
    calls: list[Path] = []

    def _resolve_share_input_path(value: str | Path) -> Path:
        candidate = Path(value)
        calls.append(candidate)
        if candidate.is_absolute() and not candidate.is_relative_to(
            Path(env.AGI_LOCAL_SHARE)
        ):
            raise ValueError("input escapes share")
        return env.resolve_share_path(candidate)

    env.resolve_share_input_path = _resolve_share_input_path
    args = DataQualityGateArgs.model_construct(
        data_out=Path("data_quality_gate/evidence"),
        baseline_csv=outside,
        reset_target=False,
    )

    with pytest.raises(ValueError, match="input escapes share"):
        if surface == "manager":
            # Patch the globals used by this exact class method. Other broad-suite
            # tests reload compatibility modules, so the current sys.modules entry
            # can be a different module object from DataQualityGate.__init__'s
            # defining globals.
            monkeypatch.setitem(
                DataQualityGate.__init__.__globals__,
                "ensure_defaults",
                lambda args, **_: args,
            )
            DataQualityGate(env, args=args)
        else:
            worker = DataQualityGateWorker()
            worker.env = env
            worker.args = args
            worker.start()

    assert calls == [outside]


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
