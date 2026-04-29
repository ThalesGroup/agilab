#!/usr/bin/env python3
"""Emit account-free cloud-emulator connector compatibility evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse
import sys
import tempfile
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG_RELATIVE_PATH = Path("docs/source/data/cloud_emulator_connectors_sample.toml")
DOC_RELATIVE_PATH = Path("docs/source/data-connectors.rst")
FEATURES_RELATIVE_PATH = Path("docs/source/features.rst")
LOCAL_ENDPOINT_HOSTS = {"127.0.0.1", "localhost", "host.docker.internal"}
EXPECTED_OBJECT_STORAGE_PROVIDERS = ["azure_blob", "gcs", "s3"]


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

from agilab.data_connector_facility import (  # noqa: E402
    load_connector_catalog,
    persist_data_connector_facility,
)
from agilab.data_connector_runtime_adapters import (  # noqa: E402
    persist_data_connector_runtime_adapters,
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


def _connector_rows(catalog: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = catalog.get("connectors", [])
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _object_storage_rows(catalog: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        row for row in _connector_rows(catalog)
        if str(row.get("kind", "") or "") == "object_storage"
    ]


def _search_rows(catalog: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        row for row in _connector_rows(catalog)
        if str(row.get("kind", "") or "") == "opensearch"
    ]


def _is_local_endpoint(raw_url: str) -> bool:
    parsed = urlparse(raw_url)
    return parsed.scheme in {"http", "https"} and parsed.hostname in LOCAL_ENDPOINT_HOSTS


def _local_endpoint_issues(catalog: Mapping[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for row in [*_object_storage_rows(catalog), *_search_rows(catalog)]:
        connector_id = str(row.get("id", "") or "")
        raw_url = str(row.get("endpoint_url", "") or row.get("url", "") or "")
        if not raw_url:
            issues.append(
                {
                    "connector_id": connector_id,
                    "message": "missing local emulator endpoint",
                }
            )
            continue
        if not _is_local_endpoint(raw_url):
            issues.append(
                {
                    "connector_id": connector_id,
                    "message": f"endpoint is not local/emulated: {raw_url}",
                }
            )
    return issues


def _runtime_adapter_by_connector(adapters: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {
        str(adapter.get("connector_id", "") or ""): adapter
        for adapter in adapters
    }


def _docs_check(repo_root: Path) -> dict[str, Any]:
    required_by_path = {
        DOC_RELATIVE_PATH: [
            "cloud-emulators",
            "tools/data_connector_cloud_emulator_report.py --compact",
            "MinIO",
            "Azurite",
            "fake-gcs-server",
            "API-contract and emulator-compatible validation",
        ],
        FEATURES_RELATIVE_PATH: [
            "data connector cloud emulator report",
            "tools/data_connector_cloud_emulator_report.py --compact",
            "cloud_emulator_contract_only",
        ],
    }
    missing: dict[str, list[str]] = {}
    for relative_path, required in required_by_path.items():
        path = repo_root / relative_path
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            missing[str(relative_path)] = [str(exc)]
            continue
        missing_for_path = [needle for needle in required if needle not in text]
        if missing_for_path:
            missing[str(relative_path)] = missing_for_path
    return _check_result(
        "data_connector_cloud_emulator_docs_reference",
        "Data connector cloud emulator docs reference",
        not missing,
        (
            "docs expose the account-free cloud emulator validation path"
            if not missing
            else "docs do not expose the cloud emulator validation path"
        ),
        evidence=[str(DOC_RELATIVE_PATH), str(FEATURES_RELATIVE_PATH)],
        details={"missing": missing},
    )


def build_report(
    *,
    repo_root: Path = REPO_ROOT,
    catalog_path: Path | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    catalog_path = catalog_path or (repo_root / CATALOG_RELATIVE_PATH)
    if not catalog_path.is_absolute():
        catalog_path = repo_root / catalog_path
    if output_path is None:
        with tempfile.TemporaryDirectory(prefix="agilab-cloud-emulator-") as tmp_dir:
            return _build_report_with_paths(
                repo_root=repo_root,
                catalog_path=catalog_path,
                output_path=Path(tmp_dir) / "data_connector_cloud_emulator.json",
            )
    return _build_report_with_paths(
        repo_root=repo_root,
        catalog_path=catalog_path,
        output_path=output_path,
    )


def _build_report_with_paths(
    *,
    repo_root: Path,
    catalog_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    catalog = load_connector_catalog(catalog_path)
    facility_proof = persist_data_connector_facility(
        repo_root=repo_root,
        output_path=output_path,
        catalog_path=catalog_path,
    )
    adapter_output = output_path.with_name("data_connector_cloud_emulator_adapters.json")
    adapter_proof = persist_data_connector_runtime_adapters(
        repo_root=repo_root,
        output_path=adapter_output,
        catalog_path=catalog_path,
    )
    facility_state = facility_proof["state"]
    adapter_state = adapter_proof["state"]
    object_rows = _object_storage_rows(catalog)
    search_rows = _search_rows(catalog)
    endpoint_issues = _local_endpoint_issues(catalog)
    providers = sorted(str(row.get("provider", "") or "") for row in object_rows)
    adapters = adapter_state.get("adapters", [])
    adapter_by_connector = _runtime_adapter_by_connector(
        [adapter for adapter in adapters if isinstance(adapter, dict)]
    )
    object_targets = {
        connector_id: str(adapter.get("target", "") or "")
        for connector_id, adapter in adapter_by_connector.items()
        if connector_id in {str(row.get("id", "") or "") for row in object_rows}
    }
    endpoint_urls = {
        str(row.get("id", "") or ""): str(row.get("endpoint_url", "") or "")
        for row in object_rows
    }
    checks = [
        _check_result(
            "data_connector_cloud_emulator_schema",
            "Data connector cloud emulator schema",
            facility_proof["ok"]
            and adapter_proof["ok"]
            and facility_state.get("run_status") == "validated"
            and adapter_state.get("run_status") == "ready_for_runtime_binding",
            "emulator catalog validates through the existing connector contracts",
            evidence=[str(catalog_path)],
            details={
                "facility_run_status": facility_state.get("run_status"),
                "adapter_run_status": adapter_state.get("run_status"),
                "facility_issues": facility_state.get("issues", []),
                "adapter_issues": adapter_state.get("issues", []),
            },
        ),
        _check_result(
            "data_connector_cloud_emulator_providers",
            "Data connector cloud emulator providers",
            providers == EXPECTED_OBJECT_STORAGE_PROVIDERS
            and len(search_rows) == 1,
            "MinIO/S3, Azurite/Azure Blob, fake-gcs-server/GCS, and local search are covered",
            evidence=[str(catalog_path)],
            details={"object_storage_providers": providers, "search_rows": search_rows},
        ),
        _check_result(
            "data_connector_cloud_emulator_endpoint_boundary",
            "Data connector cloud emulator endpoint boundary",
            not endpoint_issues,
            "emulator validation uses local endpoints and no real cloud account",
            evidence=[str(catalog_path)],
            details={"endpoint_issues": endpoint_issues, "endpoint_urls": endpoint_urls},
        ),
        _check_result(
            "data_connector_cloud_emulator_runtime_mapping",
            "Data connector cloud emulator runtime mapping",
            sorted(object_targets.values()) == [
                "azure_blob://devstoreaccount1/agilab-emulator/experiments/",
                "gs://agilab-emulator/experiments/",
                "s3://agilab-emulator/experiments/",
            ]
            and adapter_state.get("summary", {}).get("network_probe_count") == 0
            and adapter_state.get("summary", {}).get("credential_value_materialized_count") == 0,
            "emulator connectors map to production-compatible runtime targets without network probes",
            evidence=["src/agilab/data_connector_runtime_adapters.py"],
            details={
                "object_targets": object_targets,
                "adapter_summary": adapter_state.get("summary", {}),
            },
        ),
        _check_result(
            "data_connector_cloud_emulator_persistence",
            "Data connector cloud emulator persistence",
            Path(facility_proof["path"]).is_file()
            and Path(adapter_proof["path"]).is_file()
            and facility_proof["round_trip_ok"]
            and adapter_proof["round_trip_ok"],
            "emulator facility and adapter evidence survives JSON write/read",
            evidence=[facility_proof["path"], adapter_proof["path"]],
            details={
                "facility_round_trip_ok": facility_proof["round_trip_ok"],
                "adapter_round_trip_ok": adapter_proof["round_trip_ok"],
            },
        ),
        _docs_check(repo_root),
    ]
    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "report": "Data connector cloud emulator report",
        "status": "pass" if failed == 0 else "fail",
        "scope": (
            "Validates account-free cloud emulator connector contracts for "
            "AWS/S3, Azure Blob, Google Cloud Storage, and local search endpoints."
        ),
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "execution_mode": "cloud_emulator_contract_only",
            "catalog_path": str(catalog_path),
            "facility_path": facility_proof["path"],
            "adapter_path": adapter_proof["path"],
            "connector_count": facility_state.get("summary", {}).get("connector_count"),
            "object_storage_emulator_count": len(object_rows),
            "search_emulator_count": len(search_rows),
            "object_storage_providers": providers,
            "endpoint_issue_count": len(endpoint_issues),
            "real_cloud_account_required": False,
            "network_probe_count": adapter_state.get("summary", {}).get("network_probe_count"),
            "credential_value_materialized_count": adapter_state.get("summary", {}).get(
                "credential_value_materialized_count"
            ),
        },
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit AGILAB account-free cloud emulator connector evidence."
    )
    parser.add_argument("--catalog", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--compact", action="store_true")
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
