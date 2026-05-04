#!/usr/bin/env python3
"""Emit AGILAB data connector runtime adapter binding evidence."""

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

from agilab.data_connector_runtime_adapters import (
    SCHEMA,
    persist_data_connector_runtime_adapters,
)


EXPECTED_ADAPTER_IDS = [
    "artifact_object_store:runtime_adapter",
    "azure_artifact_store:runtime_adapter",
    "gcp_artifact_store:runtime_adapter",
    "ops_opensearch:runtime_adapter",
    "warehouse_sql:runtime_adapter",
]
EXPECTED_OPERATIONS = [
    "object_storage_prefix_list",
    "opensearch_index_head",
    "read_only_connectivity_check",
]
EXPECTED_RUNTIME_DEPENDENCIES = [
    "package:azure-storage-blob",
    "package:boto3",
    "package:google-cloud-storage",
    "package:psycopg",
    "python:urllib.request",
]


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
        "data connector runtime adapters report",
        "tools/data_connector_runtime_adapters_report.py --compact",
        "runtime_adapter_contract_only",
        "credentialed connector adapters",
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
        "data_connector_runtime_adapters_docs_reference",
        "Data connector runtime adapters docs reference",
        ok,
        (
            "features docs expose the data connector runtime adapters command"
            if ok
            else "features docs do not expose the runtime adapters command"
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
        with tempfile.TemporaryDirectory(prefix="agilab-data-connector-adapters-") as tmp_dir:
            return _build_report_with_path(
                repo_root=repo_root,
                catalog_path=catalog_path,
                output_path=Path(tmp_dir) / "data_connector_runtime_adapters.json",
            )
    return _build_report_with_path(
        repo_root=repo_root,
        catalog_path=catalog_path,
        output_path=output_path,
    )


def _build_report_with_path(
    *,
    repo_root: Path,
    catalog_path: Path | None,
    output_path: Path,
) -> dict[str, Any]:
    proof = persist_data_connector_runtime_adapters(
        repo_root=repo_root,
        output_path=output_path,
        catalog_path=catalog_path,
    )
    state = proof["state"]
    summary = state.get("summary", {})
    adapters = state.get("adapters", [])
    adapter_ids = sorted(str(adapter.get("adapter_id", "")) for adapter in adapters)
    checks = [
        _check_result(
            "data_connector_runtime_adapters_schema",
            "Data connector runtime adapters schema",
            proof["ok"]
            and state.get("schema") == SCHEMA
            and state.get("run_status") == "ready_for_runtime_binding"
            and state.get("execution_mode") == "runtime_adapter_contract_only",
            "runtime adapter bindings use the supported contract-only schema",
            evidence=[
                "src/agilab/data_connector_runtime_adapters.py",
                proof["catalog_path"],
            ],
            details={
                "schema": state.get("schema"),
                "run_status": state.get("run_status"),
                "execution_mode": state.get("execution_mode"),
                "issues": state.get("issues", []),
            },
        ),
        _check_result(
            "data_connector_runtime_adapters_rows",
            "Data connector runtime adapters rows",
            summary.get("adapter_count") == 5
            and adapter_ids == EXPECTED_ADAPTER_IDS
            and summary.get("operations") == EXPECTED_OPERATIONS
            and summary.get("runtime_dependencies") == EXPECTED_RUNTIME_DEPENDENCIES,
            "one runtime adapter binding is available for each connector kind",
            evidence=[proof["catalog_path"]],
            details={"adapter_ids": adapter_ids, "adapters": adapters},
        ),
        _check_result(
            "data_connector_runtime_adapters_credential_boundary",
            "Data connector runtime adapters credential boundary",
            summary.get("credential_deferred_count") == 4
            and summary.get("no_credential_required_count") == 1
            and summary.get("credential_value_materialized_count") == 0
            and all(
                adapter.get("credential_value_materialized") is False
                for adapter in adapters
            )
            and state.get("provenance", {}).get("credential_values_materialized")
            is False,
            "runtime adapters defer credential resolution to operator runtime",
            evidence=[proof["catalog_path"]],
            details={"summary": summary, "adapters": adapters},
        ),
        _check_result(
            "data_connector_runtime_adapters_health_actions",
            "Data connector runtime adapters health actions",
            summary.get("health_action_binding_count") == 5
            and sorted(str(adapter.get("health_action_id", "")) for adapter in adapters)
            == [
                "artifact_object_store:health_probe",
                "azure_artifact_store:health_probe",
                "gcp_artifact_store:health_probe",
                "ops_opensearch:health_probe",
                "warehouse_sql:health_probe",
            ]
            and all(adapter.get("supports_health_action") is True for adapter in adapters),
            "runtime adapters bind to the operator-triggered health action rows",
            evidence=["tools/data_connector_health_actions_report.py"],
            details={"adapters": adapters},
        ),
        _check_result(
            "data_connector_runtime_adapters_no_network",
            "Data connector runtime adapters no-network boundary",
            summary.get("network_probe_count") == 0
            and summary.get("executed_adapter_count") == 0
            and all(adapter.get("network_probe_executed") is False for adapter in adapters)
            and state.get("provenance", {}).get("executes_network_probe") is False
            and state.get("provenance", {}).get("safe_for_public_evidence") is True,
            "public adapter evidence does not execute connector networks",
            evidence=["src/agilab/data_connector_runtime_adapters.py"],
            details={"summary": summary, "provenance": state.get("provenance", {})},
        ),
        _check_result(
            "data_connector_runtime_adapters_persistence",
            "Data connector runtime adapters persistence",
            proof["round_trip_ok"] and Path(proof["path"]).is_file(),
            "runtime adapter bindings are unchanged after JSON write/read",
            evidence=[proof["path"]],
            details={"path": proof["path"], "round_trip_ok": proof["round_trip_ok"]},
        ),
        _docs_check(repo_root),
    ]
    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "report": "Data connector runtime adapters report",
        "status": "pass" if failed == 0 else "fail",
        "scope": (
            "Defines runtime adapter bindings and credential deferral for "
            "connector health actions without executing endpoint probes."
        ),
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "schema": state.get("schema"),
            "run_status": state.get("run_status"),
            "execution_mode": state.get("execution_mode"),
            "connector_count": summary.get("connector_count"),
            "adapter_count": summary.get("adapter_count"),
            "runtime_ready_count": summary.get("runtime_ready_count"),
            "credential_deferred_count": summary.get("credential_deferred_count"),
            "no_credential_required_count": summary.get(
                "no_credential_required_count"
            ),
            "operator_opt_in_required_count": summary.get(
                "operator_opt_in_required_count"
            ),
            "health_action_binding_count": summary.get(
                "health_action_binding_count"
            ),
            "executed_adapter_count": summary.get("executed_adapter_count"),
            "network_probe_count": summary.get("network_probe_count"),
            "credential_value_materialized_count": summary.get(
                "credential_value_materialized_count"
            ),
            "adapter_kinds": summary.get("adapter_kinds"),
            "operations": summary.get("operations"),
            "runtime_dependencies": summary.get("runtime_dependencies"),
            "round_trip_ok": proof["round_trip_ok"],
            "catalog_path": proof["catalog_path"],
            "path": proof["path"],
        },
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit AGILAB data connector runtime adapter binding evidence."
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
