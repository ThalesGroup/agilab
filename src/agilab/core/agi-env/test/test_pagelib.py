from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from agi_env import pagelib


def test_background_services_enabled_respects_disable_flag(monkeypatch):
    monkeypatch.setenv("AGILAB_DISABLE_BACKGROUND_SERVICES", "true")
    monkeypatch.setattr(pagelib, "st", SimpleNamespace(session_state={}))

    assert pagelib.background_services_enabled() is False


def test_background_services_enabled_respects_streamlit_testing_state(monkeypatch):
    monkeypatch.delenv("AGILAB_DISABLE_BACKGROUND_SERVICES", raising=False)
    monkeypatch.setattr(
        pagelib,
        "st",
        SimpleNamespace(session_state={"$$STREAMLIT_INTERNAL_KEY_TESTING": True}),
    )

    assert pagelib.background_services_enabled() is False


def test_background_services_enabled_defaults_to_true(monkeypatch):
    monkeypatch.delenv("AGILAB_DISABLE_BACKGROUND_SERVICES", raising=False)
    monkeypatch.setattr(pagelib, "st", SimpleNamespace(session_state={}))

    assert pagelib.background_services_enabled() is True


def test_resolve_mlflow_backend_and_artifact_paths(tmp_path):
    tracking_dir = tmp_path / "mlflow"

    backend = pagelib._resolve_mlflow_backend_db(tracking_dir)
    artifact_dir = pagelib._resolve_mlflow_artifact_dir(tracking_dir)

    assert backend == tracking_dir / pagelib.DEFAULT_MLFLOW_DB_NAME
    assert artifact_dir == (tracking_dir / pagelib.DEFAULT_MLFLOW_ARTIFACT_DIR).resolve()
    assert artifact_dir.is_dir()


def test_legacy_mlflow_filestore_present_detects_legacy_layouts(tmp_path):
    tracking_dir = tmp_path / "mlflow"
    tracking_dir.mkdir()
    (tracking_dir / pagelib.DEFAULT_MLFLOW_DB_NAME).write_text("", encoding="utf-8")
    (tracking_dir / pagelib.DEFAULT_MLFLOW_ARTIFACT_DIR).mkdir()
    assert pagelib._legacy_mlflow_filestore_present(tracking_dir) is False

    (tracking_dir / ".trash").mkdir()
    assert pagelib._legacy_mlflow_filestore_present(tracking_dir) is True


def test_sqlite_identifier_escapes_quotes():
    assert pagelib._sqlite_identifier('a"b') == '"a""b"'


def test_load_last_active_app_prefers_global_state_file(tmp_path, monkeypatch):
    state_file = tmp_path / "app_state.toml"
    legacy_file = tmp_path / ".last-active-app"
    app_dir = tmp_path / "demo_app"
    app_dir.mkdir()
    state_file.write_text(f'last_active_app = "{app_dir}"\n', encoding="utf-8")

    monkeypatch.setattr(pagelib, "_GLOBAL_STATE_FILE", state_file)
    monkeypatch.setattr(pagelib, "_LEGACY_LAST_APP_FILE", legacy_file)

    assert pagelib.load_last_active_app() == app_dir


def test_load_global_state_falls_back_to_legacy_plaintext(tmp_path, monkeypatch):
    state_file = tmp_path / "app_state.toml"
    legacy_file = tmp_path / ".last-active-app"
    legacy_file.write_text("/tmp/legacy-app\n", encoding="utf-8")

    monkeypatch.setattr(pagelib, "_GLOBAL_STATE_FILE", state_file)
    monkeypatch.setattr(pagelib, "_LEGACY_LAST_APP_FILE", legacy_file)

    assert pagelib._load_global_state() == {"last_active_app": "/tmp/legacy-app"}


