from __future__ import annotations

import importlib
import importlib.util
import os
from pathlib import Path
import sqlite3
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

    assert uri == pipeline_runtime.sqlite_uri_for_path((tmp_path / "mlflow-store" / "mlflow.db").resolve())
    assert (tmp_path / "mlflow-store").exists()
    assert (tmp_path / "mlflow-store" / "artifacts").exists()


def test_mlflow_tracking_uri_falls_back_to_home_when_unset(tmp_path):
    env = SimpleNamespace(MLFLOW_TRACKING_DIR="", home_abs=tmp_path)

    uri = pipeline_runtime.mlflow_tracking_uri(env)

    assert uri == pipeline_runtime.sqlite_uri_for_path((tmp_path / ".mlflow" / "mlflow.db").resolve())
    assert (tmp_path / ".mlflow").exists()


def test_mlflow_tracking_uri_resolves_relative_path_from_home(tmp_path):
    env = SimpleNamespace(MLFLOW_TRACKING_DIR="mlflow-store", home_abs=tmp_path)

    uri = pipeline_runtime.mlflow_tracking_uri(env)

    assert uri == pipeline_runtime.sqlite_uri_for_path((tmp_path / "mlflow-store" / "mlflow.db").resolve())
    assert (tmp_path / "mlflow-store").exists()


def test_build_mlflow_process_env_injects_tracking_and_run_id(tmp_path):
    env = SimpleNamespace(MLFLOW_TRACKING_DIR=tmp_path / "mlflow-store")

    process_env = pipeline_runtime.build_mlflow_process_env(
        env,
        run_id="run-123",
        base_env={"A": "1"},
    )

    assert process_env["A"] == "1"
    assert process_env["MLFLOW_TRACKING_URI"] == pipeline_runtime.sqlite_uri_for_path(
        (tmp_path / "mlflow-store" / "mlflow.db").resolve()
    )
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
        params={"step_count": 2},
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
    assert fake_mlflow.params["step_count"] == "2"
    assert fake_mlflow.run_requests == [{"run_name": "pipeline", "nested": True}]


def test_mlflow_tracking_uri_migrates_legacy_filestore(tmp_path, monkeypatch):
    tracking_root = tmp_path / "mlflow-store"
    (tracking_root / "0").mkdir(parents=True)
    (tracking_root / "meta.yaml").write_text("legacy", encoding="utf-8")
    calls = {}

    def fake_run(cmd, check, capture_output, text):
        calls["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(pipeline_runtime.subprocess, "run", fake_run)

    uri = pipeline_runtime.mlflow_tracking_uri(SimpleNamespace(MLFLOW_TRACKING_DIR=tracking_root))

    assert calls["cmd"][:4] == [sys.executable, "-m", "mlflow", "migrate-filestore"]
    assert calls["cmd"][4] == "--source"
    assert calls["cmd"][5] == str(tracking_root)
    assert calls["cmd"][6] == "--target"
    assert calls["cmd"][7] == pipeline_runtime.sqlite_uri_for_path(tracking_root / "mlflow.db")
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
