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
    assert bundle["supported_score"] == module.SUPPORTED_OVERALL_SCORE
    assert bundle["baseline_review_score"] == module.BASELINE_REVIEW_SCORE
    assert bundle["status"] == "pass"
    assert bundle["summary"]["hf_smoke_executed"] is False
    assert bundle["summary"]["score_components"] == {
        name: f"{score:.1f} / 5"
        for name, score in module.KPI_COMPONENT_SCORES.items()
    }
    assert bundle["summary"]["strategic_potential_score"] == module.STRATEGIC_POTENTIAL_SCORE
    assert bundle["summary"]["score_formula"] == module._score_formula()
    assert (
        f"Strategic potential is tracked separately at {module.STRATEGIC_POTENTIAL_SCORE}"
        in bundle["rationale"]
    )
    check_ids = {check["id"] for check in bundle["checks"]}
    assert check_ids == {
        "workflow_compatibility_report",
        "newcomer_first_proof_contract",
        "run_manifest_contract",
        "revision_traceability_report_contract",
        "public_certification_profile_report_contract",
        "supply_chain_attestation_report_contract",
        "repository_knowledge_report_contract",
        "run_diff_evidence_report_contract",
        "ci_artifact_harvest_report_contract",
        "github_actions_artifact_index_contract",
        "ci_provider_artifact_index_contract",
        "multi_app_dag_report_contract",
        "global_pipeline_dag_report_contract",
        "global_pipeline_execution_plan_report_contract",
        "global_pipeline_runner_state_report_contract",
        "global_pipeline_dispatch_state_report_contract",
        "global_pipeline_app_dispatch_smoke_report_contract",
        "global_pipeline_operator_state_report_contract",
        "global_pipeline_dependency_view_report_contract",
        "global_pipeline_live_state_updates_report_contract",
        "global_pipeline_operator_actions_report_contract",
        "global_pipeline_operator_ui_report_contract",
        "notebook_pipeline_import_report_contract",
        "notebook_roundtrip_report_contract",
        "notebook_union_environment_report_contract",
        "data_connector_facility_report_contract",
        "data_connector_resolution_report_contract",
        "data_connector_health_report_contract",
        "data_connector_health_actions_report_contract",
        "data_connector_runtime_adapters_report_contract",
        "data_connector_live_endpoint_smoke_report_contract",
        "data_connector_ui_preview_report_contract",
        "data_connector_live_ui_report_contract",
        "data_connector_view_surface_report_contract",
        "data_connector_app_catalogs_report_contract",
        "reduce_contract_adoption_guardrail",
        "reduce_contract_benchmark",
        "hf_space_smoke_contract",
        "web_ui_robot_contract",
        "production_readiness_report_contract",
        "docs_mirror_stamp",
        "public_docs_evidence_links",
    }


def test_render_readme_summary_uses_kpi_bundle_scores() -> None:
    module = _load_module()
    snapshot = module.build_score_snapshot()

    summary = module.render_readme_summary(snapshot)
    components = snapshot["summary"]["score_components"]

    assert "Current public evaluation summary" in summary
    assert (
        f"`{components['Ease of adoption']}` for ease of adoption, research experimentation, "
        "and engineering prototyping."
    ) in summary
    assert f"`{components['Production readiness']}` for production readiness." in summary
    assert f"`{snapshot['summary']['strategic_potential_score']}` for strategic potential." in summary
    assert f"rounded category average: `{snapshot['supported_score']}`" in summary


