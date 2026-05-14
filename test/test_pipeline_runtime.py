from __future__ import annotations

import builtins
from contextlib import contextmanager
import importlib
import importlib.util
import math
import os
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import types

from agi_env.snippet_contract import CURRENT_SNIPPET_API


def _import_agilab_module(module_name: str):
    src_root = Path(__file__).resolve().parents[1] / "src"
    package_root = src_root / "agilab"
    src_root_str = str(src_root)
    package_root_str = str(package_root)
    if src_root_str not in sys.path:
        sys.path.insert(0, src_root_str)
    pkg = sys.modules.get("agilab")
    if pkg is None or not hasattr(pkg, "__path__"):
        pkg = types.ModuleType("agilab")
        pkg.__path__ = [package_root_str]
        sys.modules["agilab"] = pkg
    else:
        package_path = list(pkg.__path__)
        if package_root_str not in package_path:
            pkg.__path__ = [package_root_str, *package_path]
    importlib.invalidate_caches()
    return importlib.import_module(module_name)


def _load_module_with_import_failures(module_name: str, relative_path: str, monkeypatch, names_to_fail: set[str]):
    src_root = Path(__file__).resolve().parents[1] / "src"
    package_root = src_root / "agilab"
    src_root_str = str(src_root)
    package_root_str = str(package_root)
    if src_root_str not in sys.path:
        sys.path.insert(0, src_root_str)
    pkg = sys.modules.get("agilab")
    if pkg is None or not hasattr(pkg, "__path__"):
        pkg = types.ModuleType("agilab")
        pkg.__path__ = [package_root_str]
        sys.modules["agilab"] = pkg
    else:
        package_path = list(pkg.__path__)
        if package_root_str not in package_path:
            pkg.__path__ = [package_root_str, *package_path]

    real_import = builtins.__import__
    real_import_module = importlib.import_module

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in names_to_fail:
            exc = ModuleNotFoundError(f"forced missing {name}")
            exc.name = name
            raise exc
        return real_import(name, globals, locals, fromlist, level)

    def _fake_import_module(name, package=None):
        if name in names_to_fail:
            exc = ModuleNotFoundError(f"forced missing {name}")
            exc.name = name
            raise exc
        return real_import_module(name, package)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    monkeypatch.setattr(importlib, "import_module", _fake_import_module)
    module_path = Path(relative_path)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pipeline_runtime = _import_agilab_module("agilab.pipeline_runtime")


def _patch_mlflow_cli(monkeypatch):
    monkeypatch.setattr(
        pipeline_runtime.mlflow_store,
        "mlflow_cli_argv",
        lambda args, **_kwargs: ["mlflow", *args],
    )


def test_to_bool_flag_parses_common_truthy_values():
    assert pipeline_runtime.to_bool_flag(True) is True
    assert pipeline_runtime.to_bool_flag("yes") is True
    assert pipeline_runtime.to_bool_flag("On") is True
    assert pipeline_runtime.to_bool_flag(0) is False
    assert pipeline_runtime.to_bool_flag("no") is False


def test_pipeline_runtime_fallback_loader_handles_missing_support_import(monkeypatch, tmp_path):
    module = _load_module_with_import_failures(
        "agilab_pipeline_runtime_fallback_tests",
        "src/agilab/pipeline_runtime.py",
        monkeypatch,
        {"agilab.pipeline_runtime_support"},
    )

    assert module.to_bool_flag("yes") is True
    assert module.sqlite_uri_for_path(tmp_path / "mlflow.db").startswith("sqlite:")


def test_pipeline_runtime_support_fallback_loader_handles_missing_submodules(monkeypatch, tmp_path):
    module = _load_module_with_import_failures(
        "agilab_pipeline_runtime_support_fallback_tests",
        "src/agilab/pipeline_runtime_support.py",
        monkeypatch,
        {"agilab.pipeline_runtime_execution_support", "agilab.pipeline_runtime_mlflow_support"},
    )

    assert module.to_bool_flag("yes") is True
    assert "safe_service_start_template" in module.__all__
    assert "ensure_mlflow_backend_ready" in module.__all__
    assert module.sqlite_identifier('demo"name') == '"demo""name"'


def test_pipeline_runtime_and_support_raise_when_local_fallback_specs_are_missing(monkeypatch):
    original_spec = importlib.util.spec_from_file_location

    def _missing_spec(name, location, *args, **kwargs):
        if name == "agilab_pipeline_runtime_support_fallback":
            return None
        if name in {
            "agilab_pipeline_runtime_execution_support_fallback",
            "agilab_pipeline_runtime_mlflow_support_fallback",
        }:
            return None
        return original_spec(name, location, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "spec_from_file_location", _missing_spec)

    with pytest.raises(ModuleNotFoundError, match="pipeline_runtime_support"):
        _load_module_with_import_failures(
            "agilab_pipeline_runtime_missing_local_support",
            "src/agilab/pipeline_runtime.py",
            monkeypatch,
            {"agilab.pipeline_runtime_support"},
        )

    with pytest.raises(ModuleNotFoundError, match="pipeline_runtime_execution_support.py"):
        _load_module_with_import_failures(
            "agilab_pipeline_runtime_support_missing_local_support",
            "src/agilab/pipeline_runtime_support.py",
            monkeypatch,
            {"agilab.pipeline_runtime_execution_support", "agilab.pipeline_runtime_mlflow_support"},
        )


def test_safe_service_start_template_tolerates_invalid_settings_and_verbose(monkeypatch, tmp_path):
    settings = tmp_path / "app_settings.toml"
    settings.write_text(
        """
[cluster]
cluster_enabled = "yes"
pool = 1
cython = "on"
rapids = "no"
verbose = "bad"
scheduler = ""
workers = "invalid"

[args]
value = "kept"
""".strip(),
        encoding="utf-8",
    )
    env = SimpleNamespace(
        app_settings_file=settings,
        apps_path=tmp_path / "apps",
        app="demo",
    )

    snippet = pipeline_runtime.safe_service_start_template(env, "# AUTO")

    assert "VERBOSE = 1" in snippet
    assert "MODE = 7" in snippet
    assert "SCHEDULER = None" in snippet
    assert "WORKERS = None" in snippet
    assert 'RUN_ARGS = json.loads(' in snippet
    assert f'AGILAB_SNIPPET_API = "{CURRENT_SNIPPET_API}"' in snippet
    assert "# app: demo" in snippet
    assert "require_supported_snippet_api(AGILAB_SNIPPET_API)" in snippet
    # Verify the args round-trip correctly through the generated template
    assert "value" in snippet and "kept" in snippet

    broken_env = SimpleNamespace(
        app_settings_file=SimpleNamespace(),
        apps_path=tmp_path / "apps",
        app="demo",
    )
    broken_snippet = pipeline_runtime.safe_service_start_template(broken_env, "# AUTO")
    assert "MODE = 0" in broken_snippet


def test_safe_service_start_template_covers_bool_int_and_json_scheduler_literals(tmp_path):
    settings = tmp_path / "app_settings.toml"
    settings.write_text(
        """
[cluster]
cluster_enabled = true
scheduler = true

[args]
value = "kept"
""".strip(),
        encoding="utf-8",
    )
    env = SimpleNamespace(app_settings_file=settings, apps_path=tmp_path / "apps", app="demo")
    snippet = pipeline_runtime.safe_service_start_template(env, "# AUTO")
    assert "SCHEDULER = True" in snippet

    settings.write_text(
        """
[cluster]
cluster_enabled = true
scheduler = 1234
""".strip(),
        encoding="utf-8",
    )
    snippet = pipeline_runtime.safe_service_start_template(env, "# AUTO")
    assert "SCHEDULER = 1234" in snippet

    settings.write_text(
        """
[cluster]
cluster_enabled = true
scheduler = [1, 2]
""".strip(),
        encoding="utf-8",
    )
    snippet = pipeline_runtime.safe_service_start_template(env, "# AUTO")
    assert "SCHEDULER = [1, 2]" in snippet


def test_mlflow_text_and_path_helpers_cover_edge_cases(tmp_path, monkeypatch):
    env = SimpleNamespace(MLFLOW_TRACKING_DIR="relative-store", home_abs=tmp_path)

    assert pipeline_runtime.truncate_mlflow_text("abcdef", limit=4) == "abc…"
    assert pipeline_runtime.truncate_mlflow_text("abcdef", limit=1) == "a"
    assert pipeline_runtime.resolve_mlflow_backend_db(env) == (tmp_path / "relative-store" / "mlflow.db").resolve()
    assert pipeline_runtime.resolve_mlflow_artifact_dir(env) == (tmp_path / "relative-store" / "artifacts").resolve()
    assert pipeline_runtime.legacy_mlflow_filestore_present(tmp_path / "missing") is False
    assert pipeline_runtime.sqlite_uri_for_path(tmp_path / "mlflow.db").startswith("sqlite:")


def test_get_mlflow_module_and_legacy_filestore_helpers(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "mlflow", types.SimpleNamespace())
    assert pipeline_runtime.get_mlflow_module() is sys.modules["mlflow"]
    monkeypatch.delitem(sys.modules, "mlflow", raising=False)

    original_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "mlflow":
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    assert pipeline_runtime.get_mlflow_module() is None

    def fake_runtime_import(name, *args, **kwargs):
        if name == "mlflow":
            raise RuntimeError("boom")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_runtime_import)
    with pytest.raises(RuntimeError, match="boom"):
        pipeline_runtime.get_mlflow_module()

    tracking_dir = tmp_path / "mlflow-store"
    tracking_dir.mkdir()
    (tracking_dir / ".trash").mkdir()
    assert pipeline_runtime.legacy_mlflow_filestore_present(tracking_dir) is True

    meta_dir = tmp_path / "meta-store"
    meta_dir.mkdir()
    (meta_dir / "meta.yaml").write_text("meta", encoding="utf-8")
    assert pipeline_runtime.legacy_mlflow_filestore_present(meta_dir) is True

    digit_dir = tmp_path / "digit-store"
    digit_dir.mkdir()
    (digit_dir / "1").mkdir()
    assert pipeline_runtime.legacy_mlflow_filestore_present(digit_dir) is True


