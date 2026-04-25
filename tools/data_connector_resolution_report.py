#!/usr/bin/env python3
"""Emit AGILAB data connector app-settings resolution evidence."""

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

from agilab.data_connector_resolution import (
    SCHEMA,
    persist_data_connector_resolution,
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
        "data connector resolution report",
        "tools/data_connector_resolution_report.py --compact",
        "connector-aware app/page resolution",
        "legacy_path_fallback",
        "contract_resolution_only",
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
        "data_connector_resolution_docs_reference",
        "Data connector resolution docs reference",
        ok,
        (
            "features docs expose the data connector resolution command"
            if ok
            else "features docs do not expose the data connector resolution command"
        ),
        evidence=[str(DOC_RELATIVE_PATH)],
        details=details,
    )


def build_report(
    *,
    repo_root: Path = REPO_ROOT,
    settings_path: Path | None = None,
    catalog_path: Path | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    if output_path is None:
        with tempfile.TemporaryDirectory(
            prefix="agilab-data-connector-resolution-"
        ) as tmp_dir:
            return _build_report_with_paths(
                repo_root=repo_root,
                settings_path=settings_path,
                catalog_path=catalog_path,
                output_path=Path(tmp_dir) / "data_connector_resolution.json",
            )
    return _build_report_with_paths(
        repo_root=repo_root,
        settings_path=settings_path,
        catalog_path=catalog_path,
        output_path=output_path,
    )


def _build_report_with_paths(
    *,
    repo_root: Path,
    settings_path: Path | None,
    catalog_path: Path | None,
    output_path: Path,
) -> dict[str, Any]:
    proof = persist_data_connector_resolution(
        repo_root=repo_root,
        output_path=output_path,
        settings_path=settings_path,
        catalog_path=catalog_path,
    )
    state = proof["state"]
    summary = state.get("summary", {})
    resolutions = state.get("resolutions", [])
    legacy_fallbacks = state.get("legacy_fallbacks", [])
    resolved_targets = {
        row.get("ref_path"): row
        for row in resolutions
        if isinstance(row, dict)
    }
    checks = [
        _check_result(
            "data_connector_resolution_schema",
            "Data connector resolution schema",
            proof["ok"]
            and state.get("schema") == SCHEMA
            and state.get("run_status") == "resolved"
            and state.get("execution_mode") == "contract_resolution_only",
            "connector resolution uses the supported schema and resolution mode",
            evidence=["src/agilab/data_connector_resolution.py", proof["settings_path"]],
            details={
                "schema": state.get("schema"),
                "run_status": state.get("run_status"),
                "execution_mode": state.get("execution_mode"),
                "round_trip_ok": proof["round_trip_ok"],
                "issues": state.get("issues", []),
            },
        ),
        _check_result(
            "data_connector_resolution_app_refs",
            "Data connector resolution app references",
            summary.get("connector_ref_count") == 5
            and summary.get("top_level_ref_count") == 3
            and summary.get("resolved_connector_ref_count") == 5
            and summary.get("missing_ref_count") == 0
            and summary.get("resolved_kinds") == ["object_storage", "opensearch", "sql"],
            "app-level connector references resolve to catalog entries",
            evidence=[proof["settings_path"], proof["catalog_path"]],
            details={
                "summary": summary,
                "resolutions": resolutions,
            },
        ),
        _check_result(
            "data_connector_resolution_page_refs",
            "Data connector resolution page references",
            summary.get("page_connector_ref_count") == 2
            and resolved_targets.get(
                "page_connector_refs.release_decision.evidence_index",
                {},
            ).get("kind")
            == "opensearch"
            and resolved_targets.get(
                "page_connector_refs.release_decision.artifact_store",
                {},
            ).get("kind")
            == "object_storage",
            "page-specific connector references resolve for analysis pages",
            evidence=[proof["settings_path"]],
            details={"resolutions": resolutions},
        ),
        _check_result(
            "data_connector_resolution_legacy_fallback",
            "Data connector resolution legacy fallback",
            summary.get("legacy_path_count") == 2
            and summary.get("legacy_fallback_preserved") is True
            and {row.get("ref_name") for row in legacy_fallbacks}
            == {"artifact_root", "telemetry_csv"},
            "legacy raw path fallback rows remain available during migration",
            evidence=[proof["settings_path"]],
            details={"legacy_fallbacks": legacy_fallbacks},
        ),
        _check_result(
            "data_connector_resolution_no_network",
            "Data connector resolution no network",
            summary.get("network_probe_count") == 0
            and state.get("provenance", {}).get("executes_network_probe") is False
            and state.get("source", {}).get("facility_run_status") == "validated",
            "connector resolution does not perform network probes",
            evidence=[proof["catalog_path"]],
            details={"provenance": state.get("provenance", {}), "source": state.get("source", {})},
        ),
        _check_result(
            "data_connector_resolution_persistence",
            "Data connector resolution persistence",
            proof["round_trip_ok"] and Path(proof["path"]).is_file(),
            "connector resolution state is unchanged after JSON write/read",
            evidence=[proof["path"]],
            details={"path": proof["path"], "round_trip_ok": proof["round_trip_ok"]},
        ),
        _docs_check(repo_root),
    ]
    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "report": "Data connector resolution report",
        "status": "pass" if failed == 0 else "fail",
        "scope": (
            "Validates connector-aware app/page resolution against the "
            "plain-text connector catalog while preserving legacy_path_fallback rows."
        ),
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "schema": state.get("schema"),
            "run_status": state.get("run_status"),
            "execution_mode": state.get("execution_mode"),
            "connector_ref_count": summary.get("connector_ref_count"),
            "top_level_ref_count": summary.get("top_level_ref_count"),
            "resolved_connector_ref_count": summary.get("resolved_connector_ref_count"),
            "page_connector_ref_count": summary.get("page_connector_ref_count"),
            "legacy_path_count": summary.get("legacy_path_count"),
            "missing_ref_count": summary.get("missing_ref_count"),
            "network_probe_count": summary.get("network_probe_count"),
            "catalog_run_status": summary.get("catalog_run_status"),
            "legacy_fallback_preserved": summary.get("legacy_fallback_preserved"),
            "resolved_kinds": summary.get("resolved_kinds"),
            "round_trip_ok": proof["round_trip_ok"],
            "settings_path": proof["settings_path"],
            "catalog_path": proof["catalog_path"],
            "path": proof["path"],
        },
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit AGILAB data connector app-settings resolution evidence."
    )
    parser.add_argument("--settings", type=Path, default=None)
    parser.add_argument("--catalog", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--compact", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    report = build_report(
        settings_path=args.settings,
        catalog_path=args.catalog,
        output_path=args.output,
    )
    if args.compact:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
