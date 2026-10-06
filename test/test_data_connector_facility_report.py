from __future__ import annotations

import importlib.util
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest


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


def test_data_connector_facility_rejects_non_list_connector_rows(tmp_path: Path) -> None:
    core_module = _load_module(CORE_PATH, "data_connector_facility_rows_test_module")

    with pytest.raises(ValueError, match=r"\[\[connectors\]\]"):
        core_module.build_data_connector_facility(
            {"connectors": "not-a-list"},
            source_path=tmp_path / "connectors.toml",
        )


def test_data_connector_facility_defensive_catalog_and_secret_helpers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    core_module = _load_module(CORE_PATH, "data_connector_facility_helpers_test_module")
    catalog_path = tmp_path / "connectors.toml"
    catalog_path.write_text("connectors = []\n", encoding="utf-8")
    monkeypatch.setattr(core_module.tomllib, "loads", lambda _text: ["not", "a", "table"])

    with pytest.raises(ValueError, match="TOML table"):
        core_module.load_connector_catalog(catalog_path)

    assert core_module._has_raw_secret(None) is False
    assert core_module._has_raw_secret("env:RAW_SECRET") is False
    assert core_module._has_raw_secret("token=plaintext") is True


def test_data_connector_facility_reports_required_field_auth_and_duplicate_errors(
    tmp_path: Path,
) -> None:
    core_module = _load_module(CORE_PATH, "data_connector_facility_edge_test_module")
    catalog = {
        "connectors": [
            {"kind": "unknown"},
            {
                "id": "remote",
                "kind": "opensearch",
                "index": "logs-*",
                "auth_ref": "plain-token",
            },
            {
                "id": "remote",
                "kind": "object_storage",
                "label": "Remote duplicate",
                "provider": "s3",
                "bucket": "bucket",
                "prefix": "runs/",
                "auth_ref": "env:AWS_PROFILE",
            },
        ]
    }

    state = core_module.build_data_connector_facility(
        catalog,
        source_path=tmp_path / "connectors.toml",
    )

    assert state["run_status"] == "invalid"
    messages = {(issue["location"], issue["message"]) for issue in state["issues"]}
    assert ("connector[0]", "unsupported connector kind: unknown") in messages
    assert ("remote", "missing required field: label") in messages
    assert ("remote", "missing required field: url or cluster_uri") in messages
    assert (
        "remote",
        "remote connector auth_ref must use env:, env://, secret://, or vault://",
    ) in messages
    assert ("remote", "duplicate connector id") in messages


def test_data_connector_facility_persist_accepts_relative_catalog_path(tmp_path: Path) -> None:
    core_module = _load_module(CORE_PATH, "data_connector_facility_persist_test_module")
    repo_root = tmp_path / "repo"
    catalog_path = repo_root / "config" / "connectors.toml"
    catalog_path.parent.mkdir(parents=True)
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

    proof = core_module.persist_data_connector_facility(
        repo_root=repo_root,
        output_path=tmp_path / "facility.json",
        catalog_path=Path("config/connectors.toml"),
    )

    assert proof["ok"] is True
    assert proof["catalog_path"] == str(catalog_path)


_CREDENTIAL_SENTINEL = "synthetic-catalog-credential-20261006"


def _credential_test_catalog(core_module):
    return core_module.load_connector_catalog(
        Path.cwd() / core_module.DEFAULT_CONNECTORS_RELATIVE_PATH
    )


def _write_credential_catalog_fixture(path, catalog):
    def value(item):
        if isinstance(item, dict):
            return "{" + ", ".join(f"{json.dumps(key)} = {value(child)}" for key, child in item.items()) + "}"
        return json.dumps(item)

    path.write_text(
        "\n".join(
            "[[connectors]]\n" + "\n".join(f"{key} = {value(item)}" for key, item in row.items())
            for row in catalog["connectors"]
        ) + "\n",
        encoding="utf-8",
    )


