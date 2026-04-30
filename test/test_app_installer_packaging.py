from __future__ import annotations

import asyncio
import importlib.util
import py_compile
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src/agilab/apps/install.py"
EXAMPLES_ROOT = ROOT / "src/agilab/examples"
EXAMPLE_APPS = {
    "data_io_2026": ("AGI_install_data_io_2026.py", "AGI_run_data_io_2026.py"),
    "flight": ("AGI_install_flight.py", "AGI_run_flight.py"),
    "meteo_forecast": ("AGI_install_meteo_forecast.py", "AGI_run_meteo_forecast.py"),
    "mycode": ("AGI_install_mycode.py", "AGI_run_mycode.py"),
}
EXAMPLE_PREVIEWS = {
    "inter_project_dag": ("preview_inter_project_dag.py", "flight_to_meteo_dag.json"),
    "service_mode": ("preview_service_mode.py", "sample_health_running.json"),
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

    assert module._app_dir_candidates("flight") == [
        package_root / "apps" / "builtin" / "flight_project",
        package_root / "apps" / "flight_project",
    ]


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
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = pyproject["tool"]["setuptools"]["package-data"]["agilab"]

    assert "examples/README.md" in package_data
    assert "examples/*/README.md" in package_data
    assert "examples/*/AGI_*.py" in package_data
    assert "examples/inter_project_dag/*.py" in package_data
    assert "examples/inter_project_dag/*.json" in package_data
    assert "examples/service_mode/*.py" in package_data
    assert "examples/service_mode/*.json" in package_data


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
        dag_path=EXAMPLES_ROOT / "inter_project_dag" / "flight_to_meteo_dag.json",
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
        health_payload_path=EXAMPLES_ROOT / "service_mode" / "sample_health_running.json",
        output_path=tmp_path / "service_operator_preview.json",
    )

    assert summary["example"] == "service_mode"
    assert summary["target_app"] == "mycode_project"
    assert [step["action"] for step in summary["operator_sequence"]] == [
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
        assert env_kwargs["apps_path"] == ROOT / "src/agilab/apps"
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
