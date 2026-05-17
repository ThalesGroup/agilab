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
    assert report["summary"]["connector_count"] == 5
    assert report["summary"]["planned_endpoint_count"] == 5
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


def test_live_endpoint_smoke_defers_secret_uri_resolution_to_operator_runtime(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "data_connector_live_smoke_secret_uri_test")
    catalog = module._sqlite_smoke_catalog(tmp_path / "smoke.sqlite")
    for connector in catalog["connectors"]:
        if connector.get("id") == "ops_opensearch":
            connector["auth_ref"] = "secret://agilab/opensearch_token"
    core = _load_module(CORE_PATH, "data_connector_live_smoke_secret_uri_core")

    state = core.build_data_connector_live_endpoint_smoke(
        catalog,
        source_path=tmp_path / "catalog.toml",
        execute=True,
        allowed_connector_ids=["ops_opensearch"],
    )

    rows = {row["connector_id"]: row for row in state["endpoint_smokes"]}
    assert rows["ops_opensearch"]["status"] == "skipped"
    assert rows["ops_opensearch"]["execution_status"] == "skipped_operator_runtime_secret"
    assert rows["ops_opensearch"]["credential_env_name"] == ""


def test_live_endpoint_smoke_covers_target_and_credential_edge_cases(tmp_path: Path) -> None:
    core = _load_module(CORE_PATH, "data_connector_live_smoke_edge_core")

    assert core._connector_target({"kind": "unknown"}) == ""
    assert core._sqlite_target("sqlite:///:memory:") == ":memory:"
    assert core._sqlite_target("postgresql://db") == ""
    assert core._probe_sqlite("postgresql://db") == (
        "skipped_unsupported_driver",
        "only sqlite:/// targets execute in public smoke",
    )

    row = core._smoke_row(
        {
            "id": "bad-auth",
            "kind": "opensearch",
            "label": "Bad auth",
            "url": "https://search.example.invalid",
            "index": "runs",
            "auth_ref": "plain-token-reference",
        },
        execute=True,
        allowed_connector_ids={"bad-auth"},
    )

    assert row["credential_status"] == "invalid"
    assert row["execution_status"] == "skipped_invalid_credentials"


def test_live_endpoint_smoke_opensearch_success_and_failure_paths(monkeypatch, tmp_path: Path) -> None:
    core = _load_module(CORE_PATH, "data_connector_live_smoke_opensearch_core")
    connector = {
        "id": "ops",
        "kind": "opensearch",
        "label": "Operations Search",
        "provider": "opensearch",
        "url": "https://opensearch.example.invalid",
        "index": "runs-*",
        "auth_ref": "env:OPENSEARCH_TOKEN",
    }
    monkeypatch.setenv("OPENSEARCH_TOKEN", "token-value")

    class Response:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(core.request, "urlopen", lambda *_args, **_kwargs: Response())

    healthy = core._smoke_row(
        connector,
        execute=True,
        allowed_connector_ids={"ops"},
    )

    assert healthy["status"] == "healthy"
    assert healthy["execution_status"] == "executed"
    assert healthy["network_probe_executed"] is True
    assert "HEAD returned 204" in healthy["message"]

    def fail_urlopen(*_args, **_kwargs):
        raise OSError("network down")

    monkeypatch.setattr(core.request, "urlopen", fail_urlopen)
    unhealthy = core._smoke_row(
        connector,
        execute=True,
        allowed_connector_ids={"ops"},
    )

    assert unhealthy["status"] == "unhealthy"
    assert unhealthy["execution_status"] == "executed"
    assert unhealthy["network_probe_executed"] is True
    assert unhealthy["message"] == "network down"


def test_live_endpoint_smoke_invalid_catalog_and_relative_persist_path(tmp_path: Path) -> None:
    core = _load_module(CORE_PATH, "data_connector_live_smoke_invalid_catalog_core")

    invalid_state = core.build_data_connector_live_endpoint_smoke(
        {"connectors": [{"id": "only-sql", "kind": "sql", "label": "Only SQL"}]},
        source_path=tmp_path / "bad-catalog.toml",
        execute=True,
        allowed_connector_ids=["only-sql"],
    )

    assert invalid_state["run_status"] == "planned"
    assert invalid_state["issues"] == [
        {
            "level": "error",
            "location": "connector_catalog",
            "message": "connector catalog must validate before live endpoint smoke",
        }
    ]

    catalog_path = tmp_path / "catalogs" / "connectors.toml"
    catalog_path.parent.mkdir(parents=True)
    sqlite_path = tmp_path / "smoke.sqlite"
    catalog_path.write_text(
        f"""
[[connectors]]
id = "local_sqlite"
kind = "sql"
label = "Local SQLite"
uri = "sqlite:///{sqlite_path}"
driver = "sqlite"
query_mode = "read_only"

[[connectors]]
id = "ops"
kind = "opensearch"
label = "Operations Search"
url = "https://opensearch.example.invalid"
index = "runs-*"
auth_ref = "env:OPENSEARCH_TOKEN"

[[connectors]]
id = "artifacts"
kind = "object_storage"
label = "Artifacts"
provider = "s3"
bucket = "agilab"
prefix = "runs/"
auth_ref = "env:AWS_PROFILE"
""",
        encoding="utf-8",
    )

    proof = core.persist_data_connector_live_endpoint_smoke(
        repo_root=tmp_path,
        output_path=tmp_path / "out" / "smoke.json",
        catalog_path=Path("catalogs/connectors.toml"),
    )

    assert proof["ok"] is True
    assert proof["catalog_path"] == str(catalog_path)
    assert proof["state"]["summary"]["connector_ids"] == ["artifacts", "local_sqlite", "ops"]
