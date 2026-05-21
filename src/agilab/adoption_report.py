"""Summarize first-adoption evidence from AGILAB run manifests."""

from __future__ import annotations

import argparse
import json
import os
import shlex
from pathlib import Path
from typing import Any, Mapping, Sequence

from agilab import run_manifest


SCHEMA_VERSION = 1
REPORT_KIND = "agilab.adoption_report"
FIRST_PROOF_PATH_ID = "source-checkout-first-proof"
FIRST_PROOF_PROJECT = "flight_telemetry_project"
FIRST_PROOF_REQUIRED_VALIDATIONS = (
    "proof_steps",
    "target_seconds",
    "recommended_project",
)
TROUBLESHOOTING_URL = "https://thalesgroup.github.io/agilab/newcomer-troubleshooting.html"
QUICK_START_URL = "https://thalesgroup.github.io/agilab/quick-start.html"


def _log_root() -> Path:
    return Path(os.environ.get("AGILAB_LOG_ABS", str(Path.home() / "log"))).expanduser()


def default_manifest_candidates() -> tuple[Path, ...]:
    log_root = _log_root()
    return (
        log_root / "execute" / "flight_telemetry" / run_manifest.RUN_MANIFEST_FILENAME,
        log_root / "execute" / "flight_telemetry" / run_manifest.RUN_MANIFEST_FILENAME,
    )


def default_manifest_path() -> Path:
    for candidate in default_manifest_candidates():
        if candidate.exists():
            return candidate
    return default_manifest_candidates()[0]


def _path_payload(path: Path | None) -> str | None:
    if path is None:
        return None
    return str(path.expanduser())


def _command_for_path(command: Sequence[str | Path]) -> str:
    return " ".join(shlex.quote(str(part)) for part in command)


def compatibility_report_command(manifest_path: Path) -> str:
    return _command_for_path(
        (
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/compatibility_report.py",
            "--manifest",
            manifest_path.expanduser(),
            "--compact",
        )
    )


def security_check_command() -> str:
    return _command_for_path(
        (
            "agilab",
            "security-check",
            "--profile",
            "shared",
            "--json",
            "--strict",
        )
    )


def _status_label(loaded: bool, error: str | None) -> str:
    if loaded:
        return "present"
    if error == "missing":
        return "missing"
    return "invalid"


def _validation_rows(manifest: run_manifest.RunManifest | None) -> list[dict[str, Any]]:
    if manifest is None:
        return []

    rows = [
        {
            "label": validation.label,
            "status": validation.status,
            "summary": validation.summary,
            "required": validation.label in FIRST_PROOF_REQUIRED_VALIDATIONS,
        }
        for validation in manifest.validations
    ]
    recorded = {row["label"] for row in rows}
    rows.extend(
        {
            "label": label,
            "status": "missing",
            "summary": "Required first-proof validation was not recorded.",
            "required": True,
        }
        for label in FIRST_PROOF_REQUIRED_VALIDATIONS
        if label not in recorded
    )
    return rows


def _manifest_issues(manifest: run_manifest.RunManifest | None) -> list[str]:
    if manifest is None:
        return []

    issues: list[str] = []
    validation_statuses = {
        validation.label: validation.status
        for validation in manifest.validations
    }
    argv = tuple(manifest.command.argv)

    if manifest.path_id != FIRST_PROOF_PATH_ID:
        issues.append(f"path_id is {manifest.path_id!r}, expected {FIRST_PROOF_PATH_ID!r}")
    if manifest.status != "pass":
        issues.append(f"manifest status is {manifest.status!r}")
    if not run_manifest.manifest_passed(manifest):
        issues.append("one or more manifest validations did not pass")
    missing_or_failing = [
        f"{label}={validation_statuses.get(label, 'missing')}"
        for label in FIRST_PROOF_REQUIRED_VALIDATIONS
        if validation_statuses.get(label) != "pass"
    ]
    if missing_or_failing:
        issues.append("required validation issue(s): " + ", ".join(missing_or_failing))
    if manifest.environment.app_name != FIRST_PROOF_PROJECT:
        issues.append(
            f"active app is {manifest.environment.app_name!r}, expected {FIRST_PROOF_PROJECT!r}"
        )
    if "--dry-run" in argv:
        issues.append(
            "manifest came from --dry-run; run the real first-proof path before expanding"
        )
    target = manifest.timing.target_seconds
    if target is None:
        issues.append("target_seconds is missing")
    elif manifest.timing.duration_seconds > target:
        issues.append(
            f"duration {manifest.timing.duration_seconds:.2f}s exceeds target {target:.2f}s"
        )
    return issues


