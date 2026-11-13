from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


REPORT_PATH = Path("tools/run_diff_evidence_report.py").resolve()
CORE_PATH = Path("src/agilab/run_diff_evidence.py").resolve()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_run_diff_evidence_report_passes(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "run_diff_evidence_report_test_module")

    report = module.build_report(
        repo_root=Path.cwd(),
        output_path=tmp_path / "run_diff_evidence.json",
    )

    assert report["report"] == "Run-diff evidence report"
    assert report["status"] == "pass"
    assert report["summary"]["schema"] == "agilab.run_diff_evidence.v1"
    assert report["summary"]["run_status"] == "diff_ready"
    assert report["summary"]["execution_mode"] == "run_diff_evidence_only"
    assert report["summary"]["check_added_count"] == 1
    assert report["summary"]["check_removed_count"] == 0
    assert report["summary"]["check_status_changed_count"] == 0
    assert report["summary"]["check_summary_changed_count"] == 1
    assert report["summary"]["artifact_added_count"] == 2
    assert report["summary"]["artifact_removed_count"] == 0
    assert report["summary"]["manifest_artifact_delta"] == 1
    assert report["summary"]["counterfactual_count"] == 2
    assert report["summary"]["network_probe_count"] == 0
    assert report["summary"]["live_execution_count"] == 0
    assert report["summary"]["command_execution_count"] == 0
    assert report["summary"]["round_trip_ok"] is True
    assert {check["id"] for check in report["checks"]} == {
        "run_diff_evidence_schema",
        "run_diff_evidence_check_delta",
        "run_diff_evidence_artifact_delta",
        "run_diff_evidence_manifest_delta",
        "run_diff_evidence_counterfactuals",
        "run_diff_evidence_no_execution",
        "run_diff_evidence_persistence",
        "run_diff_evidence_docs_reference",
    }


def test_run_diff_evidence_persists_material_deltas(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "run_diff_evidence_json_test_module")
    output_path = tmp_path / "run_diff_evidence.json"

    report = module.build_report(repo_root=Path.cwd(), output_path=output_path)

    assert report["status"] == "pass"
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "agilab.run_diff_evidence.v1"
    assert payload["run_status"] == "diff_ready"
    assert payload["execution_mode"] == "run_diff_evidence_only"
    assert [check["id"] for check in payload["diff"]["checks_added"]] == [
        "data_connector_runtime_adapters_report_contract"
    ]
    assert sorted(artifact["id"] for artifact in payload["diff"]["artifacts_added"]) == [
        "forecast_metrics",
        "runtime_adapter_bindings",
    ]
    assert payload["manifest"]["same_path_id"] is True
    assert payload["manifest"]["status_changed"] is False
    assert payload["manifest"]["validation_labels_added"] == [
        "runtime_adapter_contract"
    ]
    assert sorted(row["id"] for row in payload["counterfactuals"]) == [
        "single_sample_multi_app_dag",
        "without_runtime_adapter_contract",
    ]
    assert payload["provenance"]["executes_commands"] is False
    assert payload["provenance"]["executes_network_probe"] is False
    assert payload["provenance"]["safe_for_public_evidence"] is True
    assert payload["provenance"]["uses_static_sample_evidence"] is True


def test_run_diff_core_compares_custom_inputs() -> None:
    module = _load_module(CORE_PATH, "run_diff_evidence_core_test_module")

    payload = module.build_run_diff_evidence(
        baseline_bundle={
            "status": "pass",
            "supported_score": "3.8 / 5",
            "checks": [{"id": "stable_check", "status": "pass"}],
        },
        candidate_bundle={
            "status": "fail",
            "supported_score": "3.7 / 5",
            "checks": [{"id": "stable_check", "status": "fail"}],
        },
        baseline_manifest={"path_id": "proof", "status": "pass", "artifacts": []},
        candidate_manifest={"path_id": "proof", "status": "fail", "artifacts": []},
        baseline_artifacts=[],
        candidate_artifacts=[],
    )

    assert payload["summary"]["bundle_status_changed"] is True
    assert payload["summary"]["supported_score_changed"] is True
    assert payload["summary"]["check_added_count"] == 0
    assert payload["summary"]["check_status_changed_count"] == 1
    assert payload["summary"]["manifest_status_changed"] is True
    assert payload["summary"]["counterfactual_count"] == 0
    assert payload["provenance"]["uses_static_sample_evidence"] is False
    assert payload["provenance"]["safe_for_public_evidence"] is True

    assert "Bundle status changed: pass -> fail." in payload["narrative"]
    assert "KPI supported score changed: 3.8 / 5 -> 3.7 / 5." in payload["narrative"]
    assert (
        "Check evidence: 0 added, 0 removed, 1 status changes, 0 summary changes."
        in payload["narrative"]
    )
    assert "Artifact evidence: 0 added, 0 removed." in payload["narrative"]
    assert (
        "Manifest status changed: pass -> fail; artifact count: 0 -> 0."
        in payload["narrative"]
    )


