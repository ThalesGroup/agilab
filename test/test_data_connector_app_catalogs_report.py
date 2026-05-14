from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPORT_PATH = Path("tools/data_connector_app_catalogs_report.py").resolve()


def _load_module(path: Path, name: str):
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
    assert report["summary"]["app_catalog_count"] == 6
    assert report["summary"]["connector_count"] == 18
    assert report["summary"]["page_connector_ref_count"] == 15
    assert report["summary"]["legacy_path_count"] == 12
    assert report["summary"]["missing_ref_count"] == 0
    assert report["summary"]["network_probe_count"] == 0
    assert report["summary"]["apps"] == [
        "execution_pandas_project",
        "execution_polars_project",
        "flight_telemetry_project",
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
    assert paths["flight_telemetry_project"].endswith("flight_telemetry_project/src/connectors/data_connectors.toml")
    assert paths["weather_forecast_project"].endswith(
        "weather_forecast_project/src/connectors/data_connectors.toml"
    )
    assert paths["uav_queue_project"].endswith("uav_queue_project/src/connectors/data_connectors.toml")
    assert paths["uav_relay_queue_project"].endswith(
        "uav_relay_queue_project/src/connectors/data_connectors.toml"
    )
