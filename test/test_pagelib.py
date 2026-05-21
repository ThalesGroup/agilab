from __future__ import annotations

import subprocess
import os
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest

from agi_env import pagelib, ui_support


def _patch_mlflow_cli(monkeypatch):
    monkeypatch.setattr(
        pagelib.mlflow_store,
        "mlflow_cli_argv",
        lambda args, **_kwargs: ["mlflow", *args],
    )


def test_diagnose_data_directory_reports_missing_mount(tmp_path, monkeypatch):
    missing_mount = tmp_path / "missing_share"
    monkeypatch.setattr(pagelib, "_fstab_mount_points", lambda: (missing_mount,))
    monkeypatch.setattr(pagelib, "_current_mount_points", lambda: {})

    message = pagelib.diagnose_data_directory(missing_mount / "payload")

    assert "not mounted" in message


def test_diagnose_data_directory_reports_empty_share(tmp_path, monkeypatch):
    mount_dir = tmp_path / "data_share"
    mount_dir.mkdir()
    monkeypatch.setattr(pagelib, "_fstab_mount_points", lambda: (mount_dir,))
    monkeypatch.setattr(pagelib, "_current_mount_points", lambda: {mount_dir: "nfs"})

    message = pagelib.diagnose_data_directory(mount_dir / "payload")

    assert "appears empty" in message


def test_diagnose_data_directory_ok(tmp_path, monkeypatch):
    mount_dir = tmp_path / "ready_share"
    payload_dir = mount_dir / "payload"
    payload_dir.mkdir(parents=True)
    (payload_dir / "marker.txt").write_text("ok", encoding="utf-8")

    monkeypatch.setattr(pagelib, "_fstab_mount_points", lambda: (mount_dir,))
    monkeypatch.setattr(pagelib, "_current_mount_points", lambda: {mount_dir: "nfs"})

    message = pagelib.diagnose_data_directory(payload_dir)

    assert message is None


def test_run_success(monkeypatch):
    recorded = {}

    def fake_run(command, shell, check, cwd, stdout, stderr):
        recorded["command"] = command
        recorded["cwd"] = cwd

    monkeypatch.setattr(pagelib.subprocess, "run", fake_run)

    pagelib.run("echo 'ok'", cwd="/tmp")

    assert recorded == {"command": ["echo", "ok"], "cwd": "/tmp"}


def test_run_failure_exits(monkeypatch):
    logs: list[str] = []

    def fake_log(message):
        logs.append(message)

    def fake_run(*_, **__):
        raise subprocess.CalledProcessError(
            2,
            "bad",
            output=b"stdout",
            stderr=b"stderr",
        )

    def fake_exit(code):
        raise RuntimeError(f"exit:{code}")

    monkeypatch.setattr(pagelib.subprocess, "run", fake_run)
    monkeypatch.setattr(pagelib, "log", fake_log)
    monkeypatch.setattr(pagelib.sys, "exit", fake_exit)

    with pytest.raises(RuntimeError, match="exit:2"):
        pagelib.run("bad")

    assert "Error executing command" in logs[0]


def test_with_anchor_appends_hash():
    assert ui_support.with_anchor("http://example", "section") == "http://example#section"
    assert ui_support.with_anchor("http://example", "#section") == "http://example#section"
    assert ui_support.with_anchor("http://example", "") == "http://example"


def test_open_docs_url_reuses_existing_tab(monkeypatch):
    opened = []

    def open_new_tab(url):
        opened.append(url)

    ui_support._DOCS_ALREADY_OPENED = False
    ui_support._LAST_DOCS_URL = None
    monkeypatch.setattr(ui_support.webbrowser, "open_new_tab", open_new_tab)
    monkeypatch.setattr(ui_support, "focus_existing_docs_tab", lambda _: True)

    ui_support.open_docs_url("http://example/docs")
    ui_support.open_docs_url("http://example/docs")

    assert opened == ["http://example/docs"]


