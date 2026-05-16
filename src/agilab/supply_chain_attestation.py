# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Static supply-chain attestation evidence for AGILAB public review."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import tomllib
from typing import Any, Mapping


SCHEMA = "agilab.supply_chain_attestation.v1"
CREATED_AT = "2026-04-25T00:00:34Z"
UPDATED_AT = "2026-05-16T00:00:00Z"
CORE_PYPROJECTS = {
    "agi-core": Path("src/agilab/core/agi-core/pyproject.toml"),
    "agi-env": Path("src/agilab/core/agi-env/pyproject.toml"),
    "agi-cluster": Path("src/agilab/core/agi-cluster/pyproject.toml"),
    "agi-node": Path("src/agilab/core/agi-node/pyproject.toml"),
}
PAGE_LIB_PYPROJECTS = {
    "agi-gui": Path("src/agilab/lib/agi-gui/pyproject.toml"),
    "agi-pages": Path("src/agilab/lib/agi-pages/pyproject.toml"),
}
APP_LIB_PYPROJECTS = {
    "agi-apps": Path("src/agilab/lib/agi-apps/pyproject.toml"),
}
APP_PROJECT_PACKAGE_ROOT = Path("src/agilab/lib")
ATTESTED_ROOT_FILES = (
    Path("pyproject.toml"),
    Path("uv.lock"),
    Path("LICENSE"),
    Path("README.pypi.md"),
)
PACKAGE_PAYLOAD_AUDIT_SUFFIXES = {
    ".7z",
    ".csv",
    ".dot",
    ".ipynb",
    ".json",
    ".pyx",
    ".toml",
}
PACKAGE_PAYLOAD_BUDGETS = {
    "max_files": 140,
    "max_bytes": 4 * 1024 * 1024,
    "max_archives": 2,
    "max_notebooks": 1,
}
IGNORED_PAYLOAD_PATH_PARTS = {
    ".egg-info",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "notebooks",
}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def _package_data_patterns(repo_root: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for relative_path in (
        Path("pyproject.toml"),
        *PAGE_LIB_PYPROJECTS.values(),
        *APP_LIB_PYPROJECTS.values(),
    ):
        path = repo_root / relative_path
        if not path.is_file():
            continue
        payload = _read_toml(path)
        package_data = (
            payload.get("tool", {})
            .get("setuptools", {})
            .get("package-data", {})
        )
        if not isinstance(package_data, dict):
            continue
        for package_name, patterns in sorted(package_data.items()):
            if not isinstance(patterns, list):
                continue
            for pattern in patterns:
                rows.append(
                    {
                        "pyproject": relative_path.as_posix(),
                        "package": str(package_name),
                        "pattern": str(pattern),
                    }
                )
    return rows


def _project_metadata(path: Path) -> dict[str, Any]:
    payload = _read_toml(path)
    project = payload.get("project", {})
    if not isinstance(project, dict):
        project = {}
    optional_dependencies = project.get("optional-dependencies", {}) or {}
    if not isinstance(optional_dependencies, dict):
        optional_dependencies = {}
    optional_dependencies_by_extra = {
        str(extra): [str(row) for row in dependencies or []]
        for extra, dependencies in sorted(optional_dependencies.items())
        if isinstance(dependencies, list)
    }
    return {
        "name": str(project.get("name", "") or ""),
        "version": str(project.get("version", "") or ""),
        "requires_python": str(project.get("requires-python", "") or ""),
        "license": str(project.get("license", "") or ""),
        "license_files": [str(row) for row in project.get("license-files", [])],
        "dependency_count": len(project.get("dependencies", []) or []),
        "dependencies": [str(row) for row in project.get("dependencies", []) or []],
        "optional_dependencies": [
            dependency
            for dependencies in optional_dependencies_by_extra.values()
            for dependency in dependencies
        ],
        "optional_dependencies_by_extra": optional_dependencies_by_extra,
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


def _app_lib_rows(repo_root: Path) -> list[dict[str, Any]]:
    rows = []
    for name, relative_path in APP_LIB_PYPROJECTS.items():
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


def _app_project_package_rows(repo_root: Path) -> list[dict[str, Any]]:
    rows = []
    package_root = repo_root / APP_PROJECT_PACKAGE_ROOT
    for path in sorted(package_root.glob("agi-app-*-project/pyproject.toml")):
        metadata = _project_metadata(path) if path.is_file() else {}
        package_name = str(metadata.get("name") or path.parent.name)
        app_name = package_name.removeprefix("agi-app-").replace("-", "_")
        rows.append(
            {
                "name": package_name,
                "app": app_name,
                "path": _safe_relative(repo_root, path),
                "exists": path.is_file(),
                "version": metadata.get("version", ""),
                "sha256": _file_sha256(path) if path.is_file() else "",
            }
        )
    return rows


_DEPENDENCY_SPEC_RE = re.compile(
    r"^\s*([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?\s*(?:(==|>=)\s*([^,;\s]+))?"
)


def _dependency_parts(dependency: str) -> tuple[str, str, str] | None:
    requirement = dependency.split(";", 1)[0].strip()
    match = _DEPENDENCY_SPEC_RE.match(requirement)
    if not match:
        return None
    name, operator, version = match.groups()
    return name.strip(), (operator or "").strip(), (version or "").strip()


def _dependency_name(dependency: str) -> str:
    parts = _dependency_parts(dependency)
    return parts[0] if parts else ""


def _aligned_rows_for_package(
    rows: list[dict[str, Any]],
    *,
    package: str,
    dependencies: set[str],
) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if row.get("package") == package
        and row.get("dependency") in dependencies
        and row.get("aligned") is True
    ]


def _internal_dependency_constraint_rows(
    package_metadata: Mapping[str, Mapping[str, Any]],
    expected_versions: Mapping[str, str],
    *,
    expected_operator: str,
    include_optional: bool = False,
) -> list[dict[str, Any]]:
    rows = []
    for package_name, metadata in sorted(package_metadata.items()):
        dependencies = list(metadata.get("dependencies", []))
        if include_optional:
            dependencies.extend(metadata.get("optional_dependencies", []))
        for dependency in dependencies:
            parts = _dependency_parts(str(dependency))
            if parts is None:
                continue
            dependency_name, operator, version = parts
            expected_version = expected_versions.get(dependency_name)
            if expected_version is None:
                continue
            rows.append(
                {
                    "package": package_name,
                    "dependency": dependency_name,
                    "operator": operator,
                    "expected_operator": expected_operator,
                    "pinned_version": version,
                    "expected_version": expected_version,
                    "aligned": (
                        operator == expected_operator
                        and version == expected_version
                    ),
                    "specifier": str(dependency),
                }
            )
    return rows


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
                "dependencies": metadata.get("dependencies", []),
                "sha256": _file_sha256(path),
            }
        )
    return rows