def test_store_last_active_app_persists_state(tmp_path, monkeypatch):
    state_file = tmp_path / "app_state.toml"
    legacy_file = tmp_path / ".last-active-app"
    app_dir = tmp_path / "stored_app"
    app_dir.mkdir()

    monkeypatch.setattr(pagelib, "_GLOBAL_STATE_FILE", state_file)
    monkeypatch.setattr(pagelib, "_LEGACY_LAST_APP_FILE", legacy_file)

    pagelib.store_last_active_app(app_dir)

    stored = tomllib.loads(state_file.read_text(encoding="utf-8"))
    assert stored["last_active_app"] == str(app_dir)


def test_store_last_active_app_skips_persist_when_unchanged(monkeypatch, tmp_path):
    app_dir = tmp_path / "stored_app"
    app_dir.mkdir()
    monkeypatch.setattr(pagelib, "_load_global_state", lambda: {"last_active_app": str(app_dir)})
    called: list[dict[str, str]] = []
    monkeypatch.setattr(pagelib, "_persist_global_state", lambda data: called.append(data))

    pagelib.store_last_active_app(app_dir)

    assert called == []


def test_persist_global_state_writes_toml(tmp_path, monkeypatch):
    state_file = tmp_path / "app_state.toml"

    monkeypatch.setattr(pagelib, "_GLOBAL_STATE_FILE", state_file)

    pagelib._persist_global_state({"last_active_app": "/tmp/demo"})

    stored = tomllib.loads(state_file.read_text(encoding="utf-8"))
    assert stored == {"last_active_app": "/tmp/demo"}


def test_load_last_active_app_returns_none_when_target_is_missing(tmp_path, monkeypatch):
    state_file = tmp_path / "app_state.toml"
    state_file.write_text('last_active_app = "/tmp/missing-app"\n', encoding="utf-8")

    monkeypatch.setattr(pagelib, "_GLOBAL_STATE_FILE", state_file)
    monkeypatch.setattr(pagelib, "_LEGACY_LAST_APP_FILE", tmp_path / ".last-active-app")

    assert pagelib.load_last_active_app() is None


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

    assert recorded == {"command": "echo 'ok'", "cwd": "/tmp"}


def test_run_with_output_raises_jump_to_main_when_module_is_missing(tmp_path, monkeypatch):
    apps_root = tmp_path / "apps"
    apps_root.mkdir()

    class FakeProc:
        returncode = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def communicate(self, timeout=None):
            return "module not found: demo", None

        def kill(self):
            return None

    monkeypatch.setattr(pagelib.subprocess, "Popen", lambda *args, **kwargs: FakeProc())

    with pytest.raises(pagelib.JumpToMain, match="module not found: demo"):
        pagelib.run_with_output(SimpleNamespace(apps_path=apps_root), "echo demo", cwd=tmp_path)


def test_run_with_output_returns_clean_output_for_failed_command(tmp_path, monkeypatch):
    apps_root = tmp_path / "apps"
    (apps_root / ".venv").mkdir(parents=True)

    class FakeProc:
        returncode = 1

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def communicate(self, timeout=None):
            return "\x1b[31mFAILED\x1b[0m", None

        def kill(self):
            return None

    monkeypatch.setattr(pagelib.subprocess, "Popen", lambda *args, **kwargs: FakeProc())

    output = pagelib.run_with_output(SimpleNamespace(apps_path=apps_root), "echo demo", cwd=tmp_path)

    assert output == "FAILED"


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
    assert pagelib._with_anchor("http://example", "section") == "http://example#section"
    assert pagelib._with_anchor("http://example", "#section") == "http://example#section"
    assert pagelib._with_anchor("http://example", "") == "http://example"


def test_is_valid_ip_accepts_ipv4_and_rejects_out_of_range():
    assert pagelib.is_valid_ip("192.168.20.130") is True
    assert pagelib.is_valid_ip("300.168.20.130") is False


def test_get_first_match_and_keyword_handles_empty_inputs_and_first_match():
    assert pagelib.get_first_match_and_keyword([], ["time"]) == (None, None)
    assert pagelib.get_first_match_and_keyword(["alpha", "mission_time"], ["date", "time"]) == (
        "mission_time",
        "time",
    )


