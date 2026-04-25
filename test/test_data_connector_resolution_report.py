from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPORT_PATH = Path("tools/data_connector_resolution_report.py").resolve()
CORE_PATH = Path("src/agilab/data_connector_resolution.py").resolve()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_data_connector_resolution_report_passes(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "data_connector_resolution_report_test_module")

    report = module.build_report(
        repo_root=Path.cwd(),
        output_path=tmp_path / "data_connector_resolution.json",
    )

    assert report["report"] == "Data connector resolution report"
    assert report["status"] == "pass"
    assert report["summary"]["schema"] == "agilab.data_connector_resolution.v1"
    assert report["summary"]["run_status"] == "resolved"
    assert report["summary"]["execution_mode"] == "contract_resolution_only"
    assert report["summary"]["connector_ref_count"] == 5
    assert report["summary"]["top_level_ref_count"] == 3
    assert report["summary"]["resolved_connector_ref_count"] == 5
    assert report["summary"]["page_connector_ref_count"] == 2
    assert report["summary"]["legacy_path_count"] == 2
    assert report["summary"]["missing_ref_count"] == 0
    assert report["summary"]["network_probe_count"] == 0
    assert report["summary"]["catalog_run_status"] == "validated"
    assert report["summary"]["legacy_fallback_preserved"] is True
    assert report["summary"]["resolved_kinds"] == ["object_storage", "opensearch", "sql"]
    assert report["summary"]["round_trip_ok"] is True
    assert {check["id"] for check in report["checks"]} == {
        "data_connector_resolution_schema",
        "data_connector_resolution_app_refs",
        "data_connector_resolution_page_refs",
        "data_connector_resolution_legacy_fallback",
        "data_connector_resolution_no_network",
        "data_connector_resolution_persistence",
        "data_connector_resolution_docs_reference",
    }


def test_data_connector_resolution_reports_missing_connector(tmp_path: Path) -> None:
    core_module = _load_module(CORE_PATH, "data_connector_resolution_core_test_module")
    settings = {
        "connector_refs": {"missing": "missing_connector"},
        "legacy_paths": {"artifact_root": "~/export/demo"},
    }
    facility_state = {
        "schema": "agilab.data_connector_facility.v1",
        "run_status": "validated",
        "connectors": [],
    }

    state = core_module.build_data_connector_resolution(
        settings=settings,
        facility_state=facility_state,
        settings_path=tmp_path / "app_settings.toml",
        catalog_path=tmp_path / "connectors.toml",
    )

    assert state["run_status"] == "invalid"
    assert state["summary"]["connector_ref_count"] == 1
    assert state["summary"]["top_level_ref_count"] == 1
    assert state["summary"]["resolved_connector_ref_count"] == 0
    assert state["summary"]["missing_ref_count"] == 1
    assert state["summary"]["legacy_path_count"] == 1
    assert state["legacy_fallbacks"][0]["status"] == "legacy_path_fallback"
    assert state["legacy_fallbacks"][0]["source"] == "legacy_paths"
    assert state["issues"] == [
        {
            "level": "error",
            "location": "connector_refs.missing",
            "message": "unknown connector id: missing_connector",
        }
    ]
