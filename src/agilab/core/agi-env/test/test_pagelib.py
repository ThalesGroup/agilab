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


def test_get_mlflow_module_returns_none_when_import_fails(monkeypatch):
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "mlflow":
            raise ImportError("missing mlflow")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    assert pagelib._get_mlflow_module() is None


def test_get_mlflow_module_returns_imported_module(monkeypatch):
    sentinel = SimpleNamespace(name="mlflow")
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "mlflow":
            return sentinel
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    assert pagelib._get_mlflow_module() is sentinel


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


def test_load_global_state_returns_empty_dict_for_invalid_toml_without_legacy(tmp_path, monkeypatch):
    state_file = tmp_path / "app_state.toml"
    state_file.write_text("not = [valid\n", encoding="utf-8")

    monkeypatch.setattr(pagelib, "_GLOBAL_STATE_FILE", state_file)
    monkeypatch.setattr(pagelib, "_LEGACY_LAST_APP_FILE", tmp_path / ".last-active-app")

    assert pagelib._load_global_state() == {}


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


def test_persist_global_state_swallows_dump_errors(tmp_path, monkeypatch):
    state_file = tmp_path / "app_state.toml"
    monkeypatch.setattr(pagelib, "_GLOBAL_STATE_FILE", state_file)
    monkeypatch.setattr(
        pagelib,
        "_dump_toml_payload",
        lambda _data, _handle: (_ for _ in ()).throw(OSError("disk full")),
    )

    pagelib._persist_global_state({"last_active_app": "/tmp/demo"})

    assert state_file.exists()


def test_load_last_active_app_returns_none_when_target_is_missing(tmp_path, monkeypatch):
    state_file = tmp_path / "app_state.toml"
    state_file.write_text('last_active_app = "/tmp/missing-app"\n', encoding="utf-8")

    monkeypatch.setattr(pagelib, "_GLOBAL_STATE_FILE", state_file)
    monkeypatch.setattr(pagelib, "_LEGACY_LAST_APP_FILE", tmp_path / ".last-active-app")

    assert pagelib.load_last_active_app() is None


def test_load_last_active_app_returns_none_for_unparseable_path(monkeypatch):
    monkeypatch.setattr(pagelib, "_load_global_state", lambda: {"last_active_app": object()})

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


def test_open_docs_prefers_local_file_when_available(tmp_path, monkeypatch):
    pkg_root = tmp_path / "pkg"
    docs_html = pkg_root / "docs" / "html"
    docs_html.mkdir(parents=True)
    html_path = docs_html / "guide.html"
    html_path.write_text("guide", encoding="utf-8")
    env = SimpleNamespace(agilab_pck=pkg_root)

    opened = {}
    monkeypatch.setattr(pagelib, "_open_docs_url", lambda url: opened.setdefault("url", url))

    pagelib.open_docs(env, html_file="guide.html", anchor="section")

    assert opened["url"] == f"{html_path.as_uri()}#section"


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


def test_get_base64_of_image_returns_encoded_contents(tmp_path):
    image_path = tmp_path / "logo.bin"
    image_path.write_bytes(b"abc")

    assert pagelib.get_base64_of_image(image_path) == "YWJj"


def test_get_base64_of_image_returns_empty_string_and_logs_errors(tmp_path, monkeypatch):
    missing = tmp_path / "missing.bin"
    errors: list[str] = []
    monkeypatch.setattr(pagelib, "st", SimpleNamespace(error=lambda message: errors.append(str(message))))

    assert pagelib.get_base64_of_image(missing) == ""
    assert errors and "Error loading" in errors[0]


def test_get_css_text_reads_resource_stylesheet(tmp_path, monkeypatch):
    scss_path = tmp_path / "code_editor.scss"
    scss_path.write_text("body { color: red; }\n", encoding="utf-8")
    monkeypatch.setattr(
        pagelib,
        "st",
        SimpleNamespace(session_state={"env": SimpleNamespace(st_resources=tmp_path)}),
    )

    get_css_text = getattr(pagelib.get_css_text, "__wrapped__", pagelib.get_css_text)

    assert get_css_text() == "body { color: red; }\n"