def test_open_docs_url_reuses_existing_tab(monkeypatch):
    opened = []

    def open_new_tab(url):
        opened.append(url)

    pagelib._DOCS_ALREADY_OPENED = False
    pagelib._LAST_DOCS_URL = None
    monkeypatch.setattr(pagelib.webbrowser, "open_new_tab", open_new_tab)
    monkeypatch.setattr(pagelib, "_focus_existing_docs_tab", lambda _: True)

    pagelib._open_docs_url("http://example/docs")
    pagelib._open_docs_url("http://example/docs")

    assert opened == ["http://example/docs"]


def test_resolve_docs_path_prefers_build(tmp_path):
    pkg_root = tmp_path / "pkg"
    docs_build = pkg_root / "docs" / "build"
    docs_build.mkdir(parents=True)
    target = docs_build / "index.html"
    target.write_text("hello", encoding="utf-8")
    env = SimpleNamespace(agilab_pck=pkg_root)

    resolved = pagelib._resolve_docs_path(env, "index.html")

    assert resolved == target


def test_resolve_docs_path_falls_back_to_recursive_search(tmp_path):
    pkg_root = tmp_path / "pkg"
    nested = pkg_root.parent / "docs" / "nested"
    nested.mkdir(parents=True)
    target = nested / "guide.html"
    target.write_text("guide", encoding="utf-8")
    env = SimpleNamespace(agilab_pck=pkg_root)

    resolved = pagelib._resolve_docs_path(env, "guide.html")

    assert resolved == target


def test_open_docs_falls_back_to_online(monkeypatch):
    captured = {}

    def fake_open(url):
        captured["url"] = url

    monkeypatch.setattr(pagelib, "_open_docs_url", fake_open)
    env = SimpleNamespace(agilab_pck=Path("/does/not/exist"))

    pagelib.open_docs(env, html_file="missing.html", anchor="anchor")

    assert captured["url"] == "https://thalesgroup.github.io/agilab/index.html#anchor"


def test_open_local_docs_requires_existing_file(tmp_path, monkeypatch):
    pkg_root = tmp_path / "pkg"
    docs_build = pkg_root / "docs" / "build"
    docs_build.mkdir(parents=True)
    html_path = docs_build / "page.html"
    html_path.write_text("doc", encoding="utf-8")
    env = SimpleNamespace(agilab_pck=pkg_root)

    opened = {}
    monkeypatch.setattr(pagelib, "_open_docs_url", lambda url: opened.setdefault("url", url))

    pagelib.open_local_docs(env, html_file="page.html", anchor="a")

    assert opened["url"].startswith(html_path.as_uri())

    with pytest.raises(FileNotFoundError):
        pagelib.open_local_docs(env, html_file="missing.html")


def test_cached_load_df_uses_session_max_rows_and_zero_means_all(monkeypatch):
    fake_st = SimpleNamespace(session_state={"TABLE_MAX_ROWS": "7"})
    calls: list[tuple[object, bool, object]] = []
    monkeypatch.setattr(pagelib, "st", fake_st)
    monkeypatch.setattr(
        pagelib,
        "load_df",
        lambda path, with_index=True, nrows=None: calls.append((path, with_index, nrows)) or "loaded",
    )

    cached = getattr(pagelib.cached_load_df, "__wrapped__", pagelib.cached_load_df)
    assert cached("demo.csv", with_index=False) == "loaded"
    assert calls[-1] == ("demo.csv", False, 7)

    fake_st.session_state["TABLE_MAX_ROWS"] = 0
    assert cached("demo.csv", with_index=True) == "loaded"
    assert calls[-1] == ("demo.csv", True, None)


