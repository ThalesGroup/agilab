from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPORT_PATH = Path("tools/data_connector_runtime_adapters_report.py").resolve()
CORE_PATH = Path("src/agilab/data_connector_runtime_adapters.py").resolve()


def _load_module(path: Path, name: str):
    src_root = Path.cwd() / "src"
    src_root_text = str(src_root)
    if src_root_text not in sys.path:
        sys.path.insert(0, src_root_text)
    package = sys.modules.get("agilab")
    package_paths = getattr(package, "__path__", None)
    package_path = str(src_root / "agilab")
    if package_paths is not None and package_path not in list(package_paths):
        package_paths.append(package_path)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_data_connector_runtime_adapters_report_passes(tmp_path: Path) -> None:
    module = _load_module(
        REPORT_PATH,
        "data_connector_runtime_adapters_report_test_module",
    )

    report = module.build_report(
        repo_root=Path.cwd(),
        output_path=tmp_path / "data_connector_runtime_adapters.json",
    )

    assert report["report"] == "Data connector runtime adapters report"
    assert report["status"] == "pass"
    assert report["summary"]["schema"] == "agilab.data_connector_runtime_adapters.v1"
    assert report["summary"]["run_status"] == "ready_for_runtime_binding"
    assert report["summary"]["execution_mode"] == "runtime_adapter_contract_only"
    assert report["summary"]["connector_count"] == 5
    assert report["summary"]["adapter_count"] == 5
    assert report["summary"]["runtime_ready_count"] == 5
    assert report["summary"]["credential_deferred_count"] == 4
    assert report["summary"]["no_credential_required_count"] == 1
    assert report["summary"]["operator_opt_in_required_count"] == 5
    assert report["summary"]["health_action_binding_count"] == 5
    assert report["summary"]["executed_adapter_count"] == 0
    assert report["summary"]["network_probe_count"] == 0
    assert report["summary"]["credential_value_materialized_count"] == 0
    assert report["summary"]["adapter_kinds"] == [
        "object_storage",
        "opensearch",
        "sql",
    ]
    assert report["summary"]["operations"] == [
        "object_storage_prefix_list",
        "opensearch_index_head",
        "read_only_connectivity_check",
    ]
    assert report["summary"]["runtime_dependencies"] == [
        "package:azure-storage-blob",
        "package:boto3",
        "package:google-cloud-storage",
        "package:psycopg",
        "python:urllib.request",
    ]
    assert report["summary"]["round_trip_ok"] is True
    assert {check["id"] for check in report["checks"]} == {
        "data_connector_runtime_adapters_schema",
        "data_connector_runtime_adapters_rows",
        "data_connector_runtime_adapters_credential_boundary",
        "data_connector_runtime_adapters_health_actions",
        "data_connector_runtime_adapters_no_network",
        "data_connector_runtime_adapters_persistence",
        "data_connector_runtime_adapters_docs_reference",
    }


def test_data_connector_runtime_adapters_persist_runtime_rows(tmp_path: Path) -> None:
    module = _load_module(
        REPORT_PATH,
        "data_connector_runtime_adapters_json_test_module",
    )
    output_path = tmp_path / "data_connector_runtime_adapters.json"

    report = module.build_report(repo_root=Path.cwd(), output_path=output_path)

    assert report["status"] == "pass"
    payload = module.json.loads(output_path.read_text(encoding="utf-8"))
    adapters = payload["adapters"]
    assert {adapter["runtime_binding_status"] for adapter in adapters} == {
        "ready_for_operator_runtime"
    }
    assert {adapter["execution_status"] for adapter in adapters} == {
        "not_executed_operator_runtime_required"
    }
    assert {adapter["credential_resolution"] for adapter in adapters} == {
        "deferred_to_operator_runtime",
        "none_required",
    }
    assert sum(1 for adapter in adapters if adapter["requires_credentials"]) == 4
    assert sum(1 for adapter in adapters if not adapter["requires_credentials"]) == 1
    targets = {adapter["connector_id"]: adapter["target"] for adapter in adapters}
    assert targets["artifact_object_store"] == "s3://agilab-artifacts/experiments/"
    assert targets["azure_artifact_store"] == "azure_blob://agilabstorage/agilab-artifacts/experiments/"
    assert targets["gcp_artifact_store"] == "gs://agilab-artifacts/experiments/"
    assert all(adapter["network_probe_executed"] is False for adapter in adapters)
    assert all(adapter["credential_value_materialized"] is False for adapter in adapters)
    assert all(adapter["safe_for_public_evidence"] is True for adapter in adapters)


def test_data_connector_runtime_adapters_accepts_aws_s3_alias(tmp_path: Path) -> None:
    core_module = _load_module(
        CORE_PATH,
        "data_connector_runtime_adapters_core_aws_alias_test_module",
    )
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
                "auth_ref": "env:OPENSEARCH_TOKEN",
            },
            {
                "id": "aws_artifact_store",
                "kind": "object_storage",
                "label": "AWS Artifact Store",
                "provider": "AWS_S3",
                "bucket": "agilab-artifacts",
                "prefix": "experiments/",
                "auth_ref": "env:AWS_PROFILE",
            }
        ]
    }

    state = core_module.build_data_connector_runtime_adapters(
        catalog,
        source_path=tmp_path / "connectors.toml",
    )

    assert state["run_status"] == "ready_for_runtime_binding"
    adapter = next(
        row for row in state["adapters"]
        if row["connector_id"] == "aws_artifact_store"
    )
    assert adapter["target"] == "s3://agilab-artifacts/experiments/"
    assert adapter["runtime_dependency"] == "package:boto3"
    assert adapter["credential_env_name"] == "AWS_PROFILE"
