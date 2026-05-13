"""Build helpers for AGILAB app project distribution packages."""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path


APP_PROJECT_SPECS: tuple[dict[str, str], ...] = (
    {
        "project": "data_io_2026_project",
        "slug": "data_io_2026",
        "distribution": "agi-app-data-io-2026-project",
        "package": "agi_app_data_io_2026_project",
    },
    {
        "project": "execution_pandas_project",
        "slug": "execution_pandas",
        "distribution": "agi-app-execution-pandas-project",
        "package": "agi_app_execution_pandas_project",
    },
    {
        "project": "execution_polars_project",
        "slug": "execution_polars",
        "distribution": "agi-app-execution-polars-project",
        "package": "agi_app_execution_polars_project",
    },
    {
        "project": "flight_project",
        "slug": "flight",
        "distribution": "agi-app-flight-project",
        "package": "agi_app_flight_project",
    },
    {
        "project": "global_dag_project",
        "slug": "global_dag",
        "distribution": "agi-app-global-dag-project",
        "package": "agi_app_global_dag_project",
    },
    {
        "project": "meteo_forecast_project",
        "slug": "meteo_forecast",
        "distribution": "agi-app-meteo-forecast-project",
        "package": "agi_app_meteo_forecast_project",
    },
    {
        "project": "mycode_project",
        "slug": "mycode",
        "distribution": "agi-app-mycode-project",
        "package": "agi_app_mycode_project",
    },
    {
        "project": "tescia_diagnostic_project",
        "slug": "tescia_diagnostic",
        "distribution": "agi-app-tescia-diagnostic-project",
        "package": "agi_app_tescia_diagnostic_project",
    },
    {
        "project": "uav_queue_project",
        "slug": "uav_queue",
        "distribution": "agi-app-uav-queue-project",
        "package": "agi_app_uav_queue_project",
    },
    {
        "project": "uav_relay_queue_project",
        "slug": "uav_relay_queue",
        "distribution": "agi-app-uav-relay-queue-project",
        "package": "agi_app_uav_relay_queue_project",
    },
)

_EXCLUDED_PAYLOAD_DIRS = {
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "Modules",
    "build",
    "dist",
    "notebooks",
    "test",
}
_EXCLUDED_PAYLOAD_FILES = {".DS_Store", ".gitignore", ".lock", "uv.lock"}
_EXCLUDED_PAYLOAD_SUFFIXES = {".c", ".pyc", ".pyo", ".pyx", ".so"}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def repo_agilab_root() -> Path:
    return repo_root() / "src" / "agilab"


def app_project_specs() -> tuple[dict[str, str], ...]:
    return APP_PROJECT_SPECS


def app_project_spec(project_name: str) -> dict[str, str]:
    for spec in APP_PROJECT_SPECS:
        if spec["project"] == project_name:
            return spec
    raise KeyError(project_name)


def _ignore_payload_artifacts(directory: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        path = Path(directory) / name
        if path.is_dir() and (name in _EXCLUDED_PAYLOAD_DIRS or name.endswith(".egg-info")):
            ignored.add(name)
            continue
        if name in _EXCLUDED_PAYLOAD_FILES or path.suffix in _EXCLUDED_PAYLOAD_SUFFIXES:
            ignored.add(name)
    return ignored


class _NoopSanitizer:
    @staticmethod
    def strip_packaged_core_uv_sources(text: str) -> str:
        return text


def _load_sanitizer():
    module_path = repo_root() / "tools" / "package_wheel_sanitizer.py"
    if not module_path.exists():
        return _NoopSanitizer
    spec = importlib.util.spec_from_file_location("agilab_app_package_wheel_sanitizer", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load package wheel sanitizer from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sanitize_pyprojects(payload_root: Path) -> list[Path]:
    sanitizer = _load_sanitizer()
    changed: list[Path] = []
    for pyproject_path in sorted(payload_root.rglob("pyproject.toml")):
        original = pyproject_path.read_text(encoding="utf-8")
        sanitized = sanitizer.strip_packaged_core_uv_sources(original)
        if sanitized == original:
            continue
        pyproject_path.write_text(sanitized, encoding="utf-8")
        changed.append(pyproject_path)
    return changed


def copy_app_project_payload(project_name: str, target_root: Path) -> list[Path]:
    """Copy one built-in app project into a package-local payload root."""

    source_root = repo_agilab_root() / "apps" / "builtin" / project_name
    if not source_root.exists():
        return []
    target_root.mkdir(parents=True, exist_ok=True)
    destination = target_root / project_name
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source_root, destination, ignore=_ignore_payload_artifacts)
    return _sanitize_pyprojects(destination)


def copy_agi_apps_umbrella_payload(target_root: Path) -> None:
    """Copy lightweight installer/example payload for the ``agi-apps`` umbrella."""

    apps_source_root = repo_agilab_root() / "apps"
    examples_source_root = repo_agilab_root() / "examples"
    apps_target_root = target_root / "agilab" / "apps"
    examples_target_root = target_root / "agilab" / "examples"

    apps_target_root.mkdir(parents=True, exist_ok=True)
    for file_name in ("README.md", "install.py"):
        source = apps_source_root / file_name
        if source.exists():
            shutil.copy2(source, apps_target_root / file_name)

    if examples_source_root.exists():
        if examples_target_root.exists():
            shutil.rmtree(examples_target_root)
        shutil.copytree(
            examples_source_root,
            examples_target_root,
            ignore=_ignore_payload_artifacts,
        )


def write_agi_apps_catalog(target_package_root: Path) -> None:
    target_package_root.mkdir(parents=True, exist_ok=True)
    catalog_path = target_package_root / "catalog.json"
    catalog_path.write_text(json.dumps(APP_PROJECT_SPECS, indent=2) + "\n", encoding="utf-8")
