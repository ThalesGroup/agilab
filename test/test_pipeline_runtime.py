from __future__ import annotations

from contextlib import contextmanager
import importlib
import os
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest
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


def test_mlflow_text_and_path_helpers_cover_edge_cases(tmp_path, monkeypatch):
    env = SimpleNamespace(MLFLOW_TRACKING_DIR="relative-store", home_abs=tmp_path)

    assert pipeline_runtime.truncate_mlflow_text("abcdef", limit=4) == "abc…"
    assert pipeline_runtime.truncate_mlflow_text("abcdef", limit=1) == "a"
    assert pipeline_runtime.resolve_mlflow_backend_db(env) == (tmp_path / "relative-store" / "mlflow.db").resolve()
    assert pipeline_runtime.resolve_mlflow_artifact_dir(env) == (tmp_path / "relative-store" / "artifacts").resolve()
    assert pipeline_runtime.legacy_mlflow_filestore_present(tmp_path / "missing") is False
    assert pipeline_runtime.sqlite_uri_for_path(tmp_path / "mlflow.db").startswith("sqlite:")


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


def test_temporary_env_overrides_handles_none_and_missing(monkeypatch):
    monkeypatch.setenv("AGILAB_REMOVE_ME", "yes")

    with pipeline_runtime.temporary_env_overrides({"AGILAB_REMOVE_ME": None, "AGILAB_CREATE_ME": "created"}):
        assert "AGILAB_REMOVE_ME" not in os.environ
        assert os.environ["AGILAB_CREATE_ME"] == "created"

    assert os.environ["AGILAB_REMOVE_ME"] == "yes"
    assert "AGILAB_CREATE_ME" not in os.environ


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


def test_repair_mlflow_default_experiment_db_returns_false_for_missing_tables(tmp_path):
    db_path = tmp_path / "mlflow.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE runs (run_uuid TEXT PRIMARY KEY)")
        conn.commit()

    assert pipeline_runtime.repair_mlflow_default_experiment_db(db_path) is False


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
    assert "APP = 'demo'" in snippet
    assert "MODE = 7" in snippet
    assert 'SCHEDULER = \'tcp://127.0.0.1:8786\'' in snippet
    assert "WORKERS = {'127.0.0.1': 2}" in snippet
    assert "RUN_ARGS = {'data_in': 'input', 'data_out': 'output'}" in snippet


def test_ensure_safe_service_template_preserves_manual_file(tmp_path):
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text("", encoding="utf-8")
    template_path = tmp_path / "AGI_safe_service.py"
    template_path.write_text("# manual\nprint('keep')\n", encoding="utf-8")
    env = SimpleNamespace(
        app_settings_file=tmp_path / "missing.toml",
        apps_path=tmp_path / "apps",
        app="demo",
    )

    resolved = pipeline_runtime.ensure_safe_service_template(
        env,
        steps_file,
        template_filename="AGI_safe_service.py",
        marker="# AUTO",
        debug_log=lambda *_args, **_kwargs: None,
    )

    assert resolved == template_path
    assert template_path.read_text(encoding="utf-8") == "# manual\nprint('keep')\n"


def test_ensure_safe_service_template_writes_generated_content(tmp_path):
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text("", encoding="utf-8")
    env = SimpleNamespace(
        app_settings_file=tmp_path / "missing.toml",
        apps_path=tmp_path / "apps",
        app="demo",
    )

    resolved = pipeline_runtime.ensure_safe_service_template(
        env,
        steps_file,
        template_filename="AGI_safe_service.py",
        marker="# AUTO",
        debug_log=lambda *_args, **_kwargs: None,
    )

    assert resolved == tmp_path / "AGI_safe_service.py"
    assert resolved.read_text(encoding="utf-8").startswith("# AUTO")