def test_render_dataframe_preview_renders_caption_when_truncated(monkeypatch):
    rendered = {}
    captions: list[str] = []
    monkeypatch.setattr(pagelib.st, "dataframe", lambda df, **kwargs: rendered.setdefault("frame", (df.copy(), kwargs)))
    monkeypatch.setattr(pagelib.st, "caption", lambda text: captions.append(text))

    pagelib.render_dataframe_preview(
        pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6], "c": [7, 8, 9]}),
        max_rows=2,
        max_cols=2,
        hide_index=True,
        truncation_label="Preview cut",
    )

    preview_df, kwargs = rendered["frame"]
    assert list(preview_df.columns) == ["a", "b"]
    assert len(preview_df) == 2
    assert kwargs["hide_index"] is True
    assert captions == ["Preview cut: showing first 2 of 3 rows, showing first 2 of 3 columns."]


def test_render_dataframe_preview_requires_dataframe():
    with pytest.raises(TypeError, match="pandas DataFrame"):
        pagelib.render_dataframe_preview(["not", "a", "df"])


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


def test_save_csv_rejects_empty_name_and_directory(tmp_path, monkeypatch):
    errors: list[str] = []
    monkeypatch.setattr(pagelib.st, "error", lambda message: errors.append(message))
    df = SimpleNamespace(shape=(1, 1))

    assert pagelib.save_csv(df, Path("   ")) is False
    assert "filename" in errors[-1].lower()

    errors.clear()
    directory = tmp_path / "existing"
    directory.mkdir()
    assert pagelib.save_csv(df, directory) is False
    assert "directory" in errors[-1].lower()


def test_load_df_supports_csv_json_directory_and_time_index(tmp_path):
    csv_path = tmp_path / "times.csv"
    csv_path.write_text("time,value,index\n1,10,drop\n2,20,drop\n", encoding="utf-8")

    loaded_csv = getattr(pagelib.load_df, "__wrapped__", pagelib.load_df)(csv_path)
    assert list(loaded_csv["value"]) == [10, 20]
    assert loaded_csv.index[0] == pd.to_timedelta(1, unit="s")
    assert "index" not in loaded_csv.columns

    json_path = tmp_path / "records.json"
    json_path.write_text('[{"date": "2026-01-01", "value": 1}]', encoding="utf-8")
    loaded_json = getattr(pagelib.load_df, "__wrapped__", pagelib.load_df)(json_path)
    assert str(loaded_json.index[0].date()) == "2026-01-01"

    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "a.csv").write_text("date,value\n2026-01-01,1\n", encoding="utf-8")
    (folder / "b.csv").write_text("date,value\n2026-01-02,2\n", encoding="utf-8")
    loaded_dir = getattr(pagelib.load_df, "__wrapped__", pagelib.load_df)(folder)
    loaded_dir = loaded_dir.sort_index()
    assert list(loaded_dir["value"]) == [1, 2]

    unsupported = tmp_path / "notes.txt"
    unsupported.write_text("x", encoding="utf-8")
    assert getattr(pagelib.load_df, "__wrapped__", pagelib.load_df)(unsupported) is None


def test_resolve_mlflow_tracking_dir_falls_back_to_home(tmp_path):
    env = SimpleNamespace(MLFLOW_TRACKING_DIR="", home_abs=tmp_path)

    tracking_dir = pagelib._resolve_mlflow_tracking_dir(env)

    assert tracking_dir == (tmp_path / ".mlflow").resolve()


def test_activate_mlflow_initializes_default_experiment(tmp_path, monkeypatch):
    calls = {}

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
    assert "mlflow server" in launched["call"][0]
    assert pagelib._sqlite_uri_for_path(expected_db) in launched["call"][0]
    assert expected_artifacts.resolve().as_uri() in launched["call"][0]
    assert "--port 50123" in launched["call"][0]
    assert "--host 127.0.0.1" in launched["call"][0]
    assert fake_st.session_state["server_started"] is True
    assert fake_st.session_state["mlflow_port"] == 50123


