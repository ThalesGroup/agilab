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
    assert report["summary"]["connector_count"] == 5
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


def test_data_connector_facility_accepts_aws_azure_and_gcp_object_storage(tmp_path: Path) -> None:
    core_module = _load_module(CORE_PATH, "data_connector_facility_cloud_test_module")
    base_catalog = {
        "connectors": [
            {
                "id": "warehouse_sql",
                "kind": "sql",
                "label": "Warehouse SQL",
                "uri": "postgresql://warehouse.example.invalid/agilab",
                "driver": "postgresql",
                "query_mode": "read_only",
            },
            {
                "id": "ops_opensearch",
                "kind": "opensearch",
                "label": "Operations OpenSearch",
                "url": "https://opensearch.example.invalid",
                "index": "agilab-runs-*",
                "auth_ref": "env:OPENSEARCH_TOKEN",
            },
            {
                "id": "aws_artifact_store",
                "kind": "object_storage",
                "label": "AWS Artifact Store",
                "provider": "aws_s3",
                "bucket": "agilab-artifacts",
                "prefix": "experiments/",
                "region": "eu-west-3",
                "auth_ref": "env:AWS_PROFILE",
            },
            {
                "id": "azure_artifact_store",
                "kind": "object_storage",
                "label": "Azure Artifact Store",
                "provider": "azure_blob",
                "account": "agilabstorage",
                "bucket": "agilab-artifacts",
                "prefix": "experiments/",
                "auth_ref": "env:AZURE_STORAGE_CONNECTION_STRING",
            },
            {
                "id": "gcp_artifact_store",
                "kind": "object_storage",
                "label": "GCP Artifact Store",
                "provider": "gcs",
                "bucket": "agilab-artifacts",
                "prefix": "experiments/",
                "auth_ref": "env:GOOGLE_APPLICATION_CREDENTIALS",
            },
        ]
    }

    state = core_module.build_data_connector_facility(
        base_catalog,
        source_path=tmp_path / "connectors.toml",
    )

    assert state["run_status"] == "validated"
    object_rows = [
        connector for connector in state["connectors"]
        if connector["kind"] == "object_storage"
    ]
    assert {connector["provider"] for connector in object_rows} == {
        "aws_s3",
        "azure_blob",
        "gcs",
    }
    assert any(connector.get("region") == "eu-west-3" for connector in object_rows)
    assert any(connector.get("account") == "agilabstorage" for connector in object_rows)


def test_data_connector_facility_accepts_secret_uri_auth_refs(tmp_path: Path) -> None:
    core_module = _load_module(CORE_PATH, "data_connector_facility_secret_uri_test_module")
    catalog = {
        "connectors": [
            {
                "id": "warehouse_sql",
                "kind": "sql",
                "label": "Warehouse SQL",
                "uri": "postgresql://warehouse.example.invalid/agilab",
                "driver": "postgresql",
                "query_mode": "read_only",
            },
            {
                "id": "ops_opensearch",
                "kind": "opensearch",
                "label": "Operations OpenSearch",
                "url": "https://opensearch.example.invalid",
                "index": "agilab-runs-*",
                "auth_ref": "env://OPENSEARCH_TOKEN",
            },
            {
                "id": "artifact_object_store",
                "kind": "object_storage",
                "label": "Artifact Object Store",
                "provider": "s3",
                "bucket": "agilab-artifacts",
                "prefix": "experiments/",
                "auth_ref": "secret://agilab/aws_profile",
            },
        ]
    }

    state = core_module.build_data_connector_facility(
        catalog,
        source_path=tmp_path / "connectors.toml",
    )

    assert state["run_status"] == "validated"
    assert state["summary"]["raw_secret_count"] == 0


def test_data_connector_facility_accepts_elk_and_hawk_search(tmp_path: Path) -> None:
    core_module = _load_module(CORE_PATH, "data_connector_facility_search_test_module")
    catalog = {
        "connectors": [
            {
                "id": "warehouse_sql",
                "kind": "sql",
                "label": "Warehouse SQL",
                "uri": "postgresql://warehouse.example.invalid/agilab",
                "driver": "postgresql",
                "query_mode": "read_only",
            },
            {
                "id": "ops_elk",
                "kind": "opensearch",
                "label": "Operations ELK",
                "provider": "elk",
                "url": "https://elk.example.invalid",
                "index": "agilab-runs-*",
                "auth_ref": "env:ELK_TOKEN",
            },
            {
                "id": "flight_hawk",
                "kind": "opensearch",
                "label": "Flight Hawk",
                "provider": "hawk",
                "cluster_uri": "hawk.cluster.local:9200",
                "index": "hawk.user-admin.1",
                "auth_ref": "env:HAWK_TOKEN",
            },
            {
                "id": "artifact_object_store",
                "kind": "object_storage",
                "label": "Artifact Object Store",
                "provider": "s3",
                "bucket": "agilab-artifacts",
                "prefix": "experiments/",
                "auth_ref": "env:AWS_PROFILE",
            },
        ]
    }

    state = core_module.build_data_connector_facility(
        catalog,
        source_path=tmp_path / "connectors.toml",
    )

    assert state["run_status"] == "validated"
    search_rows = [
        connector for connector in state["connectors"]
        if connector["kind"] == "opensearch"
    ]
    assert {connector["provider"] for connector in search_rows} == {"elk", "hawk"}
    assert any(
        connector.get("cluster_uri") == "hawk.cluster.local:9200"
        for connector in search_rows
    )


def test_data_connector_facility_rejects_unknown_object_storage_provider(tmp_path: Path) -> None:
    core_module = _load_module(CORE_PATH, "data_connector_facility_unknown_cloud_test_module")
    catalog = {
        "connectors": [
            {
                "id": "unknown_object_store",
                "kind": "object_storage",
                "label": "Unknown Object Store",
                "provider": "ftp",
                "bucket": "agilab-artifacts",
                "prefix": "experiments/",
                "auth_ref": "env:FTP_TOKEN",
            }
        ]
    }

    state = core_module.build_data_connector_facility(
        catalog,
        source_path=tmp_path / "connectors.toml",
    )

    assert state["run_status"] == "invalid"
    assert any(
        issue["location"] == "unknown_object_store"
        and "unsupported object_storage provider" in issue["message"]
        for issue in state["issues"]
    )


def test_data_connector_facility_rejects_unknown_search_provider(tmp_path: Path) -> None:
    core_module = _load_module(
        CORE_PATH,
        "data_connector_facility_unknown_search_test_module",
    )
    catalog = {
        "connectors": [
            {
                "id": "unknown_search",
                "kind": "opensearch",
                "label": "Unknown Search",
                "provider": "solr",
                "url": "https://search.example.invalid",
                "index": "agilab-runs-*",
                "auth_ref": "env:SEARCH_TOKEN",
            }
        ]
    }

    state = core_module.build_data_connector_facility(
        catalog,
        source_path=tmp_path / "connectors.toml",
    )

    assert state["run_status"] == "invalid"
    assert any(
        issue["location"] == "unknown_search"
        and "unsupported opensearch provider" in issue["message"]
        for issue in state["issues"]
    )
