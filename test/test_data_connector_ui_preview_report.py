from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPORT_PATH = Path("tools/data_connector_ui_preview_report.py").resolve()
CORE_PATH = Path("src/agilab/data_connector_ui_preview.py").resolve()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_minimal_valid_catalog(path: Path) -> None:
    path.write_text(
        """
[[connectors]]
id = "warehouse_sql"
kind = "sql"
label = "Warehouse SQL"
uri = "postgresql://warehouse.example.invalid/agilab"
driver = "postgresql"
query_mode = "read_only"

[[connectors]]
id = "ops_search"
kind = "opensearch"
label = "Operations Search"
provider = "opensearch"
url = "search.example.invalid"
index = "agilab-runs"
auth_ref = "env:OPENSEARCH_TOKEN"

[[connectors]]
id = "artifact_store"
kind = "object_storage"
label = "Artifact Store"
provider = "s3"
bucket = "agilab-artifacts"
prefix = "experiments/"
auth_ref = "env:AWS_PROFILE"
""".strip(),
        encoding="utf-8",
    )


def _write_minimal_settings(path: Path) -> None:
    path.write_text(
        """
[connector_refs]
training_sql = "warehouse_sql"

[page_connector_refs.release_decision]
evidence_index = "ops_search"
artifact_store = "artifact_store"

[legacy_paths]
artifact_root = "~/export/agilab/artifacts"
""".strip(),
        encoding="utf-8",
    )


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


def test_data_connector_ui_preview_accepts_relative_settings_and_catalog_paths(
    tmp_path: Path,
) -> None:
    core_module = _load_module(CORE_PATH, "data_connector_ui_preview_relative_paths_module")
    settings = tmp_path / "settings.toml"
    catalog = tmp_path / "connectors.toml"
    json_path = tmp_path / "preview.json"
    html_path = tmp_path / "preview.html"
    _write_minimal_settings(settings)
    _write_minimal_valid_catalog(catalog)

    result = core_module.persist_data_connector_ui_preview(
        repo_root=tmp_path,
        output_path=json_path,
        html_output_path=html_path,
        settings_path=Path("settings.toml"),
        catalog_path=Path("connectors.toml"),
    )

    assert result["ok"] is True
    assert result["settings_path"] == str(settings)
    assert result["catalog_path"] == str(catalog)
    assert result["html_written"] is True
    assert result["state"]["summary"]["connector_card_count"] == 3
    assert result["state"]["summary"]["page_binding_count"] == 2
    assert result["state"]["summary"]["legacy_fallback_count"] == 1


def test_data_connector_ui_preview_reports_invalid_source_states(tmp_path: Path) -> None:
    core_module = _load_module(CORE_PATH, "data_connector_ui_preview_invalid_sources_module")
    settings = {"connector_refs": {"missing": "missing_connector"}}
    catalog = {
        "connectors": [
            {
                "id": "broken_sql",
                "kind": "sql",
                "label": "Broken SQL",
                "uri": "postgresql://warehouse.example.invalid/agilab",
            }
        ]
    }

    state = core_module.build_data_connector_ui_preview(
        settings=settings,
        catalog=catalog,
        settings_path=tmp_path / "settings.toml",
        catalog_path=tmp_path / "connectors.toml",
    )

    assert state["run_status"] == "invalid"
    assert [issue["location"] for issue in state["issues"]] == [
        "facility",
        "resolution",
        "health",
    ]
    assert "not ready" in state["issues"][0]["message"]
