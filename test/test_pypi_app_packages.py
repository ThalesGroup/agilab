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


def test_pypi_app_result_serializers_include_nested_metadata():
    module = _load_module()
    metadata = module.PypiAppMetadata(
        package="agi-app-weather-forecast",
        version="2026.5.18",
        summary="Weather app",
        wheel_available=True,
    )
    preflight = module.PypiAppPreflight(
        status="pass",
        requirement="agi-app-weather-forecast",
        package="agi-app-weather-forecast",
        metadata=metadata,
        checks={"pypi": "pass"},
    )
    command = module.PypiAppCommandResult(
        status="success",
        requirement="agi-app-weather-forecast",
        command=("/tmp/uv", "pip", "install"),
        returncode=0,
    )

    assert metadata.as_dict()["wheel_available"] is True
    assert preflight.as_dict()["metadata"]["summary"] == "Weather app"
    assert command.as_dict()["command"] == ["/tmp/uv", "pip", "install"]


def test_installed_pypi_apps_handles_legacy_entry_points_and_bad_loads(tmp_path: Path):
    module = _load_module()
    project_root = tmp_path / "demo_project"
    project_root.mkdir()

    class _GoodEntryPoint:
        group = "agilab.apps"
        name = "demo"
        value = "demo:project_root"

        @staticmethod
        def load():
            return {"project_root": project_root}

    class _DuplicateEntryPoint(_GoodEntryPoint):
        pass

    class _BadLoadEntryPoint:
        group = "agilab.apps"
        name = "broken"
        value = "broken:project_root"

        @staticmethod
        def load():
            raise RuntimeError("boom")

    class _IgnoredEntryPoint:
        group = "console_scripts"
        name = "ignored"
        value = "ignored:main"

        @staticmethod
        def load():
            return project_root

    app_distribution = SimpleNamespace(
        metadata={"Name": "agi_app_demo", "Version": "1.0.0", "Summary": "Demo"},
        entry_points=(
            _GoodEntryPoint(),
            _DuplicateEntryPoint(),
            _BadLoadEntryPoint(),
            _IgnoredEntryPoint(),
        ),
    )
    ignored_distribution = SimpleNamespace(
        metadata={"Name": "requests", "Version": "1.0.0"},
        entry_points=(_GoodEntryPoint(),),
    )

    apps = module.list_installed_pypi_apps(
        distributions_fn=lambda: [ignored_distribution, app_distribution]
    )

    assert [app.provider for app in apps] == ["broken", "demo"]
    assert apps[0].project_root == ""
    assert apps[1].project_root == project_root.resolve().as_posix()
    assert module._coerce_project_root(lambda: (_ for _ in ()).throw(RuntimeError("boom"))) is None
    assert module._coerce_project_root(object()) is None