def _manifest_summary(
    manifest: run_manifest.RunManifest | None,
    manifest_error: str | None,
    manifest_issues: Sequence[str],
) -> dict[str, Any]:
    if manifest is None:
        status = "missing" if manifest_error == "missing" else "invalid"
        return {
            "loaded": False,
            "status": status,
            "run_id": None,
            "path_id": None,
            "app_name": None,
            "duration_seconds": None,
            "target_seconds": None,
            "validation_statuses": {},
            "issues": list(manifest_issues),
        }

    return {
        "loaded": True,
        "status": manifest.status,
        "run_id": manifest.run_id,
        "path_id": manifest.path_id,
        "app_name": manifest.environment.app_name,
        "duration_seconds": manifest.timing.duration_seconds,
        "target_seconds": manifest.timing.target_seconds,
        "validation_statuses": {
            validation.label: validation.status
            for validation in manifest.validations
        },
        "issues": list(manifest_issues),
    }


def _file_evidence(
    *,
    evidence_id: str,
    label: str,
    path: Path | None,
    summary: str,
    required: bool = False,
    recommended: bool = False,
    command: str | None = None,
) -> dict[str, Any]:
    if path is None:
        status = "not_checked"
    else:
        status = "present" if path.expanduser().exists() else "missing"
    return {
        "id": evidence_id,
        "label": label,
        "status": status,
        "path": _path_payload(path),
        "required": required,
        "recommended": recommended,
        "command": command,
        "summary": summary,
    }


def _default_notebook_export(
    manifest: run_manifest.RunManifest | None,
    project_dir: Path | None,
) -> Path | None:
    if project_dir is not None:
        return project_dir.expanduser() / "notebooks" / "lab_stages.ipynb"
    if manifest is None:
        return None
    active_app = Path(manifest.environment.active_app).expanduser()
    if not str(active_app):
        return None
    return active_app / "notebooks" / "lab_stages.ipynb"


def _next_actions(
    *,
    manifest_path: Path,
    first_proof_status: str,
    first_proof_issues: Sequence[str],
    notebook_status: str,
    compatibility_status: str,
    security_status: str,
) -> list[dict[str, str]]:
    first_proof_command = "agilab first-proof --json --with-ui"
    actions: list[dict[str, str]] = []

    if first_proof_status == "missing":
        actions.append(
            {
                "label": "Generate the first-proof manifest",
                "command": first_proof_command,
                "reason": "No first-proof run_manifest.json was found.",
            }
        )
        actions.append(
            {
                "label": "Use first-run troubleshooting if it fails",
                "command": TROUBLESHOOTING_URL,
                "reason": "Stay on the narrow flight-telemetry path before changing route.",
            }
        )
        return actions

    if first_proof_status in {"invalid", "failing"}:
        reason = (
            "; ".join(first_proof_issues)
            if first_proof_issues
            else "The manifest is not a passing first proof."
        )
        actions.append(
            {
                "label": "Rerun the first-proof path",
                "command": first_proof_command,
                "reason": reason,
            }
        )
        actions.append(
            {
                "label": "Open newcomer troubleshooting",
                "command": TROUBLESHOOTING_URL,
                "reason": (
                    "Fix the first proof before trying notebooks, private apps, "
                    "or cluster mode."
                ),
            }
        )
        return actions

    if compatibility_status != "present":
        actions.append(
            {
                "label": "Capture compatibility evidence",
                "command": compatibility_report_command(manifest_path),
                "reason": "Attach the manifest to the public compatibility report before handoff.",
            }
        )
    if security_status != "present":
        actions.append(
            {
                "label": "Capture shared-use security evidence",
                "command": security_check_command() + " > security-check.json",
                "reason": "Shared or team adoption needs a redacted security-check artifact.",
            }
        )
    if notebook_status == "missing":
        actions.append(
            {
                "label": "Export the workflow notebook",
                "command": "WORKFLOW -> Download pipeline notebook",
                "reason": (
                    "The notebook export is the no-lock-in handoff artifact "
                    "for a team trial."
                ),
            }
        )
    if not actions:
        actions.append(
            {
                "label": "Proceed to the next adoption lane",
                "command": QUICK_START_URL,
                "reason": "The first proof and handoff evidence are present.",
            }
        )
    return actions


