from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPORT_PATH = Path("tools/data_connector_health_report.py").resolve()
CORE_PATH = Path("src/agilab/data_connector_health.py").resolve()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_data_connector_health_report_passes(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "data_connector_health_report_test_module")

    report = module.build_report(
        repo_root=Path.cwd(),
        output_path=tmp_path / "data_connector_health.json",
    )

    assert report["report"] == "Data connector health report"
    assert report["status"] == "pass"
    assert report["summary"]["schema"] == "agilab.data_connector_health.v1"
    assert report["summary"]["run_status"] == "planned"
    assert report["summary"]["execution_mode"] == "health_probe_plan_only"
    assert report["summary"]["connector_count"] == 3
    assert report["summary"]["planned_probe_count"] == 3
    assert report["summary"]["executed_probe_count"] == 0
    assert report["summary"]["opt_in_required_count"] == 3
    assert report["summary"]["network_probe_count"] == 0
    assert report["summary"]["unknown_status_count"] == 3
    assert report["summary"]["unhealthy_count"] == 0
    assert report["summary"]["probe_types"] == [
        "bucket_prefix_list",
        "driver_connectivity",
        "index_head",
    ]
    assert report["summary"]["status_values"] == ["unknown_not_probed"]
    assert report["summary"]["round_trip_ok"] is True
    assert {check["id"] for check in report["checks"]} == {
        "data_connector_health_schema",
        "data_connector_health_probe_plan",
        "data_connector_health_opt_in_boundary",
        "data_connector_health_no_network",
        "data_connector_health_status_values",
        "data_connector_health_persistence",
        "data_connector_health_docs_reference",
    }


def test_data_connector_health_rejects_invalid_catalog(tmp_path: Path) -> None:
    core_module = _load_module(CORE_PATH, "data_connector_health_core_test_module")
    catalog = {
        "connectors": [
            {
                "id": "broken_sql",
                "kind": "sql",
                "label": "Broken SQL",
                "uri": "postgresql://example.invalid/agilab",
            }
        ]
    }

    state = core_module.build_data_connector_health(
        catalog,
        source_path=tmp_path / "connectors.toml",
    )

    assert state["run_status"] == "invalid"
    assert state["summary"]["planned_probe_count"] == 1
    assert state["summary"]["executed_probe_count"] == 0
    assert state["summary"]["network_probe_count"] == 0
    assert state["issues"] == [
        {
            "level": "error",
            "location": "connector_catalog",
            "message": "connector catalog must validate before health planning",
        }
    ]
