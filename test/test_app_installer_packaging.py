from __future__ import annotations

import ast
import asyncio
import importlib.util
import json
import py_compile
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
sys.path.insert(0, str(TOOLS_ROOT))

from package_split_contract import APP_PROJECT_PACKAGE_SPECS

MODULE_PATH = ROOT / "src/agilab/apps/install.py"
ROOT_PYPROJECT = ROOT / "pyproject.toml"
AGI_APPS_PYPROJECT = ROOT / "src/agilab/lib/agi-apps/pyproject.toml"
AGI_PAGES_PYPROJECT = ROOT / "src/agilab/lib/agi-pages/pyproject.toml"
AGI_PAGES_SOURCE_PACKAGE = ROOT / "src/agilab/lib/agi-pages/src/agi_pages"
BUILTIN_APPS_ROOT = ROOT / "src/agilab/apps/builtin"
APP_TEMPLATES_ROOT = ROOT / "src/agilab/apps/templates"
EXAMPLES_ROOT = ROOT / "src/agilab/examples"
APPS_PAGES_ROOT = ROOT / "src/agilab/apps-pages"
EXAMPLE_APPS = {
    "data_io_2026": ("AGI_install_data_io_2026.py", "AGI_run_data_io_2026.py"),
    "flight": ("AGI_install_flight.py", "AGI_run_flight.py"),
    "meteo_forecast": ("AGI_install_meteo_forecast.py", "AGI_run_meteo_forecast.py"),
    "mycode": ("AGI_install_mycode.py", "AGI_run_mycode.py"),
}
EXAMPLE_PREVIEWS = {
    "inter_project_dag": ("preview_inter_project_dag.py",),
    "mlflow_auto_tracking": ("preview_mlflow_auto_tracking.py",),
    "notebook_to_dask": (
        "preview_notebook_to_dask.py",
        "notebook_to_dask_sample.ipynb",
        "lab_stages.toml",
        "pipeline_view.json",
    ),
    "resilience_failure_injection": (
        "preview_resilience_failure_injection.py",
    ),
    "service_mode": ("preview_service_mode.py",),
    "train_then_serve": ("preview_train_then_serve.py",),
}
BUILTIN_EXAMPLE_PAYLOADS = {
    "inter_project_dag": (
        BUILTIN_APPS_ROOT
        / "global_dag_project"
        / "dag_templates"
        / "flight_to_meteo_global_dag.json"
    ),
    "mlflow_auto_tracking": (
        BUILTIN_APPS_ROOT
        / "meteo_forecast_project"
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
        BUILTIN_APPS_ROOT / "mycode_project" / "service_templates" / "sample_health_running.json"
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
}
APP_GENERATED_SUFFIXES = {".c", ".pyc", ".pyo", ".pyx", ".so"}
APP_PROJECT_BY_DISTRIBUTION = {
    "agi-app-data-io-2026-project": "data_io_2026_project",
    "agi-app-execution-pandas-project": "execution_pandas_project",
    "agi-app-execution-polars-project": "execution_polars_project",
    "agi-app-flight-project": "flight_project",
    "agi-app-global-dag-project": "global_dag_project",
    "agi-app-meteo-forecast-project": "meteo_forecast_project",
    "agi-app-mycode-project": "mycode_project",
    "agi-app-tescia-diagnostic-project": "tescia_diagnostic_project",
    "agi-app-uav-queue-project": "uav_queue_project",
    "agi-app-uav-relay-queue-project": "uav_relay_queue_project",
}


def _expected_script_paths() -> list[Path]:
    return sorted(
        EXAMPLES_ROOT / example_name / script_name
        for example_name, script_names in EXAMPLE_APPS.items()
        for script_name in script_names
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
    examples_dir = package_root / "examples" / "flight"
    examples_dir.mkdir(parents=True)
    (examples_dir / "AGI_install_flight.py").write_text("# install\n", encoding="utf-8")
    (examples_dir / "AGI_run_flight.py").write_text("# run\n", encoding="utf-8")
    monkeypatch.setattr(module, "_package_root", lambda: package_root)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    module._seed_example_scripts("flight")

    execute_dir = tmp_path / "home" / "log" / "execute" / "flight"
    assert (execute_dir / "AGI_install_flight.py").read_text(encoding="utf-8") == "# install\n"
    assert (execute_dir / "AGI_run_flight.py").read_text(encoding="utf-8") == "# run\n"


def test_app_dir_candidates_prefer_packaged_builtin_apps(tmp_path: Path, monkeypatch) -> None:
    module = _load_installer(monkeypatch, tmp_path)
    package_root = tmp_path / "site-packages" / "agilab"
    monkeypatch.setattr(module, "_package_root", lambda: package_root)
    monkeypatch.setattr(module, "_installed_app_dir_candidates", lambda app_slug: [])

    assert module._app_dir_candidates("flight") == [
        package_root / "apps" / "builtin" / "flight_project",
        package_root / "apps" / "flight_project",
    ]


def test_app_dir_candidates_include_installed_app_project_packages(tmp_path: Path, monkeypatch) -> None:
    module = _load_installer(monkeypatch, tmp_path)
    package_root = tmp_path / "site-packages" / "agilab"
    installed_root = tmp_path / "site-packages" / "agi_app_flight_project" / "project" / "flight_project"
    monkeypatch.setattr(module, "_package_root", lambda: package_root)
    monkeypatch.setattr(module, "_installed_app_dir_candidates", lambda app_slug: [installed_root])

    assert module._app_dir_candidates("flight")[-1] == installed_root


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


def test_packaged_agi_example_catalog_matches_seeded_scripts() -> None:
    scripts = sorted(EXAMPLES_ROOT.glob("*/AGI_*.py"))

    assert scripts == _expected_script_paths()


def test_packaged_example_catalog_is_documented() -> None:
    catalog = EXAMPLES_ROOT / "README.md"
    assert catalog.is_file()
    catalog_text = catalog.read_text(encoding="utf-8")
    assert "## Learning Path" in catalog_text
    assert "## What To Notice" in catalog_text
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
        for heading in (
            "## Purpose",
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
    assert "inter_project_dag/*.py" in package_data
    assert "mlflow_auto_tracking/*.py" in package_data
    assert "notebook_to_dask/*.py" in package_data
    assert "notebook_to_dask/*.json" in package_data
    assert "notebook_to_dask/*.toml" in package_data
    assert "notebook_to_dask/*.ipynb" in package_data
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
    assert {
        "view-barycentric-graph==0.1.0",
        "view-data-io-decision==0.1.0",
        "view-forecast-analysis==0.1.0",
        "view-inference-analysis==0.1.0",
        "view-maps==0.1.0",
        "view-maps-3d==0.1.0",
        "view-maps-network==0.1.0",
        "view-queue-resilience==0.1.0",
        "view-relay-resilience==0.1.0",
        "view-release-decision==0.1.0",
        "view-training-analysis==0.1.0",
    } <= dependencies
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


def test_agi_apps_is_umbrella_not_builtin_app_payload_package() -> None:
    pyproject = tomllib.loads(AGI_APPS_PYPROJECT.read_text(encoding="utf-8"))
    package_data = pyproject["tool"]["setuptools"]["package-data"]
    dependencies = pyproject["project"]["dependencies"]

    assert "install.py" in package_data["agilab.apps"]
    assert not any(pattern.startswith("builtin/") for pattern in package_data["agilab.apps"])
    assert all(f"{distribution}==" in " ".join(dependencies) for distribution, _ in APP_PROJECT_PACKAGE_SPECS)


def test_agi_apps_catalog_matches_per_app_packages() -> None:
    catalog = json.loads((ROOT / "src/agilab/lib/agi-apps/src/agi_apps/catalog.json").read_text(encoding="utf-8"))
    catalog_distributions = [item["distribution"] for item in catalog]

    assert catalog_distributions == [distribution for distribution, _ in APP_PROJECT_PACKAGE_SPECS]


def test_preview_example_payloads_live_with_builtin_apps() -> None:
    for path in BUILTIN_EXAMPLE_PAYLOADS.values():
        assert path.is_file()

    assert not (EXAMPLES_ROOT / "global_dag").exists()
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
    assert summary["dag"]["execution_order"] == ["flight_context", "meteo_forecast_review"]
    assert summary["units"] == [
        {
            "app": "flight_project",
            "depends_on": [],
            "dispatch_status": "runnable",
            "id": "flight_context",
            "produces": ["flight_reduce_summary"],
        },
        {
            "app": "meteo_forecast_project",
            "depends_on": ["flight_context"],
            "dispatch_status": "blocked",
            "id": "meteo_forecast_review",
            "produces": ["forecast_metrics"],
        },
    ]
    assert summary["artifact_handoffs"] == [
        {
            "artifact": "flight_reduce_summary",
            "from": "flight_context",
            "from_app": "flight_project",
            "handoff": "Use flight trajectory reduce summary as the forecast-review context.",
            "producer_status": "runnable",
            "source_path": "flight_analysis/reduce_summary_worker_0.json",
            "to": "meteo_forecast_review",
            "to_app": "meteo_forecast_project",
        }
    ]
    assert summary["runner_state"]["round_trip_ok"] is True
    assert summary["runner_state"]["summary"]["runnable_unit_ids"] == ["flight_context"]
    assert summary["runner_state"]["summary"]["blocked_unit_ids"] == ["meteo_forecast_review"]
    assert summary["after_first_dispatch"]["dispatched_unit_id"] == "flight_context"
    assert summary["after_first_dispatch"]["run_status"] == "running"
    assert summary["real_app_execution"] is False
    assert (tmp_path / "runner_state.json").is_file()


def test_global_dag_preview_alias_builds_read_only_runner_state(tmp_path: Path) -> None:
    app_root = BUILTIN_APPS_ROOT / "global_dag_project"
    script = app_root / "src" / "global_dag" / "preview_global_dag.py"
    module_name = "agilab_global_dag_preview_test_module"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    summary = module.build_preview(
        repo_root=ROOT,
        dag_path=app_root / "dag_templates" / "flight_to_meteo_global_dag.json",
        output_path=tmp_path / "runner_state.json",
        now="2026-04-29T00:00:00Z",
    )

    assert summary["example"] == "global_dag_project"
    assert summary["dag"]["ok"] is True
    assert summary["dag"]["execution_order"] == ["flight_context", "meteo_forecast_review"]
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
    assert summary["target_app"] == "mycode_project"
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
    assert summary["artifacts"]["health_json"] == "service/mycode/health.json"
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
    assert artifact["app"] == "meteo_forecast_project"
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
    destination = tmp_path / "log" / "execute" / "flight" / "AGI_run_flight.py"
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

    module._seed_example_scripts("flight")

    text = destination.read_text(encoding="utf-8")
    assert ' / "apps" / "builtin"' in text
    assert text == (EXAMPLES_ROOT / "flight" / "AGI_run_flight.py").read_text(encoding="utf-8")


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