def test_run_diff_core_handles_malformed_helper_inputs() -> None:
    module = _load_module(CORE_PATH, "run_diff_evidence_helpers_test_module")

    assert module._checks_by_id({"checks": "bad"}) == {}
    assert module._artifacts_by_id({"artifacts": "bad"}) == {}
    assert module._artifacts_by_id(
        {
            "artifacts": [
                "bad",
                {"name": "by-name"},
                {"path": "by-path"},
                {"artifact_id": "by-artifact-id"},
            ]
        }
    ) == {
        "by-name": {"name": "by-name"},
        "by-path": {"path": "by-path"},
        "by-artifact-id": {"artifact_id": "by-artifact-id"},
    }
    assert module._artifact_id({}) == ""
    assert module._manifest_artifact_count({"artifacts": "bad", "summary": {"artifact_count": 4}}) == 4
    assert module._manifest_artifact_count({"artifacts": "bad", "summary": "bad"}) == 0
    assert module._validation_labels({"validations": "bad"}) == set()
    assert module._validation_labels({"validations": ["bad", {"label": "smoke"}]}) == {"smoke"}


def test_run_diff_sample_builder_uses_packaged_inputs() -> None:
    module = _load_module(CORE_PATH, "run_diff_evidence_sample_test_module")

    payload = module.build_sample_run_diff()

    assert payload["schema"] == "agilab.run_diff_evidence.v1"
    assert payload["summary"]["artifact_added_count"] == 2
    assert payload["provenance"]["uses_static_sample_evidence"] is True


@pytest.mark.parametrize("empty_artifacts", [[], {}], ids=["list", "mapping"])
def test_run_diff_persistence_preserves_explicit_empty_evidence(
    tmp_path: Path, empty_artifacts
) -> None:
    module = _load_module(CORE_PATH, "run_diff_evidence_empty_test_module")
    output_path = tmp_path / "empty-run-diff-evidence.json"

    proof = module.persist_run_diff_evidence(
        output_path=output_path,
        baseline_bundle={},
        candidate_bundle={},
        baseline_manifest={},
        candidate_manifest={},
        baseline_artifacts=empty_artifacts,
        candidate_artifacts=empty_artifacts,
    )
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert proof["ok"] is True
    assert proof["round_trip_ok"] is True
    assert payload == proof["state"] == proof["reloaded_state"]
    assert payload["provenance"]["uses_static_sample_evidence"] is False
    assert payload["provenance"]["safe_for_public_evidence"] is True
    assert payload["bundle"] == {
        "baseline_status": "unknown",
        "candidate_status": "unknown",
        "baseline_supported_score": "",
        "candidate_supported_score": "",
        "baseline_total": None,
        "candidate_total": None,
    }
    assert all(not rows for rows in payload["diff"].values())
    assert payload["counterfactuals"] == []
    assert payload["manifest"]["baseline_artifact_count"] == 0
    assert payload["manifest"]["candidate_artifact_count"] == 0
    assert payload["manifest"]["validation_labels_added"] == []
    assert payload["manifest"]["validation_labels_removed"] == []
    assert payload["manifest"]["baseline_status"] == "unknown"
    assert payload["manifest"]["candidate_status"] == "unknown"
    assert payload["narrative"] == [
        "Bundle status unchanged: unknown -> unknown.",
        "KPI supported score comparison unavailable "
        "(baseline: unavailable; candidate: unavailable).",
        "Check evidence: 0 added, 0 removed, 0 status changes, 0 summary changes.",
        "Artifact evidence: 0 added, 0 removed.",
        "Manifest status unchanged: unknown -> unknown; artifact count: 0 -> 0.",
    ]


