"""Classify common runtime failures before showing raw logs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RuntimeFailureDiagnostic:
    """User-facing classification for an install/run/import failure."""

    category: str
    title: str
    detail: str
    next_action: str


def _coerce_text(payload: Any) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, (list, tuple)):
        return "\n".join(str(item) for item in payload)
    return str(payload)


def _archive_display_name(text: str) -> str:
    for pattern in (
        r"Failed to extract ['\"]([^'\"]+\.7z)['\"]",
        r"dataset archive:\s*([^\s]+\.7z)",
        r"archive ['\"]([^'\"]+\.7z)['\"]",
        r"([^\s'\"]+\.7z)",
    ):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return Path(match.group(1)).name
    return "dataset.7z"


def _missing_module_name(text: str) -> str | None:
    match = re.search(r"No module named ['\"]([^'\"]+)['\"]", text)
    if match:
        return match.group(1)
    match = re.search(r"ModuleNotFoundError:\s*([^:\n]+)", text)
    if match:
        return match.group(1).strip().strip("'\"")
    return None


def classify_runtime_failure(payload: Any, *, phase: str = "runtime") -> RuntimeFailureDiagnostic | None:
    """Return a concise diagnostic for common AGILAB runtime failure classes."""

    text = _coerce_text(payload)
    normalized = text.lower()
    phase_label = str(phase or "runtime").strip().lower()

    if not normalized.strip():
        return None

    if ".7z" in normalized and (
        "not a 7z file" in normalized
        or "bad7zfile" in normalized
        or "archiveerror" in normalized
        or "failed to extract" in normalized
    ):
        archive_name = _archive_display_name(text)
        return RuntimeFailureDiagnostic(
            category="archive",
            title="Dataset archive is invalid.",
            detail=(
                f"{archive_name} could not be extracted. The archive is missing, truncated, "
                "or not a valid .7z dataset archive."
            ),
            next_action=(
                "Restore or regenerate the app dataset archive, then rerun INSTALL. "
                "For a notebook-derived project, recreate it from the packaged notebook if needed."
            ),
        )

    if "cluster mode requires agi_cluster_share" in normalized or (
        "cluster-share" in normalized and ("missing" in normalized or "not mounted" in normalized)
    ):
        return RuntimeFailureDiagnostic(
            category="cluster-share",
            title="Cluster share is not ready.",
            detail="Cluster mode requires an explicit writable AGI_CLUSTER_SHARE that is distinct from local share.",
            next_action="Configure or mount the cluster share, run the share diagnostic, then rerun the action.",
        )

    missing_module = _missing_module_name(text)
    if missing_module:
        return RuntimeFailureDiagnostic(
            category="dependency",
            title="Dependency is missing.",
            detail=f"The runtime could not import `{missing_module}` in the selected environment.",
            next_action="Rerun INSTALL for this project and verify the dependency is declared in the manager or worker pyproject.",
        )

    if "no virtual environment found" in normalized or (
        "installation is incomplete" in normalized and ".venv" in normalized
    ):
        return RuntimeFailureDiagnostic(
            category="project-state",
            title="Project environment is incomplete.",
            detail="The selected project or worker environment is missing its virtual environment.",
            next_action="Run INSTALL for the selected project before EXECUTE.",
        )

    if "worker copy" in normalized or (
        "wenv" in normalized and ("pyproject.toml" in normalized or "unsatisfiable" in normalized)
    ):
        return RuntimeFailureDiagnostic(
            category="worker-copy",
            title="Worker environment copy is inconsistent.",
            detail="The copied worker environment appears stale or has dependency metadata that no longer matches the source app.",
            next_action="Remove the stale worker environment for this app, rerun INSTALL, then retry the action.",
        )

    if (
        "failed to connect" in normalized
        or "connection refused" in normalized
        or "no route to host" in normalized
        or "scheduler host" in normalized
        or ("scheduler" in normalized and "timed out" in normalized)
    ):
        return RuntimeFailureDiagnostic(
            category="scheduler",
            title="Scheduler is unreachable.",
            detail=f"The {phase_label} action could not reach the configured scheduler or worker endpoint.",
            next_action="Check scheduler/workers hostnames, SSH access, ports, and cluster diagnostics, then retry.",
        )

    if "does not exist" in normalized and ("path" in normalized or "archive" in normalized or "project" in normalized):
        return RuntimeFailureDiagnostic(
            category="path",
            title="Required path is missing.",
            detail="A project, archive, or data path referenced by this action does not exist.",
            next_action="Check the selected project/archive path and rerun the action after restoring the missing file or directory.",
        )

    return None