def test_activate_mlflow_migrates_legacy_filestore(tmp_path, monkeypatch):
    tracking_dir = (tmp_path / ".mlflow").resolve()
    (tracking_dir / "0").mkdir(parents=True)
    (tracking_dir / "meta.yaml").write_text("legacy", encoding="utf-8")
    migrate = {}

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
    monkeypatch.setattr(pagelib, "subproc", lambda *_args, **_kwargs: None)

    pagelib.activate_mlflow(SimpleNamespace(MLFLOW_TRACKING_DIR="", home_abs=tmp_path))

    assert migrate["cmd"][:4] == [sys.executable, "-m", "mlflow", "migrate-filestore"]
    assert migrate["cmd"][5] == str(tracking_dir)
    assert migrate["cmd"][7] == pagelib._sqlite_uri_for_path(tracking_dir / "mlflow.db")


def test_reset_mlflow_sqlite_backend_moves_sidecars(tmp_path, monkeypatch):
    db_path = tmp_path / "mlflow.db"
    for suffix in ("", "-shm", "-wal", "-journal"):
        Path(f"{db_path}{suffix}").write_text("x", encoding="utf-8")

    monkeypatch.setattr(pagelib.time, "strftime", lambda *_args, **_kwargs: "20260402_120000")

    backup = pagelib._reset_mlflow_sqlite_backend(db_path)

    assert backup == tmp_path / "mlflow.schema-reset-20260402_120000.db"
    for suffix in ("", "-shm", "-wal", "-journal"):
        assert not Path(f"{db_path}{suffix}").exists()
        assert Path(f"{backup}{suffix}").exists()


def test_ensure_mlflow_sqlite_schema_current_raises_without_reset_marker(tmp_path, monkeypatch):
    db_path = tmp_path / "mlflow.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.execute("INSERT INTO alembic_version (version_num) VALUES (?)", ("head",))
        conn.commit()

    monkeypatch.setattr(
        pagelib.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="plain upgrade failure"),
    )
    monkeypatch.setattr(pagelib, "_MLFLOW_SQLITE_UPGRADE_CHECKED", set())

    with pytest.raises(RuntimeError, match="Failed to upgrade the local MLflow SQLite schema"):
        pagelib._ensure_mlflow_sqlite_schema_current(db_path)


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

    def fake_run(cmd, check, capture_output, text):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(pagelib.subprocess, "run", fake_run)
    monkeypatch.setattr(pagelib, "_MLFLOW_SQLITE_UPGRADE_CHECKED", set())

    first_uri = pagelib._ensure_mlflow_backend_ready(tracking_dir)
    second_uri = pagelib._ensure_mlflow_backend_ready(tracking_dir)

    assert first_uri == pagelib._sqlite_uri_for_path(db_path)
    assert second_uri == first_uri
    assert calls == [
        [
            sys.executable,
            "-m",
            "mlflow",
            "db",
            "upgrade",
            pagelib._sqlite_uri_for_path(db_path),
        ]
    ]


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


def test_get_projects_zip_templates_and_about_content(tmp_path, monkeypatch):
    export_apps = tmp_path / "exports"
    export_apps.mkdir()
    (export_apps / "alpha.zip").write_text("x", encoding="utf-8")
    (export_apps / "beta.zip").write_text("x", encoding="utf-8")
    apps_root = tmp_path / "apps"
    (apps_root / "templates" / "demo").mkdir(parents=True)
    agilab_pkg = tmp_path / "pkg"
    (agilab_pkg / "agilab" / "templates" / "builtin").mkdir(parents=True)

    monkeypatch.setattr(
        pagelib,
        "st",
        SimpleNamespace(session_state={"env": SimpleNamespace(export_apps=export_apps, apps_path=apps_root, agilab_pck=agilab_pkg)}),
    )

    assert sorted(pagelib.get_projects_zip()) == ["alpha.zip", "beta.zip"]
    assert pagelib.get_templates() == ["builtin", "demo"]
    assert "AGILab" in pagelib.get_about_content()["About"]