def test_run_diff_report_reads_empty_candidate_json_as_removal(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "run_diff_evidence_custom_json_test_module")
    inputs = {
        "baseline_bundle": {
            "status": "pass",
            "supported_score": "4 / 5",
            "checks": [{"id": "custom_check", "status": "pass"}],
        },
        "candidate_bundle": {},
        "baseline_manifest": {
            "path_id": "custom-proof",
            "status": "pass",
            "artifacts": [{"id": "custom_artifact"}],
            "validations": [{"label": "custom_validation", "status": "pass"}],
        },
        "candidate_manifest": {},
        "baseline_artifacts": [{"id": "custom_artifact", "path": "custom.json"}],
        "candidate_artifacts": [],
    }
    input_paths = {}
    for name, evidence in inputs.items():
        path = tmp_path / f"{name.replace('_', '-')}-evidence.json"
        path.write_text(json.dumps(evidence), encoding="utf-8")
        input_paths[f"{name}_path"] = path
    output_path = tmp_path / "candidate-removal-run-diff-evidence.json"

    report = module.build_report(
        repo_root=Path.cwd(), output_path=output_path, **input_paths
    )
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    # The report's checks qualify the packaged sample; custom deltas still persist.
    assert report["status"] == "fail"
    assert report["summary"]["round_trip_ok"] is True
    assert payload["provenance"]["uses_static_sample_evidence"] is False
    assert payload["summary"]["check_added_count"] == 0
    assert payload["summary"]["check_removed_count"] == 1
    assert payload["summary"]["artifact_added_count"] == 0
    assert payload["summary"]["artifact_removed_count"] == 1
    assert payload["summary"]["manifest_artifact_delta"] == -1
    assert [row["id"] for row in payload["diff"]["checks_removed"]] == ["custom_check"]
    assert payload["diff"]["artifacts_removed"] == inputs["baseline_artifacts"]
    assert payload["manifest"]["validation_labels_removed"] == ["custom_validation"]
    assert payload["counterfactuals"] == []
    assert payload["narrative"] == [
        "Bundle status changed: pass -> unknown.",
        "KPI supported score comparison unavailable "
        "(baseline: 4 / 5; candidate: unavailable).",
        "Check evidence: 0 added, 1 removed, 0 status changes, 0 summary changes.",
        "Artifact evidence: 0 added, 1 removed.",
        "Manifest status changed: pass -> unknown; artifact count: 1 -> 0.",
    ]


@pytest.mark.parametrize(
    ("baseline_score", "candidate_score", "score_narrative"),
    [
        (
            "3.8 / 5",
            "3.8 / 5",
            "KPI supported score unchanged: 3.8 / 5 -> 3.8 / 5.",
        ),
        (
            None,
            "3.7 / 5",
            "KPI supported score comparison unavailable "
            "(baseline: unavailable; candidate: 3.7 / 5).",
        ),
        (
            "",
            "",
            "KPI supported score comparison unavailable "
            "(baseline: unavailable; candidate: unavailable).",
        ),
        (
            "   ",
            "",
            "KPI supported score comparison unavailable "
            "(baseline: unavailable; candidate: unavailable).",
        ),
    ],
)
def test_run_diff_narrative_reports_unchanged_failure_and_score_availability(
    baseline_score, candidate_score, score_narrative: str
) -> None:
    module = _load_module(CORE_PATH, "run_diff_evidence_score_test_module")

    payload = module.build_run_diff_evidence(
        baseline_bundle={"status": "fail", "supported_score": baseline_score},
        candidate_bundle={"status": "fail", "supported_score": candidate_score},
        baseline_manifest={"status": "fail"},
        candidate_manifest={"status": "fail"},
        baseline_artifacts=[],
        candidate_artifacts=[],
    )

    assert "Bundle status unchanged: fail -> fail." in payload["narrative"]
    assert score_narrative in payload["narrative"]
    assert (
        "Manifest status unchanged: fail -> fail; artifact count: 0 -> 0."
        in payload["narrative"]
    )
    assert not any(
        "stable" in statement or "gain" in statement
        for statement in payload["narrative"]
    )


def test_run_diff_default_persistence_matches_sample_builder(tmp_path: Path) -> None:
    module = _load_module(CORE_PATH, "run_diff_evidence_default_provenance_test_module")
    output_path = tmp_path / "default-sample-run-diff-evidence.json"

    proof = module.persist_run_diff_evidence(output_path=output_path)
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert proof["ok"] is True
    assert proof["round_trip_ok"] is True
    assert (
        payload
        == proof["state"]
        == proof["reloaded_state"]
        == module.build_sample_run_diff()
    )
    assert payload["provenance"]["uses_static_sample_evidence"] is True
    assert payload["provenance"]["safe_for_public_evidence"] is True


