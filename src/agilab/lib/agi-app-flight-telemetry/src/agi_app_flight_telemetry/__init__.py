"""Installed AGILAB app project provider for flight_telemetry_project."""

from __future__ import annotations

from pathlib import Path

APP_SLUG = 'flight_telemetry'
PROJECT_NAME = 'flight_telemetry_project'
PACKAGE_NAME = 'agi-app-flight-telemetry'


def package_root() -> Path:
    return Path(__file__).resolve().parent


def project_root() -> Path:
    packaged_root = package_root() / "project" / PROJECT_NAME
    if packaged_root.exists():
        return packaged_root
    source_root = Path(__file__).resolve().parents[4] / "apps" / "builtin" / PROJECT_NAME
    return source_root if source_root.exists() else packaged_root


def metadata() -> dict[str, str]:
    return {
        "slug": APP_SLUG,
        "project": PROJECT_NAME,
        "package": PACKAGE_NAME,
        "project_root": str(project_root()),
    }


__all__ = ["APP_SLUG", "PACKAGE_NAME", "PROJECT_NAME", "metadata", "package_root", "project_root"]
