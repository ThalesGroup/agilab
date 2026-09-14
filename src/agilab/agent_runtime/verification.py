"""Read-only agent-run loading, summaries and integrity verification.

This module never imports the execution/CLI owner. The public agent_run facade
retains compatibility and forwards its trace-reader validation seams.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from agilab.agent_runtime.agent_trace import (
    AgentTraceEvent,
    load_trace_events,
    validate_event_sequence,
)

TRACE_KIND = "agilab.agent_run.v1"
MANIFEST_FILENAME = "agent_run_manifest.json"


@dataclass(frozen=True)
class AgentRunSummary:
    """Compact read-side view of an agent-run manifest."""

    run_id: str
    agent: str
    label: str
    status: str
    returncode: int | None
    manifest_path: Path
    stdout_path: Path | None
    stderr_path: Path | None
    trace_events_path: Path | None
    duration_seconds: float
    tags: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)


def load_agent_run_manifest(path: Path | str) -> dict[str, object]:
    """Load an agent-run manifest from a manifest file or run directory."""

    candidate = Path(path).expanduser()
    manifest_path = candidate / MANIFEST_FILENAME if candidate.is_dir() else candidate
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Agent run manifest must be a JSON object: {manifest_path}")
    if payload.get("kind") != TRACE_KIND:
        raise ValueError(
            f"Unsupported agent run manifest kind in {manifest_path}: {payload.get('kind')!r}"
        )
    return payload


def _path_from_artifact(value: object) -> Path | None:
    if isinstance(value, str) and value:
        return Path(value)
    if isinstance(value, dict):
        raw_path = value.get("path")
        if isinstance(raw_path, str) and raw_path:
            return Path(raw_path)
    return None


def summarize_agent_run(
    manifest_or_path: dict[str, object] | Path | str,
) -> AgentRunSummary:
    """Return a compact, typed summary for an agent-run manifest."""

    if isinstance(manifest_or_path, dict):
        manifest = manifest_or_path
    else:
        manifest = load_agent_run_manifest(manifest_or_path)

    artifacts = manifest.get("artifacts", {})
    artifact_map = artifacts if isinstance(artifacts, dict) else {}
    context = manifest.get("context", {})
    context_map = context if isinstance(context, dict) else {}
    timing = manifest.get("timing", {})
    timing_map = timing if isinstance(timing, dict) else {}
    raw_tags = context_map.get("tags", [])
    raw_metadata = context_map.get("metadata", {})

    manifest_path = _path_from_artifact(artifact_map.get("manifest")) or Path("")
    trace_payload = artifact_map.get("agent_trace")
    trace_events_path = None
    if isinstance(trace_payload, dict):
        raw_events_path = trace_payload.get("events")
        if isinstance(raw_events_path, str) and raw_events_path:
            trace_events_path = Path(raw_events_path)
    return AgentRunSummary(
        run_id=str(manifest.get("run_id") or ""),
        agent=str(manifest.get("agent") or ""),
        label=str(manifest.get("label") or ""),
        status=str(manifest.get("status") or ""),
        returncode=manifest.get("returncode")
        if isinstance(manifest.get("returncode"), int)
        else None,
        manifest_path=manifest_path,
        stdout_path=_path_from_artifact(artifact_map.get("stdout")),
        stderr_path=_path_from_artifact(artifact_map.get("stderr")),
        trace_events_path=trace_events_path,
        duration_seconds=float(timing_map.get("duration_seconds") or 0.0),
        tags=tuple(str(tag) for tag in raw_tags) if isinstance(raw_tags, list) else (),
        metadata=dict(raw_metadata) if isinstance(raw_metadata, dict) else {},
    )


def _summary_payload(summary: AgentRunSummary) -> dict[str, object]:
    return {
        "run_id": summary.run_id,
        "agent": summary.agent,
        "label": summary.label,
        "status": summary.status,
        "returncode": summary.returncode,
        "manifest": str(summary.manifest_path),
        "stdout": str(summary.stdout_path) if summary.stdout_path else None,
        "stderr": str(summary.stderr_path) if summary.stderr_path else None,
        "trace_events": str(summary.trace_events_path)
        if summary.trace_events_path
        else None,
        "duration_seconds": summary.duration_seconds,
        "tags": list(summary.tags),
        "metadata": summary.metadata,
    }


def validate_agent_run(
    manifest_or_path: dict[str, object] | Path | str,
    *,
    trace_loader: Callable[[Path | str], list[AgentTraceEvent]] = load_trace_events,
    sequence_validator: Callable[
        [Sequence[AgentTraceEvent]], list[str]
    ] = validate_event_sequence,
) -> dict[str, object]:
    """Validate one agent-run manifest enough for safe read-side reuse."""

    if isinstance(manifest_or_path, dict):
        manifest = manifest_or_path
    else:
        manifest = load_agent_run_manifest(manifest_or_path)
    summary = summarize_agent_run(manifest)
    issues: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    integrity: dict[str, str] = {}

    def fail(code: str, message: str) -> None:
        issues.append({"code": code, "message": message})

    def warn(code: str, message: str) -> None:
        warnings.append({"code": code, "message": message})

    if manifest.get("kind") != TRACE_KIND:
        fail("kind", f"unsupported manifest kind: {manifest.get('kind')!r}")
    if summary.status not in {"planned", "pass", "fail", "timeout", "denied"}:
        fail("status", f"unsupported status: {summary.status!r}")
    if summary.status != "planned":
        returncode = manifest.get("returncode")
        if type(returncode) is not int:
            fail("returncode", "terminal agent runs require an integer returncode")
        elif (summary.status == "pass") != (returncode == 0):
            fail(
                "status_returncode",
                "terminal status contradicts the recorded returncode",
            )
        elif summary.status == "timeout" and returncode != 124:
            fail("status_returncode", "timeout status requires returncode 124")
    termination = manifest.get("termination")
    terminal_trace_unavailable = False
    if termination is not None:
        if not isinstance(termination, dict):
            fail("termination", "agent run termination evidence must be an object")
        else:
            if termination.get("schema") != "agilab.agent_run.termination.v1":
                fail(
                    "termination_schema",
                    "agent run termination evidence schema is invalid",
                )
            termination_reason = str(termination.get("reason") or "")
            valid_termination_reasons = {
                "execution_infrastructure_error",
                "operator_cancelled",
                "system_exit",
            }
            if termination_reason not in valid_termination_reasons:
                fail("termination_reason", "agent run termination reason is invalid")
            if termination_reason == "system_exit":
                expected_status = "pass" if summary.returncode == 0 else "fail"
                if summary.returncode is None:
                    fail(
                        "termination_returncode",
                        "system exit termination requires a returncode",
                    )
                elif summary.status != expected_status:
                    fail(
                        "termination_status",
                        "system exit termination status must match its returncode",
                    )
                if termination.get("error_type") != "SystemExit":
                    fail(
                        "termination_error_type",
                        "system exit termination must name SystemExit",
                    )
            elif termination_reason == "operator_cancelled":
                if summary.status != "fail" or summary.returncode != 130:
                    fail(
                        "termination_status",
                        "operator cancellation must have fail status and returncode 130",
                    )
                if termination.get("error_type") != "KeyboardInterrupt":
                    fail(
                        "termination_error_type",
                        "operator cancellation must name KeyboardInterrupt",
                    )
            else:
                if summary.status != "fail":
                    fail(
                        "termination_status",
                        "execution infrastructure termination must have fail status",
                    )
                if summary.returncode is None or summary.returncode == 0:
                    fail(
                        "termination_returncode",
                        "execution infrastructure termination requires a non-zero returncode",
                    )
            if not str(termination.get("phase") or ""):
                fail(
                    "termination_phase",
                    "execution infrastructure termination phase is missing",
                )
            if not str(termination.get("error_type") or ""):
                fail(
                    "termination_error_type",
                    "execution infrastructure error type is missing",
                )
            if not isinstance(termination.get("trace_recorded"), bool):
                fail(
                    "termination_trace_state",
                    "execution infrastructure trace state must be boolean",
                )
            if termination.get("trace_recorded") is False:
                terminal_trace_unavailable = (
                    termination.get("schema") == "agilab.agent_run.termination.v1"
                    and termination_reason in valid_termination_reasons
                )
                warn(
                    "termination_trace",
                    "terminal trace evidence could not be recorded; manifest evidence is authoritative",
                )
    if summary.manifest_path and not summary.manifest_path.exists():
        fail(
            "manifest_path",
            f"manifest artifact path is missing: {summary.manifest_path}",
        )
    if summary.status != "planned":
        if not summary.stdout_path:
            fail("stdout_path", "stdout artifact path is missing from manifest")
        elif not summary.stdout_path.exists():
            fail(
                "stdout_exists",
                f"stdout artifact does not exist: {summary.stdout_path}",
            )
        if not summary.stderr_path:
            fail("stderr_path", "stderr artifact path is missing from manifest")
        elif not summary.stderr_path.exists():
            fail(
                "stderr_exists",
                f"stderr artifact does not exist: {summary.stderr_path}",
            )
        artifacts = manifest.get("artifacts", {})
        artifact_map = artifacts if isinstance(artifacts, dict) else {}
        for name in (
            "stdout",
            "stderr",
            *(["claim"] if "claim" in artifact_map else []),
        ):
            descriptor = artifact_map.get(name)
            descriptor = descriptor if isinstance(descriptor, dict) else {}
            path = _path_from_artifact(artifact_map.get(name))
            integrity[name] = "unverified"
            if not path or not path.is_file():
                integrity[name] = "failed"
                if path and path.exists():
                    fail(f"{name}_file", f"{name} artifact must be a regular file")
                continue
            expected_hash = descriptor.get("sha256")
            expected_size = descriptor.get("size_bytes")
            if expected_hash is None or expected_size is None:
                warn(
                    f"{name}_integrity",
                    f"{name} lacks a recorded hash or size; content integrity is unverified",
                )
            if expected_hash is not None and (
                not isinstance(expected_hash, str)
                or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None
            ):
                fail(f"{name}_sha256", f"{name} recorded sha256 is invalid")
                integrity[name] = "failed"
                continue
            if expected_size is not None and (
                type(expected_size) is not int or expected_size < 0
            ):
                fail(f"{name}_size", f"{name} recorded size_bytes is invalid")
                integrity[name] = "failed"
                continue
            try:
                with path.open("rb") as stream:
                    size = os.fstat(stream.fileno()).st_size
                    actual_hash = hashlib.file_digest(stream, "sha256").hexdigest()
            except OSError:
                fail(
                    f"{name}_read",
                    f"{name} artifact cannot be read for integrity verification",
                )
                integrity[name] = "failed"
                continue
            if expected_hash is not None and actual_hash != expected_hash:
                fail(f"{name}_sha256", f"{name} bytes do not match the recorded sha256")
                integrity[name] = "failed"
            if expected_size is not None and size != expected_size:
                fail(
                    f"{name}_size", f"{name} bytes do not match the recorded size_bytes"
                )
                integrity[name] = "failed"
            if (
                integrity[name] != "failed"
                and expected_hash is not None
                and expected_size is not None
            ):
                integrity[name] = "verified"
        # The ownership claim was added without changing TRACE_KIND, so valid
        # v1 manifests written before the claim existed remain readable. Once a
        # manifest declares a claim, however, fail closed on every claim error.
        if "claim" in artifact_map:
            claim_path = _path_from_artifact(artifact_map.get("claim"))
            if not claim_path:
                fail("claim_path", "agent run ownership claim path is invalid")
            elif not claim_path.exists():
                fail(
                    "claim_exists",
                    f"agent run ownership claim does not exist: {claim_path}",
                )
            else:
                try:
                    claim_payload = json.loads(claim_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    fail(
                        "claim_payload",
                        f"agent run ownership claim is invalid: {claim_path}",
                    )
                else:
                    if (
                        not isinstance(claim_payload, dict)
                        or claim_payload.get("schema") != "agilab.agent_run.claim.v1"
                    ):
                        fail(
                            "claim_schema",
                            f"agent run ownership claim schema is invalid: {claim_path}",
                        )
                    elif str(claim_payload.get("run_id") or "") != summary.run_id:
                        fail(
                            "claim_run_id",
                            f"agent run ownership claim does not match run_id: {claim_path}",
                        )

    command = manifest.get("command", {})
    command_map = command if isinstance(command, dict) else {}
    if command_map.get("argv_redacted") is False:
        warn(
            "argv_redaction",
            "command arguments are stored in full; confirm they contain no prompt secrets",
        )
    if not command_map.get("argv_sha256"):
        fail("argv_sha256", "command argv hash is missing")

    if summary.trace_events_path:
        if summary.trace_events_path.exists():
            try:
                trace_events = trace_loader(summary.trace_events_path)
            except (OSError, TypeError, ValueError) as exc:
                if not terminal_trace_unavailable:
                    fail("trace_events_invalid", str(exc))
            else:
                if not terminal_trace_unavailable:
                    for issue in sequence_validator(trace_events):
                        fail("trace_sequence", issue)
                    if any(event.run_id != summary.run_id for event in trace_events):
                        fail(
                            "trace_run_id",
                            "trace events do not match the manifest run_id",
                        )
                    if summary.status != "planned":
                        terminal = trace_events[-1] if trace_events else None
                        if terminal is None or terminal.event != "session_end":
                            fail(
                                "trace_terminal",
                                "terminal agent run lacks a final session_end event",
                            )
                        elif terminal.status != summary.status:
                            fail(
                                "trace_terminal",
                                "terminal trace status contradicts the manifest",
                            )
                        for event in trace_events:
                            if event.event in {"command_done", "session_end"}:
                                recorded_code = event.metadata.get("returncode")
                                if recorded_code is not None and (
                                    type(recorded_code) is not int
                                    or event.status
                                    not in {"pass", "fail", "timeout", "denied"}
                                    or (event.status == "pass") != (recorded_code == 0)
                                    or (
                                        event.status == "timeout"
                                        and recorded_code != 124
                                    )
                                ):
                                    fail(
                                        "trace_outcome",
                                        "trace event status contradicts its own returncode",
                                    )
                                # Publication can fail after command completion.
                                # In that case only the final session_end describes
                                # the runner's termination; earlier events retain
                                # the command's distinct outcome.
                                if termination is not None and event is not terminal:
                                    continue
                                if recorded_code is not None and (
                                    type(recorded_code) is not int
                                    or recorded_code != summary.returncode
                                ):
                                    fail(
                                        "trace_returncode",
                                        "terminal trace returncode contradicts the manifest",
                                    )
        elif not terminal_trace_unavailable:
            fail(
                "trace_events_exists",
                f"trace events file does not exist: {summary.trace_events_path}",
            )
    else:
        warn("trace_events_path", "trace events path is missing from manifest")

    return {
        "schema": "agilab.agent_run_validation.v1",
        "run": _summary_payload(summary),
        "ok": not issues,
        "issue_count": len(issues),
        "warning_count": len(warnings),
        "issues": issues,
        "warnings": warnings,
        "content_integrity": {
            "status": (
                "not_applicable"
                if summary.status == "planned"
                else "failed"
                if "failed" in integrity.values()
                else "unverified"
                if "unverified" in integrity.values()
                else "verified"
            ),
            "artifacts": integrity,
            "scope": "Recorded stdout, stderr and ownership-claim hashes and sizes; no producer authenticity or task-quality claim.",
        },
        "artifact_policy": "Validation checks terminal consistency, artifact presence and recorded content hashes; stdout/stderr contents are not embedded.",
    }


def render_validation_markdown(payload: dict[str, object]) -> str:
    """Render agent-run validation as compact Markdown."""

    run = payload.get("run", {})
    run_map = run if isinstance(run, dict) else {}
    issues = payload.get("issues", [])
    warnings = payload.get("warnings", [])
    issue_list = issues if isinstance(issues, list) else []
    warning_list = warnings if isinstance(warnings, list) else []
    lines = [
        "# AGILAB agent-run validation",
        "",
        f"- run_id: {run_map.get('run_id', '')}",
        f"- status: {run_map.get('status', '')}",
        f"- ok: {payload.get('ok', False)}",
        f"- issue_count: {payload.get('issue_count', 0)}",
        f"- warning_count: {payload.get('warning_count', 0)}",
    ]
    if issue_list:
        lines.extend(["", "## Issues", ""])
        for issue in issue_list:
            if isinstance(issue, dict):
                lines.append(f"- {issue.get('code', '')}: {issue.get('message', '')}")
    if warning_list:
        lines.extend(["", "## Warnings", ""])
        for warning in warning_list:
            if isinstance(warning, dict):
                lines.append(
                    f"- {warning.get('code', '')}: {warning.get('message', '')}"
                )
    return "\n".join(lines)
