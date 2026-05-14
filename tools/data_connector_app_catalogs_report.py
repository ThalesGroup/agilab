#!/usr/bin/env python3
"""Emit AGILAB app-local data connector catalog evidence."""

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

from agilab.data_connector_app_catalogs import (
    SCHEMA,
    persist_data_connector_app_catalogs,
)

EXPECTED_APPS = [
    "execution_pandas_project",
    "execution_polars_project",
    "flight_telemetry_project",
    "uav_queue_project",
    "uav_relay_queue_project",
    "weather_forecast_project",
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
        "data connector app catalogs report",
        "tools/data_connector_app_catalogs_report.py --compact",
        "app_catalog_validation_only",
        "app-local connector catalogs",
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
        "data_connector_app_catalogs_docs_reference",
        "Data connector app catalogs docs reference",
        ok,
        (
            "features docs expose the data connector app catalogs command"
            if ok
            else "features docs do not expose the data connector app catalogs command"
        ),
        evidence=[str(DOC_RELATIVE_PATH)],
        details=details,
    )


def build_report(
    *,
    repo_root: Path = REPO_ROOT,
    output_path: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    if output_path is None:
        with tempfile.TemporaryDirectory(prefix="agilab-data-connector-app-catalogs-") as tmp_dir:
            return _build_report_with_path(
                repo_root=repo_root,
                output_path=Path(tmp_dir) / "data_connector_app_catalogs.json",
            )
    return _build_report_with_path(repo_root=repo_root, output_path=output_path)


def _build_report_with_path(*, repo_root: Path, output_path: Path) -> dict[str, Any]:
    proof = persist_data_connector_app_catalogs(
        repo_root=repo_root,
        output_path=output_path,
    )
    state = proof["state"]
    summary = state.get("summary", {})
    app_rows = state.get("apps", [])
    apps = {row.get("app"): row for row in app_rows if isinstance(row, dict)}
    catalog_paths = [str(row.get("catalog_path", "")) for row in app_rows]
    checks = [
        _check_result(
            "data_connector_app_catalogs_schema",
            "Data connector app catalogs schema",
            proof["ok"]
            and state.get("schema") == SCHEMA
            and state.get("run_status") == "validated"
            and state.get("execution_mode") == "app_catalog_validation_only",
            "app connector catalogs use the supported validation-only schema",
            evidence=["src/agilab/data_connector_app_catalogs.py"],
            details={
                "schema": state.get("schema"),
                "run_status": state.get("run_status"),
                "execution_mode": state.get("execution_mode"),
                "issues": state.get("issues", []),
            },
        ),
        _check_result(
            "data_connector_app_catalogs_discovery",
            "Data connector app catalogs discovery",
            summary.get("app_catalog_count") == 6
            and set(EXPECTED_APPS) == set(apps)
            and all("/connectors/data_connectors.toml" in path for path in catalog_paths),
            "report discovers app-local connector catalogs from app_settings.toml",
            evidence=catalog_paths,
            details={"apps": app_rows},
        ),
        _check_result(
            "data_connector_app_catalogs_facility_contract",
            "Data connector app catalogs facility contract",
            all(row.get("catalog_run_status") == "validated" for row in app_rows)
            and all(row.get("connector_count") == 3 for row in app_rows)
            and all(
                row.get("supported_kinds") == ["object_storage", "opensearch", "sql"]
                for row in app_rows
            ),
            "each app-local catalog validates SQL, OpenSearch, and object storage",
            evidence=catalog_paths,
            details={"apps": app_rows},
        ),
        _check_result(
            "data_connector_app_catalogs_resolution",
            "Data connector app catalogs resolution",
            all(row.get("resolution_run_status") == "resolved" for row in app_rows)
            and all(row.get("missing_ref_count") == 0 for row in app_rows)
            and summary.get("page_connector_ref_count") == 15,
            "app-local connector references resolve for app and page settings",
            evidence=[str(row.get("settings_path", "")) for row in app_rows],
            details={"apps": app_rows},
        ),
        _check_result(
            "data_connector_app_catalogs_legacy_fallbacks",
            "Data connector app catalogs legacy fallbacks",
            summary.get("legacy_path_count") == 12
            and all(row.get("legacy_path_count") == 2 for row in app_rows),
            "app-local catalog migration keeps legacy path fallbacks visible",
            evidence=[str(row.get("settings_path", "")) for row in app_rows],
            details={"apps": app_rows},
        ),
        _check_result(
            "data_connector_app_catalogs_no_network",
            "Data connector app catalogs no-network boundary",
            summary.get("network_probe_count") == 0
            and state.get("provenance", {}).get("executes_network_probe") is False,
            "app catalog validation and resolution do not execute network probes",
            evidence=["src/agilab/data_connector_app_catalogs.py"],
            details={"summary": summary, "provenance": state.get("provenance", {})},
        ),
        _check_result(
            "data_connector_app_catalogs_persistence",
            "Data connector app catalogs persistence",
            proof["round_trip_ok"] and Path(proof["path"]).is_file(),
            "app connector catalog state is unchanged after JSON write/read",
            evidence=[proof["path"]],
            details={"path": proof["path"], "round_trip_ok": proof["round_trip_ok"]},
        ),
        _docs_check(repo_root),
    ]
    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "report": "Data connector app catalogs report",
        "status": "pass" if failed == 0 else "fail",
        "scope": (
            "Validates app-local connector catalogs referenced from built-in "
            "app_settings.toml files without executing connector probes."
        ),
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "schema": state.get("schema"),
            "run_status": state.get("run_status"),
            "execution_mode": state.get("execution_mode"),
            "app_catalog_count": summary.get("app_catalog_count"),
            "connector_count": summary.get("connector_count"),
            "page_connector_ref_count": summary.get("page_connector_ref_count"),
            "legacy_path_count": summary.get("legacy_path_count"),
            "missing_ref_count": summary.get("missing_ref_count"),
            "network_probe_count": summary.get("network_probe_count"),
            "apps": summary.get("apps"),
            "round_trip_ok": proof["round_trip_ok"],
            "path": proof["path"],
        },
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit AGILAB app-local data connector catalog evidence."
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--compact", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    report = build_report(output_path=args.output)
    if args.compact:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
