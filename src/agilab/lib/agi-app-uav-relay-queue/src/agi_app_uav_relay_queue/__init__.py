"""Installed AGILAB app project provider for uav_relay_queue_project."""

from __future__ import annotations

from pathlib import Path

APP_SLUG = 'uav_relay_queue'
PROJECT_NAME = 'uav_relay_queue_project'
PACKAGE_NAME = 'agi-app-uav-relay-queue'


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
