from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
from types import SimpleNamespace

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "agilab" / "notebook_demo.py"
MODULE_SPEC = importlib.util.spec_from_file_location("agilab.notebook_demo", MODULE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
notebook_demo = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = notebook_demo
MODULE_SPEC.loader.exec_module(notebook_demo)
NOTEBOOK_DIR = Path(__file__).resolve().parents[1] / "src" / "agilab" / "examples" / "notebook_quickstart"


def _make_app(root: Path, name: str = "mycode_project") -> Path:
    app_root = root / name
    (app_root / "src").mkdir(parents=True)
    (app_root / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    return app_root


def _notebook_source(name: str) -> str:
    notebook = json.loads((NOTEBOOK_DIR / name).read_text(encoding="utf-8"))
    return "\n".join(
        "".join(cell.get("source", []))
        for cell in notebook["cells"]
    )


def test_resolve_notebook_apps_path_prefers_source_builtin_root(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    builtin_root = repo_root / "src" / "agilab" / "apps" / "builtin"
    _make_app(builtin_root)

    resolved = notebook_demo.resolve_notebook_apps_path(start=repo_root / "docs")

    assert resolved == builtin_root


def test_resolve_notebook_apps_path_accepts_explicit_project_root(tmp_path: Path) -> None:
    project_root = _make_app(tmp_path / "apps")

    resolved = notebook_demo.resolve_notebook_apps_path(apps_path=project_root)

    assert resolved == project_root.parent


def test_resolve_notebook_apps_path_reports_install_hint(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(notebook_demo, "_package_dir", lambda _package: None)
    monkeypatch.setattr(notebook_demo, "_installed_app_project_root", lambda _app: None)

    with pytest.raises(FileNotFoundError, match="Install 'agilab\\[examples\\]' or 'agi-apps'"):
        notebook_demo.resolve_notebook_apps_path(start=tmp_path)


def test_notebook_demo_package_and_installed_app_resolution_edges(monkeypatch, tmp_path: Path) -> None:
    assert notebook_demo._normalise_project_app("") == "mycode_project"
    assert notebook_demo._normalise_project_app("weather-forecast") == "weather_forecast_project"

    builtin_root = tmp_path / "pkg" / "apps" / "builtin"
    app_root = _make_app(builtin_root, "weather_forecast_project")
    assert notebook_demo._root_for_app(builtin_root.parent, "weather_forecast") == builtin_root
    assert notebook_demo._root_for_app(app_root, "weather_forecast") == builtin_root

    class FakeSpec:
        submodule_search_locations = [str(tmp_path / "package")]
        origin = None

    monkeypatch.setattr(notebook_demo.importlib.util, "find_spec", lambda _package: FakeSpec())
    assert notebook_demo._package_dir("demo") == tmp_path / "package"

    class OriginSpec:
        submodule_search_locations = []
        origin = str(tmp_path / "origin_pkg" / "__init__.py")

    monkeypatch.setattr(notebook_demo.importlib.util, "find_spec", lambda _package: OriginSpec())
    assert notebook_demo._package_dir("demo") == tmp_path / "origin_pkg"
    monkeypatch.setattr(
        notebook_demo.importlib.util,
        "find_spec",
        lambda _package: (_ for _ in ()).throw(ValueError("bad spec")),
    )
    assert notebook_demo._package_dir("demo") is None

    provider = ModuleType("agi_env.app_provider_registry")
    provider.resolve_installed_app_project = lambda _app: app_root
    monkeypatch.setitem(sys.modules, "agi_env.app_provider_registry", provider)
    assert notebook_demo._installed_app_project_root("weather_forecast_project") == app_root
    provider.resolve_installed_app_project = lambda _app: (_ for _ in ()).throw(RuntimeError("boom"))
    assert notebook_demo._installed_app_project_root("weather_forecast_project") is None

    monkeypatch.setattr(notebook_demo, "_package_dir", lambda package: tmp_path / "pkg" if package == "agilab" else None)
    monkeypatch.setattr(notebook_demo, "_installed_app_project_root", lambda _app: None)
    assert notebook_demo.resolve_notebook_apps_path("weather_forecast", start=tmp_path / "missing") == builtin_root


def test_notebook_local_request_uses_visible_local_defaults(monkeypatch) -> None:
    requests = []

    class FakeRunRequest:
        def __init__(self, **kwargs):
            requests.append(kwargs)
            self.__dict__.update(kwargs)

    monkeypatch.setattr(notebook_demo, "_import_run_request", lambda: FakeRunRequest)

    request = notebook_demo.notebook_local_request(params={"seed": 7})

    assert request.scheduler == "127.0.0.1"
    assert request.workers == {"127.0.0.1": 1}
    assert request.mode == 0
    assert request.params == {"seed": 7}
    assert requests == [
        {
            "params": {"seed": 7},
            "scheduler": "127.0.0.1",
            "workers": {"127.0.0.1": 1},
            "mode": 0,
        }
    ]


def test_notebook_local_request_rejects_mixed_params_and_uses_keyword_params(monkeypatch) -> None:
    class FakeRunRequest:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    monkeypatch.setattr(notebook_demo, "_import_run_request", lambda: FakeRunRequest)

    with pytest.raises(ValueError, match="either params"):
        notebook_demo.notebook_local_request(params={"seed": 1}, dataset="moons")

    request = notebook_demo.notebook_local_request(
        workers={"worker": 2},
        mode="debug",
        dataset="spiral",
    )
    assert request.params == {"dataset": "spiral"}
    assert request.workers == {"worker": 2}
    assert request.mode == "debug"


def test_notebook_app_env_resolves_apps_path_and_returns_agi_env(monkeypatch, tmp_path: Path) -> None:
    builtin_root = tmp_path / "apps" / "builtin"
    _make_app(builtin_root)
    calls = []

    class FakeAgiEnv:
        def __init__(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(notebook_demo, "_import_agi_env", lambda: FakeAgiEnv)

    env = notebook_demo.notebook_app_env("mycode_project", apps_path=builtin_root, verbose=1)

    assert isinstance(env, FakeAgiEnv)
    assert calls == [{"apps_path": builtin_root, "app": "mycode_project", "verbose": 1}]


@pytest.mark.asyncio
async def test_install_if_needed_uses_request_defaults_without_hiding_agi_run(monkeypatch) -> None:
    calls = []
    fake_agi = object()
    app_env = SimpleNamespace(app="mycode_project", target="mycode")
    request = SimpleNamespace(
        scheduler="10.0.0.1",
        workers={"10.0.0.2": 2},
        mode=3,
    )

    async def fake_install_if_needed(AGI, env, **kwargs):
        calls.append((AGI, env, kwargs))
        return True

    monkeypatch.setattr(notebook_demo, "_import_agi", lambda: fake_agi)
    monkeypatch.setattr(notebook_demo, "_install_if_needed_with_agi", fake_install_if_needed)

    installed = await notebook_demo.install_if_needed(app_env, request=request, print_fn=lambda _msg: None)

    assert installed is True
    assert calls[0][0] is fake_agi
    assert calls[0][1] is app_env
    assert calls[0][2]["scheduler"] == "10.0.0.1"
    assert calls[0][2]["workers"] == {"10.0.0.2": 2}
    assert calls[0][2]["modes_enabled"] == 3
    assert callable(calls[0][2]["print_fn"])


@pytest.mark.asyncio
async def test_install_if_needed_accepts_explicit_scheduler_workers_and_modes(monkeypatch) -> None:
    calls = []

    async def fake_install_if_needed(_AGI, _env, **kwargs):
        calls.append(kwargs)
        return False

    monkeypatch.setattr(notebook_demo, "_import_agi", lambda: object())
    monkeypatch.setattr(notebook_demo, "_install_if_needed_with_agi", fake_install_if_needed)

    installed = await notebook_demo.install_if_needed(
        SimpleNamespace(app="demo"),
        request=SimpleNamespace(scheduler="ignored", workers={"ignored": 1}, mode="bad"),
        scheduler="127.0.0.9",
        workers={"127.0.0.10": 3},
        modes_enabled=5,
    )

    assert installed is False
    assert calls == [
        {
            "scheduler": "127.0.0.9",
            "workers": {"127.0.0.10": 3},
            "modes_enabled": 5,
            "print_fn": print,
        }
    ]


def test_notebook_log_root_uses_runtime_target(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(notebook_demo.Path, "home", staticmethod(lambda: tmp_path))

    assert notebook_demo.notebook_log_root(SimpleNamespace(target="mycode")) == (
        tmp_path / "log" / "execute" / "mycode"
    )
    assert notebook_demo.notebook_log_root("weather_forecast_project") == (
        tmp_path / "log" / "execute" / "weather_forecast"
    )


def test_notebook_quickstart_assets_use_framework_demo_helpers() -> None:
    notebooks = (
        "agi_core_first_run.ipynb",
        "agi_core_colab_first_run.ipynb",
        "agi_core_kaggle_first_run.ipynb",
        "agi_core_colab_first_run_source.ipynb",
        "agi_core_kaggle_first_run_source.ipynb",
        "agi_core_colab_benchmark.ipynb",
        "agi_core_colab_benchmark_source.ipynb",
        "agi_core_colab_data_dag.ipynb",
        "agi_core_colab_data_dag_pypi.ipynb",
        "agi_core_colab_worker_paths.ipynb",
        "agi_core_colab_worker_paths_pypi.ipynb",
    )

    for notebook in notebooks:
        source = _notebook_source(notebook)
        assert "from agilab.notebook_demo import" in source, notebook
        assert "def worker_env_ready" not in source, notebook
        assert "async def install_if_needed(app_env" not in source, notebook


def test_pypi_notebooks_install_packaged_app_assets() -> None:
    notebooks = (
        "agi_core_colab_first_run.ipynb",
        "agi_core_kaggle_first_run.ipynb",
        "agi_core_colab_benchmark.ipynb",
        "agi_core_colab_data_dag_pypi.ipynb",
        "agi_core_colab_worker_paths_pypi.ipynb",
    )

    for notebook in notebooks:
        source = _notebook_source(notebook)
        assert '"agi-core", "agi-apps"' in source, notebook