def test_pypi_metadata_helpers_cover_error_and_size_edges():
    module = _load_module()

    assert module._read_json_response(_Response('{"ok": true}')) == {"ok": True}
    assert module._distribution_project_url(
        {"project_urls": {"Repository": "https://example.test/repo"}}
    ) == "https://example.test/repo"
    assert module._distribution_project_url(
        {"home_page": "https://example.test/home"}
    ) == "https://example.test/home"
    assert module._release_files({"urls": [{"packagetype": "sdist"}, "bad"]}, "1.0") == (
        {"packagetype": "sdist"},
    )
    assert module._best_wheel_url(({"packagetype": "sdist", "url": "sdist.tar.gz"},)) == ""

    assert module._wheel_entry_points_from_bytes(_wheel_bytes("")) == ()
    assert module._wheel_entry_points_from_bytes(
        _wheel_bytes("[console_scripts]\ndemo = demo:main\n")
    ) == ()
    assert module._download_wheel_entry_points("") is None

    too_large = _Response(b"", headers={"Content-Length": "5"})
    assert (
        module._download_wheel_entry_points(
            "https://files.example/demo.whl",
            opener=lambda *_args, **_kwargs: too_large,
            max_bytes=4,
        )
        is None
    )
    oversized_body = _Response(b"12345")
    assert (
        module._download_wheel_entry_points(
            "https://files.example/demo.whl",
            opener=lambda *_args, **_kwargs: oversized_body,
            max_bytes=4,
        )
        is None
    )

    def http_error(code: int):
        return module.urllib.error.HTTPError(
            "https://pypi.example/json",
            code,
            "error",
            hdrs=None,
            fp=None,
        )

    for code, expected in ((404, "not available on PyPI"), (500, "HTTP 500")):
        with pytest.raises(ValueError, match=expected):
            module.fetch_pypi_app_metadata(
                "agi-app-demo",
                opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(http_error(code)),
            )

    with pytest.raises(ValueError, match="offline"):
        module.fetch_pypi_app_metadata(
            "agi-app-demo",
            opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                module.urllib.error.URLError("offline")
            ),
        )
    with pytest.raises(ValueError, match="bad json"):
        module.fetch_pypi_app_metadata(
            "agi-app-demo",
            opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("bad json")),
        )

    metadata = module.fetch_pypi_app_metadata(
        "agi-app-demo",
        opener=lambda *_args, **_kwargs: _Response(
            json.dumps({"info": [], "urls": [{"packagetype": "bdist_wheel"}]}).encode("utf-8")
        ),
        inspect_wheel=False,
    )
    assert metadata.package == "agi-app-demo"
    assert metadata.package_url == "https://pypi.org/project/agi-app-demo/"


def test_preflight_reports_python_entry_point_and_dependency_failures(monkeypatch):
    module = _load_module()

    monkeypatch.setattr(
        module.importlib_metadata,
        "version",
        lambda name: "2025.1.1" if name in {"agilab", "agi-core"} else "",
    )
    failing = module.PypiAppMetadata(
        package="agi-app-demo",
        version="1.0.0",
        requires_python=">=3.14",
        requires_dist=("agilab>=2026", "agi-core>=2026", "bad requirement"),
        wheel_available=False,
        sdist_available=False,
        wheel_metadata_checked=True,
        entry_points=(),
    )
    monkeypatch.setattr(module, "fetch_pypi_app_metadata", lambda *_args, **_kwargs: failing)

    result = module.preflight_pypi_app_install("agi-app-demo", python_version="3.13.0")

    assert result.status == "fail"
    assert result.checks["wheel"] == "warning: no wheel published"
    assert result.checks["entry_point"] == "fail: latest wheel has no agilab.apps entry point"
    assert any("Python 3.13.0 does not satisfy" in issue for issue in result.issues)
    assert any("installed 2025.1.1 does not satisfy" in issue for issue in result.issues)

    unknown = module.PypiAppMetadata(
        package="agi-app-demo",
        version="1.0.0",
        requires_python="not-a-specifier",
        wheel_available=True,
        wheel_metadata_checked=False,
    )
    monkeypatch.setattr(module, "fetch_pypi_app_metadata", lambda *_args, **_kwargs: unknown)

    result = module.preflight_pypi_app_install("agi-app-demo", python_version="3.13.0")

    assert result.status == "pass"
    assert result.checks["python"].startswith("unknown:")
    assert result.checks["entry_point"] == "unknown: wheel metadata was not inspected"


