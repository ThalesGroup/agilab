from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


def _ensure_agilab_package_path() -> None:
    package_root = Path("src/agilab").resolve()
    package_spec = importlib.util.spec_from_file_location(
        "agilab",
        package_root / "__init__.py",
        submodule_search_locations=[str(package_root)],
    )
    package = sys.modules.get("agilab")
    if package is None:
        assert package_spec is not None and package_spec.loader is not None
        package = importlib.util.module_from_spec(package_spec)
        sys.modules["agilab"] = package
        package_spec.loader.exec_module(package)
        return

    package_paths = list(getattr(package, "__path__", []) or [])
    package_root_text = str(package_root)
    if package_root_text not in package_paths:
        package.__path__ = [package_root_text, *package_paths]
    package.__spec__ = package_spec
    package.__file__ = str(package_root / "__init__.py")
    package.__package__ = "agilab"


def _load_dag_execution_adapters():
    _ensure_agilab_package_path()
    module_path = Path("src/agilab/dag_execution_adapters.py")
    spec = importlib.util.spec_from_file_location("agilab.dag_execution_adapters", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["agilab.dag_execution_adapters"] = module
    spec.loader.exec_module(module)
    return module


dag_execution_adapters = _load_dag_execution_adapters()


def test_adapter_registry_exposes_uav_queue_to_relay_adapter():
    assert dag_execution_adapters.registered_execution_adapter_ids() == (
        "flight_to_meteo_controlled",
        "uav_queue_to_relay_controlled",
    )


def test_adapter_dispatch_reports_unknown_adapter(tmp_path):
    result = dag_execution_adapters.run_next_adapter_stage(
        "missing-adapter",
        {"units": []},
        dag_execution_adapters.DagExecutionContext(repo_root=Path.cwd(), lab_dir=tmp_path),
    )

    assert not result.ok
    assert result.state == {"units": []}
    assert "No DAG execution adapter is registered" in result.message


def test_flight_to_meteo_adapter_executes_contract_stages(tmp_path):
    state = {
        "created_at": "2026-05-07T00:00:00Z",
        "units": [
            {"id": "flight_context", "dispatch_status": "runnable"},
            {
                "id": "meteo_forecast_review",
                "dispatch_status": "blocked",
                "artifact_dependencies": [{"artifact": "flight_reduce_summary", "from": "flight_context"}],
            },
        ],
        "artifacts": [],
        "events": [],
        "summary": {},
        "provenance": {"real_app_execution": False},
    }
    context = dag_execution_adapters.DagExecutionContext(
        repo_root=Path.cwd(),
        lab_dir=tmp_path,
        now_fn=lambda: "2026-05-07T00:00:00Z",
    )

    first = dag_execution_adapters.run_next_adapter_stage("flight_to_meteo_controlled", state, context)
    second = dag_execution_adapters.run_next_adapter_stage("flight_to_meteo_controlled", first.state, context)

    assert first.ok
    assert first.executed_unit_id == "flight_context"
    assert first.state["summary"]["available_artifact_ids"] == ["flight_reduce_summary"]
    assert first.state["summary"]["controlled_executed_unit_ids"] == ["flight_context"]
    assert first.state["provenance"]["real_app_execution"] is False
    assert first.state["provenance"]["controlled_execution"] is True
    assert first.state["units"][0]["execution_mode"] == "contract_adapter"
    assert first.state["units"][1]["dispatch_status"] == "runnable"
    flight_artifact = tmp_path / ".agilab" / "global_dag_real_runs" / "flight_context" / "flight_reduce_summary.json"
    assert flight_artifact.is_file()
    assert second.ok
    assert second.executed_unit_id == "meteo_forecast_review"
    assert second.state["run_status"] == "completed"
    assert second.state["summary"]["available_artifact_ids"] == [
        "flight_reduce_summary",
        "forecast_metrics",
    ]