def test_refresh_readme_summary_replaces_static_block(tmp_path: Path) -> None:
    module = _load_module()
    snapshot = module.build_score_snapshot()
    readme_path = tmp_path / "README.md"
    readme_path.write_text(
        "\n".join(
            [
                "# AGILAB",
                "",
                "## Evaluation Snapshot",
                "",
                "Current public evaluation summary, refreshed from the public KPI bundle:",
                "",
                "- stale",
                "",
                "These are public experimentation-workbench scores, not production MLOps claims.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    changed = module.refresh_readme_summary(
        readme_path=readme_path,
        bundle=snapshot,
    )

    refreshed = readme_path.read_text(encoding="utf-8")
    assert changed is True
    assert module.README_SUMMARY_START in refreshed
    assert module.README_SUMMARY_END in refreshed
    assert "- stale" not in refreshed
    assert f"`{snapshot['summary']['strategic_potential_score']}` for strategic potential." in refreshed
    assert "These are public experimentation-workbench scores" in refreshed


def test_workflow_compatibility_report_requires_hf_demo_validated() -> None:
    module = _load_module()

    check = module._check_workflow_compatibility_report(Path.cwd())

    assert check["status"] == "pass"
    statuses = check["details"]["required_public_statuses"]["actual_statuses"]
    assert statuses["agilab-hf-demo"] == "validated"
    assert "workflow_evidence_commands" in check["details"]["check_ids"]
    assert "run_manifest_evidence_ingestion" in check["details"]["check_ids"]
    assert "artifact_index_evidence_ingestion" in check["details"]["check_ids"]
    assert check["details"]["run_manifest_evidence_ingestion"]["loaded_manifest_count"] == 0
    assert check["details"]["artifact_index_evidence_ingestion"][
        "loaded_artifact_index_count"
    ] == 0


def test_newcomer_first_proof_contract_reports_guided_wizard() -> None:
    module = _load_module()

    check = module._check_newcomer_first_proof_contract(Path.cwd())

    assert check["status"] == "pass"
    assert check["details"]["labels"] == ["preinit smoke", "source ui smoke"]
    wizard = check["details"]["wizard"]
    assert wizard["recommended_path_id"] == "source-checkout-first-proof"
    assert wizard["actionable_route_ids"] == ["source-checkout-first-proof"]
    assert wizard["documented_route_ids"] == ["notebook-quickstart"]
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


def test_revision_traceability_report_contract_fingerprints_repo() -> None:
    module = _load_module()

    check = module._check_revision_traceability_report(Path.cwd())

    assert check["status"] == "pass"
    assert check["details"]["summary"]["schema"] == "agilab.revision_traceability.v1"
    assert check["details"]["summary"]["execution_mode"] == "revision_traceability_static"
    assert check["details"]["summary"]["core_component_count"] == 5
    assert check["details"]["summary"]["builtin_app_count"] == 10
    assert check["details"]["summary"]["app_fingerprint_count"] == 10
    assert check["details"]["summary"]["command_execution_count"] == 0
    assert check["details"]["summary"]["network_probe_count"] == 0
    assert "revision_traceability_builtin_apps" in check["details"]["check_ids"]


def test_public_certification_profile_report_contract_bounds_scope() -> None:
    module = _load_module()

    check = module._check_public_certification_profile_report(Path.cwd())

    assert check["status"] == "pass"
    assert check["details"]["summary"]["schema"] == (
        "agilab.public_certification_profile.v1"
    )
    assert check["details"]["summary"]["certification_profile"] == "bounded_public_evidence"
    assert check["details"]["summary"]["path_count"] == 6
    assert check["details"]["summary"]["certified_public_evidence_count"] == 5
    assert check["details"]["summary"]["documented_not_certified_count"] == 1
    assert check["details"]["summary"]["certified_beyond_newcomer_operator_count"] == 3
    assert check["details"]["summary"]["production_certification_claimed"] is False
    assert check["details"]["summary"]["formal_third_party_certification"] is False
    assert check["details"]["summary"]["command_execution_count"] == 0
    assert check["details"]["summary"]["network_probe_count"] == 0
    assert "public_certification_profile_boundaries" in check["details"]["check_ids"]


def test_supply_chain_attestation_report_contract_fingerprints_package() -> None:
    module = _load_module()

    check = module._check_supply_chain_attestation_report(Path.cwd())

    assert check["status"] == "pass"
    assert check["details"]["summary"]["schema"] == "agilab.supply_chain_attestation.v1"
    assert check["details"]["summary"]["execution_mode"] == (
        "supply_chain_static_attestation"
    )
    assert check["details"]["summary"]["package_name"] == "agilab"
    assert check["details"]["summary"]["lockfile_present"] is True
    assert check["details"]["summary"]["license_present"] is True
    assert check["details"]["summary"]["core_component_count"] == 4
    assert check["details"]["summary"]["core_release_graph_aligned"] is True
    assert check["details"]["summary"]["page_lib_component_count"] == 2
    assert check["details"]["summary"]["page_lib_release_graph_aligned"] is True
    assert check["details"]["summary"]["aligned_internal_dependency_pins"] is True
    assert check["details"]["summary"]["mismatched_internal_dependency_pin_count"] == 0
    assert check["details"]["summary"]["builtin_app_pyproject_count"] == 10
    assert check["details"]["summary"]["aligned_builtin_app_versions"] is True
    assert check["details"]["summary"]["mismatched_builtin_app_version_count"] == 0
    assert check["details"]["summary"]["aligned_builtin_app_internal_dependency_bounds"] is True
    assert check["details"]["summary"]["mismatched_builtin_app_internal_dependency_bound_count"] == 0
    assert check["details"]["summary"]["package_data_pattern_count"] >= 1
    assert check["details"]["summary"]["builtin_payload_file_count"] >= 1
    assert check["details"]["summary"]["builtin_payload_bytes"] >= 1
    assert check["details"]["summary"]["builtin_archive_file_count"] >= 0
    assert check["details"]["summary"]["builtin_notebook_file_count"] >= 0
    assert check["details"]["summary"]["command_execution_count"] == 0
    assert check["details"]["summary"]["network_probe_count"] == 0
    assert check["details"]["summary"]["formal_supply_chain_attestation"] is False
    assert "supply_chain_attestation_core_alignment" in check["details"]["check_ids"]
    assert "supply_chain_attestation_payload_inventory" in check["details"]["check_ids"]


def test_repository_knowledge_report_contract_indexes_repo_context() -> None:
    module = _load_module()

    check = module._check_repository_knowledge_report(Path.cwd())

    assert check["status"] == "pass"
    assert check["details"]["summary"]["schema"] == (
        "agilab.repository_knowledge_index.v1"
    )
    assert check["details"]["summary"]["run_status"] == "indexed"
    assert check["details"]["summary"]["execution_mode"] == (
        "repository_knowledge_static_index"
    )
    assert check["details"]["summary"]["indexed_file_count"] > 50
    assert check["details"]["summary"]["python_file_count"] > 20
    assert check["details"]["summary"]["docs_file_count"] > 10
    assert check["details"]["summary"]["pyproject_count"] >= 8
    assert check["details"]["summary"]["runbook_count"] >= 3
    assert check["details"]["summary"]["knowledge_map_count"] == 4
    assert check["details"]["summary"]["query_seed_count"] >= 4
    assert check["details"]["summary"]["excluded_path_hit_count"] == 0
    assert check["details"]["summary"]["generated_wiki_source_of_truth"] is False
    assert check["details"]["summary"]["official_docs_source_of_truth"] is True
    assert check["details"]["summary"]["network_probe_count"] == 0
    assert check["details"]["summary"]["command_execution_count"] == 0
    assert "repository_knowledge_exclusion_guardrails" in check["details"]["check_ids"]
    assert "repository_knowledge_source_of_truth_boundary" in check["details"]["check_ids"]


def test_run_diff_evidence_report_contract_reports_counterfactuals() -> None:
    module = _load_module()

    check = module._check_run_diff_evidence_report(Path.cwd())

    assert check["status"] == "pass"
    assert check["details"]["summary"]["schema"] == "agilab.run_diff_evidence.v1"
    assert check["details"]["summary"]["run_status"] == "diff_ready"
    assert check["details"]["summary"]["execution_mode"] == "run_diff_evidence_only"
    assert check["details"]["summary"]["check_added_count"] == 1
    assert check["details"]["summary"]["check_removed_count"] == 0
    assert check["details"]["summary"]["check_status_changed_count"] == 0
    assert check["details"]["summary"]["check_summary_changed_count"] == 1
    assert check["details"]["summary"]["artifact_added_count"] == 2
    assert check["details"]["summary"]["artifact_removed_count"] == 0
    assert check["details"]["summary"]["manifest_artifact_delta"] == 1
    assert check["details"]["summary"]["counterfactual_count"] == 2
    assert check["details"]["summary"]["network_probe_count"] == 0
    assert check["details"]["summary"]["live_execution_count"] == 0
    assert check["details"]["summary"]["command_execution_count"] == 0
    assert "run_diff_evidence_counterfactuals" in check["details"]["check_ids"]
    assert "run_diff_evidence_no_execution" in check["details"]["check_ids"]


def test_ci_artifact_harvest_report_contract_reports_external_artifacts() -> None:
    module = _load_module()

    check = module._check_ci_artifact_harvest_report(Path.cwd())

    assert check["status"] == "pass"
    assert check["details"]["summary"]["schema"] == "agilab.ci_artifact_harvest.v1"
    assert check["details"]["summary"]["run_status"] == "harvest_ready"
    assert check["details"]["summary"]["execution_mode"] == "ci_artifact_contract_only"
    assert check["details"]["summary"]["release_status"] == "validated"
    assert check["details"]["summary"]["artifact_count"] == 4
    assert check["details"]["summary"]["required_artifact_count"] == 4
    assert check["details"]["summary"]["loaded_artifact_count"] == 4
    assert check["details"]["summary"]["missing_required_count"] == 0
    assert check["details"]["summary"]["checksum_verified_count"] == 4
    assert check["details"]["summary"]["checksum_mismatch_count"] == 0
    assert check["details"]["summary"]["provenance_tagged_count"] == 4
    assert check["details"]["summary"]["external_machine_evidence_count"] == 4
    assert check["details"]["summary"]["live_ci_query_count"] == 0
    assert check["details"]["summary"]["network_probe_count"] == 0
    assert check["details"]["summary"]["command_execution_count"] == 0
    assert "ci_artifact_harvest_release_status" in check["details"]["check_ids"]
    assert "ci_artifact_harvest_no_live_ci" in check["details"]["check_ids"]


def test_github_actions_artifact_index_contract_feeds_harvest() -> None:
    module = _load_module()

    check = module._check_github_actions_artifact_index(Path.cwd())

    assert check["status"] == "pass"
    assert check["details"]["summary"]["schema"] == "agilab.ci_provider_artifact_index.v1"
    assert check["details"]["summary"]["archive_count"] == 1
    assert check["details"]["summary"]["artifact_count"] == 4
    assert check["details"]["summary"]["missing_required_count"] == 0
    assert check["details"]["summary"]["provider_query_count"] == 0
    assert check["details"]["summary"]["download_count"] == 0
    assert check["details"]["summary"]["network_probe_count"] == 0
    assert check["details"]["harvest_summary"]["release_status"] == "validated"


def test_ci_provider_artifact_index_contract_feeds_gitlab_harvest() -> None:
    module = _load_module()

    check = module._check_ci_provider_artifact_index(Path.cwd())

    assert check["status"] == "pass"
    assert check["details"]["provider"] == "gitlab_ci"
    assert check["details"]["summary"]["schema"] == "agilab.ci_provider_artifact_index.v1"
    assert check["details"]["summary"]["archive_count"] == 1
    assert check["details"]["summary"]["artifact_count"] == 4
    assert check["details"]["summary"]["missing_required_count"] == 0
    assert check["details"]["summary"]["provider_query_count"] == 0
    assert check["details"]["summary"]["download_count"] == 0
    assert check["details"]["summary"]["network_probe_count"] == 0
    assert check["details"]["live_gitlab_summary"]["provider_query_count"] == 1
    assert check["details"]["live_gitlab_summary"]["download_count"] == 1
    assert check["details"]["live_gitlab_summary"]["network_probe_count"] == 2
    assert check["details"]["live_gitlab_summary"]["missing_required_count"] == 3
    assert check["details"]["harvest_summary"]["release_status"] == "validated"


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
    assert check["details"]["summary"]["sample_count"] == 2
    assert check["details"]["summary"]["supplemental_sample_count"] == 1
    assert check["details"]["summary"]["suite_node_count"] == 6
    assert check["details"]["summary"]["suite_edge_count"] == 4
    assert check["details"]["summary"]["suite_app_count"] == 6
    assert check["details"]["summary"]["suite_cross_app_edge_count"] == 4
    assert "multi_app_dag_artifact_handoffs" in check["details"]["check_ids"]
    assert "multi_app_dag_sample_suite" in check["details"]["check_ids"]


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


def test_global_pipeline_app_dispatch_smoke_report_contract_executes_real_dag() -> None:
    module = _load_module()

    check = module._check_global_pipeline_app_dispatch_smoke_report(Path.cwd())

    assert check["status"] == "pass"
    assert check["executed"] is True
    assert check["details"]["dag_path"] == "docs/source/data/multi_app_dag_sample.json"
    assert check["details"]["summary"]["run_status"] == "completed"
    assert check["details"]["summary"]["persistence_format"] == "json"
    assert check["details"]["summary"]["round_trip_ok"] is True
    assert check["details"]["summary"]["unit_count"] == 2
    assert check["details"]["summary"]["completed_unit_ids"] == ["queue_baseline", "relay_followup"]
    assert check["details"]["summary"]["runnable_unit_ids"] == []
    assert check["details"]["summary"]["real_executed_unit_ids"] == ["queue_baseline", "relay_followup"]
    assert check["details"]["summary"]["readiness_only_unit_ids"] == []
    assert check["details"]["summary"]["real_execution_scope"] == "full_dag_smoke"
    assert check["details"]["summary"]["queue_packets_generated"] > 0
    assert check["details"]["summary"]["relay_packets_generated"] > 0
    assert check["details"]["summary"]["packets_generated"] > 0
    assert "queue_metrics" in check["details"]["summary"]["available_artifact_ids"]
    assert "relay_metrics" in check["details"]["summary"]["available_artifact_ids"]
    assert "global_pipeline_app_dispatch_smoke_real_queue" in check["details"]["check_ids"]
    assert "global_pipeline_app_dispatch_smoke_real_relay" in check["details"]["check_ids"]


def test_global_pipeline_operator_state_report_contract_exposes_actions() -> None:
    module = _load_module()

    check = module._check_global_pipeline_operator_state_report(Path.cwd())

    assert check["status"] == "pass"
    assert check["executed"] is True
    assert check["details"]["summary"]["run_status"] == "ready_for_operator_review"
    assert check["details"]["summary"]["persistence_format"] == "json"
    assert check["details"]["summary"]["round_trip_ok"] is True
    assert check["details"]["summary"]["visible_unit_count"] == 2
    assert check["details"]["summary"]["completed_unit_ids"] == ["queue_baseline", "relay_followup"]
    assert check["details"]["summary"]["source_real_execution_scope"] == "full_dag_smoke"
    assert check["details"]["summary"]["handoff_count"] == 1
    assert check["details"]["summary"]["retry_action_count"] == 2
    assert check["details"]["summary"]["partial_rerun_action_count"] == 2
    assert "queue_metrics" in check["details"]["summary"]["available_artifact_ids"]
    assert "relay_metrics" in check["details"]["summary"]["available_artifact_ids"]
    assert "global_pipeline_operator_state_actions" in check["details"]["check_ids"]


def test_global_pipeline_dependency_view_report_contract_exposes_adjacency() -> None:
    module = _load_module()

    check = module._check_global_pipeline_dependency_view_report(Path.cwd())

    assert check["status"] == "pass"
    assert check["executed"] is True
    assert check["details"]["summary"]["run_status"] == "ready_for_operator_review"
    assert check["details"]["summary"]["persistence_format"] == "json"
    assert check["details"]["summary"]["round_trip_ok"] is True
    assert check["details"]["summary"]["node_count"] == 2
    assert check["details"]["summary"]["edge_count"] == 1
    assert check["details"]["summary"]["cross_app_edge_count"] == 1
    assert check["details"]["summary"]["upstream_dependency_count"] == 1
    assert check["details"]["summary"]["downstream_dependency_count"] == 1
    assert check["details"]["summary"]["visible_unit_ids"] == ["queue_baseline", "relay_followup"]
    assert check["details"]["summary"]["source_real_execution_scope"] == "full_dag_smoke"
    assert "queue_metrics" in check["details"]["summary"]["available_artifact_ids"]
    assert "global_pipeline_dependency_view_cross_app_edge" in check["details"]["check_ids"]


def test_global_pipeline_live_state_updates_report_contract_exposes_stream() -> None:
    module = _load_module()

    check = module._check_global_pipeline_live_state_updates_report(Path.cwd())

    assert check["status"] == "pass"
    assert check["executed"] is True
    assert check["details"]["summary"]["run_status"] == "ready_for_operator_review"
    assert check["details"]["summary"]["persistence_format"] == "json"
    assert check["details"]["summary"]["round_trip_ok"] is True
    assert check["details"]["summary"]["update_count"] == 6
    assert check["details"]["summary"]["graph_update_count"] == 1
    assert check["details"]["summary"]["unit_update_count"] == 2
    assert check["details"]["summary"]["artifact_update_count"] == 1
    assert check["details"]["summary"]["dependency_update_count"] == 1
    assert check["details"]["summary"]["action_update_count"] == 1
    assert check["details"]["summary"]["retry_action_count"] == 2
    assert check["details"]["summary"]["partial_rerun_action_count"] == 2
    assert check["details"]["summary"]["visible_unit_ids"] == ["queue_baseline", "relay_followup"]
    assert check["details"]["summary"]["source_real_execution_scope"] == "full_dag_smoke"
    assert "global_pipeline_live_state_updates_sequence" in check["details"]["check_ids"]


def test_global_pipeline_operator_actions_report_contract_executes_actions() -> None:
    module = _load_module()

    check = module._check_global_pipeline_operator_actions_report(Path.cwd())

    assert check["status"] == "pass"
    assert check["executed"] is True
    assert check["details"]["summary"]["run_status"] == "completed"
    assert check["details"]["summary"]["persistence_format"] == "json"
    assert check["details"]["summary"]["round_trip_ok"] is True
    assert check["details"]["summary"]["action_request_count"] == 2
    assert check["details"]["summary"]["completed_action_count"] == 2
    assert check["details"]["summary"]["retry_execution_count"] == 1
    assert check["details"]["summary"]["partial_rerun_execution_count"] == 1
    assert check["details"]["summary"]["real_action_execution_count"] == 2
    assert check["details"]["summary"]["output_artifact_count"] == 4
    assert check["details"]["summary"]["event_count"] == 4
    assert check["details"]["summary"]["source_real_execution_scope"] == "full_dag_smoke"
    assert "global_pipeline_operator_actions_real_replay" in check["details"]["check_ids"]


def test_global_pipeline_operator_ui_report_contract_renders_components() -> None:
    module = _load_module()

    check = module._check_global_pipeline_operator_ui_report(Path.cwd())

    assert check["status"] == "pass"
    assert check["executed"] is True
    assert check["details"]["summary"]["run_status"] == "ready_for_operator_review"
    assert check["details"]["summary"]["persistence_format"] == "json+html"
    assert check["details"]["summary"]["round_trip_ok"] is True
    assert check["details"]["summary"]["component_count"] == 6
    assert check["details"]["summary"]["unit_card_count"] == 2
    assert check["details"]["summary"]["action_control_count"] == 2
    assert check["details"]["summary"]["artifact_row_count"] == 4
    assert check["details"]["summary"]["timeline_update_count"] == 6
    assert check["details"]["summary"]["supported_action_ids"] == [
        "queue_baseline:retry",
        "relay_followup:partial_rerun",
    ]
    assert check["details"]["summary"]["source_real_execution_scope"] == "full_dag_smoke"
    assert "global_pipeline_operator_ui_html_render" in check["details"]["check_ids"]


def test_notebook_pipeline_import_report_contract_preserves_notebook_metadata() -> None:
    module = _load_module()

    check = module._check_notebook_pipeline_import_report(Path.cwd())

    assert check["status"] == "pass"
    assert check["details"]["summary"]["schema"] == "agilab.notebook_pipeline_import.v1"
    assert check["details"]["summary"]["run_status"] == "imported"
    assert check["details"]["summary"]["execution_mode"] == "not_executed_import"
    assert check["details"]["summary"]["persistence_format"] == "json"
    assert check["details"]["summary"]["round_trip_ok"] is True
    assert check["details"]["summary"]["code_cell_count"] == 2
    assert check["details"]["summary"]["markdown_cell_count"] == 2
    assert check["details"]["summary"]["pipeline_stage_count"] == 2
    assert check["details"]["summary"]["context_block_count"] == 2
    assert check["details"]["summary"]["lab_stages_preview_stage_count"] == 2
    assert check["details"]["summary"]["env_hint_count"] == 3
    assert check["details"]["summary"]["artifact_reference_count"] == 3
    assert "notebook_pipeline_import_context_links" in check["details"]["check_ids"]
    assert "notebook_pipeline_import_lab_stages_preview" in check["details"]["check_ids"]


def test_notebook_roundtrip_report_contract_preserves_lab_stages_fields() -> None:
    module = _load_module()

    check = module._check_notebook_roundtrip_report(Path.cwd())

    assert check["status"] == "pass"
    assert check["details"]["summary"]["execution_mode"] == "not_executed_import"
    assert check["details"]["summary"]["import_mode"] == "agilab_supervisor_metadata"
    assert check["details"]["summary"]["supervisor_stage_count"] == 2
    assert check["details"]["summary"]["pipeline_stage_count"] == 2
    assert check["details"]["summary"]["lab_stages_round_trip_ok"] is True
    assert check["details"]["summary"]["env_hint_count"] == 3
    assert check["details"]["summary"]["artifact_reference_count"] == 3
    assert "notebook_roundtrip_lab_stages_fields" in check["details"]["check_ids"]


def test_notebook_union_environment_report_contract_guards_mixed_runtimes() -> None:
    module = _load_module()

    check = module._check_notebook_union_environment_report(Path.cwd())

    assert check["status"] == "pass"
    assert check["details"]["summary"]["compatible_union_mode"] == "single_kernel_union_candidate"
    assert check["details"]["summary"]["incompatible_union_mode"] == "supervisor_notebook_required"
    assert check["details"]["summary"]["compatible_stage_count"] == 2
    assert check["details"]["summary"]["code_cell_count"] == 2
    assert check["details"]["summary"]["incompatible_issue_count"] >= 2
    assert "notebook_union_environment_mixed_runtime_guard" in check["details"]["check_ids"]


def test_data_connector_facility_report_contract_validates_connector_targets() -> None:
    module = _load_module()

    check = module._check_data_connector_facility_report(Path.cwd())

    assert check["status"] == "pass"
    assert check["details"]["summary"]["schema"] == "agilab.data_connector_facility.v1"
    assert check["details"]["summary"]["run_status"] == "validated"
    assert check["details"]["summary"]["execution_mode"] == "contract_validation_only"
    assert check["details"]["summary"]["connector_count"] == 5
    assert check["details"]["summary"]["supported_kinds"] == [
        "object_storage",
        "opensearch",
        "sql",
    ]
    assert check["details"]["summary"]["raw_secret_count"] == 0
    assert check["details"]["summary"]["network_probe_count"] == 0
    assert check["details"]["summary"]["round_trip_ok"] is True
    assert "data_connector_facility_secret_boundary" in check["details"]["check_ids"]


def test_data_connector_resolution_report_contract_resolves_app_page_refs() -> None:
    module = _load_module()

    check = module._check_data_connector_resolution_report(Path.cwd())

    assert check["status"] == "pass"
    assert check["details"]["summary"]["schema"] == "agilab.data_connector_resolution.v1"
    assert check["details"]["summary"]["run_status"] == "resolved"
    assert check["details"]["summary"]["execution_mode"] == "contract_resolution_only"
    assert check["details"]["summary"]["connector_ref_count"] == 5
    assert check["details"]["summary"]["top_level_ref_count"] == 3
    assert check["details"]["summary"]["page_connector_ref_count"] == 2
    assert check["details"]["summary"]["legacy_path_count"] == 2
    assert check["details"]["summary"]["missing_ref_count"] == 0
    assert check["details"]["summary"]["network_probe_count"] == 0
    assert check["details"]["summary"]["catalog_run_status"] == "validated"
    assert check["details"]["summary"]["legacy_fallback_preserved"] is True
    assert check["details"]["summary"]["resolved_kinds"] == [
        "object_storage",
        "opensearch",
        "sql",
    ]
    assert "data_connector_resolution_page_refs" in check["details"]["check_ids"]
    assert "data_connector_resolution_no_network" in check["details"]["check_ids"]


def test_data_connector_health_report_contract_plans_opt_in_probes() -> None:
    module = _load_module()

    check = module._check_data_connector_health_report(Path.cwd())

    assert check["status"] == "pass"
    assert check["details"]["summary"]["schema"] == "agilab.data_connector_health.v1"
    assert check["details"]["summary"]["run_status"] == "planned"
    assert check["details"]["summary"]["execution_mode"] == "health_probe_plan_only"
    assert check["details"]["summary"]["connector_count"] == 5
    assert check["details"]["summary"]["planned_probe_count"] == 5
    assert check["details"]["summary"]["executed_probe_count"] == 0
    assert check["details"]["summary"]["opt_in_required_count"] == 5
    assert check["details"]["summary"]["network_probe_count"] == 0
    assert check["details"]["summary"]["status_values"] == ["unknown_not_probed"]
    assert check["details"]["summary"]["unhealthy_count"] == 0
    assert "data_connector_health_opt_in_boundary" in check["details"]["check_ids"]
    assert "data_connector_health_no_network" in check["details"]["check_ids"]


def test_data_connector_health_actions_report_contract_exposes_operator_triggers() -> None:
    module = _load_module()

    check = module._check_data_connector_health_actions_report(Path.cwd())

    assert check["status"] == "pass"
    assert check["details"]["summary"]["schema"] == "agilab.data_connector_health_actions.v1"
    assert check["details"]["summary"]["run_status"] == "ready_for_operator_trigger"
    assert check["details"]["summary"]["execution_mode"] == "operator_trigger_contract_only"
    assert check["details"]["summary"]["action_count"] == 5
    assert check["details"]["summary"]["connector_count"] == 5
    assert check["details"]["summary"]["operator_trigger_count"] == 5
    assert check["details"]["summary"]["pending_action_count"] == 5
    assert check["details"]["summary"]["pending_operator_trigger_count"] == 5
    assert check["details"]["summary"]["executed_probe_count"] == 0
    assert check["details"]["summary"]["network_probe_count"] == 0
    assert check["details"]["summary"]["operator_context_required_count"] == 5
    assert check["details"]["summary"]["credential_gated_count"] == 4
    assert check["details"]["summary"]["no_credential_required_count"] == 1
    assert check["details"]["summary"]["default_status_values"] == ["unknown_not_probed"]
    assert check["details"]["summary"]["result_status_values"] == ["unknown_not_probed"]
    assert "data_connector_health_actions_operator_trigger" in check["details"]["check_ids"]
    assert "data_connector_health_actions_no_network" in check["details"]["check_ids"]


def test_data_connector_runtime_adapters_report_contract_exposes_bindings() -> None:
    module = _load_module()

    check = module._check_data_connector_runtime_adapters_report(Path.cwd())

    assert check["status"] == "pass"
    assert check["details"]["summary"]["schema"] == (
        "agilab.data_connector_runtime_adapters.v1"
    )
    assert check["details"]["summary"]["run_status"] == "ready_for_runtime_binding"
    assert check["details"]["summary"]["execution_mode"] == "runtime_adapter_contract_only"
    assert check["details"]["summary"]["connector_count"] == 5
    assert check["details"]["summary"]["adapter_count"] == 5
    assert check["details"]["summary"]["runtime_ready_count"] == 5
    assert check["details"]["summary"]["credential_deferred_count"] == 4
    assert check["details"]["summary"]["no_credential_required_count"] == 1
    assert check["details"]["summary"]["operator_opt_in_required_count"] == 5
    assert check["details"]["summary"]["health_action_binding_count"] == 5
    assert check["details"]["summary"]["executed_adapter_count"] == 0
    assert check["details"]["summary"]["network_probe_count"] == 0
    assert check["details"]["summary"]["credential_value_materialized_count"] == 0
    assert check["details"]["summary"]["operations"] == [
        "object_storage_prefix_list",
        "opensearch_index_head",
        "read_only_connectivity_check",
    ]
    assert "data_connector_runtime_adapters_rows" in check["details"]["check_ids"]
    assert "data_connector_runtime_adapters_no_network" in check["details"]["check_ids"]


def test_data_connector_live_endpoint_smoke_report_contract_reports_opt_in() -> None:
    module = _load_module()

    check = module._check_data_connector_live_endpoint_smoke_report(Path.cwd())

    assert check["status"] == "pass"
    assert check["details"]["summary"]["schema"] == (
        "agilab.data_connector_live_endpoint_smoke.v1"
    )
    assert check["details"]["summary"]["execution_mode"] == "live_endpoint_smoke_plan_only"
    assert check["details"]["summary"]["connector_count"] == 5
    assert check["details"]["summary"]["planned_endpoint_count"] == 5
    assert check["details"]["summary"]["executed_endpoint_count"] == 0
    assert check["details"]["summary"]["network_probe_count"] == 0
    assert check["details"]["summary"]["sqlite_smoke_healthy_count"] == 1
    assert (
        "data_connector_live_endpoint_smoke_sqlite_execution"
        in check["details"]["check_ids"]
    )


def test_data_connector_ui_preview_report_contract_renders_connector_state() -> None:
    module = _load_module()

    check = module._check_data_connector_ui_preview_report(Path.cwd())

    assert check["status"] == "pass"
    assert check["details"]["summary"]["schema"] == "agilab.data_connector_ui_preview.v1"
    assert check["details"]["summary"]["run_status"] == "ready_for_ui_preview"
    assert check["details"]["summary"]["execution_mode"] == "static_ui_preview_only"
    assert check["details"]["summary"]["persistence_format"] == "json+html"
    assert check["details"]["summary"]["connector_card_count"] == 5
    assert check["details"]["summary"]["page_binding_count"] == 2
    assert check["details"]["summary"]["legacy_fallback_count"] == 2
    assert check["details"]["summary"]["health_probe_status_count"] == 5
    assert check["details"]["summary"]["component_count"] == 10
    assert check["details"]["summary"]["network_probe_count"] == 0
    assert check["details"]["summary"]["html_rendered"] is True
    assert check["details"]["summary"]["html_written"] is True
    assert "data_connector_ui_preview_html_render" in check["details"]["check_ids"]
    assert "data_connector_ui_preview_health_boundary" in check["details"]["check_ids"]


def test_data_connector_live_ui_report_contract_wires_release_decision() -> None:
    module = _load_module()

    check = module._check_data_connector_live_ui_report(Path.cwd())

    assert check["status"] == "pass"
    assert check["details"]["summary"]["schema"] == "agilab.data_connector_live_ui.v1"
    assert check["details"]["summary"]["run_status"] == "ready_for_live_ui"
    assert check["details"]["summary"]["execution_mode"] == "streamlit_render_contract_only"
    assert check["details"]["summary"]["connector_card_count"] == 5
    assert check["details"]["summary"]["page_binding_count"] == 2
    assert check["details"]["summary"]["legacy_fallback_count"] == 2
    assert check["details"]["summary"]["health_probe_status_count"] == 5
    assert check["details"]["summary"]["streamlit_metric_count"] == 4
    assert check["details"]["summary"]["streamlit_dataframe_count"] == 4
    assert check["details"]["summary"]["network_probe_count"] == 0
    assert check["details"]["summary"]["operator_opt_in_required_for_health"] is True
    assert check["details"]["summary"]["release_decision_hooked"] is True
    assert "data_connector_live_ui_release_decision_hook" in check["details"]["check_ids"]
    assert "data_connector_live_ui_health_boundary" in check["details"]["check_ids"]


def test_data_connector_view_surface_report_contract_maps_release_decision_panels() -> None:
    module = _load_module()

    check = module._check_data_connector_view_surface_report(Path.cwd())

    assert check["status"] == "pass"
    assert check["details"]["summary"]["schema"] == (
        "agilab.data_connector_view_surface.v1"
    )
    assert check["details"]["summary"]["run_status"] == "validated"
    assert check["details"]["summary"]["execution_mode"] == (
        "connector_view_surface_contract_only"
    )
    assert check["details"]["summary"]["view_surface_count"] == 4
    assert check["details"]["summary"]["ready_view_surface_count"] == 4
    assert check["details"]["summary"]["release_decision_surface_count"] == 4
    assert check["details"]["summary"]["page_source_loaded"] is True
    assert check["details"]["summary"]["live_ui_run_status"] == "ready_for_live_ui"
    assert check["details"]["summary"]["network_probe_count"] == 0
    assert check["details"]["summary"]["command_execution_count"] == 0
    assert (
        "data_connector_view_surface_external_artifact_traceability"
        in check["details"]["check_ids"]
    )
    assert (
        "data_connector_view_surface_import_export_provenance"
        in check["details"]["check_ids"]
    )


def test_data_connector_app_catalogs_report_contract_validates_builtin_apps() -> None:
    module = _load_module()

    check = module._check_data_connector_app_catalogs_report(Path.cwd())

    assert check["status"] == "pass"
    assert check["details"]["summary"]["schema"] == "agilab.data_connector_app_catalogs.v1"
    assert check["details"]["summary"]["run_status"] == "validated"
    assert check["details"]["summary"]["execution_mode"] == "app_catalog_validation_only"
    assert check["details"]["summary"]["app_catalog_count"] == 6
    assert check["details"]["summary"]["connector_count"] == 18
    assert check["details"]["summary"]["page_connector_ref_count"] == 15
    assert check["details"]["summary"]["legacy_path_count"] == 12
    assert check["details"]["summary"]["missing_ref_count"] == 0
    assert check["details"]["summary"]["network_probe_count"] == 0
    assert check["details"]["summary"]["apps"] == [
        "execution_pandas_project",
        "execution_polars_project",
        "flight_telemetry_project",
        "uav_queue_project",
        "uav_relay_queue_project",
        "weather_forecast_project",
    ]
    assert "data_connector_app_catalogs_discovery" in check["details"]["check_ids"]
    assert "data_connector_app_catalogs_no_network" in check["details"]["check_ids"]


def test_reduce_contract_adoption_guardrail_reports_template_exemption() -> None:
    module = _load_module()

    check = module._check_reduce_contract_adoption_guardrail(Path.cwd())

    assert check["status"] == "pass"
    assert check["details"]["checked_app_count"] == 8
    assert check["details"]["template_only_exemptions"] == {
        "global_dag_project": "cross-app DAG template preview with no concrete worker merge output",
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
                    "flight-telemetry project",
                    "flight view_maps",
                )
            ]

        @staticmethod
        def check_public_app_tree():
            return None

        @staticmethod
        def check_public_pages_tree():
            return None

        @staticmethod
        def run_smoke():
            return _FakeSummary(
                success=True,
                total_duration_seconds=1.0,
                target_seconds=30.0,
                within_target=True,
                checks=[
                    _FakeCheck("public app tree", True, 0.5, "ok"),
                    _FakeCheck("public pages tree", True, 0.5, "ok"),
                ],
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
