#!/usr/bin/env python3
"""Emit AGILAB data connector live UI evidence."""

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

from agilab.data_connector_live_ui import SCHEMA, persist_data_connector_live_ui


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
        "data connector live UI report",
        "tools/data_connector_live_ui_report.py --compact",
        "streamlit_render_contract_only",
        "Release Decision",
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
        "data_connector_live_ui_docs_reference",
        "Data connector live UI docs reference",
        ok,
        (
            "features docs expose the data connector live UI command"
            if ok
            else "features docs do not expose the data connector live UI command"
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
        with tempfile.TemporaryDirectory(prefix="agilab-data-connector-live-ui-") as tmp_dir:
            return _build_report_with_path(
                repo_root=repo_root,
                settings_path=settings_path,
                catalog_path=catalog_path,
                release_decision_page=release_decision_page,
                output_path=Path(tmp_dir) / "data_connector_live_ui.json",
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
    proof = persist_data_connector_live_ui(
        repo_root=repo_root,
        output_path=output_path,
        settings_path=settings_path,
        catalog_path=catalog_path,
        release_decision_page=release_decision_page,
    )
    state = proof["state"]
    summary = state.get("summary", {})
    hook = state.get("release_decision_hook", {})
    render_payload = state.get("render_payload", {})
    render_summary = render_payload.get("summary", {})
    call_methods = summary.get("streamlit_call_methods", {})
    page_bindings = render_payload.get("page_bindings", [])
    health_probes = render_payload.get("health_probes", [])
    checks = [
        _check_result(
            "data_connector_live_ui_schema",
            "Data connector live UI schema",
            proof["ok"]
            and state.get("schema") == SCHEMA
            and state.get("run_status") == "ready_for_live_ui"
            and state.get("execution_mode") == "streamlit_render_contract_only",
            "connector live UI uses the supported render-contract schema",
            evidence=["src/agilab/data_connector_live_ui.py", proof["settings_path"]],
            details={
                "schema": state.get("schema"),
                "run_status": state.get("run_status"),
                "execution_mode": state.get("execution_mode"),
                "round_trip_ok": proof["round_trip_ok"],
                "issues": state.get("issues", []),
            },
        ),
        _check_result(
            "data_connector_live_ui_release_decision_hook",
            "Data connector live UI Release Decision hook",
            hook.get("loaded") is True
            and hook.get("imports_renderer") is True
            and hook.get("builds_preview") is True
            and hook.get("calls_renderer") is True
            and hook.get("stores_session_state") is True,
            "Release Decision page builds and renders the connector live UI payload",
            evidence=[proof["release_decision_page"]],
            details={"hook": hook},
        ),
        _check_result(
            "data_connector_live_ui_components",
            "Data connector live UI components",
            render_summary.get("connector_card_count") == 5
            and render_summary.get("page_binding_count") == 2
            and render_summary.get("legacy_fallback_count") == 2
            and call_methods.get("expander", 0) == 1
            and call_methods.get("metric", 0) == 4
            and call_methods.get("dataframe", 0) == 4,
            "renderer emits connector cards, page bindings, fallbacks, and probes",
            evidence=["src/agilab/data_connector_live_ui.py"],
            details={"summary": render_summary, "call_methods": call_methods},
        ),
        _check_result(
            "data_connector_live_ui_health_boundary",
            "Data connector live UI health boundary",
            render_summary.get("health_probe_status_count") == 5
            and render_summary.get("network_probe_count") == 0
            and render_summary.get("operator_opt_in_required_for_health") is True
            and {probe.get("status") for probe in health_probes} == {"unknown_not_probed"},
            "live UI keeps connector health behind operator opt-in",
            evidence=[proof["catalog_path"]],
            details={"summary": render_summary, "health_probes": health_probes},
        ),
        _check_result(
            "data_connector_live_ui_release_decision_provenance",
            "Data connector live UI Release Decision provenance",
            {row.get("page") for row in page_bindings} == {"release_decision"}
            and {row.get("ref_name") for row in page_bindings}
            == {"evidence_index", "artifact_store"},
            "live UI exposes Release Decision connector provenance bindings",
            evidence=[proof["settings_path"]],
            details={"page_bindings": page_bindings},
        ),
        _check_result(
            "data_connector_live_ui_no_network",
            "Data connector live UI no-network boundary",
            state.get("provenance", {}).get("executes_network_probe") is False
            and render_payload.get("provenance", {}).get("executes_network_probe") is False
            and summary.get("network_probe_count") == 0,
            "report and renderer do not execute connector network probes",
            evidence=["src/agilab/data_connector_live_ui.py"],
            details={
                "state_provenance": state.get("provenance", {}),
                "render_provenance": render_payload.get("provenance", {}),
            },
        ),
        _check_result(
            "data_connector_live_ui_persistence",
            "Data connector live UI persistence",
            proof["round_trip_ok"] and Path(proof["path"]).is_file(),
            "connector live UI state is unchanged after JSON write/read",
            evidence=[proof["path"]],
            details={"path": proof["path"], "round_trip_ok": proof["round_trip_ok"]},
        ),
        _docs_check(repo_root),
    ]
    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "report": "Data connector live UI report",
        "status": "pass" if failed == 0 else "fail",
        "scope": (
            "Wires connector state and connector-derived provenance into the "
            "Release Decision Streamlit surface without executing connector probes."
        ),
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "schema": state.get("schema"),
            "run_status": state.get("run_status"),
            "execution_mode": state.get("execution_mode"),
            "connector_card_count": summary.get("connector_card_count"),
            "page_binding_count": summary.get("page_binding_count"),
            "legacy_fallback_count": summary.get("legacy_fallback_count"),
            "health_probe_status_count": summary.get("health_probe_status_count"),
            "streamlit_metric_count": summary.get("streamlit_metric_count"),
            "streamlit_dataframe_count": summary.get("streamlit_dataframe_count"),
            "streamlit_call_count": summary.get("streamlit_call_count"),
            "network_probe_count": summary.get("network_probe_count"),
            "operator_opt_in_required_for_health": summary.get(
                "operator_opt_in_required_for_health"
            ),
            "release_decision_hooked": summary.get("release_decision_hooked"),
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
        description="Emit AGILAB data connector live UI evidence."
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
