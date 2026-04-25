#!/usr/bin/env python3
"""Emit operator UI component evidence for AGILAB global pipeline runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DAG_RELATIVE_PATH = Path("docs/source/data/multi_app_dag_sample.json")
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

from agilab.global_pipeline_operator_ui import (
    ACTION_HANDLER_COMMAND,
    DEFAULT_RUN_ID,
    PERSISTENCE_FORMAT,
    SCHEMA,
    persist_operator_ui,
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
    doc_path = repo_root / DOC_RELATIVE_PATH
    required = [
        "global DAG operator UI report",
        "tools/global_pipeline_operator_ui_report.py --compact",
        "operator UI components",
        "render persisted state and support operator actions",
    ]
    try:
        text = doc_path.read_text(encoding="utf-8")
        missing = [needle for needle in required if needle not in text]
        ok = not missing
        details = {"missing": missing}
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "global_pipeline_operator_ui_docs_reference",
        "Global pipeline operator UI docs reference",
        ok,
        (
            "features docs expose the global DAG operator UI command"
            if ok
            else "features docs do not expose the global DAG operator UI command"
        ),
        evidence=[str(DOC_RELATIVE_PATH)],
        details=details,
    )


def _load_failure_report(
    operator_actions_path: Path | None,
    dag_path: Path | None,
    exc: Exception,
) -> dict[str, Any]:
    evidence_path = operator_actions_path or dag_path or SAMPLE_DAG_RELATIVE_PATH
    check = _check_result(
        "global_pipeline_operator_ui_load",
        "Global pipeline operator UI load",
        False,
        "global pipeline operator UI could not be persisted",
        evidence=[str(evidence_path)],
        details={"error": str(exc)},
    )
    return {
        "report": "Global pipeline operator UI report",
        "status": "fail",
        "scope": (
            "Reads persisted operator action outcomes and renders reusable "
            "operator UI components plus a static HTML proof."
        ),
        "dag_path": str(dag_path or SAMPLE_DAG_RELATIVE_PATH),
        "summary": {
            "passed": 0,
            "failed": 1,
            "total": 1,
            "issues": [{"level": "error", "location": "load", "message": str(exc)}],
        },
        "operator_ui": {},
        "checks": [check],
    }


def _build_proof(
    *,
    repo_root: Path,
    output_path: Path,
    html_output_path: Path | None,
    operator_actions_path: Path | None,
    workspace_path: Path | None,
    dag_path: Path | None,
):
    return persist_operator_ui(
        repo_root=repo_root,
        output_path=output_path,
        html_output_path=html_output_path,
        operator_actions_path=operator_actions_path,
        workspace_path=workspace_path,
        dag_path=dag_path,
    )


def build_report(
    *,
    repo_root: Path = REPO_ROOT,
    dag_path: Path | None = None,
    operator_actions_path: Path | None = None,
    output_path: Path | None = None,
    html_output_path: Path | None = None,
    workspace_path: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    if output_path is None:
        with tempfile.TemporaryDirectory(prefix="agilab-operator-ui-") as tmp_dir:
            root = Path(tmp_dir)
            return _build_report_with_paths(
                repo_root=repo_root,
                dag_path=dag_path,
                operator_actions_path=operator_actions_path,
                output_path=root / "global_pipeline_operator_ui.json",
                html_output_path=html_output_path,
                workspace_path=workspace_path or (root / "workspace"),
            )
    return _build_report_with_paths(
        repo_root=repo_root,
        dag_path=dag_path,
        operator_actions_path=operator_actions_path,
        output_path=output_path,
        html_output_path=html_output_path,
        workspace_path=workspace_path
        or (output_path.parent / "global_pipeline_operator_ui_workspace"),
    )


def _component_ids(components: Sequence[dict[str, Any]]) -> list[str]:
    return [
        str(component.get("id", ""))
        for component in components
        if isinstance(component, dict)
    ]


def _build_report_with_paths(
    *,
    repo_root: Path,
    dag_path: Path | None,
    operator_actions_path: Path | None,
    output_path: Path,
    html_output_path: Path | None,
    workspace_path: Path | None,
) -> dict[str, Any]:
    try:
        proof = _build_proof(
            repo_root=repo_root,
            output_path=output_path,
            html_output_path=html_output_path,
            operator_actions_path=operator_actions_path,
            workspace_path=workspace_path,
            dag_path=dag_path,
        )
    except Exception as exc:
        return _load_failure_report(operator_actions_path, dag_path, exc)

    proof_details = proof.as_dict()
    state = proof.operator_ui
    summary = state.get("summary", {})
    source = state.get("source", {})
    rendering = state.get("rendering", {})
    components = state.get("components", [])
    iterable_components = components if isinstance(components, list) else []
    component_ids = _component_ids(iterable_components)
    action_controls = []
    artifact_rows = []
    unit_cards = []
    for component in iterable_components:
        if not isinstance(component, dict):
            continue
        if component.get("id") == "action_controls":
            action_controls = component.get("items", [])
        if component.get("id") == "artifact_table":
            artifact_rows = component.get("items", [])
        if component.get("id") == "unit_cards":
            unit_cards = component.get("items", [])
    html_text = Path(proof.html_path).read_text(encoding="utf-8")

    checks = [
        _check_result(
            "global_pipeline_operator_ui_schema",
            "Global pipeline operator UI schema",
            proof.ok
            and state.get("schema") == SCHEMA
            and state.get("persistence_format") == PERSISTENCE_FORMAT
            and state.get("run_id") == DEFAULT_RUN_ID
            and source.get("operator_actions_schema")
            == "agilab.global_pipeline_operator_actions.v1",
            "operator UI uses the supported schema and reads operator-actions JSON"
            if proof.ok
            else "operator UI schema or operator-actions source is invalid",
            evidence=[
                "src/agilab/global_pipeline_operator_ui.py",
                proof.operator_actions_path,
            ],
            details={
                "schema": state.get("schema"),
                "expected_schema": SCHEMA,
                "persistence_format": state.get("persistence_format"),
                "run_id": state.get("run_id"),
                "source": source,
                "issues": [issue.as_dict() for issue in proof.issues],
            },
        ),
        _check_result(
            "global_pipeline_operator_ui_components",
            "Global pipeline operator UI components",
            summary.get("component_count") == 6
            and summary.get("unit_card_count") == 2
            and summary.get("artifact_row_count") == 4
            and {
                "status_banner",
                "unit_cards",
                "dependency_graph",
                "update_timeline",
                "action_controls",
                "artifact_table",
            }.issubset(component_ids),
            "operator UI exposes status, unit, dependency, timeline, action, "
            "and artifact components",
            evidence=["src/agilab/global_pipeline_operator_ui.py"],
            details={"component_ids": component_ids, "unit_cards": unit_cards},
        ),
        _check_result(
            "global_pipeline_operator_ui_action_controls",
            "Global pipeline operator UI action controls",
            summary.get("action_control_count") == 2
            and summary.get("supported_action_ids")
            == ["queue_baseline:retry", "relay_followup:partial_rerun"]
            and all(
                control.get("handler_command") == ACTION_HANDLER_COMMAND
                and control.get("enabled") is True
                and control.get("execution_status") == "completed"
                for control in action_controls
                if isinstance(control, dict)
            ),
            "operator UI exposes supported retry and partial-rerun controls",
            evidence=["tools/global_pipeline_operator_actions_report.py"],
            details={"action_controls": action_controls},
        ),
        _check_result(
            "global_pipeline_operator_ui_html_render",
            "Global pipeline operator UI HTML render",
            Path(proof.html_path).is_file()
            and "queue_baseline" in html_text
            and "relay_followup" in html_text
            and "queue_baseline:retry" in html_text
            and "relay_followup:partial_rerun" in html_text
            and "queue_metrics_retry" in html_text,
            "operator UI renders persisted state and action controls to HTML",
            evidence=[proof.html_path],
            details={
                "html_path": proof.html_path,
                "html_exists": Path(proof.html_path).is_file(),
                "html_size": len(html_text),
            },
        ),
        _check_result(
            "global_pipeline_operator_ui_source_actions",
            "Global pipeline operator UI source actions",
            source.get("operator_actions_run_status") == "completed"
            and source.get("source_real_execution_scope") == "full_dag_smoke"
            and rendering.get("supports_operator_actions") is True
            and rendering.get("streamlit_page") is False,
            "operator UI keeps provenance to action outcomes and declares action support",
            evidence=["tools/global_pipeline_operator_actions_report.py"],
            details={
                "source": source,
                "rendering": rendering,
                "artifact_rows": artifact_rows,
            },
        ),
        _check_result(
            "global_pipeline_operator_ui_persistence",
            "Global pipeline operator UI JSON round trip",
            proof.round_trip_ok and Path(proof.path).is_file(),
            "operator UI model is unchanged after JSON write/read",
            evidence=[proof.path],
            details={
                "path": proof.path,
                "path_exists": Path(proof.path).is_file(),
                "round_trip_ok": proof.round_trip_ok,
            },
        ),
        _docs_check(repo_root),
    ]

    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "report": "Global pipeline operator UI report",
        "status": "pass" if failed == 0 else "fail",
        "scope": (
            "Reads persisted operator action outcomes and renders reusable "
            "operator UI components plus a static HTML proof. It is not yet "
            "wired as a Streamlit page."
        ),
        "dag_path": str(dag_path or SAMPLE_DAG_RELATIVE_PATH),
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "schema": state.get("schema"),
            "run_id": state.get("run_id"),
            "run_status": state.get("run_status"),
            "persistence_format": state.get("persistence_format"),
            "round_trip_ok": proof.round_trip_ok,
            "path": proof.path,
            "html_path": proof.html_path,
            "operator_actions_path": proof.operator_actions_path,
            "component_count": proof.component_count,
            "unit_card_count": proof.unit_card_count,
            "action_control_count": proof.action_control_count,
            "artifact_row_count": proof.artifact_row_count,
            "timeline_update_count": summary.get("timeline_update_count"),
            "supported_action_ids": summary.get("supported_action_ids"),
            "source_real_execution_scope": summary.get("source_real_execution_scope"),
            "issues": [issue.as_dict() for issue in proof.issues],
        },
        "operator_ui": proof_details,
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit operator UI component evidence for AGILAB global pipeline runs."
    )
    parser.add_argument(
        "--dag",
        type=Path,
        default=None,
        help=f"Path to a DAG JSON contract. Defaults to {SAMPLE_DAG_RELATIVE_PATH}.",
    )
    parser.add_argument(
        "--operator-actions",
        type=Path,
        default=None,
        help="Optional existing persisted operator-actions JSON to read.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path for the persisted operator-UI JSON proof.",
    )
    parser.add_argument(
        "--html-output",
        type=Path,
        default=None,
        help="Optional path for the rendered operator-UI HTML proof.",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Optional workspace root when generating upstream state.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact JSON without indentation.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    report = build_report(
        dag_path=args.dag,
        operator_actions_path=args.operator_actions,
        output_path=args.output,
        html_output_path=args.html_output,
        workspace_path=args.workspace,
    )
    if args.compact:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