def test_resolve_docs_path_prefers_build(tmp_path):
    pkg_root = tmp_path / "pkg"
    docs_build = pkg_root / "docs" / "build"
    docs_build.mkdir(parents=True)
    target = docs_build / "index.html"
    target.write_text("hello", encoding="utf-8")
    env = SimpleNamespace(agilab_pck=pkg_root)

    resolved = ui_support.resolve_docs_path(env, "index.html")

    assert resolved == target


def test_open_docs_falls_back_to_online(monkeypatch):
    captured = {}

    def fake_open(url):
        captured["url"] = url

    monkeypatch.setattr(ui_support, "open_docs_url", fake_open)
    env = SimpleNamespace(agilab_pck=Path("/does/not/exist"))

    ui_support.open_docs(env, html_file="missing.html", anchor="anchor")

    assert captured["url"] == "https://thalesgroup.github.io/agilab/index.html#anchor"


def test_open_local_docs_requires_existing_file(tmp_path, monkeypatch):
    pkg_root = tmp_path / "pkg"
    docs_build = pkg_root / "docs" / "build"
    docs_build.mkdir(parents=True)
    html_path = docs_build / "page.html"
    html_path.write_text("doc", encoding="utf-8")
    env = SimpleNamespace(agilab_pck=pkg_root)

    opened = {}
    monkeypatch.setattr(ui_support, "open_docs_url", lambda url: opened.setdefault("url", url))

    ui_support.open_local_docs(env, html_file="page.html", anchor="a")

    assert opened["url"].startswith(html_path.as_uri())

    with pytest.raises(FileNotFoundError):
        ui_support.open_local_docs(env, html_file="missing.html")


def test_run_lab_captures_output_and_restores_env(tmp_path, monkeypatch):
    snippet = tmp_path / "snippet.py"
    codex = tmp_path / "codex.py"
    codex.write_text("print('tracking=' + os.environ.get('MLFLOW_TRACKING_URI', ''))\n", encoding="utf-8")

    def fake_run_path(_path):
        exec("import os\nprint('tracking=' + os.environ.get('MLFLOW_TRACKING_URI', ''))\n", {})

    monkeypatch.setattr(pagelib.runpy, "run_path", fake_run_path)
    monkeypatch.setattr(pagelib.st, "warning", lambda *_args, **_kwargs: None)
    os.environ.pop("MLFLOW_TRACKING_URI", None)

    output = pagelib.run_lab(
        ["D", "Q", "print('hello')"],
        snippet,
        codex,
        env_overrides={"MLFLOW_TRACKING_URI": "file:///tmp/mlflow"},
    )

    assert snippet.read_text(encoding="utf-8") == "print('hello')"
    assert "tracking=file:///tmp/mlflow" in output
    assert "MLFLOW_TRACKING_URI" not in os.environ


def test_resolve_mlflow_tracking_dir_falls_back_to_home(tmp_path):
    env = SimpleNamespace(MLFLOW_TRACKING_DIR="", home_abs=tmp_path)

    tracking_dir = pagelib._resolve_mlflow_tracking_dir(env)

    assert tracking_dir == (tmp_path / ".mlflow").resolve()


