"""Human-readable run evidence for AGILAB executions."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

RUN_MARKDOWN_EVIDENCE_SCHEMA = "agilab.run_markdown_evidence.v1"
RUN_PLAN_FILE = "RUN_PLAN.md"
RUN_PROCESS_FILE = "RUN_PROCESS.md"
RUN_REPORT_FILE = "RUN_REPORT.md"
RUN_EVIDENCE_MANIFEST_FILE = "run_evidence_manifest.json"

_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b([A-Za-z0-9_-]*(?:api[_-]?key|key|token|secret|password|credential)[A-Za-z0-9_-]*)"
    r"(\s*[:=]\s*)([^\s,'\")]+)"
)


@dataclass(frozen=True)
class RunEvidencePaths:
    """Path contract for one app run evidence directory."""

    root: Path
    plan: Path
    process: Path
    report: Path
    manifest: Path

    def as_dict(self) -> dict[str, str]:
        return {
            "root": str(self.root),
            "plan": str(self.plan),
            "process": str(self.process),
            "report": str(self.report),
            "manifest": str(self.manifest),
        }


def utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_run_evidence_paths(root: Path | str) -> RunEvidencePaths:
    root_path = Path(root).expanduser()
    return RunEvidencePaths(
        root=root_path,
        plan=root_path / RUN_PLAN_FILE,
        process=root_path / RUN_PROCESS_FILE,
        report=root_path / RUN_REPORT_FILE,
        manifest=root_path / RUN_EVIDENCE_MANIFEST_FILE,
    )


def requires_execution_approval(*, cluster_enabled: bool = False, service_mode: bool = False) -> bool:
    """Return whether a run should require an explicit operator acknowledgement."""

    return bool(cluster_enabled or service_mode)


def approval_status(*, approval_required: bool, approved: bool) -> str:
    if not approval_required:
        return "not_required"
    return "approved" if approved else "pending"


def redact_potential_secrets(text: str) -> str:
    """Redact obvious inline secret assignments before writing review evidence."""

    return _SECRET_ASSIGNMENT_RE.sub(r"\1\2<redacted>", str(text))


def _md_value(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if value is None:
        return ""
    return str(value)


def _flat_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    if not metadata:
        return {}
    result: dict[str, Any] = {}
    for key, value in metadata.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            result[str(key)] = value
        else:
            result[str(key)] = json.loads(json.dumps(value, default=str))
    return result


def _safe_fenced(text: str) -> str:
    return redact_potential_secrets(text).replace("```", "'''")


def write_run_plan(
    paths: RunEvidencePaths,
    *,
    run_id: str,
    app: str,
    target: str,
    project_path: Path | str,
    command: str,
    execution_mode: str,
    cluster_enabled: bool,
    service_mode: bool,
    approval_required: bool,
    approval_status_value: str,
    created_at: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> Path:
    """Write the pre-execution run plan."""

    paths.root.mkdir(parents=True, exist_ok=True)
    rows = {
        "Schema": RUN_MARKDOWN_EVIDENCE_SCHEMA,
        "Run id": run_id,
        "App": app,
        "Target": target,
        "Project path": str(project_path),
        "Execution mode": execution_mode,
        "Cluster enabled": cluster_enabled,
        "Service mode": service_mode,
        "Approval required": approval_required,
        "Approval status": approval_status_value,
        "Created at": created_at or utc_now_text(),
    }
    metadata_rows = _flat_metadata(metadata)
    lines = [
        f"<!-- schema: {RUN_MARKDOWN_EVIDENCE_SCHEMA} -->",
        "# RUN_PLAN",
        "",
        "| Field | Value |",
        "| --- | --- |",
        *[f"| {key} | `{_md_value(value)}` |" for key, value in rows.items()],
    ]
    if metadata_rows:
        lines.extend(
            [
                "",
                "## Context",
                "",
                "| Key | Value |",
                "| --- | --- |",
                *[f"| {key} | `{_md_value(value)}` |" for key, value in sorted(metadata_rows.items())],
            ]
        )
    lines.extend(
        [
            "",
            "## Command",
            "",
            "```python",
            _safe_fenced(command),
            "```",
            "",
        ]
    )
    paths.plan.write_text("\n".join(lines), encoding="utf-8")
    return paths.plan


def append_run_process(
    paths: RunEvidencePaths,
    *,
    event: str,
    status: str,
    message: str,
    at: str | None = None,
) -> Path:
    """Append a process event to the run process journal."""

    paths.root.mkdir(parents=True, exist_ok=True)
    if not paths.process.exists():
        paths.process.write_text(
            "\n".join(
                [
                    f"<!-- schema: {RUN_MARKDOWN_EVIDENCE_SCHEMA} -->",
                    "# RUN_PROCESS",
                    "",
                    "| Time | Event | Status | Message |",
                    "| --- | --- | --- | --- |",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
    clean_message = " ".join(redact_potential_secrets(message).splitlines()).strip()
    with paths.process.open("a", encoding="utf-8") as handle:
        handle.write(f"| `{at or utc_now_text()}` | `{event}` | `{status}` | {clean_message} |\n")
    return paths.process


def file_artifact_info(path: Path | str, *, root: Path | str | None = None) -> dict[str, Any]:
    artifact_path = Path(path).expanduser()
    info: dict[str, Any] = {
        "path": str(artifact_path),
        "exists": artifact_path.is_file(),
    }
    if root is not None:
        try:
            info["relative_path"] = artifact_path.resolve().relative_to(Path(root).expanduser().resolve()).as_posix()
        except (OSError, RuntimeError, ValueError):
            info["relative_path"] = None
    if not artifact_path.is_file():
        return info
    data = artifact_path.read_bytes()
    info.update(
        {
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    )
    return info


def _artifact_lines(artifacts: Iterable[Path | str], *, root: Path | str | None = None) -> list[str]:
    rows = ["| Artifact | Exists | Size bytes | SHA-256 |", "| --- | --- | ---: | --- |"]
    for artifact in artifacts:
        info = file_artifact_info(artifact, root=root)
        rows.append(
            "| "
            f"`{info.get('relative_path') or info['path']}` | "
            f"`{_md_value(info.get('exists'))}` | "
            f"`{_md_value(info.get('size_bytes'))}` | "
            f"`{_md_value(info.get('sha256'))}` |"
        )
    return rows


def write_run_report(
    paths: RunEvidencePaths,
    *,
    run_id: str,
    status: str,
    started_at: str,
    ended_at: str,
    duration_seconds: float,
    log_path: Path | str | None = None,
    stderr: str = "",
    error: str = "",
    artifacts: Iterable[Path | str] = (),
    metadata: Mapping[str, Any] | None = None,
) -> Path:
    """Write the post-execution report."""

    paths.root.mkdir(parents=True, exist_ok=True)
    normalized_status = str(status or "unknown").lower()
    verdict = "PASS" if normalized_status in {"success", "passed", "done"} else "FAIL"
    artifact_paths = list(artifacts)
    if log_path is not None:
        artifact_paths.insert(0, Path(log_path))
    metadata_rows = _flat_metadata(metadata)
    lines = [
        f"<!-- schema: {RUN_MARKDOWN_EVIDENCE_SCHEMA} -->",
        "# RUN_REPORT",
        "",
        f"- Schema: `{RUN_MARKDOWN_EVIDENCE_SCHEMA}`",
        f"- Run id: `{run_id}`",
        f"- Verdict: `{verdict}`",
        f"- Status: `{normalized_status}`",
        f"- Started at: `{started_at}`",
        f"- Ended at: `{ended_at}`",
        f"- Duration seconds: `{duration_seconds:.3f}`",
    ]
    if metadata_rows:
        lines.extend(
            [
                "",
                "## Summary Context",
                "",
                "| Key | Value |",
                "| --- | --- |",
                *[f"| {key} | `{_md_value(value)}` |" for key, value in sorted(metadata_rows.items())],
            ]
        )
    if stderr.strip() or error.strip():
        lines.extend(
            [
                "",
                "## Failure Diagnostic",
                "",
                "```text",
                _safe_fenced("\n".join(part for part in (error, stderr) if part.strip())),
                "```",
            ]
        )
    lines.extend(["", "## Artifacts", "", *_artifact_lines(artifact_paths, root=paths.root), ""])
    paths.report.write_text("\n".join(lines), encoding="utf-8")
    return paths.report


def write_run_evidence_manifest(
    paths: RunEvidencePaths,
    *,
    run_id: str,
    status: str,
    context: Mapping[str, Any] | None = None,
) -> Path:
    """Write a machine-readable index for the Markdown evidence files."""

    paths.root.mkdir(parents=True, exist_ok=True)
    artifacts = [
        file_artifact_info(paths.plan, root=paths.root),
        file_artifact_info(paths.process, root=paths.root),
        file_artifact_info(paths.report, root=paths.root),
    ]
    payload = {
        "schema": RUN_MARKDOWN_EVIDENCE_SCHEMA,
        "run_id": run_id,
        "status": str(status),
        "created_at": utc_now_text(),
        "evidence_root": str(paths.root),
        "artifacts": artifacts,
        "context": _flat_metadata(context),
    }
    paths.manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return paths.manifest
