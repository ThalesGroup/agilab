# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Revision traceability evidence for AGILAB core packages and built-in apps."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tomllib
from typing import Any, Mapping


SCHEMA = "agilab.revision_traceability.v1"
CREATED_AT = "2026-04-25T00:00:34Z"
UPDATED_AT = "2026-04-25T00:00:34Z"
BUILTIN_APPS_RELATIVE_PATH = Path("src/agilab/apps/builtin")
CORE_COMPONENT_FILES = {
    "agilab": Path("pyproject.toml"),
    "agi-core": Path("src/agilab/core/agi-core/pyproject.toml"),
    "agi-env": Path("src/agilab/core/agi-env/pyproject.toml"),
    "agi-cluster": Path("src/agilab/core/agi-cluster/pyproject.toml"),
    "agi-node": Path("src/agilab/core/agi-node/pyproject.toml"),
}
APP_TRACE_FILES = (
    Path("pyproject.toml"),
    Path("src/app_settings.toml"),
    Path("pipeline_view.dot"),
    Path("lab_steps.toml"),
    Path("notebook_export.toml"),
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _combined_digest(rows: list[Mapping[str, Any]]) -> str:
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(payload)


def _relative(repo_root: Path, path: Path) -> str:
    return path.relative_to(repo_root).as_posix()


def _read_pyproject_version(path: Path) -> str:
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
        project = payload.get("project", {})
        if isinstance(project, dict):
            return str(project.get("version", "") or "")
    except Exception:
        return ""
    return ""


def _read_git_head(repo_root: Path) -> dict[str, str]:
    git_dir = repo_root / ".git"
    if git_dir.is_file():
        text = git_dir.read_text(encoding="utf-8").strip()
        prefix = "gitdir:"
        if text.startswith(prefix):
            git_dir = (repo_root / text.removeprefix(prefix).strip()).resolve()
    head_path = git_dir / "HEAD"
    if not head_path.is_file():
        return {"status": "unavailable", "head": "", "ref": "", "commit": ""}
    head = head_path.read_text(encoding="utf-8").strip()
    if head.startswith("ref:"):
        ref = head.removeprefix("ref:").strip()
        ref_path = git_dir / ref
        commit = ref_path.read_text(encoding="utf-8").strip() if ref_path.is_file() else ""
        if not commit:
            packed_refs = git_dir / "packed-refs"
            if packed_refs.is_file():
                for line in packed_refs.read_text(encoding="utf-8").splitlines():
                    if line.startswith("#") or not line.strip():
                        continue
                    parts = line.split(" ", 1)
                    if len(parts) == 2 and parts[1].strip() == ref:
                        commit = parts[0]
                        break
        return {
            "status": "available" if commit else "unresolved_ref",
            "head": head,
            "ref": ref,
            "commit": commit,
        }
    return {
        "status": "available" if head else "unavailable",
        "head": head,
        "ref": "",
        "commit": head,
    }


def _core_component_row(repo_root: Path, name: str, relative_path: Path) -> dict[str, Any]:
    path = repo_root / relative_path
    exists = path.is_file()
    return {
        "name": name,
        "path": relative_path.as_posix(),
        "exists": exists,
        "version": _read_pyproject_version(path) if exists else "",
        "sha256": _file_sha256(path) if exists else "",
    }


def _app_trace_row(repo_root: Path, app_dir: Path) -> dict[str, Any]:
    files = []
    for relative_path in APP_TRACE_FILES:
        path = app_dir / relative_path
        if path.is_file():
            files.append(
                {
                    "path": _relative(repo_root, path),
                    "sha256": _file_sha256(path),
                    "bytes": path.stat().st_size,
                }
            )
    pyproject = app_dir / "pyproject.toml"
    return {
        "app": app_dir.name,
        "path": _relative(repo_root, app_dir),
        "version": _read_pyproject_version(pyproject) if pyproject.is_file() else "",
        "has_pyproject": pyproject.is_file(),
        "has_app_settings": (app_dir / "src/app_settings.toml").is_file(),
        "has_pipeline_view": (app_dir / "pipeline_view.dot").is_file(),
        "file_count": len(files),
        "files": files,
        "fingerprint_sha256": _combined_digest(files),
    }


def build_revision_traceability(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    core_components = [
        _core_component_row(repo_root, name, relative_path)
        for name, relative_path in CORE_COMPONENT_FILES.items()
    ]
    apps_root = repo_root / BUILTIN_APPS_RELATIVE_PATH
    app_rows = [
        _app_trace_row(repo_root, app_dir)
        for app_dir in sorted(apps_root.iterdir())
        if app_dir.is_dir()
    ]
    missing_core = [row["name"] for row in core_components if not row["exists"]]
    missing_app_pyprojects = [row["app"] for row in app_rows if not row["has_pyproject"]]
    missing_app_settings = [row["app"] for row in app_rows if not row["has_app_settings"]]
    repository = _read_git_head(repo_root)
    issues = [
        {
            "level": "error",
            "location": f"core.{name}",
            "message": "core component pyproject is missing",
        }
        for name in missing_core
    ]
    issues.extend(
        {
            "level": "error",
            "location": f"apps.{name}",
            "message": "built-in app pyproject is missing",
        }
        for name in missing_app_pyprojects
    )
    issues.extend(
        {
            "level": "error",
            "location": f"apps.{name}",
            "message": "built-in app settings are missing",
        }
        for name in missing_app_settings
    )
    return {
        "schema": SCHEMA,
        "run_id": "revision-traceability-proof",
        "created_at": CREATED_AT,
        "updated_at": UPDATED_AT,
        "run_status": "validated" if not issues else "invalid",
        "execution_mode": "revision_traceability_static",
        "repository": repository,
        "summary": {
            "schema": SCHEMA,
            "core_component_count": len(core_components),
            "core_component_versions": {
                row["name"]: row["version"] for row in core_components
            },
            "builtin_app_count": len(app_rows),
            "builtin_apps": [row["app"] for row in app_rows],
            "app_fingerprint_count": sum(1 for row in app_rows if row["file_count"] > 0),
            "missing_core_component_count": len(missing_core),
            "missing_app_pyproject_count": len(missing_app_pyprojects),
            "missing_app_settings_count": len(missing_app_settings),
            "pipeline_view_app_count": sum(1 for row in app_rows if row["has_pipeline_view"]),
            "command_execution_count": 0,
            "network_probe_count": 0,
            "repository_commit": repository.get("commit", ""),
        },
        "core_components": core_components,
        "builtin_apps": app_rows,
        "issues": issues,
        "provenance": {
            "uses_git_cli": False,
            "executes_commands": False,
            "queries_network": False,
            "safe_for_public_evidence": True,
        },
    }


def write_revision_traceability(path: Path, state: Mapping[str, Any]) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_revision_traceability(path: Path) -> dict[str, Any]:
    return json.loads(path.expanduser().read_text(encoding="utf-8"))


def persist_revision_traceability(*, repo_root: Path, output_path: Path) -> dict[str, Any]:
    state = build_revision_traceability(repo_root)
    path = write_revision_traceability(output_path, state)
    reloaded = load_revision_traceability(path)
    return {
        "ok": state == reloaded and state.get("run_status") == "validated",
        "path": str(path),
        "state": state,
        "reloaded_state": reloaded,
        "round_trip_ok": state == reloaded,
    }