def build_report(
    *,
    manifest_path: Path | None = None,
    project_dir: Path | None = None,
    notebook_export: Path | None = None,
    compatibility_report: Path | None = None,
    security_report: Path | None = None,
) -> dict[str, Any]:
    selected_manifest_path = (manifest_path or default_manifest_path()).expanduser()
    manifest, manifest_error = run_manifest.try_load_run_manifest(selected_manifest_path)
    if manifest_error == "missing":
        issues: list[str] = []
    elif manifest is None:
        issues = [f"manifest parse error: {manifest_error}"]
    else:
        issues = _manifest_issues(manifest)
    first_proof_status = (
        "passed"
        if manifest is not None and not issues
        else "missing"
        if manifest_error == "missing"
        else "invalid"
        if manifest is None
        else "failing"
    )
    ready_to_explore = first_proof_status == "passed"
    notebook_path = (
        notebook_export.expanduser()
        if notebook_export is not None
        else _default_notebook_export(manifest, project_dir)
    )

    manifest_evidence = {
        "id": "run_manifest",
        "label": "First-proof run manifest",
        "status": _status_label(manifest is not None, manifest_error),
        "path": _path_payload(selected_manifest_path),
        "required": True,
        "recommended": False,
        "command": None,
        "summary": (
            "Passing first-proof manifest found."
            if first_proof_status == "passed"
            else "Generate or fix the first-proof run_manifest.json."
        ),
    }
    notebook_evidence = _file_evidence(
        evidence_id="notebook_export",
        label="Workflow notebook export",
        path=notebook_path,
        required=False,
        recommended=True,
        command="WORKFLOW -> Download pipeline notebook",
        summary="No-lock-in artifact for controlled team handoff.",
    )
    compatibility_evidence = _file_evidence(
        evidence_id="compatibility_report",
        label="Compatibility report output",
        path=compatibility_report.expanduser() if compatibility_report is not None else None,
        required=False,
        recommended=True,
        command=compatibility_report_command(selected_manifest_path),
        summary="Machine-readable compatibility evidence for the manifest.",
    )
    security_evidence = _file_evidence(
        evidence_id="security_check",
        label="Shared security-check output",
        path=security_report.expanduser() if security_report is not None else None,
        required=False,
        recommended=True,
        command=security_check_command() + " > security-check.json",
        summary="Redacted shared-use hardening evidence.",
    )
    evidence = [
        manifest_evidence,
        notebook_evidence,
        compatibility_evidence,
        security_evidence,
    ]
    handoff_ids = {"run_manifest", "notebook_export", "compatibility_report", "security_check"}
    handoff_ready = ready_to_explore and all(
        item["status"] == "present"
        for item in evidence
        if item["id"] in handoff_ids
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": REPORT_KIND,
        "manifest_path": _path_payload(selected_manifest_path),
        "candidate_manifest_paths": [_path_payload(path) for path in default_manifest_candidates()],
        "summary": {
            "first_proof_status": first_proof_status,
            "safe_to_expand": ready_to_explore,
            "safe_to_expand_scope": "next_demo_or_notebook_lane" if ready_to_explore else "none",
            "team_trial_handoff_ready": handoff_ready,
        },
        "first_proof": _manifest_summary(manifest, manifest_error, issues),
        "validations": _validation_rows(manifest),
        "evidence": evidence,
        "next_actions": _next_actions(
            manifest_path=selected_manifest_path,
            first_proof_status=first_proof_status,
            first_proof_issues=issues,
            notebook_status=str(notebook_evidence["status"]),
            compatibility_status=str(compatibility_evidence["status"]),
            security_status=str(security_evidence["status"]),
        ),
        "links": [
            {"label": "Quick start", "url": QUICK_START_URL},
            {"label": "Newcomer troubleshooting", "url": TROUBLESHOOTING_URL},
            {
                "label": "Compatibility matrix",
                "url": "https://thalesgroup.github.io/agilab/compatibility-matrix.html",
            },
        ],
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    summary = dict(report.get("summary", {}))
    first_proof = dict(report.get("first_proof", {}))
    lines = [
        "# AGILAB Adoption Report",
        "",
        f"- Manifest: `{report.get('manifest_path')}`",
        f"- First-proof status: `{summary.get('first_proof_status')}`",
        f"- Safe to expand: `{'yes' if summary.get('safe_to_expand') else 'no'}`",
        "- Team-trial handoff ready: "
        f"`{'yes' if summary.get('team_trial_handoff_ready') else 'no'}`",
        f"- Run id: `{first_proof.get('run_id') or 'n/a'}`",
        "",
        "## Evidence",
        "",
        "| Item | Status | Path or command |",
        "|---|---|---|",
    ]
    for item in report.get("evidence", []):
        row = dict(item)
        path_or_command = row.get("path") or row.get("command") or ""
        lines.append(f"| {row.get('label')} | `{row.get('status')}` | `{path_or_command}` |")

    issues = list(first_proof.get("issues") or [])
    if issues:
        lines.extend(["", "## Blocking Issues", ""])
        lines.extend(f"- {issue}" for issue in issues)

    lines.extend(["", "## Next Actions", ""])
    for index, action in enumerate(report.get("next_actions", []), start=1):
        row = dict(action)
        lines.append(f"{index}. {row.get('label')}: `{row.get('command')}`")
        if row.get("reason"):
            lines.append(f"   Reason: {row.get('reason')}")

    lines.append("")
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize AGILAB first-adoption evidence from run_manifest.json."
    )
    parser.add_argument(
        "--manifest",
        default=None,
        help=(
            "Path to run_manifest.json. Defaults to "
            "~/log/execute/flight_telemetry/run_manifest.json."
        ),
    )
    parser.add_argument(
        "--project-dir",
        default=None,
        help="Project directory used to locate notebooks/lab_stages.ipynb for handoff evidence.",
    )
    parser.add_argument(
        "--notebook-export",
        default=None,
        help="Explicit path to the exported lab_stages.ipynb handoff artifact.",
    )
    parser.add_argument(
        "--compatibility-report",
        default=None,
        help="Optional path to a saved compatibility-report artifact.",
    )
    parser.add_argument(
        "--security-report",
        default=None,
        help="Optional path to a saved security-check JSON artifact.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of Markdown.")
    parser.add_argument("--output", default=None, help="Write the report to this file.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero unless the first-proof manifest is a passing baseline.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = build_report(
        manifest_path=Path(args.manifest).expanduser() if args.manifest else None,
        project_dir=Path(args.project_dir).expanduser() if args.project_dir else None,
        notebook_export=Path(args.notebook_export).expanduser() if args.notebook_export else None,
        compatibility_report=Path(args.compatibility_report).expanduser()
        if args.compatibility_report
        else None,
        security_report=Path(args.security_report).expanduser() if args.security_report else None,
    )
    rendered = (
        json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.json
        else render_markdown(report)
    )
    if args.output:
        output_path = Path(args.output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    if args.strict and not report["summary"]["safe_to_expand"]:
        return 1
    return 0
