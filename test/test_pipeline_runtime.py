from __future__ import annotations

import importlib
import os
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import types


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


pipeline_runtime = _import_agilab_module("agilab.pipeline_runtime")


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
    assert process_env[pipeline_runtime.MLFLOW_STEP_RUN_ID_ENV] == "run-123"
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


def test_python_for_step_keeps_app_env_for_non_controller_snippet(tmp_path, monkeypatch):
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

    assert pipeline_runtime.python_for_step(runtime_root, engine="agi.run", code=agi_code) == controller_python
    assert pipeline_runtime.python_for_step(runtime_root, engine="agi.run", code=direct_code) == nested_python


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

    monkeypatch.setattr(pipeline_runtime.subprocess, "run", fake_run)
    monkeypatch.setattr(pipeline_runtime, "_MLFLOW_SQLITE_UPGRADE_CHECKED", set())

    env = SimpleNamespace(MLFLOW_TRACKING_DIR=tracking_root)

    first_uri = pipeline_runtime.mlflow_tracking_uri(env)
    second_uri = pipeline_runtime.mlflow_tracking_uri(env)

    assert first_uri == pipeline_runtime.sqlite_uri_for_path(db_path.resolve())
    assert second_uri == first_uri
    assert calls == [
        [
            sys.executable,
            "-m",
            "mlflow",
            "db",
            "upgrade",
            pipeline_runtime.sqlite_uri_for_path(db_path.resolve()),
        ]
    ]


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

    monkeypatch.setattr(pipeline_runtime.subprocess, "run", fake_run)
    monkeypatch.setattr(pipeline_runtime, "_MLFLOW_SQLITE_UPGRADE_CHECKED", set())

    env = SimpleNamespace(MLFLOW_TRACKING_DIR=tracking_root)

    uri = pipeline_runtime.mlflow_tracking_uri(env)

    assert uri == pipeline_runtime.sqlite_uri_for_path(db_path.resolve())
    assert not db_path.exists()
    assert len(list(tracking_root.glob("mlflow.schema-reset-*.db"))) == 1


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
