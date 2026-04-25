#!/usr/bin/env python3
"""Emit cross-KPI public evidence for AGILAB review/adoption scoring."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from decimal import Decimal, ROUND_HALF_UP
import importlib.util
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_REVIEW_SCORE = "3.2 / 5"
KPI_COMPONENT_SCORES = {
    "Ease of adoption": Decimal("3.5"),
    "Research experimentation": Decimal("4.0"),
    "Engineering prototyping": Decimal("4.0"),
    "Production readiness": Decimal("3.0"),
}
OVERALL_SCORE_RAW = sum(KPI_COMPONENT_SCORES.values(), Decimal("0")) / Decimal(len(KPI_COMPONENT_SCORES))
SUPPORTED_OVERALL_SCORE = f"{OVERALL_SCORE_RAW.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)} / 5"
TEMPLATE_ONLY_BUILTIN_APPS = {
    "mycode_project": "starter template with placeholder worker hooks and no concrete merge output",
}


def _load_tool_module(repo_root: Path, name: str) -> Any:
    module_path = repo_root / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"{name}_for_kpi_bundle", module_path)
    if not spec or not spec.loader:
        raise RuntimeError(f"unable to load tool module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_source_module(repo_root: Path, relative_path: str, module_name: str) -> Any:
    module_path = repo_root / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if not spec or not spec.loader:
        raise RuntimeError(f"unable to load source module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _check_result(
    check_id: str,
    label: str,
    passed: bool,
    summary: str,
    *,
    evidence: Sequence[str] = (),
    details: dict[str, Any] | None = None,
    executed: bool = False,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": "pass" if passed else "fail",
        "summary": summary,
        "executed": executed,
        "evidence": list(evidence),
        "details": details or {},
    }


def _check_workflow_compatibility_report(repo_root: Path) -> dict[str, Any]:
    try:
        compatibility_report = _load_tool_module(repo_root, "compatibility_report")
        report = compatibility_report.build_report(
            repo_root=repo_root,
            include_default_manifests=False,
        )
        check_ids = [check.get("id") for check in report.get("checks", [])]
        status_check = next(
            (
                check
                for check in report.get("checks", [])
                if check.get("id") == "required_public_statuses"
            ),
            {},
        )
        manifest_check = next(
            (
                check
                for check in report.get("checks", [])
                if check.get("id") == "run_manifest_evidence_ingestion"
            ),
            {},
        )
        ok = (
            report.get("status") == "pass"
            and "workflow_evidence_commands" in check_ids
            and "run_manifest_evidence_ingestion" in check_ids
        )
        details = {
            "status": report.get("status"),
            "summary": report.get("summary"),
            "check_ids": check_ids,
            "required_public_statuses": status_check.get("details", {}),
            "run_manifest_evidence_ingestion": manifest_check.get("details", {}),
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "workflow_compatibility_report",
        "Workflow-backed compatibility report",
        ok,
        (
            "compatibility report validates public path statuses, proof commands, and run manifests"
            if ok
            else "compatibility report is failing or disconnected from the KPI bundle"
        ),
        evidence=[
            "tools/compatibility_report.py",
            "docs/source/data/compatibility_matrix.toml",
        ],
        details=details,
    )


def _check_newcomer_first_proof_contract(repo_root: Path) -> dict[str, Any]:
    try:
        newcomer_first_proof = _load_tool_module(repo_root, "newcomer_first_proof")
        first_proof_wizard = _load_source_module(
            repo_root,
            "src/agilab/first_proof_wizard.py",
            "first_proof_wizard_for_kpi_bundle",
        )

        active_app = newcomer_first_proof.DEFAULT_ACTIVE_APP
        commands = newcomer_first_proof.build_proof_commands(active_app, with_install=False)
        labels = [command.label for command in commands]
        wizard_content = first_proof_wizard.newcomer_first_proof_content(repo_root)
        wizard_state = first_proof_wizard.newcomer_first_proof_state(
            SimpleNamespace(
                apps_path=repo_root / "src" / "agilab" / "apps" / "builtin",
                app="flight_project",
                AGILAB_LOG_ABS=repo_root / ".missing-first-proof-log",
            ),
            repo_root=repo_root,
        )
        ok = (
            labels == ["preinit smoke", "source ui smoke"]
            and float(newcomer_first_proof.DEFAULT_MAX_SECONDS) == 600.0
            and active_app.name == "flight_project"
            and wizard_content["recommended_path_id"] == "source-checkout-first-proof"
            and wizard_content["actionable_route_ids"] == ["source-checkout-first-proof"]
            and wizard_content["documented_route_ids"] == [
                "notebook-quickstart",
                "published-package-route",
            ]
            and wizard_content["compatibility_status"] == "validated"
            and wizard_content["compatibility_report_status"] == "pass"
            and wizard_content["proof_command_labels"] == labels
            and wizard_content["run_manifest_filename"] == "run_manifest.json"
            and [label for label, _ in wizard_content["steps"]] == [
                "PROJECT",
                "ORCHESTRATE",
                "ANALYSIS",
            ]
            and wizard_state["remediation_status"] == "missing"
            and "tools/compatibility_report.py --manifest" in wizard_state["evidence_commands"][1]
        )
        details = {
            "active_app": str(active_app),
            "labels": labels,
            "target_seconds": newcomer_first_proof.DEFAULT_MAX_SECONDS,
            "command_count": len(commands),
            "wizard": {
                "recommended_path_id": wizard_content.get("recommended_path_id"),
                "recommended_path_label": wizard_content.get("recommended_path_label"),
                "actionable_route_ids": wizard_content.get("actionable_route_ids"),
                "documented_route_ids": wizard_content.get("documented_route_ids"),
                "compatibility_status": wizard_content.get("compatibility_status"),
                "compatibility_report_status": wizard_content.get("compatibility_report_status"),
                "run_manifest_filename": wizard_content.get("run_manifest_filename"),
                "steps": [label for label, _ in wizard_content.get("steps", [])],
                "remediation_status": wizard_state.get("remediation_status"),
                "evidence_commands": wizard_state.get("evidence_commands"),
            },
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "newcomer_first_proof_contract",
        "Newcomer first-proof contract",
        ok,
        (
            "source-checkout newcomer proof is executable and exposes manifest remediation"
            if ok
            else "source-checkout newcomer proof contract is incomplete"
        ),
        evidence=[
            "tools/newcomer_first_proof.py",
            "src/agilab/first_proof_wizard.py",
            "src/agilab/About_agilab.py",
            "README.md",
        ],
        details=details,
    )


def _check_run_manifest_contract(repo_root: Path) -> dict[str, Any]:
    try:
        run_manifest = _load_source_module(
            repo_root,
            "src/agilab/run_manifest.py",
            "run_manifest_for_kpi_bundle",
        )
        newcomer_first_proof = _load_tool_module(repo_root, "newcomer_first_proof")
        active_app = newcomer_first_proof.DEFAULT_ACTIVE_APP
        commands = newcomer_first_proof.build_proof_commands(active_app, with_install=False)
        results = [
            newcomer_first_proof.ProofStepResult(
                label=command.label,
                description=command.description,
                argv=list(command.argv),
                returncode=0,
                duration_seconds=1.0,
                stdout="ok",
                env=command.env,
            )
            for command in commands
        ]
        summary = newcomer_first_proof.summarize_kpi(
            command_count=len(commands),
            results=results,
            max_seconds=float(newcomer_first_proof.DEFAULT_MAX_SECONDS),
        )
        manifest_path = newcomer_first_proof.default_manifest_path(active_app)
        manifest = newcomer_first_proof.build_run_manifest(
            active_app=active_app,
            with_install=False,
            commands=commands,
            results=results,
            summary=summary,
            max_seconds=float(newcomer_first_proof.DEFAULT_MAX_SECONDS),
            manifest_path=manifest_path,
        )
        encoded = manifest.as_dict()
        validation_labels = [validation["label"] for validation in encoded["validations"]]
        ok = (
            run_manifest.SCHEMA_VERSION == 1
            and run_manifest.RUN_MANIFEST_FILENAME == "run_manifest.json"
            and encoded["schema_version"] == 1
            and encoded["kind"] == "agilab.run_manifest"
            and encoded["path_id"] == "source-checkout-first-proof"
            and encoded["status"] == "pass"
            and encoded["command"]["argv"] == ["tools/newcomer_first_proof.py", "--json"]
            and encoded["environment"]["app_name"] == "flight_project"
            and encoded["timing"]["target_seconds"] == 600.0
            and validation_labels == ["proof_steps", "target_seconds", "recommended_project"]
            and run_manifest.manifest_passed(manifest)
        )
        details = {
            "schema_version": encoded.get("schema_version"),
            "kind": encoded.get("kind"),
            "filename": run_manifest.RUN_MANIFEST_FILENAME,
            "path_id": encoded.get("path_id"),
            "status": encoded.get("status"),
            "command": encoded.get("command"),
            "environment_keys": sorted(encoded.get("environment", {})),
            "timing_keys": sorted(encoded.get("timing", {})),
            "artifact_count": len(encoded.get("artifacts", [])),
            "validation_labels": validation_labels,
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "run_manifest_contract",
        "Run manifest contract",
        ok,
        (
            "newcomer first proof emits the stable run_manifest.json evidence schema"
            if ok
            else "run manifest contract is missing or disconnected"
        ),
        evidence=[
            "src/agilab/run_manifest.py",
            "tools/newcomer_first_proof.py",
            "src/agilab/first_proof_wizard.py",
        ],
        details=details,
    )


def _check_reduce_contract_benchmark(repo_root: Path) -> dict[str, Any]:
    try:
        reduce_contract_benchmark = _load_tool_module(repo_root, "reduce_contract_benchmark")
        summary = reduce_contract_benchmark.run_benchmark()
        ok = (
            bool(summary.success)
            and bool(summary.within_target)
            and summary.partial_count == reduce_contract_benchmark.DEFAULT_PARTIALS
            and summary.total_items
            == reduce_contract_benchmark.DEFAULT_PARTIALS
            * reduce_contract_benchmark.DEFAULT_ITEMS_PER_PARTIAL
            and summary.artifact["name"] == "public_reduce_benchmark_summary"
        )
        details = asdict(summary)
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "reduce_contract_benchmark",
        "Reduce contract benchmark",
        ok,
        (
            "public reduce-contract benchmark passes within target"
            if ok
            else "public reduce-contract benchmark is failing or incomplete"
        ),
        evidence=["tools/reduce_contract_benchmark.py", "README.md"],
        details=details,
        executed=True,
    )


def _builtin_project_dirs(repo_root: Path) -> list[Path]:
    builtin_root = repo_root / "src" / "agilab" / "apps" / "builtin"
    return sorted(
        path
        for path in builtin_root.glob("*_project")
        if (path / "pyproject.toml").is_file()
    )


def _manager_package_dir(project_dir: Path) -> Path:
    packages = sorted(
        child
        for child in (project_dir / "src").iterdir()
        if child.is_dir()
        and (child / "__init__.py").is_file()
        and not child.name.endswith("_worker")
    )
    if len(packages) != 1:
        raise ValueError(f"{project_dir.name} should expose one manager package")
    return packages[0]


def _reduce_contract_adoption_details(repo_root: Path) -> dict[str, Any]:
    checked_apps: list[str] = []
    failures: list[str] = []

    for project_dir in _builtin_project_dirs(repo_root):
        if project_dir.name in TEMPLATE_ONLY_BUILTIN_APPS:
            continue

        checked_apps.append(project_dir.name)
        try:
            package_dir = _manager_package_dir(project_dir)
            init_path = package_dir / "__init__.py"
            reduction_path = package_dir / "reduction.py"
            if not reduction_path.is_file():
                failures.append(f"{project_dir.name}: missing {reduction_path.relative_to(repo_root)}")
                continue

            init_text = init_path.read_text(encoding="utf-8")
            reduction_text = reduction_path.read_text(encoding="utf-8")
            if "from .reduction import" not in init_text:
                failures.append(f"{project_dir.name}: manager package does not export reduction contract")
            if not re.search(r"\b[A-Z0-9_]+_REDUCE_CONTRACT\b", init_text):
                failures.append(f"{project_dir.name}: no exported *_REDUCE_CONTRACT symbol")
            if "REDUCE_ARTIFACT_FILENAME_TEMPLATE" not in reduction_text:
                failures.append(f"{project_dir.name}: reducer does not declare artifact filename template")
            if "reduce_summary_worker_{worker_id}.json" not in reduction_text:
                failures.append(f"{project_dir.name}: reducer does not use worker-scoped reduce summary name")
            if "write_reduce_artifact" not in reduction_text:
                failures.append(f"{project_dir.name}: reducer does not expose write_reduce_artifact")
        except Exception as exc:
            failures.append(f"{project_dir.name}: {exc}")

    mycode_docs = repo_root / "docs" / "source" / "mycode-project.rst"
    try:
        mycode_text = mycode_docs.read_text(encoding="utf-8")
        normalized_docs = re.sub(r"\s+", " ", mycode_text.lower())
        if "template-only" not in normalized_docs:
            failures.append("mycode_project docs do not mark the project as template-only")
        if "no concrete merge output" not in normalized_docs:
            failures.append("mycode_project docs do not explain the reducer exemption")
        if "reduce_summary_worker_<id>.json" not in mycode_text:
            failures.append("mycode_project docs do not name the reducer artifact contract")
    except Exception as exc:
        failures.append(f"mycode_project docs: {exc}")

    return {
        "checked_apps": checked_apps,
        "checked_app_count": len(checked_apps),
        "template_only_exemptions": TEMPLATE_ONLY_BUILTIN_APPS,
        "failures": failures,
    }


def _check_reduce_contract_adoption_guardrail(repo_root: Path) -> dict[str, Any]:
    try:
        details = _reduce_contract_adoption_details(repo_root)
        ok = not details["failures"] and details["checked_app_count"] > 0
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "reduce_contract_adoption_guardrail",
        "Reduce contract adoption guardrail",
        ok,
        (
            "every non-template built-in app exposes a worker-scoped reducer contract"
            if ok
            else "one or more non-template built-in apps lack reducer contract adoption"
        ),
        evidence=[
            "src/agilab/apps/builtin",
            "test/test_reduce_contract_adoption.py",
            "docs/source/mycode-project.rst",
        ],
        details=details,
    )


def _check_multi_app_dag_report(repo_root: Path) -> dict[str, Any]:
    try:
        multi_app_dag_report = _load_tool_module(repo_root, "multi_app_dag_report")
        report = multi_app_dag_report.build_report(repo_root=repo_root)
        summary = report.get("summary", {})
        ok = (
            report.get("status") == "pass"
            and summary.get("node_count") == 2
            and summary.get("edge_count") == 1
            and summary.get("app_count") == 2
            and summary.get("cross_app_edge_count") == 1
            and summary.get("execution_order") == ["queue_baseline", "relay_followup"]
        )
        details = {
            "status": report.get("status"),
            "dag_path": report.get("dag_path"),
            "summary": summary,
            "check_ids": [check.get("id") for check in report.get("checks", [])],
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "multi_app_dag_report_contract",
        "Multi-app DAG report contract",
        ok,
        (
            "multi-app DAG report validates a cross-app artifact handoff contract"
            if ok
            else "multi-app DAG report is failing or disconnected"
        ),
        evidence=[
            "tools/multi_app_dag_report.py",
            "src/agilab/multi_app_dag.py",
            "docs/source/data/multi_app_dag_sample.json",
        ],
        details=details,
    )


def _check_global_pipeline_dag_report(repo_root: Path) -> dict[str, Any]:
    try:
        global_pipeline_dag_report = _load_tool_module(repo_root, "global_pipeline_dag_report")
        report = global_pipeline_dag_report.build_report(repo_root=repo_root)
        summary = report.get("summary", {})
        ok = (
            report.get("status") == "pass"
            and summary.get("runner_status") == "not_executed"
            and summary.get("app_node_count") == 2
            and summary.get("app_step_node_count") == 8
            and summary.get("local_pipeline_edge_count") == 6
            and summary.get("cross_app_edge_count") == 1
            and summary.get("execution_order") == ["queue_baseline", "relay_followup"]
        )
        details = {
            "status": report.get("status"),
            "dag_path": report.get("dag_path"),
            "summary": summary,
            "check_ids": [check.get("id") for check in report.get("checks", [])],
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "global_pipeline_dag_report_contract",
        "Global pipeline DAG report contract",
        ok,
        (
            "global pipeline DAG report assembles the read-only product graph"
            if ok
            else "global pipeline DAG report is failing or disconnected"
        ),
        evidence=[
            "tools/global_pipeline_dag_report.py",
            "src/agilab/global_pipeline_dag.py",
            "docs/source/data/multi_app_dag_sample.json",
            "src/agilab/apps/builtin/uav_queue_project/pipeline_view.dot",
            "src/agilab/apps/builtin/uav_relay_queue_project/pipeline_view.dot",
        ],
        details=details,
    )


def _check_global_pipeline_execution_plan_report(repo_root: Path) -> dict[str, Any]:
    try:
        execution_plan_report = _load_tool_module(repo_root, "global_pipeline_execution_plan_report")
        report = execution_plan_report.build_report(repo_root=repo_root)
        summary = report.get("summary", {})
        ok = (
            report.get("status") == "pass"
            and summary.get("runner_status") == "not_executed"
            and summary.get("unit_count") == 2
            and summary.get("pending_count") == 2
            and summary.get("not_executed_count") == 2
            and summary.get("ready_unit_ids") == ["queue_baseline"]
            and summary.get("blocked_unit_ids") == ["relay_followup"]
            and summary.get("artifact_dependency_count") == 1
        )
        details = {
            "status": report.get("status"),
            "dag_path": report.get("dag_path"),
            "summary": summary,
            "check_ids": [check.get("id") for check in report.get("checks", [])],
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "global_pipeline_execution_plan_report_contract",
        "Global pipeline execution plan report contract",
        ok,
        (
            "global pipeline execution plan report defines pending units and dependencies"
            if ok
            else "global pipeline execution plan report is failing or disconnected"
        ),
        evidence=[
            "tools/global_pipeline_execution_plan_report.py",
            "src/agilab/global_pipeline_execution_plan.py",
            "tools/global_pipeline_dag_report.py",
            "docs/source/data/multi_app_dag_sample.json",
        ],
        details=details,
    )


def _check_global_pipeline_runner_state_report(repo_root: Path) -> dict[str, Any]:
    try:
        runner_state_report = _load_tool_module(repo_root, "global_pipeline_runner_state_report")
        report = runner_state_report.build_report(repo_root=repo_root)
        summary = report.get("summary", {})
        ok = (
            report.get("status") == "pass"
            and summary.get("runner_mode") == "read_only_preview"
            and summary.get("run_status") == "not_started"
            and summary.get("unit_count") == 2
            and summary.get("runnable_count") == 1
            and summary.get("blocked_count") == 1
            and summary.get("runnable_unit_ids") == ["queue_baseline"]
            and summary.get("blocked_unit_ids") == ["relay_followup"]
            and summary.get("retry_policy_count") == 2
            and summary.get("partial_rerun_record_count") == 2
            and summary.get("operator_state_count") == 2
        )
        details = {
            "status": report.get("status"),
            "dag_path": report.get("dag_path"),
            "summary": summary,
            "check_ids": [check.get("id") for check in report.get("checks", [])],
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "global_pipeline_runner_state_report_contract",
        "Global pipeline runner state report contract",
        ok,
        (
            "global pipeline runner state report exposes read-only dispatch and UI state"
            if ok
            else "global pipeline runner state report is failing or disconnected"
        ),
        evidence=[
            "tools/global_pipeline_runner_state_report.py",
            "src/agilab/global_pipeline_runner_state.py",
            "tools/global_pipeline_execution_plan_report.py",
            "docs/source/data/multi_app_dag_sample.json",
        ],
        details=details,
    )


def _check_global_pipeline_dispatch_state_report(repo_root: Path) -> dict[str, Any]:
    try:
        dispatch_state_report = _load_tool_module(repo_root, "global_pipeline_dispatch_state_report")
        report = dispatch_state_report.build_report(repo_root=repo_root)
        summary = report.get("summary", {})
        ok = (
            report.get("status") == "pass"
            and summary.get("run_status") == "in_progress"
            and summary.get("persistence_format") == "json"
            and summary.get("round_trip_ok") is True
            and summary.get("unit_count") == 2
            and summary.get("completed_unit_ids") == ["queue_baseline"]
            and summary.get("runnable_unit_ids") == ["relay_followup"]
            and summary.get("blocked_unit_ids") == []
            and summary.get("available_artifact_ids") == ["queue_metrics"]
            and summary.get("retry_counter_count") == 2
            and summary.get("partial_rerun_flag_count") == 2
        )
        details = {
            "status": report.get("status"),
            "dag_path": report.get("dag_path"),
            "summary": summary,
            "check_ids": [check.get("id") for check in report.get("checks", [])],
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "global_pipeline_dispatch_state_report_contract",
        "Global pipeline dispatch state report contract",
        ok,
        (
            "global pipeline dispatch state report persists a durable transition proof"
            if ok
            else "global pipeline dispatch state report is failing or disconnected"
        ),
        evidence=[
            "tools/global_pipeline_dispatch_state_report.py",
            "src/agilab/global_pipeline_dispatch_state.py",
            "tools/global_pipeline_runner_state_report.py",
            "docs/source/data/multi_app_dag_sample.json",
        ],
        details=details,
    )


def _check_global_pipeline_app_dispatch_smoke_report(repo_root: Path) -> dict[str, Any]:
    try:
        app_dispatch_smoke_report = _load_tool_module(repo_root, "global_pipeline_app_dispatch_smoke_report")
        report = app_dispatch_smoke_report.build_report(repo_root=repo_root)
        summary = report.get("summary", {})
        ok = (
            report.get("status") == "pass"
            and summary.get("run_status") == "completed"
            and summary.get("persistence_format") == "json"
            and summary.get("round_trip_ok") is True
            and summary.get("unit_count") == 2
            and summary.get("completed_unit_ids") == ["queue_baseline", "relay_followup"]
            and summary.get("runnable_unit_ids") == []
            and summary.get("real_executed_unit_ids") == ["queue_baseline", "relay_followup"]
            and summary.get("readiness_only_unit_ids") == []
            and summary.get("real_execution_scope") == "full_dag_smoke"
            and "queue_metrics" in summary.get("available_artifact_ids", [])
            and "relay_metrics" in summary.get("available_artifact_ids", [])
            and int(summary.get("queue_packets_generated", 0) or 0) > 0
            and int(summary.get("relay_packets_generated", 0) or 0) > 0
            and int(summary.get("packets_generated", 0) or 0) > 0
        )
        details = {
            "status": report.get("status"),
            "dag_path": report.get("dag_path"),
            "summary": summary,
            "check_ids": [check.get("id") for check in report.get("checks", [])],
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "global_pipeline_app_dispatch_smoke_report_contract",
        "Global pipeline app dispatch smoke report contract",
        ok,
        (
            "global pipeline app dispatch smoke executes queue_baseline and relay_followup through real app entries"
            if ok
            else "global pipeline app dispatch smoke report is failing or disconnected"
        ),
        evidence=[
            "tools/global_pipeline_app_dispatch_smoke_report.py",
            "src/agilab/global_pipeline_app_dispatch_smoke.py",
            "src/agilab/apps/builtin/uav_queue_project/src/uav_queue/uav_queue.py",
            "src/agilab/apps/builtin/uav_queue_project/src/uav_queue_worker/uav_queue_worker.py",
            "src/agilab/apps/builtin/uav_relay_queue_project/src/uav_relay_queue/uav_relay_queue.py",
            "src/agilab/apps/builtin/uav_relay_queue_project/src/uav_relay_queue_worker/uav_relay_queue_worker.py",
        ],
        details=details,
        executed=True,
    )


def _check_global_pipeline_operator_state_report(repo_root: Path) -> dict[str, Any]:
    try:
        operator_state_report = _load_tool_module(
            repo_root, "global_pipeline_operator_state_report"
        )
        report = operator_state_report.build_report(repo_root=repo_root)
        summary = report.get("summary", {})
        ok = (
            report.get("status") == "pass"
            and summary.get("run_status") == "ready_for_operator_review"
            and summary.get("persistence_format") == "json"
            and summary.get("round_trip_ok") is True
            and summary.get("visible_unit_count") == 2
            and summary.get("completed_unit_ids") == ["queue_baseline", "relay_followup"]
            and summary.get("source_real_execution_scope") == "full_dag_smoke"
            and summary.get("handoff_count") == 1
            and summary.get("retry_action_count") == 2
            and summary.get("partial_rerun_action_count") == 2
            and "queue_metrics" in summary.get("available_artifact_ids", [])
            and "relay_metrics" in summary.get("available_artifact_ids", [])
        )
        details = {
            "status": report.get("status"),
            "dag_path": report.get("dag_path"),
            "summary": summary,
            "check_ids": [check.get("id") for check in report.get("checks", [])],
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "global_pipeline_operator_state_report_contract",
        "Global pipeline operator state report contract",
        ok,
        (
            "global pipeline operator state report exposes completed units "
            "and available operator actions"
            if ok
            else "global pipeline operator state report is failing or disconnected"
        ),
        evidence=[
            "tools/global_pipeline_operator_state_report.py",
            "src/agilab/global_pipeline_operator_state.py",
            "tools/global_pipeline_app_dispatch_smoke_report.py",
        ],
        details=details,
        executed=True,
    )


def _check_global_pipeline_dependency_view_report(repo_root: Path) -> dict[str, Any]:
    try:
        dependency_view_report = _load_tool_module(
            repo_root, "global_pipeline_dependency_view_report"
        )
        report = dependency_view_report.build_report(repo_root=repo_root)
        summary = report.get("summary", {})
        ok = (
            report.get("status") == "pass"
            and summary.get("run_status") == "ready_for_operator_review"
            and summary.get("persistence_format") == "json"
            and summary.get("round_trip_ok") is True
            and summary.get("node_count") == 2
            and summary.get("edge_count") == 1
            and summary.get("cross_app_edge_count") == 1
            and summary.get("upstream_dependency_count") == 1
            and summary.get("downstream_dependency_count") == 1
            and summary.get("visible_unit_ids") == ["queue_baseline", "relay_followup"]
            and summary.get("source_real_execution_scope") == "full_dag_smoke"
            and "queue_metrics" in summary.get("available_artifact_ids", [])
        )
        details = {
            "status": report.get("status"),
            "dag_path": report.get("dag_path"),
            "summary": summary,
            "check_ids": [check.get("id") for check in report.get("checks", [])],
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "global_pipeline_dependency_view_report_contract",
        "Global pipeline dependency view report contract",
        ok,
        (
            "global pipeline dependency view report exposes cross-app "
            "upstream/downstream adjacency"
            if ok
            else "global pipeline dependency view report is failing or disconnected"
        ),
        evidence=[
            "tools/global_pipeline_dependency_view_report.py",
            "src/agilab/global_pipeline_dependency_view.py",
            "tools/global_pipeline_operator_state_report.py",
        ],
        details=details,
        executed=True,
    )


def _check_global_pipeline_live_state_updates_report(repo_root: Path) -> dict[str, Any]:
    try:
        live_state_updates_report = _load_tool_module(
            repo_root, "global_pipeline_live_state_updates_report"
        )
        report = live_state_updates_report.build_report(repo_root=repo_root)
        summary = report.get("summary", {})
        ok = (
            report.get("status") == "pass"
            and summary.get("run_status") == "ready_for_operator_review"
            and summary.get("persistence_format") == "json"
            and summary.get("round_trip_ok") is True
            and summary.get("update_count") == 6
            and summary.get("graph_update_count") == 1
            and summary.get("unit_update_count") == 2
            and summary.get("artifact_update_count") == 1
            and summary.get("dependency_update_count") == 1
            and summary.get("action_update_count") == 1
            and summary.get("retry_action_count") == 2
            and summary.get("partial_rerun_action_count") == 2
            and summary.get("visible_unit_ids") == ["queue_baseline", "relay_followup"]
            and summary.get("source_real_execution_scope") == "full_dag_smoke"
        )
        details = {
            "status": report.get("status"),
            "dag_path": report.get("dag_path"),
            "summary": summary,
            "check_ids": [check.get("id") for check in report.get("checks", [])],
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "global_pipeline_live_state_updates_report_contract",
        "Global pipeline live state updates report contract",
        ok,
        (
            "global pipeline live state updates report exposes ordered "
            "full-DAG operator update payloads"
            if ok
            else "global pipeline live state updates report is failing or disconnected"
        ),
        evidence=[
            "tools/global_pipeline_live_state_updates_report.py",
            "src/agilab/global_pipeline_live_state_updates.py",
            "tools/global_pipeline_dependency_view_report.py",
        ],
        details=details,
        executed=True,
    )


def _check_global_pipeline_operator_actions_report(repo_root: Path) -> dict[str, Any]:
    try:
        operator_actions_report = _load_tool_module(
            repo_root, "global_pipeline_operator_actions_report"
        )
        report = operator_actions_report.build_report(repo_root=repo_root)
        summary = report.get("summary", {})
        ok = (
            report.get("status") == "pass"
            and summary.get("run_status") == "completed"
            and summary.get("persistence_format") == "json"
            and summary.get("round_trip_ok") is True
            and summary.get("action_request_count") == 2
            and summary.get("completed_action_count") == 2
            and summary.get("retry_execution_count") == 1
            and summary.get("partial_rerun_execution_count") == 1
            and summary.get("real_action_execution_count") == 2
            and summary.get("output_artifact_count") == 4
            and summary.get("event_count") == 4
            and summary.get("source_real_execution_scope") == "full_dag_smoke"
        )
        details = {
            "status": report.get("status"),
            "dag_path": report.get("dag_path"),
            "summary": summary,
            "check_ids": [check.get("id") for check in report.get("checks", [])],
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "global_pipeline_operator_actions_report_contract",
        "Global pipeline operator actions report contract",
        ok,
        (
            "global pipeline operator actions report executes retry and "
            "partial-rerun requests through real app-entry replays"
            if ok
            else "global pipeline operator actions report is failing or disconnected"
        ),
        evidence=[
            "tools/global_pipeline_operator_actions_report.py",
            "src/agilab/global_pipeline_operator_actions.py",
            "tools/global_pipeline_live_state_updates_report.py",
        ],
        details=details,
        executed=True,
    )


def _check_global_pipeline_operator_ui_report(repo_root: Path) -> dict[str, Any]:
    try:
        operator_ui_report = _load_tool_module(
            repo_root, "global_pipeline_operator_ui_report"
        )
        report = operator_ui_report.build_report(repo_root=repo_root)
        summary = report.get("summary", {})
        ok = (
            report.get("status") == "pass"
            and summary.get("run_status") == "ready_for_operator_review"
            and summary.get("persistence_format") == "json+html"
            and summary.get("round_trip_ok") is True
            and summary.get("component_count") == 6
            and summary.get("unit_card_count") == 2
            and summary.get("action_control_count") == 2
            and summary.get("artifact_row_count") == 4
            and summary.get("timeline_update_count") == 6
            and summary.get("supported_action_ids")
            == ["queue_baseline:retry", "relay_followup:partial_rerun"]
            and summary.get("source_real_execution_scope") == "full_dag_smoke"
        )
        details = {
            "status": report.get("status"),
            "dag_path": report.get("dag_path"),
            "summary": summary,
            "check_ids": [check.get("id") for check in report.get("checks", [])],
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "global_pipeline_operator_ui_report_contract",
        "Global pipeline operator UI report contract",
        ok,
        (
            "global pipeline operator UI report renders persisted state and "
            "operator action controls"
            if ok
            else "global pipeline operator UI report is failing or disconnected"
        ),
        evidence=[
            "tools/global_pipeline_operator_ui_report.py",
            "src/agilab/global_pipeline_operator_ui.py",
            "tools/global_pipeline_operator_actions_report.py",
        ],
        details=details,
        executed=True,
    )


def _check_notebook_pipeline_import_report(repo_root: Path) -> dict[str, Any]:
    try:
        notebook_import_report = _load_tool_module(
            repo_root, "notebook_pipeline_import_report"
        )
        report = notebook_import_report.build_report(repo_root=repo_root)
        summary = report.get("summary", {})
        ok = (
            report.get("status") == "pass"
            and summary.get("schema") == "agilab.notebook_pipeline_import.v1"
            and summary.get("run_status") == "imported"
            and summary.get("execution_mode") == "not_executed_import"
            and summary.get("persistence_format") == "json"
            and summary.get("round_trip_ok") is True
            and summary.get("code_cell_count") == 2
            and summary.get("markdown_cell_count") == 2
            and summary.get("pipeline_step_count") == 2
            and summary.get("context_block_count") == 2
            and summary.get("lab_steps_preview_step_count") == 2
            and int(summary.get("env_hint_count", 0) or 0) >= 3
            and int(summary.get("artifact_reference_count", 0) or 0) >= 3
        )
        details = {
            "status": report.get("status"),
            "notebook_path": report.get("notebook_path"),
            "summary": summary,
            "check_ids": [check.get("id") for check in report.get("checks", [])],
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "notebook_pipeline_import_report_contract",
        "Notebook pipeline import report contract",
        ok,
        (
            "notebook-to-pipeline import report preserves code, context, "
            "environment hints, and artifact references without execution"
            if ok
            else "notebook-to-pipeline import report is failing or disconnected"
        ),
        evidence=[
            "tools/notebook_pipeline_import_report.py",
            "src/agilab/notebook_pipeline_import.py",
            "src/agilab/pipeline_editor.py",
            "docs/source/data/notebook_pipeline_import_sample.ipynb",
        ],
        details=details,
    )


def _check_notebook_roundtrip_report(repo_root: Path) -> dict[str, Any]:
    try:
        notebook_roundtrip_report = _load_tool_module(
            repo_root, "notebook_roundtrip_report"
        )
        report = notebook_roundtrip_report.build_report(repo_root=repo_root)
        summary = report.get("summary", {})
        ok = (
            report.get("status") == "pass"
            and summary.get("execution_mode") == "not_executed_import"
            and summary.get("import_mode") == "agilab_supervisor_metadata"
            and summary.get("supervisor_step_count") == 2
            and summary.get("pipeline_step_count") == 2
            and summary.get("lab_steps_round_trip_ok") is True
            and int(summary.get("env_hint_count", 0) or 0) >= 3
            and int(summary.get("artifact_reference_count", 0) or 0) >= 3
        )
        details = {
            "status": report.get("status"),
            "summary": summary,
            "check_ids": [check.get("id") for check in report.get("checks", [])],
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "notebook_roundtrip_report_contract",
        "Notebook round-trip report contract",
        ok,
        (
            "notebook round-trip report preserves lab_steps fields through "
            "supervisor export and non-executing import"
            if ok
            else "notebook round-trip report is failing or disconnected"
        ),
        evidence=[
            "tools/notebook_roundtrip_report.py",
            "src/agilab/notebook_export_support.py",
            "src/agilab/notebook_pipeline_import.py",
        ],
        details=details,
    )


def _check_notebook_union_environment_report(repo_root: Path) -> dict[str, Any]:
    try:
        notebook_union_report = _load_tool_module(
            repo_root, "notebook_union_environment_report"
        )
        report = notebook_union_report.build_report(repo_root=repo_root)
        summary = report.get("summary", {})
        ok = (
            report.get("status") == "pass"
            and summary.get("compatible_union_mode") == "single_kernel_union_candidate"
            and summary.get("incompatible_union_mode") == "supervisor_notebook_required"
            and summary.get("compatible_step_count") == 2
            and summary.get("code_cell_count") == 2
            and int(summary.get("incompatible_issue_count", 0) or 0) >= 2
        )
        details = {
            "status": report.get("status"),
            "summary": summary,
            "check_ids": [check.get("id") for check in report.get("checks", [])],
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "notebook_union_environment_report_contract",
        "Notebook union-environment report contract",
        ok,
        (
            "notebook union-environment report gates single-kernel notebook "
            "generation on compatible runtimes"
            if ok
            else "notebook union-environment report is failing or disconnected"
        ),
        evidence=[
            "tools/notebook_union_environment_report.py",
            "src/agilab/notebook_union_environment.py",
        ],
        details=details,
    )


def _check_data_connector_facility_report(repo_root: Path) -> dict[str, Any]:
    try:
        data_connector_report = _load_tool_module(
            repo_root, "data_connector_facility_report"
        )
        report = data_connector_report.build_report(repo_root=repo_root)
        summary = report.get("summary", {})
        ok = (
            report.get("status") == "pass"
            and summary.get("schema") == "agilab.data_connector_facility.v1"
            and summary.get("run_status") == "validated"
            and summary.get("execution_mode") == "contract_validation_only"
            and summary.get("connector_count") == 3
            and summary.get("supported_kinds") == [
                "object_storage",
                "opensearch",
                "sql",
            ]
            and summary.get("raw_secret_count") == 0
            and summary.get("network_probe_count") == 0
            and summary.get("round_trip_ok") is True
        )
        details = {
            "status": report.get("status"),
            "summary": summary,
            "check_ids": [check.get("id") for check in report.get("checks", [])],
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "data_connector_facility_report_contract",
        "Data connector facility report contract",
        ok,
        (
            "data connector facility report validates SQL, OpenSearch, and "
            "object-storage connector definitions"
            if ok
            else "data connector facility report is failing or disconnected"
        ),
        evidence=[
            "tools/data_connector_facility_report.py",
            "src/agilab/data_connector_facility.py",
            "docs/source/data/data_connectors_sample.toml",
        ],
        details=details,
    )


def _check_data_connector_resolution_report(repo_root: Path) -> dict[str, Any]:
    try:
        data_connector_report = _load_tool_module(
            repo_root, "data_connector_resolution_report"
        )
        report = data_connector_report.build_report(repo_root=repo_root)
        summary = report.get("summary", {})
        ok = (
            report.get("status") == "pass"
            and summary.get("schema") == "agilab.data_connector_resolution.v1"
            and summary.get("run_status") == "resolved"
            and summary.get("execution_mode") == "contract_resolution_only"
            and summary.get("connector_ref_count") == 5
            and summary.get("top_level_ref_count") == 3
            and summary.get("page_connector_ref_count") == 2
            and summary.get("legacy_path_count") == 2
            and summary.get("missing_ref_count") == 0
            and summary.get("network_probe_count") == 0
            and summary.get("catalog_run_status") == "validated"
            and summary.get("legacy_fallback_preserved") is True
            and summary.get("resolved_kinds") == [
                "object_storage",
                "opensearch",
                "sql",
            ]
            and summary.get("round_trip_ok") is True
        )
        details = {
            "status": report.get("status"),
            "summary": summary,
            "check_ids": [check.get("id") for check in report.get("checks", [])],
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "data_connector_resolution_report_contract",
        "Data connector resolution report contract",
        ok,
        (
            "data connector resolution report validates connector-aware "
            "app/page resolution and legacy path fallback"
            if ok
            else "data connector resolution report is failing or disconnected"
        ),
        evidence=[
            "tools/data_connector_resolution_report.py",
            "src/agilab/data_connector_resolution.py",
            "docs/source/data/data_connector_app_settings_sample.toml",
            "docs/source/data/data_connectors_sample.toml",
        ],
        details=details,
    )


def _check_data_connector_health_report(repo_root: Path) -> dict[str, Any]:
    try:
        data_connector_report = _load_tool_module(repo_root, "data_connector_health_report")
        report = data_connector_report.build_report(repo_root=repo_root)
        summary = report.get("summary", {})
        ok = (
            report.get("status") == "pass"
            and summary.get("schema") == "agilab.data_connector_health.v1"
            and summary.get("run_status") == "planned"
            and summary.get("execution_mode") == "health_probe_plan_only"
            and summary.get("connector_count") == 3
            and summary.get("planned_probe_count") == 3
            and summary.get("executed_probe_count") == 0
            and summary.get("opt_in_required_count") == 3
            and summary.get("network_probe_count") == 0
            and summary.get("status_values") == ["unknown_not_probed"]
            and summary.get("unhealthy_count") == 0
            and summary.get("round_trip_ok") is True
        )
        details = {
            "status": report.get("status"),
            "summary": summary,
            "check_ids": [check.get("id") for check in report.get("checks", [])],
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "data_connector_health_report_contract",
        "Data connector health report contract",
        ok,
        (
            "data connector health report plans opt-in connector probes "
            "without executing network checks"
            if ok
            else "data connector health report is failing or disconnected"
        ),
        evidence=[
            "tools/data_connector_health_report.py",
            "src/agilab/data_connector_health.py",
            "docs/source/data/data_connectors_sample.toml",
        ],
        details=details,
    )


def _check_data_connector_ui_preview_report(repo_root: Path) -> dict[str, Any]:
    try:
        data_connector_report = _load_tool_module(
            repo_root,
            "data_connector_ui_preview_report",
        )
        report = data_connector_report.build_report(repo_root=repo_root)
        summary = report.get("summary", {})
        ok = (
            report.get("status") == "pass"
            and summary.get("schema") == "agilab.data_connector_ui_preview.v1"
            and summary.get("run_status") == "ready_for_ui_preview"
            and summary.get("execution_mode") == "static_ui_preview_only"
            and summary.get("persistence_format") == "json+html"
            and summary.get("connector_card_count") == 3
            and summary.get("page_binding_count") == 2
            and summary.get("legacy_fallback_count") == 2
            and summary.get("health_probe_status_count") == 3
            and summary.get("component_count") == 8
            and summary.get("network_probe_count") == 0
            and summary.get("html_rendered") is True
            and summary.get("html_written") is True
            and summary.get("round_trip_ok") is True
        )
        details = {
            "status": report.get("status"),
            "summary": summary,
            "check_ids": [check.get("id") for check in report.get("checks", [])],
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "data_connector_ui_preview_report_contract",
        "Data connector UI preview report contract",
        ok,
        (
            "data connector UI preview report renders static connector state "
            "and provenance without executing network probes"
            if ok
            else "data connector UI preview report is failing or disconnected"
        ),
        evidence=[
            "tools/data_connector_ui_preview_report.py",
            "src/agilab/data_connector_ui_preview.py",
            "docs/source/data/data_connector_app_settings_sample.toml",
            "docs/source/data/data_connectors_sample.toml",
        ],
        details=details,
    )


def _check_data_connector_live_ui_report(repo_root: Path) -> dict[str, Any]:
    try:
        data_connector_report = _load_tool_module(
            repo_root,
            "data_connector_live_ui_report",
        )
        report = data_connector_report.build_report(repo_root=repo_root)
        summary = report.get("summary", {})
        ok = (
            report.get("status") == "pass"
            and summary.get("schema") == "agilab.data_connector_live_ui.v1"
            and summary.get("run_status") == "ready_for_live_ui"
            and summary.get("execution_mode") == "streamlit_render_contract_only"
            and summary.get("connector_card_count") == 3
            and summary.get("page_binding_count") == 2
            and summary.get("legacy_fallback_count") == 2
            and summary.get("health_probe_status_count") == 3
            and summary.get("streamlit_metric_count") == 4
            and summary.get("streamlit_dataframe_count") == 4
            and summary.get("network_probe_count") == 0
            and summary.get("operator_opt_in_required_for_health") is True
            and summary.get("release_decision_hooked") is True
            and summary.get("round_trip_ok") is True
        )
        details = {
            "status": report.get("status"),
            "summary": summary,
            "check_ids": [check.get("id") for check in report.get("checks", [])],
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "data_connector_live_ui_report_contract",
        "Data connector live UI report contract",
        ok,
        (
            "data connector live UI report wires connector provenance into "
            "Release Decision without executing network probes"
            if ok
            else "data connector live UI report is failing or disconnected"
        ),
        evidence=[
            "tools/data_connector_live_ui_report.py",
            "src/agilab/data_connector_live_ui.py",
            "src/agilab/apps-pages/view_release_decision/src/"
            "view_release_decision/view_release_decision.py",
            "docs/source/data/data_connector_app_settings_sample.toml",
            "docs/source/data/data_connectors_sample.toml",
        ],
        details=details,
    )


def _check_data_connector_app_catalogs_report(repo_root: Path) -> dict[str, Any]:
    try:
        data_connector_report = _load_tool_module(
            repo_root,
            "data_connector_app_catalogs_report",
        )
        report = data_connector_report.build_report(repo_root=repo_root)
        summary = report.get("summary", {})
        ok = (
            report.get("status") == "pass"
            and summary.get("schema") == "agilab.data_connector_app_catalogs.v1"
            and summary.get("run_status") == "validated"
            and summary.get("execution_mode") == "app_catalog_validation_only"
            and summary.get("app_catalog_count") == 2
            and summary.get("connector_count") == 6
            and summary.get("page_connector_ref_count") == 5
            and summary.get("legacy_path_count") == 4
            and summary.get("missing_ref_count") == 0
            and summary.get("network_probe_count") == 0
            and summary.get("apps") == ["flight_project", "meteo_forecast_project"]
            and summary.get("round_trip_ok") is True
        )
        details = {
            "status": report.get("status"),
            "summary": summary,
            "check_ids": [check.get("id") for check in report.get("checks", [])],
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "data_connector_app_catalogs_report_contract",
        "Data connector app catalogs report contract",
        ok,
        (
            "data connector app catalogs report validates app-local connector "
            "catalogs without executing network probes"
            if ok
            else "data connector app catalogs report is failing or disconnected"
        ),
        evidence=[
            "tools/data_connector_app_catalogs_report.py",
            "src/agilab/data_connector_app_catalogs.py",
            "src/agilab/apps/builtin/flight_project/src/app_settings.toml",
            "src/agilab/apps/builtin/meteo_forecast_project/src/app_settings.toml",
        ],
        details=details,
    )


def _check_hf_space_smoke_contract(repo_root: Path) -> dict[str, Any]:
    try:
        hf_space_smoke = _load_tool_module(repo_root, "hf_space_smoke")
        specs = hf_space_smoke.route_specs()
        labels = [spec.label for spec in specs]
        required_labels = {
            "streamlit health",
            "base app",
            "flight project",
            "flight view_maps",
            "flight view_maps_network",
        }
        ok = (
            required_labels.issubset(labels)
            and hf_space_smoke.DEFAULT_SPACE_ID == "jpmorard/agilab"
            and callable(hf_space_smoke.check_public_app_tree)
        )
        details = {
            "space_id": hf_space_smoke.DEFAULT_SPACE_ID,
            "space_url": hf_space_smoke.DEFAULT_SPACE_URL,
            "labels": labels,
            "required_labels": sorted(required_labels),
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "hf_space_smoke_contract",
        "Hugging Face Space smoke contract",
        ok,
        (
            "HF smoke covers public routes and guards against non-public app entries"
            if ok
            else "HF smoke contract is incomplete"
        ),
        evidence=["tools/hf_space_smoke.py", "README.md"],
        details=details,
    )


def _check_web_robot_contract(repo_root: Path) -> dict[str, Any]:
    try:
        web_robot = _load_tool_module(repo_root, "agilab_web_robot")
        remote_view = web_robot.resolve_analysis_view_path("view_maps", remote=True)
        analysis_url = web_robot.build_page_url(
            "https://jpmorard-agilab.hf.space",
            "ANALYSIS",
            active_app="flight_project",
            current_page=remote_view,
        )
        ok = (
            web_robot.DEFAULT_TARGET_SECONDS == 120.0
            and "view_maps" in web_robot.ANALYSIS_VIEW_PATHS
            and remote_view == "/app/src/agilab/apps-pages/view_maps/src/view_maps/view_maps.py"
            and "current_page=%2Fapp%2Fsrc%2Fagilab%2Fapps-pages%2Fview_maps" in analysis_url
            and "could not determine the active app" in web_robot.DEFAULT_REJECT_PATTERNS
        )
        details = {
            "target_seconds": web_robot.DEFAULT_TARGET_SECONDS,
            "remote_view": remote_view,
            "analysis_url": analysis_url,
            "route": ["landing", "ORCHESTRATE", "ANALYSIS", "view_maps"],
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "web_ui_robot_contract",
        "Browser-level web UI robot contract",
        ok,
        (
            "Playwright robot covers the real AGILAB web routes and analysis deep link"
            if ok
            else "browser-level web UI robot contract is incomplete"
        ),
        evidence=["tools/agilab_web_robot.py", "README.md"],
        details=details,
    )


def _run_hf_space_smoke(repo_root: Path) -> dict[str, Any]:
    try:
        hf_space_smoke = _load_tool_module(repo_root, "hf_space_smoke")
        summary = hf_space_smoke.run_smoke()
        details = asdict(summary)
        ok = bool(summary.success)
        summary_text = (
            "public HF Space smoke passed"
            if ok
            else "public HF Space smoke failed"
        )
    except Exception as exc:
        ok = False
        summary_text = str(exc)
        details = {"error": str(exc)}
    return _check_result(
        "hf_space_smoke_run",
        "Hugging Face Space smoke run",
        ok,
        summary_text,
        evidence=["tools/hf_space_smoke.py", "https://huggingface.co/spaces/jpmorard/agilab"],
        details=details,
        executed=True,
    )


def _check_production_readiness_report(repo_root: Path) -> dict[str, Any]:
    try:
        production_readiness_report = _load_tool_module(repo_root, "production_readiness_report")
        report = production_readiness_report.build_report(repo_root=repo_root, run_docs_profile=False)
        ok = report.get("status") == "pass" and report.get("supported_score") == "3.0 / 5"
        details = {
            "status": report.get("status"),
            "supported_score": report.get("supported_score"),
            "summary": report.get("summary"),
            "check_ids": [check.get("id") for check in report.get("checks", [])],
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "production_readiness_report_contract",
        "Production-readiness report contract",
        ok,
        (
            "production-readiness evidence report passes and preserves the 3.0 / 5 scope limit"
            if ok
            else "production-readiness evidence report is failing or overclaiming"
        ),
        evidence=["tools/production_readiness_report.py"],
        details=details,
    )


def _check_docs_mirror_stamp(repo_root: Path) -> dict[str, Any]:
    try:
        sync_docs_source = _load_tool_module(repo_root, "sync_docs_source")
        ok, message = sync_docs_source.verify_mirror_stamp(repo_root / "docs" / "source")
    except Exception as exc:
        ok, message = False, str(exc)
    return _check_result(
        "docs_mirror_stamp",
        "Docs mirror stamp",
        ok,
        message,
        evidence=["docs/.docs_source_mirror_stamp.json", "tools/sync_docs_source.py"],
    )


def _check_public_docs_links(repo_root: Path) -> dict[str, Any]:
    paths = [
        repo_root / "README.md",
        repo_root / "docs" / "source" / "compatibility-matrix.rst",
        repo_root / "docs" / "source" / "demos.rst",
        repo_root / "docs" / "source" / "quick-start.rst",
    ]
    required = {
        "README.md": [
            "tools/newcomer_first_proof.py --json",
            "run_manifest.json",
            "tools/reduce_contract_benchmark.py --json",
            "tools/multi_app_dag_report.py --compact",
            "tools/global_pipeline_dag_report.py --compact",
            "tools/global_pipeline_execution_plan_report.py --compact",
            "tools/global_pipeline_runner_state_report.py --compact",
            "tools/global_pipeline_dispatch_state_report.py --compact",
            "tools/global_pipeline_app_dispatch_smoke_report.py --compact",
            "tools/global_pipeline_operator_state_report.py --compact",
            "tools/global_pipeline_dependency_view_report.py --compact",
            "tools/global_pipeline_live_state_updates_report.py --compact",
            "tools/global_pipeline_operator_actions_report.py --compact",
            "tools/global_pipeline_operator_ui_report.py --compact",
            "tools/notebook_pipeline_import_report.py --compact",
            "tools/notebook_roundtrip_report.py --compact",
            "tools/notebook_union_environment_report.py --compact",
            "tools/data_connector_facility_report.py --compact",
            "tools/data_connector_resolution_report.py --compact",
            "tools/data_connector_health_report.py --compact",
            "tools/data_connector_ui_preview_report.py --compact",
            "tools/data_connector_live_ui_report.py --compact",
            "tools/data_connector_app_catalogs_report.py --compact",
            "Overall public evaluation",
            "compatibility matrix",
        ],
        "docs/source/compatibility-matrix.rst": [
            "AGILAB Hugging Face demo",
            "validated",
            "run_manifest.json",
            "tools/compatibility_report.py",
            "tools/hf_space_smoke.py --json",
            "tools/agilab_web_robot.py",
            "tools/production_readiness_report.py",
            "tools/multi_app_dag_report.py",
            "tools/global_pipeline_dag_report.py",
            "tools/global_pipeline_execution_plan_report.py",
            "tools/global_pipeline_runner_state_report.py",
            "tools/global_pipeline_dispatch_state_report.py",
            "tools/global_pipeline_app_dispatch_smoke_report.py",
            "tools/global_pipeline_operator_state_report.py",
            "tools/global_pipeline_dependency_view_report.py",
            "tools/global_pipeline_live_state_updates_report.py",
            "tools/global_pipeline_operator_actions_report.py",
            "tools/global_pipeline_operator_ui_report.py",
            "tools/notebook_pipeline_import_report.py",
            "tools/notebook_roundtrip_report.py",
            "tools/notebook_union_environment_report.py",
            "tools/data_connector_facility_report.py",
            "tools/data_connector_resolution_report.py",
            "tools/data_connector_health_report.py",
            "tools/data_connector_ui_preview_report.py",
            "tools/data_connector_live_ui_report.py",
            "tools/data_connector_app_catalogs_report.py",
            "tools/kpi_evidence_bundle.py",
        ],
        "docs/source/demos.rst": ["https://huggingface.co/spaces/jpmorard/agilab"],
        "docs/source/quick-start.rst": ["tools/newcomer_first_proof.py"],
    }
    missing: dict[str, list[str]] = {}
    try:
        for path in paths:
            rel = str(path.relative_to(repo_root))
            text = _read_text(path)
            missing_for_path = [needle for needle in required[rel] if needle not in text]
            if missing_for_path:
                missing[rel] = missing_for_path
        ok = not missing
        details = {"missing": missing}
    except Exception as exc:
        ok = False
        details = {"error": str(exc), "missing": missing}
    return _check_result(
        "public_docs_evidence_links",
        "Public docs evidence links",
        ok,
        (
            "README and public docs expose the machine-readable evidence reports"
            if ok
            else "README or public docs are missing evidence report references"
        ),
        evidence=[str(path.relative_to(repo_root)) for path in paths],
        details=details,
    )


def _score_formula() -> str:
    terms = " + ".join(f"{score:.1f}" for score in KPI_COMPONENT_SCORES.values())
    return f"({terms}) / {len(KPI_COMPONENT_SCORES)} = {OVERALL_SCORE_RAW}"


def build_bundle(
    *,
    repo_root: Path = REPO_ROOT,
    run_hf_smoke: bool = False,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    checks = [
        _check_workflow_compatibility_report(repo_root),
        _check_newcomer_first_proof_contract(repo_root),
        _check_run_manifest_contract(repo_root),
        _check_multi_app_dag_report(repo_root),
        _check_global_pipeline_dag_report(repo_root),
        _check_global_pipeline_execution_plan_report(repo_root),
        _check_global_pipeline_runner_state_report(repo_root),
        _check_global_pipeline_dispatch_state_report(repo_root),
        _check_global_pipeline_app_dispatch_smoke_report(repo_root),
        _check_global_pipeline_operator_state_report(repo_root),
        _check_global_pipeline_dependency_view_report(repo_root),
        _check_global_pipeline_live_state_updates_report(repo_root),
        _check_global_pipeline_operator_actions_report(repo_root),
        _check_global_pipeline_operator_ui_report(repo_root),
        _check_notebook_pipeline_import_report(repo_root),
        _check_notebook_roundtrip_report(repo_root),
        _check_notebook_union_environment_report(repo_root),
        _check_data_connector_facility_report(repo_root),
        _check_data_connector_resolution_report(repo_root),
        _check_data_connector_health_report(repo_root),
        _check_data_connector_ui_preview_report(repo_root),
        _check_data_connector_live_ui_report(repo_root),
        _check_data_connector_app_catalogs_report(repo_root),
        _check_reduce_contract_adoption_guardrail(repo_root),
        _check_reduce_contract_benchmark(repo_root),
        _check_hf_space_smoke_contract(repo_root),
        _check_web_robot_contract(repo_root),
        _check_production_readiness_report(repo_root),
        _check_docs_mirror_stamp(repo_root),
        _check_public_docs_links(repo_root),
    ]
    if run_hf_smoke:
        checks.append(_run_hf_space_smoke(repo_root))

    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "kpi": "Overall public evaluation",
        "supported_score": SUPPORTED_OVERALL_SCORE,
        "baseline_review_score": BASELINE_REVIEW_SCORE,
        "status": "pass" if failed == 0 else "fail",
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "hf_smoke_executed": run_hf_smoke,
            "score_components": {
                name: f"{score:.1f} / 5"
                for name, score in KPI_COMPONENT_SCORES.items()
            },
            "score_formula": _score_formula(),
            "score_rounding": "one decimal, half up",
        },
        "rationale": (
            "Supports an overall public evaluation of 3.6 / 5 as the one-decimal "
            "mean of the four scored public KPIs: adoption, research "
            "experimentation, engineering prototyping, and bounded "
            "production-readiness evidence. It does not change the alpha status "
            "or claim production MLOps coverage."
        ),
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit machine-readable evidence for AGILAB's overall public evaluation KPI."
    )
    parser.add_argument(
        "--run-hf-smoke",
        action="store_true",
        help="Also execute the public Hugging Face Space smoke test. Default only checks the smoke contract.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact JSON without indentation.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    bundle = build_bundle(run_hf_smoke=args.run_hf_smoke)
    if args.compact:
        print(json.dumps(bundle, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(bundle, indent=2, sort_keys=True))
    return 0 if bundle["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