def test_python_for_venv_prefers_nested_dot_venv(tmp_path):
    runtime_root = tmp_path / "runtime_root"
    direct_python = runtime_root / "bin" / "python"
    nested_python = runtime_root / ".venv" / "bin" / "python"
    direct_python.parent.mkdir(parents=True)
    nested_python.parent.mkdir(parents=True)
    direct_python.write_text("", encoding="utf-8")
    nested_python.write_text("", encoding="utf-8")

    resolved = pipeline_runtime.python_for_venv(runtime_root)

    assert resolved == nested_python


def test_python_for_venv_and_runtime_helpers_cover_fallbacks(tmp_path, monkeypatch):
    default_python = tmp_path / "controller" / "python"
    default_python.parent.mkdir(parents=True)
    default_python.write_text("", encoding="utf-8")
    monkeypatch.setattr(pipeline_runtime.sys, "executable", str(default_python))

    assert pipeline_runtime.python_for_venv(None) == default_python
    assert pipeline_runtime.python_for_venv(tmp_path / "missing") == default_python
    assert pipeline_runtime.label_for_stage_runtime(None, engine="runpy", code="print('x')") == "default env"
    assert pipeline_runtime.is_valid_runtime_root(None) is False

    class BrokenPath:
        def __fspath__(self):
            raise RuntimeError("boom")

    assert pipeline_runtime.is_valid_runtime_root(BrokenPath()) is False


def test_is_valid_runtime_root_accepts_project_or_venv(tmp_path):
    project_root = tmp_path / "project"
    venv_root = tmp_path / "venv"
    (project_root / ".venv").mkdir(parents=True)
    python_exe = venv_root / "bin" / "python"
    python_exe.parent.mkdir(parents=True)
    python_exe.write_text("", encoding="utf-8")

    assert pipeline_runtime.is_valid_runtime_root(project_root) is True
    assert pipeline_runtime.is_valid_runtime_root(venv_root) is True
    assert pipeline_runtime.is_valid_runtime_root(tmp_path / "missing") is False


def test_mlflow_tracking_uri_creates_shared_store(tmp_path):
    env = SimpleNamespace(MLFLOW_TRACKING_DIR=tmp_path / "mlflow-store")

    uri = pipeline_runtime.mlflow_tracking_uri(env)

    assert uri == pipeline_runtime.sqlite_uri_for_path((tmp_path / "mlflow-store" / "mlflow.db").resolve())
    assert (tmp_path / "mlflow-store").exists()
    assert (tmp_path / "mlflow-store" / "artifacts").exists()


def test_mlflow_tracking_uri_falls_back_to_home_when_unset(tmp_path):
    env = SimpleNamespace(MLFLOW_TRACKING_DIR="", home_abs=tmp_path)

    uri = pipeline_runtime.mlflow_tracking_uri(env)

    assert uri == pipeline_runtime.sqlite_uri_for_path((tmp_path / ".mlflow" / "mlflow.db").resolve())
    assert (tmp_path / ".mlflow").exists()


def test_sqlite_uri_for_path_handles_windows_style(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline_runtime, "os", SimpleNamespace(name="nt"))
    assert pipeline_runtime.sqlite_uri_for_path(tmp_path / "mlflow.db").startswith("sqlite:///")


def test_mlflow_tracking_uri_resolves_relative_path_from_home(tmp_path):
    env = SimpleNamespace(MLFLOW_TRACKING_DIR="mlflow-store", home_abs=tmp_path)

    uri = pipeline_runtime.mlflow_tracking_uri(env)

    assert uri == pipeline_runtime.sqlite_uri_for_path((tmp_path / "mlflow-store" / "mlflow.db").resolve())
    assert (tmp_path / "mlflow-store").exists()


def test_build_mlflow_process_env_injects_tracking_and_run_id(tmp_path):
    env = SimpleNamespace(MLFLOW_TRACKING_DIR=tmp_path / "mlflow-store", apps_path=tmp_path / "apps")

    process_env = pipeline_runtime.build_mlflow_process_env(
        env,
        run_id="run-123",
        base_env={"A": "1"},
    )

    assert process_env["A"] == "1"
    assert process_env["APPS_PATH"] == str(tmp_path / "apps")
    assert process_env["MLFLOW_TRACKING_URI"] == pipeline_runtime.sqlite_uri_for_path(
        (tmp_path / "mlflow-store" / "mlflow.db").resolve()
    )
    assert process_env[pipeline_runtime.MLFLOW_STAGE_RUN_ID_ENV] == "run-123"
    assert process_env["MLFLOW_RUN_ID"] == "run-123"


def test_uses_controller_python_detects_agi_cluster_snippet():
    code = (
        "from agi_cluster.agi_distributor import AGI\n"
        "from agi_env import AgiEnv\n"
        "async def main():\n"
        "    return await AGI.install(None)\n"
    )

    assert pipeline_runtime.uses_controller_python("agi.install", code) is True
    assert pipeline_runtime.uses_controller_python("agi.run", code) is True
    assert pipeline_runtime.uses_controller_python("runpy", code) is False


def test_python_for_stage_keeps_app_env_for_non_controller_snippet(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime_root"
    nested_python = runtime_root / ".venv" / "bin" / "python"
    nested_python.parent.mkdir(parents=True)
    nested_python.write_text("", encoding="utf-8")
    controller_python = tmp_path / "controller" / "python"
    controller_python.parent.mkdir(parents=True)
    controller_python.write_text("", encoding="utf-8")
    monkeypatch.setattr(pipeline_runtime.sys, "executable", str(controller_python))

    agi_code = "from agi_cluster.agi_distributor import AGI\nprint('x')\n"
    direct_code = "from agi_env import AgiEnv\nprint('x')\n"

    assert pipeline_runtime.python_for_stage(runtime_root, engine="agi.run", code=agi_code) == controller_python
    assert pipeline_runtime.python_for_stage(runtime_root, engine="agi.run", code=direct_code) == nested_python


def test_temporary_env_overrides_restores_previous_values(monkeypatch):
    monkeypatch.setenv("AGILAB_TEMP", "before")
    monkeypatch.delenv("AGILAB_NEW_TEMP", raising=False)

    with pipeline_runtime.temporary_env_overrides({"AGILAB_TEMP": "during", "AGILAB_NEW_TEMP": "x"}):
        assert os.environ["AGILAB_TEMP"] == "during"
        assert os.environ["AGILAB_NEW_TEMP"] == "x"

    assert os.environ["AGILAB_TEMP"] == "before"
    assert "AGILAB_NEW_TEMP" not in os.environ


def test_temporary_env_overrides_handles_none_and_missing(monkeypatch):
    monkeypatch.setenv("AGILAB_REMOVE_ME", "yes")

    with pipeline_runtime.temporary_env_overrides({"AGILAB_REMOVE_ME": None, "AGILAB_CREATE_ME": "created"}):
        assert "AGILAB_REMOVE_ME" not in os.environ
        assert os.environ["AGILAB_CREATE_ME"] == "created"

    assert os.environ["AGILAB_REMOVE_ME"] == "yes"
    assert "AGILAB_CREATE_ME" not in os.environ


def test_runtime_helper_edges_cover_run_id_cleanup_and_metric_failures(tmp_path, monkeypatch):
    env = SimpleNamespace(MLFLOW_TRACKING_DIR=tmp_path / "mlflow-store", apps_path=None)
    process_env = pipeline_runtime.build_mlflow_process_env(
        env,
        base_env={
            "KEEP": "1",
            pipeline_runtime.MLFLOW_STAGE_RUN_ID_ENV: "stale-stage",
            "MLFLOW_RUN_ID": "stale",
        },
    )

    assert process_env["KEEP"] == "1"
    assert pipeline_runtime.MLFLOW_STAGE_RUN_ID_ENV not in process_env
    assert "MLFLOW_RUN_ID" not in process_env

    monkeypatch.setenv("AGILAB_TEMP_KEEP", "before")
    with pipeline_runtime.temporary_env_overrides({}):
        assert os.environ["AGILAB_TEMP_KEEP"] == "before"

    class FakeMlflow:
        def __init__(self):
            self.tags = []
            self.metrics = []

        def set_tags(self, payload):
            self.tags.append(payload)

        def log_metric(self, key, value):
            self.metrics.append((key, value))
            raise RuntimeError("skip bad metric")

    fake_mlflow = FakeMlflow()
    pipeline_runtime.log_mlflow_artifacts(
        {"mlflow": fake_mlflow},
        text_artifacts={"skip.txt": None},
        tags={"status": "ok"},
        metrics={"broken": "nan"},
    )

    assert fake_mlflow.tags == [{"status": "ok"}]
    assert len(fake_mlflow.metrics) == 1
    assert fake_mlflow.metrics[0][0] == "broken"
    assert math.isnan(fake_mlflow.metrics[0][1])
    assert pipeline_runtime.is_valid_runtime_root(tmp_path) is False


def test_wrap_code_with_mlflow_resume_uses_env_run_id():
    wrapped = pipeline_runtime.wrap_code_with_mlflow_resume("print('hello')")

    assert pipeline_runtime.MLFLOW_STAGE_RUN_ID_ENV in wrapped
    assert "MLFLOW_TRACKING_URI" in wrapped
    assert "mlflow.start_run(run_id=_agilab_run_id)" in wrapped
    assert "print('hello')" in wrapped


def test_start_mlflow_run_sets_uri_logs_tags_and_params(tmp_path, monkeypatch):
    class FakeRun:
        def __init__(self):
            self.info = SimpleNamespace(run_id="run-1")

    class FakeMlflow:
        def __init__(self):
            self.tracking_uri = None
            self.experiment_name = None
            self.tags = {}
            self.params = {}
            self.run_requests = []
            self.created = []

        def set_tracking_uri(self, value):
            self.tracking_uri = value

        def get_experiment_by_name(self, value):
            return None

        def create_experiment(self, name, artifact_location=None):
            self.created.append((name, artifact_location))

        def set_experiment(self, value):
            self.experiment_name = value

        def start_run(self, **kwargs):
            self.run_requests.append(kwargs)
            outer = self

            class _Ctx:
                def __enter__(self_inner):
                    outer.active_run = FakeRun()
                    return outer.active_run

                def __exit__(self_inner, exc_type, exc, tb):
                    return False

            return _Ctx()

        def set_tags(self, tags):
            self.tags.update(tags)

        def log_params(self, params):
            self.params.update(params)

    fake_mlflow = FakeMlflow()
    monkeypatch.setattr(pipeline_runtime, "get_mlflow_module", lambda: fake_mlflow)
    env = SimpleNamespace(MLFLOW_TRACKING_DIR=tmp_path / "mlflow-store")

    with pipeline_runtime.start_mlflow_run(
        env,
        run_name="pipeline",
        tags={"k": "v"},
        params={"stage_count": 2},
        nested=True,
    ) as tracking:
        assert tracking["run"].info.run_id == "run-1"

    assert fake_mlflow.tracking_uri == pipeline_runtime.sqlite_uri_for_path(
        (tmp_path / "mlflow-store" / "mlflow.db").resolve()
    )
    assert fake_mlflow.experiment_name == pipeline_runtime.DEFAULT_MLFLOW_EXPERIMENT_NAME
    assert fake_mlflow.created == [
        (
            pipeline_runtime.DEFAULT_MLFLOW_EXPERIMENT_NAME,
            (tmp_path / "mlflow-store" / "artifacts").resolve().as_uri(),
        )
    ]
    assert fake_mlflow.tags["k"] == "v"
    assert fake_mlflow.params["stage_count"] == "2"
    assert fake_mlflow.run_requests == [{"run_name": "pipeline", "nested": True}]


def test_start_mlflow_run_yields_none_when_mlflow_is_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline_runtime, "get_mlflow_module", lambda: None)

    with pipeline_runtime.start_mlflow_run(SimpleNamespace(MLFLOW_TRACKING_DIR=tmp_path), run_name="demo") as tracking:
        assert tracking is None


