from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path("tools/kpi_evidence_bundle.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("kpi_evidence_bundle_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_bundle_passes_static_public_evidence_contracts() -> None:
    module = _load_module()

    bundle = module.build_bundle(run_hf_smoke=False)

    assert bundle["kpi"] == "Overall public evaluation"
    assert bundle["supported_score"] == "3.6 / 5"
    assert bundle["baseline_review_score"] == "3.2 / 5"
    assert bundle["status"] == "pass"
    assert bundle["summary"]["hf_smoke_executed"] is False
    assert bundle["summary"]["score_components"] == {
        "Ease of adoption": "3.5 / 5",
        "Research experimentation": "4.0 / 5",
        "Engineering prototyping": "4.0 / 5",
        "Production readiness": "3.0 / 5",
    }
    assert bundle["summary"]["score_formula"] == "(3.5 + 4.0 + 4.0 + 3.0) / 4 = 3.625"
    check_ids = {check["id"] for check in bundle["checks"]}
    assert check_ids == {
        "workflow_compatibility_report",
        "newcomer_first_proof_contract",
        "run_manifest_contract",
        "multi_app_dag_report_contract",
        "global_pipeline_dag_report_contract",
        "global_pipeline_execution_plan_report_contract",
        "global_pipeline_runner_state_report_contract",
        "global_pipeline_dispatch_state_report_contract",
        "global_pipeline_app_dispatch_smoke_report_contract",
        "reduce_contract_adoption_guardrail",
        "reduce_contract_benchmark",
        "hf_space_smoke_contract",
        "web_ui_robot_contract",
        "production_readiness_report_contract",
        "docs_mirror_stamp",
        "public_docs_evidence_links",
    }


def test_workflow_compatibility_report_requires_hf_demo_validated() -> None:
    module = _load_module()

    check = module._check_workflow_compatibility_report(Path.cwd())

    assert check["status"] == "pass"
    statuses = check["details"]["required_public_statuses"]["actual_statuses"]
    assert statuses["agilab-hf-demo"] == "validated"
    assert "workflow_evidence_commands" in check["details"]["check_ids"]
    assert "run_manifest_evidence_ingestion" in check["details"]["check_ids"]
    assert check["details"]["run_manifest_evidence_ingestion"]["loaded_manifest_count"] == 0


def test_newcomer_first_proof_contract_reports_guided_wizard() -> None:
    module = _load_module()

    check = module._check_newcomer_first_proof_contract(Path.cwd())

    assert check["status"] == "pass"
    assert check["details"]["labels"] == ["preinit smoke", "source ui smoke"]
    wizard = check["details"]["wizard"]
    assert wizard["recommended_path_id"] == "source-checkout-first-proof"
    assert wizard["actionable_route_ids"] == ["source-checkout-first-proof"]
    assert wizard["documented_route_ids"] == ["notebook-quickstart", "published-package-route"]
    assert wizard["compatibility_status"] == "validated"
    assert wizard["compatibility_report_status"] == "pass"
    assert wizard["run_manifest_filename"] == "run_manifest.json"
    assert wizard["remediation_status"] == "missing"
    assert "tools/compatibility_report.py --manifest" in wizard["evidence_commands"][1]
    assert wizard["steps"] == ["PROJECT", "ORCHESTRATE", "ANALYSIS"]


def test_run_manifest_contract_reports_stable_schema() -> None:
    module = _load_module()

    check = module._check_run_manifest_contract(Path.cwd())

    assert check["status"] == "pass"
    assert check["details"]["schema_version"] == 1
    assert check["details"]["kind"] == "agilab.run_manifest"
    assert check["details"]["filename"] == "run_manifest.json"
    assert check["details"]["path_id"] == "source-checkout-first-proof"
    assert check["details"]["validation_labels"] == [
        "proof_steps",
        "target_seconds",
        "recommended_project",
    ]


def test_multi_app_dag_report_contract_reports_cross_app_handoff() -> None:
    module = _load_module()

    check = module._check_multi_app_dag_report(Path.cwd())

    assert check["status"] == "pass"
    assert check["details"]["dag_path"] == "docs/source/data/multi_app_dag_sample.json"
    assert check["details"]["summary"]["execution_order"] == [
        "queue_baseline",
        "relay_followup",
    ]
    assert check["details"]["summary"]["cross_app_edge_count"] == 1
    assert "multi_app_dag_artifact_handoffs" in check["details"]["check_ids"]


def test_global_pipeline_dag_report_contract_reports_read_only_graph() -> None:
    module = _load_module()

    check = module._check_global_pipeline_dag_report(Path.cwd())

    assert check["status"] == "pass"
    assert check["details"]["dag_path"] == "docs/source/data/multi_app_dag_sample.json"
    assert check["details"]["summary"]["runner_status"] == "not_executed"
    assert check["details"]["summary"]["app_node_count"] == 2
    assert check["details"]["summary"]["app_step_node_count"] == 8
    assert check["details"]["summary"]["local_pipeline_edge_count"] == 6
    assert check["details"]["summary"]["cross_app_edge_count"] == 1
    assert "global_pipeline_dag_graph_shape" in check["details"]["check_ids"]


def test_global_pipeline_execution_plan_report_contract_reports_pending_units() -> None:
    module = _load_module()

    check = module._check_global_pipeline_execution_plan_report(Path.cwd())

    assert check["status"] == "pass"
    assert check["details"]["dag_path"] == "docs/source/data/multi_app_dag_sample.json"
    assert check["details"]["summary"]["runner_status"] == "not_executed"
    assert check["details"]["summary"]["unit_count"] == 2
    assert check["details"]["summary"]["pending_count"] == 2
    assert check["details"]["summary"]["ready_unit_ids"] == ["queue_baseline"]
    assert check["details"]["summary"]["blocked_unit_ids"] == ["relay_followup"]
    assert "global_pipeline_execution_plan_state" in check["details"]["check_ids"]


def test_global_pipeline_runner_state_report_contract_reports_dispatch_state() -> None:
    module = _load_module()

    check = module._check_global_pipeline_runner_state_report(Path.cwd())

    assert check["status"] == "pass"
    assert check["details"]["dag_path"] == "docs/source/data/multi_app_dag_sample.json"
    assert check["details"]["summary"]["runner_mode"] == "read_only_preview"
    assert check["details"]["summary"]["run_status"] == "not_started"
    assert check["details"]["summary"]["unit_count"] == 2
    assert check["details"]["summary"]["runnable_count"] == 1
    assert check["details"]["summary"]["blocked_count"] == 1
    assert check["details"]["summary"]["runnable_unit_ids"] == ["queue_baseline"]
    assert check["details"]["summary"]["blocked_unit_ids"] == ["relay_followup"]
    assert check["details"]["summary"]["retry_policy_count"] == 2
    assert check["details"]["summary"]["partial_rerun_record_count"] == 2
    assert check["details"]["summary"]["operator_state_count"] == 2
    assert "global_pipeline_runner_state_operator_ui" in check["details"]["check_ids"]


def test_global_pipeline_dispatch_state_report_contract_reports_persistence() -> None:
    module = _load_module()

    check = module._check_global_pipeline_dispatch_state_report(Path.cwd())

    assert check["status"] == "pass"
    assert check["details"]["dag_path"] == "docs/source/data/multi_app_dag_sample.json"
    assert check["details"]["summary"]["run_status"] == "in_progress"
    assert check["details"]["summary"]["persistence_format"] == "json"
    assert check["details"]["summary"]["round_trip_ok"] is True
    assert check["details"]["summary"]["unit_count"] == 2
    assert check["details"]["summary"]["completed_unit_ids"] == ["queue_baseline"]
    assert check["details"]["summary"]["runnable_unit_ids"] == ["relay_followup"]
    assert check["details"]["summary"]["blocked_unit_ids"] == []
    assert check["details"]["summary"]["available_artifact_ids"] == ["queue_metrics"]
    assert check["details"]["summary"]["retry_counter_count"] == 2
    assert check["details"]["summary"]["partial_rerun_flag_count"] == 2
    assert "global_pipeline_dispatch_state_round_trip" in check["details"]["check_ids"]


def test_global_pipeline_app_dispatch_smoke_report_contract_executes_real_queue() -> None:
    module = _load_module()

    check = module._check_global_pipeline_app_dispatch_smoke_report(Path.cwd())

    assert check["status"] == "pass"
    assert check["executed"] is True
    assert check["details"]["dag_path"] == "docs/source/data/multi_app_dag_sample.json"
    assert check["details"]["summary"]["run_status"] == "in_progress"
    assert check["details"]["summary"]["persistence_format"] == "json"
    assert check["details"]["summary"]["round_trip_ok"] is True
    assert check["details"]["summary"]["unit_count"] == 2
    assert check["details"]["summary"]["completed_unit_ids"] == ["queue_baseline"]
    assert check["details"]["summary"]["runnable_unit_ids"] == ["relay_followup"]
    assert check["details"]["summary"]["real_executed_unit_ids"] == ["queue_baseline"]
    assert check["details"]["summary"]["readiness_only_unit_ids"] == ["relay_followup"]
    assert check["details"]["summary"]["real_execution_scope"] == "first_unit_only"
    assert check["details"]["summary"]["packets_generated"] > 0
    assert "queue_metrics" in check["details"]["summary"]["available_artifact_ids"]
    assert "global_pipeline_app_dispatch_smoke_real_queue" in check["details"]["check_ids"]


def test_reduce_contract_adoption_guardrail_reports_template_exemption() -> None:
    module = _load_module()

    check = module._check_reduce_contract_adoption_guardrail(Path.cwd())

    assert check["status"] == "pass"
    assert check["details"]["checked_app_count"] == 6
    assert check["details"]["template_only_exemptions"] == {
        "mycode_project": "starter template with placeholder worker hooks and no concrete merge output",
    }
    assert check["details"]["failures"] == []


def test_optional_hf_smoke_run_is_explicit(monkeypatch) -> None:
    module = _load_module()

    @dataclass(frozen=True)
    class _FakeCheck:
        label: str
        success: bool
        duration_seconds: float
        detail: str
        url: str | None = None

    @dataclass(frozen=True)
    class _FakeRoute:
        label: str

    @dataclass(frozen=True)
    class _FakeSummary:
        success: bool
        total_duration_seconds: float
        target_seconds: float
        within_target: bool
        checks: list[_FakeCheck]

    class _FakeHfSmoke:
        DEFAULT_SPACE_ID = "jpmorard/agilab"
        DEFAULT_SPACE_URL = "https://jpmorard-agilab.hf.space"

        @staticmethod
        def route_specs():
            return [
                _FakeRoute(label)
                for label in (
                    "streamlit health",
                    "base app",
                    "flight project",
                    "flight view_maps",
                    "flight view_maps_network",
                )
            ]

        @staticmethod
        def check_public_app_tree():
            return None

        @staticmethod
        def run_smoke():
            return _FakeSummary(
                success=True,
                total_duration_seconds=1.0,
                target_seconds=30.0,
                within_target=True,
                checks=[_FakeCheck("public app tree", True, 1.0, "ok")],
            )

    original_loader = module._load_tool_module

    def _load_tool_module(repo_root, name):
        if name == "hf_space_smoke":
            return _FakeHfSmoke
        return original_loader(repo_root, name)

    monkeypatch.setattr(module, "_load_tool_module", _load_tool_module)

    bundle = module.build_bundle(run_hf_smoke=True)

    assert bundle["status"] == "pass"
    assert bundle["summary"]["hf_smoke_executed"] is True
    check = next(check for check in bundle["checks"] if check["id"] == "hf_space_smoke_run")
    assert check["executed"] is True
    assert check["details"]["checks"][0]["label"] == "public app tree"


def test_main_emits_json_and_returns_success(capsys) -> None:
    module = _load_module()

    exit_code = module.main(["--compact"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["kpi"] == "Overall public evaluation"
    assert payload["status"] == "pass"
    assert payload["summary"]["failed"] == 0
