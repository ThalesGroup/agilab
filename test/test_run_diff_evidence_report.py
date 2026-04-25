from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


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
