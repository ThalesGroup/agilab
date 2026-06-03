"""Installed AGILAB app project provider for tescia_diagnostic_project."""

from __future__ import annotations

from pathlib import Path

APP_SLUG = 'tescia_diagnostic'
PROJECT_NAME = 'tescia_diagnostic_project'
PACKAGE_NAME = 'agi-app-tescia-diagnostic'


def package_root() -> Path:
    return Path(__file__).resolve().parent


def project_root() -> Path:
    source_root = Path(__file__).resolve().parents[4] / "apps" / "builtin" / PROJECT_NAME
    if source_root.exists():
        return source_root
    return package_root() / "project" / PROJECT_NAME


def metadata() -> dict[str, str]:
    return {
        "slug": APP_SLUG,
        "project": PROJECT_NAME,
        "package": PACKAGE_NAME,
        "project_root": str(project_root()),
    }


__all__ = ["APP_SLUG", "PACKAGE_NAME", "PROJECT_NAME", "metadata", "package_root", "project_root"]
