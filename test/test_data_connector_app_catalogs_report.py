from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPORT_PATH = Path("tools/data_connector_app_catalogs_report.py").resolve()
CORE_PATH = Path("src/agilab/data_connector_app_catalogs.py").resolve()


def _load_module(path: Path, name: str):
    src_root = Path.cwd() / "src"
    src_root_text = str(src_root)
    if src_root_text not in sys.path:
        sys.path.insert(0, src_root_text)
    package = sys.modules.get("agilab")
    package_paths = getattr(package, "__path__", None)
    package_path = str(src_root / "agilab")
    if package_paths is not None and package_path not in list(package_paths):
        package_paths.append(package_path)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_data_connector_app_catalogs_report_passes(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "data_connector_app_catalogs_report_test_module")

    report = module.build_report(
        repo_root=Path.cwd(),
        output_path=tmp_path / "data_connector_app_catalogs.json",
    )

    assert report["report"] == "Data connector app catalogs report"
    assert report["status"] == "pass"
    assert report["summary"]["schema"] == "agilab.data_connector_app_catalogs.v1"
    assert report["summary"]["run_status"] == "validated"
    assert report["summary"]["execution_mode"] == "app_catalog_validation_only"
    assert report["summary"]["app_catalog_count"] == 8
    assert report["summary"]["connector_count"] == 24
    assert report["summary"]["page_connector_ref_count"] == 18
    assert report["summary"]["legacy_path_count"] == 16
    assert report["summary"]["missing_ref_count"] == 0
    assert report["summary"]["network_probe_count"] == 0
    assert report["summary"]["apps"] == [
        "execution_pandas_project",
        "execution_polars_project",
        "flight_project",
        "flight_telemetry_project",
        "meteo_forecast_project",
        "uav_queue_project",
        "uav_relay_queue_project",
        "weather_forecast_project",
    ]
    assert report["summary"]["round_trip_ok"] is True
    assert {check["id"] for check in report["checks"]} == {
        "data_connector_app_catalogs_schema",
        "data_connector_app_catalogs_discovery",
        "data_connector_app_catalogs_facility_contract",
        "data_connector_app_catalogs_resolution",
        "data_connector_app_catalogs_legacy_fallbacks",
        "data_connector_app_catalogs_no_network",
        "data_connector_app_catalogs_persistence",
        "data_connector_app_catalogs_docs_reference",
    }


def test_data_connector_app_catalogs_resolve_relative_to_app_settings(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "data_connector_app_catalogs_resolve_test_module")

    report = module.build_report(
        repo_root=Path.cwd(),
        output_path=tmp_path / "data_connector_app_catalogs.json",
    )

    assert report["status"] == "pass"
    payload = module.json.loads(
        (tmp_path / "data_connector_app_catalogs.json").read_text(encoding="utf-8")
    )
    paths = {row["app"]: row["catalog_path"] for row in payload["apps"]}
    assert paths["execution_pandas_project"].endswith(
        "execution_pandas_project/src/connectors/data_connectors.toml"
    )
    assert paths["execution_polars_project"].endswith(
        "execution_polars_project/src/connectors/data_connectors.toml"
    )
    assert paths["flight_project"].endswith("flight_project/src/connectors/data_connectors.toml")
    assert paths["flight_telemetry_project"].endswith("flight_telemetry_project/src/connectors/data_connectors.toml")
    assert paths["meteo_forecast_project"].endswith(
        "meteo_forecast_project/src/connectors/data_connectors.toml"
    )
    assert paths["weather_forecast_project"].endswith(
        "weather_forecast_project/src/connectors/data_connectors.toml"
    )
    assert paths["uav_queue_project"].endswith("uav_queue_project/src/connectors/data_connectors.toml")
    assert paths["uav_relay_queue_project"].endswith(
        "uav_relay_queue_project/src/connectors/data_connectors.toml"
    )


def test_data_connector_app_catalogs_core_reports_invalid_app_catalog_edges(tmp_path: Path, monkeypatch) -> None:
    module = _load_module(CORE_PATH, "data_connector_app_catalogs_core_edges_test_module")
    repo_root = tmp_path / "repo"
    settings_rel = Path("src/agilab/apps/builtin/demo_project/src/app_settings.toml")
    settings_path = repo_root / settings_rel
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text("[", encoding="utf-8")

    assert module._settings_with_catalog(settings_path) is None
    assert module._app_name(Path("app_settings.toml")) == ""

    monkeypatch.setattr(module, "load_app_settings", lambda _path: {"connector_catalog": {"path": "connectors.toml"}})
    monkeypatch.setattr(module, "_settings_catalog_path", lambda *_args, **_kwargs: repo_root / "connectors.toml")
    monkeypatch.setattr(module, "load_connector_catalog", lambda _path: {"connectors": []})
    monkeypatch.setattr(
        module,
        "build_data_connector_facility",
        lambda *_args, **_kwargs: {
            "run_status": "invalid",
            "summary": {"connector_count": 1, "supported_kinds": ["sql"], "network_probe_count": 0},
            "connectors": [{"id": "warehouse"}],
        },
    )
    monkeypatch.setattr(
        module,
        "build_data_connector_resolution",
        lambda **_kwargs: {
            "run_status": "invalid",
            "summary": {
                "connector_ref_count": 1,
                "page_connector_ref_count": 1,
                "legacy_path_count": 0,
                "missing_ref_count": 1,
                "network_probe_count": 0,
            },
            "resolutions": [{"page": "release_decision"}],
        },
    )

    state = module.build_data_connector_app_catalogs(repo_root=repo_root, settings_paths=[settings_rel])

    assert state["run_status"] == "invalid"
    assert state["apps"][0]["app"] == "demo_project"
    assert {issue["location"] for issue in state["issues"]} >= {
        "demo_project.facility",
        "demo_project.resolution",
        "demo_project",
    }
