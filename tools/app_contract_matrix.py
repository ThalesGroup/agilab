#!/usr/bin/env python3
"""Emit AGILAB built-in app and PyPI app-package contract evidence."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
import sys
import tomllib
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "agilab.app_contract_matrix.v1"
BUILTIN_APPS_REL = Path("src/agilab/apps/builtin")
APPS_PAGES_REL = Path("src/agilab/apps-pages")
PUBLIC_APP_CATALOG_REL = Path("docs/source/public-app-catalog.rst")
APPS_PAGES_CATALOG_REL = Path("docs/source/apps-pages.rst")
AGI_APPS_CATALOG_REL = Path("src/agilab/lib/agi-apps/src/agi_apps/catalog.json")
AGI_PAGES_PROVIDER_REL = Path("src/agilab/lib/agi-pages/src/agi_pages/__init__.py")
REDUCER_EXEMPT_PROJECTS = frozenset({"mycode_project", "global_dag_project"})
OPTIONAL_LAB_STAGES_EXEMPT_PROJECTS = frozenset(
    {
        "execution_pandas_project",
        "execution_polars_project",
        "flight_telemetry_project",
        "mycode_project",
        "pytorch_playground_project",
    }
)


@dataclass(frozen=True)
class Check:
    id: str
    label: str
    status: str
    summary: str
    evidence: tuple[str, ...] = ()
    details: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "status": self.status,
            "summary": self.summary,
            "evidence": list(self.evidence),
            "details": dict(self.details or {}),
        }


def _check(
    check_id: str,
    label: str,
    passed: bool,
    summary: str,
    *,
    evidence: Sequence[str] = (),
    details: Mapping[str, Any] | None = None,
) -> Check:
    return Check(
        check_id,
        label,
        "pass" if passed else "fail",
        summary,
        tuple(evidence),
        details,
    )


def _load_module(repo_root: Path, relative_path: Path, module_name: str):
    module_path = repo_root / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def _relative(repo_root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)


def _dependencies(payload: Mapping[str, Any]) -> tuple[str, ...]:
    raw = payload.get("project", {}).get("dependencies", [])
    if not isinstance(raw, list):
        return ()
    return tuple(str(item) for item in raw)


def _has_dependency(dependencies: Sequence[str], package: str) -> bool:
    pattern = re.compile(
        rf"^{re.escape(package)}(?:$|\s*(?:\[|==|~=|!=|<=|>=|<|>|;))",
        re.IGNORECASE,
    )
    return any(pattern.match(item.strip()) for item in dependencies)


def discover_builtin_projects(repo_root: Path) -> tuple[Path, ...]:
    builtin_root = repo_root / BUILTIN_APPS_REL
    return tuple(sorted(path for path in builtin_root.glob("*_project") if path.is_dir()))


def discover_page_bundle_projects(repo_root: Path) -> tuple[Path, ...]:
    pages_root = repo_root / APPS_PAGES_REL
    if not pages_root.is_dir():
        return ()
    return tuple(
        sorted(
            path
            for path in pages_root.iterdir()
            if path.is_dir() and (path / "pyproject.toml").is_file()
        )
    )


def _project_slug(project_name: str) -> str:
    return project_name[: -len("_project")] if project_name.endswith("_project") else project_name


def _project_checks(repo_root: Path, project_path: Path) -> list[Check]:
    project_name = project_path.name
    slug = _project_slug(project_name)
    pyproject_path = project_path / "pyproject.toml"
    readme_path = project_path / "README.md"
    app_settings_path = project_path / "src" / "app_settings.toml"
    app_args_form_path = project_path / "src" / "app_args_form.py"
    manager_module = project_path / "src" / slug
    worker_module = project_path / "src" / f"{slug}_worker"
    worker_pyproject = worker_module / "pyproject.toml"
    lab_stages_path = project_path / "lab_stages.toml"
    reduction_path = manager_module / "reduction.py"
    checks: list[Check] = []

    required_files = (pyproject_path, readme_path, app_settings_path, app_args_form_path)
    missing_required = [_relative(repo_root, path) for path in required_files if not path.is_file()]
    checks.append(
        _check(
            f"{project_name}:required_files",
            f"{project_name} required files",
            not missing_required,
            "required app contract files are present",
            evidence=tuple(_relative(repo_root, path) for path in required_files),
            details={"missing": missing_required},
        )
    )

    try:
        pyproject = _read_toml(pyproject_path)
        manager_dependencies = _dependencies(pyproject)
        project_data = pyproject.get("project", {})
        missing_core_deps = [
            package
            for package in ("agi-env", "agi-node", "agi-cluster")
            if not _has_dependency(manager_dependencies, package)
        ]
        checks.append(
            _check(
                f"{project_name}:manager_pyproject",
                f"{project_name} manager pyproject",
                project_data.get("name") == project_name
                and bool(project_data.get("version"))
                and not missing_core_deps,
                "manager pyproject declares the project name, version, and core dependencies",
                evidence=(_relative(repo_root, pyproject_path),),
                details={
                    "name": project_data.get("name"),
                    "version": project_data.get("version"),
                    "missing_core_dependencies": missing_core_deps,
                },
            )
        )
    except Exception as exc:
        checks.append(
            _check(
                f"{project_name}:manager_pyproject",
                f"{project_name} manager pyproject",
                False,
                f"manager pyproject could not be parsed: {exc}",
                evidence=(_relative(repo_root, pyproject_path),),
            )
        )

    module_missing = [
        _relative(repo_root, path)
        for path in (manager_module / "__init__.py", worker_module / "__init__.py", worker_pyproject)
        if not path.is_file()
    ]
    checks.append(
        _check(
            f"{project_name}:module_layout",
            f"{project_name} module layout",
            not module_missing,
            "manager and worker modules are present",
            evidence=(
                _relative(repo_root, manager_module),
                _relative(repo_root, worker_module),
                _relative(repo_root, worker_pyproject),
            ),
            details={"missing": module_missing},
        )
    )

    try:
        worker_data = _read_toml(worker_pyproject)
        worker_dependencies = _dependencies(worker_data)
        uv_sources = worker_data.get("tool", {}).get("uv", {}).get("sources", {})
        missing_worker_deps = [
            package for package in ("agi-env", "agi-node") if not _has_dependency(worker_dependencies, package)
        ]
        source_paths = {
            key: value.get("path") if isinstance(value, dict) else None
            for key, value in uv_sources.items()
            if key in {"agi-env", "agi-node"}
        }
        checks.append(
            _check(
                f"{project_name}:worker_pyproject",
                f"{project_name} worker pyproject",
                bool(worker_data.get("project", {}).get("name"))
                and bool(worker_data.get("project", {}).get("version"))
                and not missing_worker_deps
                and source_paths
                == {
                    "agi-env": "../../../../../core/agi-env",
                    "agi-node": "../../../../../core/agi-node",
                },
                "worker pyproject declares worker metadata, deps, and local source paths",
                evidence=(_relative(repo_root, worker_pyproject),),
                details={
                    "name": worker_data.get("project", {}).get("name"),
                    "version": worker_data.get("project", {}).get("version"),
                    "missing_worker_dependencies": missing_worker_deps,
                    "source_paths": source_paths,
                },
            )
        )
    except Exception as exc:
        checks.append(
            _check(
                f"{project_name}:worker_pyproject",
                f"{project_name} worker pyproject",
                False,
                f"worker pyproject could not be parsed: {exc}",
                evidence=(_relative(repo_root, worker_pyproject),),
            )
        )

    try:
        settings = _read_toml(app_settings_path)
        meta = settings.get("__meta__", {})
        unsupported_version = False
        if isinstance(meta, dict) and meta.get("version") not in (None, "", 1, "1"):
            unsupported_version = True
        checks.append(
            _check(
                f"{project_name}:app_settings",
                f"{project_name} app settings",
                not unsupported_version and isinstance(settings, dict),
                "app_settings.toml is parseable and does not declare an unsupported schema",
                evidence=(_relative(repo_root, app_settings_path),),
                details={"meta": meta if isinstance(meta, dict) else {"invalid_meta": str(meta)}},
            )
        )
    except Exception as exc:
        checks.append(
            _check(
                f"{project_name}:app_settings",
                f"{project_name} app settings",
                False,
                f"app_settings.toml could not be parsed: {exc}",
                evidence=(_relative(repo_root, app_settings_path),),
            )
        )

    readme_text = readme_path.read_text(encoding="utf-8", errors="ignore") if readme_path.is_file() else ""
    checks.append(
        _check(
            f"{project_name}:readme",
            f"{project_name} README",
            project_name in readme_text and len(readme_text.split()) >= 40,
            "README names the project and has enough adaptation context",
            evidence=(_relative(repo_root, readme_path),),
            details={"word_count": len(readme_text.split()), "mentions_project": project_name in readme_text},
        )
    )

    if project_name in OPTIONAL_LAB_STAGES_EXEMPT_PROJECTS:
        lab_stage_ok = True
        lab_stage_summary = "lab_stages.toml is optional for this app contract"
        lab_stage_details: dict[str, Any] = {"required": False, "exists": lab_stages_path.is_file()}
    else:
        try:
            lab_stages = _read_toml(lab_stages_path)
            lab_stage_ok = bool(lab_stages)
            lab_stage_summary = "lab_stages.toml is parseable"
            lab_stage_details = {"required": True, "top_level_keys": sorted(lab_stages)}
        except Exception as exc:
            lab_stage_ok = False
            lab_stage_summary = f"lab_stages.toml is required and could not be parsed: {exc}"
            lab_stage_details = {"required": True, "exists": lab_stages_path.is_file()}
    checks.append(
        _check(
            f"{project_name}:lab_stages",
            f"{project_name} lab stages",
            lab_stage_ok,
            lab_stage_summary,
            evidence=(_relative(repo_root, lab_stages_path),),
            details=lab_stage_details,
        )
    )

    reducer_required = project_name not in REDUCER_EXEMPT_PROJECTS
    reducer_ok = reduction_path.is_file() or not reducer_required
    checks.append(
        _check(
            f"{project_name}:reducer_contract",
            f"{project_name} reducer contract",
            reducer_ok,
            "reducer contract is present or the app is explicitly template-only",
            evidence=(_relative(repo_root, reduction_path),),
            details={"required": reducer_required, "exemptions": sorted(REDUCER_EXEMPT_PROJECTS)},
        )
    )
    return checks


def _project_name_for_package(repo_root: Path, package_path: str) -> str:
    package_root = repo_root / package_path
    project_pyprojects = sorted(package_root.glob("src/*/project/*_project/pyproject.toml"))
    if project_pyprojects:
        return str(project_pyprojects[0].parent.name)
    init_candidates = sorted(package_root.glob("src/*/__init__.py"))
    project_name_re = re.compile(r"^PROJECT_NAME\s*=\s*[\"']([^\"']+)[\"']")
    for init_path in init_candidates:
        for line in init_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            match = project_name_re.match(line.strip())
            if match:
                return match.group(1)
    return ""


def _public_catalog_rows(repo_root: Path) -> dict[str, dict[str, str]]:
    catalog_path = repo_root / PUBLIC_APP_CATALOG_REL
    lines = catalog_path.read_text(encoding="utf-8").splitlines()
    rows: dict[str, dict[str, str]] = {}
    current: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("* - "):
            if len(current) >= 4 and current[0] != "Project":
                rows[current[0]] = {
                    "package": current[1],
                    "status": current[2],
                    "use": " ".join(current[3:]),
                }
            current = [stripped.removeprefix("* - ").strip("`")]
        elif stripped.startswith("- ") and current:
            current.append(stripped.removeprefix("- ").strip("`"))
        elif current and len(current) >= 4 and stripped and not stripped.startswith((".. ", ":")):
            current[-1] = f"{current[-1]} {stripped}".strip()
    if len(current) >= 4 and current[0] != "Project":
        rows[current[0]] = {
            "package": current[1],
            "status": current[2],
            "use": " ".join(current[3:]),
        }
    return rows


def _apps_pages_catalog_rows(repo_root: Path) -> dict[str, dict[str, str]]:
    catalog_path = repo_root / APPS_PAGES_CATALOG_REL
    lines = catalog_path.read_text(encoding="utf-8").splitlines()
    rows: dict[str, dict[str, str]] = {}
    current: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("* - "):
            if len(current) >= 4 and current[0] != "Module":
                rows[current[0]] = {
                    "package": current[1],
                    "purpose": current[2],
                    "status": " ".join(current[3:]),
                }
            current = [stripped.removeprefix("* - ").strip("`")]
        elif stripped.startswith("- ") and current:
            current.append(stripped.removeprefix("- ").strip("`"))
        elif current and len(current) >= 4 and stripped and not stripped.startswith((".. ", ":")):
            current[-1] = f"{current[-1]} {stripped}".strip()
    if len(current) >= 4 and current[0] != "Module":
        rows[current[0]] = {
            "package": current[1],
            "purpose": current[2],
            "status": " ".join(current[3:]),
        }
    return rows


def _catalog_distribution_rows(repo_root: Path) -> dict[str, dict[str, str]]:
    payload = json.loads((repo_root / AGI_APPS_CATALOG_REL).read_text(encoding="utf-8"))
    rows: dict[str, dict[str, str]] = {}
    if isinstance(payload, list):
        for row in payload:
            if isinstance(row, dict) and isinstance(row.get("distribution"), str):
                rows[row["distribution"]] = {key: str(value) for key, value in row.items()}
    return rows


def _literal_string_tuple_assignment(path: Path, name: str) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        value = ast.literal_eval(node.value)
        if isinstance(value, tuple) and all(isinstance(item, str) for item in value):
            return value
        raise RuntimeError(f"{path} assignment {name} is not a tuple of strings")
    raise RuntimeError(f"{path} does not define {name}")


def _agi_pages_public_modules(repo_root: Path) -> tuple[str, ...]:
    return _literal_string_tuple_assignment(
        repo_root / AGI_PAGES_PROVIDER_REL,
        "PUBLIC_PAGE_MODULES",
    )


def _page_pyproject_contract_errors(
    repo_root: Path,
    package_to_module: Mapping[str, str],
    package_specs: Mapping[str, str],
) -> dict[str, dict[str, Any]]:
    errors: dict[str, dict[str, Any]] = {}
    for package, module in sorted(package_to_module.items()):
        pyproject_path = repo_root / package_specs[package] / "pyproject.toml"
        try:
            pyproject = _read_toml(pyproject_path)
        except Exception as exc:
            errors[package] = {
                "module": module,
                "pyproject": _relative(repo_root, pyproject_path),
                "error": str(exc),
            }
            continue
        project = pyproject.get("project", {})
        entry_points = project.get("entry-points", {})
        agilab_pages = (
            entry_points.get("agilab.pages", {})
            if isinstance(entry_points, dict)
            else {}
        )
        expected_entry_point = f"{module}:bundle_root"
        mismatch: dict[str, Any] = {
            "module": module,
            "pyproject": _relative(repo_root, pyproject_path),
        }
        if project.get("name") != package:
            mismatch["name"] = project.get("name")
            mismatch["expected_name"] = package
        if not project.get("version"):
            mismatch["version"] = project.get("version")
        if not isinstance(agilab_pages, dict) or agilab_pages.get(module) != expected_entry_point:
            mismatch["entry_point"] = (
                agilab_pages.get(module) if isinstance(agilab_pages, dict) else None
            )
            mismatch["expected_entry_point"] = expected_entry_point
        if set(mismatch) != {"module", "pyproject"}:
            errors[package] = mismatch
    return errors


def _status_includes_agi_pages(status: str) -> bool:
    normalized = status.casefold()
    return "included in" in normalized and "agi-pages" in normalized


def _global_checks(
    repo_root: Path,
    *,
    package_split_module: Any | None = None,
    pypi_app_packages_module: Any | None = None,
    pypi_promoted_packages: Sequence[str] | None = None,
) -> list[Check]:
    package_split = package_split_module or _load_module(
        repo_root,
        Path("tools/package_split_contract.py"),
        "agilab_app_contract_package_split",
    )
    pypi_app_packages = pypi_app_packages_module or _load_module(
        repo_root,
        Path("src/agilab/pypi_app_packages.py"),
        "agilab_app_contract_pypi_app_packages",
    )
    builtin_projects = {path.name for path in discover_builtin_projects(repo_root)}
    source_page_modules = {path.name for path in discover_page_bundle_projects(repo_root)}
    package_specs = dict(package_split.APP_PROJECT_PACKAGE_SPECS)
    page_package_specs = dict(package_split.PAGE_BUNDLE_PACKAGE_SPECS)
    promoted_package_names = set(package_split.PROMOTED_APP_PROJECT_PACKAGE_NAMES)
    if pypi_promoted_packages is None:
        pypi_promoted = set(pypi_app_packages.PROMOTED_PYPI_APP_PACKAGES)
    else:
        pypi_promoted = set(pypi_promoted_packages)
    package_to_project = {
        package: _project_name_for_package(repo_root, package_path)
        for package, package_path in package_specs.items()
    }
    public_rows = _public_catalog_rows(repo_root)
    agi_apps_rows = _catalog_distribution_rows(repo_root)

    package_mapping_errors = {
        package: {
            "package_path": package_specs[package],
            "project": project,
            "builtin_exists": project in builtin_projects,
        }
        for package, project in sorted(package_to_project.items())
        if not project or project not in builtin_projects
    }
    checks = [
        _check(
            "app_package_specs_point_to_builtin_projects",
            "App package specs point to built-in projects",
            not package_mapping_errors,
            "package split app specs resolve to existing built-in projects",
            evidence=("tools/package_split_contract.py", str(BUILTIN_APPS_REL)),
            details={"errors": package_mapping_errors, "package_to_project": package_to_project},
        )
    ]

    page_package_to_module = {
        package: Path(page_path).name for package, page_path in sorted(page_package_specs.items())
    }
    page_mapping_errors = {
        package: {
            "package_path": page_package_specs[package],
            "module": module,
            "source_exists": module in source_page_modules,
            "pyproject_exists": (repo_root / page_package_specs[package] / "pyproject.toml").is_file(),
        }
        for package, module in page_package_to_module.items()
        if module not in source_page_modules
        or not (repo_root / page_package_specs[package] / "pyproject.toml").is_file()
    }
    checks.append(
        _check(
            "page_bundle_specs_point_to_source_bundles",
            "Page-bundle package specs point to source bundles",
            not page_mapping_errors,
            "package split page specs resolve to checked-in apps-pages bundles",
            evidence=("tools/package_split_contract.py", str(APPS_PAGES_REL)),
            details={
                "errors": page_mapping_errors,
                "package_to_module": page_package_to_module,
            },
        )
    )

    page_pyproject_errors = _page_pyproject_contract_errors(
        repo_root,
        page_package_to_module,
        page_package_specs,
    )
    checks.append(
        _check(
            "page_bundle_pyprojects_match_package_contract",
            "Page-bundle pyprojects match package contract",
            not page_pyproject_errors,
            "page-bundle pyprojects expose the expected name, version, and entry point",
            evidence=(str(APPS_PAGES_REL), "tools/package_split_contract.py"),
            details={"errors": page_pyproject_errors},
        )
    )

    page_catalog_rows = _apps_pages_catalog_rows(repo_root)
    expected_page_catalog = {
        module: package for package, module in page_package_to_module.items()
    }
    missing_page_rows = sorted(module for module in source_page_modules if module not in page_catalog_rows)
    source_catalog_package_mismatches: dict[str, dict[str, Any]] = {}
    for module in sorted(source_page_modules):
        pyproject_path = repo_root / APPS_PAGES_REL / module / "pyproject.toml"
        try:
            expected_package = _read_toml(pyproject_path).get("project", {}).get("name")
        except Exception as exc:
            source_catalog_package_mismatches[module] = {"error": str(exc)}
            continue
        if page_catalog_rows.get(module, {}).get("package") != expected_package:
            source_catalog_package_mismatches[module] = {
                "expected_package": expected_package,
                "catalog_package": page_catalog_rows.get(module, {}).get("package"),
            }
    page_package_mismatches = {
        module: {
            "expected_package": package,
            "catalog_package": page_catalog_rows.get(module, {}).get("package"),
        }
        for module, package in sorted(expected_page_catalog.items())
        if page_catalog_rows.get(module, {}).get("package") != package
    }
    included_rows_without_contract = {
        module: {
            "catalog_package": row.get("package"),
            "status": row.get("status"),
        }
        for module, row in sorted(page_catalog_rows.items())
        if _status_includes_agi_pages(row.get("status", ""))
        and module not in expected_page_catalog
    }
    checks.append(
        _check(
            "apps_pages_catalog_matches_page_contract",
            "Apps-pages docs catalog matches page contract",
            not missing_page_rows
            and not source_catalog_package_mismatches
            and not page_package_mismatches
            and not included_rows_without_contract,
            "apps-pages docs list every source bundle and match package split status",
            evidence=(str(APPS_PAGES_CATALOG_REL), "tools/package_split_contract.py"),
            details={
                "missing_source_rows": missing_page_rows,
                "source_package_mismatches": source_catalog_package_mismatches,
                "package_mismatches": page_package_mismatches,
                "included_rows_without_package_contract": included_rows_without_contract,
            },
        )
    )

    try:
        provider_modules = set(_agi_pages_public_modules(repo_root))
        provider_error = ""
    except Exception as exc:
        provider_modules = set()
        provider_error = str(exc)
    expected_provider_modules = set(expected_page_catalog)
    checks.append(
        _check(
            "agi_pages_provider_matches_page_bundle_contract",
            "agi-pages provider matches page-bundle contract",
            not provider_error and provider_modules == expected_provider_modules,
            "agi-pages provider exposes exactly the lightweight page-bundle contract",
            evidence=(str(AGI_PAGES_PROVIDER_REL), "tools/package_split_contract.py"),
            details={
                "error": provider_error,
                "missing_from_provider": sorted(expected_provider_modules - provider_modules),
                "extra_in_provider": sorted(provider_modules - expected_provider_modules),
            },
        )
    )

    checks.append(
        _check(
            "promoted_pypi_app_catalog_matches_package_split",
            "Promoted PyPI app catalog matches package split",
            promoted_package_names == pypi_promoted,
            "install UI/search catalog exposes the same promoted app packages as the release contract",
            evidence=("tools/package_split_contract.py", "src/agilab/pypi_app_packages.py"),
            details={
                "missing_from_pypi_catalog": sorted(promoted_package_names - pypi_promoted),
                "extra_in_pypi_catalog": sorted(pypi_promoted - promoted_package_names),
            },
        )
    )

    catalog_missing = sorted(package for package in package_specs if package not in agi_apps_rows)
    catalog_project_mismatch = {
        package: {
            "expected_project": package_to_project.get(package),
            "catalog_project": agi_apps_rows.get(package, {}).get("project"),
        }
        for package in sorted(set(package_specs) - set(catalog_missing))
        if agi_apps_rows.get(package, {}).get("project") != package_to_project.get(package)
    }
    checks.append(
        _check(
            "agi_apps_catalog_covers_app_packages",
            "agi-apps catalog covers app packages",
            not catalog_missing and not catalog_project_mismatch,
            "agi-apps catalog maps each app distribution to the expected project",
            evidence=(str(AGI_APPS_CATALOG_REL), "tools/package_split_contract.py"),
            details={
                "missing_distributions": catalog_missing,
                "project_mismatches": catalog_project_mismatch,
            },
        )
    )

    expected_public_rows: dict[str, tuple[str, str]] = {}
    for package, project in package_to_project.items():
        status = "PyPI app package" if package in promoted_package_names else "Release artifact"
        expected_public_rows[project] = (package, status)
    for project in sorted(builtin_projects):
        expected_public_rows.setdefault(project, ("None", "Source built-in"))
    public_mismatches = {
        project: {
            "expected": {"package": package, "status": status},
            "actual": {
                "package": public_rows.get(project, {}).get("package"),
                "status": public_rows.get(project, {}).get("status"),
            },
        }
        for project, (package, status) in sorted(expected_public_rows.items())
        if public_rows.get(project, {}).get("package") != package
        or public_rows.get(project, {}).get("status") != status
    }
    checks.append(
        _check(
            "public_app_catalog_matches_package_contract",
            "Public app catalog matches package contract",
            not public_mismatches,
            "public docs catalog lists every built-in app with the expected package/status",
            evidence=(str(PUBLIC_APP_CATALOG_REL), "tools/package_split_contract.py"),
            details={"mismatches": public_mismatches},
        )
    )
    return checks


def build_report(
    *,
    repo_root: Path = REPO_ROOT,
    package_split_module: Any | None = None,
    pypi_app_packages_module: Any | None = None,
    pypi_promoted_packages: Sequence[str] | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    project_paths = discover_builtin_projects(repo_root)
    checks: list[Check] = []
    checks.append(
        _check(
            "builtin_project_inventory",
            "Built-in project inventory",
            bool(project_paths) and len({path.name for path in project_paths}) == len(project_paths),
            "built-in project directories are discoverable and unique",
            evidence=(str(BUILTIN_APPS_REL),),
            details={"projects": [path.name for path in project_paths]},
        )
    )
    for project_path in project_paths:
        checks.extend(_project_checks(repo_root, project_path))
    checks.extend(
        _global_checks(
            repo_root,
            package_split_module=package_split_module,
            pypi_app_packages_module=pypi_app_packages_module,
            pypi_promoted_packages=pypi_promoted_packages,
        )
    )
    failed = [check for check in checks if check.status != "pass"]
    project_failures: dict[str, list[str]] = {}
    for check in failed:
        if ":" in check.id:
            project, _suffix = check.id.split(":", 1)
            project_failures.setdefault(project, []).append(check.id)
    return {
        "report": "AGILAB app contract matrix",
        "schema": SCHEMA,
        "status": "pass" if not failed else "fail",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "project_count": len(project_paths),
            "check_count": len(checks),
            "passed": len(checks) - len(failed),
            "failed": len(failed),
            "failed_projects": project_failures,
        },
        "checks": [check.as_dict() for check in checks],
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit AGILAB built-in app and PyPI app-package contract evidence."
    )
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output path.")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON.")
    parser.add_argument("--json", action="store_true", help="Alias for --compact.")
    parser.add_argument("--quiet", action="store_true", help="Do not print the JSON report to stdout.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    report = build_report()
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.quiet:
        return 0 if report["status"] == "pass" else 1
    if args.compact or args.json:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
