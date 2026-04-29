#!/usr/bin/env python3
"""Emit AGILAB data connector view-surface evidence."""

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

from agilab.data_connector_view_surface import (  # noqa: E402
    SCHEMA,
    persist_data_connector_view_surface,
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


def _surface_by_id(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("id", "")): row
        for row in state.get("view_surfaces", [])
        if isinstance(row, dict)
    }


def _surface_ready(state: dict[str, Any], surface_id: str) -> bool:
    return _surface_by_id(state).get(surface_id, {}).get("status") == "ready"


def _docs_check(repo_root: Path) -> dict[str, Any]:
    required = [
        "connector-aware view surface report",
        "tools/data_connector_view_surface_report.py --compact",
        "agilab.data_connector_view_surface.v1",
        "connector_view_surface_contract_only",
        "Release Decision",
        "external artifact traceability",
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
        "data_connector_view_surface_docs_reference",
        "Data connector view surface docs reference",
        ok,
        (
            "features docs expose the data connector view-surface command"
            if ok
            else "features docs do not expose the data connector view-surface command"
        ),
        evidence=[str(DOC_RELATIVE_PATH)],
        details=details,
    )


def build_report(
    *,
    repo_root: Path = REPO_ROOT,
    settings_path: Path | None = None,
    catalog_path: Path | None = None,
    release_decision_page: Path | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    if output_path is None:
        with tempfile.TemporaryDirectory(
            prefix="agilab-data-connector-view-surface-"
        ) as tmp_dir:
            return _build_report_with_path(
                repo_root=repo_root,
                settings_path=settings_path,
                catalog_path=catalog_path,
                release_decision_page=release_decision_page,
                output_path=Path(tmp_dir) / "data_connector_view_surface.json",
            )
    return _build_report_with_path(
        repo_root=repo_root,
        settings_path=settings_path,
        catalog_path=catalog_path,
        release_decision_page=release_decision_page,
        output_path=output_path,
    )


def _build_report_with_path(
    *,
    repo_root: Path,
    settings_path: Path | None,
    catalog_path: Path | None,
    release_decision_page: Path | None,
    output_path: Path,
) -> dict[str, Any]:
    proof = persist_data_connector_view_surface(
        repo_root=repo_root,
        output_path=output_path,
        settings_path=settings_path,
        catalog_path=catalog_path,
        release_decision_page=release_decision_page,
    )
    state = proof["state"]
    summary = state.get("summary", {})
    flags = state.get("source_flags", {})
    surfaces = _surface_by_id(state)
    provenance = state.get("provenance", {})
    checks = [
        _check_result(
            "data_connector_view_surface_schema",
            "Data connector view surface schema",
            proof["ok"]
            and state.get("schema") == SCHEMA
            and state.get("run_status") == "validated"
            and state.get("execution_mode") == "connector_view_surface_contract_only",
            "connector view surface uses the supported contract schema",
            evidence=["src/agilab/data_connector_view_surface.py"],
            details={
                "schema": state.get("schema"),
                "run_status": state.get("run_status"),
                "execution_mode": state.get("execution_mode"),
                "round_trip_ok": proof["round_trip_ok"],
                "issues": state.get("issues", []),
            },
        ),
        _check_result(
            "data_connector_view_surface_release_decision_mount",
            "Data connector view surface Release Decision mount",
            flags.get("release_decision_page_loaded") is True
            and flags.get("imports_live_renderer") is True
            and flags.get("builds_connector_preview") is True
            and flags.get("calls_live_renderer") is True
            and flags.get("stores_connector_live_ui_state") is True,
            "Release Decision page mounts the connector-aware view surface",
            evidence=[proof["release_decision_page"]],
            details={"source_flags": flags},
        ),
        _check_result(
            "data_connector_view_surface_connector_state_provenance",
            "Data connector view surface connector state provenance",
            _surface_ready(state, "connector_state_provenance_panel")
            and summary.get("connector_card_count") == 5
            and summary.get("page_binding_count") == 2,
            "view surface exposes connector state, page bindings, fallbacks, and roots",
            evidence=surfaces.get("connector_state_provenance_panel", {}).get(
                "evidence", []
            ),
            details=surfaces.get("connector_state_provenance_panel", {}),
        ),
        _check_result(
            "data_connector_view_surface_health_status_panel",
            "Data connector view surface health status panel",
            _surface_ready(state, "connector_health_status_panel")
            and summary.get("health_probe_status_count") == 5
            and summary.get("network_probe_count") == 0,
            "view surface exposes planned connector health while keeping probes gated",
            evidence=surfaces.get("connector_health_status_panel", {}).get(
                "evidence", []
            ),
            details=surfaces.get("connector_health_status_panel", {}),
        ),
        _check_result(
            "data_connector_view_surface_import_export_provenance",
            "Data connector view surface import/export provenance",
            _surface_ready(state, "import_export_provenance_panel")
            and summary.get("import_export_provenance_ready") is True,
            "view surface imports external manifest evidence and exports it in decisions",
            evidence=surfaces.get("import_export_provenance_panel", {}).get(
                "evidence", []
            ),
            details=surfaces.get("import_export_provenance_panel", {}),
        ),
        _check_result(
            "data_connector_view_surface_external_artifact_traceability",
            "Data connector view surface external artifact traceability",
            _surface_ready(state, "external_artifact_traceability_panel")
            and summary.get("external_artifact_traceability_ready") is True,
            "view surface imports CI artifact harvest rows with checksum and provenance fields",
            evidence=surfaces.get("external_artifact_traceability_panel", {}).get(
                "evidence", []
            ),
            details=surfaces.get("external_artifact_traceability_panel", {}),
        ),
        _check_result(
            "data_connector_view_surface_no_network",
            "Data connector view surface no-network boundary",
            summary.get("network_probe_count") == 0
            and summary.get("command_execution_count") == 0
            and provenance.get("executes_network_probe") is False
            and provenance.get("executes_commands") is False,
            "view-surface report reads local files and does not execute network probes",
            evidence=["src/agilab/data_connector_view_surface.py"],
            details={"summary": summary, "provenance": provenance},
        ),
        _check_result(
            "data_connector_view_surface_persistence",
            "Data connector view surface persistence",
            proof["round_trip_ok"] and Path(proof["path"]).is_file(),
            "connector view-surface state is unchanged after JSON write/read",
            evidence=[proof["path"]],
            details={"path": proof["path"], "round_trip_ok": proof["round_trip_ok"]},
        ),
        _docs_check(repo_root),
    ]
    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "report": "Data connector view surface report",
        "status": "pass" if failed == 0 else "fail",
        "scope": (
            "Validates Release Decision connector-aware panels for state, "
            "health boundary, import/export provenance, and external artifact "
            "traceability without network probes."
        ),
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "schema": state.get("schema"),
            "run_status": state.get("run_status"),
            "execution_mode": state.get("execution_mode"),
            "view_surface_count": summary.get("view_surface_count"),
            "ready_view_surface_count": summary.get("ready_view_surface_count"),
            "missing_view_surface_count": summary.get("missing_view_surface_count"),
            "release_decision_surface_count": summary.get(
                "release_decision_surface_count"
            ),
            "page_source_loaded": summary.get("page_source_loaded"),
            "source_check_count": summary.get("source_check_count"),
            "source_check_passed_count": summary.get("source_check_passed_count"),
            "live_ui_run_status": summary.get("live_ui_run_status"),
            "connector_card_count": summary.get("connector_card_count"),
            "page_binding_count": summary.get("page_binding_count"),
            "health_probe_status_count": summary.get("health_probe_status_count"),
            "external_artifact_traceability_ready": summary.get(
                "external_artifact_traceability_ready"
            ),
            "import_export_provenance_ready": summary.get(
                "import_export_provenance_ready"
            ),
            "network_probe_count": summary.get("network_probe_count"),
            "command_execution_count": summary.get("command_execution_count"),
            "round_trip_ok": proof["round_trip_ok"],
            "settings_path": proof["settings_path"],
            "catalog_path": proof["catalog_path"],
            "release_decision_page": proof["release_decision_page"],
            "path": proof["path"],
        },
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit AGILAB data connector view-surface evidence."
    )
    parser.add_argument("--settings", type=Path, default=None)
    parser.add_argument("--catalog", type=Path, default=None)
    parser.add_argument("--release-decision-page", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--compact", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    report = build_report(
        settings_path=args.settings,
        catalog_path=args.catalog,
        release_decision_page=args.release_decision_page,
        output_path=args.output,
    )
    if args.compact:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
