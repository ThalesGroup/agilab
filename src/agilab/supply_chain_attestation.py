# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Static supply-chain attestation evidence for AGILAB public review."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tomllib
from typing import Any, Mapping


SCHEMA = "agilab.supply_chain_attestation.v1"
CREATED_AT = "2026-04-25T00:00:34Z"
UPDATED_AT = "2026-04-25T00:00:34Z"
CORE_PYPROJECTS = {
    "agi-core": Path("src/agilab/core/agi-core/pyproject.toml"),
    "agi-env": Path("src/agilab/core/agi-env/pyproject.toml"),
    "agi-cluster": Path("src/agilab/core/agi-cluster/pyproject.toml"),
    "agi-node": Path("src/agilab/core/agi-node/pyproject.toml"),
}
PAGE_LIB_PYPROJECTS = {
    "agi-gui": Path("src/agilab/lib/agi-gui/pyproject.toml"),
}
ATTESTED_ROOT_FILES = (
    Path("pyproject.toml"),
    Path("uv.lock"),
    Path("LICENSE"),
    Path("README.pypi.md"),
)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def _project_metadata(path: Path) -> dict[str, Any]:
    payload = _read_toml(path)
    project = payload.get("project", {})
    if not isinstance(project, dict):
        project = {}
    return {
        "name": str(project.get("name", "") or ""),
        "version": str(project.get("version", "") or ""),
        "requires_python": str(project.get("requires-python", "") or ""),
        "license": str(project.get("license", "") or ""),
        "license_files": [str(row) for row in project.get("license-files", [])],
        "dependency_count": len(project.get("dependencies", []) or []),
        "dependencies": [str(row) for row in project.get("dependencies", []) or []],
    }


def _safe_relative(repo_root: Path, path: Path) -> str:
    return path.relative_to(repo_root).as_posix()


def _root_file_rows(repo_root: Path) -> list[dict[str, Any]]:
    rows = []
    for relative_path in ATTESTED_ROOT_FILES:
        path = repo_root / relative_path
        rows.append(
            {
                "path": relative_path.as_posix(),
                "exists": path.is_file(),
                "sha256": _file_sha256(path) if path.is_file() else "",
                "bytes": path.stat().st_size if path.is_file() else 0,
            }
        )
    return rows


def _core_rows(repo_root: Path) -> list[dict[str, Any]]:
    rows = []
    for name, relative_path in CORE_PYPROJECTS.items():
        path = repo_root / relative_path
        metadata = _project_metadata(path) if path.is_file() else {}
        rows.append(
            {
                "name": name,
                "path": relative_path.as_posix(),
                "exists": path.is_file(),
                "version": metadata.get("version", ""),
                "sha256": _file_sha256(path) if path.is_file() else "",
            }
        )
    return rows


def _page_lib_rows(repo_root: Path) -> list[dict[str, Any]]:
    rows = []
    for name, relative_path in PAGE_LIB_PYPROJECTS.items():
        path = repo_root / relative_path
        metadata = _project_metadata(path) if path.is_file() else {}
        rows.append(
            {
                "name": name,
                "path": relative_path.as_posix(),
                "exists": path.is_file(),
                "version": metadata.get("version", ""),
                "sha256": _file_sha256(path) if path.is_file() else "",
            }
        )
    return rows


def _dependency_name(dependency: str) -> str:
    return dependency.split(";", 1)[0].split("[", 1)[0].split("=", 1)[0].strip()


def _app_pyproject_rows(repo_root: Path) -> list[dict[str, Any]]:
    apps_root = repo_root / "src/agilab/apps/builtin"
    rows = []
    for path in sorted(apps_root.glob("*/pyproject.toml")):
        metadata = _project_metadata(path)
        rows.append(
            {
                "app": path.parent.name,
                "path": _safe_relative(repo_root, path),
                "version": metadata.get("version", ""),
                "sha256": _file_sha256(path),
            }
        )
    return rows