def test_start_tracker_run_exposes_backend_neutral_logging_methods(monkeypatch, tmp_path):
    run_requests: list[dict[str, object]] = []
    artifact_calls: list[tuple[object, dict[str, object]]] = []
    tracking_payload = {
        "run": SimpleNamespace(info=SimpleNamespace(run_id="run-abc")),
        "tracking_uri": "sqlite:///tmp/mlflow.db",
    }

    @contextmanager
    def fake_start_mlflow_run(*_args, **kwargs):
        run_requests.append(kwargs)
        yield tracking_payload

    monkeypatch.setattr(pipeline_runtime, "start_mlflow_run", fake_start_mlflow_run)
    monkeypatch.setattr(
        pipeline_runtime,
        "log_mlflow_artifacts",
        lambda tracking, **kwargs: artifact_calls.append((tracking, kwargs)),
    )

    artifact = tmp_path / "result.txt"
    artifact.write_text("ok", encoding="utf-8")

    with pipeline_runtime.start_tracker_run(
        SimpleNamespace(MLFLOW_TRACKING_DIR=tmp_path),
        run_name="pipeline",
        tags={"kind": "demo"},
        params={"stage_count": 1},
        nested=True,
    ) as tracker:
        assert tracker
        assert tracker.enabled is True
        assert tracker.run_id == "run-abc"
        assert tracker.tracking_uri == "sqlite:///tmp/mlflow.db"

        tracker.log_metric("score", 0.75)
        tracker.log_metrics({"loss": 0.25})
        tracker.set_tag("status", "ok")
        tracker.set_tags({"phase": "test"})
        tracker.log_text("logs/stdout.txt", "hello")
        tracker.log_artifact(artifact)

    assert run_requests == [
        {
            "run_name": "pipeline",
            "tags": {"kind": "demo"},
            "params": {"stage_count": 1},
            "nested": True,
        }
    ]
    assert [call[0] for call in artifact_calls] == [tracking_payload] * 6
    assert artifact_calls[0][1]["metrics"] == {"score": 0.75}
    assert artifact_calls[1][1]["metrics"] == {"loss": 0.25}
    assert artifact_calls[2][1]["tags"] == {"status": "ok"}
    assert artifact_calls[3][1]["tags"] == {"phase": "test"}
    assert artifact_calls[4][1]["text_artifacts"] == {"logs/stdout.txt": "hello"}
    assert artifact_calls[5][1]["file_artifacts"] == [artifact]


def test_start_tracker_run_degrades_to_disabled_tracker(monkeypatch, tmp_path):
    @contextmanager
    def fake_start_mlflow_run(*_args, **_kwargs):
        yield None

    monkeypatch.setattr(pipeline_runtime, "start_mlflow_run", fake_start_mlflow_run)

    with pipeline_runtime.start_tracker_run(
        SimpleNamespace(MLFLOW_TRACKING_DIR=tmp_path),
        run_name="pipeline",
    ) as tracker:
        assert not tracker
        assert tracker.enabled is False
        assert tracker.run_id is None
        assert tracker.tracking_uri is None
        tracker.log_metric("ignored", 1.0)