def test_inject_theme_renders_theme_stylesheet(tmp_path, monkeypatch):
    theme_path = tmp_path / "theme.css"
    theme_path.write_text("body { color: red; }\n", encoding="utf-8")
    markdown_calls: list[tuple[str, bool]] = []
    monkeypatch.setitem(
        sys.modules,
        "streamlit",
        SimpleNamespace(markdown=lambda text, unsafe_allow_html=False: markdown_calls.append((text, unsafe_allow_html))),
    )

    inject_theme = getattr(pagelib.inject_theme, "__wrapped__", pagelib.inject_theme)
    inject_theme(base_path=tmp_path)

    assert markdown_calls == [("<style>body { color: red; }\n</style>", True)]


def test_inject_theme_falls_back_to_binary_decode_when_text_read_fails(tmp_path, monkeypatch):
    theme_path = tmp_path / "theme.css"
    theme_path.write_bytes(b"\xffbody { color: blue; }\n")
    markdown_calls: list[tuple[str, bool]] = []
    monkeypatch.setitem(
        sys.modules,
        "streamlit",
        SimpleNamespace(markdown=lambda text, unsafe_allow_html=False: markdown_calls.append((text, unsafe_allow_html))),
    )

    inject_theme = getattr(pagelib.inject_theme, "__wrapped__", pagelib.inject_theme)
    inject_theme(base_path=tmp_path)

    assert len(markdown_calls) == 1
    assert markdown_calls[0][1] is True
    assert "body { color: blue; }" in markdown_calls[0][0]
    assert "\ufffd" in markdown_calls[0][0]


def test_open_docs_url_reopens_tab_when_focus_fails(monkeypatch):
    opened = []

    pagelib._DOCS_ALREADY_OPENED = True
    pagelib._LAST_DOCS_URL = "http://example/docs"
    monkeypatch.setattr(pagelib, "_focus_existing_docs_tab", lambda _: False)
    monkeypatch.setattr(pagelib.webbrowser, "open_new_tab", lambda url: opened.append(url))

    pagelib._open_docs_url("http://example/docs")

    assert opened == ["http://example/docs"]
    assert pagelib._DOCS_ALREADY_OPENED is True
    assert pagelib._LAST_DOCS_URL == "http://example/docs"


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


def test_find_files_filters_hidden_entries_and_honors_recursive_flag(tmp_path):
    root_file = tmp_path / "root.csv"
    root_file.write_text("a\n1\n", encoding="utf-8")
    nested_dir = tmp_path / "nested"
    nested_dir.mkdir()
    nested_file = nested_dir / "inner.csv"
    nested_file.write_text("a\n2\n", encoding="utf-8")
    hidden_dir = tmp_path / ".hidden"
    hidden_dir.mkdir()
    (hidden_dir / "ignored.csv").write_text("a\n3\n", encoding="utf-8")
    hidden_nested = nested_dir / ".secret"
    hidden_nested.mkdir()
    (hidden_nested / "ignored.csv").write_text("a\n4\n", encoding="utf-8")

    find_files = getattr(pagelib.find_files, "__wrapped__", pagelib.find_files)

    recursive_paths = sorted(path.relative_to(tmp_path).as_posix() for path in find_files(tmp_path, ".csv", True))
    non_recursive_paths = sorted(path.relative_to(tmp_path).as_posix() for path in find_files(tmp_path, ".csv", False))

    assert recursive_paths == ["nested/inner.csv", "root.csv"]
    assert non_recursive_paths == ["nested/inner.csv"]


def test_find_files_raises_with_directory_diagnosis(monkeypatch, tmp_path):
    find_files = getattr(pagelib.find_files, "__wrapped__", pagelib.find_files)
    missing = tmp_path / "missing"
    monkeypatch.setattr(pagelib, "diagnose_data_directory", lambda _path: "share unavailable")

    with pytest.raises(NotADirectoryError, match="share unavailable"):
        find_files(missing, ".csv", True)


def test_find_files_raises_generic_message_without_diagnosis(tmp_path, monkeypatch):
    find_files = getattr(pagelib.find_files, "__wrapped__", pagelib.find_files)
    missing = tmp_path / "missing"
    monkeypatch.setattr(pagelib, "diagnose_data_directory", lambda _path: None)

    with pytest.raises(NotADirectoryError, match="not a valid directory"):
        find_files(missing, ".csv", True)


