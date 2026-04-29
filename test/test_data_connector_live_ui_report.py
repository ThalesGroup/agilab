from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPORT_PATH = Path("tools/data_connector_live_ui_report.py").resolve()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_data_connector_live_ui_report_passes(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "data_connector_live_ui_report_test_module")

    report = module.build_report(
        repo_root=Path.cwd(),
        output_path=tmp_path / "data_connector_live_ui.json",
    )

    assert report["report"] == "Data connector live UI report"
    assert report["status"] == "pass"
    assert report["summary"]["schema"] == "agilab.data_connector_live_ui.v1"
    assert report["summary"]["run_status"] == "ready_for_live_ui"
    assert report["summary"]["execution_mode"] == "streamlit_render_contract_only"
    assert report["summary"]["connector_card_count"] == 5
    assert report["summary"]["page_binding_count"] == 2
    assert report["summary"]["legacy_fallback_count"] == 2
    assert report["summary"]["health_probe_status_count"] == 5
    assert report["summary"]["streamlit_metric_count"] == 4
    assert report["summary"]["streamlit_dataframe_count"] == 4
    assert report["summary"]["network_probe_count"] == 0
    assert report["summary"]["operator_opt_in_required_for_health"] is True
    assert report["summary"]["release_decision_hooked"] is True
    assert report["summary"]["round_trip_ok"] is True
    assert {check["id"] for check in report["checks"]} == {
        "data_connector_live_ui_schema",
        "data_connector_live_ui_release_decision_hook",
        "data_connector_live_ui_components",
        "data_connector_live_ui_health_boundary",
        "data_connector_live_ui_release_decision_provenance",
        "data_connector_live_ui_no_network",
        "data_connector_live_ui_persistence",
        "data_connector_live_ui_docs_reference",
    }


def test_data_connector_live_ui_persists_render_contract(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "data_connector_live_ui_report_json_test_module")
    json_path = tmp_path / "data_connector_live_ui.json"

    report = module.build_report(repo_root=Path.cwd(), output_path=json_path)

    assert report["status"] == "pass"
    payload = module.json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "agilab.data_connector_live_ui.v1"
    assert payload["summary"]["streamlit_call_methods"]["dataframe"] == 4
    assert payload["render_payload"]["summary"]["page_ids"] == ["release_decision"]
    assert payload["render_payload"]["provenance"]["executes_network_probe"] is False