def test_cli_non_json_and_management_branches(monkeypatch, capsys):
    module = _load_module()
    installed = module.InstalledPypiApp(
        package="agi-app-demo",
        version="1.0.0",
        entry_point="demo:root",
        provider="demo",
        project_root="/tmp/demo",
    )
    success = module.PypiAppCommandResult(
        status="success",
        requirement="agi-app-demo",
        command=("uv", "pip", "install", "agi-app-demo"),
        returncode=0,
        output_tail="installed",
    )
    failure = module.PypiAppCommandResult(
        status="error",
        requirement="agi-app-demo",
        command=("uv", "pip", "install", "agi-app-demo"),
        returncode=9,
        output_tail="failed",
    )

    monkeypatch.setattr(module, "list_installed_pypi_apps", lambda: (installed,))
    assert module.main(["list"]) == 0
    assert "agi-app-demo" in capsys.readouterr().out

    assert module.main(["search", "missing"]) == 0
    assert "No entries." in capsys.readouterr().out

    monkeypatch.setattr(
        module,
        "preflight_pypi_app_install",
        lambda *_args, **_kwargs: module.PypiAppPreflight(
            status="fail",
            requirement="agi-app-demo",
            package="agi-app-demo",
            checks={"pypi": "fail"},
            issues=("bad package",),
        ),
    )
    assert module.main(["check", "agi-app-demo"]) == 1
    assert "! bad package" in capsys.readouterr().out

    assert module.main(["install", "agi-app-demo"]) == 1
    assert "preflight failed" in capsys.readouterr().err

    monkeypatch.setattr(module, "preflight_pypi_app_install", lambda *_args, **_kwargs: success)
    monkeypatch.setattr(module, "run_pypi_app_install", lambda *_args, **_kwargs: success)
    assert module.main(["install", "agi-app-demo", "--skip-preflight"]) == 0
    assert "installed" in capsys.readouterr().out

    monkeypatch.setattr(module, "installed_app_package_names", lambda: ())
    assert module.main(["update", "--all"]) == 0
    assert "No installed PyPI app packages found." in capsys.readouterr().out

    monkeypatch.setattr(module, "installed_app_package_names", lambda: ("agi-app-demo",))
    assert module.main(["update", "--all", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["updated"][0]["status"] == "success"

    monkeypatch.setattr(module, "run_pypi_app_install", lambda *_args, **_kwargs: failure)
    assert module.main(["update", "agi-app-demo"]) == 9
    assert "failed" in capsys.readouterr().out

    with pytest.raises(SystemExit, match="requires a package or --all"):
        module.main(["update"])

    assert module.main(["remove", "agi-app-demo", "--dry-run"]) == 0
    assert "pip uninstall" in capsys.readouterr().out

    monkeypatch.setattr(module, "run_pypi_app_uninstall", lambda *_args, **_kwargs: failure)
    assert module.main(["remove", "agi-app-demo", "--json"]) == 9
    assert json.loads(capsys.readouterr().out)["status"] == "error"


def test_remaining_helper_defensive_branches(monkeypatch):
    module = _load_module()

    monkeypatch.setattr(module, "normalize_pypi_app_requirement", lambda _value: "not-valid")
    with pytest.raises(ValueError, match="Invalid agi-app requirement"):
        module.pypi_app_package_name("agi-app-demo")

    module = _load_module()

    class _BrokenEntryPoints(tuple):
        def select(self, *, group):
            raise RuntimeError("metadata error")

    assert module._entry_points_for_distribution(
        SimpleNamespace(entry_points=_BrokenEntryPoints(()))
    ) == ()
    assert module.search_promoted_pypi_app_catalog() == module.PROMOTED_PYPI_APP_PACKAGES
    assert module._release_files({"releases": {"1.0": "bad"}}, "1.0") == ()

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as wheel:
        wheel.writestr("demo-1.0.0.dist-info/METADATA", "Name: demo\n")
    assert module._wheel_entry_points_from_bytes(buffer.getvalue()) == ()

    assert module._version_satisfies_spec("1.0", "") is True
    monkeypatch.setattr(module, "Version", None)
    assert module._version_satisfies_spec("1.0", ">=1") is None
    monkeypatch.setattr(module, "Version", _load_module().Version)

    assert len(module._python_version_string().split(".")) == 3

    def missing_version(_name):
        raise module.importlib_metadata.PackageNotFoundError("missing")

    monkeypatch.setattr(module.importlib_metadata, "version", missing_version)
    assert module._installed_version("agi-core") == ""

    monkeypatch.setattr(module, "Requirement", None)
    assert module._dependency_compatibility(("agi-core>=2026",)) == {}

    module = _load_module()
    monkeypatch.setattr(module.importlib_metadata, "version", missing_version)
    assert module._dependency_compatibility(
        ("numpy>=1", "agi-core>=2026", "agilab>=2026", "agilab not-a-specifier")
    ) == {
        "agi-core_compatibility": "unknown: distribution is not installed",
        "agilab_compatibility": "unknown: distribution is not installed",
    }

    monkeypatch.setattr(module.importlib_metadata, "version", lambda _name: "bad-version")
    assert module._dependency_compatibility(("agi-core>=2026",)) == {
        "agi-core_compatibility": "unknown: could not evaluate >=2026"
    }

    apps = [
        module.InstalledPypiApp("agi-app-z", "1", "z:root", "z", "/z"),
        module.InstalledPypiApp("agi-app-a", "1", "a:root", "a", "/a"),
        module.InstalledPypiApp("agi-app-a", "1", "a:root", "a", "/a"),
    ]
    assert module.installed_app_package_names(apps) == ("agi-app-a", "agi-app-z")
    monkeypatch.setattr(module, "list_installed_pypi_apps", lambda: tuple(apps))
    assert module.installed_app_package_names() == ("agi-app-a", "agi-app-z")


def test_preflight_fetch_failure_and_cli_json_edges(monkeypatch, capsys):
    module = _load_module()
    metadata = module.PypiAppMetadata(
        package="agi-app-demo",
        version="1.0.0",
        package_url="https://pypi.org/project/agi-app-demo/",
        wheel_available=True,
        wheel_metadata_checked=True,
        entry_points=("demo=demo:root",),
    )
    passing_preflight = module.PypiAppPreflight(
        status="pass",
        requirement="agi-app-demo",
        package="agi-app-demo",
        metadata=metadata,
        checks={"pypi": "pass"},
    )
    failing_preflight = module.PypiAppPreflight(
        status="fail",
        requirement="agi-app-demo",
        package="agi-app-demo",
        checks={"pypi": "fail"},
        issues=("metadata failed",),
    )
    success = module.PypiAppCommandResult(
        status="success",
        requirement="agi-app-demo",
        command=("uv", "pip", "install", "agi-app-demo"),
        returncode=0,
    )

    monkeypatch.setattr(
        module,
        "fetch_pypi_app_metadata",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("metadata failed")),
    )
    preflight = module.preflight_pypi_app_install("agi-app-demo")
    assert preflight.status == "fail"
    assert preflight.checks == {"pypi": "fail"}
    assert preflight.issues == ("metadata failed",)

    monkeypatch.setattr(
        module,
        "list_installed_pypi_apps",
        lambda: (
            module.InstalledPypiApp("agi-app-demo", "1.0.0", "demo:root", "demo", "/tmp/demo"),
        ),
    )
    assert module.main(["list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["apps"][0]["package"] == "agi-app-demo"

    monkeypatch.setattr(module, "preflight_pypi_app_install", lambda *_args, **_kwargs: passing_preflight)
    assert module.main(["check", "agi-app-demo", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["metadata"]["version"] == "1.0.0"

    assert module.main(["check", "agi-app-demo"]) == 0
    check_output = capsys.readouterr().out
    assert "- version: 1.0.0" in check_output
    assert "- url: https://pypi.org/project/agi-app-demo/" in check_output

    monkeypatch.setattr(
        module,
        "preflight_pypi_app_install",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad requirement")),
    )
    assert module.main(["check", "agi-app-demo", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["issues"] == ["bad requirement"]

    assert module.main(["check", "agi-app-demo"]) == 2
    assert "bad requirement" in capsys.readouterr().err

    assert module.main(["install", "agi-app-demo", "--dry-run"]) == 0
    assert "pip install" in capsys.readouterr().out

    monkeypatch.setattr(module, "preflight_pypi_app_install", lambda *_args, **_kwargs: failing_preflight)
    assert module.main(["install", "agi-app-demo", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["issues"] == ["metadata failed"]

    monkeypatch.setattr(module, "installed_app_package_names", lambda: ())
    assert module.main(["update", "--all", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"updated": []}

    monkeypatch.setattr(module, "installed_app_package_names", lambda: ("agi-app-demo",))
    monkeypatch.setattr(module, "run_pypi_app_install", lambda *_args, **_kwargs: success)
    assert module.main(["update", "--all"]) == 0
    assert "success: agi-app-demo" in capsys.readouterr().out

    assert module.main(["remove", "agi-app-demo", "--dry-run", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["requirement"] == "agi-app-demo"
