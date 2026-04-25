from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPORT_PATH = Path("tools/data_connector_view_surface_report.py").resolve()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_data_connector_view_surface_report_passes(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "data_connector_view_surface_report_test_module")

    report = module.build_report(
        repo_root=Path.cwd(),
        output_path=tmp_path / "data_connector_view_surface.json",
    )

    assert report["report"] == "Data connector view surface report"
    assert report["status"] == "pass"
    assert report["summary"]["schema"] == "agilab.data_connector_view_surface.v1"
    assert report["summary"]["run_status"] == "validated"
    assert report["summary"]["execution_mode"] == "connector_view_surface_contract_only"
    assert report["summary"]["view_surface_count"] == 4
    assert report["summary"]["ready_view_surface_count"] == 4
    assert report["summary"]["missing_view_surface_count"] == 0
    assert report["summary"]["release_decision_surface_count"] == 4
    assert report["summary"]["page_source_loaded"] is True
    assert report["summary"]["live_ui_run_status"] == "ready_for_live_ui"
    assert report["summary"]["connector_card_count"] == 3
    assert report["summary"]["page_binding_count"] == 2
    assert report["summary"]["health_probe_status_count"] == 3
    assert report["summary"]["external_artifact_traceability_ready"] is True
    assert report["summary"]["import_export_provenance_ready"] is True
    assert report["summary"]["network_probe_count"] == 0
    assert report["summary"]["command_execution_count"] == 0
    assert report["summary"]["round_trip_ok"] is True
    assert {check["id"] for check in report["checks"]} == {
        "data_connector_view_surface_schema",
        "data_connector_view_surface_release_decision_mount",
        "data_connector_view_surface_connector_state_provenance",
        "data_connector_view_surface_health_status_panel",
        "data_connector_view_surface_import_export_provenance",
        "data_connector_view_surface_external_artifact_traceability",
        "data_connector_view_surface_no_network",
        "data_connector_view_surface_persistence",
        "data_connector_view_surface_docs_reference",
    }


def test_data_connector_view_surface_persists_surfaces(tmp_path: Path) -> None:
    module = _load_module(
        REPORT_PATH,
        "data_connector_view_surface_report_json_test_module",
    )
    json_path = tmp_path / "data_connector_view_surface.json"

    report = module.build_report(repo_root=Path.cwd(), output_path=json_path)

    assert report["status"] == "pass"
    payload = module.json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "agilab.data_connector_view_surface.v1"
    assert payload["provenance"]["executes_network_probe"] is False
    assert payload["provenance"]["executes_commands"] is False
    assert {surface["id"] for surface in payload["view_surfaces"]} == {
        "connector_state_provenance_panel",
        "connector_health_status_panel",
        "import_export_provenance_panel",
        "external_artifact_traceability_panel",
    }
    assert all(surface["status"] == "ready" for surface in payload["view_surfaces"])