def _forbid_credential_resolution_and_network(monkeypatch):
    from agilab.security import secret_uri

    def forbidden(*_args, **_kwargs):
        raise AssertionError("evidence collection must not resolve credentials or connect")

    monkeypatch.setattr(secret_uri, "resolve_secret_uri", forbidden)
    monkeypatch.setattr(secret_uri, "_default_keyring_getter", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setenv("OPENSEARCH_TOKEN", _CREDENTIAL_SENTINEL)


@pytest.mark.parametrize("compact", [False, True], ids=["pretty", "compact"])
@pytest.mark.parametrize(
    ("kind", "field", "value"),
    [
        ("sql", "uri", f"postgresql://fixture:{_CREDENTIAL_SENTINEL}@db.invalid/data"),
        ("sql", "uri", f"postgresql://db.invalid/data?password={_CREDENTIAL_SENTINEL}"),
        ("sql", "uri", f"postgresql://db.invalid/data?%70ass%77ord={_CREDENTIAL_SENTINEL}"),
        ("opensearch", "auth_ref", _CREDENTIAL_SENTINEL),
        ("opensearch", "auth_ref", f"secret://fixture:{_CREDENTIAL_SENTINEL}@store/token"),
        ("opensearch", "auth_ref", f"vault://fixture/token?password={_CREDENTIAL_SENTINEL}"),
        ("object_storage", "endpoint_url", f"https://fixture:{_CREDENTIAL_SENTINEL}@store.invalid"),
        ("object_storage", "provider", f"token={_CREDENTIAL_SENTINEL}"),
        ("sql", "description", f"connection token={_CREDENTIAL_SENTINEL}"),
        ("sql", "description", f"Bearer {_CREDENTIAL_SENTINEL}"),
        ("sql", "id", f"password={_CREDENTIAL_SENTINEL}"),
    ],
    ids=["uri-userinfo", "uri-query", "uri-encoded-query", "raw-auth-ref", "reference_userinfo", "reference_query", "optional-endpoint", "invalid-provider", "description", "bearer-description", "issue-location"],
)
def test_connector_cli_rejects_inline_credentials_without_output_leaks(
    kind, field, value, compact, tmp_path, monkeypatch, capsys
):
    core = _load_module(CORE_PATH, "data_connector_credential_cli_core_test_module")
    report_module = _load_module(REPORT_PATH, "data_connector_credential_cli_report_test_module")
    _forbid_credential_resolution_and_network(monkeypatch)
    catalog = _credential_test_catalog(core)
    next(row for row in catalog["connectors"] if row["kind"] == kind)[field] = value
    catalog_path = tmp_path / "inline-credential-catalog.toml"
    _write_credential_catalog_fixture(catalog_path, catalog)
    output_path = tmp_path / "credential-safe-connector-state.json"
    argv = ["--catalog", str(catalog_path), "--output", str(output_path)]
    if compact:
        argv.append("--compact")

    exit_code = report_module.main(argv)
    captured = capsys.readouterr()
    state = json.loads(output_path.read_text(encoding="utf-8"))
    report = json.loads(captured.out)

    assert exit_code == 1
    assert report["status"] == "fail"
    assert state["run_status"] == "invalid"
    assert state["summary"]["raw_secret_count"] >= 1
    assert report["summary"]["raw_secret_count"] >= 1
    assert state["summary"]["network_probe_count"] == 0
    assert state["provenance"]["executes_network_probe"] is False
    assert _CREDENTIAL_SENTINEL not in json.dumps(state)
    assert _CREDENTIAL_SENTINEL not in json.dumps(report)
    assert _CREDENTIAL_SENTINEL not in captured.out + captured.err
    assert ("\n" not in captured.out.strip()) is compact


@pytest.mark.parametrize("compact", [False, True], ids=["pretty", "compact"])
@pytest.mark.parametrize("context", ["assignment", "reference-and-assignment"])
@pytest.mark.parametrize("field", ["label", "description"])
@pytest.mark.parametrize("key", ["MY_SECRET_KEY", "MY_PASSWORD", "API_TOKEN"])
def test_connector_canonical_assignments_never_reach_public_evidence(
    key, field, context, compact, tmp_path, monkeypatch, capsys
):
    from agilab.security.secret_uri import redact_text

    sentinel = "SYNTHETIC_KEY_CANARY_SHORT"
    assignment = f"{key}={sentinel}"
    assert redact_text(assignment) != assignment
    value = assignment
    if context == "reference-and-assignment":
        value = f"secret://fixture/token?authorization_scope=read {assignment}"
    core = _load_module(CORE_PATH, "data_connector_assignment_core_test_module")
    report_module = _load_module(REPORT_PATH, "data_connector_assignment_report_test_module")
    _forbid_credential_resolution_and_network(monkeypatch)
    catalog = _credential_test_catalog(core)
    next(row for row in catalog["connectors"] if row["kind"] == "sql")[field] = value
    catalog_path = tmp_path / "synthetic-assignment-connector-catalog.toml"
    _write_credential_catalog_fixture(catalog_path, catalog)
    output_path = tmp_path / "credential-safe-assignment-connector-state.json"
    argv = ["--catalog", str(catalog_path), "--output", str(output_path)]
    if compact:
        argv.append("--compact")

    exit_code = report_module.main(argv)
    captured = capsys.readouterr()
    saved_bytes = output_path.read_bytes()
    state = json.loads(saved_bytes)
    report = json.loads(captured.out)

    assert exit_code == 1
    assert report["status"] == "fail"
    assert state["run_status"] == "invalid"
    assert state["summary"]["raw_secret_count"] >= 1
    assert report["summary"]["raw_secret_count"] >= 1
    assert state["summary"]["network_probe_count"] == 0
    assert state["provenance"]["executes_network_probe"] is False
    assert sentinel.encode() not in saved_bytes
    assert sentinel not in json.dumps(state) + json.dumps(report)
    assert sentinel not in captured.out + captured.err
    assert ("\n" not in captured.out.strip()) is compact
    assert all(
        row["auth_ref"] == original["auth_ref"]
        for row, original in zip(state["connectors"], catalog["connectors"])
        if original.get("auth_ref")
    )


@pytest.mark.parametrize("compact", [False, True], ids=["pretty", "compact"])
def test_connector_inline_credential_reference_prose_keeps_historical_contract(
    compact, tmp_path, monkeypatch, capsys
):
    core = _load_module(CORE_PATH, "data_connector_inline_reference_core_test_module")
    canonical_path = Path("src/agilab/data_connectors/data_connector_facility.py").resolve()
    assert Path(core.build_data_connector_facility.__code__.co_filename).resolve() == canonical_path
    report_module = _load_module(REPORT_PATH, "data_connector_inline_reference_report_test_module")
    _forbid_credential_resolution_and_network(monkeypatch)
    catalog = _credential_test_catalog(core)
    description = "Reference only: secret://fixture/token"
    catalog["connectors"][0]["description"] = description
    catalog_path = tmp_path / "inline-credential-reference-description-catalog.toml"
    _write_credential_catalog_fixture(catalog_path, catalog)
    output_path = tmp_path / "preserved-inline-credential-reference-state.json"
    argv = ["--catalog", str(catalog_path), "--output", str(output_path)]
    if compact:
        argv.append("--compact")

    exit_code = report_module.main(argv)
    captured = capsys.readouterr()
    state = json.loads(output_path.read_bytes())
    report = json.loads(captured.out)

    assert exit_code == 0
    assert report["status"] == "pass"
    assert state["run_status"] == "validated"
    assert state["summary"]["raw_secret_count"] == 0
    assert report["summary"]["raw_secret_count"] == 0
    assert state["connectors"][0]["description"] == description
    assert state["summary"]["network_probe_count"] == 0
    assert state["provenance"]["executes_network_probe"] is False
    assert ("\n" not in captured.out.strip()) is compact


@pytest.mark.parametrize("reference", ["env:OPENSEARCH_TOKEN", "env://OPENSEARCH_TOKEN", "secret://fixture/token", "vault://fixture/token"])
def test_connector_evidence_keeps_credential_references_without_resolution(
    reference, tmp_path, monkeypatch
):
    core = _load_module(CORE_PATH, "data_connector_safe_reference_core_test_module")
    _forbid_credential_resolution_and_network(monkeypatch)
    catalog = _credential_test_catalog(core)
    for row in catalog["connectors"]:
        if row.get("auth_ref"):
            row["auth_ref"] = reference

    state = core.build_data_connector_facility(catalog, source_path="synthetic-reference-catalog.toml")
    path = core.write_data_connector_facility(tmp_path / "safe-reference-state.json", state)

    assert state["run_status"] == "validated"
    assert state["summary"]["raw_secret_count"] == 0
    assert all(row["auth_ref"] == reference for row in state["connectors"] if row["auth_ref"])
    assert core.load_data_connector_facility(path) == state
    assert _CREDENTIAL_SENTINEL not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("compact", [False, True], ids=["pretty", "compact"])
@pytest.mark.parametrize(
    ("kind", "field", "duplicate"),
    [("sql", "id", False), ("sql", "kind", False), ("object_storage", "provider", False),
     ("opensearch", "provider", False), ("sql", "id", True)],
    ids=["malformed-id", "malformed-kind", "malformed-storage-provider", "malformed-search-provider", "duplicate-malformed-id"],
)
def test_connector_malformed_diagnostic_fields_never_expose_credentials(
    kind, field, duplicate, compact, tmp_path, monkeypatch, capsys
):
    core = _load_module(CORE_PATH, "data_connector_malformed_diagnostics_core_test_module")
    report_module = _load_module(REPORT_PATH, "data_connector_malformed_diagnostics_report_test_module")
    _forbid_credential_resolution_and_network(monkeypatch)
    catalog = _credential_test_catalog(core)
    row = next(row for row in catalog["connectors"] if row["kind"] == kind)
    row[field] = {"password": _CREDENTIAL_SENTINEL}
    if duplicate:
        catalog["connectors"].append(dict(row))
    catalog_path = tmp_path / "malformed-diagnostic-catalog.toml"
    _write_credential_catalog_fixture(catalog_path, catalog)
    state = core.build_data_connector_facility(catalog, source_path="malformed-diagnostic-catalog.toml")
    state_path = core.write_data_connector_facility(tmp_path / "safe-diagnostic-state.json", state)
    output_path = tmp_path / "safe-diagnostic-cli-state.json"
    argv = ["--catalog", str(catalog_path), "--output", str(output_path)]
    if compact:
        argv.append("--compact")

    exit_code = report_module.main(argv)
    captured = capsys.readouterr()
    report = json.loads(captured.out)

    assert exit_code == 1
    assert state["run_status"] == "invalid"
    assert state["summary"]["raw_secret_count"] >= 1
    assert report["status"] == "fail"
    assert _CREDENTIAL_SENTINEL not in json.dumps(state)
    assert _CREDENTIAL_SENTINEL not in state_path.read_text(encoding="utf-8")
    assert _CREDENTIAL_SENTINEL not in output_path.read_text(encoding="utf-8")
    assert _CREDENTIAL_SENTINEL not in captured.out + captured.err


@pytest.mark.parametrize("compact", [False, True], ids=["pretty", "compact"])
@pytest.mark.parametrize(
    ("provider", "query"),
    [("azure_blob", f"sv=2026-10-06&sig={_CREDENTIAL_SENTINEL}"),
     ("s3", f"X-Amz-Signature={_CREDENTIAL_SENTINEL}"),
     ("gcs", f"X-Goog-Signature={_CREDENTIAL_SENTINEL}")],
    ids=["azure-sas", "aws-signed-url", "gcs-signed-url"],
)
def test_connector_signed_storage_query_is_not_persisted_or_printed(
    provider, query, compact, tmp_path, monkeypatch, capsys
):
    core = _load_module(CORE_PATH, "data_connector_signed_storage_core_test_module")
    report_module = _load_module(REPORT_PATH, "data_connector_signed_storage_report_test_module")
    _forbid_credential_resolution_and_network(monkeypatch)
    catalog = _credential_test_catalog(core)
    row = next(row for row in catalog["connectors"] if row.get("provider") == provider)
    row["endpoint_url"] = f"https://storage.invalid/objects?{query}"
    catalog_path = tmp_path / "signed-storage-catalog.toml"
    _write_credential_catalog_fixture(catalog_path, catalog)
    output_path = tmp_path / "credential-safe-storage-state.json"
    argv = ["--catalog", str(catalog_path), "--output", str(output_path)]
    if compact:
        argv.append("--compact")

    exit_code = report_module.main(argv)
    captured = capsys.readouterr()
    state = json.loads(output_path.read_text(encoding="utf-8"))
    report = json.loads(captured.out)

    assert exit_code == 1
    assert state["run_status"] == "invalid"
    assert state["summary"]["raw_secret_count"] >= 1
    assert report["status"] == "fail"
    assert row["auth_ref"].startswith("env:")
    assert _CREDENTIAL_SENTINEL not in json.dumps(state)
    assert _CREDENTIAL_SENTINEL not in json.dumps(report)
    assert _CREDENTIAL_SENTINEL not in captured.out + captured.err


def test_connector_benign_query_names_are_not_credentials():
    core = _load_module(CORE_PATH, "data_connector_benign_query_core_test_module")
    catalog = _credential_test_catalog(core)
    uri = "https://storage.invalid/objects?design=diagram&signal=ready&signature_version=2026&authorization_scope=read"
    row = next(row for row in catalog["connectors"] if row.get("provider") == "azure_blob")
    row["endpoint_url"] = uri

    state = core.build_data_connector_facility(catalog, source_path="benign-query-catalog.toml")

    assert state["run_status"] == "validated"
    assert state["summary"]["raw_secret_count"] == 0
    assert next(row for row in state["connectors"] if row.get("provider") == "azure_blob")["endpoint_url"] == uri


def test_connector_evidence_is_identical_across_python_hash_seeds():
    repo_root = Path.cwd()
    catalog = {"connectors": [{
        "id": 42, "kind": "sql", "label": False, "uri": {"password": _CREDENTIAL_SENTINEL},
        "driver": False, "query_mode": None, "description": [], "auth_ref": [_CREDENTIAL_SENTINEL],
    }]}
    code = (
        "import json\n"
        "from pathlib import Path\n"
        "from agilab.data_connectors import data_connector_facility as core\n"
        f"assert Path(core.__file__).resolve() == Path({str(repo_root / 'src/agilab/data_connectors/data_connector_facility.py')!r}).resolve()\n"
        f"catalog = json.loads({json.dumps(catalog)!r})\n"
        "state = core.build_data_connector_facility(catalog, source_path='synthetic-hash-seed-catalog.toml')\n"
        "assert state['run_status'] == 'invalid'\n"
        "print(json.dumps(state, sort_keys=True, separators=(',', ':')))\n"
    )
    output = []
    for seed in (1, 2, 3, 7, 13, 23, 42, 73):
        environment = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR", "TMP", "TEMP") if key in os.environ}
        environment.update(PYTHONHASHSEED=str(seed), PYTHONPATH=str(repo_root / "src"), PYTHONDONTWRITEBYTECODE="1")
        completed = subprocess.run(
            [sys.executable, "-c", code], cwd=repo_root, env=environment,
            check=True, capture_output=True, text=True, timeout=15,
        )
        assert _CREDENTIAL_SENTINEL not in completed.stdout + completed.stderr
        output.append(completed.stdout)

    assert len(set(output)) == 1, "evidence must not depend on Python's hash seed"


def test_connector_malformed_value_does_not_survive_into_evidence(tmp_path):
    core = _load_module(CORE_PATH, "data_connector_malformed_evidence_core_test_module")
    catalog = _credential_test_catalog(core)
    next(row for row in catalog["connectors"] if row["kind"] == "sql")["uri"] = {
        "password": _CREDENTIAL_SENTINEL,
    }

    state = core.build_data_connector_facility(catalog, source_path="synthetic-malformed-catalog.toml")
    path = core.write_data_connector_facility(tmp_path / "safe-malformed-state.json", state)

    assert state["run_status"] == "invalid"
    assert state["summary"]["raw_secret_count"] >= 1
    assert _CREDENTIAL_SENTINEL not in json.dumps(state)
    assert _CREDENTIAL_SENTINEL not in path.read_text(encoding="utf-8")
