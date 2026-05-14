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
    ("agi-app-mission-decision", "src/agilab/lib/agi-app-mission-decision"),
    ("agi-app-pandas-execution", "src/agilab/lib/agi-app-pandas-execution"),
    ("agi-app-polars-execution", "src/agilab/lib/agi-app-polars-execution"),
    ("agi-app-flight-telemetry", "src/agilab/lib/agi-app-flight-telemetry"),
    ("agi-app-global-dag", "src/agilab/lib/agi-app-global-dag"),
    ("agi-app-weather-forecast", "src/agilab/lib/agi-app-weather-forecast"),
    ("agi-app-tescia-diagnostic-project", "src/agilab/lib/agi-app-tescia-diagnostic-project"),
    ("agi-app-uav-queue-project", "src/agilab/lib/agi-app-uav-queue-project"),
    ("agi-app-uav-relay-queue", "src/agilab/lib/agi-app-uav-relay-queue"),
)

PROMOTED_APP_PROJECT_PACKAGE_NAMES: tuple[str, ...] = (
    "agi-app-mission-decision",
    "agi-app-pandas-execution",
    "agi-app-polars-execution",
    "agi-app-flight-telemetry",
    "agi-app-global-dag",
    "agi-app-weather-forecast",
    "agi-app-uav-relay-queue",
)


PAGE_BUNDLE_PACKAGE_SPECS: tuple[tuple[str, str], ...] = (
    ("agi-page-simplex-map", "src/agilab/apps-pages/view_barycentric"),
    ("agi-page-decision-evidence", "src/agilab/apps-pages/view_data_io_decision"),
    ("agi-page-timeseries-forecast", "src/agilab/apps-pages/view_forecast_analysis"),
    ("agi-page-inference-report", "src/agilab/apps-pages/view_inference_analysis"),
    ("agi-page-geospatial-map", "src/agilab/apps-pages/view_maps"),
    ("agi-page-geospatial-3d", "src/agilab/apps-pages/view_maps_3d"),
    ("agi-page-network-map", "src/agilab/apps-pages/view_maps_network"),
    ("agi-page-queue-health", "src/agilab/apps-pages/view_queue_resilience"),
    ("agi-page-relay-health", "src/agilab/apps-pages/view_relay_resilience"),
    ("agi-page-promotion-gate", "src/agilab/apps-pages/view_release_decision"),
    ("agi-page-feature-attribution", "src/agilab/apps-pages/view_shap_explanation"),
    ("agi-page-training-report", "src/agilab/apps-pages/view_training_analysis"),
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
