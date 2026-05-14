from __future__ import annotations

from pathlib import Path

from agi_env.app_provider_registry import (
    APP_PROVIDER_ENTRYPOINT_GROUP,
    InstalledAppProject,
    app_name_aliases,
    discover_installed_app_projects,
    resolve_app_runtime_target,
    installed_app_project_paths,
    resolve_installed_app_project,
)


class _EntryPoint:
    def __init__(self, name: str, value):
        self.name = name
        self._value = value

    def load(self):
        return self._value


class _EntryPoints(tuple):
    def select(self, *, group: str):
        if group != APP_PROVIDER_ENTRYPOINT_GROUP:
            return ()
        return self


def test_app_name_aliases_cover_slug_and_project_suffix() -> None:
    assert app_name_aliases("flight_telemetry") == (
        "flight_telemetry",
        "flight_telemetry_project",
        "flight",
        "flight_project",
    )
    assert app_name_aliases("flight-telemetry-project") == (
        "flight_telemetry_project",
        "flight_telemetry",
        "flight",
        "flight_project",
    )


def test_resolve_app_runtime_target_uses_explicit_project_metadata(tmp_path: Path) -> None:
    project = tmp_path / "flight_telemetry_project"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        "[project]\nname='flight_telemetry_project'\n\n[tool.agilab]\nruntime_target='flight'\n",
        encoding="utf-8",
    )

    assert resolve_app_runtime_target(project, "flight_telemetry_project") == "flight"
    assert resolve_app_runtime_target(None, "weather_forecast_project") == "weather_forecast"


def test_discover_installed_app_projects_loads_valid_entry_points(tmp_path: Path) -> None:
    flight_telemetry_project = tmp_path / "flight_telemetry_project"
    flight_telemetry_project.mkdir()
    (flight_telemetry_project / "pyproject.toml").write_text("[project]\nname='flight_telemetry_project'\n", encoding="utf-8")
    broken_project = tmp_path / "broken_project"
    broken_project.mkdir()

    def entry_points_fn():
        return _EntryPoints(
            [
                _EntryPoint("flight", lambda: flight_telemetry_project),
                _EntryPoint("broken", lambda: broken_project),
            ]
        )

    projects = discover_installed_app_projects(entry_points_fn=entry_points_fn)

    assert projects == (
        InstalledAppProject(name="flight_telemetry_project", project_root=flight_telemetry_project.resolve(), provider="flight"),
    )
    assert installed_app_project_paths(entry_points_fn=entry_points_fn) == (flight_telemetry_project.resolve(),)


def test_resolve_installed_app_project_accepts_slug_provider_and_project_name(tmp_path: Path) -> None:
    project = tmp_path / "mycode_project"
    project.mkdir()
    (project / "src").mkdir()
    (project / "src" / "app_settings.toml").write_text("", encoding="utf-8")
    installed = [InstalledAppProject(name="mycode_project", project_root=project, provider="mycode")]

    assert resolve_installed_app_project("mycode", projects=installed) == project
    assert resolve_installed_app_project("mycode_project", projects=installed) == project
    assert resolve_installed_app_project("other", projects=installed) is None
