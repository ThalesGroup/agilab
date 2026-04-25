from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPORT_PATH = Path("tools/data_connector_facility_report.py").resolve()
CORE_PATH = Path("src/agilab/data_connector_facility.py").resolve()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_data_connector_facility_report_passes(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "data_connector_facility_report_test_module")

    report = module.build_report(
        repo_root=Path.cwd(),
        output_path=tmp_path / "data_connectors.json",
    )

    assert report["report"] == "Data connector facility report"
    assert report["status"] == "pass"
    assert report["summary"]["schema"] == "agilab.data_connector_facility.v1"
    assert report["summary"]["run_status"] == "validated"
    assert report["summary"]["execution_mode"] == "contract_validation_only"
    assert report["summary"]["connector_count"] == 3
    assert report["summary"]["supported_kinds"] == [
        "object_storage",
        "opensearch",
        "sql",
    ]
    assert report["summary"]["raw_secret_count"] == 0
    assert report["summary"]["network_probe_count"] == 0
    assert report["summary"]["round_trip_ok"] is True
    assert {check["id"] for check in report["checks"]} == {
        "data_connector_facility_schema",
        "data_connector_facility_first_class_targets",
        "data_connector_facility_required_fields",
        "data_connector_facility_secret_boundary",
        "data_connector_facility_persistence",
        "data_connector_facility_docs_reference",
    }


def test_data_connector_facility_rejects_mixed_secret_and_missing_kind(tmp_path: Path) -> None:
    core_module = _load_module(CORE_PATH, "data_connector_facility_core_test_module")
    catalog = {
        "connectors": [
            {
                "id": "bad_sql",
                "kind": "sql",
                "label": "Bad SQL",
                "uri": "postgresql://host/db?password=plaintext",
                "driver": "postgresql",
                "query_mode": "write",
            }
        ]
    }

    state = core_module.build_data_connector_facility(
        catalog,
        source_path=tmp_path / "bad.toml",
    )

    assert state["run_status"] == "invalid"
    assert state["summary"]["connector_count"] == 1
    assert state["summary"]["raw_secret_count"] == 1
    assert "opensearch" in state["summary"]["missing_kinds"]
    assert "object_storage" in state["summary"]["missing_kinds"]
    assert {
        issue["location"]
        for issue in state["issues"]
    } == {"bad_sql", "bad_sql.uri", "connectors"}
