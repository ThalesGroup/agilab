#!/usr/bin/env python3
"""Emit AGILAB data connector UI preview evidence."""

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

from agilab.data_connector_ui_preview import (
    SCHEMA,
    persist_data_connector_ui_preview,
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
        "data connector UI preview report",
        "tools/data_connector_ui_preview_report.py --compact",
        "static_ui_preview_only",
        "connector state",
        "connector-derived provenance",
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
        "data_connector_ui_preview_docs_reference",
        "Data connector UI preview docs reference",
        ok,
        (
            "features docs expose the data connector UI preview command"
            if ok
            else "features docs do not expose the data connector UI preview command"
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
    html_output_path: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    if output_path is None or html_output_path is None:
        with tempfile.TemporaryDirectory(prefix="agilab-data-connector-ui-preview-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            return _build_report_with_paths(
                repo_root=repo_root,
                settings_path=settings_path,
                catalog_path=catalog_path,
                output_path=tmp_path / "data_connector_ui_preview.json",
                html_output_path=tmp_path / "data_connector_ui_preview.html",
            )
    return _build_report_with_paths(
        repo_root=repo_root,
        settings_path=settings_path,
        catalog_path=catalog_path,
        output_path=output_path,
        html_output_path=html_output_path,
    )


def _build_report_with_paths(
    *,
    repo_root: Path,
    settings_path: Path | None,
    catalog_path: Path | None,
    output_path: Path,
    html_output_path: Path,
) -> dict[str, Any]:
    proof = persist_data_connector_ui_preview(
        repo_root=repo_root,
        output_path=output_path,
        html_output_path=html_output_path,
        settings_path=settings_path,
        catalog_path=catalog_path,
    )
    state = proof["state"]
    summary = state.get("summary", {})
    connector_cards = state.get("connector_cards", [])
    page_bindings = state.get("page_bindings", [])
    legacy_fallbacks = state.get("legacy_fallbacks", [])
    html = str(state.get("html", ""))
    checks = [
        _check_result(
            "data_connector_ui_preview_schema",
            "Data connector UI preview schema",
            proof["ok"]
            and state.get("schema") == SCHEMA
            and state.get("run_status") == "ready_for_ui_preview"
            and state.get("execution_mode") == "static_ui_preview_only"
            and state.get("persistence_format") == "json+html",
            "connector UI preview uses the supported schema and persistence mode",
            evidence=["src/agilab/data_connector_ui_preview.py", proof["settings_path"]],
            details={
                "schema": state.get("schema"),
                "run_status": state.get("run_status"),
                "execution_mode": state.get("execution_mode"),
                "persistence_format": state.get("persistence_format"),
                "round_trip_ok": proof["round_trip_ok"],
                "issues": state.get("issues", []),
            },
        ),
        _check_result(
            "data_connector_ui_preview_connector_cards",
            "Data connector UI preview connector cards",
            summary.get("connector_card_count") == 5
            and {card.get("kind") for card in connector_cards}
            == {"sql", "opensearch", "object_storage"}
            and all(card.get("health_status") == "unknown_not_probed" for card in connector_cards),
            "preview renders one card per first-class connector",
            evidence=[proof["catalog_path"]],
            details={"connector_cards": connector_cards},
        ),
        _check_result(
            "data_connector_ui_preview_page_bindings",
            "Data connector UI preview page bindings",
            summary.get("page_binding_count") == 2
            and {row.get("source") for row in page_bindings} == {"page_connector_refs"}
            and {row.get("ref_name") for row in page_bindings}
            == {"evidence_index", "artifact_store"},
            "preview exposes page-specific connector references",
            evidence=[proof["settings_path"]],
            details={"page_bindings": page_bindings},
        ),
        _check_result(
            "data_connector_ui_preview_legacy_fallbacks",
            "Data connector UI preview legacy fallbacks",
            summary.get("legacy_fallback_count") == 2
            and {row.get("status") for row in legacy_fallbacks}
            == {"legacy_path_fallback"},
            "preview keeps legacy path fallbacks visible during migration",
            evidence=[proof["settings_path"]],
            details={"legacy_fallbacks": legacy_fallbacks},
        ),
        _check_result(
            "data_connector_ui_preview_health_boundary",
            "Data connector UI preview health boundary",
            summary.get("health_probe_status_count") == 5
            and summary.get("network_probe_count") == 0
            and state.get("provenance", {}).get("operator_opt_in_required_for_health") is True,
            "preview shows health boundary without executing network probes",
            evidence=[proof["catalog_path"]],
            details={"summary": summary, "provenance": state.get("provenance", {})},
        ),
        _check_result(
            "data_connector_ui_preview_html_render",
            "Data connector UI preview HTML render",
            proof["html_written"]
            and "<h1>Data Connector UI Preview</h1>" in html
            and "Legacy path fallbacks" in html,
            "preview writes a static HTML artifact",
            evidence=[proof["html_path"]],
            details={"html_path": proof["html_path"], "html_size": len(html)},
        ),
        _check_result(
            "data_connector_ui_preview_persistence",
            "Data connector UI preview persistence",
            proof["round_trip_ok"] and Path(proof["path"]).is_file(),
            "connector UI preview state is unchanged after JSON write/read",
            evidence=[proof["path"]],
            details={
                "path": proof["path"],
                "html_path": proof["html_path"],
                "round_trip_ok": proof["round_trip_ok"],
            },
        ),
        _docs_check(repo_root),
    ]
    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "report": "Data connector UI preview report",
        "status": "pass" if failed == 0 else "fail",
        "scope": (
            "Renders connector state and connector-derived provenance as a "
            "static JSON+HTML preview without executing connector probes."
        ),
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "schema": state.get("schema"),
            "run_status": state.get("run_status"),
            "execution_mode": state.get("execution_mode"),
            "persistence_format": state.get("persistence_format"),
            "connector_card_count": summary.get("connector_card_count"),
            "page_binding_count": summary.get("page_binding_count"),
            "legacy_fallback_count": summary.get("legacy_fallback_count"),
            "health_probe_status_count": summary.get("health_probe_status_count"),
            "component_count": summary.get("component_count"),
            "network_probe_count": summary.get("network_probe_count"),
            "html_rendered": summary.get("html_rendered"),
            "round_trip_ok": proof["round_trip_ok"],
            "html_written": proof["html_written"],
            "settings_path": proof["settings_path"],
            "catalog_path": proof["catalog_path"],
            "path": proof["path"],
            "html_path": proof["html_path"],
        },
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit AGILAB data connector UI preview evidence."
    )
    parser.add_argument("--settings", type=Path, default=None)
    parser.add_argument("--catalog", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--html-output", type=Path, default=None)
    parser.add_argument("--compact", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    report = build_report(
        settings_path=args.settings,
        catalog_path=args.catalog,
        output_path=args.output,
        html_output_path=args.html_output,
    )
    if args.compact:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