def test_activate_mlflow_initializes_default_experiment(tmp_path, monkeypatch):
    calls = {}
    _patch_mlflow_cli(monkeypatch)

    class FakeSessionState(dict):
        def __getattr__(self, name):
            try:
                return self[name]
            except KeyError as exc:
                raise AttributeError(name) from exc

        def __setattr__(self, name, value):
            self[name] = value

    class FakeMlflow:
        def get_experiment_by_name(self, value):
            return None

        def create_experiment(self, name, artifact_location=None):
            calls["created"] = (name, artifact_location)

        def set_tracking_uri(self, value):
            calls["tracking_uri"] = value

        def set_experiment(self, value):
            calls["experiment"] = value

    fake_st = SimpleNamespace(session_state=FakeSessionState(), error=lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pagelib, "st", fake_st)
    monkeypatch.setattr(pagelib, "_get_mlflow_module", lambda: FakeMlflow())
    monkeypatch.setattr(pagelib, "get_random_port", lambda: 50123)
    monkeypatch.setattr(pagelib, "is_port_in_use", lambda _port: False)
    monkeypatch.setattr(pagelib, "_wait_for_listen_port", lambda _port: True)
    monkeypatch.setattr(
        pagelib.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    launched = {}
    monkeypatch.setattr(
        pagelib,
        "subproc",
        lambda command, cwd: launched.setdefault("call", (command, cwd)),
    )

    env = SimpleNamespace(MLFLOW_TRACKING_DIR="", home_abs=tmp_path)
    pagelib.activate_mlflow(env)

    expected_dir = (tmp_path / ".mlflow").resolve()
    expected_db = expected_dir / "mlflow.db"
    expected_artifacts = expected_dir / "artifacts"
    assert expected_dir.exists()
    assert calls["tracking_uri"] == pagelib._sqlite_uri_for_path(expected_db)
    assert calls["experiment"] == pagelib.DEFAULT_MLFLOW_EXPERIMENT_NAME
    assert calls["created"] == (
        pagelib.DEFAULT_MLFLOW_EXPERIMENT_NAME,
        expected_artifacts.resolve().as_uri(),
    )
    assert env.MLFLOW_TRACKING_DIR == str(expected_dir)
    command = launched["call"][0]
    assert command[:2] == ["mlflow", "server"]
    assert "-m" not in command
    assert command[command.index("--backend-store-uri") + 1] == pagelib._sqlite_uri_for_path(expected_db)
    assert command[command.index("--default-artifact-root") + 1] == expected_artifacts.resolve().as_uri()
    assert command[command.index("--port") + 1] == "50123"
    assert command[command.index("--host") + 1] == "127.0.0.1"
    assert fake_st.session_state["server_started"] is True
    assert fake_st.session_state["mlflow_port"] == 50123


def test_activate_mlflow_migrates_legacy_filestore(tmp_path, monkeypatch):
    tracking_dir = (tmp_path / ".mlflow").resolve()
    (tracking_dir / "0").mkdir(parents=True)
    (tracking_dir / "meta.yaml").write_text("legacy", encoding="utf-8")
    migrate = {}
    _patch_mlflow_cli(monkeypatch)

    class FakeSessionState(dict):
        def __getattr__(self, name):
            try:
                return self[name]
            except KeyError as exc:
                raise AttributeError(name) from exc

        def __setattr__(self, name, value):
            self[name] = value

    class FakeMlflow:
        def get_experiment_by_name(self, value):
            return None

        def create_experiment(self, name, artifact_location=None):
            return None

        def set_tracking_uri(self, value):
            return None

        def set_experiment(self, value):
            return None

    def fake_run(cmd, check, capture_output, text):
        migrate["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(pagelib.subprocess, "run", fake_run)
    monkeypatch.setattr(
        pagelib,
        "st",
        SimpleNamespace(session_state=FakeSessionState(), error=lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(pagelib, "_get_mlflow_module", lambda: FakeMlflow())
    monkeypatch.setattr(pagelib, "get_random_port", lambda: 50123)
    monkeypatch.setattr(pagelib, "is_port_in_use", lambda _port: False)
    monkeypatch.setattr(pagelib, "_wait_for_listen_port", lambda _port: True)
    monkeypatch.setattr(pagelib, "subproc", lambda *_args, **_kwargs: None)

    pagelib.activate_mlflow(SimpleNamespace(MLFLOW_TRACKING_DIR="", home_abs=tmp_path))

    assert migrate["cmd"][:2] == ["mlflow", "migrate-filestore"]
    assert "-m" not in migrate["cmd"]
    assert migrate["cmd"][migrate["cmd"].index("--source") + 1] == str(tracking_dir)
    assert migrate["cmd"][migrate["cmd"].index("--target") + 1] == pagelib._sqlite_uri_for_path(
        tracking_dir / "mlflow.db"
    )


def test_activate_mlflow_reports_port_start_failure(tmp_path, monkeypatch):
    errors = []
    _patch_mlflow_cli(monkeypatch)

    class FakeSessionState(dict):
        def __getattr__(self, name):
            try:
                return self[name]
            except KeyError as exc:
                raise AttributeError(name) from exc

        def __setattr__(self, name, value):
            self[name] = value

    fake_st = SimpleNamespace(session_state=FakeSessionState(), error=lambda message: errors.append(message))
    monkeypatch.setattr(pagelib, "st", fake_st)
    monkeypatch.setattr(pagelib, "_ensure_default_mlflow_experiment", lambda _tracking_dir: "sqlite:///tmp/mlflow.db")
    monkeypatch.setattr(pagelib, "_resolve_mlflow_artifact_dir", lambda _tracking_dir: tmp_path / "artifacts")
    monkeypatch.setattr(pagelib, "get_random_port", lambda: 50123)
    monkeypatch.setattr(pagelib, "is_port_in_use", lambda _port: False)
    monkeypatch.setattr(pagelib, "_wait_for_listen_port", lambda _port: False)
    monkeypatch.setattr(pagelib, "subproc", lambda *_args, **_kwargs: None)

    started = pagelib.activate_mlflow(SimpleNamespace(MLFLOW_TRACKING_DIR="", home_abs=tmp_path))

    assert started is False
    assert fake_st.session_state.get("server_started") is False
    assert "mlflow_port" not in fake_st.session_state
    assert any("did not open its listening port" in message for message in errors)


def test_ensure_mlflow_backend_ready_repairs_default_experiment_id_zero(tmp_path):
    tracking_dir = (tmp_path / ".mlflow").resolve()
    tracking_dir.mkdir(parents=True)
    db_path = tracking_dir / "mlflow.db"

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
            (3, pagelib.DEFAULT_MLFLOW_EXPERIMENT_NAME, "file:///legacy/mlruns/3", "active", 0, 0, "default"),
        )
        conn.execute("INSERT INTO runs (run_uuid, experiment_id) VALUES (?, ?)", ("run-1", 3))
        conn.commit()

    uri = pagelib._ensure_mlflow_backend_ready(tracking_dir)

    assert uri == pagelib._sqlite_uri_for_path(db_path)
    with sqlite3.connect(db_path) as conn:
        experiment = conn.execute(
            "SELECT experiment_id, artifact_location FROM experiments WHERE name = ?",
            (pagelib.DEFAULT_MLFLOW_EXPERIMENT_NAME,),
        ).fetchone()
        run = conn.execute("SELECT experiment_id FROM runs WHERE run_uuid = ?", ("run-1",)).fetchone()

    assert experiment == (
        0,
        (tracking_dir / "artifacts").resolve().as_uri(),
    )
    assert run == (0,)


def test_ensure_mlflow_backend_ready_upgrades_sqlite_schema_once(tmp_path, monkeypatch):
    tracking_dir = (tmp_path / ".mlflow").resolve()
    tracking_dir.mkdir(parents=True)
    db_path = tracking_dir / "mlflow.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.execute("INSERT INTO alembic_version (version_num) VALUES (?)", ("1b5f0d9ad7c1",))
        conn.commit()
    calls = []
    _patch_mlflow_cli(monkeypatch)

    def fake_run(cmd, check, capture_output, text):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(pagelib.subprocess, "run", fake_run)
    monkeypatch.setattr(pagelib, "_MLFLOW_SQLITE_UPGRADE_CHECKED", set())

    first_uri = pagelib._ensure_mlflow_backend_ready(tracking_dir)
    second_uri = pagelib._ensure_mlflow_backend_ready(tracking_dir)

    assert first_uri == pagelib._sqlite_uri_for_path(db_path)
    assert second_uri == first_uri
    assert calls == [["mlflow", "db", "upgrade", pagelib._sqlite_uri_for_path(db_path)]]


def test_ensure_mlflow_backend_ready_resets_unknown_alembic_revision(tmp_path, monkeypatch):
    tracking_dir = (tmp_path / ".mlflow").resolve()
    tracking_dir.mkdir(parents=True)
    db_path = tracking_dir / "mlflow.db"
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
    monkeypatch.setattr(pagelib.subprocess, "run", fake_run)
    monkeypatch.setattr(pagelib, "_MLFLOW_SQLITE_UPGRADE_CHECKED", set())

    uri = pagelib._ensure_mlflow_backend_ready(tracking_dir)

    assert uri == pagelib._sqlite_uri_for_path(db_path)
    assert not db_path.exists()
    assert len(list(tracking_dir.glob("mlflow.schema-reset-*.db"))) == 1


def test_ensure_default_mlflow_experiment_resets_store_after_schema_error(tmp_path, monkeypatch):
    tracking_dir = (tmp_path / ".mlflow").resolve()
    tracking_dir.mkdir(parents=True)
    calls: dict[str, object] = {"tracking": [], "reset": 0, "create": []}

    class FakeMlflow:
        def set_tracking_uri(self, uri):
            calls["tracking"].append(uri)

        def get_experiment_by_name(self, name):
            count = int(calls.get("lookup", 0)) + 1
            calls["lookup"] = count
            if count == 1:
                raise RuntimeError("Detected out-of-date database schema")
            return None

        def create_experiment(self, name, artifact_location=None):
            calls["create"].append((name, artifact_location))

        def set_experiment(self, name):
            calls["set_experiment"] = name

    monkeypatch.setattr(pagelib, "_get_mlflow_module", lambda: FakeMlflow())
    monkeypatch.setattr(pagelib, "_ensure_mlflow_backend_ready", lambda _: "sqlite:///tmp/mlflow.db")
    monkeypatch.setattr(
        pagelib,
        "_reset_mlflow_sqlite_backend",
        lambda path: calls.__setitem__("reset", int(calls["reset"]) + 1) or path,
    )

    uri = pagelib._ensure_default_mlflow_experiment(tracking_dir)

    assert uri == "sqlite:///tmp/mlflow.db"
    assert calls["reset"] == 1
    assert calls["tracking"] == ["sqlite:///tmp/mlflow.db", "sqlite:///tmp/mlflow.db"]
    assert calls["set_experiment"] == pagelib.DEFAULT_MLFLOW_EXPERIMENT_NAME


def test_ensure_default_mlflow_experiment_resets_store_after_duplicate_column_error(tmp_path, monkeypatch):
    tracking_dir = (tmp_path / ".mlflow").resolve()
    tracking_dir.mkdir(parents=True)
    calls: dict[str, object] = {"tracking": [], "reset": 0}

    class FakeMlflow:
        def set_tracking_uri(self, uri):
            calls["tracking"].append(uri)

        def get_experiment_by_name(self, name):
            count = int(calls.get("lookup", 0)) + 1
            calls["lookup"] = count
            if count == 1:
                raise RuntimeError("sqlite3.OperationalError: duplicate column name: storage_location")
            return None

        def create_experiment(self, name, artifact_location=None):
            return None

        def set_experiment(self, name):
            calls["set_experiment"] = name

    monkeypatch.setattr(pagelib, "_get_mlflow_module", lambda: FakeMlflow())
    monkeypatch.setattr(pagelib, "_ensure_mlflow_backend_ready", lambda _: "sqlite:///tmp/mlflow.db")
    monkeypatch.setattr(
        pagelib,
        "_reset_mlflow_sqlite_backend",
        lambda path: calls.__setitem__("reset", int(calls["reset"]) + 1) or path,
    )

    uri = pagelib._ensure_default_mlflow_experiment(tracking_dir)

    assert uri == "sqlite:///tmp/mlflow.db"
    assert calls["reset"] == 1
    assert calls["tracking"] == ["sqlite:///tmp/mlflow.db", "sqlite:///tmp/mlflow.db"]
    assert calls["set_experiment"] == pagelib.DEFAULT_MLFLOW_EXPERIMENT_NAME
