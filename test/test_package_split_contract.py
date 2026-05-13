from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = REPO_ROOT / "tools"
sys.path.insert(0, str(TOOLS_ROOT))

from package_split_contract import (
    APP_PROJECT_PACKAGE_SPECS,
    ASSET_PACKAGE_NAMES,
    EXACT_INTERNAL_DEPENDENCY_PACKAGE_NAMES,
    LIBRARY_PACKAGE_CONTRACTS,
    PACKAGE_CONTRACTS,
    PACKAGE_NAMES,
    ROOT_EXTRA_INTERNAL_REQUIREMENTS,
    UMBRELLA_PACKAGE_CONTRACT,
    WHEEL_ONLY_PACKAGE_NAMES,
    package_by_name,
    project_path,
    pyproject_path,
)


def _load_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _requirements(pyproject: Path, section: str) -> list[Requirement]:
    data = _load_toml(pyproject)
    project = data.get("project", {})
    if section == "dependencies":
        dependencies = project.get("dependencies", [])
    else:
        dependencies = project.get("optional-dependencies", {}).get(section, [])
    return [Requirement(dependency) for dependency in dependencies]


def _requirement_names(pyproject: Path, section: str) -> set[str]:
    return {requirement.name.lower() for requirement in _requirements(pyproject, section)}


def _exact_pin(requirement: Requirement) -> str | None:
    for specifier in requirement.specifier:
        if specifier.operator == "==":
            return specifier.version
    return None


def _has_lower_bound(requirement: Requirement) -> bool:
    return any(specifier.operator in {">=", "~="} for specifier in requirement.specifier)