def test_export_df_emits_warning_success_and_failure(monkeypatch):
    class FakeSessionState(dict):
        def __getattr__(self, name):
            try:
                return self[name]
            except KeyError as exc:
                raise AttributeError(name) from exc

        def __setattr__(self, name, value):
            self[name] = value

    warnings: list[str] = []
    successes: list[str] = []
    session_state = FakeSessionState({"df_file_out": "/tmp/out.csv"})
    fake_st = SimpleNamespace(
        session_state=session_state,
        warning=lambda message: warnings.append(str(message)),
        success=lambda message: successes.append(str(message)),
    )
    monkeypatch.setattr(pagelib, "st", fake_st)

    pagelib.export_df()
    assert warnings == ["DataFrame is empty. Nothing to export."]

    session_state["loaded_df"] = pd.DataFrame({"a": [1]})
    monkeypatch.setattr(pagelib, "save_csv", lambda df, path: False)
    pagelib.export_df()
    assert warnings[-1] == "Export failed; please check the filename and dataframe content."

    monkeypatch.setattr(pagelib, "save_csv", lambda df, path: True)
    pagelib.export_df()
    assert successes == ["Saved to /tmp/out.csv!"]


def test_update_views_creates_missing_links_and_removes_stale_hardlinks(tmp_path, monkeypatch):
    class FakeSessionState(dict):
        def __getattr__(self, name):
            try:
                return self[name]
            except KeyError as exc:
                raise AttributeError(name) from exc

        def __setattr__(self, name, value):
            self[name] = value

    repo_root = tmp_path / "repo"
    pages_root = repo_root / "src" / "gui" / "pages"
    pages_root.mkdir(parents=True)
    keep_view = tmp_path / "keep_view.py"
    keep_view.write_text("print('keep')\n", encoding="utf-8")
    new_view = tmp_path / "new_view.py"
    new_view.write_text("print('new')\n", encoding="utf-8")
    stale_source = tmp_path / "stale_view.py"
    stale_source.write_text("print('stale')\n", encoding="utf-8")
    local_only = pages_root / "local_only.py"
    local_only.write_text("print('local')\n", encoding="utf-8")
    os.link(stale_source, pages_root / "stale_view.py")

    changes: list[str] = []
    session_state = FakeSessionState(
        {
            "_env": SimpleNamespace(change_app=lambda project: changes.append(project)),
            "preview_tree": True,
        }
    )
    monkeypatch.setattr(pagelib, "st", SimpleNamespace(session_state=session_state))
    monkeypatch.setattr(pagelib.os, "getcwd", lambda: str(repo_root))

    updated = pagelib.update_views("demo_project", [str(keep_view), str(new_view)])

    assert updated is True
    assert changes == ["demo_project"]
    assert session_state["preview_tree"] is False
    assert (pages_root / "keep_view.py").exists()
    assert (pages_root / "new_view.py").exists()
    assert not (pages_root / "stale_view.py").exists()
    assert local_only.exists()


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


def test_resolve_mlflow_tracking_dir_resolves_relative_path_under_home(tmp_path):
    env = SimpleNamespace(MLFLOW_TRACKING_DIR="workspace/mlflow", home_abs=tmp_path)

    tracking_dir = pagelib._resolve_mlflow_tracking_dir(env)

    assert tracking_dir == (tmp_path / "workspace" / "mlflow").resolve()


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


def test_get_templates_falls_back_to_globbed_template_names(tmp_path, monkeypatch):
    apps_root = tmp_path / "apps"
    apps_root.mkdir()
    (apps_root / "alpha_template").mkdir()
    (apps_root / "beta_template").mkdir()
    monkeypatch.setattr(
        pagelib,
        "st",
        SimpleNamespace(session_state={"env": SimpleNamespace(apps_path=apps_root, agilab_pck=None)}),
    )

    assert pagelib.get_templates() == ["alpha_template", "beta_template"]


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


