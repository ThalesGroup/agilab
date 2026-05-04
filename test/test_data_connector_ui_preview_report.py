from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPORT_PATH = Path("tools/data_connector_ui_preview_report.py").resolve()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_data_connector_ui_preview_report_passes(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "data_connector_ui_preview_report_test_module")

    report = module.build_report(
        repo_root=Path.cwd(),
        output_path=tmp_path / "data_connector_ui_preview.json",
        html_output_path=tmp_path / "data_connector_ui_preview.html",
    )

    assert report["report"] == "Data connector UI preview report"
    assert report["status"] == "pass"
    assert report["summary"]["schema"] == "agilab.data_connector_ui_preview.v1"
    assert report["summary"]["run_status"] == "ready_for_ui_preview"
    assert report["summary"]["execution_mode"] == "static_ui_preview_only"
    assert report["summary"]["persistence_format"] == "json+html"
    assert report["summary"]["connector_card_count"] == 5
    assert report["summary"]["page_binding_count"] == 2
    assert report["summary"]["legacy_fallback_count"] == 2
    assert report["summary"]["health_probe_status_count"] == 5
    assert report["summary"]["component_count"] == 10
    assert report["summary"]["network_probe_count"] == 0
    assert report["summary"]["html_rendered"] is True
    assert report["summary"]["round_trip_ok"] is True
    assert report["summary"]["html_written"] is True
    assert {check["id"] for check in report["checks"]} == {
        "data_connector_ui_preview_schema",
        "data_connector_ui_preview_connector_cards",
        "data_connector_ui_preview_page_bindings",
        "data_connector_ui_preview_legacy_fallbacks",
        "data_connector_ui_preview_health_boundary",
        "data_connector_ui_preview_html_render",
        "data_connector_ui_preview_persistence",
        "data_connector_ui_preview_docs_reference",
    }


def test_data_connector_ui_preview_writes_html(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "data_connector_ui_preview_report_html_test_module")
    html_path = tmp_path / "data_connector_ui_preview.html"

    report = module.build_report(
        repo_root=Path.cwd(),
        output_path=tmp_path / "data_connector_ui_preview.json",
        html_output_path=html_path,
    )

    html = html_path.read_text(encoding="utf-8")
    assert report["status"] == "pass"
    assert "<h1>Data Connector UI Preview</h1>" in html
    assert "warehouse_sql" in html
    assert "release_decision" in html
    assert "Legacy path fallbacks" in html
    assert "unknown_not_probed" in html
