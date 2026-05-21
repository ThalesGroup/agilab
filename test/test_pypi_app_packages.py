from __future__ import annotations

import importlib.util
import io
import json
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest


MODULE_PATH = Path("src/agilab/pypi_app_packages.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("agilab_pypi_app_packages_tests", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Response:
    def __init__(self, payload: bytes, *, headers: dict[str, str] | None = None):
        self._payload = payload
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, *_args):
        return self._payload


def _wheel_bytes(entry_points: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as wheel:
        wheel.writestr("demo-1.0.0.dist-info/entry_points.txt", entry_points)
    return buffer.getvalue()


def test_requirement_normalization_commands_and_catalog_search():
    module = _load_module()

    assert module.normalize_pypi_app_requirement(" AGI-APP-Weather_Forecast>=2026.5,<2027 ") == (
        "agi-app-weather-forecast>=2026.5,<2027"
    )
    assert module.pypi_app_package_name("agi-app-weather-forecast==2026.5.18") == "agi-app-weather-forecast"
    assert module.search_promoted_pypi_app_catalog("weather") == ("agi-app-weather-forecast",)
    assert module.search_promoted_pypi_app_catalog("tescia") == ("agi-app-tescia-diagnostic",)
    assert module.pypi_app_install_command(
        "agi-app-weather-forecast",
        python_executable="/tmp/python",
        uv_executable="/tmp/uv",
    ) == (
        "/tmp/uv",
        "--preview-features",
        "extra-build-dependencies",
        "pip",
        "install",
        "--python",
        "/tmp/python",
        "--upgrade",
        "agi-app-weather-forecast",
    )
    assert module.pypi_app_uninstall_command(
        "agi-app-weather-forecast",
        python_executable="/tmp/python",
        uv_executable="/tmp/uv",
    )[-2:] == ("-y", "agi-app-weather-forecast")

    for bad_value in ("", "requests", "agi-page-geospatial-map", "agi-app-demo @ https://example.test/x"):
        with pytest.raises(ValueError):
            module.normalize_pypi_app_requirement(bad_value)


def test_fetch_metadata_and_preflight_reads_wheel_entry_points(monkeypatch):
    module = _load_module()
    wheel = _wheel_bytes("[agilab.apps]\nweather_forecast = agi_app_weather_forecast:project_root\n")
    payload = {
        "info": {
            "version": "2026.5.18",
            "summary": "Weather app",
            "requires_python": ">=3.11",
            "requires_dist": ["agi-core>=2026.05.13,<2027.0"],
            "package_url": "https://pypi.org/project/agi-app-weather-forecast/",
            "maintainer": "AGILAB",
        },
        "releases": {
            "2026.5.18": [
                {
                    "packagetype": "bdist_wheel",
                    "url": "https://files.pythonhosted.org/weather.whl",
                    "digests": {"sha256": "abc"},
                    "provenance": {"available": True},
                },
                {"packagetype": "sdist", "digests": {"sha256": "def"}},
            ]
        },
    }

    def opener(request, **_kwargs):
        url = request.full_url
        if url.endswith("/json"):
            return _Response(json.dumps(payload).encode("utf-8"))
        if url.endswith(".whl"):
            return _Response(wheel, headers={"Content-Length": str(len(wheel))})
        raise AssertionError(url)

    monkeypatch.setattr(module.importlib_metadata, "version", lambda name: "2026.05.18" if name == "agi-core" else "")

    metadata = module.fetch_pypi_app_metadata("agi-app-weather-forecast", opener=opener)

    assert metadata.wheel_available is True
    assert metadata.sdist_available is True
    assert metadata.provenance_available is True
    assert metadata.entry_points == ("weather_forecast=agi_app_weather_forecast:project_root",)

    preflight = module.preflight_pypi_app_install("agi-app-weather-forecast", opener=opener, python_version="3.13.1")

    assert preflight.status == "pass"
    assert preflight.checks["entry_point"].startswith("pass:")
    assert preflight.checks["agi-core_compatibility"].startswith("pass:")


def test_list_installed_pypi_apps_discovers_agilab_entry_points(tmp_path: Path):
    module = _load_module()
    project_root = tmp_path / "weather_forecast_project"
    project_root.mkdir()

    class _EntryPoint:
        name = "weather_forecast"
        value = "agi_app_weather_forecast:project_root"
        group = "agilab.apps"

        @staticmethod
        def load():
            return project_root

    class _EntryPoints(tuple):
        def select(self, *, group):
            return tuple(entry for entry in self if entry.group == group)

    distribution = SimpleNamespace(
        metadata={"Name": "agi-app-weather-forecast", "Summary": "Weather app"},
        version="2026.5.18",
        entry_points=_EntryPoints((_EntryPoint(),)),
    )

    apps = module.list_installed_pypi_apps(distributions_fn=lambda: [distribution])

    assert [app.as_dict() for app in apps] == [
        {
            "entry_point": "agi_app_weather_forecast:project_root",
            "package": "agi-app-weather-forecast",
            "project_root": project_root.resolve().as_posix(),
            "provider": "weather_forecast",
            "source": "installed",
            "summary": "Weather app",
            "version": "2026.5.18",
        }
    ]


def test_management_commands_report_runner_results():
    module = _load_module()
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def runner(command, **kwargs):
        calls.append((tuple(command), kwargs))
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    install = module.run_pypi_app_install(
        "agi-app-weather-forecast",
        runner=runner,
        python_executable="/tmp/python",
        uv_executable="/tmp/uv",
    )
    remove = module.run_pypi_app_uninstall(
        "agi-app-weather-forecast",
        runner=runner,
        python_executable="/tmp/python",
        uv_executable="/tmp/uv",
    )

    assert install.status == "success"
    assert remove.status == "success"
    assert calls[0][0][-1] == "agi-app-weather-forecast"
    assert calls[1][0][-1] == "agi-app-weather-forecast"
    assert calls[0][1]["timeout"] == module.PYPI_APP_INSTALL_TIMEOUT_SECONDS


def test_cli_search_and_dry_run_outputs_json(capsys):
    module = _load_module()

    assert module.main(["search", "weather", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["packages"] == [{"package": "agi-app-weather-forecast", "source": "promoted-catalog"}]

    assert module.main(["install", "agi-app-weather-forecast", "--dry-run", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["requirement"] == "agi-app-weather-forecast"
    assert payload["command"][-1] == "agi-app-weather-forecast"
