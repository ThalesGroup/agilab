#!/usr/bin/env python3
"""Emit AGILAB data connector facility evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
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

from agilab.data_connector_facility import (
    SCHEMA,
    SUPPORTED_KINDS,
    persist_data_connector_facility,
)
from agilab.data_connector_cloud import SUPPORTED_OBJECT_STORAGE_PROVIDERS


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


def _docs_check(repo_root: Path) -> dict[str, Any]:
    required = [
        "data connector facility report",
        "tools/data_connector_facility_report.py --compact",
        "SQL, OpenSearch/Elasticsearch, and object-storage connector definitions",
        "contract_validation_only",
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
        "data_connector_facility_docs_reference",
        "Data connector facility docs reference",
        ok,
        (
            "features docs expose the data connector facility command"
            if ok
            else "features docs do not expose the data connector facility command"
        ),
        evidence=[str(DOC_RELATIVE_PATH)],
        details=details,
    )


def build_report(
    *,
    repo_root: Path = REPO_ROOT,
    catalog_path: Path | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    if output_path is None:
        with tempfile.TemporaryDirectory(prefix="agilab-data-connectors-") as tmp_dir:
            return _build_report_with_paths(
                repo_root=repo_root,
                catalog_path=catalog_path,
                output_path=Path(tmp_dir) / "data_connector_facility.json",
            )
    return _build_report_with_paths(
        repo_root=repo_root,
        catalog_path=catalog_path,
        output_path=output_path,
    )


def _build_report_with_paths(
    *,
    repo_root: Path,
    catalog_path: Path | None,
    output_path: Path,
) -> dict[str, Any]:
    proof = persist_data_connector_facility(
        repo_root=repo_root,
        output_path=output_path,
        catalog_path=catalog_path,
    )
    state = proof["state"]
    summary = state.get("summary", {})
    connectors = state.get("connectors", [])
    connector_by_kind = {
        connector.get("kind"): connector
        for connector in connectors
        if isinstance(connector, dict)
    }
    object_storage_providers = sorted(
        {
            str(connector.get("provider", "") or "")
            for connector in connectors
            if isinstance(connector, dict)
            and connector.get("kind") == "object_storage"
        }
    )
    auth_refs = [
        str(connector.get("auth_ref", "") or "")
        for connector in connectors
        if isinstance(connector, dict) and connector.get("auth_ref")
    ]
    checks = [
        _check_result(
            "data_connector_facility_schema",
            "Data connector facility schema",
            proof["ok"]
            and state.get("schema") == SCHEMA
            and state.get("run_status") == "validated"
            and state.get("execution_mode") == "contract_validation_only",
            "connector catalog uses the supported schema and validation mode",
            evidence=["src/agilab/data_connector_facility.py", proof["catalog_path"]],
            details={
                "schema": state.get("schema"),
                "run_status": state.get("run_status"),
                "execution_mode": state.get("execution_mode"),
                "round_trip_ok": proof["round_trip_ok"],
                "issues": state.get("issues", []),
            },
        ),
        _check_result(
            "data_connector_facility_first_class_targets",
            "Data connector facility first-class targets",
            summary.get("connector_count") == 5
            and summary.get("supported_kinds") == sorted(SUPPORTED_KINDS)
            and summary.get("missing_kinds") == [],
            "catalog defines SQL, OpenSearch, and multi-cloud object-storage connectors",
            evidence=[proof["catalog_path"]],
            details=summary,
        ),
        _check_result(
            "data_connector_facility_required_fields",
            "Data connector facility required fields",
            connector_by_kind.get("sql", {}).get("query_mode") == "read_only"
            and connector_by_kind.get("opensearch", {}).get("index") == "agilab-runs-*"
            and object_storage_providers == list(SUPPORTED_OBJECT_STORAGE_PROVIDERS),
            "connector rows include kind-specific required fields",
            evidence=[proof["catalog_path"]],
            details={
                "connector_by_kind": connector_by_kind,
                "object_storage_providers": object_storage_providers,
            },
        ),
        _check_result(
            "data_connector_facility_secret_boundary",
            "Data connector facility secret boundary",
            summary.get("raw_secret_count") == 0
            and all(auth_ref.startswith("env:") for auth_ref in auth_refs)
            and state.get("provenance", {}).get("executes_network_probe") is False,
            "connector catalog uses environment references and no network probes",
            evidence=[proof["catalog_path"]],
            details={
                "auth_refs": auth_refs,
                "provenance": state.get("provenance", {}),
            },
        ),
        _check_result(
            "data_connector_facility_persistence",
            "Data connector facility persistence",
            proof["round_trip_ok"] and Path(proof["path"]).is_file(),
            "connector facility state is unchanged after JSON write/read",
            evidence=[proof["path"]],
            details={
                "path": proof["path"],
                "round_trip_ok": proof["round_trip_ok"],
            },
        ),
        _docs_check(repo_root),
    ]
    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "report": "Data connector facility report",
        "status": "pass" if failed == 0 else "fail",
        "scope": (
            "Validates plain-text SQL, OpenSearch, and object-storage connector "
            "definitions without opening network connections."
        ),
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "schema": state.get("schema"),
            "run_status": state.get("run_status"),
            "execution_mode": state.get("execution_mode"),
            "connector_count": summary.get("connector_count"),
            "supported_kinds": summary.get("supported_kinds"),
            "raw_secret_count": summary.get("raw_secret_count"),
            "network_probe_count": summary.get("network_probe_count"),
            "round_trip_ok": proof["round_trip_ok"],
            "catalog_path": proof["catalog_path"],
            "path": proof["path"],
        },
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit AGILAB data connector facility evidence."
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help="Optional connector catalog TOML path.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional JSON evidence output path.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact JSON without indentation.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    report = build_report(catalog_path=args.catalog, output_path=args.output)
    if args.compact:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
