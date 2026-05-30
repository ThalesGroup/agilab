from __future__ import annotations

import ast
import asyncio
import importlib.util
import json
import py_compile
import runpy
import sqlite3
import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
sys.path.insert(0, str(TOOLS_ROOT))

from package_split_contract import (  # noqa: E402
    APP_PROJECT_PACKAGE_SPECS,
    PAGE_BUNDLE_PACKAGE_SPECS,
    PROMOTED_APP_PROJECT_PACKAGE_NAMES,
)

MODULE_PATH = ROOT / "src/agilab/apps/install.py"
APP_PROJECT_BUILD_SUPPORT = ROOT / "src/agilab/lib/app_project_build_support.py"
ROOT_PYPROJECT = ROOT / "pyproject.toml"
AGI_APPS_PYPROJECT = ROOT / "src/agilab/lib/agi-apps/pyproject.toml"
AGI_PAGES_PYPROJECT = ROOT / "src/agilab/lib/agi-pages/pyproject.toml"
AGI_PAGES_SOURCE_PACKAGE = ROOT / "src/agilab/lib/agi-pages/src/agi_pages"
BUILTIN_APPS_ROOT = ROOT / "src/agilab/apps/builtin"
APP_TEMPLATES_ROOT = ROOT / "src/agilab/apps/templates"
EXAMPLES_ROOT = ROOT / "src/agilab/examples"
APPS_PAGES_ROOT = ROOT / "src/agilab/apps-pages"
EXAMPLE_APPS = {
    "mission_decision": ("AGI_install_mission_decision.py", "AGI_run_mission_decision.py"),
    "flight_telemetry": ("AGI_install_flight_telemetry.py", "AGI_run_flight_telemetry.py"),
    "sklearn_pipeline": ("AGI_install_sklearn_pipeline.py", "AGI_run_sklearn_pipeline.py"),
    "weather_forecast": ("AGI_install_weather_forecast.py", "AGI_run_weather_forecast.py"),
    "minimal_app": ("AGI_install_minimal_app.py", "AGI_run_minimal_app.py"),
}
EXAMPLE_PREVIEWS = {
    "excel_workbook_proof": ("preview_excel_workbook_proof.py",),
    "inter_project_dag": ("preview_inter_project_dag.py",),
    "mlflow_auto_tracking": ("preview_mlflow_auto_tracking.py",),
    "native_rust_worker": ("preview_native_rust_worker.py",),
    "notebook_to_dask": (
        "preview_notebook_to_dask.py",
        "notebook_to_dask_sample.ipynb",
        "lab_stages.toml",
        "pipeline_view.json",
    ),
    "parallel_stage": (
        "preview_parallel_stage.py",
        "parallel_stage.toml",
    ),
    "resilience_failure_injection": (
        "preview_resilience_failure_injection.py",
    ),
    "service_mode": ("preview_service_mode.py",),
    "sqlite_connector_proof": ("preview_sqlite_connector_proof.py",),
    "train_then_serve": ("preview_train_then_serve.py",),
    "voila_notebook_proof": ("preview_voila_notebook_proof.py",),
}
EXAMPLE_NOTEBOOK_ASSETS = {
    "notebook_migrations/skforecast_meteo_fr": ("README.md",),
    "notebook_quickstart": ("README.md", "agi_core_first_run.ipynb"),
}
EXAMPLE_CLASS_LABELS = {
    "Runnable app project",
    "Read-only preview",
    "Notebook import asset",
}
EXAMPLE_CATALOG_DOC = ROOT / "docs/source/packaged-examples.rst"
DOCS_INDEX = ROOT / "docs/source/index.rst"
DEPRECATED_EXAMPLE_DIR_NAMES = {
    "data_io_2026",
    "flight",
    "weather_forecast_legacy",
}
BUILTIN_EXAMPLE_PAYLOADS = {
    "inter_project_dag": (
        BUILTIN_APPS_ROOT
        / "multi_app_dag_project"
        / "dag_templates"
        / "flight_to_weather_multi_app_dag.json"
    ),
    "mlflow_auto_tracking": (
        BUILTIN_APPS_ROOT
        / "weather_forecast_project"
        / "tracking_templates"
        / "mlflow_auto_tracking_run_config.json"
    ),
    "resilience_failure_injection": (
        BUILTIN_APPS_ROOT
        / "uav_queue_project"
        / "scenario_templates"
        / "resilience_failure_injection_scenario.json"
    ),
    "service_mode": (
        BUILTIN_APPS_ROOT / "minimal_app_project" / "service_templates" / "sample_health_running.json"
    ),
    "train_then_serve": (
        BUILTIN_APPS_ROOT
        / "uav_relay_queue_project"
        / "service_templates"
        / "train_then_serve_policy_run.json"
    ),
}
APP_SOURCE_SUFFIXES = {
    ".7z",
    ".csv",
    ".dot",
    ".ipynb",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".txt",
}
APP_GENERATED_NAMES = {".coverage", ".DS_Store", "uv.lock"}
APP_GENERATED_DIRS = {
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
}
APP_GENERATED_SUFFIXES = {".c", ".pyc", ".pyo", ".pyx", ".so"}
APP_PROJECT_BY_DISTRIBUTION = {
    "agi-app-mission-decision": "mission_decision_project",
    "agi-app-pandas-execution": "execution_pandas_project",
    "agi-app-polars-execution": "execution_polars_project",
    "agi-app-flight-telemetry": "flight_telemetry_project",
    "agi-app-multi-dag": "multi_app_dag_project",
    "agi-app-weather-forecast": "weather_forecast_project",
    "agi-app-sklearn-pipeline": "sklearn_pipeline_project",
    "agi-app-pytorch-playground": "pytorch_playground_project",
    "agi-app-tescia-diagnostic": "tescia_diagnostic_project",
    "agi-app-uav-queue": "uav_queue_project",
    "agi-app-uav-relay-queue": "uav_relay_queue_project",
}
APP_PACKAGE_README_REQUIRED_SECTIONS = (
    "## Purpose",
    "## Installed Project",
    "## Install",
    "## Run In AGILAB",
    "## Expected Inputs",
    "## Expected Outputs",
    "## Change One Thing",
    "## Scope",
)


def _expected_script_paths() -> list[Path]:
    return sorted(
        EXAMPLES_ROOT / example_name / script_name
        for example_name, script_names in EXAMPLE_APPS.items()
        for script_name in script_names
    )


def _packaged_example_dirs() -> list[str]:
    return sorted(
        path.name
        for path in EXAMPLES_ROOT.iterdir()
        if path.is_dir() and not path.name.startswith("__")
    )