def build_supply_chain_attestation(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    root_pyproject = repo_root / "pyproject.toml"
    root_metadata = _project_metadata(root_pyproject)
    root_files = _root_file_rows(repo_root)
    core_components = _core_rows(repo_root)
    page_lib_components = _page_lib_rows(repo_root)
    app_pyprojects = _app_pyproject_rows(repo_root)
    root_version = root_metadata.get("version", "")
    core_versions = {row["name"]: row["version"] for row in core_components}
    aligned_core_versions = all(
        version == root_version for version in core_versions.values()
    )
    page_lib_versions = {row["name"]: row["version"] for row in page_lib_components}
    aligned_page_lib_versions = all(
        version == root_version for version in page_lib_versions.values()
    )
    pinned_core_dependencies = [
        dependency
        for dependency in root_metadata.get("dependencies", [])
        if _dependency_name(dependency) in CORE_PYPROJECTS and "==" in dependency
    ]
    pinned_page_lib_dependencies = [
        dependency
        for dependency in root_metadata.get("dependencies", [])
        if _dependency_name(dependency) in PAGE_LIB_PYPROJECTS and "==" in dependency
    ]
    missing_files = [row["path"] for row in root_files if not row["exists"]]
    issues = [
        {
            "level": "error",
            "location": f"files.{path}",
            "message": "required supply-chain evidence file is missing",
        }
        for path in missing_files
    ]
    if not aligned_core_versions:
        issues.append(
            {
                "level": "error",
                "location": "core.version_alignment",
                "message": "bundled AGI core package versions do not align",
            }
        )
    return {
        "schema": SCHEMA,
        "run_id": "supply-chain-attestation-proof",
        "created_at": CREATED_AT,
        "updated_at": UPDATED_AT,
        "run_status": "validated" if not issues else "invalid",
        "execution_mode": "supply_chain_static_attestation",
        "package": root_metadata,
        "summary": {
            "schema": SCHEMA,
            "package_name": root_metadata.get("name", ""),
            "package_version": root_version,
            "requires_python": root_metadata.get("requires_python", ""),
            "dependency_count": root_metadata.get("dependency_count", 0),
            "pinned_core_dependency_count": len(pinned_core_dependencies),
            "pinned_core_dependencies": pinned_core_dependencies,
            "pinned_page_lib_dependency_count": len(pinned_page_lib_dependencies),
            "pinned_page_lib_dependencies": pinned_page_lib_dependencies,
            "root_file_count": len(root_files),
            "missing_root_file_count": len(missing_files),
            "lockfile_present": (repo_root / "uv.lock").is_file(),
            "license_present": (repo_root / "LICENSE").is_file(),
            "core_component_count": len(core_components),
            "core_versions": core_versions,
            "aligned_core_versions": aligned_core_versions,
            "page_lib_component_count": len(page_lib_components),
            "page_lib_versions": page_lib_versions,
            "aligned_page_lib_versions": aligned_page_lib_versions,
            "builtin_app_pyproject_count": len(app_pyprojects),
            "command_execution_count": 0,
            "network_probe_count": 0,
            "formal_supply_chain_attestation": False,
        },
        "root_files": root_files,
        "core_components": core_components,
        "page_lib_components": page_lib_components,
        "builtin_app_pyprojects": app_pyprojects,
        "issues": issues,
        "provenance": {
            "source": "local_repository_files",
            "executes_commands": False,
            "queries_network": False,
            "safe_for_public_evidence": True,
        },
    }


def write_supply_chain_attestation(path: Path, state: Mapping[str, Any]) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_supply_chain_attestation(path: Path) -> dict[str, Any]:
    return json.loads(path.expanduser().read_text(encoding="utf-8"))


def persist_supply_chain_attestation(*, repo_root: Path, output_path: Path) -> dict[str, Any]:
    state = build_supply_chain_attestation(repo_root)
    path = write_supply_chain_attestation(output_path, state)
    reloaded = load_supply_chain_attestation(path)
    return {
        "ok": state == reloaded and state.get("run_status") == "validated",
        "path": str(path),
        "state": state,
        "reloaded_state": reloaded,
        "round_trip_ok": state == reloaded,
    }
