"""Read-only manifest and artifact tools used by the AGILAB MCP bridge."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from agilab import bridge_cli, run_manifest
from agilab.secret_uri import redact_mapping


def list_projects(apps_root: str | Path) -> dict[str, Any]:
    root = Path(apps_root).expanduser().resolve(strict=False)
    projects = (
        [
            {"name": path.name, "path": str(path)}
            for path in sorted(root.iterdir())
            if path.is_dir() and path.name.endswith("_project")
        ]
        if root.is_dir()
        else []
    )
    return {
        "schema": "agilab.mcp.list_projects.v1",
        "apps_root": str(root),
        "projects": projects,
    }


def list_runs(log_root: str | Path) -> dict[str, Any]:
    root = Path(log_root).expanduser().resolve(strict=False)
    runs = (
        [
            {"path": str(path), "parent": str(path.parent)}
            for path in sorted(root.rglob(run_manifest.RUN_MANIFEST_FILENAME))
        ]
        if root.is_dir()
        else []
    )
    return {
        "schema": "agilab.mcp.list_runs.v1",
        "log_root": str(root),
        "runs": runs,
    }


def read_manifest(manifest_path: str | Path) -> dict[str, Any]:
    path = Path(manifest_path).expanduser().resolve(strict=False)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"Manifest must be a JSON object: {path}")
    return {
        "schema": "agilab.mcp.read_manifest.v1",
        "manifest_path": str(path),
        "manifest": redact_mapping(payload),
    }


def summarize_run(manifest_path: str | Path) -> dict[str, Any]:
    manifest, _, resolved = bridge_cli._load_run_manifest(Path(manifest_path))
    return {
        "schema": "agilab.mcp.summarize_run.v1",
        "manifest_path": str(resolved),
        "summary": run_manifest.manifest_summary(manifest),
    }


def list_artifacts(manifest_path: str | Path) -> dict[str, Any]:
    manifest, _, resolved = bridge_cli._load_run_manifest(Path(manifest_path))
    return {
        "schema": "agilab.mcp.list_artifacts.v1",
        "manifest_path": str(resolved),
        "artifacts": bridge_cli._artifact_rows(manifest, resolved),
    }


def compare_runs(
    left_manifest: str | Path, right_manifest: str | Path
) -> dict[str, Any]:
    left, _, left_path = bridge_cli._load_run_manifest(Path(left_manifest))
    right, _, right_path = bridge_cli._load_run_manifest(Path(right_manifest))
    left_summary = run_manifest.manifest_summary(left)
    right_summary = run_manifest.manifest_summary(right)
    return {
        "schema": "agilab.mcp.compare_runs.v1",
        "left_manifest": str(left_path),
        "right_manifest": str(right_path),
        "status_changed": left.status != right.status,
        "duration_delta_seconds": right.timing.duration_seconds
        - left.timing.duration_seconds,
        "artifact_count_delta": right_summary["artifact_count"]
        - left_summary["artifact_count"],
        "left": left_summary,
        "right": right_summary,
    }


def export_quarto_report(
    manifest_path: str | Path, output_path: str | Path
) -> dict[str, Any]:
    return bridge_cli.export_quarto_report(
        Path(manifest_path), Path(output_path), render=False
    )