def _load_installer(monkeypatch, tmp_path: Path):
    sys.modules.pop("agilab_app_install_test_module", None)
    app_path = tmp_path / "demo_project"
    app_path.mkdir()
    monkeypatch.setattr(sys, "argv", ["install.py", str(app_path)])
    spec = importlib.util.spec_from_file_location("agilab_app_install_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_app_project_build_support():
    sys.modules.pop("agilab_app_project_build_support_test_module", None)
    spec = importlib.util.spec_from_file_location(
        "agilab_app_project_build_support_test_module",
        APP_PROJECT_BUILD_SUPPORT,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_app_package_entry_points_prefer_source_checkout_builtin_projects() -> None:
    for distribution, project_name in sorted(APP_PROJECT_BY_DISTRIBUTION.items()):
        init_candidates = sorted((ROOT / "src/agilab/lib" / distribution / "src").glob("agi_app_*/__init__.py"))
        assert len(init_candidates) == 1, distribution
        init_path = init_candidates[0]
        module_name = f"{init_path.parent.name}_project_root_test"
        sys.modules.pop(module_name, None)
        spec = importlib.util.spec_from_file_location(module_name, init_path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        assert module.project_root() == (BUILTIN_APPS_ROOT / project_name).resolve()


def test_app_project_payload_build_helper_ignores_generated_app_dirs() -> None:
    support = _load_app_project_build_support()

    assert APP_GENERATED_DIRS <= support._EXCLUDED_PAYLOAD_DIRS


def _builtin_app_dirs() -> list[Path]:
    return sorted(path for path in BUILTIN_APPS_ROOT.glob("*_project") if path.is_dir())


def _root_package_data() -> list[str]:
    pyproject = tomllib.loads(ROOT_PYPROJECT.read_text(encoding="utf-8"))
    return pyproject["tool"]["setuptools"]["package-data"]["agilab"]


def _agi_apps_package_data(package: str) -> list[str]:
    pyproject = tomllib.loads(AGI_APPS_PYPROJECT.read_text(encoding="utf-8"))
    return pyproject["tool"]["setuptools"]["package-data"][package]


def _agi_apps_excluded_data(package: str) -> list[str]:
    pyproject = tomllib.loads(AGI_APPS_PYPROJECT.read_text(encoding="utf-8"))
    return pyproject["tool"]["setuptools"]["exclude-package-data"].get(package, [])


def _agi_pages_package_data() -> list[str]:
    pyproject = tomllib.loads(AGI_PAGES_PYPROJECT.read_text(encoding="utf-8"))
    return pyproject["tool"]["setuptools"].get("package-data", {}).get("agi_pages", [])


def _agi_app_project_pyproject(distribution: str) -> dict:
    return tomllib.loads((ROOT / "src/agilab/lib" / distribution / "pyproject.toml").read_text(encoding="utf-8"))


def _builtin_project_pyproject(project_name: str) -> dict:
    return tomllib.loads((BUILTIN_APPS_ROOT / project_name / "pyproject.toml").read_text(encoding="utf-8"))


def _python_floor(requires_python: str) -> tuple[int, int]:
    prefix = ">="
    assert requires_python.startswith(prefix), requires_python
    version = requires_python.removeprefix(prefix).split(",", 1)[0]
    major, minor, *_ = version.split(".")
    return int(major), int(minor)


def _packaged_app_dirs() -> list[Path]:
    return [
        *_builtin_app_dirs(),
        *sorted(path for path in APP_TEMPLATES_ROOT.glob("*_template") if path.is_dir()),
    ]


def _git_paths(*args: str) -> set[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return {line for line in result.stdout.splitlines() if line}


def _is_source_like_app_file(app_dir: Path, path: Path) -> bool:
    rel_parts = path.relative_to(app_dir).parts
    if path.name in APP_GENERATED_NAMES:
        return False
    if path.suffix in APP_GENERATED_SUFFIXES:
        return False
    if any(part in APP_GENERATED_DIRS or part.endswith(".egg-info") for part in rel_parts):
        return False
    return path.name == ".gitignore" or path.suffix in APP_SOURCE_SUFFIXES


def test_packaged_apps_include_required_project_assets() -> None:
    missing: list[str] = []
    for app_dir in _packaged_app_dirs():
        for rel_path in (
            "README.md",
            "pyproject.toml",
            "src/app_args_form.py",
            "src/app_settings.toml",
            "src/pre_prompt.json",
        ):
            candidate = app_dir / rel_path
            if not candidate.is_file():
                missing.append(candidate.relative_to(ROOT).as_posix())

    assert not missing, "Missing packaged app project assets:\n" + "\n".join(missing)


def test_app_template_python_files_compile_safe() -> None:
    scripts = sorted(APP_TEMPLATES_ROOT.glob("*_template/src/**/*.py"))

    assert scripts
    for script in scripts:
        py_compile.compile(str(script), doraise=True)


def test_app_templates_keep_runtime_contracts_explicit() -> None:
    templates = sorted(path for path in APP_TEMPLATES_ROOT.glob("*_template") if path.is_dir())
    assert templates

    workerless_templates = {"simple_app_template"}
    forbidden_python_fragments = (
        "AGI._env",
        "warnings.filterwarnings",
        "Backward-compatible",
        "Compatibility shim",
        "legacy",
        "data_uri",
    )
    for template in templates:
        pyproject = tomllib.loads((template / "pyproject.toml").read_text(encoding="utf-8"))
        authors = pyproject["project"].get("authors", [])
        assert authors, template.name
        assert all(author.get("email") != "your email" for author in authors), template.name
        assert all("@" in author.get("email", "") for author in authors), template.name
        dependencies = set()
        for dependency in pyproject["project"]["dependencies"]:
            name = dependency.split(";", 1)[0].split("[", 1)[0].strip()
            for operator in ("==", ">=", "<=", "~=", "!=", ">", "<"):
                name = name.split(operator, 1)[0].strip()
            dependencies.add(name)
        assert {"agi-env", "pydantic", "streamlit"} <= dependencies
        if template.name in workerless_templates:
            assert {"agi-cluster", "agi-node"}.isdisjoint(dependencies), template.name
            assert not any(template.glob("src/*_worker")), template.name
        else:
            assert {"agi-cluster", "agi-node"} <= dependencies, template.name
        assert "filterwarnings" not in pyproject.get("tool", {}).get("mypy", {})

        cluster_settings = tomllib.loads((template / "src/app_settings.toml").read_text(encoding="utf-8"))["cluster"]
        assert "cluster_enabled" in cluster_settings
        assert {"workers_enable", "workers_enabled", "scheduler_enable"}.isdisjoint(cluster_settings)

        for script in sorted((template / "src").glob("**/*.py")):
            text = script.read_text(encoding="utf-8")
            for fragment in forbidden_python_fragments:
                assert fragment not in text, f"{script.relative_to(ROOT).as_posix()} contains {fragment!r}"


def test_app_template_pre_prompts_are_generic_and_dependency_neutral() -> None:
    templates = sorted(path for path in APP_TEMPLATES_ROOT.glob("*_template") if path.is_dir())
    assert templates

    stale_fragments = ("mlflow", "sklearn", "scikit-learn", "df is already loaded")
    for template in templates:
        prompt_path = template / "src/pre_prompt.json"
        payload = json.loads(prompt_path.read_text(encoding="utf-8"))
        prompt_text = json.dumps(payload).lower()

        assert isinstance(payload, list)
        assert all(isinstance(item.get("role"), str) and isinstance(item.get("content"), str) for item in payload)
        for fragment in stale_fragments:
            assert fragment not in prompt_text, f"{prompt_path.relative_to(ROOT).as_posix()} contains {fragment!r}"


def test_builtin_app_pre_prompts_are_workflow_message_lists() -> None:
    prompt_paths = sorted(BUILTIN_APPS_ROOT.glob("*/src/pre_prompt.json"))
    assert prompt_paths

    for prompt_path in prompt_paths:
        payload = json.loads(prompt_path.read_text(encoding="utf-8"))
        assert isinstance(payload, list), prompt_path.relative_to(ROOT).as_posix()
        assert all(isinstance(item, dict) for item in payload), prompt_path.relative_to(ROOT).as_posix()
        assert all(isinstance(item.get("role"), str) for item in payload), prompt_path.relative_to(ROOT).as_posix()
        assert all(isinstance(item.get("content"), str) for item in payload), prompt_path.relative_to(ROOT).as_posix()


def test_packaged_app_source_assets_are_tracked_or_git_visible() -> None:
    tracked = _git_paths("ls-files")
    visible_untracked = _git_paths("ls-files", "--others", "--exclude-standard")
    git_visible = tracked | visible_untracked

    hidden_or_untracked: list[str] = []
    for app_dir in _packaged_app_dirs():
        for path in sorted(candidate for candidate in app_dir.rglob("*") if candidate.is_file()):
            if not _is_source_like_app_file(app_dir, path):
                continue
            rel_path = path.relative_to(ROOT).as_posix()
            if rel_path not in git_visible:
                hidden_or_untracked.append(rel_path)

    assert not hidden_or_untracked, (
        "Packaged app source assets are hidden by .gitignore or unavailable to git:\n"
        + "\n".join(hidden_or_untracked)
    )


def test_seed_example_scripts_uses_packaged_examples_dir(tmp_path: Path, monkeypatch) -> None:
    module = _load_installer(monkeypatch, tmp_path)
    package_root = tmp_path / "site-packages" / "agilab"
    examples_dir = package_root / "examples" / "flight_telemetry"
    examples_dir.mkdir(parents=True)
    (examples_dir / "AGI_install_flight_telemetry.py").write_text("# install\n", encoding="utf-8")
    (examples_dir / "AGI_run_flight_telemetry.py").write_text("# run\n", encoding="utf-8")
    monkeypatch.setattr(module, "_package_root", lambda: package_root)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    module._seed_example_scripts("flight_telemetry")

    execute_dir = tmp_path / "home" / "log" / "execute" / "flight_telemetry"
    assert (execute_dir / "AGI_install_flight_telemetry.py").read_text(encoding="utf-8") == "# install\n"
    assert (execute_dir / "AGI_run_flight_telemetry.py").read_text(encoding="utf-8") == "# run\n"


def test_app_dir_candidates_prefer_packaged_builtin_apps(tmp_path: Path, monkeypatch) -> None:
    module = _load_installer(monkeypatch, tmp_path)
    package_root = tmp_path / "site-packages" / "agilab"
    monkeypatch.setattr(module, "_package_root", lambda: package_root)
    monkeypatch.setattr(module, "_installed_app_dir_candidates", lambda app_slug: [])

    assert module._app_dir_candidates("flight_telemetry") == [
        package_root / "apps" / "builtin" / "flight_telemetry_project",
        package_root / "apps" / "flight_telemetry_project",
    ]


def test_app_dir_candidates_include_installed_app_project_packages(tmp_path: Path, monkeypatch) -> None:
    module = _load_installer(monkeypatch, tmp_path)
    package_root = tmp_path / "site-packages" / "agilab"
    installed_root = tmp_path / "site-packages" / "agi_app_flight_telemetry" / "project" / "flight_telemetry_project"
    monkeypatch.setattr(module, "_package_root", lambda: package_root)
    monkeypatch.setattr(module, "_installed_app_dir_candidates", lambda app_slug: [installed_root])

    assert module._app_dir_candidates("flight")[-1] == installed_root


def _seed_venv_python(project: Path) -> None:
    python = project / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text("#!/usr/bin/env python\n", encoding="utf-8")


def test_install_state_cache_hits_only_when_fingerprint_and_venvs_match(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_installer(monkeypatch, tmp_path)
    monkeypatch.setenv("AGILAB_INSTALL_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(module, "_uv_version", lambda _uv: "uv test")

    app_path = tmp_path / "demo_project"
    app_src = app_path / "src" / "demo"
    worker_src = app_path / "src" / "demo_worker"
    app_src.mkdir(parents=True)
    worker_src.mkdir(parents=True)
    (app_path / "pyproject.toml").write_text("[project]\nname='demo-project'\n", encoding="utf-8")
    (app_src / "demo.py").write_text("print('manager')\n", encoding="utf-8")
    (worker_src / "demo_worker.py").write_text("print('worker')\n", encoding="utf-8")
    (worker_src / "pyproject.toml").write_text("[project]\nname='demo-worker'\n", encoding="utf-8")
    wenv_abs = tmp_path / "wenv" / "demo_worker"

    env = SimpleNamespace(
        active_app=app_path,
        wenv_abs=wenv_abs,
        app="demo_project",
        target="demo",
        target_worker="demo_worker",
        install_type=1,
        is_source_env=False,
        python_version="3.13",
        pyvers_worker="3.13",
        uv="uv",
        uv_worker="uv",
    )

    assert module._install_state_matches(env, modes_enabled=6, scheduler="127.0.0.1")[0] is False

    _seed_venv_python(app_path)
    _seed_venv_python(wenv_abs)
    assert module._install_state_matches(env, modes_enabled=6, scheduler="127.0.0.1")[0] is False

    module._write_install_state(env, modes_enabled=6, scheduler="127.0.0.1")
    assert module._install_state_matches(env, modes_enabled=6, scheduler="127.0.0.1") == (
        True,
        "install fingerprint unchanged",
    )

    (app_path / "pyproject.toml").write_text(
        "[project]\nname='demo-project'\ndependencies=['numpy']\n",
        encoding="utf-8",
    )
    hit, reason = module._install_state_matches(env, modes_enabled=6, scheduler="127.0.0.1")
    assert hit is False
    assert reason == "install fingerprint changed"


def test_install_state_cache_for_workerless_apps_requires_only_manager_venv(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_installer(monkeypatch, tmp_path)
    monkeypatch.setenv("AGILAB_INSTALL_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(module, "_uv_version", lambda _uv: "uv test")

    app_path = tmp_path / "simple_project"
    app_src = app_path / "src" / "simple"
    app_src.mkdir(parents=True)
    (app_path / "pyproject.toml").write_text(
        "[project]\nname='simple-project'\n\n[tool.agilab.app]\nruntime='local'\nworkerless=true\n",
        encoding="utf-8",
    )
    (app_src / "simple.py").write_text("print('manager')\n", encoding="utf-8")
    wenv_abs = tmp_path / "wenv" / "simple_worker"
    env = SimpleNamespace(
        active_app=app_path,
        wenv_abs=wenv_abs,
        app="simple_project",
        target="simple",
        target_worker="simple_worker",
        install_type=1,
        is_source_env=False,
        python_version="3.13",
        pyvers_worker="3.13",
        uv="uv",
        uv_worker="uv",
    )

    _seed_venv_python(app_path)
    module._write_install_state(env, modes_enabled=6, scheduler="127.0.0.1")

    assert module._install_state_matches(env, modes_enabled=6, scheduler="127.0.0.1") == (
        True,
        "install fingerprint unchanged",
    )


def test_validate_app_definition_accepts_declared_workerless_app_without_worker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_installer(monkeypatch, tmp_path)
    app_path = tmp_path / "simple_project"
    manager_path = app_path / "src" / "simple" / "simple.py"
    manager_path.parent.mkdir(parents=True)
    manager_path.write_text("class Simple: ...\n", encoding="utf-8")
    pyproject = app_path / "pyproject.toml"
    pyproject.write_text(
        "[project]\nname='simple-project'\n\n[tool.agilab.app]\nruntime='local'\nworkerless=true\n",
        encoding="utf-8",
    )
    env = SimpleNamespace(
        is_worker_env=False,
        active_app=app_path,
        app="simple_project",
        manager_pyproject=pyproject,
        manager_path=manager_path,
        worker_path=app_path / "src" / "simple_worker" / "simple_worker.py",
        target_worker_class="SimpleWorker",
        base_worker_cls=None,
    )

    module.validate_app_definition(env)


def test_install_state_cache_misses_when_dataset_payload_is_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_installer(monkeypatch, tmp_path)
    monkeypatch.setenv("AGILAB_INSTALL_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(module, "_uv_version", lambda _uv: "uv test")

    app_path = tmp_path / "demo_project"
    (app_path / "src" / "demo_worker").mkdir(parents=True)
    (app_path / "pyproject.toml").write_text("[project]\nname='demo-project'\n", encoding="utf-8")
    dataset_archive = app_path / "src" / "demo_worker" / "dataset.7z"
    dataset_archive.write_bytes(b"archive")
    wenv_abs = tmp_path / "wenv" / "demo_worker"
    share_root = tmp_path / "share"
    data_root = share_root / "demo"
    data_root.mkdir(parents=True)

    env = SimpleNamespace(
        active_app=app_path,
        wenv_abs=wenv_abs,
        app="demo_project",
        target="demo",
        target_worker="demo_worker",
        install_type=1,
        is_source_env=False,
        python_version="3.13",
        pyvers_worker="3.13",
        uv="uv",
        uv_worker="uv",
        dataset_archive=dataset_archive,
        app_data_rel="demo",
        share_root_path=lambda: share_root,
    )
    _seed_venv_python(app_path)
    _seed_venv_python(wenv_abs)
    module._write_install_state(env, modes_enabled=6, scheduler="127.0.0.1")

    hit, reason = module._install_state_matches(env, modes_enabled=6, scheduler="127.0.0.1")

    assert hit is False
    assert reason == f"dataset payload missing at {data_root}"

    (data_root / "seeded.csv").write_text("ok\n", encoding="utf-8")

    assert module._install_state_matches(env, modes_enabled=6, scheduler="127.0.0.1") == (
        True,
        "install fingerprint unchanged",
    )


def test_install_main_skips_agi_install_on_cache_hit(tmp_path: Path, monkeypatch) -> None:
    module = _load_installer(monkeypatch, tmp_path)
    app_path = tmp_path / "demo_project"
    wenv_abs = tmp_path / "wenv" / "demo_worker"
    env = SimpleNamespace(active_app=app_path, wenv_abs=wenv_abs)
    calls: list[str] = []

    class FakeAGI:
        DASK_MODE = 4
        CYTHON_MODE = 2

        @staticmethod
        async def install(**_kwargs):
            calls.append("install")

    monkeypatch.setattr(sys, "argv", ["install.py", str(app_path)])
    monkeypatch.setattr(module, "AgiEnv", lambda **_kwargs: env)
    monkeypatch.setattr(module, "AGI", FakeAGI)
    monkeypatch.setattr(module, "ensure_data_storage", lambda _env: None)
    monkeypatch.setattr(module, "validate_app_definition", lambda _env: None)
    monkeypatch.setattr(module, "_install_state_matches", lambda *_args, **_kwargs: (True, "test hit"))

    assert asyncio.run(module.main()) == 0
    assert calls == []


def test_install_main_syncs_workerless_app_without_agi_install(tmp_path: Path, monkeypatch) -> None:
    module = _load_installer(monkeypatch, tmp_path)
    app_path = tmp_path / "simple_project"
    manager_path = app_path / "src" / "simple" / "simple.py"
    manager_path.parent.mkdir(parents=True)
    manager_path.write_text("class Simple: ...\n", encoding="utf-8")
    pyproject = app_path / "pyproject.toml"
    pyproject.write_text(
        "[project]\nname='simple-project'\n\n[tool.agilab.app]\nruntime='local'\nworkerless=true\n",
        encoding="utf-8",
    )
    env = SimpleNamespace(
        is_worker_env=False,
        active_app=app_path,
        app="simple_project",
        manager_pyproject=pyproject,
        manager_path=manager_path,
        worker_path=app_path / "src" / "simple_worker" / "simple_worker.py",
        target_worker_class="SimpleWorker",
        base_worker_cls=None,
        wenv_abs=tmp_path / "wenv" / "simple_worker",
    )
    calls: list[str] = []

    class FakeAGI:
        DASK_MODE = 4
        CYTHON_MODE = 2

        @staticmethod
        async def install(**_kwargs):
            calls.append("install")

    monkeypatch.setattr(sys, "argv", ["install.py", str(app_path)])
    monkeypatch.setattr(module, "AgiEnv", lambda **_kwargs: env)
    monkeypatch.setattr(module, "AGI", FakeAGI)
    monkeypatch.setattr(module, "ensure_data_storage", lambda _env: None)
    monkeypatch.setattr(module, "_install_state_matches", lambda *_args, **_kwargs: (False, "test miss"))
    monkeypatch.setattr(module, "_write_install_state", lambda *_args, **_kwargs: calls.append("state"))
    monkeypatch.setattr(module, "sync_workerless_manager_env", lambda _env: calls.append("sync"))

    assert asyncio.run(module.main()) == 0
    assert calls == ["sync", "state"]


def test_packaged_agi_example_scripts_are_compile_safe() -> None:
    scripts = sorted(EXAMPLES_ROOT.glob("*/AGI_*.py"))

    assert scripts
    for script in scripts:
        py_compile.compile(str(script), doraise=True)


def test_packaged_agi_example_scripts_avoid_cython_first_run_mode() -> None:
    scripts = sorted(EXAMPLES_ROOT.glob("*/AGI_*.py"))

    assert scripts
    for script in scripts:
        text = script.read_text(encoding="utf-8")
        assert "AGI.CYTHON_MODE" not in text


def test_packaged_preview_example_scripts_are_compile_safe() -> None:
    scripts = [
        EXAMPLES_ROOT / example_name / script_name
        for example_name, script_names in EXAMPLE_PREVIEWS.items()
        for script_name in script_names
        if script_name.endswith(".py")
    ]

    assert scripts
    for script in scripts:
        py_compile.compile(str(script), doraise=True)


def test_excel_workbook_proof_preview_writes_workbook_refresh_and_evidence(tmp_path: Path) -> None:
    script = EXAMPLES_ROOT / "excel_workbook_proof" / "preview_excel_workbook_proof.py"
    spec = importlib.util.spec_from_file_location("excel_workbook_proof_preview_test", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    preview = module.build_preview(output_dir=tmp_path)

    proof_workbook = tmp_path / "sales_proof_workbook.xlsx"
    evidence_path = tmp_path / "agilab_evidence.json"
    assert proof_workbook.is_file()
    assert (tmp_path / "input_sales_workbook.xlsx").is_file()
    assert (tmp_path / "power_query_refresh" / "sales_input.csv").is_file()
    assert (tmp_path / "power_query_refresh" / "sales_summary.csv").is_file()
    assert evidence_path.is_file()
    with ZipFile(proof_workbook) as archive:
        names = set(archive.namelist())
        assert "xl/workbook.xml" in names
        assert "xl/worksheets/sheet3.xml" in names
        workbook_xml = archive.read("xl/workbook.xml").decode("utf-8")
    assert "AGILAB Evidence" in workbook_xml
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["schema"] == module.SCHEMA
    assert evidence["artifacts"]["proof_workbook"]["sha256"] == preview["artifacts"]["proof_workbook"]["sha256"]
    assert evidence["office_add_in_required"] is False


def test_sqlite_connector_proof_preview_writes_database_csv_and_evidence(tmp_path: Path) -> None:
    script = EXAMPLES_ROOT / "sqlite_connector_proof" / "preview_sqlite_connector_proof.py"
    spec = importlib.util.spec_from_file_location("sqlite_connector_proof_preview_test", script)

    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    preview = module.build_preview(output_dir=tmp_path, min_accuracy=0.91)

    database_path = tmp_path / "sqlite_connector_proof.db"
    csv_path = tmp_path / "promotion_candidates.csv"
    evidence_path = tmp_path / "database_evidence.json"
    assert database_path.is_file()
    assert csv_path.is_file()
    assert evidence_path.is_file()

    with sqlite3.connect(database_path) as connection:
        run_count = connection.execute("SELECT COUNT(*) FROM experiment_runs").fetchone()[0]
        gate_count = connection.execute("SELECT COUNT(*) FROM quality_gates").fetchone()[0]
    assert run_count == 4
    assert gate_count == 4

    csv_text = csv_path.read_text(encoding="utf-8")
    assert csv_text.splitlines()[0] == "run_id,app,dataset,accuracy,latency_ms,gate"
    assert "run-004,pytorch_playground_project,circles,0.947,64.8,promotion_gate" in csv_text
    assert "run-003" not in csv_text

    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["schema"] == module.SCHEMA
    assert evidence["connector"]["kind"] == "sql"
    assert evidence["connector"]["driver"] == "sqlite"
    assert evidence["connector"]["query_mode"] == "read_only"
    assert evidence["connector"]["network_required"] is False
    assert evidence["connector"]["secrets_required"] is False
    assert evidence["query"]["parameterized"] is True
    assert evidence["query"]["parameters"] == {"min_accuracy": 0.91}
    assert evidence["result"]["row_count"] == 3
    assert evidence["database"]["schema_sha256"] == preview["database"]["schema_sha256"]
    assert evidence["artifacts"]["database"]["sha256"] == preview["artifacts"]["database"]["sha256"]


def test_voila_notebook_proof_preview_writes_notebook_view_plan_and_evidence(
    tmp_path: Path,
) -> None:
    script = EXAMPLES_ROOT / "voila_notebook_proof" / "preview_voila_notebook_proof.py"
    spec = importlib.util.spec_from_file_location("voila_notebook_proof_preview_test", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    preview = module.build_preview(output_dir=tmp_path)

    notebook = json.loads((tmp_path / "dashboard.ipynb").read_text(encoding="utf-8"))
    contract = json.loads((tmp_path / "widget_to_args.json").read_text(encoding="utf-8"))
    plan = json.loads((tmp_path / "agilab_app_view_plan.json").read_text(encoding="utf-8"))
    evidence = json.loads((tmp_path / "voila_notebook_evidence.json").read_text(encoding="utf-8"))

    assert notebook["nbformat"] == 4
    assert any("ipywidgets" in "".join(cell.get("source", [])) for cell in notebook["cells"])
    assert contract["app_args"]["region"]["widget"] == "Dropdown"
    assert "notebooks/dashboard.ipynb" in plan["app_owned_files"]
    assert plan["shared_pages_boundary"][0]["component"] == "view_app_ui"
    assert evidence["schema"] == module.SCHEMA
    assert evidence["voila_dependency_required_for_preview"] is False
    assert (
        evidence["artifacts"]["dashboard_notebook"]["sha256"]
        == preview["artifacts"]["dashboard_notebook"]["sha256"]
    )
    assert preview["artifacts"]["evidence"]["path"] == "voila_notebook_evidence.json"


def test_native_rust_worker_preview_writes_pyo3_project_and_evidence(tmp_path: Path) -> None:
    script = EXAMPLES_ROOT / "native_rust_worker" / "preview_native_rust_worker.py"
    spec = importlib.util.spec_from_file_location("native_rust_worker_preview_test", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    preview = module.build_preview(output_dir=tmp_path)

    rust_worker = tmp_path / "rust_worker"
    evidence_path = tmp_path / "native_rust_worker_evidence.json"
    rust_source = rust_worker / "src" / "lib.rs"
    pyproject = rust_worker / "pyproject.toml"
    assert evidence_path.is_file()
    assert rust_source.is_file()
    assert pyproject.is_file()
    assert (rust_worker / "Cargo.toml").is_file()
    assert (rust_worker / "worker_wrapper.py").is_file()
    assert (rust_worker / "sample_payload.json").is_file()
    assert (rust_worker / "python" / "agilab_native_worker_demo" / "__init__.py").is_file()
    assert "build-backend = \"maturin\"" in pyproject.read_text(encoding="utf-8")
    assert "#[pyfunction]" in rust_source.read_text(encoding="utf-8")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["schema"] == module.SCHEMA
    assert evidence["base_install_impact"] == "none"
    assert evidence["requires_rust_toolchain_for_native_run"] is True
    assert evidence["recommended_build_backend"] == "maturin"
    assert evidence["python_binding"] == "PyO3"
    assert evidence["python_reference"]["checksum"] == preview["python_reference"]["checksum"]
    assert "rust_lib" in evidence["artifacts"]


def test_native_rust_worker_preview_cli_and_reference_validation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = EXAMPLES_ROOT / "native_rust_worker" / "preview_native_rust_worker.py"
    spec = importlib.util.spec_from_file_location("native_rust_worker_preview_cli_test", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    assert module.python_reference_score([1.0], [2.0], 0) == 0.0
    with pytest.raises(ValueError, match="same length"):
        module.python_reference_score([1.0], [], 1)

    cli_output = tmp_path / "cli-preview"
    monkeypatch.setattr(sys, "argv", [script.name, "--output-dir", str(cli_output)])
    module.main()
    printed = json.loads(capsys.readouterr().out)

    assert printed["schema"] == module.SCHEMA
    assert printed["artifacts"]["evidence"]["path"] == str(cli_output / "native_rust_worker_evidence.json")

    script_output = tmp_path / "script-preview"
    monkeypatch.setattr(sys, "argv", [script.name, "--output-dir", str(script_output)])
    runpy.run_path(str(script), run_name="__main__")
    printed_from_script = json.loads(capsys.readouterr().out)

    assert printed_from_script["schema"] == module.SCHEMA
    assert printed_from_script["artifacts"]["evidence"]["path"] == str(
        script_output / "native_rust_worker_evidence.json"
    )


def test_packaged_agi_example_catalog_matches_seeded_scripts() -> None:
    scripts = sorted(EXAMPLES_ROOT.glob("*/AGI_*.py"))

    assert scripts == _expected_script_paths()


def test_packaged_example_catalog_has_no_deprecated_alias_dirs() -> None:
    existing = {path.name for path in EXAMPLES_ROOT.iterdir() if path.is_dir()}

    assert DEPRECATED_EXAMPLE_DIR_NAMES.isdisjoint(existing)


def test_packaged_example_catalog_is_documented() -> None:
    catalog = EXAMPLES_ROOT / "README.md"
    assert catalog.is_file()
    catalog_text = catalog.read_text(encoding="utf-8")
    assert "## Learning Path" in catalog_text
    assert "## Execution Map" in catalog_text
    assert "## What To Notice" in catalog_text
    assert "## Validate The Examples" in catalog_text
    assert "## How To Read An Example" in catalog_text

    for example_name, script_names in EXAMPLE_APPS.items():
        example_dir = EXAMPLES_ROOT / example_name
        readme = example_dir / "README.md"
        assert readme.is_file()
        readme_text = readme.read_text(encoding="utf-8")
        assert example_name in catalog_text
        for script_name in script_names:
            assert (example_dir / script_name).is_file()
            assert script_name in readme_text
        for heading in (
            "## Purpose",
            "## Example Class",
            "## What You Learn",
            "## Install",
            "## Run",
            "## Expected Input",
            "## Expected Output",
            "## Read The Script",
            "## Change One Thing",
            "## Troubleshooting",
        ):
            assert heading in readme_text

    for example_name, file_names in EXAMPLE_PREVIEWS.items():
        example_dir = EXAMPLES_ROOT / example_name
        readme = example_dir / "README.md"
        assert readme.is_file()
        readme_text = readme.read_text(encoding="utf-8")
        assert example_name in catalog_text
        for file_name in file_names:
            assert (example_dir / file_name).is_file()
            assert file_name in readme_text
        assert "uv --preview-features extra-build-dependencies run python" in readme_text
        assert not any(
            line.startswith("python src/agilab/examples/")
            for line in readme_text.splitlines()
        )
        for heading in (
            "## Purpose",
            "## Example Class",
            "## What You Learn",
            "## Install",
            "## Run",
            "## Expected Input",
            "## Expected Output",
            "## Read The Script",
            "## Change One Thing",
            "## Troubleshooting",
        ):
            assert heading in readme_text

    for example_name, file_names in EXAMPLE_NOTEBOOK_ASSETS.items():
        example_dir = EXAMPLES_ROOT / example_name
        readme = example_dir / "README.md"
        assert readme.is_file()
        readme_text = readme.read_text(encoding="utf-8")
        assert example_name in catalog_text
        for file_name in file_names:
            assert (example_dir / file_name).is_file()
        for heading in (
            "## Purpose",
            "## Example Class",
            "## What You Learn",
            "## Install",
            "## Run",
            "## Expected Input",
            "## Expected Output",
            "## Read The Notebook",
            "## Change One Thing",
            "## Troubleshooting",
        ):
            assert heading in readme_text

    learning_path = catalog_text.split("## Learning Path", 1)[1].split("## Execution Map", 1)[0]
    assert "`multi_app_dag_project`" not in learning_path
    assert "Built-in app-owned demo templates" in catalog_text


def test_packaged_example_readmes_have_explicit_execution_class() -> None:
    expected_classes = {
        **{example_name: "Runnable app project" for example_name in EXAMPLE_APPS},
        **{example_name: "Read-only preview" for example_name in EXAMPLE_PREVIEWS},
        **{example_name: "Notebook import asset" for example_name in EXAMPLE_NOTEBOOK_ASSETS},
    }

    for example_name in _packaged_example_dirs():
        if example_name == "notebook_migrations":
            continue
        assert example_name in expected_classes

    for example_name, expected_class in sorted(expected_classes.items()):
        readme_text = (EXAMPLES_ROOT / example_name / "README.md").read_text(encoding="utf-8")
        assert "## Example Class" in readme_text
        assert f"**{expected_class}.**" in readme_text
        for other_class in EXAMPLE_CLASS_LABELS - {expected_class}:
            assert f"**{other_class}.**" not in readme_text


def test_packaged_example_catalog_has_rendered_docs_page() -> None:
    assert EXAMPLE_CATALOG_DOC.is_file()
    catalog_text = EXAMPLE_CATALOG_DOC.read_text(encoding="utf-8")
    index_text = DOCS_INDEX.read_text(encoding="utf-8")

    assert "Packaged examples <packaged-examples>" in index_text
    assert "Packaged example catalog" in catalog_text
    assert "src/agilab/examples" in catalog_text
    for example_name in _packaged_example_dirs():
        assert f"``{example_name}``" in catalog_text


def test_packaged_example_readmes_teach_safe_adaptation() -> None:
    for example_name in EXAMPLE_APPS:
        readme_text = (EXAMPLES_ROOT / example_name / "README.md").read_text(encoding="utf-8")

        assert "RunRequest" in readme_text
        assert "Change One Thing" in readme_text
        assert "Troubleshooting" in readme_text
        assert "Expected Output" in readme_text


def test_packaged_example_readmes_are_included_as_package_data() -> None:
    package_data = _agi_apps_package_data("agilab.examples")

    assert "README.md" in package_data
    assert "*/README.md" in package_data
    assert "*/AGI_*.py" in package_data
    assert "excel_workbook_proof/*.py" in package_data
    assert "inter_project_dag/*.py" in package_data
    assert "mlflow_auto_tracking/*.py" in package_data
    assert "native_rust_worker/*.py" in package_data
    assert "notebook_to_dask/*.py" in package_data
    assert "notebook_to_dask/*.json" in package_data
    assert "notebook_to_dask/*.toml" in package_data
    assert "notebook_to_dask/*.ipynb" in package_data
    assert "voila_notebook_proof/*.py" in package_data
    assert "notebook_quickstart/*.ipynb" in package_data
    assert "notebook_migrations/*/README.md" in package_data
    assert "notebook_migrations/*/analysis_artifacts/*.csv" in package_data
    assert "notebook_migrations/*/analysis_artifacts/*.json" in package_data
    assert "notebook_migrations/*/data/*.csv" in package_data
    assert "notebook_migrations/*/migrated_project/*.dot" in package_data
    assert "notebook_migrations/*/migrated_project/*.toml" in package_data
    assert "notebook_migrations/*/notebooks/*.ipynb" in package_data
    assert "resilience_failure_injection/*.py" in package_data
    assert "service_mode/*.py" in package_data
    assert "sqlite_connector_proof/*.py" in package_data
    assert "train_then_serve/*.py" in package_data


def test_root_package_does_not_embed_builtin_apps_examples_or_pages() -> None:
    package_data = _root_package_data()

    assert "apps/install.py" not in package_data
    assert not any(pattern.startswith("apps/builtin/") for pattern in package_data)
    assert not any(pattern.startswith("examples/") for pattern in package_data)
    assert not any(pattern.startswith("apps-pages/") for pattern in package_data)


def test_agi_pages_package_exposes_analysis_page_provider_and_umbrella_dependencies() -> None:
    package_data = _agi_pages_package_data()
    pyproject = tomllib.loads(AGI_PAGES_PYPROJECT.read_text(encoding="utf-8"))
    dependencies = set(pyproject["project"]["dependencies"])
    dependency_text = " ".join(dependencies)

    assert (APPS_PAGES_ROOT / "README.md").is_file()
    assert (APPS_PAGES_ROOT / "__init__.py").is_file()
    assert (APPS_PAGES_ROOT / "view_maps" / "pyproject.toml").is_file()
    assert not any(pattern.startswith("*/") for pattern in package_data)
    assert not any("src" in pattern for pattern in package_data)
    assert (AGI_PAGES_SOURCE_PACKAGE / "__init__.py").is_file()
    source_text = (AGI_PAGES_SOURCE_PACKAGE / "__init__.py").read_text(encoding="utf-8")
    assert "PAGE_BUNDLE_ENTRYPOINT_GROUP" in source_text
    assert "PUBLIC_PAGE_MODULES" in source_text
    assert "view_maps" in source_text
    assert any(dependency.startswith("agi-gui==") for dependency in dependencies)
    assert all(
        f"{distribution}==" not in dependency_text
        for distribution, _ in PAGE_BUNDLE_PACKAGE_SPECS
    )
    assert pyproject["tool"]["setuptools"]["package-dir"] == {"": "src"}
    assert pyproject["tool"]["setuptools"]["packages"] == ["agi_pages"]


def test_per_app_project_packages_expose_self_contained_project_payloads() -> None:
    missing_entry_points: list[str] = []

    for distribution, _project_path in APP_PROJECT_PACKAGE_SPECS:
        pyproject = _agi_app_project_pyproject(distribution)
        import_package = distribution.replace("-", "_")
        project_name = APP_PROJECT_BY_DISTRIBUTION[distribution]
        slug = project_name.removesuffix("_project")

        assert pyproject["tool"]["setuptools"]["packages"] == [import_package]
        assert pyproject["tool"]["setuptools"]["package-data"][import_package] == ["project/**/*"]
        entry_points = pyproject["project"]["entry-points"]["agilab.apps"]
        if slug not in entry_points or project_name not in entry_points:
            missing_entry_points.append(distribution)

    assert not missing_entry_points


def test_per_app_project_package_readmes_are_useful_for_pypi() -> None:
    for distribution, project_path in APP_PROJECT_PACKAGE_SPECS:
        package_dir = ROOT / project_path
        readme = (package_dir / "README.md").read_text(encoding="utf-8")
        pyproject = _agi_app_project_pyproject(distribution)
        project_name = APP_PROJECT_BY_DISTRIBUTION[distribution]
        description = pyproject["project"]["description"]

        assert len(readme.split()) >= 160, distribution
        for section in APP_PACKAGE_README_REQUIRED_SECTIONS:
            assert section in readme, f"{distribution}: missing {section}"
        assert f"pip install {distribution}" in readme
        assert project_name in readme
        assert f'AgiEnv(app="{project_name}")' in readme
        assert "Most users install these app packages through the umbrella" not in readme
        assert "## Install\n\n```bash" in readme
        assert len(description.split()) >= 7, distribution
        assert "app project" not in description.lower()


def test_per_app_project_package_python_floor_matches_payload() -> None:
    for distribution, _project_path in APP_PROJECT_PACKAGE_SPECS:
        package_pyproject = _agi_app_project_pyproject(distribution)
        project_name = APP_PROJECT_BY_DISTRIBUTION[distribution]
        payload_pyproject = _builtin_project_pyproject(project_name)
        package_floor = _python_floor(package_pyproject["project"]["requires-python"])
        payload_floor = _python_floor(payload_pyproject["project"]["requires-python"])

        assert package_floor == payload_floor, distribution

        advertised_versions = {
            tuple(int(part) for part in classifier.rsplit(" :: ", 1)[-1].split("."))
            for classifier in package_pyproject["project"]["classifiers"]
            if classifier.startswith("Programming Language :: Python :: 3.")
        }
        assert advertised_versions
        assert min(advertised_versions) >= package_floor
        assert package_floor in advertised_versions


def test_builtin_app_worker_python_floor_matches_manager_payload() -> None:
    for distribution, _project_path in APP_PROJECT_PACKAGE_SPECS:
        project_name = APP_PROJECT_BY_DISTRIBUTION[distribution]
        project_root = BUILTIN_APPS_ROOT / project_name
        manager_floor = _python_floor(_builtin_project_pyproject(project_name)["project"]["requires-python"])
        worker_manifests = sorted(project_root.glob("src/*_worker/pyproject.toml"))

        assert worker_manifests, distribution
        for worker_manifest in worker_manifests:
            worker_pyproject = tomllib.loads(worker_manifest.read_text(encoding="utf-8"))
            worker_floor = _python_floor(worker_pyproject["project"]["requires-python"])
            assert worker_floor == manager_floor, worker_manifest.relative_to(ROOT).as_posix()


def test_app_project_payload_copy_produces_self_contained_project_dirs(tmp_path: Path) -> None:
    support = _load_app_project_build_support()

    for distribution, _project_path in APP_PROJECT_PACKAGE_SPECS:
        project_name = APP_PROJECT_BY_DISTRIBUTION[distribution]
        target_root = tmp_path / distribution / "project"

        changed = support.copy_app_project_payload(project_name, target_root)

        payload_root = target_root / project_name
        assert payload_root.is_dir(), distribution
        for rel_path in (
            "README.md",
            "pyproject.toml",
            "src/app_args_form.py",
            "src/app_settings.toml",
            "src/pre_prompt.json",
        ):
            assert (payload_root / rel_path).is_file(), f"{distribution}: missing {rel_path}"
        assert any((payload_root / "src").glob("*/__init__.py")), distribution
        assert list((payload_root / "src").glob("*_worker/pyproject.toml")), distribution
        assert not any(part.name in APP_GENERATED_DIRS for part in payload_root.rglob("*") if part.is_dir())
        assert not any(part.name in APP_GENERATED_NAMES for part in payload_root.rglob("*") if part.is_file())
        assert not any(part.suffix in APP_GENERATED_SUFFIXES for part in payload_root.rglob("*") if part.is_file())
        assert not list(payload_root.rglob("uv.lock"))
        assert changed, f"{distribution}: expected packaged pyproject source sanitization"
        for pyproject_path in payload_root.rglob("pyproject.toml"):
            assert "[tool.uv.sources]" not in pyproject_path.read_text(encoding="utf-8")


def test_agi_apps_umbrella_bundles_only_the_base_minimal_app_template() -> None:
    pyproject = tomllib.loads(AGI_APPS_PYPROJECT.read_text(encoding="utf-8"))
    package_data = pyproject["tool"]["setuptools"]["package-data"]
    dependencies = pyproject["project"]["dependencies"]

    assert "install.py" in package_data["agilab.apps"]
    builtin_patterns = [
        pattern for pattern in package_data["agilab.apps"] if pattern.startswith("builtin/")
    ]
    assert builtin_patterns == ["builtin/minimal_app_project/**/*"]
    dependency_text = " ".join(dependencies)
    assert all(f"{distribution}==" in dependency_text for distribution in PROMOTED_APP_PROJECT_PACKAGE_NAMES)
    assert all(
        f"{distribution}==" not in dependency_text
        for distribution, _ in APP_PROJECT_PACKAGE_SPECS
        if distribution not in PROMOTED_APP_PROJECT_PACKAGE_NAMES
    )


def test_agi_apps_catalog_matches_per_app_packages() -> None:
    catalog = json.loads((ROOT / "src/agilab/lib/agi-apps/src/agi_apps/catalog.json").read_text(encoding="utf-8"))
    catalog_distributions = [item["distribution"] for item in catalog]

    assert catalog_distributions == [distribution for distribution, _ in APP_PROJECT_PACKAGE_SPECS]


def test_agi_apps_umbrella_copy_keeps_only_minimal_app_builtin_payload(tmp_path: Path) -> None:
    support = _load_app_project_build_support()

    support.copy_agi_apps_umbrella_payload(tmp_path)

    builtin_root = tmp_path / "agilab" / "apps" / "builtin"
    assert (builtin_root / "minimal_app_project" / "pyproject.toml").is_file()
    assert not (builtin_root / "flight_telemetry_project").exists()
    assert not (builtin_root / "minimal_app_project" / ".venv").exists()
    assert not (builtin_root / "minimal_app_project" / "uv.lock").exists()
    assert not list((builtin_root / "minimal_app_project").rglob("*.pyx"))
    assert not list((builtin_root / "minimal_app_project").rglob("*.c"))


def test_agilab_apps_init_exposes_builtin_namespace_without_stale_docstring_code() -> None:
    module_path = ROOT / "src/agilab/apps/__init__.py"
    module_name = "agilab_apps_init_contract_test"
    spec = importlib.util.spec_from_file_location(
        module_name,
        module_path,
        submodule_search_locations=[str(module_path.parent)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)

    doc = module.__doc__ or ""
    assert "from __future__" not in doc
    assert "if _BUILTIN_DIR.is_dir()" not in doc
    assert list(module.__path__).count(str(BUILTIN_APPS_ROOT)) == 1


def test_preview_example_payloads_live_with_builtin_apps() -> None:
    for path in BUILTIN_EXAMPLE_PAYLOADS.values():
        assert path.is_file()

    assert not (EXAMPLES_ROOT / "multi_app_dag").exists()
    for example_name in BUILTIN_EXAMPLE_PAYLOADS:
        assert not sorted((EXAMPLES_ROOT / example_name).glob("*.json"))


def test_inter_project_dag_preview_builds_read_only_runner_state(tmp_path: Path) -> None:
    script = EXAMPLES_ROOT / "inter_project_dag" / "preview_inter_project_dag.py"
    module_name = "agilab_inter_project_dag_preview_test_module"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    summary = module.build_preview(
        repo_root=ROOT,
        dag_path=BUILTIN_EXAMPLE_PAYLOADS["inter_project_dag"],
        output_path=tmp_path / "runner_state.json",
        now="2026-04-29T00:00:00Z",
    )

    assert summary["example"] == "inter_project_dag"
    assert summary["dag"]["ok"] is True
    assert summary["dag"]["execution_order"] == ["flight_context", "weather_forecast_review"]
    assert summary["units"] == [
        {
            "app": "flight_telemetry_project",
            "depends_on": [],
            "dispatch_status": "runnable",
            "id": "flight_context",
            "produces": ["flight_reduce_summary"],
        },
        {
            "app": "weather_forecast_project",
            "depends_on": ["flight_context"],
            "dispatch_status": "blocked",
            "id": "weather_forecast_review",
            "produces": ["forecast_metrics"],
        },
    ]
    assert summary["artifact_handoffs"] == [
        {
            "artifact": "flight_reduce_summary",
            "from": "flight_context",
            "from_app": "flight_telemetry_project",
            "handoff": "Use flight trajectory reduce summary as the forecast-review context.",
            "producer_status": "runnable",
            "source_path": "flight_analysis/reduce_summary_worker_0.json",
            "to": "weather_forecast_review",
            "to_app": "weather_forecast_project",
        }
    ]
    assert summary["runner_state"]["round_trip_ok"] is True
    assert summary["runner_state"]["summary"]["runnable_unit_ids"] == ["flight_context"]
    assert summary["runner_state"]["summary"]["blocked_unit_ids"] == ["weather_forecast_review"]
    assert summary["after_first_dispatch"]["dispatched_unit_id"] == "flight_context"
    assert summary["after_first_dispatch"]["run_status"] == "running"
    assert summary["real_app_execution"] is False
    assert (tmp_path / "runner_state.json").is_file()


def test_multi_app_dag_preview_alias_builds_read_only_runner_state(tmp_path: Path) -> None:
    app_root = BUILTIN_APPS_ROOT / "multi_app_dag_project"
    script = app_root / "src" / "multi_app_dag" / "preview_multi_app_dag.py"
    module_name = "agilab_multi_app_dag_preview_test_module"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    summary = module.build_preview(
        repo_root=ROOT,
        dag_path=app_root / "dag_templates" / "flight_to_weather_multi_app_dag.json",
        output_path=tmp_path / "runner_state.json",
        now="2026-04-29T00:00:00Z",
    )

    assert summary["example"] == "multi_app_dag_project"
    assert summary["dag"]["ok"] is True
    assert summary["dag"]["execution_order"] == ["flight_context", "weather_forecast_review"]
    assert summary["after_first_dispatch"]["dispatched_unit_id"] == "flight_context"
    assert summary["real_app_execution"] is False
    assert (tmp_path / "runner_state.json").is_file()


def test_service_mode_preview_builds_health_gate_operator_summary(tmp_path: Path) -> None:
    script = EXAMPLES_ROOT / "service_mode" / "preview_service_mode.py"
    module_name = "agilab_service_mode_preview_test_module"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    summary = module.build_preview(
        health_payload_path=BUILTIN_EXAMPLE_PAYLOADS["service_mode"],
        output_path=tmp_path / "service_operator_preview.json",
    )

    assert summary["example"] == "service_mode"
    assert summary["target_app"] == "minimal_app_project"
    assert [action["action"] for action in summary["operator_sequence"]] == [
        "start",
        "status",
        "health",
        "stop",
    ]
    assert summary["health_gate"] == {
        "details": {
            "restart_rate": 0.0,
            "status": "running",
            "workers_restarted_count": 0,
            "workers_running_count": 1,
            "workers_unhealthy_count": 0,
        },
        "ok": True,
        "reason": "ok",
        "thresholds": {
            "allow_idle": False,
            "max_restart_rate": 0.25,
            "max_unhealthy": 0,
        },
    }
    assert summary["artifacts"]["health_json"] == "service/minimal_app/health.json"
    assert summary["real_service_execution"] is False
    assert (tmp_path / "service_operator_preview.json").is_file()


def test_mlflow_auto_tracking_preview_writes_local_evidence_without_mlflow(tmp_path: Path) -> None:
    script = EXAMPLES_ROOT / "mlflow_auto_tracking" / "preview_mlflow_auto_tracking.py"
    module_name = "agilab_mlflow_auto_tracking_preview_test_module"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    summary = module.run_preview(
        config_path=BUILTIN_EXAMPLE_PAYLOADS["mlflow_auto_tracking"],
        output_dir=tmp_path / "mlflow_auto_tracking",
        backend="none",
    )

    assert summary["example"] == "mlflow_auto_tracking"
    assert summary["tracker_backend"] == "none"
    assert summary["tracking"]["status"] == "skipped"
    assert summary["registry_created_by_agilab"] is False
    assert summary["logged_metrics"] == ["coverage_ratio", "forecast_mae", "forecast_rmse"]
    run_summary = Path(summary["local_evidence"]["run_summary"])
    assert run_summary.is_file()
    artifact = json.loads(run_summary.read_text(encoding="utf-8"))
    assert artifact["app"] == "weather_forecast_project"
    assert artifact["pipeline"] == "notebook_migration_forecast"
    assert (tmp_path / "mlflow_auto_tracking" / "mlflow_tracking_preview.json").is_file()


def test_resilience_failure_injection_preview_recommends_adaptive_response(tmp_path: Path) -> None:
    script = EXAMPLES_ROOT / "resilience_failure_injection" / "preview_resilience_failure_injection.py"
    module_name = "agilab_resilience_failure_injection_preview_test_module"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    summary = module.build_preview(
        scenario_path=BUILTIN_EXAMPLE_PAYLOADS["resilience_failure_injection"],
        output_path=tmp_path / "resilience_preview.json",
    )

    assert summary["example"] == "resilience_failure_injection"
    assert summary["comparison"]["failure_event"]["id"] == "jam_relay_alpha"
    assert summary["comparison"]["baseline_ranking"][0]["route_id"] == "alpha_fast"
    assert summary["comparison"]["degraded_ranking"][0]["route_id"] == "beta_balanced"
    assert summary["comparison"]["recommended_strategy"]["strategy_id"] == "ppo_active_mesh_policy"
    assert summary["comparison"]["recommended_strategy"]["policy_adjusted"] is True
    fixed_strategy = next(
        item
        for item in summary["comparison"]["strategy_comparison"]
        if item["strategy_id"] == "fixed_low_latency"
    )
    assert fixed_strategy["failure_affected"] is True
    assert fixed_strategy["score_delta"] < 0
    assert summary["real_policy_training"] is False
    assert "certified MARL" in summary["claim_boundary"]
    assert (tmp_path / "resilience_preview.json").is_file()


def test_sklearn_pipeline_app_writes_model_metrics_and_manifest(tmp_path: Path) -> None:
    script = BUILTIN_APPS_ROOT / "sklearn_pipeline_project" / "src" / "sklearn_pipeline" / "core.py"
    module_name = "agilab_sklearn_pipeline_core_test_module"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    summary = module.build_sklearn_pipeline_artifacts(output_dir=tmp_path, seed=2026, sample_count=120)

    metrics = json.loads((tmp_path / "metrics.json").read_text(encoding="utf-8"))
    manifest = json.loads((tmp_path / "run_manifest.json").read_text(encoding="utf-8"))
    summary_payload = json.loads((tmp_path / "sklearn_pipeline_summary.json").read_text(encoding="utf-8"))
    predictions = (tmp_path / "predictions.csv").read_text(encoding="utf-8").splitlines()

    assert metrics["schema"] == module.SCHEMA
    assert metrics["metrics"]["accuracy"] >= 0.8
    assert metrics["metrics"]["f1"] >= 0.8
    assert manifest["app"] == "sklearn_pipeline_project"
    assert manifest["promotion_hint"] in {"candidate", "review"}
    assert manifest["artifacts"]["model"]["path"] == "model.joblib"
    assert manifest["artifacts"]["predictions"]["sha256"] == summary["artifacts"]["predictions"]["sha256"]
    assert summary_payload == summary
    assert summary_payload["artifacts"]["manifest"]["sha256"] == summary["artifacts"]["manifest"]["sha256"]
    assert "summary" not in summary["artifacts"]
    assert (tmp_path / "model.joblib").is_file()
    assert (tmp_path / "sklearn_report.md").is_file()
    assert predictions[0] == "row_id,target,prediction,positive_probability"
    assert len(predictions) == metrics["metrics"]["test_rows"] + 1


def _load_train_then_serve_preview_module():
    script = EXAMPLES_ROOT / "train_then_serve" / "preview_train_then_serve.py"
    module_name = "agilab_train_then_serve_preview_test_module"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_train_then_serve_preview_exports_service_contract(tmp_path: Path) -> None:
    module = _load_train_then_serve_preview_module()

    summary = module.run_preview(
        config_path=BUILTIN_EXAMPLE_PAYLOADS["train_then_serve"],
        output_dir=tmp_path / "train_then_serve",
    )

    assert summary["example"] == "train_then_serve"
    assert summary["selected_relay"] == "relay_beta"
    assert summary["service_ready"] is True
    assert summary["real_training"] is False
    assert summary["real_service_started"] is False

    contract_path = Path(summary["artifacts"]["service_contract"])
    health_path = Path(summary["artifacts"]["service_health"])
    prediction_path = Path(summary["artifacts"]["prediction_sample"])
    assert contract_path.is_file()
    assert health_path.is_file()
    assert prediction_path.is_file()

    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    health = json.loads(health_path.read_text(encoding="utf-8"))
    prediction = json.loads(prediction_path.read_text(encoding="utf-8"))
    assert contract["source_training_run"]["trainer"] == "uav_relay_queue_ppo"
    assert contract["sample_decision"]["selected_relay"] == "relay_beta"
    assert health["schema"] == "agi.service.health.v1"
    assert health["ok"] is True
    assert prediction["decision"]["selected_relay"] == "relay_beta"
    assert (tmp_path / "train_then_serve" / "train_then_serve_preview.json").is_file()


def test_train_then_serve_preview_marks_unhealthy_when_latency_budget_fails(
    tmp_path: Path,
) -> None:
    module = _load_train_then_serve_preview_module()
    config = json.loads(BUILTIN_EXAMPLE_PAYLOADS["train_then_serve"].read_text(encoding="utf-8"))
    config["service"]["health_thresholds"]["latency_budget_ms"] = 50.0
    config_path = tmp_path / "low_latency_budget.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    summary = module.run_preview(
        config_path=config_path,
        output_dir=tmp_path / "train_then_serve",
    )

    health = json.loads(
        Path(summary["artifacts"]["service_health"]).read_text(encoding="utf-8")
    )
    assert summary["selected_relay"] == "relay_beta"
    assert summary["service_ready"] is False
    assert health["latency_budget_ms"] == 50.0
    assert health["sample_latency_ms"] == 55.0
    assert health["latency_ok"] is False
    assert health["ok"] is False


def test_train_then_serve_preview_rejects_invalid_config_shapes(tmp_path: Path) -> None:
    module = _load_train_then_serve_preview_module()
    list_config = tmp_path / "list_config.json"
    list_config.write_text("[]", encoding="utf-8")

    with pytest.raises(SystemExit, match="must be a JSON object"):
        module.load_config(list_config)

    missing_candidates = tmp_path / "missing_candidates.json"
    missing_candidates.write_text(json.dumps({"prediction_request": {}}), encoding="utf-8")

    with pytest.raises(SystemExit, match="candidate_relays"):
        module.run_preview(
            config_path=missing_candidates,
            output_dir=tmp_path / "missing_candidates_output",
        )


def test_train_then_serve_preview_cli_accepts_custom_paths(
    tmp_path: Path,
    capsys,
) -> None:
    module = _load_train_then_serve_preview_module()
    config_path = BUILTIN_EXAMPLE_PAYLOADS["train_then_serve"]
    output_dir = tmp_path / "cli_output"

    summary = module.main(
        ["--config", str(config_path), "--output-dir", str(output_dir)]
    )

    printed = json.loads(capsys.readouterr().out)
    assert summary["selected_relay"] == "relay_beta"
    assert printed["selected_relay"] == "relay_beta"
    assert Path(summary["artifacts"]["service_contract"]).is_file()
    assert (output_dir / "train_then_serve_preview.json").is_file()


def test_notebook_to_dask_preview_builds_migration_contract(tmp_path: Path) -> None:
    script = EXAMPLES_ROOT / "notebook_to_dask" / "preview_notebook_to_dask.py"
    module_name = "agilab_notebook_to_dask_preview_test_module"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    summary = module.build_preview(output_path=tmp_path / "notebook_to_dask_preview.json")

    assert summary["example"] == "notebook_to_dask"
    assert summary["notebook_import"]["execution_mode"] == "not_executed_import"
    assert summary["notebook_import"]["summary"]["pipeline_stage_count"] == 3
    assert summary["notebook_import"]["env_hints"] == ["dask", "json", "pandas", "pathlib"]
    assert summary["artifact_contract"] == {
        "analysis_consumes": [
            "artifacts/daily_orders.parquet",
            "artifacts/dask_summary.json",
        ],
        "inputs": ["data/orders.csv"],
        "outputs": [
            "artifacts/daily_orders.parquet",
            "artifacts/dask_summary.json",
        ],
    }
    assert summary["dask_solution"]["engine"] == "dask.dataframe"
    assert summary["dask_solution"]["stage_ids"] == ["cell-4", "cell-6"]
    assert summary["dask_solution"]["real_execution"] is False
    assert summary["lab_stages_preview"]["matches_generated"] is True
    assert summary["pipeline_view"]["node_count"] == 4
    assert (tmp_path / "notebook_to_dask_preview.json").is_file()


def test_parallel_stage_preview_handles_low_file_count_partitioning(tmp_path: Path) -> None:
    script = EXAMPLES_ROOT / "parallel_stage" / "preview_parallel_stage.py"
    module_name = "agilab_parallel_stage_preview_test_module"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    summary = module.build_preview(
        output_path=tmp_path / "parallel_stage_preview.json",
        available_cores=8,
        file_count=3,
    )

    assert summary["contract_valid"] is True
    assert summary["low_file_count_policy"]["splittable_large_files"]["effective_workers"] == 8
    assert summary["low_file_count_policy"]["splittable_large_files"]["planned_partitions"] == 64
    assert summary["low_file_count_policy"]["unsplittable_small_files"]["effective_workers"] == 3
    assert summary["low_file_count_policy"]["unsplittable_small_files"]["planned_partitions"] == 3
    assert (tmp_path / "parallel_stage_preview.json").is_file()


def test_service_mode_health_gate_rejects_non_running_service() -> None:
    script = EXAMPLES_ROOT / "service_mode" / "preview_service_mode.py"
    module_name = "agilab_service_mode_preview_health_test_module"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    stopped = module.evaluate_health_gate({"status": "stopped", "workers_running_count": 0})
    running_without_workers = module.evaluate_health_gate(
        {"status": "running", "workers_running_count": 0}
    )
    unhealthy = module.evaluate_health_gate(
        {
            "status": "running",
            "workers_running_count": 1,
            "workers_unhealthy_count": 1,
        }
    )

    assert stopped["ok"] is False
    assert stopped["reason"] == "service status is stopped"
    assert running_without_workers["ok"] is False
    assert running_without_workers["reason"] == "service has no running workers"
    assert unhealthy["ok"] is False
    assert unhealthy["reason"] == "unhealthy workers 1 exceeds limit 0"


def test_packaged_examples_avoid_magic_mode_literals() -> None:
    magic_mode_fragments = ("mode=13", "mode=15", "modes_enabled=13", "modes_enabled=15")
    scripts = sorted(EXAMPLES_ROOT.glob("*/AGI_*.py"))

    assert scripts
    for script in scripts:
        text = script.read_text(encoding="utf-8")
        for fragment in magic_mode_fragments:
            assert fragment not in text


def test_packaged_examples_use_public_api_and_modern_runner() -> None:
    for script in _expected_script_paths():
        text = script.read_text(encoding="utf-8")

        assert "AGI._" not in text
        assert "asyncio.get_event_loop()" not in text
        assert "asyncio.run(main())" in text
        assert "def agilab_apps_path() -> Path:" in text
        assert "open(f\"{Path.home()}" not in text


def test_packaged_builtin_examples_resolve_builtin_apps_root() -> None:
    stale_root = 'return Path(marker.read_text(encoding="utf-8").strip()) / "apps"\n'
    current_root = 'return Path(marker.read_text(encoding="utf-8").strip()) / "apps" / "builtin"'

    for script in _expected_script_paths():
        text = script.read_text(encoding="utf-8")

        assert current_root in text
        assert stale_root not in text


def test_seed_example_scripts_refreshes_stale_builtin_helper(tmp_path: Path, monkeypatch) -> None:
    module = _load_installer(monkeypatch, tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    destination = tmp_path / "log" / "execute" / "flight_telemetry" / "AGI_run_flight_telemetry.py"
    destination.parent.mkdir(parents=True)
    destination.write_text(
        "\n".join(
            [
                "from pathlib import Path",
                "",
                "def agilab_apps_path() -> Path:",
                '    marker = Path.home() / ".local/share/agilab/.agilab-path"',
                '    return Path(marker.read_text(encoding="utf-8").strip()) / "apps"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    module._seed_example_scripts("flight_telemetry")

    text = destination.read_text(encoding="utf-8")
    assert ' / "apps" / "builtin"' in text
    assert text == (EXAMPLES_ROOT / "flight_telemetry" / "AGI_run_flight_telemetry.py").read_text(encoding="utf-8")


def test_packaged_run_and_install_examples_import_with_fake_home(tmp_path: Path, monkeypatch) -> None:
    agilab_path = tmp_path / ".local" / "share" / "agilab"
    agilab_path.mkdir(parents=True)
    (agilab_path / ".agilab-path").write_text(str(ROOT / "src/agilab"), encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))

    scripts = sorted(
        script
        for script in EXAMPLES_ROOT.glob("*/AGI_*.py")
        if script.name.startswith(("AGI_install_", "AGI_run_"))
    )

    assert scripts
    for script in scripts:
        module_name = f"agilab_example_{script.parent.name}_{script.stem}"
        sys.modules.pop(module_name, None)
        spec = importlib.util.spec_from_file_location(module_name, script)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        assert callable(module.main)


def test_packaged_examples_fail_cleanly_without_agilab_marker(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    for script in _expected_script_paths():
        module_name = f"agilab_example_missing_marker_{script.parent.name}_{script.stem}"
        sys.modules.pop(module_name, None)
        spec = importlib.util.spec_from_file_location(module_name, script)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        try:
            module.agilab_apps_path()
        except SystemExit as exc:
            assert "AGILAB is not initialized" in str(exc)
        else:
            raise AssertionError(f"{script} did not fail cleanly without .agilab-path")


def test_packaged_example_main_bodies_build_public_requests(tmp_path: Path, monkeypatch) -> None:
    agilab_path = tmp_path / ".local" / "share" / "agilab"
    agilab_path.mkdir(parents=True)
    (agilab_path / ".agilab-path").write_text(str(ROOT / "src/agilab"), encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))

    for script in _expected_script_paths():
        calls: dict[str, object] = {}

        class FakeEnv:
            def __init__(self, **kwargs):
                calls["env_kwargs"] = kwargs

        class FakeAGI:
            @staticmethod
            async def install(env, **kwargs):
                calls["operation"] = "install"
                calls["env"] = env
                calls["kwargs"] = kwargs
                return {"ok": True, "operation": "install"}

            @staticmethod
            async def run(env, request):
                calls["operation"] = "run"
                calls["env"] = env
                calls["request"] = request
                return {"ok": True, "operation": "run"}

        module_name = f"agilab_example_main_{script.parent.name}_{script.stem}"
        sys.modules.pop(module_name, None)
        spec = importlib.util.spec_from_file_location(module_name, script)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        module.AgiEnv = FakeEnv
        module.AGI = FakeAGI

        result = asyncio.run(module.main())

        assert result["ok"] is True
        env_kwargs = calls["env_kwargs"]
        assert env_kwargs["apps_path"] == ROOT / "src/agilab/apps/builtin"
        assert str(env_kwargs["app"]).endswith("_project")
        assert env_kwargs["verbose"] == 1
        if script.name.startswith("AGI_install_"):
            assert calls["operation"] == "install"
            kwargs = calls["kwargs"]
            assert kwargs["scheduler"] == "127.0.0.1"
            assert kwargs["workers"] == {"127.0.0.1": 1}
            assert isinstance(kwargs["modes_enabled"], int)
            assert kwargs["modes_enabled"] > 0
        else:
            assert calls["operation"] == "run"
            request = calls["request"]
            assert request.scheduler == "127.0.0.1"
            assert request.workers == {"127.0.0.1": 1}
            assert request.mode is not None
            assert "args" not in request.params


def test_example_notebooks_use_current_agi_run_request_api() -> None:
    legacy_execution_kwargs = {
        "mode",
        "modes_enabled",
        "rapids_enabled",
        "scheduler",
        "workers",
        "workers_data_path",
    }
    failures: list[str] = []

    for notebook in sorted(EXAMPLES_ROOT.rglob("*.ipynb")):
        payload = json.loads(notebook.read_text(encoding="utf-8"))
        for cell_number, cell in enumerate(payload.get("cells", []), start=1):
            if cell.get("cell_type") != "code":
                continue
            source = "".join(cell.get("source", []))
            try:
                tree = ast.parse(source)
            except SyntaxError as exc:
                failures.append(f"{notebook.relative_to(ROOT)} cell {cell_number}: {exc}")
                continue

            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not (
                    isinstance(func, ast.Attribute)
                    and func.attr == "run"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "AGI"
                ):
                    continue
                bad_kwargs = sorted(
                    keyword.arg
                    for keyword in node.keywords
                    if keyword.arg in legacy_execution_kwargs
                )
                if bad_kwargs:
                    failures.append(
                        f"{notebook.relative_to(ROOT)} cell {cell_number}: "
                        f"AGI.run uses legacy execution kwargs {bad_kwargs}; "
                        "use request=RunRequest(...)"
                    )

    assert not failures, "\n".join(failures)
