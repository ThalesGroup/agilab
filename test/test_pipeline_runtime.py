from __future__ import annotations

import importlib
import importlib.util
import os
from pathlib import Path
import sys
from types import SimpleNamespace


def _load_module(module_name: str, relative_path: str):
    module_path = Path(relative_path)
    importlib.invalidate_caches()
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


pipeline_runtime = _load_module("agilab.pipeline_runtime", "src/agilab/pipeline_runtime.py")


def test_to_bool_flag_parses_common_truthy_values():
    assert pipeline_runtime.to_bool_flag(True) is True
    assert pipeline_runtime.to_bool_flag("yes") is True
    assert pipeline_runtime.to_bool_flag("On") is True
    assert pipeline_runtime.to_bool_flag(0) is False
    assert pipeline_runtime.to_bool_flag("no") is False


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

    assert uri == (tmp_path / "mlflow-store").resolve().as_uri()
    assert (tmp_path / "mlflow-store").exists()


def test_build_mlflow_process_env_injects_tracking_and_run_id(tmp_path):
    env = SimpleNamespace(MLFLOW_TRACKING_DIR=tmp_path / "mlflow-store")

    process_env = pipeline_runtime.build_mlflow_process_env(
        env,
        run_id="run-123",
        base_env={"A": "1"},
    )

    assert process_env["A"] == "1"
    assert process_env["MLFLOW_TRACKING_URI"] == (tmp_path / "mlflow-store").resolve().as_uri()
    assert process_env[pipeline_runtime.MLFLOW_STEP_RUN_ID_ENV] == "run-123"
    assert process_env["MLFLOW_RUN_ID"] == "run-123"


def test_temporary_env_overrides_restores_previous_values(monkeypatch):
    monkeypatch.setenv("AGILAB_TEMP", "before")
    monkeypatch.delenv("AGILAB_NEW_TEMP", raising=False)

    with pipeline_runtime.temporary_env_overrides({"AGILAB_TEMP": "during", "AGILAB_NEW_TEMP": "x"}):
        assert os.environ["AGILAB_TEMP"] == "during"
        assert os.environ["AGILAB_NEW_TEMP"] == "x"

    assert os.environ["AGILAB_TEMP"] == "before"
    assert "AGILAB_NEW_TEMP" not in os.environ


def test_wrap_code_with_mlflow_resume_uses_env_run_id():
    wrapped = pipeline_runtime.wrap_code_with_mlflow_resume("print('hello')")

    assert pipeline_runtime.MLFLOW_STEP_RUN_ID_ENV in wrapped
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
            self.tags = {}
            self.params = {}
            self.run_requests = []

        def set_tracking_uri(self, value):
            self.tracking_uri = value

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
        params={"step_count": 2},
        nested=True,
    ) as tracking:
        assert tracking["run"].info.run_id == "run-1"

    assert fake_mlflow.tracking_uri == (tmp_path / "mlflow-store").resolve().as_uri()
    assert fake_mlflow.tags["k"] == "v"
    assert fake_mlflow.params["step_count"] == "2"
    assert fake_mlflow.run_requests == [{"run_name": "pipeline", "nested": True}]