def _load_pypi_publish():
    module_path = REPO_ROOT / "tools/pypi_publish.py"
    spec = importlib.util.spec_from_file_location("pypi_publish_contract_test_module", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_release_plan():
    module_path = REPO_ROOT / "tools/release_plan.py"
    spec = importlib.util.spec_from_file_location("release_plan_contract_test_module", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_package_contract_matches_pyproject_names_paths_and_roles() -> None:
    for package in PACKAGE_CONTRACTS:
        project_dir = project_path(REPO_ROOT, package)
        pyproject = pyproject_path(REPO_ROOT, package)
        assert project_dir.exists(), package.name
        assert pyproject.exists(), package.name

        data = _load_toml(pyproject)
        assert data["project"]["name"] == package.name
        assert data["project"]["version"]


def test_internal_dependencies_follow_bundle_or_asset_version_policy() -> None:
    versions = {
        package.name: _load_toml(pyproject_path(REPO_ROOT, package))["project"]["version"]
        for package in PACKAGE_CONTRACTS
    }
    internal_names = set(PACKAGE_NAMES)
    violations: list[str] = []

    for package in PACKAGE_CONTRACTS:
        pyproject = pyproject_path(REPO_ROOT, package)
        data = _load_toml(pyproject)
        project = data.get("project", {})
        dependency_sections = {"dependencies": project.get("dependencies", [])}
        dependency_sections.update(project.get("optional-dependencies", {}))

        for section, dependencies in dependency_sections.items():
            for dependency in dependencies:
                requirement = Requirement(dependency)
                if requirement.name.lower() not in internal_names:
                    continue
                exact_version = _exact_pin(requirement)
                if package.name in ASSET_PACKAGE_NAMES:
                    if exact_version is not None:
                        violations.append(f"{package.name}:{section}:{requirement}: asset payload must not exact-pin internal packages")
                    if not _has_lower_bound(requirement):
                        violations.append(f"{package.name}:{section}:{requirement}: asset payload must declare a compatible runtime floor")
                    continue

                expected_version = versions[requirement.name.lower()]
                if package.name not in EXACT_INTERNAL_DEPENDENCY_PACKAGE_NAMES:
                    violations.append(f"{package.name}: missing version policy")
                elif exact_version != expected_version:
                    violations.append(
                        f"{package.name}:{section}:{requirement}: expected {requirement.name}=={expected_version}"
                    )

    assert violations == []


def test_root_extras_and_uv_sources_match_package_split_contract() -> None:
    root_pyproject = REPO_ROOT / "pyproject.toml"
    base_internal = ROOT_EXTRA_INTERNAL_REQUIREMENTS["dependencies"]
    assert set(base_internal) <= _requirement_names(root_pyproject, "dependencies")

    base_names = _requirement_names(root_pyproject, "dependencies")
    optional_internal = {
        name
        for extra_name, names in ROOT_EXTRA_INTERNAL_REQUIREMENTS.items()
        if extra_name != "dependencies"
        for name in names
    }
    assert base_names.isdisjoint(optional_internal)

    for extra, package_names in ROOT_EXTRA_INTERNAL_REQUIREMENTS.items():
        if extra == "dependencies":
            continue
        requirement_names = _requirement_names(root_pyproject, extra)
        assert set(package_names) <= requirement_names, extra

    assert _requirement_names(root_pyproject, "pages") == {"agi-pages"}

    sources = _load_toml(root_pyproject).get("tool", {}).get("uv", {}).get("sources", {})
    for package in LIBRARY_PACKAGE_CONTRACTS:
        source = sources.get(package.name)
        assert source is not None, package.name
        assert source.get("editable") is True, package.name
        assert source.get("path", "").lstrip("./") == package.project, package.name


def test_publish_tool_uses_the_same_package_split_contract() -> None:
    module = _load_pypi_publish()

    assert [name for name, *_ in module.publishable_libs()] == [package.name for package in LIBRARY_PACKAGE_CONTRACTS]
    assert module.ALL_PACKAGE_NAMES == list(PACKAGE_NAMES)
    assert module.WHEEL_ONLY_PACKAGES == set(WHEEL_ONLY_PACKAGE_NAMES)

    for package_name in WHEEL_ONLY_PACKAGE_NAMES:
        assert module.effective_dist_kind(package_name, "both") == "wheel"
    assert module.effective_dist_kind("agilab", "both") == "both"


def test_package_lookup_rejects_unknown_package() -> None:
    with pytest.raises(KeyError, match="not-a-public-package"):
        package_by_name("not-a-public-package")


def test_src_layout_packages_do_not_publish_top_level_init_modules() -> None:
    leaking_src_roots = [
        package.name
        for package in LIBRARY_PACKAGE_CONTRACTS
        if (project_path(REPO_ROOT, package) / "src" / "__init__.py").exists()
    ]

    assert leaking_src_roots == []


def test_workflow_and_docs_cover_the_same_package_split() -> None:
    workflow = (REPO_ROOT / ".github/workflows/pypi-publish.yaml").read_text(encoding="utf-8")
    docs = (REPO_ROOT / "docs/source/package-publishing-policy.rst").read_text(encoding="utf-8")
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    release_plan = _load_release_plan()

    assert "tools/release_plan.py" in workflow
    assert "include: ${{ fromJSON(needs.release-plan.outputs.library_matrix) }}" in workflow
    assert workflow.count("          - package: ") == 0
    assert release_plan.library_matrix() == [
        {
            "package": package.name,
            "project": package.project,
            "dist": package.dist,
            "pypi_project": package.name,
            "pypi_environment": package.pypi_environment,
            "artifact_policy": package.artifact_policy,
        }
        for package in LIBRARY_PACKAGE_CONTRACTS
    ]

    assert UMBRELLA_PACKAGE_CONTRACT.pypi_environment in workflow

    for package_name in PACKAGE_NAMES:
        assert f"``{package_name}``" in docs or f"`{package_name}`" in readme

    for package_name in WHEEL_ONLY_PACKAGE_NAMES:
        assert f"``{package_name}`` is published to PyPI as a wheel" in docs
        assert package_by_name(package_name).artifact_policy == "wheel-only"
    assert "agi-pages" not in WHEEL_ONLY_PACKAGE_NAMES
    assert "agi-apps" not in WHEEL_ONLY_PACKAGE_NAMES
    assert package_by_name("agi-pages").artifact_policy == "wheel+sdist"
    assert package_by_name("agi-apps").artifact_policy == "wheel+sdist"
    assert "``agi-pages`` wheel is published to PyPI as a\nwheel-only asset" not in docs


def test_app_project_package_contracts_match_declared_project_packages() -> None:
    app_project_contracts = [
        (package.name, package.project)
        for package in LIBRARY_PACKAGE_CONTRACTS
        if package.role == "app-project"
    ]

    assert app_project_contracts == list(APP_PROJECT_PACKAGE_SPECS)
    assert package_by_name("agi-core").role == "runtime-bundle"
    assert app_project_contracts
    package_names = [package.name for package in LIBRARY_PACKAGE_CONTRACTS]
    assert max(package_names.index(name) for name, _ in app_project_contracts) < package_names.index("agi-apps")
