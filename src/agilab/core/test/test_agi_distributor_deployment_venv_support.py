from __future__ import annotations

import os
from pathlib import Path

from agi_cluster.agi_distributor import deployment_venv_support


def _write_venv_python(
    project: Path,
    *,
    os_name: str = os.name,
    python_version: str | None = None,
) -> Path:
    python_path = deployment_venv_support.project_venv_python(project, os_name=os_name)
    python_path.parent.mkdir(parents=True, exist_ok=True)
    python_path.write_text("", encoding="utf-8")
    if python_version is not None:
        (project / ".venv" / "pyvenv.cfg").write_text(
            f"version = {python_version}\n",
            encoding="utf-8",
        )
    return python_path


def test_project_venv_python_uses_target_platform_layouts(tmp_path: Path) -> None:
    assert deployment_venv_support.project_venv_python(tmp_path, os_name="posix") == (
        tmp_path / ".venv" / "bin" / "python"
    )
    assert deployment_venv_support.project_venv_python(tmp_path, os_name="nt") == (
        tmp_path / ".venv" / "Scripts" / "python.exe"
    )


def test_project_venv_matches_checks_executable_and_requested_version(tmp_path: Path) -> None:
    assert deployment_venv_support.project_venv_matches(tmp_path, python_version="3.13") is False

    _write_venv_python(tmp_path, python_version="3.13.2")

    assert deployment_venv_support.project_venv_matches(tmp_path, python_version="3.13") is True
    assert deployment_venv_support.project_venv_matches(tmp_path, python_version="3.12") is False


def test_project_site_packages_dir_handles_windows_and_free_threaded_versions(tmp_path: Path) -> None:
    assert deployment_venv_support.project_site_packages_dir(tmp_path, os_name="nt") == (
        tmp_path / ".venv" / "Lib" / "site-packages"
    )
    assert deployment_venv_support.project_site_packages_dir(tmp_path, python_version="3.13t") == (
        tmp_path / ".venv" / "lib" / "python3.13t" / "site-packages"
    )


def test_project_site_packages_dir_prefers_existing_python_site_packages(tmp_path: Path) -> None:
    expected = tmp_path / ".venv" / "lib" / "python3.12" / "site-packages"
    expected.mkdir(parents=True)

    assert deployment_venv_support.project_site_packages_dir(tmp_path) == expected
