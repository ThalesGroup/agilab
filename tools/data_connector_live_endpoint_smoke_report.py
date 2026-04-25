#!/usr/bin/env python3
"""Emit AGILAB data connector live endpoint smoke evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_RELATIVE_PATH = Path("docs/source/features.rst")


def _ensure_repo_on_path(repo_root: Path) -> None:
    src_root = repo_root / "src"
    for entry in (str(src_root), str(repo_root)):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    package = sys.modules.get("agilab")
    package_path = str(src_root / "agilab")
    package_paths = getattr(package, "__path__", None)
    if package_paths is not None and package_path not in list(package_paths):
        try:
            package_paths.append(package_path)
        except AttributeError:
            package.__path__ = [*package_paths, package_path]


_ensure_repo_on_path(REPO_ROOT)

from agilab.data_connector_live_endpoint_smoke import (  # noqa: E402
    SCHEMA,
    build_data_connector_live_endpoint_smoke,
    persist_data_connector_live_endpoint_smoke,
)


def _check_result(
    check_id: str,
    label: str,
    passed: bool,
    summary: str,
    *,
    evidence: Sequence[str] = (),
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": "pass" if passed else "fail",
        "summary": summary,
        "evidence": list(evidence),
        "details": details or {},
    }


def _sqlite_smoke_catalog(db_path: Path) -> dict[str, Any]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.execute("create table if not exists smoke (id integer primary key)")
    return {
        "connectors": [
            {
                "id": "local_sqlite",
                "kind": "sql",
                "label": "Local SQLite smoke",
                "uri": f"sqlite:///{db_path}",
                "driver": "sqlite",
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


def _docs_check(repo_root: Path) -> dict[str, Any]:
    required = [
        "data connector live endpoint smoke report",
        "tools/data_connector_live_endpoint_smoke_report.py --compact",
        "live_endpoint_smoke_plan_only",
        "live_endpoint_smoke_opt_in",
    ]
    doc_path = repo_root / DOC_RELATIVE_PATH
    try:
        text = doc_path.read_text(encoding="utf-8")
        missing = [needle for needle in required if needle not in text]
        ok = not missing
        details = {"missing": missing}
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "data_connector_live_endpoint_smoke_docs_reference",
        "Data connector live endpoint smoke docs reference",
        ok,
        (
            "features docs expose the live endpoint smoke command"
            if ok
            else "features docs do not expose the live endpoint smoke command"
        ),
        evidence=[str(DOC_RELATIVE_PATH)],
        details=details,
    )


def build_report(
    *,
    repo_root: Path = REPO_ROOT,
    catalog_path: Path | None = None,
    output_path: Path | None = None,
    execute: bool = False,
    allowed_connector_ids: Sequence[str] = (),
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    if output_path is None:
        with tempfile.TemporaryDirectory(prefix="agilab-data-connector-live-smoke-") as tmp_dir:
            return _build_report_with_path(
                repo_root=repo_root,
                catalog_path=catalog_path,
                output_path=Path(tmp_dir) / "data_connector_live_endpoint_smoke.json",
                execute=execute,
                allowed_connector_ids=allowed_connector_ids,
            )
    return _build_report_with_path(
        repo_root=repo_root,
        catalog_path=catalog_path,
        output_path=output_path,
        execute=execute,
        allowed_connector_ids=allowed_connector_ids,
    )


def _build_report_with_path(
    *,
    repo_root: Path,
    catalog_path: Path | None,
    output_path: Path,
    execute: bool,
    allowed_connector_ids: Sequence[str],
) -> dict[str, Any]:
    proof = persist_data_connector_live_endpoint_smoke(
        repo_root=repo_root,
        output_path=output_path,
        catalog_path=catalog_path,
        execute=execute,
        allowed_connector_ids=allowed_connector_ids,
    )
    state = proof["state"]
    summary = state.get("summary", {})
    endpoint_smokes = state.get("endpoint_smokes", [])
    sqlite_state = _sqlite_smoke_state(output_path.parent)
    sqlite_summary = sqlite_state.get("summary", {})
    checks = [
        _check_result(
            "data_connector_live_endpoint_smoke_schema",
            "Data connector live endpoint smoke schema",
            proof["ok"]
            and state.get("schema") == SCHEMA
            and state.get("execution_mode")
            in {"live_endpoint_smoke_plan_only", "live_endpoint_smoke_opt_in"},
            "live endpoint smoke uses the supported schema",
            evidence=["src/agilab/data_connector_live_endpoint_smoke.py"],
            details={
                "schema": state.get("schema"),
                "run_status": state.get("run_status"),
                "execution_mode": state.get("execution_mode"),
                "issues": state.get("issues", []),
            },
        ),
        _check_result(
            "data_connector_live_endpoint_smoke_plan",
            "Data connector live endpoint smoke plan",
            summary.get("connector_count") == 3
            and summary.get("planned_endpoint_count") == 3,
            "live smoke plan covers the three first-class connector kinds",
            evidence=[proof["catalog_path"]],
            details={"summary": summary, "endpoint_smokes": endpoint_smokes},
        ),
        _check_result(
            "data_connector_live_endpoint_smoke_public_boundary",
            "Data connector live endpoint smoke public boundary",
            (execute or summary.get("executed_endpoint_count") == 0)
            and state.get("provenance", {}).get("requires_operator_opt_in") is True
            and state.get("provenance", {}).get("credential_values_logged") is False,
            "public evidence stays operator-gated and never logs credential values",
            evidence=[proof["catalog_path"]],
            details={"summary": summary, "provenance": state.get("provenance", {})},
        ),
        _check_result(
            "data_connector_live_endpoint_smoke_sqlite_execution",
            "Data connector live endpoint smoke SQLite execution",
            sqlite_state.get("run_status") == "smoke_complete"
            and sqlite_summary.get("executed_endpoint_count") == 1
            and sqlite_summary.get("healthy_count") == 1
            and sqlite_summary.get("network_probe_count") == 0,
            "operator opt-in execution path is validated with a local SQLite endpoint",
            evidence=["src/agilab/data_connector_live_endpoint_smoke.py"],
            details={"summary": sqlite_summary, "state": sqlite_state},
        ),
        _check_result(
            "data_connector_live_endpoint_smoke_persistence",
            "Data connector live endpoint smoke persistence",
            proof["round_trip_ok"] and Path(proof["path"]).is_file(),
            "live endpoint smoke state is unchanged after JSON write/read",
            evidence=[proof["path"]],
            details={"path": proof["path"], "round_trip_ok": proof["round_trip_ok"]},
        ),
        _docs_check(repo_root),
    ]
    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "report": "Data connector live endpoint smoke report",
        "status": "pass" if failed == 0 else "fail",
        "scope": (
            "Plans opt-in live endpoint smoke checks and validates the execution "
            "path with local SQLite without opening external networks by default."
        ),
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "schema": state.get("schema"),
            "run_status": state.get("run_status"),
            "execution_mode": state.get("execution_mode"),
            "connector_count": summary.get("connector_count"),
            "planned_endpoint_count": summary.get("planned_endpoint_count"),
            "executed_endpoint_count": summary.get("executed_endpoint_count"),
            "healthy_count": summary.get("healthy_count"),
            "unhealthy_count": summary.get("unhealthy_count"),
            "skipped_count": summary.get("skipped_count"),
            "missing_credential_count": summary.get("missing_credential_count"),
            "network_probe_count": summary.get("network_probe_count"),
            "sqlite_smoke_healthy_count": sqlite_summary.get("healthy_count"),
            "round_trip_ok": proof["round_trip_ok"],
            "catalog_path": proof["catalog_path"],
            "path": proof["path"],
        },
        "checks": checks,
    }


def _sqlite_smoke_state(tmp_dir: Path) -> dict[str, Any]:
    return build_data_connector_live_endpoint_smoke(
        _sqlite_smoke_catalog(tmp_dir / "live_endpoint_smoke.sqlite"),
        source_path=tmp_dir / "sqlite_smoke_catalog.toml",
        execute=True,
        allowed_connector_ids=["local_sqlite"],
        run_id="data-connector-sqlite-live-smoke-proof",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit AGILAB data connector live endpoint smoke evidence."
    )
    parser.add_argument("--catalog", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-connector", action="append", default=[])
    parser.add_argument("--compact", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    report = build_report(
        catalog_path=args.catalog,
        output_path=args.output,
        execute=args.execute,
        allowed_connector_ids=args.allow_connector,
    )
    if args.compact:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