def test_init_custom_ui_clears_form_keys(monkeypatch):
    fake_state = {
        "toggle_edit_ui": True,
        "x:app_args_form:field": "value",
        "keep": "ok",
    }
    monkeypatch.setattr(pagelib, "st", SimpleNamespace(session_state=fake_state))

    pagelib.init_custom_ui(Path("/tmp/form.py"))

    assert fake_state["toggle_edit"] is False
    assert "x:app_args_form:field" not in fake_state
    assert fake_state["app_args_form_refresh_nonce"] == 1
    assert fake_state["keep"] == "ok"


def test_detect_agilab_version_prefers_source_pyproject_and_git_metadata(tmp_path, monkeypatch):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname='agilab'\nversion='2026.4.2'\n", encoding="utf-8")

    calls = []
    def fake_run(cmd, check, stdout, stderr, text):
        calls.append(cmd)
        if "rev-parse" in cmd:
            return SimpleNamespace(stdout="abc123\n")
        return SimpleNamespace(stdout="dirty\n")

    monkeypatch.setattr(pagelib.subprocess, "run", fake_run)

    version = pagelib._detect_agilab_version(SimpleNamespace(is_source_env=True, agilab_pck=tmp_path))

    assert version == "2026.4.2+dev.abc123*"
    assert len(calls) == 2


def test_detect_agilab_version_falls_back_to_installed_metadata(monkeypatch):
    monkeypatch.setattr(pagelib, "_importlib_metadata", SimpleNamespace(version=lambda _name: "9.9.9"))

    version = pagelib._detect_agilab_version(SimpleNamespace(is_source_env=False, agilab_pck=None))

    assert version == "9.9.9"


def test_render_logo_shows_version_when_logo_exists(tmp_path, monkeypatch):
    logo_path = tmp_path / "agilab_logo.png"
    logo_path.write_text("png", encoding="utf-8")
    sidebar = SimpleNamespace(
        image=lambda path, width: setattr(sidebar, "image_call", (path, width)),
        caption=lambda text: setattr(sidebar, "caption_text", text),
        warning=lambda text: setattr(sidebar, "warning_text", text),
    )
    fake_st = SimpleNamespace(session_state={"env": SimpleNamespace(st_resources=tmp_path)}, sidebar=sidebar)
    monkeypatch.setattr(pagelib, "st", fake_st)
    monkeypatch.setattr(pagelib, "_detect_agilab_version", lambda env: "2026.4.2")

    pagelib.render_logo()

    assert sidebar.image_call == (str(logo_path), 170)
    assert sidebar.caption_text == "v2026.4.2"


def test_get_df_index_list_views_read_lines_and_scan_dir(tmp_path):
    file_path = tmp_path / "demo.csv"
    file_path.write_text("a\n1\n", encoding="utf-8")
    (tmp_path / "views").mkdir()
    (tmp_path / "views" / "first.py").write_text("print('a')\n", encoding="utf-8")
    (tmp_path / "views" / "__init__.py").write_text("", encoding="utf-8")
    subdir = tmp_path / "subdir"
    subdir.mkdir()

    assert pagelib.get_df_index([str(file_path)], file_path) == 0
    assert pagelib.get_df_index([], None) is None
    assert pagelib.list_views(str(tmp_path / "views")) == [str(tmp_path / "views" / "first.py")]
    assert list(pagelib.read_file_lines(file_path)) == ["a", "1"]
    assert sorted(pagelib.scan_dir(tmp_path)) == ["subdir", "views"]


