from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


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


def test_data_connector_resolution_defensive_helpers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    core_module = _load_module(CORE_PATH, "data_connector_resolution_helpers_test_module")
    settings_path = tmp_path / "app_settings.toml"
    settings_path.write_text("connector_refs = {}\n", encoding="utf-8")
    monkeypatch.setattr(core_module.tomllib, "loads", lambda _text: ["not", "a", "table"])

    with pytest.raises(ValueError, match="TOML table"):
        core_module.load_app_settings(settings_path)

    assert core_module._connector_by_id({"connectors": "bad"}) == {}
    assert core_module._connector_target({"kind": "unknown"}) == ""
    assert core_module._top_level_refs({"connector_refs": "bad"}) == {}
    assert core_module._page_refs({"page_connector_refs": "bad"}) == []
    assert core_module._page_refs({"page_connector_refs": {"analysis": "bad"}}) == []
    assert core_module._legacy_paths({"legacy_paths": "bad"}) == {}
    assert core_module._legacy_paths({"legacy_paths": {"": "x", "empty": ""}}) == {}


def test_data_connector_resolution_catalog_path_resolution_branches(tmp_path: Path) -> None:
    core_module = _load_module(CORE_PATH, "data_connector_resolution_path_test_module")
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    absolute_catalog = tmp_path / "absolute.toml"
    absolute_catalog.touch()
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()
    sibling_catalog = settings_dir / "sibling.toml"
    sibling_catalog.touch()

    assert core_module._settings_catalog_path(
        {"connector_catalog": {"path": str(absolute_catalog)}},
        repo_root,
    ) == absolute_catalog
    assert core_module._settings_catalog_path(
        {"connector_catalog": "not-a-table"},
        repo_root,
    ) == repo_root / core_module.DEFAULT_CONNECTORS_RELATIVE_PATH
    assert core_module._settings_catalog_path(
        {"connector_catalog": {"path": "docs/source/data/connectors.toml"}},
        repo_root,
    ) == repo_root / "docs/source/data/connectors.toml"
    assert core_module._settings_catalog_path(
        {"connector_catalog": {"path": "sibling.toml"}},
        repo_root,
        settings_dir / "app_settings.toml",
    ) == sibling_catalog
    assert core_module._settings_catalog_path(
        {"connector_catalog": {"path": "missing.toml"}},
        repo_root,
        settings_dir / "app_settings.toml",
    ) == repo_root / "missing.toml"


def test_data_connector_resolution_reports_invalid_catalog_and_missing_page_ref(
    tmp_path: Path,
) -> None:
    core_module = _load_module(CORE_PATH, "data_connector_resolution_invalid_test_module")
    settings = {
        "page_connector_refs": {"analysis": {"events": "missing_connector"}},
    }
    facility_state = {
        "schema": "agilab.data_connector_facility.v1",
        "run_status": "invalid",
        "connectors": [],
    }

    state = core_module.build_data_connector_resolution(
        settings=settings,
        facility_state=facility_state,
        settings_path=tmp_path / "app_settings.toml",
        catalog_path=tmp_path / "connectors.toml",
    )

    assert state["run_status"] == "invalid"
    assert state["summary"]["catalog_run_status"] == "invalid"
    assert {
        (issue["location"], issue["message"]) for issue in state["issues"]
    } == {
        ("connector_catalog", "catalog run status is not validated: invalid"),
        (
            "page_connector_refs.analysis.events",
            "unknown connector id: missing_connector",
        ),
    }


def test_data_connector_resolution_persist_accepts_relative_paths(tmp_path: Path) -> None:
    core_module = _load_module(CORE_PATH, "data_connector_resolution_persist_test_module")
    repo_root = tmp_path / "repo"
    settings_path = repo_root / "config" / "app_settings.toml"
    catalog_path = repo_root / "config" / "connectors.toml"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(
        """
[connector_catalog]
path = "connectors.toml"

[connector_refs]
warehouse = "warehouse_sql"
""",
        encoding="utf-8",
    )
    catalog_path.write_text(
        """
[[connectors]]
id = "warehouse_sql"
kind = "sql"
label = "Warehouse SQL"
uri = "sqlite:///warehouse.db"
driver = "sqlite"
query_mode = "read_only"

[[connectors]]
id = "ops_opensearch"
kind = "opensearch"
label = "Operations OpenSearch"
url = "https://opensearch.example.invalid"
index = "agilab-runs-*"
auth_ref = "env:OPENSEARCH_TOKEN"

[[connectors]]
id = "artifact_object_store"
kind = "object_storage"
label = "Artifact Object Store"
provider = "s3"
bucket = "agilab-artifacts"
prefix = "experiments/"
auth_ref = "env:AWS_PROFILE"
""",
        encoding="utf-8",
    )

    proof = core_module.persist_data_connector_resolution(
        repo_root=repo_root,
        output_path=tmp_path / "resolution.json",
        settings_path=Path("config/app_settings.toml"),
        catalog_path=Path("config/connectors.toml"),
    )

    assert proof["ok"] is True
    assert proof["settings_path"] == str(settings_path)
    assert proof["catalog_path"] == str(catalog_path)