@pytest.mark.parametrize(
    "defaulted_input",
    [
        "baseline_bundle",
        "candidate_bundle",
        "baseline_manifest",
        "candidate_manifest",
        "baseline_artifacts",
        "candidate_artifacts",
    ],
)
def test_run_diff_mixed_persistence_records_each_sample_default(
    tmp_path: Path, defaulted_input: str
) -> None:
    module = _load_module(CORE_PATH, "run_diff_evidence_mixed_provenance_test_module")
    inputs = {
        "baseline_bundle": {},
        "candidate_bundle": {},
        "baseline_manifest": {},
        "candidate_manifest": {},
        "baseline_artifacts": [],
        "candidate_artifacts": [],
    }
    inputs[defaulted_input] = None
    output_path = tmp_path / "mixed-sample-run-diff-evidence.json"

    proof = module.persist_run_diff_evidence(output_path=output_path, **inputs)
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert proof["ok"] is True
    assert proof["round_trip_ok"] is True
    assert payload == proof["state"] == proof["reloaded_state"]
    assert payload["provenance"]["uses_static_sample_evidence"] is True


def test_run_diff_explicit_sample_inputs_keep_caller_provenance(tmp_path: Path) -> None:
    module = _load_module(CORE_PATH, "run_diff_evidence_caller_provenance_test_module")
    inputs = {
        "baseline_bundle": module.sample_baseline_bundle(),
        "candidate_bundle": module.sample_candidate_bundle(),
        "baseline_manifest": module.sample_baseline_manifest(),
        "candidate_manifest": module.sample_candidate_manifest(),
        "baseline_artifacts": module.sample_baseline_artifacts(),
        "candidate_artifacts": module.sample_candidate_artifacts(),
    }
    expected = module.build_run_diff_evidence(**inputs)
    output_path = tmp_path / "caller-supplied-sample-run-diff-evidence.json"

    proof = module.persist_run_diff_evidence(output_path=output_path, **inputs)
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert proof["ok"] is True
    assert proof["round_trip_ok"] is True
    assert payload == proof["state"] == proof["reloaded_state"] == expected
    assert payload["provenance"]["uses_static_sample_evidence"] is False
    # Preserved metadata does not validate arbitrary caller JSON for public use.
    assert payload["provenance"]["safe_for_public_evidence"] is True


@pytest.mark.parametrize(
    ("baseline_bundle", "candidate_bundle", "score_narrative"),
    [
        (
            {"supported_score": 0},
            {},
            "KPI supported score comparison unavailable "
            "(baseline: 0; candidate: unavailable).",
        ),
        (
            {},
            {"supported_score": 0},
            "KPI supported score comparison unavailable "
            "(baseline: unavailable; candidate: 0).",
        ),
    ],
)
def test_run_diff_narrative_distinguishes_zero_from_missing_score(
    baseline_bundle, candidate_bundle, score_narrative: str
) -> None:
    module = _load_module(CORE_PATH, "run_diff_evidence_zero_score_test_module")

    payload = module.build_run_diff_evidence(
        baseline_bundle=baseline_bundle,
        candidate_bundle=candidate_bundle,
        baseline_manifest={},
        candidate_manifest={},
        baseline_artifacts=[],
        candidate_artifacts=[],
    )

    assert payload["summary"]["supported_score_changed"] is True
    assert score_narrative in payload["narrative"]


def test_run_diff_narrative_separates_equal_scores_from_changed_status() -> None:
    module = _load_module(CORE_PATH, "run_diff_evidence_equal_score_test_module")

    payload = module.build_run_diff_evidence(
        baseline_bundle={"status": "pass", "supported_score": 0},
        candidate_bundle={"status": "fail", "supported_score": 0},
        baseline_manifest={},
        candidate_manifest={},
        baseline_artifacts=[],
        candidate_artifacts=[],
    )

    assert payload["summary"]["bundle_status_changed"] is True
    assert payload["summary"]["supported_score_changed"] is False
    assert "Bundle status changed: pass -> fail." in payload["narrative"]
    assert "KPI supported score unchanged: 0 -> 0." in payload["narrative"]
