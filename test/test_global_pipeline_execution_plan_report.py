from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPORT_PATH = Path("tools/global_pipeline_execution_plan_report.py").resolve()
CORE_PATH = Path("src/agilab/global_pipeline_execution_plan.py").resolve()


def _load_report_module():
    spec = importlib.util.spec_from_file_location("global_pipeline_execution_plan_report_test_module", REPORT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_core_module():
    spec = importlib.util.spec_from_file_location("global_pipeline_execution_plan_test_module", CORE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_execution_plan_report_builds_pending_units() -> None:
    module = _load_report_module()

    report = module.build_report(repo_root=Path.cwd())

    assert report["report"] == "Global pipeline execution plan report"
    assert report["status"] == "pass"
    assert report["dag_path"] == "docs/source/data/multi_app_dag_sample.json"
    assert report["summary"]["schema"] == "agilab.global_pipeline_execution_plan.v1"
    assert report["summary"]["runner_status"] == "not_executed"
    assert report["summary"]["unit_count"] == 2
    assert report["summary"]["pending_count"] == 2
    assert report["summary"]["not_executed_count"] == 2
    assert report["summary"]["ready_unit_ids"] == ["queue_baseline"]
    assert report["summary"]["blocked_unit_ids"] == ["relay_followup"]
    assert report["summary"]["artifact_dependency_count"] == 1
    assert report["summary"]["execution_order"] == ["queue_baseline", "relay_followup"]
    assert {check["id"] for check in report["checks"]} == {
        "global_pipeline_execution_plan_schema",
        "global_pipeline_execution_plan_order",
        "global_pipeline_execution_plan_state",
        "global_pipeline_execution_plan_artifact_dependencies",
        "global_pipeline_execution_plan_provenance",
        "global_pipeline_execution_plan_docs_reference",
    }


def test_execution_plan_units_keep_dependencies_and_provenance() -> None:
    module = _load_core_module()

    plan = module.build_execution_plan(repo_root=Path.cwd())

    assert plan.ok is True
    first, second = plan.runnable_units
    assert first["id"] == "queue_baseline"
    assert first["ready"] is True
    assert first["depends_on"] == []
    assert first["produces"] == [
        {
            "artifact": "queue_metrics",
            "kind": "summary_metrics",
            "path": "queue_analysis/uav_queue_summary_metrics.json",
        }
    ]
    assert second["id"] == "relay_followup"
    assert second["ready"] is False
    assert second["depends_on"] == ["queue_baseline"]
    assert second["artifact_dependencies"] == [
        {
            "artifact": "queue_metrics",
            "from": "queue_baseline",
            "from_app": "uav_queue_project",
            "handoff": "Use base queue summary metrics as the relay scenario context.",
            "source_path": "queue_analysis/uav_queue_summary_metrics.json",
        }
    ]
    assert second["provenance"] == {
        "contract_app": "uav_relay_queue_project",
        "contract_node_id": "relay_followup",
        "pipeline_view": "src/agilab/apps/builtin/uav_relay_queue_project/pipeline_view.dot",
        "planning_mode": "read_only",
        "source_dag": "docs/source/data/multi_app_dag_sample.json",
        "source_graph_runner_status": "not_executed",
        "source_graph_schema": "agilab.global_pipeline_dag.v1",
    }


def test_execution_plan_carries_app_template_execution_contracts() -> None:
    module = _load_core_module()

    plan = module.build_execution_plan(
        repo_root=Path.cwd(),
        dag_path=Path("src/agilab/apps/builtin/flight_telemetry_project/dag_templates/flight_to_weather.json"),
    )

    assert plan.ok is True
    first, second = plan.runnable_units
    assert first["execution_contract"]["entrypoint"] == "flight_telemetry_project.flight_context"
    assert first["execution_contract"]["params"]["output_format"] == "parquet"
    assert first["execution_contract"]["data_in"] == "flight/dataset"
    assert first["execution_contract"]["stages"] == []
    assert second["execution_contract"]["entrypoint"] == "weather_forecast_project.weather_forecast_review"
    assert second["execution_contract"]["params"]["station"] == "Paris-Montsouris"
    assert second["execution_contract"]["data_out"] == "weather_forecast/results"


def test_execution_plan_report_handles_load_failure(tmp_path: Path) -> None:
    module = _load_report_module()
    missing = tmp_path / "missing.json"

    report = module.build_report(repo_root=Path.cwd(), dag_path=missing)

    assert report["status"] == "fail"
    assert report["checks"] == [
        {
            "details": {
                "error": f"[Errno 2] No such file or directory: '{missing}'",
            },
            "evidence": [str(missing)],
            "id": "global_pipeline_execution_plan_load",
            "label": "Global pipeline execution plan load",
            "status": "fail",
            "summary": "global pipeline execution plan could not be assembled",
        }
    ]
