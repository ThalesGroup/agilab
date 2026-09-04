"""Build helpers for AGILAB app project distribution packages."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
from pathlib import Path


APP_PROJECT_SPECS: tuple[dict[str, str], ...] = (
    {
        "project": "mission_decision_project",
        "slug": "mission_decision",
        "distribution": "agi-app-mission-decision",
        "package": "agi_app_mission_decision",
    },
    {
        "project": "execution_pandas_project",
        "slug": "execution_pandas",
        "distribution": "agi-app-pandas-execution",
        "package": "agi_app_pandas_execution",
    },
    {
        "project": "execution_polars_project",
        "slug": "execution_polars",
        "distribution": "agi-app-polars-execution",
        "package": "agi_app_polars_execution",
    },
    {
        "project": "flight_telemetry_project",
        "slug": "flight_telemetry",
        "distribution": "agi-app-flight-telemetry",
        "package": "agi_app_flight_telemetry",
    },
    {
        "project": "multi_app_dag_project",
        "slug": "multi_app_dag",
        "distribution": "agi-app-multi-dag",
        "package": "agi_app_multi_dag",
    },
    {
        "project": "weather_forecast_project",
        "slug": "weather_forecast",
        "distribution": "agi-app-weather-forecast",
        "package": "agi_app_weather_forecast",
    },
    {
        "project": "sklearn_pipeline_project",
        "slug": "sklearn_pipeline",
        "distribution": "agi-app-sklearn-pipeline",
        "package": "agi_app_sklearn_pipeline",
    },
    {
        "project": "data_quality_gate_project",
        "slug": "data_quality_gate",
        "distribution": "agi-app-data-quality-gate",
        "package": "agi_app_data_quality_gate",
    },
    {
        "project": "pytorch_playground_project",
        "slug": "pytorch_playground",
        "distribution": "agi-app-pytorch-playground",
        "package": "agi_app_pytorch_playground",
    },
    {
        "project": "tescia_diagnostic_project",
        "slug": "tescia_diagnostic",
        "distribution": "agi-app-tescia-diagnostic",
        "package": "agi_app_tescia_diagnostic",
    },
    {
        "project": "uav_queue_project",
        "slug": "uav_queue",
        "distribution": "agi-app-uav-queue",
        "package": "agi_app_uav_queue",
    },
    {
        "project": "uav_relay_queue_project",
        "slug": "uav_relay_queue",
        "distribution": "agi-app-uav-relay-queue",
        "package": "agi_app_uav_relay_queue",
    },
)

BASE_BUILTIN_TEMPLATE_PROJECTS: tuple[str, ...] = ("minimal_app_project",)

_EXCLUDED_PAYLOAD_DIRS = {
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "Modules",
    "agilab",
    "build",
    "dist",
    "notebooks",
    "test",
}
_EXCLUDED_PAYLOAD_FILES = {".coverage", ".DS_Store", ".gitignore", ".lock", "uv.lock"}
_EXCLUDED_PAYLOAD_SUFFIXES = {".c", ".pid", ".pyc", ".pyo", ".pyx", ".so"}


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


def _is_link_like(path: Path) -> bool:
    """Return whether ``path`` can redirect traversal outside the payload tree."""
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction is not None and is_junction())


def _require_unlinked_tree_root(path: Path, *, label: str) -> None:
    if _is_link_like(path):
        raise ValueError(f"{label} must not be a symlink or junction: {path}")


def _copy_stable_regular_file(source: Path, destination: Path, *, label: str) -> None:
    try:
        path_stat = source.stat(follow_symlinks=False)
    except OSError as exc:
        raise ValueError(f"{label} must be a stable regular file: {source}") from exc
    if not stat.S_ISREG(path_stat.st_mode):
        raise ValueError(f"{label} must be a stable regular file: {source}")

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(source, flags)
    except OSError as exc:
        raise ValueError(f"{label} must be a stable regular file: {source}") from exc
    with os.fdopen(descriptor, "rb") as source_handle:
        opened_stat = os.fstat(source_handle.fileno())
        if not stat.S_ISREG(opened_stat.st_mode) or not os.path.samestat(
            path_stat, opened_stat
        ):
            raise ValueError(f"{label} changed before it could be copied: {source}")
        with destination.open("wb") as destination_handle:
            shutil.copyfileobj(source_handle, destination_handle)
    destination.chmod(stat.S_IMODE(opened_stat.st_mode))


def _ignore_payload_artifacts(directory: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        path = Path(directory) / name
        if _is_link_like(path):
            ignored.add(name)
            continue
        if path.is_dir() and (name in _EXCLUDED_PAYLOAD_DIRS or name.endswith(".egg-info")):
            ignored.add(name)
            continue
        if (
            name in _EXCLUDED_PAYLOAD_FILES
            or name.startswith(".coverage.")
            or path.suffix in _EXCLUDED_PAYLOAD_SUFFIXES
        ):
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
    _require_unlinked_tree_root(source_root, label="App project payload root")
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

    _require_unlinked_tree_root(apps_source_root, label="Apps payload root")
    apps_target_root.mkdir(parents=True, exist_ok=True)
    for file_name in ("README.md", "install.py"):
        source = apps_source_root / file_name
        if source.exists():
            _copy_stable_regular_file(
                source,
                apps_target_root / file_name,
                label="App payload file",
            )

    builtin_target_root = apps_target_root / "builtin"
    for project_name in BASE_BUILTIN_TEMPLATE_PROJECTS:
        source = apps_source_root / "builtin" / project_name
        if not source.exists():
            continue
        _require_unlinked_tree_root(source, label=f"Built-in app payload root {project_name}")
        destination = builtin_target_root / project_name
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination, ignore=_ignore_payload_artifacts)
        _sanitize_pyprojects(destination)

    if examples_source_root.exists():
        _require_unlinked_tree_root(examples_source_root, label="Examples payload root")
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
