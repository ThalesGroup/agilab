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


APP_PROJECT_PACKAGE_SPECS: tuple[tuple[str, str], ...] = (
    ("agi-app-data-io-2026-project", "src/agilab/lib/agi-app-data-io-2026-project"),
    ("agi-app-execution-pandas-project", "src/agilab/lib/agi-app-execution-pandas-project"),
    ("agi-app-execution-polars-project", "src/agilab/lib/agi-app-execution-polars-project"),
    ("agi-app-flight-project", "src/agilab/lib/agi-app-flight-project"),
    ("agi-app-global-dag-project", "src/agilab/lib/agi-app-global-dag-project"),
    ("agi-app-meteo-forecast-project", "src/agilab/lib/agi-app-meteo-forecast-project"),
    ("agi-app-mycode-project", "src/agilab/lib/agi-app-mycode-project"),
    ("agi-app-tescia-diagnostic-project", "src/agilab/lib/agi-app-tescia-diagnostic-project"),
    ("agi-app-uav-queue-project", "src/agilab/lib/agi-app-uav-queue-project"),
    ("agi-app-uav-relay-queue-project", "src/agilab/lib/agi-app-uav-relay-queue-project"),
)


PAGE_BUNDLE_PACKAGE_SPECS: tuple[tuple[str, str], ...] = (
    ("view-barycentric-graph", "src/agilab/apps-pages/view_barycentric"),
    ("view-data-io-decision", "src/agilab/apps-pages/view_data_io_decision"),
    ("view-forecast-analysis", "src/agilab/apps-pages/view_forecast_analysis"),
    ("view-inference-analysis", "src/agilab/apps-pages/view_inference_analysis"),
    ("view-maps", "src/agilab/apps-pages/view_maps"),
    ("view-maps-3d", "src/agilab/apps-pages/view_maps_3d"),
    ("view-maps-network", "src/agilab/apps-pages/view_maps_network"),
    ("view-queue-resilience", "src/agilab/apps-pages/view_queue_resilience"),
    ("view-relay-resilience", "src/agilab/apps-pages/view_relay_resilience"),
    ("view-release-decision", "src/agilab/apps-pages/view_release_decision"),
    ("view-training-analysis", "src/agilab/apps-pages/view_training_analysis"),
)


PACKAGE_CONTRACTS: tuple[PackageContract, ...] = (
    PackageContract(
        name="agi-env",
        role="runtime-component",
        project="src/agilab/core/agi-env",
        dist="src/agilab/core/agi-env/dist",
        pypi_environment="pypi-agi-env",
    ),
    PackageContract(
        name="agi-gui",
        role="ui-component",
        project="src/agilab/lib/agi-gui",
        dist="src/agilab/lib/agi-gui/dist",
        pypi_environment="pypi-agi-gui",
    ),
    *(
        PackageContract(
            name=name,
            role="page-bundle",
            project=project,
            dist=f"{project}/dist",
            pypi_environment=f"pypi-{name}",
        )
        for name, project in PAGE_BUNDLE_PACKAGE_SPECS
    ),
    PackageContract(
        name="agi-pages",
        role="page-umbrella",
        project="src/agilab/lib/agi-pages",
        dist="src/agilab/lib/agi-pages/dist",
        pypi_environment="pypi-agi-pages",
    ),
    PackageContract(
        name="agi-node",
        role="runtime-component",
        project="src/agilab/core/agi-node",
        dist="src/agilab/core/agi-node/dist",
        pypi_environment="pypi-agi-node",
    ),
    PackageContract(
        name="agi-cluster",
        role="runtime-component",
        project="src/agilab/core/agi-cluster",
        dist="src/agilab/core/agi-cluster/dist",
        pypi_environment="pypi-agi-cluster",
    ),
    PackageContract(
        name="agi-core",
        role="runtime-bundle",
        project="src/agilab/core/agi-core",
        dist="src/agilab/core/agi-core/dist",
        pypi_environment="pypi-agi-core",
    ),
    *(
        PackageContract(
            name=name,
            role="app-project",
            project=project,
            dist=f"{project}/dist",
            pypi_environment=f"pypi-{name}",
        )
        for name, project in APP_PROJECT_PACKAGE_SPECS
    ),
    PackageContract(
        name="agi-apps",
        role="app-umbrella",
        project="src/agilab/lib/agi-apps",
        dist="src/agilab/lib/agi-apps/dist",
        pypi_environment="pypi-agi-apps",
    ),
    PackageContract(
        name="agilab",
        role="top-level-bundle",
        project=".",
        dist="dist",
        pypi_environment="pypi-agilab",
    ),
)

LIBRARY_PACKAGE_CONTRACTS: tuple[PackageContract, ...] = tuple(
    package for package in PACKAGE_CONTRACTS if package.role != "top-level-bundle"
)
UMBRELLA_PACKAGE_CONTRACT: PackageContract = next(
    package for package in PACKAGE_CONTRACTS if package.role == "top-level-bundle"
)

PACKAGE_NAMES: tuple[str, ...] = tuple(package.name for package in PACKAGE_CONTRACTS)
LIBRARY_PACKAGE_NAMES: tuple[str, ...] = tuple(package.name for package in LIBRARY_PACKAGE_CONTRACTS)
WHEEL_ONLY_PACKAGE_NAMES: tuple[str, ...] = tuple(
    package.name for package in PACKAGE_CONTRACTS if package.artifact_policy == "wheel-only"
)

CORE_PACKAGE_NAMES: tuple[str, ...] = tuple(
    package.name
    for package in LIBRARY_PACKAGE_CONTRACTS
    if package.role in {"runtime-component", "runtime-bundle"}
)
PAGE_PACKAGE_NAMES: tuple[str, ...] = tuple(
    package.name
    for package in LIBRARY_PACKAGE_CONTRACTS
    if package.role in {"ui-component", "page-bundle", "page-umbrella"}
)
APP_PACKAGE_NAMES: tuple[str, ...] = tuple(
    package.name
    for package in LIBRARY_PACKAGE_CONTRACTS
    if package.role in {"app-project", "app-umbrella"}
)
ASSET_PACKAGE_NAMES: tuple[str, ...] = tuple(
    package.name
    for package in LIBRARY_PACKAGE_CONTRACTS
    if package.role in {"app-project", "page-bundle"}
)
BUNDLE_PACKAGE_NAMES: tuple[str, ...] = tuple(
    package.name
    for package in PACKAGE_CONTRACTS
    if package.role
    in {"runtime-bundle", "page-umbrella", "app-umbrella", "top-level-bundle"}
)
EXACT_INTERNAL_DEPENDENCY_PACKAGE_NAMES: tuple[str, ...] = tuple(
    package.name
    for package in PACKAGE_CONTRACTS
    if package.name not in ASSET_PACKAGE_NAMES
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
