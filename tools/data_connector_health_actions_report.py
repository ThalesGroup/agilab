#!/usr/bin/env python3
"""Emit AGILAB data connector health action evidence."""

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

from agilab.data_connector_health_actions import (
    SCHEMA,
    persist_data_connector_health_actions,
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


def _docs_check(repo_root: Path) -> dict[str, Any]:
    required = [
        "data connector health actions report",
        "tools/data_connector_health_actions_report.py --compact",
        "operator_trigger_contract_only",
        "operator-triggered health",
        "action rows",
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
        "data_connector_health_actions_docs_reference",
        "Data connector health actions docs reference",
        ok,
        (
            "features docs expose the data connector health actions command"
            if ok
            else "features docs do not expose the data connector health actions command"
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
        with tempfile.TemporaryDirectory(prefix="agilab-data-connector-health-actions-") as tmp_dir:
            return _build_report_with_path(
                repo_root=repo_root,
                catalog_path=catalog_path,
                output_path=Path(tmp_dir) / "data_connector_health_actions.json",
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
    proof = persist_data_connector_health_actions(
        repo_root=repo_root,
        output_path=output_path,
        catalog_path=catalog_path,
    )
    state = proof["state"]
    summary = state.get("summary", {})
    actions = state.get("actions", [])
    action_ids = sorted(str(action.get("action_id", "")) for action in actions)
    checks = [
        _check_result(
            "data_connector_health_actions_schema",
            "Data connector health actions schema",
            proof["ok"]
            and state.get("schema") == SCHEMA
            and state.get("run_status") == "ready_for_operator_trigger"
            and state.get("execution_mode") == "operator_trigger_contract_only",
            "connector health actions use the supported trigger-contract schema",
            evidence=["src/agilab/data_connector_health_actions.py", proof["catalog_path"]],
            details={
                "schema": state.get("schema"),
                "run_status": state.get("run_status"),
                "execution_mode": state.get("execution_mode"),
                "issues": state.get("issues", []),
            },
        ),
        _check_result(
            "data_connector_health_actions_rows",
            "Data connector health actions rows",
            summary.get("action_count") == 3
            and action_ids
            == [
                "artifact_object_store:health_probe",
                "ops_opensearch:health_probe",
                "warehouse_sql:health_probe",
            ]
            and summary.get("probe_types")
            == ["bucket_prefix_list", "driver_connectivity", "index_head"]
            and {action.get("default_status") for action in actions}
            == {"unknown_not_probed"},
            "one stable action row is available for each planned connector probe",
            evidence=[proof["catalog_path"]],
            details={"action_ids": action_ids, "actions": actions},
        ),
        _check_result(
            "data_connector_health_actions_operator_trigger",
            "Data connector health actions operator trigger",
            summary.get("operator_trigger_count") == 3
            and summary.get("pending_action_count") == 3
            and {action.get("trigger_mode") for action in actions}
            == {"operator_explicit_opt_in"}
            and {action.get("ui_control") for action in actions} == {"button"}
            and all(
                str(action.get("button_label", "")).startswith("Run health probe: ")
                for action in actions
            )
            and state.get("provenance", {}).get("supports_operator_trigger") is True,
            "one explicit operator button trigger is available for each connector probe",
            evidence=[proof["catalog_path"]],
            details={"summary": summary, "actions": actions},
        ),
        _check_result(
            "data_connector_health_actions_no_network",
            "Data connector health actions no-network boundary",
            (
                summary.get("network_probe_count") == 0
                and summary.get("executed_probe_count") == 0
                and all(
                    action.get("network_probe_executed") is False for action in actions
                )
                and state.get("provenance", {}).get("executes_network_probe") is False
                and state.get("provenance", {}).get("safe_for_public_evidence") is True
            ),
            "public health actions do not execute connector network probes",
            evidence=["src/agilab/data_connector_health_actions.py"],
            details={"summary": summary, "provenance": state.get("provenance", {})},
        ),
        _check_result(
            "data_connector_health_actions_credential_boundary",
            "Data connector health actions credentials boundary",
            summary.get("operator_context_required_count") == 3
            and summary.get("credential_gated_count") == 2
            and summary.get("no_credential_required_count") == 1
            and all(
                action.get("requires_operator_context") is True
                for action in actions
            )
            and all(
                action.get("requires_credentials")
                is (action.get("credential_source") != "none_required")
                for action in actions
            )
            and state.get("provenance", {}).get("requires_runtime_credentials") is True
            and state.get("provenance", {}).get("requires_operator_opt_in") is True,
            "health actions distinguish credential-gated and local connector probes",
            evidence=[proof["catalog_path"]],
            details={"actions": actions, "provenance": state.get("provenance", {})},
        ),
        _check_result(
            "data_connector_health_actions_persistence",
            "Data connector health actions persistence",
            proof["round_trip_ok"] and Path(proof["path"]).is_file(),
            "connector health actions are unchanged after JSON write/read",
            evidence=[proof["path"]],
            details={"path": proof["path"], "round_trip_ok": proof["round_trip_ok"]},
        ),
        _docs_check(repo_root),
    ]
    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "report": "Data connector health actions report",
        "status": "pass" if failed == 0 else "fail",
        "scope": (
            "Defines explicit operator-triggered health probe actions while "
            "keeping public evidence free of connector network execution."
        ),
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "schema": state.get("schema"),
            "run_status": state.get("run_status"),
            "execution_mode": state.get("execution_mode"),
            "action_count": summary.get("action_count"),
            "connector_count": summary.get("connector_count"),
            "operator_trigger_count": summary.get("operator_trigger_count"),
            "pending_action_count": summary.get("pending_action_count"),
            "pending_operator_trigger_count": summary.get("pending_operator_trigger_count"),
            "executed_probe_count": summary.get("executed_probe_count"),
            "network_probe_count": summary.get("network_probe_count"),
            "operator_context_required_count": summary.get(
                "operator_context_required_count"
            ),
            "credential_gated_count": summary.get("credential_gated_count"),
            "no_credential_required_count": summary.get(
                "no_credential_required_count"
            ),
            "probe_types": summary.get("probe_types"),
            "default_status_values": summary.get("default_status_values"),
            "result_status_values": summary.get("result_status_values"),
            "round_trip_ok": proof["round_trip_ok"],
            "catalog_path": proof["catalog_path"],
            "path": proof["path"],
        },
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit AGILAB data connector health action evidence."
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