def _builtin_payload_rows(repo_root: Path) -> list[dict[str, Any]]:
    apps_root = repo_root / "src/agilab/apps/builtin"
    rows: list[dict[str, Any]] = []
    if not apps_root.is_dir():
        return rows
    for path in sorted(apps_root.rglob("*")):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(apps_root).parts
        if any(part in IGNORED_PAYLOAD_PATH_PARTS for part in relative_parts):
            continue
        if any(part.endswith(".egg-info") for part in relative_parts):
            continue
        if any(part.startswith(".") for part in relative_parts):
            continue
        suffix = path.suffix.lower()
        if suffix not in PACKAGE_PAYLOAD_AUDIT_SUFFIXES:
            continue
        rows.append(
            {
                "path": _safe_relative(repo_root, path),
                "suffix": suffix or "<none>",
                "bytes": path.stat().st_size,
                "sha256": _file_sha256(path),
            }
        )
    return rows


def _suffix_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        suffix = str(row.get("suffix", ""))
        counts[suffix] = counts.get(suffix, 0) + 1
    return dict(sorted(counts.items()))


def build_supply_chain_attestation(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    root_pyproject = repo_root / "pyproject.toml"
    root_metadata = _project_metadata(root_pyproject)
    root_files = _root_file_rows(repo_root)
    core_components = _core_rows(repo_root)
    page_lib_components = _page_lib_rows(repo_root)
    app_lib_components = _app_lib_rows(repo_root)
    app_project_package_components = _app_project_package_rows(repo_root)
    app_pyprojects = _app_pyproject_rows(repo_root)
    package_data_patterns = _package_data_patterns(repo_root)
    builtin_payload_files = _builtin_payload_rows(repo_root)
    builtin_payload_bytes = sum(
        int(row.get("bytes", 0)) for row in builtin_payload_files
    )
    builtin_archive_file_count = sum(
        1 for row in builtin_payload_files if row.get("suffix") == ".7z"
    )
    builtin_notebook_file_count = sum(
        1 for row in builtin_payload_files if row.get("suffix") == ".ipynb"
    )
    builtin_payload_budget = {
        "file_count": len(builtin_payload_files),
        "max_files": PACKAGE_PAYLOAD_BUDGETS["max_files"],
        "bytes": builtin_payload_bytes,
        "max_bytes": PACKAGE_PAYLOAD_BUDGETS["max_bytes"],
        "archive_count": builtin_archive_file_count,
        "max_archives": PACKAGE_PAYLOAD_BUDGETS["max_archives"],
        "notebook_count": builtin_notebook_file_count,
        "max_notebooks": PACKAGE_PAYLOAD_BUDGETS["max_notebooks"],
    }
    builtin_payload_within_budget = (
        builtin_payload_budget["file_count"] <= builtin_payload_budget["max_files"]
        and builtin_payload_budget["bytes"] <= builtin_payload_budget["max_bytes"]
        and builtin_payload_budget["archive_count"] <= builtin_payload_budget["max_archives"]
        and builtin_payload_budget["notebook_count"] <= builtin_payload_budget["max_notebooks"]
    )
    largest_builtin_payload_files = sorted(
        builtin_payload_files,
        key=lambda row: int(row.get("bytes", 0)),
        reverse=True,
    )[:10]
    root_version = root_metadata.get("version", "")
    core_versions = {row["name"]: row["version"] for row in core_components}
    aligned_core_versions = all(
        version == root_version for version in core_versions.values()
    )
    page_lib_versions = {row["name"]: row["version"] for row in page_lib_components}
    aligned_page_lib_versions = all(
        version == root_version for version in page_lib_versions.values()
    )
    app_lib_versions = {row["name"]: row["version"] for row in app_lib_components}
    aligned_app_lib_versions = all(
        version == root_version for version in app_lib_versions.values()
    )
    package_metadata = {"agilab": root_metadata}
    for name, relative_path in {**CORE_PYPROJECTS, **PAGE_LIB_PYPROJECTS, **APP_LIB_PYPROJECTS}.items():
        path = repo_root / relative_path
        package_metadata[name] = _project_metadata(path) if path.is_file() else {}
    expected_internal_versions = {
        "agilab": root_version,
        **core_versions,
        **page_lib_versions,
        **app_lib_versions,
    }
    internal_dependency_pins = _internal_dependency_constraint_rows(
        package_metadata,
        expected_internal_versions,
        expected_operator="==",
        include_optional=True,
    )
    mismatched_internal_dependency_pins = [
        row for row in internal_dependency_pins if not row["aligned"]
    ]
    aligned_internal_dependency_pins = not mismatched_internal_dependency_pins
    aligned_root_core_pins = _aligned_rows_for_package(
        internal_dependency_pins,
        package="agilab",
        dependencies=set(CORE_PYPROJECTS),
    )
    aligned_root_page_lib_pins = _aligned_rows_for_package(
        internal_dependency_pins,
        package="agilab",
        dependencies=set(PAGE_LIB_PYPROJECTS),
    )
    aligned_root_app_lib_pins = _aligned_rows_for_package(
        internal_dependency_pins,
        package="agilab",
        dependencies=set(APP_LIB_PYPROJECTS),
    )
    core_release_graph_aligned = aligned_core_versions or (
        aligned_internal_dependency_pins and bool(aligned_root_core_pins)
    )
    page_lib_release_graph_aligned = aligned_page_lib_versions or (
        aligned_internal_dependency_pins and bool(aligned_root_page_lib_pins)
    )
    app_lib_release_graph_aligned = aligned_app_lib_versions or (
        aligned_internal_dependency_pins and bool(aligned_root_app_lib_pins)
    )
    expected_app_project_versions = {
        str(row["app"]): str(row["version"])
        for row in app_project_package_components
        if row.get("version")
    }
    mismatched_builtin_app_versions = [
        {
            **row,
            "expected_version": expected_app_project_versions.get(str(row.get("app")), ""),
        }
        for row in app_pyprojects
        if expected_app_project_versions.get(str(row.get("app")))
        and row.get("version") != expected_app_project_versions.get(str(row.get("app")))
    ]
    aligned_builtin_app_versions = not mismatched_builtin_app_versions
    app_metadata = {
        str(row["app"]): {"dependencies": row.get("dependencies", [])}
        for row in app_pyprojects
    }
    builtin_app_internal_dependency_bounds = _internal_dependency_constraint_rows(
        app_metadata,
        expected_internal_versions,
        expected_operator=">=",
    )
    mismatched_builtin_app_internal_dependency_bounds = [
        row for row in builtin_app_internal_dependency_bounds if not row["aligned"]
    ]
    aligned_builtin_app_internal_dependency_bounds = (
        not mismatched_builtin_app_internal_dependency_bounds
    )
    root_declared_dependencies = [
        *root_metadata.get("dependencies", []),
        *root_metadata.get("optional_dependencies", []),
    ]
    pinned_core_dependencies = [
        dependency
        for dependency in root_declared_dependencies
        if _dependency_name(dependency) in CORE_PYPROJECTS and "==" in dependency
    ]
    pinned_page_lib_dependencies = [
        dependency
        for dependency in root_declared_dependencies
        if _dependency_name(dependency) in PAGE_LIB_PYPROJECTS and "==" in dependency
    ]
    pinned_app_lib_dependencies = [
        dependency
        for dependency in root_declared_dependencies
        if _dependency_name(dependency) in APP_LIB_PYPROJECTS and "==" in dependency
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
    if not core_release_graph_aligned:
        issues.append(
            {
                "level": "error",
                "location": "core.version_alignment",
                "message": "bundled AGI core components are not covered by exact bundle pins",
            }
        )
    if not page_lib_release_graph_aligned:
        issues.append(
            {
                "level": "error",
                "location": "page_lib.version_alignment",
                "message": "AGILAB page libraries are not covered by exact bundle pins",
            }
        )
    if not app_lib_release_graph_aligned:
        issues.append(
            {
                "level": "error",
                "location": "app_lib.version_alignment",
                "message": "AGILAB app libraries are not covered by exact bundle pins",
            }
        )
    for row in mismatched_internal_dependency_pins:
        issues.append(
            {
                "level": "error",
                "location": (
                    f"dependencies.{row['package']}.{row['dependency']}"
                ),
                "message": (
                    f"{row['package']} pins {row['dependency']} to "
                    f"{row['pinned_version']} but expected {row['expected_version']}"
                ),
            }
        )
    for row in mismatched_builtin_app_versions:
        issues.append(
            {
                "level": "error",
                "location": f"builtin_apps.{row['app']}.version",
                "message": (
                    f"built-in app {row['app']} has version {row['version']} "
                    f"but expected {row['expected_version']}"
                ),
            }
        )
    for row in mismatched_builtin_app_internal_dependency_bounds:
        issues.append(
            {
                "level": "error",
                "location": (
                    f"builtin_apps.{row['package']}.dependencies.{row['dependency']}"
                ),
                "message": (
                    f"built-in app {row['package']} requires {row['dependency']} "
                    f"with {row['operator'] or 'no operator'} {row['pinned_version'] or '<none>'} "
                    f"but expected >= {row['expected_version']}"
                ),
            }
        )
    if not builtin_payload_within_budget:
        issues.append(
            {
                "level": "error",
                "location": "package_payload.budget",
                "message": "built-in app payload inventory exceeds the public package budget",
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
            "pinned_app_lib_dependency_count": len(pinned_app_lib_dependencies),
            "pinned_app_lib_dependencies": pinned_app_lib_dependencies,
            "internal_dependency_pin_count": len(internal_dependency_pins),
            "internal_dependency_pins": internal_dependency_pins,
            "mismatched_internal_dependency_pin_count": len(
                mismatched_internal_dependency_pins
            ),
            "mismatched_internal_dependency_pins": mismatched_internal_dependency_pins,
            "aligned_internal_dependency_pins": aligned_internal_dependency_pins,
            "root_file_count": len(root_files),
            "missing_root_file_count": len(missing_files),
            "lockfile_present": (repo_root / "uv.lock").is_file(),
            "license_present": (repo_root / "LICENSE").is_file(),
            "core_component_count": len(core_components),
            "core_versions": core_versions,
            "aligned_core_versions": aligned_core_versions,
            "core_release_graph_aligned": core_release_graph_aligned,
            "page_lib_component_count": len(page_lib_components),
            "page_lib_versions": page_lib_versions,
            "aligned_page_lib_versions": aligned_page_lib_versions,
            "page_lib_release_graph_aligned": page_lib_release_graph_aligned,
            "app_lib_component_count": len(app_lib_components),
            "app_lib_versions": app_lib_versions,
            "aligned_app_lib_versions": aligned_app_lib_versions,
            "app_lib_release_graph_aligned": app_lib_release_graph_aligned,
            "app_project_package_component_count": len(app_project_package_components),
            "app_project_package_versions": {
                row["name"]: row["version"] for row in app_project_package_components
            },
            "builtin_app_pyproject_count": len(app_pyprojects),
            "package_data_pattern_count": len(package_data_patterns),
            "package_data_patterns": package_data_patterns,
            "builtin_payload_file_count": len(builtin_payload_files),
            "builtin_payload_bytes": builtin_payload_bytes,
            "builtin_payload_budget": builtin_payload_budget,
            "builtin_payload_within_budget": builtin_payload_within_budget,
            "builtin_payload_extension_counts": _suffix_counts(
                builtin_payload_files
            ),
            "builtin_archive_file_count": builtin_archive_file_count,
            "builtin_notebook_file_count": builtin_notebook_file_count,
            "largest_builtin_payload_files": largest_builtin_payload_files,
            "aligned_builtin_app_versions": aligned_builtin_app_versions,
            "mismatched_builtin_app_version_count": len(
                mismatched_builtin_app_versions
            ),
            "mismatched_builtin_app_versions": mismatched_builtin_app_versions,
            "builtin_app_internal_dependency_bound_count": len(
                builtin_app_internal_dependency_bounds
            ),
            "builtin_app_internal_dependency_bounds": (
                builtin_app_internal_dependency_bounds
            ),
            "aligned_builtin_app_internal_dependency_bounds": (
                aligned_builtin_app_internal_dependency_bounds
            ),
            "mismatched_builtin_app_internal_dependency_bound_count": len(
                mismatched_builtin_app_internal_dependency_bounds
            ),
            "mismatched_builtin_app_internal_dependency_bounds": (
                mismatched_builtin_app_internal_dependency_bounds
            ),
            "command_execution_count": 0,
            "network_probe_count": 0,
            "formal_supply_chain_attestation": False,
        },
        "root_files": root_files,
        "core_components": core_components,
        "page_lib_components": page_lib_components,
        "app_lib_components": app_lib_components,
        "app_project_package_components": app_project_package_components,
        "builtin_app_pyprojects": app_pyprojects,
        "package_data_patterns": package_data_patterns,
        "builtin_payload_files": builtin_payload_files,
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