def test_resolve_active_app_prefers_query_param_and_fallback_last_app(tmp_path, monkeypatch):
    apps_root = tmp_path / "apps"
    builtin_root = apps_root / "builtin"
    target = builtin_root / "flight_project"
    target.mkdir(parents=True)
    changed_to: list[Path] = []
    stored: list[Path] = []
    fake_st = SimpleNamespace(query_params={"active_app": "flight"})
    monkeypatch.setattr(pagelib, "st", fake_st)
    monkeypatch.setattr(pagelib, "store_last_active_app", lambda path: stored.append(path))

    env = SimpleNamespace(
        apps_path=apps_root,
        app="mycode_project",
        projects=["flight_project"],
        active_app=apps_root / "mycode_project",
        change_app=lambda path: changed_to.append(path) or setattr(env, "active_app", path) or setattr(env, "app", path.name),
    )

    app_name, changed = pagelib.resolve_active_app(env)

    assert changed is True
    assert app_name == "flight_project"
    assert changed_to == [target]
    assert stored == [target]

    monkeypatch.setattr(pagelib, "st", SimpleNamespace(query_params={}))
    last_app = apps_root / "demo_project"
    last_app.mkdir(parents=True)
    monkeypatch.setattr(pagelib, "load_last_active_app", lambda: last_app)

    env.app = "flight_project"
    env.active_app = target
    changed_to.clear()
    app_name, changed = pagelib.resolve_active_app(env)

    assert changed is True
    assert app_name == "demo_project"
    assert changed_to == [last_app]


def test_activate_gpt_oss_handles_missing_package_and_success(monkeypatch):
    class FakeSessionState(dict):
        def __getattr__(self, name):
            try:
                return self[name]
            except KeyError as exc:
                raise AttributeError(name) from exc

        def __setattr__(self, name, value):
            self[name] = value

    warnings: list[str] = []
    errors: list[str] = []
    fake_st = SimpleNamespace(
        session_state=FakeSessionState(),
        warning=lambda message: warnings.append(str(message)),
        error=lambda message: errors.append(str(message)),
    )
    monkeypatch.setattr(pagelib, "st", fake_st)
    monkeypatch.setitem(sys.modules, "gpt_oss", None)

    real_import = __import__
    def fake_import(name, *args, **kwargs):
        if name == "gpt_oss":
            raise ImportError("missing gpt_oss")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    env = SimpleNamespace(envars={})

    assert pagelib.activate_gpt_oss(env) is False
    assert any("Install `gpt-oss`" in msg for msg in warnings)
    assert fake_st.session_state["gpt_oss_autostart_failed"] is True

    monkeypatch.setattr("builtins.__import__", real_import)
    sys.modules["gpt_oss"] = SimpleNamespace()
    fake_st.session_state.clear()
    warnings.clear()
    monkeypatch.setattr(pagelib, "get_random_port", lambda: 50124)
    monkeypatch.setattr(pagelib, "is_port_in_use", lambda _port: False)
    launched = {}
    monkeypatch.setattr(pagelib, "subproc", lambda command, cwd: launched.setdefault("call", (command, cwd)))

    assert pagelib.activate_gpt_oss(env) is True
    assert "gpt_oss.responses_api.serve" in launched["call"][0]
    assert "--inference-backend stub" in launched["call"][0]
    assert fake_st.session_state["gpt_oss_server_started"] is True
    assert fake_st.session_state["gpt_oss_endpoint"] == "http://127.0.0.1:50124/v1/responses"
    assert env.envars["GPT_OSS_ENDPOINT"] == "http://127.0.0.1:50124/v1/responses"


def test_activate_gpt_oss_requires_checkpoint_for_transformers_backend(monkeypatch):
    class FakeSessionState(dict):
        def __getattr__(self, name):
            try:
                return self[name]
            except KeyError as exc:
                raise AttributeError(name) from exc

        def __setattr__(self, name, value):
            self[name] = value

    warnings: list[str] = []
    fake_st = SimpleNamespace(
        session_state=FakeSessionState({"gpt_oss_backend": "vllm"}),
        warning=lambda message: warnings.append(str(message)),
        error=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(pagelib, "st", fake_st)
    sys.modules["gpt_oss"] = SimpleNamespace()

    env = SimpleNamespace(envars={})
    assert pagelib.activate_gpt_oss(env) is False
    assert any("requires a checkpoint" in msg for msg in warnings)
