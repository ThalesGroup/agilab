#!/usr/bin/env python3
"""Emit AGILAB data connector health-probe planning evidence."""

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

from agilab.data_connector_health import (
    SCHEMA,
    persist_data_connector_health,
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
        "data connector health report",
        "tools/data_connector_health_report.py --compact",
        "health_probe_plan_only",
        "operator opt-in",
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
        "data_connector_health_docs_reference",
        "Data connector health docs reference",
        ok,
        (
            "features docs expose the data connector health command"
            if ok
            else "features docs do not expose the data connector health command"
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
        with tempfile.TemporaryDirectory(prefix="agilab-data-connector-health-") as tmp_dir:
            return _build_report_with_paths(
                repo_root=repo_root,
                catalog_path=catalog_path,
                output_path=Path(tmp_dir) / "data_connector_health.json",
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
    proof = persist_data_connector_health(
        repo_root=repo_root,
        output_path=output_path,
        catalog_path=catalog_path,
    )
    state = proof["state"]
    summary = state.get("summary", {})
    probes = state.get("probes", [])
    checks = [
        _check_result(
            "data_connector_health_schema",
            "Data connector health schema",
            proof["ok"]
            and state.get("schema") == SCHEMA
            and state.get("run_status") == "planned"
            and state.get("execution_mode") == "health_probe_plan_only",
            "connector health planning uses the supported schema and mode",
            evidence=["src/agilab/data_connector_health.py", proof["catalog_path"]],
            details={
                "schema": state.get("schema"),
                "run_status": state.get("run_status"),
                "execution_mode": state.get("execution_mode"),
                "round_trip_ok": proof["round_trip_ok"],
                "issues": state.get("issues", []),
            },
        ),
        _check_result(
            "data_connector_health_probe_plan",
            "Data connector health probe plan",
            summary.get("connector_count") == 3
            and summary.get("planned_probe_count") == 3
            and summary.get("probe_types")
            == ["bucket_prefix_list", "driver_connectivity", "index_head"],
            "health probe plan covers SQL, OpenSearch, and object storage",
            evidence=[proof["catalog_path"]],
            details={"summary": summary, "probes": probes},
        ),
        _check_result(
            "data_connector_health_opt_in_boundary",
            "Data connector health opt-in boundary",
            summary.get("opt_in_required_count") == 3
            and all(
                probe.get("operator_context_required") is True
                for probe in probes
                if isinstance(probe, dict)
            )
            and state.get("provenance", {}).get("requires_operator_opt_in") is True,
            "health probes require explicit operator opt-in",
            evidence=[proof["catalog_path"]],
            details={"provenance": state.get("provenance", {}), "probes": probes},
        ),
        _check_result(
            "data_connector_health_no_network",
            "Data connector health no network",
            summary.get("executed_probe_count") == 0
            and summary.get("network_probe_count") == 0
            and state.get("provenance", {}).get("executes_network_probe") is False,
            "public health evidence does not execute connector network probes",
            evidence=[proof["catalog_path"]],
            details={"summary": summary, "provenance": state.get("provenance", {})},
        ),
        _check_result(
            "data_connector_health_status_values",
            "Data connector health status values",
            summary.get("status_values") == ["unknown_not_probed"]
            and summary.get("unknown_status_count") == 3
            and summary.get("unhealthy_count") == 0,
            "planned probes remain unknown rather than claiming live health",
            evidence=[proof["catalog_path"]],
            details=summary,
        ),
        _check_result(
            "data_connector_health_persistence",
            "Data connector health persistence",
            proof["round_trip_ok"] and Path(proof["path"]).is_file(),
            "connector health plan is unchanged after JSON write/read",
            evidence=[proof["path"]],
            details={"path": proof["path"], "round_trip_ok": proof["round_trip_ok"]},
        ),
        _docs_check(repo_root),
    ]
    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "report": "Data connector health report",
        "status": "pass" if failed == 0 else "fail",
        "scope": (
            "Plans connector health probes with operator opt-in while keeping "
            "public evidence in health_probe_plan_only mode."
        ),
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "schema": state.get("schema"),
            "run_status": state.get("run_status"),
            "execution_mode": state.get("execution_mode"),
            "connector_count": summary.get("connector_count"),
            "planned_probe_count": summary.get("planned_probe_count"),
            "executed_probe_count": summary.get("executed_probe_count"),
            "opt_in_required_count": summary.get("opt_in_required_count"),
            "network_probe_count": summary.get("network_probe_count"),
            "unknown_status_count": summary.get("unknown_status_count"),
            "unhealthy_count": summary.get("unhealthy_count"),
            "probe_types": summary.get("probe_types"),
            "status_values": summary.get("status_values"),
            "round_trip_ok": proof["round_trip_ok"],
            "catalog_path": proof["catalog_path"],
            "path": proof["path"],
        },
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit AGILAB data connector health-probe planning evidence."
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
