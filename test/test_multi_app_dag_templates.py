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


def _load_module(module_name: str, relative_path: str):
    _ensure_agilab_package_path()
    module_path = Path(relative_path)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


multi_app_dag = _load_module("agilab.multi_app_dag", "src/agilab/multi_app_dag.py")
multi_app_dag_templates = _load_module("agilab.multi_app_dag_templates", "src/agilab/multi_app_dag_templates.py")


def test_app_dag_templates_discovers_active_app_owned_template():
    repo_root = Path.cwd()

    templates = multi_app_dag_templates.discover_app_dag_templates(repo_root, app_name="uav_queue_project")

    paths = [template.repo_relative(repo_root) for template in templates]
    assert paths == ["src/agilab/apps/builtin/uav_queue_project/dag_templates/uav_queue_to_relay.json"]
    assert templates[0].label == "UAV queue to relay"
    payload = json.loads(templates[0].path.read_text(encoding="utf-8"))
    assert multi_app_dag.validate_multi_app_dag(payload, repo_root=repo_root).ok
    assert payload["execution"]["runner_status"] == "controlled_real_stage_execution"
    assert payload["execution"]["adapter"] == "uav_queue_to_relay_controlled"


def test_app_dag_templates_can_fallback_to_all_templates_when_active_app_has_none():
    repo_root = Path.cwd()

    paths = multi_app_dag_templates.app_dag_template_paths(
        repo_root,
        app_name="weather_forecast_project",
        include_all_when_empty=True,
    )

    assert "src/agilab/apps/builtin/flight_telemetry_project/dag_templates/flight_to_weather.json" in paths
    assert "src/agilab/apps/builtin/uav_queue_project/dag_templates/uav_queue_to_relay.json" in paths
    flight_payload = json.loads(
        (repo_root / "src/agilab/apps/builtin/flight_telemetry_project/dag_templates/flight_to_weather.json").read_text(
            encoding="utf-8"
        )
    )
    assert flight_payload["execution"]["runner_status"] == "controlled_contract_stage_execution"
    assert flight_payload["execution"]["adapter"] == "controlled_contract_dag"
    assert flight_payload["nodes"][0]["execution"]["entrypoint"] == "flight_telemetry_project.flight_context"
    assert flight_payload["nodes"][0]["execution"]["params"]["output_format"] == "parquet"
    assert flight_payload["nodes"][0]["execution"]["data_out"] == "flight/dataframe"
    assert flight_payload["nodes"][1]["execution"]["entrypoint"] == "weather_forecast_project.weather_forecast_review"
    assert flight_payload["nodes"][1]["execution"]["params"]["station"] == "Paris-Montsouris"
    assert flight_payload["nodes"][1]["execution"]["data_in"] == "weather_forecast/dataset"
