from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPORT_PATH = Path("tools/data_connector_live_endpoint_smoke_report.py").resolve()
CORE_PATH = Path("src/agilab/data_connector_live_endpoint_smoke.py").resolve()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_live_endpoint_smoke_report_passes_public_contract(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "data_connector_live_smoke_report_test_module")

    report = module.build_report(
        repo_root=Path.cwd(),
        output_path=tmp_path / "data_connector_live_endpoint_smoke.json",
    )

    assert report["report"] == "Data connector live endpoint smoke report"
    assert report["status"] == "pass"
    assert report["summary"]["schema"] == "agilab.data_connector_live_endpoint_smoke.v1"
    assert report["summary"]["execution_mode"] == "live_endpoint_smoke_plan_only"
    assert report["summary"]["connector_count"] == 3
    assert report["summary"]["planned_endpoint_count"] == 3
    assert report["summary"]["executed_endpoint_count"] == 0
    assert report["summary"]["network_probe_count"] == 0
    assert report["summary"]["sqlite_smoke_healthy_count"] == 1
    assert {check["id"] for check in report["checks"]} == {
        "data_connector_live_endpoint_smoke_schema",
        "data_connector_live_endpoint_smoke_plan",
        "data_connector_live_endpoint_smoke_public_boundary",
        "data_connector_live_endpoint_smoke_sqlite_execution",
        "data_connector_live_endpoint_smoke_persistence",
        "data_connector_live_endpoint_smoke_docs_reference",
    }


def test_live_endpoint_smoke_executes_allowed_sqlite_only(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "data_connector_live_smoke_sqlite_test_module")
    catalog = module._sqlite_smoke_catalog(tmp_path / "smoke.sqlite")
    core = _load_module(CORE_PATH, "data_connector_live_smoke_core_test_module")

    state = core.build_data_connector_live_endpoint_smoke(
        catalog,
        source_path=tmp_path / "catalog.toml",
        execute=True,
        allowed_connector_ids=["local_sqlite"],
    )

    assert state["run_status"] == "smoke_complete"
    assert state["summary"]["executed_endpoint_count"] == 1
    assert state["summary"]["healthy_count"] == 1
    assert state["summary"]["network_probe_count"] == 0
    rows = {row["connector_id"]: row for row in state["endpoint_smokes"]}
    assert rows["local_sqlite"]["status"] == "healthy"
    assert rows["ops_opensearch"]["execution_status"] == "skipped_not_allowed"
    assert rows["artifact_object_store"]["execution_status"] == "skipped_not_allowed"


def test_live_endpoint_smoke_execute_requires_allow_list(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "data_connector_live_smoke_allow_list_test")
    catalog = module._sqlite_smoke_catalog(tmp_path / "smoke.sqlite")
    core = _load_module(CORE_PATH, "data_connector_live_smoke_allow_list_core")

    state = core.build_data_connector_live_endpoint_smoke(
        catalog,
        source_path=tmp_path / "catalog.toml",
        execute=True,
    )

    assert state["summary"]["executed_endpoint_count"] == 0
    assert state["summary"]["network_probe_count"] == 0
    assert {row["execution_status"] for row in state["endpoint_smokes"]} == {
        "skipped_not_allowed"
    }


def test_live_endpoint_smoke_skips_missing_credentials(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPENSEARCH_TOKEN", raising=False)
    module = _load_module(REPORT_PATH, "data_connector_live_smoke_missing_creds_test")
    catalog = module._sqlite_smoke_catalog(tmp_path / "smoke.sqlite")
    core = _load_module(CORE_PATH, "data_connector_live_smoke_missing_creds_core")

    state = core.build_data_connector_live_endpoint_smoke(
        catalog,
        source_path=tmp_path / "catalog.toml",
        execute=True,
        allowed_connector_ids=["ops_opensearch"],
    )

    rows = {row["connector_id"]: row for row in state["endpoint_smokes"]}
    assert rows["ops_opensearch"]["status"] == "skipped"
    assert rows["ops_opensearch"]["execution_status"] == "skipped_missing_credentials"
    assert rows["ops_opensearch"]["credential_env_name"] == "OPENSEARCH_TOKEN"
