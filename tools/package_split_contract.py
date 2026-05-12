#!/usr/bin/env python3
"""Single source of truth for the public AGILAB package split."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PackageContract:
    name: str
    role: str
    project: str
    dist: str
    pypi_environment: str
    artifact_policy: str = "wheel+sdist"

    @property
    def pyproject(self) -> str:
        if self.project == ".":
            return "pyproject.toml"
        return f"{self.project}/pyproject.toml"


PACKAGE_CONTRACTS: tuple[PackageContract, ...] = (
    PackageContract(
        name="agi-env",
        role="core",
        project="src/agilab/core/agi-env",
        dist="src/agilab/core/agi-env/dist",
        pypi_environment="pypi-agi-env",
    ),
    PackageContract(
        name="agi-gui",
        role="ui-support",
        project="src/agilab/lib/agi-gui",
        dist="src/agilab/lib/agi-gui/dist",
        pypi_environment="pypi-agi-gui",
    ),
    PackageContract(
        name="agi-pages",
        role="page-assets",
        project="src/agilab/lib/agi-pages",
        dist="src/agilab/lib/agi-pages/dist",
        pypi_environment="pypi-agi-pages",
        artifact_policy="wheel-only",
    ),
    PackageContract(
        name="agi-node",
        role="core",
        project="src/agilab/core/agi-node",
        dist="src/agilab/core/agi-node/dist",
        pypi_environment="pypi-agi-node",
    ),
    PackageContract(
        name="agi-cluster",
        role="core",
        project="src/agilab/core/agi-cluster",
        dist="src/agilab/core/agi-cluster/dist",
        pypi_environment="pypi-agi-cluster",
    ),
    PackageContract(
        name="agi-core",
        role="core",
        project="src/agilab/core/agi-core",
        dist="src/agilab/core/agi-core/dist",
        pypi_environment="pypi-agi-core",
    ),
    PackageContract(
        name="agi-apps",
        role="app-assets",
        project="src/agilab/lib/agi-apps",
        dist="src/agilab/lib/agi-apps/dist",
        pypi_environment="pypi-agi-apps",
        artifact_policy="wheel-only",
    ),
    PackageContract(
        name="agilab",
        role="umbrella",
        project=".",
        dist="dist",
        pypi_environment="pypi-agilab",
    ),
)

LIBRARY_PACKAGE_CONTRACTS: tuple[PackageContract, ...] = tuple(
    package for package in PACKAGE_CONTRACTS if package.role != "umbrella"
)
UMBRELLA_PACKAGE_CONTRACT: PackageContract = next(
    package for package in PACKAGE_CONTRACTS if package.role == "umbrella"
)

PACKAGE_NAMES: tuple[str, ...] = tuple(package.name for package in PACKAGE_CONTRACTS)
LIBRARY_PACKAGE_NAMES: tuple[str, ...] = tuple(package.name for package in LIBRARY_PACKAGE_CONTRACTS)
WHEEL_ONLY_PACKAGE_NAMES: tuple[str, ...] = tuple(
    package.name for package in PACKAGE_CONTRACTS if package.artifact_policy == "wheel-only"
)

CORE_PACKAGE_NAMES: tuple[str, ...] = tuple(
    package.name for package in LIBRARY_PACKAGE_CONTRACTS if package.role == "core"
)
PAGE_PACKAGE_NAMES: tuple[str, ...] = tuple(
    package.name for package in LIBRARY_PACKAGE_CONTRACTS if package.role in {"ui-support", "page-assets"}
)
APP_PACKAGE_NAMES: tuple[str, ...] = tuple(
    package.name for package in LIBRARY_PACKAGE_CONTRACTS if package.role == "app-assets"
)

ROOT_EXTRA_INTERNAL_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "dependencies": ("agi-core",),
    "ui": ("agi-apps", "agi-pages", "agi-gui"),
    "examples": ("agi-apps",),
    "pages": ("agi-pages",),
}


def package_by_name(name: str) -> PackageContract:
    for package in PACKAGE_CONTRACTS:
        if package.name == name:
            return package
    raise KeyError(name)


def project_path(repo_root: Path, package: PackageContract) -> Path:
    return repo_root if package.project == "." else repo_root / package.project


def pyproject_path(repo_root: Path, package: PackageContract) -> Path:
    return repo_root / package.pyproject