def test_ensure_safe_service_template_is_noop_when_content_matches(tmp_path):
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text("", encoding="utf-8")
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
        steps_file,
        template_filename="AGI_safe_service.py",
        marker="# AUTO",
        debug_log=lambda *_args, **_kwargs: None,
    )

    assert resolved == template_path
    assert template_path.read_text(encoding="utf-8") == expected


def test_label_for_step_runtime_describes_controller_and_runtime_env(tmp_path, monkeypatch):
    runtime_root = tmp_path / "worker_env"
    runtime_root.mkdir()
    controller_python = tmp_path / "controller" / "python"
    controller_python.parent.mkdir(parents=True)
    controller_python.write_text("", encoding="utf-8")
    monkeypatch.setattr(pipeline_runtime.sys, "executable", str(controller_python))

    agi_code = "from agi_cluster.agi_distributor import AGI\nawait AGI.run(None)\n"

    assert (
        pipeline_runtime.label_for_step_runtime(runtime_root, engine="agi.run", code=agi_code)
        == "controller env -> worker_env"
    )
    assert (
        pipeline_runtime.label_for_step_runtime(runtime_root, engine="runpy", code="print('x')")
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


def test_run_locked_step_runpy_executes_and_logs(tmp_path, monkeypatch):
    snippet_file = tmp_path / "snippet.py"
    codex_file = tmp_path / "codex.py"
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text("", encoding="utf-8")
    run_log = tmp_path / "step_1.log"
    logs: list[str] = []
    released: list[str] = []

    fake_streamlit = types.ModuleType("streamlit")
    fake_streamlit.session_state = {"snippet_file": str(snippet_file)}
    fake_streamlit.error = lambda message: logs.append(f"ERROR:{message}")
    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)

    @contextmanager
    def fake_start_mlflow_run(*_args, **_kwargs):
        yield {"run": SimpleNamespace(info=SimpleNamespace(run_id="run-123"))}

    monkeypatch.setattr(pipeline_runtime, "label_for_step_runtime", lambda *_args, **_kwargs: "default env")
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

    pipeline_runtime.run_locked_step(
        env,
        "page",
        steps_file,
        0,
        {"D": "demo step", "Q": "question", "C": "print('hello')"},
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
        step_summary=lambda _entry, _limit: "summary",
    )

    assert fake_streamlit.session_state["page__run_logs"] == []
    assert any("Run step 1 started" in line for line in logs)
    assert any('Step 1: engine=runpy, env=default env, summary="summary"' in line for line in logs)
    assert any("Output (step 1):\nrunpy output" in line for line in logs)
    assert "ARTIFACTS" in logs
    assert released == ["lock"]


def test_run_locked_step_agi_run_executes_script_and_logs(tmp_path, monkeypatch):
    snippet_file = tmp_path / "snippet.py"
    codex_file = tmp_path / "codex.py"
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text("", encoding="utf-8")
    run_log = tmp_path / "step_1.log"
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

    monkeypatch.setattr(pipeline_runtime, "label_for_step_runtime", lambda *_args, **_kwargs: "runtime env")
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

    pipeline_runtime.run_locked_step(
        env,
        "page",
        steps_file,
        0,
        {"D": "demo step", "Q": "question", "C": "print('hello')", "R": "agi.run"},
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
        step_summary=lambda _entry, _limit: "summary",
    )

    script_path = steps_file.parent / "AGI_run.py"
    assert script_path.read_text(encoding="utf-8").startswith("# wrapped")
    assert stream_calls[0]["cmd"].endswith(f" {script_path}")
    assert stream_calls[0]["cwd"] == steps_file.parent.resolve()
    assert stream_calls[0]["extra_env"] == {"MLFLOW_RUN_ID": "run-456", "EXTRA": "1"}
    assert any("engine=agi.run, env=runtime env" in line for line in logs)
    assert any("Output (step 1):\nscript output" in line for line in logs)
    assert "ARTIFACTS" in logs
    assert releases == ["lock"]
