from __future__ import annotations

import importlib.util
import json
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


def _load_dag_execution_registry():
    _ensure_agilab_package_path()
    module_path = Path("src/agilab/dag_execution_registry.py")
    spec = importlib.util.spec_from_file_location("agilab.dag_execution_registry", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["agilab.dag_execution_registry"] = module
    spec.loader.exec_module(module)
    return module


dag_execution_registry = _load_dag_execution_registry()


def _template_path(repo_root: Path) -> Path:
    return repo_root / dag_execution_registry.UAV_QUEUE_TEMPLATE_RELATIVE_PATH


def _flight_template_path(repo_root: Path) -> Path:
    return repo_root / dag_execution_registry.FLIGHT_TO_WEATHER_TEMPLATE_RELATIVE_PATH


def _uav_units() -> list[dict[str, str]]:
    return [
        {"id": "queue_baseline", "app": "uav_queue_project"},
        {"id": "relay_followup", "app": "uav_relay_queue_project"},
    ]


def _flight_units() -> list[dict[str, object]]:
    return [
        {
            "id": "flight_context",
            "app": "flight_telemetry_project",
            "execution_contract": {"entrypoint": "flight_telemetry_project.flight_context"},
            "produces": [
                {
                    "artifact": "flight_reduce_summary",
                    "path": "flight_analysis/reduce_summary_worker_0.json",
                }
            ],
        },
        {
            "id": "weather_forecast_review",
            "app": "weather_forecast_project",
            "execution_contract": {"entrypoint": "weather_forecast_project.weather_forecast_review"},
            "produces": [
                {
                    "artifact": "forecast_metrics",
                    "path": "forecast_analysis/forecast_metrics.json",
                }
            ],
        },
    ]


def test_registry_supports_checked_in_uav_template():
    repo_root = Path.cwd()

    adapter = dag_execution_registry.registered_adapter_for_source(_template_path(repo_root), repo_root)
    support = dag_execution_registry.resolve_real_run_support(
        units=_uav_units(),
        dag_path=_template_path(repo_root),
        repo_root=repo_root,
    )

    assert adapter == dag_execution_registry.UAV_QUEUE_TO_RELAY_ADAPTER
    assert support.supported
    assert support.status == "Executable"
    assert support.adapter == "uav_queue_to_relay_controlled"
    assert "checked-in UAV queue-to-relay DAG" in support.message


def test_registry_supports_checked_in_flight_template():
    repo_root = Path.cwd()

    adapter = dag_execution_registry.registered_adapter_for_source(_flight_template_path(repo_root), repo_root)
    support = dag_execution_registry.resolve_real_run_support(
        units=_flight_units(),
        dag_path=_flight_template_path(repo_root),
        repo_root=repo_root,
    )

    assert adapter == dag_execution_registry.FLIGHT_TO_WEATHER_DAG_ADAPTER
    assert support.supported
    assert support.status == "Executable"
    assert support.adapter == "controlled_contract_dag"
    assert "checked-in app-owned DAG" in support.message


def test_registry_supports_marker_opted_app_owned_contract_template(tmp_path):
    repo_root = tmp_path
    dag_path = (
        repo_root
        / "src"
        / "agilab"
        / "apps"
        / "builtin"
        / "alpha_project"
        / "dag_templates"
        / "alpha_to_beta.json"
    )
    dag_path.parent.mkdir(parents=True)
    dag_path.write_text(
        json.dumps(
            {
                "schema": "agilab.multi_app_dag.v1",
                "dag_id": "alpha-to-beta",
                "execution": {
                    "mode": "sequential_dependency_order",
                    "runner_status": "controlled_contract_stage_execution",
                    "adapter": "controlled_contract_dag",
                },
                "nodes": [
                    {
                        "id": "alpha",
                        "app": "alpha_project",
                        "execution": {"entrypoint": "alpha_project.alpha"},
                        "produces": [{"id": "alpha_metrics", "path": "alpha/metrics.json"}],
                    },
                    {
                        "id": "beta",
                        "app": "beta_project",
                        "execution": {"entrypoint": "beta_project.beta"},
                        "produces": [{"id": "beta_metrics", "path": "beta/metrics.json"}],
                    },
                ],
                "edges": [],
            }
        ),
        encoding="utf-8",
    )

    support = dag_execution_registry.resolve_real_run_support(
        units=[
            {
                "id": "alpha",
                "app": "alpha_project",
                "execution_contract": {"entrypoint": "alpha_project.alpha"},
                "produces": [{"artifact": "alpha_metrics", "path": "alpha/metrics.json"}],
            },
            {
                "id": "beta",
                "app": "beta_project",
                "execution_contract": {"entrypoint": "beta_project.beta"},
                "produces": [{"artifact": "beta_metrics", "path": "beta/metrics.json"}],
            },
        ],
        dag_path=dag_path,
        repo_root=repo_root,
    )

    assert support.supported
    assert support.adapter == "controlled_contract_dag"
    assert "checked-in app-owned DAG" in support.message


def test_registry_rejects_marker_opted_contract_template_without_stage_contract(tmp_path):
    repo_root = tmp_path
    dag_path = (
        repo_root
        / "src"
        / "agilab"
        / "apps"
        / "builtin"
        / "alpha_project"
        / "dag_templates"
        / "alpha_to_beta.json"
    )
    dag_path.parent.mkdir(parents=True)
    dag_path.write_text(
        json.dumps(
            {
                "schema": "agilab.multi_app_dag.v1",
                "dag_id": "alpha-to-beta",
                "execution": {
                    "mode": "sequential_dependency_order",
                    "runner_status": "controlled_contract_stage_execution",
                    "adapter": "controlled_contract_dag",
                },
                "nodes": [
                    {"id": "alpha", "app": "alpha_project"},
                    {"id": "beta", "app": "beta_project"},
                ],
                "edges": [],
            }
        ),
        encoding="utf-8",
    )

    support = dag_execution_registry.resolve_real_run_support(
        units=[
            {
                "id": "alpha",
                "app": "alpha_project",
                "produces": [{"artifact": "alpha_metrics", "path": "alpha/metrics.json"}],
            }
        ],
        dag_path=dag_path,
        repo_root=repo_root,
    )

    assert not support.supported
    assert "must declare `execution.entrypoint` or `execution.command`" in support.message


def test_registry_reports_no_selected_dag():
    support = dag_execution_registry.resolve_real_run_support(
        units=_uav_units(),
        dag_path=None,
        repo_root=Path.cwd(),
    )

    assert not support.supported
    assert support.message == "No DAG contract is selected."


def test_registry_keeps_copied_template_preview_only(tmp_path):
    repo_root = Path.cwd()
    copied_path = tmp_path / "uav_queue_to_relay.json"
    copied_path.write_text(_template_path(repo_root).read_text(encoding="utf-8"), encoding="utf-8")

    support = dag_execution_registry.resolve_real_run_support(
        units=_uav_units(),
        dag_path=copied_path,
        repo_root=repo_root,
    )

    assert not support.supported
    assert support.status == "Preview-only"
    assert "Workspace and custom DAGs remain preview-only" in support.message


def test_registry_rejects_required_stage_shape_mismatch():
    repo_root = Path.cwd()

    missing = dag_execution_registry.resolve_real_run_support(
        units=[{"id": "queue_baseline", "app": "uav_queue_project"}],
        dag_path=_template_path(repo_root),
        repo_root=repo_root,
    )
    wrong_app = dag_execution_registry.resolve_real_run_support(
        units=[
            {"id": "queue_baseline", "app": "flight_telemetry_project"},
            {"id": "relay_followup", "app": "uav_relay_queue_project"},
        ],
        dag_path=_template_path(repo_root),
        repo_root=repo_root,
    )

    assert not missing.supported
    assert "does not contain the controlled queue and relay stages" in missing.message
    assert not wrong_app.supported
    assert "does not map queue and relay stages" in wrong_app.message


def test_registry_reports_missing_adapter_marker(tmp_path):
    repo_root = Path.cwd()
    payload = json.loads(_template_path(repo_root).read_text(encoding="utf-8"))
    payload["execution"].pop("adapter")
    dag_path = tmp_path / "missing-adapter.json"
    dag_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    support = dag_execution_registry.adapter_marker_status(
        dag_path,
        dag_execution_registry.UAV_QUEUE_TO_RELAY_ADAPTER,
    )

    assert support is not None
    assert not support.supported
    assert "missing the controlled execution adapter marker" in support.message


def test_registry_reports_missing_runner_status_marker(tmp_path):
    repo_root = Path.cwd()
    payload = json.loads(_template_path(repo_root).read_text(encoding="utf-8"))
    payload["execution"].pop("runner_status")
    dag_path = tmp_path / "missing-runner-status.json"
    dag_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    support = dag_execution_registry.adapter_marker_status(
        dag_path,
        dag_execution_registry.UAV_QUEUE_TO_RELAY_ADAPTER,
    )

    assert support is not None
    assert not support.supported
    assert "missing the controlled execution status marker" in support.message


def test_registry_keeps_legacy_sample_executable_for_existing_docs_flow():
    repo_root = Path.cwd()

    support = dag_execution_registry.resolve_real_run_support(
        units=_uav_units(),
        dag_path=repo_root / dag_execution_registry.GLOBAL_DAG_SAMPLE_RELATIVE_PATH,
        repo_root=repo_root,
    )

    assert support.supported
    assert support.adapter == "uav_queue_to_relay_controlled"
