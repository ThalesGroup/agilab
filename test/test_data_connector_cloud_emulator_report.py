from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPORT_PATH = Path("tools/data_connector_cloud_emulator_report.py").resolve()
CATALOG_PATH = Path("docs/source/data/cloud_emulator_connectors_sample.toml")


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "data_connector_cloud_emulator_report_test_module",
        REPORT_PATH,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_data_connector_cloud_emulator_report_passes(tmp_path: Path) -> None:
    module = _load_module()

    report = module.build_report(
        repo_root=Path.cwd(),
        output_path=tmp_path / "data_connector_cloud_emulator.json",
    )

    assert report["report"] == "Data connector cloud emulator report"
    assert report["status"] == "pass"
    assert report["summary"]["execution_mode"] == "cloud_emulator_contract_only"
    assert report["summary"]["real_cloud_account_required"] is False
    assert report["summary"]["connector_count"] == 5
    assert report["summary"]["object_storage_emulator_count"] == 3
    assert report["summary"]["search_emulator_count"] == 1
    assert report["summary"]["object_storage_providers"] == [
        "azure_blob",
        "gcs",
        "s3",
    ]
    assert report["summary"]["endpoint_issue_count"] == 0
    assert report["summary"]["network_probe_count"] == 0
    assert report["summary"]["credential_value_materialized_count"] == 0
    assert {check["id"] for check in report["checks"]} == {
        "data_connector_cloud_emulator_schema",
        "data_connector_cloud_emulator_providers",
        "data_connector_cloud_emulator_endpoint_boundary",
        "data_connector_cloud_emulator_runtime_mapping",
        "data_connector_cloud_emulator_persistence",
        "data_connector_cloud_emulator_docs_reference",
    }


def test_data_connector_cloud_emulator_report_rejects_real_cloud_endpoint(
    tmp_path: Path,
) -> None:
    module = _load_module()
    text = CATALOG_PATH.read_text(encoding="utf-8").replace(
        "http://127.0.0.1:9000",
        "https://s3.amazonaws.com",
        1,
    )
    catalog = tmp_path / "real_cloud_endpoint.toml"
    catalog.write_text(text, encoding="utf-8")

    report = module.build_report(
        repo_root=Path.cwd(),
        catalog_path=catalog,
        output_path=tmp_path / "data_connector_cloud_emulator.json",
    )

    assert report["status"] == "fail"
    endpoint_check = next(
        check for check in report["checks"]
        if check["id"] == "data_connector_cloud_emulator_endpoint_boundary"
    )
    assert endpoint_check["status"] == "fail"
    assert endpoint_check["details"]["endpoint_issues"] == [
        {
            "connector_id": "minio_s3_emulator",
            "message": "endpoint is not local/emulated: https://s3.amazonaws.com",
        }
    ]