def test_read_version_from_pyproject_falls_back_to_cwd_and_skips_foreign_project(tmp_path, monkeypatch):
    foreign_root = tmp_path / "foreign"
    foreign_root.mkdir()
    (foreign_root / "pyproject.toml").write_text(
        "[project]\nname='other-project'\nversion='0.1.0'\n",
        encoding="utf-8",
    )
    repo_root = tmp_path / "repo"
    nested = repo_root / "src" / "pkg"
    nested.mkdir(parents=True)
    (repo_root / "pyproject.toml").write_text(
        "[project]\nname='agilab'\nversion='2026.4.11'\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(nested)

    version = pagelib._read_version_from_pyproject(SimpleNamespace(agilab_pck=foreign_root))

    assert version == "2026.4.11"


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


def test_render_logo_warns_when_logo_is_missing(tmp_path, monkeypatch):
    sidebar = SimpleNamespace(
        image=lambda *_args, **_kwargs: None,
        caption=lambda *_args, **_kwargs: None,
        warning=lambda text: setattr(sidebar, "warning_text", text),
    )
    monkeypatch.setattr(
        pagelib,
        "st",
        SimpleNamespace(session_state={"env": SimpleNamespace(st_resources=tmp_path)}, sidebar=sidebar),
    )

    pagelib.render_logo()

    assert sidebar.warning_text == "Logo could not be loaded. Please check the logo path."


def test_subproc_uses_absolute_cwd_and_returns_stdout(monkeypatch, tmp_path):
    calls = {}

    class FakeProcess:
        def __init__(self, stdout_value):
            self.stdout = stdout_value

    def fake_popen(command, shell, cwd, stdout, stderr, text):
        calls["command"] = command
        calls["shell"] = shell
        calls["cwd"] = cwd
        calls["stdout"] = stdout
        calls["stderr"] = stderr
        calls["text"] = text
        return FakeProcess("stream-output")

    monkeypatch.setattr(pagelib.subprocess, "Popen", fake_popen)

    stdout_value = pagelib.subproc("echo hello", tmp_path / ".." / tmp_path.name)

    assert stdout_value == "stream-output"
    assert calls["command"] == "echo hello"
    assert calls["shell"] is True
    assert calls["cwd"] == os.path.abspath(tmp_path / ".." / tmp_path.name)
    assert calls["stdout"] == subprocess.PIPE
    assert calls["stderr"] == subprocess.STDOUT
    assert calls["text"] is True


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


def test_ast_helpers_extract_top_level_and_class_symbols(tmp_path):
    source_path = tmp_path / "symbols.py"
    source_path.write_text(
        "TOP_A = 1\n"
        "TOP_B, TOP_C = 2, 3\n"
        "annot: int = 4\n"
        "\n"
        "def outer():\n"
        "    hidden = 1\n"
        "    def nested():\n"
        "        return hidden\n"
        "    return nested()\n"
        "\n"
        "class Demo(object):\n"
        "    CLASS_ATTR = 1\n"
        "    x, y = 2, 3\n"
        "    ann: int = 4\n"
        "    def __init__(self):\n"
        "        self.runtime = 5\n"
        "    def first(self):\n"
        "        return 1\n"
        "    def second(self):\n"
        "        return 2\n",
        encoding="utf-8",
    )

    top_level = pagelib.get_fcts_and_attrs_name(source_path)
    class_level = pagelib.get_fcts_and_attrs_name(source_path, class_name="Demo")

    assert top_level == {
        "functions": ["outer"],
        "attributes": ["TOP_A", "TOP_B", "TOP_C", "annot"],
    }
    assert class_level == {
        "functions": ["__init__", "first", "second"],
        "attributes": ["CLASS_ATTR", "x", "y", "ann"],
    }
    assert pagelib.get_classes_name(source_path) == ["Demo"]
    assert pagelib.get_class_methods(source_path, "Demo") == ["__init__", "first", "second"]


def test_ast_helpers_raise_for_missing_invalid_or_unreadable_sources(tmp_path):
    missing = tmp_path / "missing.py"
    broken = tmp_path / "broken.py"
    broken.write_text("def nope(:\n", encoding="utf-8")
    source_path = tmp_path / "symbols.py"
    source_path.write_text("class Demo:\n    def run(self):\n        return 1\n", encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        pagelib.get_fcts_and_attrs_name(missing)
    with pytest.raises(SyntaxError):
        pagelib.get_fcts_and_attrs_name(broken)
    with pytest.raises(ValueError, match="Class 'Missing' not found"):
        pagelib.get_fcts_and_attrs_name(source_path, class_name="Missing")
    with pytest.raises(ValueError, match="Class 'Missing' not found"):
        pagelib.get_class_methods(source_path, "Missing")


def test_initialize_csv_files_and_update_datadir_manage_dataset_state(tmp_path, monkeypatch):
    class FakeSessionState(dict):
        def __getattr__(self, name):
            try:
                return self[name]
            except KeyError as exc:
                raise AttributeError(name) from exc

        def __setattr__(self, name, value):
            self[name] = value

    datadir = tmp_path / "datasets"
    datadir.mkdir()
    next_datadir = datadir / "next"
    next_datadir.mkdir()
    first = datadir / "first.csv"
    second = datadir / "second.csv"
    next_first = next_datadir / "next_first.csv"
    next_second = next_datadir / "next_second.csv"
    first.write_text("a\n1\n", encoding="utf-8")
    second.write_text("a\n2\n", encoding="utf-8")
    next_first.write_text("a\n3\n", encoding="utf-8")
    next_second.write_text("a\n4\n", encoding="utf-8")

    state = FakeSessionState(
        {
            "datadir": datadir,
            "input_datadir": str(next_datadir),
            "dataset_files": ["stale-entry"],
        }
    )
    fake_st = SimpleNamespace(session_state=state)
    calls: list[Path] = []

    monkeypatch.setattr(pagelib, "st", fake_st)
    monkeypatch.setattr(
        pagelib,
        "find_files",
        lambda directory, ext=".csv", recursive=True: calls.append(Path(directory)) or (
            [first, second] if Path(directory) == datadir else [next_first, next_second]
        ),
    )

    pagelib.initialize_csv_files()

    assert state["csv_files"] == [first, second]
    assert state["dataset_files"] == ["stale-entry"]
    assert state["df_file"] == "first.csv"
    assert calls == [datadir]

    state["df_file"] = "first.csv"
    state["csv_files"] = [first, second]
    state["dataset_files"] = [first, second]

    pagelib.update_datadir("datadir", "input_datadir")

    assert state["datadir"] == str(next_datadir)
    assert state["df_file"] == "next_first.csv"
    assert state["csv_files"] == [next_first, next_second]
    assert state["dataset_files"] == [next_first, next_second]
    assert calls == [datadir, next_datadir]


def test_select_project_filters_shortlists_and_handles_empty_results(monkeypatch):
    class FakeSidebar:
        def __init__(self, search_term: str, selection: str | None = None):
            self.search_term = search_term
            self.selection = selection
            self.infos: list[str] = []
            self.captions: list[str] = []
            self.select_calls: list[dict[str, object]] = []

        def text_input(self, *_args, **_kwargs):
            return self.search_term

        def info(self, message):
            self.infos.append(str(message))

        def caption(self, message):
            self.captions.append(str(message))

        def selectbox(self, label, options, index=0, key=None):
            self.select_calls.append(
                {"label": label, "options": list(options), "index": index, "key": key}
            )
            return self.selection if self.selection is not None else options[index]

    projects = [f"demo_{idx:03d}_project" for idx in range(60)]
    current = projects[-1]
    changed: list[str] = []
    sidebar = FakeSidebar("demo_", selection=projects[1])
    env = SimpleNamespace(
        apps_path=Path("/tmp/apps"),
        builtin_apps_path=Path("/tmp/apps/builtin"),
        projects=[],
        get_projects=lambda _apps, _builtin: projects,
    )
    monkeypatch.setattr(
        pagelib,
        "st",
        SimpleNamespace(session_state={"env": env}, sidebar=sidebar),
    )
    monkeypatch.setattr(pagelib, "on_project_change", lambda selection: changed.append(selection))

    pagelib.select_project(["ignored"], current)

    assert env.projects == projects
    assert sidebar.captions == ["Showing first 51 of 60 matches"]
    assert sidebar.select_calls[0]["index"] == 0
    shortlist = sidebar.select_calls[0]["options"]
    assert shortlist[0] == current
    assert len(shortlist) == 51
    assert changed == [projects[1]]

    empty_sidebar = FakeSidebar("zzz")
    monkeypatch.setattr(
        pagelib,
        "st",
        SimpleNamespace(session_state={}, sidebar=empty_sidebar),
    )

    pagelib.select_project(projects[:3], current_project="")

    assert empty_sidebar.infos == ["No projects match that filter."]
    assert empty_sidebar.select_calls == []


def test_sidebar_views_and_on_df_change_manage_selection_state(monkeypatch, tmp_path):
    class FakeSessionState(dict):
        def __getattr__(self, name):
            try:
                return self[name]
            except KeyError as exc:
                raise AttributeError(name) from exc

        def __setattr__(self, name, value):
            self[name] = value

    class FakeSidebar:
        def __init__(self, session_state):
            self.session_state = session_state

        def selectbox(self, label, options, index=0, key=None, on_change=None):
            choice = options[index]
            if key is not None:
                self.session_state[key] = choice
            return choice

    export_root = tmp_path / "export"
    lab_dir = export_root / "lab_a"
    lab_dir.mkdir(parents=True)
    default_df = lab_dir / "default_df"
    other_df = lab_dir / "other.csv"
    default_df.write_text("a\n1\n", encoding="utf-8")
    other_df.write_text("a\n2\n", encoding="utf-8")

    env = SimpleNamespace(AGILAB_EXPORT_ABS=export_root, target="lab_a")
    session_state = FakeSessionState({"env": env})
    fake_st = SimpleNamespace(session_state=session_state, sidebar=FakeSidebar(session_state))
    monkeypatch.setattr(pagelib, "st", fake_st)
    monkeypatch.setattr(pagelib, "scan_dir", lambda path: ["lab_a"])
    monkeypatch.setattr(pagelib, "find_files", lambda path: [other_df, default_df])
    monkeypatch.setattr(pagelib, "on_lab_change", lambda *_args, **_kwargs: None, raising=False)

    pagelib.sidebar_views()

    assert session_state["lab_dir"] == "lab_a"
    assert session_state["lab_dir_selectbox"] == "lab_a"
    assert session_state["module_path"] == Path("lab_a")
    assert session_state["df_file"] == export_root / Path("lab_a/default_df")
    assert session_state["index_page"] == Path("lab_a/default_df")

    steps_file = tmp_path / "steps" / "last.toml"
    loaded: list[tuple[Path, Path, str]] = []
    monkeypatch.setattr(
        pagelib,
        "load_last_step",
        lambda module_dir, steps_path, page_key: loaded.append((module_dir, steps_path, page_key)),
        raising=False,
    )
    session_state["legacydf"] = "lab_a/other.csv"
    session_state["legacy"] = "cached"

    pagelib.on_df_change(Path("lab_a"), Path("ignored.csv"), "legacy", steps_file)

    assert session_state["legacydf_file"] == export_root / "lab_a/other.csv"
    assert session_state["df_file"] == export_root / "lab_a/other.csv"
    assert "legacy" not in session_state
    assert session_state["page_broken"] is True
    assert loaded == [(Path("lab_a"), steps_file, "legacy")]
    assert steps_file.parent.is_dir()


def test_sidebar_views_handles_empty_dataframe_list(monkeypatch, tmp_path):
    class FakeSessionState(dict):
        def __getattr__(self, name):
            try:
                return self[name]
            except KeyError as exc:
                raise AttributeError(name) from exc

        def __setattr__(self, name, value):
            self[name] = value

    class FakeSidebar:
        def __init__(self, session_state):
            self.session_state = session_state

        def selectbox(self, label, options, index=0, key=None, on_change=None):
            choice = options[index] if options else None
            if key is not None:
                self.session_state[key] = choice
            return choice

    export_root = tmp_path / "export"
    (export_root / "lab_a").mkdir(parents=True)
    env = SimpleNamespace(AGILAB_EXPORT_ABS=export_root, target="lab_a")
    session_state = FakeSessionState({"env": env})
    fake_st = SimpleNamespace(session_state=session_state, sidebar=FakeSidebar(session_state))
    monkeypatch.setattr(pagelib, "st", fake_st)
    monkeypatch.setattr(pagelib, "scan_dir", lambda path: ["lab_a"])
    monkeypatch.setattr(pagelib, "find_files", lambda path: [])
    monkeypatch.setattr(pagelib, "on_lab_change", lambda *_args, **_kwargs: None, raising=False)

    pagelib.sidebar_views()

    assert session_state["lab_dir"] == "lab_a"
    assert session_state["lab_dir_selectbox"] == "lab_a"
    assert session_state["df_files"] == []
    assert session_state["index_page"] == "lab_a"
    assert session_state["lab_adf"] is None
    assert session_state["df_file"] is None


def test_on_df_change_uses_explicit_df_file_when_no_selection(monkeypatch, tmp_path):
    class FakeSessionState(dict):
        def __getattr__(self, name):
            try:
                return self[name]
            except KeyError as exc:
                raise AttributeError(name) from exc

        def __setattr__(self, name, value):
            self[name] = value

    export_root = tmp_path / "export"
    export_root.mkdir()
    explicit_df = tmp_path / "absolute.csv"
    explicit_df.write_text("a\n1\n", encoding="utf-8")
    session_state = FakeSessionState(
        {
            "env": SimpleNamespace(AGILAB_EXPORT_ABS=export_root),
            "legacy": "cached",
            "page_broken": False,
        }
    )
    monkeypatch.setattr(pagelib, "st", SimpleNamespace(session_state=session_state))

    pagelib.on_df_change(Path("lab_a"), "legacy", df_file=explicit_df, steps_file=None)

    assert session_state["legacydf_file"] == explicit_df
    assert session_state["df_file"] == explicit_df
    assert "legacy" not in session_state
    assert session_state["page_broken"] is True


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