def test_mlflow_tracking_uri_migrates_legacy_filestore(tmp_path, monkeypatch):
    tracking_root = tmp_path / "mlflow-store"
    (tracking_root / "0").mkdir(parents=True)
    (tracking_root / "meta.yaml").write_text("legacy", encoding="utf-8")
    calls = {}

    def fake_run(cmd, check, capture_output, text):
        calls["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    _patch_mlflow_cli(monkeypatch)
    monkeypatch.setattr(pipeline_runtime.subprocess, "run", fake_run)

    uri = pipeline_runtime.mlflow_tracking_uri(SimpleNamespace(MLFLOW_TRACKING_DIR=tracking_root))

    assert calls["cmd"][:2] == ["mlflow", "migrate-filestore"]
    assert "-m" not in calls["cmd"]
    assert calls["cmd"][calls["cmd"].index("--source") + 1] == str(tracking_root)
    assert calls["cmd"][calls["cmd"].index("--target") + 1] == pipeline_runtime.sqlite_uri_for_path(
        tracking_root / "mlflow.db"
    )
    assert uri == pipeline_runtime.sqlite_uri_for_path(tracking_root / "mlflow.db")


def test_mlflow_tracking_uri_repairs_default_experiment_id_zero(tmp_path):
    tracking_root = tmp_path / "mlflow-store"
    tracking_root.mkdir(parents=True)
    db_path = tracking_root / "mlflow.db"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE experiments (
                experiment_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                artifact_location TEXT,
                lifecycle_stage TEXT,
                creation_time INTEGER,
                last_update_time INTEGER,
                workspace TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE runs (
                run_uuid TEXT PRIMARY KEY,
                experiment_id INTEGER
            )
            """
        )
        conn.execute(
            """
            INSERT INTO experiments (
                experiment_id,
                name,
                artifact_location,
                lifecycle_stage,
                creation_time,
                last_update_time,
                workspace
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (7, pipeline_runtime.DEFAULT_MLFLOW_EXPERIMENT_NAME, "file:///legacy/mlruns/7", "active", 0, 0, "default"),
        )
        conn.execute("INSERT INTO runs (run_uuid, experiment_id) VALUES (?, ?)", ("run-1", 7))
        conn.commit()

    env = SimpleNamespace(MLFLOW_TRACKING_DIR=tracking_root)

    uri = pipeline_runtime.mlflow_tracking_uri(env)

    assert uri == pipeline_runtime.sqlite_uri_for_path(db_path.resolve())
    with sqlite3.connect(db_path) as conn:
        experiment = conn.execute(
            "SELECT experiment_id, artifact_location FROM experiments WHERE name = ?",
            (pipeline_runtime.DEFAULT_MLFLOW_EXPERIMENT_NAME,),
        ).fetchone()
        run = conn.execute("SELECT experiment_id FROM runs WHERE run_uuid = ?", ("run-1",)).fetchone()

    assert experiment == (
        0,
        (tracking_root / "artifacts").resolve().as_uri(),
    )
    assert run == (0,)


def test_repair_mlflow_default_experiment_db_returns_false_for_missing_tables(tmp_path):
    db_path = tmp_path / "mlflow.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE runs (run_uuid TEXT PRIMARY KEY)")
        conn.commit()

    assert pipeline_runtime.repair_mlflow_default_experiment_db(db_path) is False


def test_repair_mlflow_default_experiment_db_handles_additional_edge_cases(tmp_path, monkeypatch):
    missing_columns_db = tmp_path / "missing-columns.db"
    with sqlite3.connect(missing_columns_db) as conn:
        conn.execute("CREATE TABLE experiments (experiment_id INTEGER PRIMARY KEY)")
        conn.commit()
    assert pipeline_runtime.repair_mlflow_default_experiment_db(missing_columns_db) is False

    missing_default_db = tmp_path / "missing-default.db"
    with sqlite3.connect(missing_default_db) as conn:
        conn.execute(
            """
            CREATE TABLE experiments (
                experiment_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                artifact_location TEXT,
                workspace TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO experiments (experiment_id, name, artifact_location, workspace) VALUES (1, 'other', '', 'default')"
        )
        conn.commit()
    assert pipeline_runtime.repair_mlflow_default_experiment_db(missing_default_db) is False

    repair_db = tmp_path / "repair.db"
    with sqlite3.connect(repair_db) as conn:
        conn.execute(
            """
            CREATE TABLE experiments (
                experiment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                artifact_location TEXT,
                workspace TEXT
            )
            """
        )
        conn.execute("CREATE TABLE runs (run_uuid TEXT PRIMARY KEY, experiment_id INTEGER)")
        conn.execute("CREATE TABLE notes (note_id INTEGER PRIMARY KEY AUTOINCREMENT, message TEXT)")
        conn.execute(
            "INSERT INTO experiments (experiment_id, name, artifact_location, workspace) VALUES (?, ?, ?, ?)",
            (7, pipeline_runtime.DEFAULT_MLFLOW_EXPERIMENT_NAME, "", "default"),
        )
        conn.execute("INSERT INTO runs (run_uuid, experiment_id) VALUES (?, ?)", ("run-1", 7))
        conn.execute("INSERT INTO notes (message) VALUES (?)", ("kept",))
        conn.commit()

    assert pipeline_runtime.repair_mlflow_default_experiment_db(repair_db, "file:///new-artifacts") is True
    with sqlite3.connect(repair_db) as conn:
        experiment = conn.execute(
            "SELECT experiment_id, artifact_location FROM experiments WHERE name = ?",
            (pipeline_runtime.DEFAULT_MLFLOW_EXPERIMENT_NAME,),
        ).fetchone()
        run = conn.execute("SELECT experiment_id FROM runs WHERE run_uuid = ?", ("run-1",)).fetchone()
        note = conn.execute("SELECT message FROM notes").fetchone()

    assert experiment == (0, "file:///new-artifacts")
    assert run == (0,)
    assert note == ("kept",)

    def _raise_sqlite_error(*_args, **_kwargs):
        raise sqlite3.Error("boom")

    monkeypatch.setattr(pipeline_runtime.sqlite3, "connect", _raise_sqlite_error)
    assert pipeline_runtime.repair_mlflow_default_experiment_db(repair_db) is False


def test_mlflow_tracking_uri_upgrades_sqlite_schema_once(tmp_path, monkeypatch):
    tracking_root = tmp_path / "mlflow-store"
    tracking_root.mkdir(parents=True)
    db_path = tracking_root / "mlflow.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.execute("INSERT INTO alembic_version (version_num) VALUES (?)", ("1b5f0d9ad7c1",))
        conn.commit()
    calls = []

    def fake_run(cmd, check, capture_output, text):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    _patch_mlflow_cli(monkeypatch)
    monkeypatch.setattr(pipeline_runtime.subprocess, "run", fake_run)
    monkeypatch.setattr(pipeline_runtime, "_MLFLOW_SQLITE_UPGRADE_CHECKED", set())

    env = SimpleNamespace(MLFLOW_TRACKING_DIR=tracking_root)

    first_uri = pipeline_runtime.mlflow_tracking_uri(env)
    second_uri = pipeline_runtime.mlflow_tracking_uri(env)

    assert first_uri == pipeline_runtime.sqlite_uri_for_path(db_path.resolve())
    assert second_uri == first_uri
    assert calls == [["mlflow", "db", "upgrade", pipeline_runtime.sqlite_uri_for_path(db_path.resolve())]]


def test_mlflow_tracking_uri_resets_unknown_alembic_revision(tmp_path, monkeypatch):
    tracking_root = tmp_path / "mlflow-store"
    tracking_root.mkdir(parents=True)
    db_path = tracking_root / "mlflow.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.execute("INSERT INTO alembic_version (version_num) VALUES (?)", ("1b5f0d9ad7c1",))
        conn.commit()

    def fake_run(cmd, check, capture_output, text):
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="alembic.util.exc.CommandError: Can't locate revision identified by '1b5f0d9ad7c1'",
        )

    _patch_mlflow_cli(monkeypatch)
    monkeypatch.setattr(pipeline_runtime.subprocess, "run", fake_run)
    monkeypatch.setattr(pipeline_runtime, "_MLFLOW_SQLITE_UPGRADE_CHECKED", set())

    env = SimpleNamespace(MLFLOW_TRACKING_DIR=tracking_root)

    uri = pipeline_runtime.mlflow_tracking_uri(env)

    assert uri == pipeline_runtime.sqlite_uri_for_path(db_path.resolve())
    assert not db_path.exists()
    assert len(list(tracking_root.glob("mlflow.schema-reset-*.db"))) == 1


def test_ensure_mlflow_sqlite_schema_current_ignores_sqlite_open_error(tmp_path, monkeypatch):
    db_path = tmp_path / "mlflow.db"
    db_path.write_text("", encoding="utf-8")

    def _raise_sqlite_error(*_args, **_kwargs):
        raise sqlite3.Error("locked")

    monkeypatch.setattr(pipeline_runtime.sqlite3, "connect", _raise_sqlite_error)
    monkeypatch.setattr(pipeline_runtime, "_MLFLOW_SQLITE_UPGRADE_CHECKED", set())

    pipeline_runtime.ensure_mlflow_sqlite_schema_current(db_path)


def test_ensure_mlflow_sqlite_schema_current_raises_for_unhandled_upgrade_error(tmp_path, monkeypatch):
    db_path = tmp_path / "mlflow.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.execute("INSERT INTO alembic_version (version_num) VALUES (?)", ("abc",))
        conn.commit()

    monkeypatch.setattr(
        pipeline_runtime.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout="", stderr="plain failure"),
    )
    _patch_mlflow_cli(monkeypatch)
    monkeypatch.setattr(pipeline_runtime, "_MLFLOW_SQLITE_UPGRADE_CHECKED", set())

    with pytest.raises(RuntimeError, match="Failed to upgrade the local MLflow SQLite schema"):
        pipeline_runtime.ensure_mlflow_sqlite_schema_current(db_path)


def test_reset_mlflow_sqlite_backend_returns_none_for_missing_db(tmp_path):
    assert pipeline_runtime.reset_mlflow_sqlite_backend(tmp_path / "missing.db") is None


def test_mlflow_tracking_uri_raises_when_legacy_migration_fails(tmp_path, monkeypatch):
    tracking_root = tmp_path / "legacy-store"
    tracking_root.mkdir(parents=True)
    (tracking_root / ".trash").mkdir()
    env = SimpleNamespace(MLFLOW_TRACKING_DIR=tracking_root)

    monkeypatch.setattr(
        pipeline_runtime.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout="", stderr="migration failed"),
    )
    _patch_mlflow_cli(monkeypatch)

    with pytest.raises(RuntimeError, match="Failed to migrate the legacy MLflow file store to SQLite"):
        pipeline_runtime.mlflow_tracking_uri(env)


def test_ensure_default_mlflow_experiment_resets_store_after_schema_error(tmp_path, monkeypatch):
    tracking_root = tmp_path / "mlflow-store"
    tracking_root.mkdir(parents=True)
    env = SimpleNamespace(MLFLOW_TRACKING_DIR=tracking_root)
    calls: dict[str, object] = {"tracking": [], "reset": 0, "create": []}

    class FakeMlflow:
        def __init__(self):
            self.calls = 0
            self.tracking = SimpleNamespace(MlflowClient=None)

        def set_tracking_uri(self, uri):
            calls["tracking"].append(uri)

        def get_experiment_by_name(self, name):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("Detected out-of-date database schema")
            return None

        def create_experiment(self, name, artifact_location=None):
            calls["create"].append((name, artifact_location))

        def set_experiment(self, name):
            calls["set_experiment"] = name

    monkeypatch.setattr(pipeline_runtime, "mlflow_tracking_uri", lambda _: "sqlite:///tmp/mlflow.db")
    monkeypatch.setattr(
        pipeline_runtime,
        "reset_mlflow_sqlite_backend",
        lambda path: calls.__setitem__("reset", int(calls["reset"]) + 1) or path,
    )

    uri = pipeline_runtime.ensure_default_mlflow_experiment(env, FakeMlflow())

    assert uri == "sqlite:///tmp/mlflow.db"
    assert calls["reset"] == 1
    assert calls["tracking"] == ["sqlite:///tmp/mlflow.db", "sqlite:///tmp/mlflow.db"]
    assert calls["set_experiment"] == pipeline_runtime.DEFAULT_MLFLOW_EXPERIMENT_NAME


def test_ensure_default_mlflow_experiment_resets_store_after_duplicate_column_error(tmp_path, monkeypatch):
    tracking_root = tmp_path / "mlflow-store"
    tracking_root.mkdir(parents=True)
    env = SimpleNamespace(MLFLOW_TRACKING_DIR=tracking_root)
    calls: dict[str, object] = {"tracking": [], "reset": 0}

    class FakeMlflow:
        def __init__(self):
            self.calls = 0
            self.tracking = SimpleNamespace(MlflowClient=None)

        def set_tracking_uri(self, uri):
            calls["tracking"].append(uri)

        def get_experiment_by_name(self, name):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("sqlite3.OperationalError: duplicate column name: storage_location")
            return None

        def create_experiment(self, name, artifact_location=None):
            return None

        def set_experiment(self, name):
            calls["set_experiment"] = name

    monkeypatch.setattr(pipeline_runtime, "mlflow_tracking_uri", lambda _: "sqlite:///tmp/mlflow.db")
    monkeypatch.setattr(
        pipeline_runtime,
        "reset_mlflow_sqlite_backend",
        lambda path: calls.__setitem__("reset", int(calls["reset"]) + 1) or path,
    )

    uri = pipeline_runtime.ensure_default_mlflow_experiment(env, FakeMlflow())

    assert uri == "sqlite:///tmp/mlflow.db"
    assert calls["reset"] == 1
    assert calls["tracking"] == ["sqlite:///tmp/mlflow.db", "sqlite:///tmp/mlflow.db"]
    assert calls["set_experiment"] == pipeline_runtime.DEFAULT_MLFLOW_EXPERIMENT_NAME


def test_ensure_default_mlflow_experiment_handles_none_create_failure_and_unexpected_errors(tmp_path, monkeypatch):
    tracking_root = tmp_path / "mlflow-store"
    tracking_root.mkdir(parents=True)
    env = SimpleNamespace(MLFLOW_TRACKING_DIR=tracking_root)
    monkeypatch.setattr(pipeline_runtime, "mlflow_tracking_uri", lambda *_args, **_kwargs: "sqlite:///tmp/mlflow.db")
    monkeypatch.setattr(pipeline_runtime, "get_mlflow_module", lambda: None)

    assert pipeline_runtime.ensure_default_mlflow_experiment(env, None) is None

    calls: list[str] = []

    class CreateFailsMlflow:
        def set_tracking_uri(self, uri):
            calls.append(f"tracking:{uri}")

        def get_experiment_by_name(self, _name):
            return None

        def create_experiment(self, *_args, **_kwargs):
            raise RuntimeError("already exists")

        def set_experiment(self, name):
            calls.append(f"set:{name}")

    uri = pipeline_runtime.ensure_default_mlflow_experiment(env, CreateFailsMlflow())
    assert uri == "sqlite:///tmp/mlflow.db"
    assert calls == [
        "tracking:sqlite:///tmp/mlflow.db",
        f"set:{pipeline_runtime.DEFAULT_MLFLOW_EXPERIMENT_NAME}",
    ]

    class BrokenMlflow:
        def set_tracking_uri(self, _uri):
            return None

        def get_experiment_by_name(self, _name):
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        pipeline_runtime.ensure_default_mlflow_experiment(env, BrokenMlflow())


def test_safe_service_start_template_embeds_cluster_and_args(tmp_path):
    settings = tmp_path / "app_settings.toml"
    settings.write_text(
        """
[cluster]
cluster_enabled = true
pool = true
cython = true
rapids = false
scheduler = "tcp://127.0.0.1:8786"
verbose = "2"

[cluster.workers]
"127.0.0.1" = 2

[args]
data_in = "input"
data_out = "output"
""".strip(),
        encoding="utf-8",
    )
    env = SimpleNamespace(
        app_settings_file=settings,
        apps_path=tmp_path / "apps",
        app="demo",
    )

    snippet = pipeline_runtime.safe_service_start_template(env, "# AUTO")

    assert snippet.startswith("# AUTO")
    assert 'APP = "demo"' in snippet
    assert "VERBOSE = 2" in snippet
    assert "MODE = 7" in snippet
    assert 'SCHEDULER = "tcp://127.0.0.1:8786"' in snippet
    assert "WORKERS = json.loads(" in snippet
    assert "127.0.0.1" in snippet
    assert "RUN_ARGS = json.loads(" in snippet
    assert "data_in" in snippet and "data_out" in snippet


def test_safe_service_start_template_preserves_builtin_apps_path(tmp_path):
    settings = tmp_path / "app_settings.toml"
    settings.write_text("[cluster]\ncluster_enabled = true\n", encoding="utf-8")
    apps_path = tmp_path / "apps"
    builtin_apps = apps_path / "builtin"
    (builtin_apps / "flight_telemetry_project").mkdir(parents=True)
    env = SimpleNamespace(
        app_settings_file=settings,
        apps_path=apps_path,
        app="flight_telemetry_project",
    )

    snippet = pipeline_runtime.safe_service_start_template(env, "# AUTO")

    assert f'APPS_PATH = "{builtin_apps}"' in snippet


def test_ensure_safe_service_template_preserves_manual_file(tmp_path):
    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text("", encoding="utf-8")
    template_path = tmp_path / "AGI_safe_service.py"
    template_path.write_text("# manual\nprint('keep')\n", encoding="utf-8")
    env = SimpleNamespace(
        app_settings_file=tmp_path / "missing.toml",
        apps_path=tmp_path / "apps",
        app="demo",
    )

    resolved = pipeline_runtime.ensure_safe_service_template(
        env,
        stages_file,
        template_filename="AGI_safe_service.py",
        marker="# AUTO",
        debug_log=lambda *_args, **_kwargs: None,
    )

    assert resolved == template_path
    assert template_path.read_text(encoding="utf-8") == "# manual\nprint('keep')\n"


def test_ensure_safe_service_template_writes_generated_content(tmp_path):
    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text("", encoding="utf-8")
    env = SimpleNamespace(
        app_settings_file=tmp_path / "missing.toml",
        apps_path=tmp_path / "apps",
        app="demo",
    )

    resolved = pipeline_runtime.ensure_safe_service_template(
        env,
        stages_file,
        template_filename="AGI_safe_service.py",
        marker="# AUTO",
        debug_log=lambda *_args, **_kwargs: None,
    )

    assert resolved == tmp_path / "AGI_safe_service.py"
    assert resolved.read_text(encoding="utf-8").startswith("# AUTO")


def test_ensure_safe_service_template_is_noop_when_content_matches(tmp_path):
    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text("", encoding="utf-8")
    template_path = tmp_path / "AGI_safe_service.py"
    env = SimpleNamespace(
        app_settings_file=tmp_path / "missing.toml",
        apps_path=tmp_path / "apps",
        app="demo",
    )
    expected = pipeline_runtime.safe_service_start_template(env, "# AUTO")
    template_path.write_text(expected, encoding="utf-8")

    resolved = pipeline_runtime.ensure_safe_service_template(
        env,
        stages_file,
        template_filename="AGI_safe_service.py",
        marker="# AUTO",
        debug_log=lambda *_args, **_kwargs: None,
    )

    assert resolved == template_path
    assert template_path.read_text(encoding="utf-8") == expected


def test_ensure_safe_service_template_logs_and_returns_none_on_write_error(tmp_path):
    stages_file = tmp_path / "missing" / "lab_stages.toml"
    env = SimpleNamespace(
        app_settings_file=tmp_path / "missing.toml",
        apps_path=tmp_path / "apps",
        app="demo",
    )
    debug_calls: list[str] = []
    original_write_text = Path.write_text

    def fail_write_text(self, *args, **kwargs):
        if self.name == "AGI_safe_service.py":
            raise OSError("disk full")
        return original_write_text(self, *args, **kwargs)

    with patch.object(Path, "write_text", fail_write_text):
        resolved = pipeline_runtime.ensure_safe_service_template(
            env,
            stages_file,
            template_filename="AGI_safe_service.py",
            marker="# AUTO",
            debug_log=lambda message, *_args: debug_calls.append(message),
        )

    assert resolved is None
    assert debug_calls


def test_label_for_stage_runtime_describes_controller_and_runtime_env(tmp_path, monkeypatch):
    runtime_root = tmp_path / "worker_env"
    runtime_root.mkdir()
    controller_python = tmp_path / "controller" / "python"
    controller_python.parent.mkdir(parents=True)
    controller_python.write_text("", encoding="utf-8")
    monkeypatch.setattr(pipeline_runtime.sys, "executable", str(controller_python))

    agi_code = "from agi_cluster.agi_distributor import AGI\nawait AGI.run(None)\n"

    assert (
        pipeline_runtime.label_for_stage_runtime(runtime_root, engine="agi.run", code=agi_code)
        == "controller env -> worker_env"
    )
    assert (
        pipeline_runtime.label_for_stage_runtime(runtime_root, engine="runpy", code="print('x')")
        == "worker_env"
    )


def test_stream_run_command_streams_clean_output_and_injects_pythonpath(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    apps_root = repo_root / "src" / "agilab" / "apps"
    (repo_root / "src" / "agilab").mkdir(parents=True)
    apps_root.mkdir(parents=True)
    env = SimpleNamespace(apps_path=apps_root)
    log_lines: list[str] = []
    popen_calls: dict[str, object] = {}

    class FakeProc:
        returncode = 0

        def __init__(self, *args, **kwargs):
            popen_calls["argv"] = list(args[0])
            popen_calls.update(kwargs)
            self.stdout = iter(["\x1b[31mhello\x1b[0m\n", "world\n"])

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def wait(self, timeout=None):
            popen_calls["timeout"] = timeout

    monkeypatch.setattr(pipeline_runtime.subprocess, "Popen", FakeProc)

    output = pipeline_runtime.stream_run_command(
        env,
        "page",
        "echo hi",
        tmp_path,
        push_run_log=lambda _page, line, _placeholder=None: log_lines.append(line),
        ansi_escape_re=__import__("re").compile(r"\x1b[^m]*m"),
        jump_exception_cls=RuntimeError,
        extra_env={"EXTRA": "1"},
        timeout=15,
    )

    assert output == "hello\nworld"
    assert log_lines == ["hello", "world"]
    assert popen_calls["argv"] == ["echo", "hi"]
    assert popen_calls["shell"] is False
    assert popen_calls["env"]["uv_IGNORE_ACTIVE_VENV"] == "1"
    assert popen_calls["env"]["EXTRA"] == "1"
    assert str(repo_root / "src") in popen_calls["env"]["PYTHONPATH"]
    assert popen_calls["timeout"] == 15


def test_stream_run_command_raises_for_missing_module_without_app_venv(tmp_path, monkeypatch):
    apps_root = tmp_path / "apps"
    apps_root.mkdir()
    env = SimpleNamespace(apps_path=apps_root)

    class FakeProc:
        returncode = 0

        def __init__(self, *args, **kwargs):
            self.stdout = iter(["Module not found: demo\n"])

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def wait(self, timeout=None):
            return None

    monkeypatch.setattr(pipeline_runtime.subprocess, "Popen", FakeProc)

    with pytest.raises(RuntimeError, match="Module not found: demo"):
        pipeline_runtime.stream_run_command(
            env,
            "page",
            "echo hi",
            tmp_path,
            push_run_log=lambda *_args, **_kwargs: None,
            ansi_escape_re=__import__("re").compile(r"\x1b[^m]*m"),
            jump_exception_cls=RuntimeError,
        )


def test_stream_run_command_reports_timeout(tmp_path, monkeypatch):
    env = SimpleNamespace(apps_path=tmp_path / "apps")
    logs: list[str] = []

    class FakeProc:
        def __init__(self, *args, **kwargs):
            self.stdout = iter(["line one\n"])

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def wait(self, timeout=None):
            raise pipeline_runtime.subprocess.TimeoutExpired("echo hi", timeout)

        def kill(self):
            logs.append("killed")

    monkeypatch.setattr(pipeline_runtime.subprocess, "Popen", FakeProc)

    output = pipeline_runtime.stream_run_command(
        env,
        "page",
        "echo hi",
        tmp_path,
        push_run_log=lambda _page, line, _placeholder=None: logs.append(line),
        ansi_escape_re=__import__("re").compile(r"\x1b[^m]*m"),
        jump_exception_cls=RuntimeError,
        timeout=5,
    )

    assert output == "line one"
    assert "Command timed out after 5 seconds." in logs
    assert "killed" in logs


def test_stream_run_command_reports_called_process_error(tmp_path, monkeypatch):
    env = SimpleNamespace(apps_path=tmp_path / "apps")
    logs: list[str] = []

    class FakeProc:
        def __init__(self, *args, **kwargs):
            self.stdout = iter(["line one\n"])

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def wait(self, timeout=None):
            raise pipeline_runtime.subprocess.CalledProcessError(1, "echo hi")

        def kill(self):
            logs.append("killed")

    monkeypatch.setattr(pipeline_runtime.subprocess, "Popen", FakeProc)

    output = pipeline_runtime.stream_run_command(
        env,
        "page",
        "echo hi",
        tmp_path,
        push_run_log=lambda _page, line, _placeholder=None: logs.append(line),
        ansi_escape_re=__import__("re").compile(r"\x1b[^m]*m"),
        jump_exception_cls=RuntimeError,
    )

    assert output == "line one"
    assert "Command failed: Command 'echo hi' returned non-zero exit status 1." in logs
    assert "killed" in logs


def test_stream_run_command_tolerates_broken_apps_path_resolution(tmp_path, monkeypatch):
    logs: list[str] = []

    class BrokenPath:
        def __fspath__(self):
            raise RuntimeError("boom")

    class FakeProc:
        def __init__(self, *args, **kwargs):
            self.stdout = iter(["ok\n"])

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def wait(self, timeout=None):
            return None

    monkeypatch.setattr(pipeline_runtime.subprocess, "Popen", FakeProc)

    output = pipeline_runtime.stream_run_command(
        SimpleNamespace(apps_path=BrokenPath()),
        "page",
        "echo hi",
        tmp_path,
        push_run_log=lambda _page, line, _placeholder=None: logs.append(line),
        ansi_escape_re=__import__("re").compile(r"\x1b[^m]*m"),
        jump_exception_cls=RuntimeError,
    )

    assert output == "ok"
    assert logs == ["ok"]


def test_log_mlflow_artifacts_uses_temp_files_when_log_text_missing(tmp_path):
    artifacts: list[tuple[str, str | None]] = []
    tags: list[dict[str, str]] = []
    metrics: list[tuple[str, float]] = []

    artifact_file = tmp_path / "result.txt"
    artifact_file.write_text("payload", encoding="utf-8")

    class FakeMlflow:
        def set_tags(self, payload):
            tags.append(payload)

        def log_metric(self, key, value):
            metrics.append((key, value))

        def log_artifact(self, path, artifact_path=None):
            artifacts.append((Path(path).read_text(encoding="utf-8"), artifact_path))

    pipeline_runtime.log_mlflow_artifacts(
        {"mlflow": FakeMlflow()},
        text_artifacts={"logs/stdout.txt": "demo"},
        file_artifacts=[artifact_file],
        tags={"status": "ok"},
        metrics={"served": 1.5, "skip": None},
    )

    assert tags == [{"status": "ok"}]
    assert metrics == [("served", 1.5)]
    assert ("demo", "logs") in artifacts
    assert ("payload", None) in artifacts


def test_log_mlflow_artifacts_handles_empty_tracking_and_log_text_support(tmp_path):
    pipeline_runtime.log_mlflow_artifacts(None, text_artifacts={"ignored.txt": "x"})

    calls = {"texts": [], "tags": []}

    class FakeMlflow:
        def set_tags(self, payload):
            calls["tags"].append(payload)

        def log_text(self, text, artifact_name):
            calls["texts"].append((text, artifact_name))

        def log_metric(self, *_args, **_kwargs):
            raise RuntimeError("should not be called")

        def log_artifact(self, *_args, **_kwargs):
            raise RuntimeError("should not be called")

    pipeline_runtime.log_mlflow_artifacts(
        {"mlflow": FakeMlflow()},
        text_artifacts={"logs/stdout.txt": "demo"},
        tags={"status": "ok"},
        metrics={},
        file_artifacts=[tmp_path / "missing.txt", ""],
    )

    assert calls["tags"] == [{"status": "ok"}]
    assert calls["texts"] == [("demo", "logs/stdout.txt")]


def test_run_locked_stage_runpy_executes_and_logs(tmp_path, monkeypatch):
    snippet_file = tmp_path / "snippet.py"
    codex_file = tmp_path / "codex.py"
    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text("", encoding="utf-8")
    run_log = tmp_path / "stage_1.log"
    logs: list[str] = []
    released: list[str] = []

    fake_streamlit = types.ModuleType("streamlit")
    fake_streamlit.session_state = {"snippet_file": str(snippet_file)}
    fake_streamlit.error = lambda message: logs.append(f"ERROR:{message}")
    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)

    @contextmanager
    def fake_start_mlflow_run(*_args, **_kwargs):
        yield {"run": SimpleNamespace(info=SimpleNamespace(run_id="run-123"))}

    monkeypatch.setattr(pipeline_runtime, "label_for_stage_runtime", lambda *_args, **_kwargs: "default env")
    monkeypatch.setattr(pipeline_runtime, "build_mlflow_process_env", lambda *_args, **_kwargs: {"MLFLOW_RUN_ID": "run-123"})
    monkeypatch.setattr(pipeline_runtime, "start_mlflow_run", fake_start_mlflow_run)
    monkeypatch.setattr(pipeline_runtime, "run_lab", lambda *_args, **_kwargs: "runpy output")
    monkeypatch.setattr(pipeline_runtime, "log_mlflow_artifacts", lambda *_args, **_kwargs: logs.append("ARTIFACTS"))

    env = SimpleNamespace(
        app="demo",
        active_app="",
        apps_path=tmp_path / "apps",
        copilot_file=codex_file,
    )
    placeholder = SimpleNamespace(caption=lambda message: logs.append(f"CAPTION:{message}"))

    pipeline_runtime.run_locked_stage(
        env,
        "page",
        stages_file,
        0,
        {"D": "demo stage", "Q": "question", "C": "print('hello')"},
        {},
        {},
        normalize_runtime_path=lambda value: str(value or ""),
        prepare_run_log_file=lambda *_args, **_kwargs: (run_log, None),
        push_run_log=lambda _page, line, _placeholder=None: logs.append(line),
        refresh_pipeline_run_lock=lambda *_args, **_kwargs: None,
        acquire_pipeline_run_lock=lambda *_args, **_kwargs: "lock",
        release_pipeline_run_lock=lambda lock, *_args, **_kwargs: released.append(lock),
        get_run_placeholder=lambda *_args, **_kwargs: placeholder,
        is_valid_runtime_root=lambda *_args, **_kwargs: False,
        python_for_venv=lambda *_args, **_kwargs: tmp_path / "python",
        stream_run_command=lambda **_kwargs: "unused",
        stage_summary=lambda _entry, _limit: "summary",
    )

    assert fake_streamlit.session_state["page__run_logs"] == []
    assert any("Run stage 1 started" in line for line in logs)
    assert any('Stage 1: engine=runpy, env=default env, summary="summary"' in line for line in logs)
    assert any("Output (stage 1):\nrunpy output" in line for line in logs)
    assert "ARTIFACTS" in logs
    assert released == ["lock"]


def test_run_locked_stage_handles_missing_snippet_and_lock_refusal(tmp_path, monkeypatch):
    logs: list[str] = []
    fake_streamlit = types.ModuleType("streamlit")
    fake_streamlit.session_state = {}
    fake_streamlit.error = lambda message: logs.append(f"ERROR:{message}")
    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)

    env = SimpleNamespace(app="demo", active_app="", apps_path=tmp_path / "apps", copilot_file=tmp_path / "copilot.py")
    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text("", encoding="utf-8")

    pipeline_runtime.run_locked_stage(
        env,
        "page",
        stages_file,
        0,
        {"D": "demo", "Q": "question", "C": "print('x')"},
        {},
        {},
        normalize_runtime_path=lambda value: str(value or ""),
        prepare_run_log_file=lambda *_args, **_kwargs: (None, None),
        push_run_log=lambda *_args, **_kwargs: None,
        refresh_pipeline_run_lock=lambda *_args, **_kwargs: None,
        acquire_pipeline_run_lock=lambda *_args, **_kwargs: "lock",
        release_pipeline_run_lock=lambda *_args, **_kwargs: None,
        get_run_placeholder=lambda *_args, **_kwargs: None,
        is_valid_runtime_root=lambda *_args, **_kwargs: False,
        python_for_venv=lambda *_args, **_kwargs: tmp_path / "python",
        stream_run_command=lambda **_kwargs: "",
        stage_summary=lambda *_args, **_kwargs: "summary",
    )

    assert logs == ["ERROR:Snippet file is not configured. Reload the page and try again."]

    fake_streamlit.session_state = {"snippet_file": str(tmp_path / "snippet.py")}
    pipeline_runtime.run_locked_stage(
        env,
        "page",
        stages_file,
        0,
        {"D": "demo", "Q": "question", "C": "print('x')"},
        {},
        {},
        normalize_runtime_path=lambda value: str(value or ""),
        prepare_run_log_file=lambda *_args, **_kwargs: (None, None),
        push_run_log=lambda *_args, **_kwargs: None,
        refresh_pipeline_run_lock=lambda *_args, **_kwargs: None,
        acquire_pipeline_run_lock=lambda *_args, **_kwargs: None,
        release_pipeline_run_lock=lambda *_args, **_kwargs: None,
        get_run_placeholder=lambda *_args, **_kwargs: None,
        is_valid_runtime_root=lambda *_args, **_kwargs: False,
        python_for_venv=lambda *_args, **_kwargs: tmp_path / "python",
        stream_run_command=lambda **_kwargs: "",
        stage_summary=lambda *_args, **_kwargs: "summary",
    )

    assert fake_streamlit.session_state["page__run_logs"] == []


def test_run_locked_stage_refuses_stale_generated_agi_snippet(tmp_path, monkeypatch):
    logs: list[str] = []
    released: list[str] = []
    fake_streamlit = types.ModuleType("streamlit")
    fake_streamlit.session_state = {"snippet_file": str(tmp_path / "snippet.py")}
    fake_streamlit.error = lambda message: logs.append(f"ERROR:{message}")
    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)

    env = SimpleNamespace(
        app="demo",
        active_app=tmp_path,
        apps_path=tmp_path / "apps",
        copilot_file=tmp_path / "copilot.py",
    )
    stale_code = """
import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

async def main():
    await AGI.run(AgiEnv(apps_path="/tmp/apps", app="demo"))
"""

    pipeline_runtime.run_locked_stage(
        env,
        "page",
        tmp_path / "lab_stages.toml",
        0,
        {"D": "demo", "Q": "Imported snippet: AGI_run_demo.py", "C": stale_code},
        {},
        {},
        normalize_runtime_path=lambda value: str(value or ""),
        prepare_run_log_file=lambda *_args, **_kwargs: (None, None),
        push_run_log=lambda _page, line, _placeholder=None: logs.append(line),
        refresh_pipeline_run_lock=lambda *_args, **_kwargs: logs.append("REFRESH"),
        acquire_pipeline_run_lock=lambda *_args, **_kwargs: "lock",
        release_pipeline_run_lock=lambda lock, *_args, **_kwargs: released.append(lock),
        get_run_placeholder=lambda *_args, **_kwargs: None,
        is_valid_runtime_root=lambda *_args, **_kwargs: True,
        python_for_venv=lambda *_args, **_kwargs: tmp_path / "python",
        stream_run_command=lambda *_args, **_kwargs: logs.append("RUN") or "",
        stage_summary=lambda *_args, **_kwargs: "summary",
    )

    assert any("AGILAB core snippet API changed" in line for line in logs)
    assert any("AGI_run_demo.py" in line for line in logs)
    assert "RUN" not in logs
    assert released == ["lock"]


def test_run_locked_stage_covers_runtime_fallbacks_empty_output_and_export_target(tmp_path, monkeypatch):
    snippet_file = tmp_path / "snippet.py"
    snippet_file.write_text("print('x')", encoding="utf-8")
    codex_file = tmp_path / "codex.py"
    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text("", encoding="utf-8")
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    export_file = tmp_path / "export.csv"
    export_file.write_text("x\n1\n", encoding="utf-8")
    logs: list[str] = []
    released: list[str] = []

    fake_streamlit = types.ModuleType("streamlit")
    fake_streamlit.session_state = {
        "snippet_file": str(snippet_file),
        "lab_selected_venv": str(runtime_root),
        "df_file_out": str(export_file),
    }
    fake_streamlit.error = lambda message: logs.append(f"ERROR:{message}")
    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)

    @contextmanager
    def fake_start_mlflow_run(*_args, **_kwargs):
        yield {"run": SimpleNamespace(info=SimpleNamespace(run_id="run-999"))}

    artifact_calls: list[dict[str, object]] = []
    monkeypatch.setattr(pipeline_runtime, "label_for_stage_runtime", lambda *_args, **_kwargs: "runtime env")
    monkeypatch.setattr(pipeline_runtime, "build_mlflow_process_env", lambda *_args, **_kwargs: {"MLFLOW_RUN_ID": "run-999"})
    monkeypatch.setattr(pipeline_runtime, "start_mlflow_run", fake_start_mlflow_run)
    monkeypatch.setattr(
        pipeline_runtime,
        "log_mlflow_artifacts",
        lambda *_args, **kwargs: artifact_calls.append(kwargs),
    )

    pipeline_runtime.run_locked_stage(
        SimpleNamespace(
            app="demo",
            active_app=str(runtime_root),
            apps_path=tmp_path / "apps",
            copilot_file=codex_file,
        ),
        "page",
        stages_file,
        0,
        {"D": "demo stage", "Q": "question", "C": "print('hello')", "R": "runpy"},
        {},
        {},
        normalize_runtime_path=lambda value: str(value or ""),
        prepare_run_log_file=lambda *_args, **_kwargs: (None, "log unavailable"),
        push_run_log=lambda _page, line, _placeholder=None: logs.append(line),
        refresh_pipeline_run_lock=lambda *_args, **_kwargs: None,
        acquire_pipeline_run_lock=lambda *_args, **_kwargs: "lock",
        release_pipeline_run_lock=lambda lock, *_args, **_kwargs: released.append(lock),
        get_run_placeholder=lambda *_args, **_kwargs: None,
        is_valid_runtime_root=lambda value: str(value) == str(runtime_root),
        python_for_venv=lambda *_args, **_kwargs: tmp_path / "runtime" / ".venv" / "bin" / "python",
        stream_run_command=lambda *_args, **_kwargs: "",
        stage_summary=lambda *_args, **_kwargs: "summary",
    )

    assert any("unable to prepare log file: log unavailable" in line for line in logs)
    assert any('Stage 1: engine=agi.run, env=runtime env, summary="summary"' in line for line in logs)
    assert artifact_calls and str(export_file) in artifact_calls[0]["file_artifacts"]
    assert released == ["lock"]


def test_run_locked_stage_retries_active_app_when_engine_requires_runtime(tmp_path, monkeypatch):
    snippet_file = tmp_path / "snippet.py"
    snippet_file.write_text("print('x')", encoding="utf-8")
    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text("", encoding="utf-8")
    active_app = tmp_path / "active-app"
    active_app.mkdir()
    logs: list[str] = []

    fake_streamlit = types.ModuleType("streamlit")
    fake_streamlit.session_state = {"snippet_file": str(snippet_file)}
    fake_streamlit.error = lambda message: logs.append(f"ERROR:{message}")
    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)

    @contextmanager
    def fake_start_mlflow_run(*_args, **_kwargs):
        yield None

    checks: list[str] = []

    def _is_valid_runtime_root(value):
        checks.append(str(value))
        return checks.count(str(active_app)) >= 2

    monkeypatch.setattr(pipeline_runtime, "start_mlflow_run", fake_start_mlflow_run)
    monkeypatch.setattr(pipeline_runtime, "build_mlflow_process_env", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(pipeline_runtime, "label_for_stage_runtime", lambda *_args, **_kwargs: "runtime env")

    pipeline_runtime.run_locked_stage(
        SimpleNamespace(
            app="demo",
            active_app=str(active_app),
            apps_path=tmp_path / "apps",
            copilot_file=tmp_path / "copilot.py",
        ),
        "page",
        stages_file,
        0,
        {"D": "demo stage", "Q": "question", "C": "print('hello')", "R": "agi.run"},
        {},
        {},
        normalize_runtime_path=lambda value: str(value or ""),
        prepare_run_log_file=lambda *_args, **_kwargs: (tmp_path / "run.log", None),
        push_run_log=lambda _page, line, _placeholder=None: logs.append(line),
        refresh_pipeline_run_lock=lambda *_args, **_kwargs: None,
        acquire_pipeline_run_lock=lambda *_args, **_kwargs: "lock",
        release_pipeline_run_lock=lambda *_args, **_kwargs: None,
        get_run_placeholder=lambda *_args, **_kwargs: None,
        is_valid_runtime_root=_is_valid_runtime_root,
        python_for_venv=lambda *_args, **_kwargs: tmp_path / "python",
        stream_run_command=lambda *_args, **_kwargs: "ok",
        stage_summary=lambda *_args, **_kwargs: "summary",
    )

    assert checks.count(str(active_app)) >= 2
    assert fake_streamlit.session_state["lab_selected_venv"] == str(active_app)
    assert fake_streamlit.session_state["lab_selected_engine"] == "agi.run"


def test_run_locked_stage_uses_active_app_as_primary_runtime_fallback(tmp_path, monkeypatch):
    snippet_file = tmp_path / "snippet.py"
    snippet_file.write_text("print('x')", encoding="utf-8")
    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text("", encoding="utf-8")
    active_app = tmp_path / "active-app"
    active_app.mkdir()
    logs: list[str] = []

    fake_streamlit = types.ModuleType("streamlit")
    fake_streamlit.session_state = {"snippet_file": str(snippet_file)}
    fake_streamlit.error = lambda message: logs.append(f"ERROR:{message}")
    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)

    @contextmanager
    def fake_start_mlflow_run(*_args, **_kwargs):
        yield None

    monkeypatch.setattr(pipeline_runtime, "start_mlflow_run", fake_start_mlflow_run)
    monkeypatch.setattr(pipeline_runtime, "build_mlflow_process_env", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(pipeline_runtime, "label_for_stage_runtime", lambda *_args, **_kwargs: "runtime env")

    pipeline_runtime.run_locked_stage(
        SimpleNamespace(
            app="demo",
            active_app=str(active_app),
            apps_path=tmp_path / "apps",
            copilot_file=tmp_path / "copilot.py",
        ),
        "page",
        stages_file,
        0,
        {"D": "demo stage", "Q": "question", "C": "print('hello')", "R": ""},
        {},
        {},
        normalize_runtime_path=lambda value: str(value or ""),
        prepare_run_log_file=lambda *_args, **_kwargs: (tmp_path / "run.log", None),
        push_run_log=lambda _page, line, _placeholder=None: logs.append(line),
        refresh_pipeline_run_lock=lambda *_args, **_kwargs: None,
        acquire_pipeline_run_lock=lambda *_args, **_kwargs: "lock",
        release_pipeline_run_lock=lambda *_args, **_kwargs: None,
        get_run_placeholder=lambda *_args, **_kwargs: None,
        is_valid_runtime_root=lambda value: str(value) == str(active_app),
        python_for_venv=lambda *_args, **_kwargs: tmp_path / "python",
        stream_run_command=lambda *_args, **_kwargs: "",
        stage_summary=lambda *_args, **_kwargs: "summary",
    )

    assert fake_streamlit.session_state["lab_selected_venv"] == str(active_app)
    assert any("engine=agi.run, env=runtime env" in line for line in logs)


def test_run_locked_stage_runpy_empty_output_logs_message_and_export_target(tmp_path, monkeypatch):
    snippet_file = tmp_path / "snippet.py"
    snippet_file.write_text("print('x')", encoding="utf-8")
    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text("", encoding="utf-8")
    export_file = tmp_path / "export.csv"
    export_file.write_text("x\n1\n", encoding="utf-8")
    logs: list[str] = []

    fake_streamlit = types.ModuleType("streamlit")
    fake_streamlit.session_state = {
        "snippet_file": str(snippet_file),
        "df_file_out": str(export_file),
    }
    fake_streamlit.error = lambda message: logs.append(f"ERROR:{message}")
    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)

    @contextmanager
    def fake_start_mlflow_run(*_args, **_kwargs):
        yield {"run": SimpleNamespace(info=SimpleNamespace(run_id="run-321"))}

    artifact_calls: list[dict[str, object]] = []
    monkeypatch.setattr(pipeline_runtime, "label_for_stage_runtime", lambda *_args, **_kwargs: "default env")
    monkeypatch.setattr(pipeline_runtime, "build_mlflow_process_env", lambda *_args, **_kwargs: {"MLFLOW_RUN_ID": "run-321"})
    monkeypatch.setattr(pipeline_runtime, "start_mlflow_run", fake_start_mlflow_run)
    monkeypatch.setattr(
        pipeline_runtime,
        "log_mlflow_artifacts",
        lambda *_args, **kwargs: artifact_calls.append(kwargs),
    )
    monkeypatch.setattr(pipeline_runtime, "run_lab", lambda *_args, **_kwargs: "")

    pipeline_runtime.run_locked_stage(
        SimpleNamespace(
            app="demo",
            active_app="",
            apps_path=tmp_path / "apps",
            copilot_file=tmp_path / "copilot.py",
        ),
        "page",
        stages_file,
        0,
        {"D": "demo stage", "Q": "question", "C": "print('hello')"},
        {},
        {},
        normalize_runtime_path=lambda value: str(value or ""),
        prepare_run_log_file=lambda *_args, **_kwargs: (tmp_path / "run.log", None),
        push_run_log=lambda _page, line, _placeholder=None: logs.append(line),
        refresh_pipeline_run_lock=lambda *_args, **_kwargs: None,
        acquire_pipeline_run_lock=lambda *_args, **_kwargs: "lock",
        release_pipeline_run_lock=lambda *_args, **_kwargs: None,
        get_run_placeholder=lambda *_args, **_kwargs: None,
        is_valid_runtime_root=lambda *_args, **_kwargs: False,
        python_for_venv=lambda *_args, **_kwargs: tmp_path / "python",
        stream_run_command=lambda *_args, **_kwargs: "",
        stage_summary=lambda *_args, **_kwargs: "summary",
    )

    assert any("Output (stage 1): runpy executed (no captured stdout)" in line for line in logs)
    assert artifact_calls and str(export_file) in artifact_calls[0]["file_artifacts"]


def test_run_locked_stage_agi_run_executes_script_and_logs(tmp_path, monkeypatch):
    snippet_file = tmp_path / "snippet.py"
    codex_file = tmp_path / "codex.py"
    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text("", encoding="utf-8")
    run_log = tmp_path / "stage_1.log"
    logs: list[str] = []
    releases: list[str] = []
    stream_calls: list[dict[str, object]] = []

    fake_streamlit = types.ModuleType("streamlit")
    fake_streamlit.session_state = {
        "snippet_file": str(snippet_file),
        "lab_selected_venv": str(tmp_path / "runtime"),
    }
    fake_streamlit.error = lambda message: logs.append(f"ERROR:{message}")
    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)

    @contextmanager
    def fake_start_mlflow_run(*_args, **_kwargs):
        yield {"run": SimpleNamespace(info=SimpleNamespace(run_id="run-456"))}

    monkeypatch.setattr(pipeline_runtime, "label_for_stage_runtime", lambda *_args, **_kwargs: "runtime env")
    monkeypatch.setattr(
        pipeline_runtime,
        "build_mlflow_process_env",
        lambda *_args, **_kwargs: {"MLFLOW_RUN_ID": "run-456", "EXTRA": "1"},
    )
    monkeypatch.setattr(pipeline_runtime, "start_mlflow_run", fake_start_mlflow_run)
    monkeypatch.setattr(pipeline_runtime, "log_mlflow_artifacts", lambda *_args, **_kwargs: logs.append("ARTIFACTS"))
    monkeypatch.setattr(pipeline_runtime, "wrap_code_with_mlflow_resume", lambda code: f"# wrapped\n{code}")

    env = SimpleNamespace(
        app="demo",
        active_app=str(tmp_path / "runtime"),
        apps_path=tmp_path / "apps",
        copilot_file=codex_file,
    )
    placeholder = SimpleNamespace(caption=lambda message: logs.append(f"CAPTION:{message}"))

    pipeline_runtime.run_locked_stage(
        env,
        "page",
        stages_file,
        0,
        {"D": "demo stage", "Q": "question", "C": "print('hello')", "R": "agi.run"},
        {0: str(tmp_path / "runtime")},
        {},
        normalize_runtime_path=lambda value: str(value or ""),
        prepare_run_log_file=lambda *_args, **_kwargs: (run_log, None),
        push_run_log=lambda _page, line, _placeholder=None: logs.append(line),
        refresh_pipeline_run_lock=lambda *_args, **_kwargs: None,
        acquire_pipeline_run_lock=lambda *_args, **_kwargs: "lock",
        release_pipeline_run_lock=lambda lock, *_args, **_kwargs: releases.append(lock),
        get_run_placeholder=lambda *_args, **_kwargs: placeholder,
        is_valid_runtime_root=lambda value: bool(value),
        python_for_venv=lambda *_args, **_kwargs: tmp_path / "runtime" / ".venv" / "bin" / "python",
        stream_run_command=lambda env, index_page, cmd, cwd, **kwargs: stream_calls.append(
            {"cmd": cmd, "cwd": cwd, "extra_env": kwargs.get("extra_env")}
        ) or "script output",
        stage_summary=lambda _entry, _limit: "summary",
    )

    script_path = stages_file.parent / "AGI_run.py"
    assert script_path.read_text(encoding="utf-8").startswith("# wrapped")
    assert Path(stream_calls[0]["cmd"][0]).name.startswith("python")
    assert stream_calls[0]["cmd"][1] == str(script_path)
    assert stream_calls[0]["cwd"] == stages_file.parent.resolve()
    assert stream_calls[0]["extra_env"] == {"MLFLOW_RUN_ID": "run-456", "EXTRA": "1"}
    assert any("engine=agi.run, env=runtime env" in line for line in logs)
    assert any("Output (stage 1):\nscript output" in line for line in logs)
    assert "ARTIFACTS" in logs
    assert releases == ["lock"]
