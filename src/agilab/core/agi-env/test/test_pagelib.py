from __future__ import annotations

import ast
import importlib
import importlib.util
import io
import os
import sqlite3
import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

from agi_env import pagelib, ui_support


def _patch_mlflow_cli(monkeypatch):
    monkeypatch.setattr(
        pagelib.mlflow_store,
        "mlflow_cli_argv",
        lambda args, **_kwargs: ["mlflow", *args],
    )


def test_mlflow_cli_argv_prefers_installed_executable() -> None:
    argv = pagelib.mlflow_store.mlflow_cli_argv(
        ["server"],
        which_fn=lambda name: "/tmp/bin/mlflow" if name == "mlflow" else None,
        find_spec_fn=lambda _name: None,
    )

    assert argv == ["/tmp/bin/mlflow", "server"]


def test_mlflow_cli_argv_falls_back_to_cli_entry_module() -> None:
    argv = pagelib.mlflow_store.mlflow_cli_argv(
        ["db", "upgrade", "sqlite:///tmp/mlflow.db"],
        sys_executable="/tmp/python",
        which_fn=lambda _name: None,
        find_spec_fn=lambda name: object() if name == "mlflow.cli" else None,
    )

    assert argv[:3] == ["/tmp/python", "-c", pagelib.mlflow_store._MLFLOW_CLI_BOOTSTRAP]
    assert argv[3:] == ["db", "upgrade", "sqlite:///tmp/mlflow.db"]
    assert "-m" not in argv


def test_mlflow_cli_argv_reports_missing_mlflow_cli() -> None:
    with pytest.raises(RuntimeError, match=r"agilab\[mlflow\]"):
        pagelib.mlflow_store.mlflow_cli_argv(
            ["server"],
            which_fn=lambda _name: None,
            find_spec_fn=lambda _name: None,
        )


def test_mlflow_cli_argv_reports_broken_mlflow_cli_import() -> None:
    def _broken_find_spec(_name: str):
        raise TypeError("Descriptors cannot be created directly.")

    with pytest.raises(RuntimeError, match=r"agilab\[mlflow\]"):
        pagelib.mlflow_store.mlflow_cli_argv(
            ["server"],
            which_fn=lambda _name: None,
            find_spec_fn=_broken_find_spec,
        )


def _load_pagelib_with_missing(module_name: str, *missing_modules: str):
    module_path = Path("src/agilab/core/agi-env/src/agi_env/pagelib.py")
    importlib.invalidate_caches()
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    original_import = __import__

    def _patched_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in missing_modules:
            raise ModuleNotFoundError(name)
        return original_import(name, globals, locals, fromlist, level)

    with patch("builtins.__import__", _patched_import):
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    return module


def _load_ui_support_with_missing(module_name: str, *missing_modules: str):
    module_path = Path("src/agilab/core/agi-env/src/agi_env/ui_support.py")
    importlib.invalidate_caches()
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    original_import = __import__

    def _patched_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in missing_modules:
            raise ModuleNotFoundError(name)
        return original_import(name, globals, locals, fromlist, level)

    with patch("builtins.__import__", _patched_import):
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    return module


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


def test_background_services_enabled_respects_mlflow_autostart_disabled(monkeypatch):
    monkeypatch.delenv("AGILAB_DISABLE_BACKGROUND_SERVICES", raising=False)
    monkeypatch.setattr(pagelib, "st", SimpleNamespace(session_state={"mlflow_autostart_disabled": True}))

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


def test_get_mlflow_module_reraises_non_import_errors(monkeypatch):
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "mlflow":
            raise RuntimeError("boom")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    with pytest.raises(RuntimeError, match="boom"):
        pagelib._get_mlflow_module()


def test_resolve_mlflow_backend_and_artifact_paths(tmp_path):
    tracking_dir = tmp_path / "mlflow"

    backend = pagelib._resolve_mlflow_backend_db(tracking_dir)
    artifact_dir = pagelib._resolve_mlflow_artifact_dir(tracking_dir)

    assert backend == tracking_dir / pagelib.DEFAULT_MLFLOW_DB_NAME
    assert artifact_dir == (tracking_dir / pagelib.DEFAULT_MLFLOW_ARTIFACT_DIR).resolve()
    assert artifact_dir.is_dir()


def test_dump_toml_payload_supports_tomlkit_fallback_and_runtime_error():
    fallback = _load_ui_support_with_missing("agi_env.ui_support_tomlkit_fallback", "tomli_w")
    sink = io.BytesIO()
    fallback._dump_toml_payload({"last_active_app": "/tmp/demo"}, sink)
    assert b"last_active_app" in sink.getvalue()

    broken = _load_ui_support_with_missing("agi_env.ui_support_no_toml_writer", "tomli_w", "tomlkit")
    with pytest.raises(RuntimeError, match="Writing settings requires"):
        broken._dump_toml_payload({"demo": "value"}, io.BytesIO())


def test_legacy_mlflow_filestore_present_detects_legacy_layouts(tmp_path):
    tracking_dir = tmp_path / "mlflow"
    tracking_dir.mkdir()
    (tracking_dir / pagelib.DEFAULT_MLFLOW_DB_NAME).write_text("", encoding="utf-8")
    (tracking_dir / pagelib.DEFAULT_MLFLOW_ARTIFACT_DIR).mkdir()
    assert pagelib._legacy_mlflow_filestore_present(tracking_dir) is False

    (tracking_dir / ".trash").mkdir()
    assert pagelib._legacy_mlflow_filestore_present(tracking_dir) is True


def test_legacy_mlflow_filestore_present_handles_missing_dir_and_numeric_runs(tmp_path):
    missing_dir = tmp_path / "missing"
    assert pagelib._legacy_mlflow_filestore_present(missing_dir) is False

    tracking_dir = tmp_path / "mlflow"
    tracking_dir.mkdir()
    (tracking_dir / "12").mkdir()
    assert pagelib._legacy_mlflow_filestore_present(tracking_dir) is True


def test_sqlite_identifier_escapes_quotes():
    assert pagelib._sqlite_identifier('a"b') == '"a""b"'


def test_sqlite_uri_for_path_covers_posix_and_windows_formats(monkeypatch, tmp_path):
    db_path = tmp_path / "mlflow.db"
    resolved_db_path = db_path.resolve().as_posix()

    monkeypatch.setattr(pagelib.os, "name", "posix", raising=False)
    assert pagelib._sqlite_uri_for_path(db_path) == f"sqlite:////{resolved_db_path.lstrip('/')}"

    class _FakeWindowsPath:
        def __init__(self, _value):
            self._value = resolved_db_path

        def expanduser(self):
            return self

        def resolve(self):
            return self

        def as_posix(self):
            return self._value

    monkeypatch.setattr(pagelib.os, "name", "nt", raising=False)
    monkeypatch.setattr(pagelib, "Path", _FakeWindowsPath)
    assert pagelib._sqlite_uri_for_path(db_path) == f"sqlite:///{resolved_db_path}"


def test_load_last_active_app_prefers_global_state_file(tmp_path, monkeypatch):
    state_file = tmp_path / "app_state.toml"
    legacy_file = tmp_path / ".last-active-app"
    app_dir = tmp_path / "demo_app"
    app_dir.mkdir()
    state_file.write_text(f'last_active_app = "{app_dir}"\n', encoding="utf-8")

    monkeypatch.setattr(ui_support, "_GLOBAL_STATE_FILE", state_file)
    monkeypatch.setattr(ui_support, "_LEGACY_LAST_APP_FILE", legacy_file)

    assert ui_support.load_last_active_app() == app_dir


def test_load_global_state_falls_back_to_legacy_plaintext(tmp_path, monkeypatch):
    state_file = tmp_path / "app_state.toml"
    legacy_file = tmp_path / ".last-active-app"
    legacy_file.write_text("/tmp/legacy-app\n", encoding="utf-8")

    monkeypatch.setattr(ui_support, "_GLOBAL_STATE_FILE", state_file)
    monkeypatch.setattr(ui_support, "_LEGACY_LAST_APP_FILE", legacy_file)

    assert ui_support.load_global_state() == {"last_active_app": "/tmp/legacy-app"}


def test_load_global_state_returns_empty_dict_for_invalid_toml_without_legacy(tmp_path, monkeypatch):
    state_file = tmp_path / "app_state.toml"
    state_file.write_text("not = [valid\n", encoding="utf-8")

    monkeypatch.setattr(ui_support, "_GLOBAL_STATE_FILE", state_file)
    monkeypatch.setattr(ui_support, "_LEGACY_LAST_APP_FILE", tmp_path / ".last-active-app")

    assert ui_support.load_global_state() == {}


def test_store_last_active_app_persists_state(tmp_path, monkeypatch):
    state_file = tmp_path / "app_state.toml"
    legacy_file = tmp_path / ".last-active-app"
    app_dir = tmp_path / "stored_app"
    app_dir.mkdir()

    monkeypatch.setattr(ui_support, "_GLOBAL_STATE_FILE", state_file)
    monkeypatch.setattr(ui_support, "_LEGACY_LAST_APP_FILE", legacy_file)

    ui_support.store_last_active_app(app_dir)

    stored = tomllib.loads(state_file.read_text(encoding="utf-8"))
    assert stored["last_active_app"] == str(app_dir)


def test_store_last_active_app_skips_persist_when_unchanged(monkeypatch, tmp_path):
    app_dir = tmp_path / "stored_app"
    app_dir.mkdir()
    monkeypatch.setattr(ui_support, "load_global_state", lambda: {"last_active_app": str(app_dir)})
    called: list[dict[str, str]] = []
    monkeypatch.setattr(ui_support, "persist_global_state", lambda data: called.append(data))

    ui_support.store_last_active_app(app_dir)

    assert called == []


def test_persist_global_state_writes_toml(tmp_path, monkeypatch):
    state_file = tmp_path / "app_state.toml"

    monkeypatch.setattr(ui_support, "_GLOBAL_STATE_FILE", state_file)

    ui_support.persist_global_state({"last_active_app": "/tmp/demo"})

    stored = tomllib.loads(state_file.read_text(encoding="utf-8"))
    assert stored == {"last_active_app": "/tmp/demo"}


def test_persist_global_state_swallows_dump_errors(tmp_path, monkeypatch):
    state_file = tmp_path / "app_state.toml"
    monkeypatch.setattr(ui_support, "_GLOBAL_STATE_FILE", state_file)
    monkeypatch.setattr(
        ui_support,
        "_dump_toml_payload",
        lambda _data, _handle: (_ for _ in ()).throw(OSError("disk full")),
    )

    ui_support.persist_global_state({"last_active_app": "/tmp/demo"})

    assert state_file.exists()


def test_load_last_active_app_returns_none_when_target_is_missing(tmp_path, monkeypatch):
    state_file = tmp_path / "app_state.toml"
    state_file.write_text('last_active_app = "/tmp/missing-app"\n', encoding="utf-8")

    monkeypatch.setattr(ui_support, "_GLOBAL_STATE_FILE", state_file)
    monkeypatch.setattr(ui_support, "_LEGACY_LAST_APP_FILE", tmp_path / ".last-active-app")

    assert ui_support.load_last_active_app() is None


def test_load_last_active_app_returns_none_for_unparseable_path(monkeypatch):
    monkeypatch.setattr(ui_support, "load_global_state", lambda: {"last_active_app": object()})

    assert ui_support.load_last_active_app() is None


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
    assert ui_support.with_anchor("http://example", "section") == "http://example#section"
    assert ui_support.with_anchor("http://example", "#section") == "http://example#section"
    assert ui_support.with_anchor("http://example", "") == "http://example"


def test_is_valid_ip_accepts_ipv4_and_rejects_out_of_range():
    assert pagelib.is_valid_ip("192.168.20.130") is True
    assert pagelib.is_valid_ip("300.168.20.130") is False


def test_is_valid_ip_rejects_non_ipv4_strings():
    assert pagelib.is_valid_ip("not-an-ip") is False


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


def test_resolve_docs_path_falls_back_to_recursive_search(tmp_path):
    pkg_root = tmp_path / "pkg"
    nested = pkg_root.parent / "docs" / "nested"
    nested.mkdir(parents=True)
    target = nested / "guide.html"
    target.write_text("guide", encoding="utf-8")
    env = SimpleNamespace(agilab_pck=pkg_root)

    resolved = ui_support.resolve_docs_path(env, "guide.html")

    assert resolved == target


def test_open_docs_falls_back_to_online(monkeypatch):
    captured = {}

    def fake_open(url):
        captured["url"] = url

    monkeypatch.setattr(ui_support, "open_docs_url", fake_open)
    env = SimpleNamespace(agilab_pck=Path("/does/not/exist"))

    ui_support.open_docs(env, html_file="missing.html", anchor="anchor")

    assert captured["url"] == "https://thalesgroup.github.io/agilab/index.html#anchor"


def test_open_docs_prefers_local_file_when_available(tmp_path, monkeypatch):
    pkg_root = tmp_path / "pkg"
    docs_html = pkg_root / "docs" / "html"
    docs_html.mkdir(parents=True)
    html_path = docs_html / "guide.html"
    html_path.write_text("guide", encoding="utf-8")
    env = SimpleNamespace(agilab_pck=pkg_root)

    opened = {}
    monkeypatch.setattr(ui_support, "open_docs_url", lambda url: opened.setdefault("url", url))

    ui_support.open_docs(env, html_file="guide.html", anchor="section")

    assert opened["url"] == f"{html_path.as_uri()}#section"


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
    monkeypatch.setattr(
        pagelib,
        "st",
        SimpleNamespace(markdown=lambda text, unsafe_allow_html=False: markdown_calls.append((text, unsafe_allow_html))),
    )

    inject_theme = getattr(pagelib.inject_theme, "__wrapped__", pagelib.inject_theme)
    inject_theme(base_path=tmp_path)

    assert markdown_calls == [("<style>body { color: red; }\n</style>", True)]


def test_inject_theme_rereads_theme_stylesheet(tmp_path, monkeypatch):
    theme_path = tmp_path / "theme.css"
    theme_path.write_text("body { color: red; }\n", encoding="utf-8")
    markdown_calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        pagelib,
        "st",
        SimpleNamespace(markdown=lambda text, unsafe_allow_html=False: markdown_calls.append((text, unsafe_allow_html))),
    )

    pagelib.inject_theme(base_path=tmp_path)
    theme_path.write_text("body { color: blue; }\n", encoding="utf-8")
    pagelib.inject_theme(base_path=tmp_path)

    assert markdown_calls == [
        ("<style>body { color: red; }\n</style>", True),
        ("<style>body { color: blue; }\n</style>", True),
    ]


def test_inject_theme_falls_back_to_binary_decode_when_text_read_fails(tmp_path, monkeypatch):
    theme_path = tmp_path / "theme.css"
    theme_path.write_bytes(b"\xffbody { color: blue; }\n")
    markdown_calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        pagelib,
        "st",
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

    ui_support._DOCS_ALREADY_OPENED = True
    ui_support._LAST_DOCS_URL = "http://example/docs"
    monkeypatch.setattr(ui_support, "focus_existing_docs_tab", lambda _: False)
    monkeypatch.setattr(ui_support.webbrowser, "open_new_tab", lambda url: opened.append(url))

    ui_support.open_docs_url("http://example/docs")

    assert opened == ["http://example/docs"]
    assert ui_support._DOCS_ALREADY_OPENED is True
    assert ui_support._LAST_DOCS_URL == "http://example/docs"


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


def test_repair_mlflow_default_experiment_db_returns_false_for_missing_layouts(tmp_path):
    missing_db = tmp_path / "missing.db"
    assert pagelib._repair_mlflow_default_experiment_db(missing_db) is False

    bad_cols_db = tmp_path / "bad-cols.db"
    with sqlite3.connect(bad_cols_db) as conn:
        conn.execute("CREATE TABLE experiments (experiment_id INTEGER PRIMARY KEY)")
        conn.commit()
    assert pagelib._repair_mlflow_default_experiment_db(bad_cols_db) is False

    missing_default_db = tmp_path / "missing-default.db"
    with sqlite3.connect(missing_default_db) as conn:
        conn.execute(
            "CREATE TABLE experiments (experiment_id INTEGER PRIMARY KEY, name TEXT, workspace TEXT, artifact_location TEXT)"
        )
        conn.execute(
            "INSERT INTO experiments (experiment_id, name, workspace, artifact_location) VALUES (1, 'Other', 'default', 'file:///old')"
        )
        conn.commit()
    assert pagelib._repair_mlflow_default_experiment_db(missing_default_db) is False


def test_repair_mlflow_default_experiment_db_rewrites_nonzero_default_and_artifact(tmp_path):
    db_path = tmp_path / "mlflow.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE experiments (experiment_id INTEGER PRIMARY KEY, name TEXT, workspace TEXT, artifact_location TEXT)"
        )
        conn.execute("CREATE TABLE runs (run_uuid TEXT, experiment_id INTEGER)")
        conn.execute(
            "INSERT INTO experiments (experiment_id, name, workspace, artifact_location) VALUES (7, ?, ?, ?)",
            (pagelib.DEFAULT_MLFLOW_EXPERIMENT_NAME, "default", "file:///old"),
        )
        conn.execute("INSERT INTO runs (run_uuid, experiment_id) VALUES ('r1', 7)")
        conn.commit()

    assert pagelib._repair_mlflow_default_experiment_db(db_path, artifact_uri="file:///new-artifacts") is True

    with sqlite3.connect(db_path) as conn:
        experiment = conn.execute(
            "SELECT experiment_id, artifact_location FROM experiments WHERE name = ?",
            (pagelib.DEFAULT_MLFLOW_EXPERIMENT_NAME,),
        ).fetchone()
        run_row = conn.execute("SELECT experiment_id FROM runs WHERE run_uuid = 'r1'").fetchone()

    assert experiment == (0, "file:///new-artifacts")
    assert run_row == (0,)


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
    _patch_mlflow_cli(monkeypatch)
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
    envs = []
    _patch_mlflow_cli(monkeypatch)

    def fake_run(cmd, check, capture_output, text, env=None):
        calls.append(cmd)
        envs.append(env)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(pagelib.subprocess, "run", fake_run)
    monkeypatch.setattr(pagelib, "_MLFLOW_SQLITE_UPGRADE_CHECKED", set())

    first_uri = pagelib._ensure_mlflow_backend_ready(tracking_dir)
    second_uri = pagelib._ensure_mlflow_backend_ready(tracking_dir)

    assert first_uri == pagelib._sqlite_uri_for_path(db_path)
    assert second_uri == first_uri
    assert calls == [["mlflow", "db", "upgrade", pagelib._sqlite_uri_for_path(db_path)]]
    assert envs[0]["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] == "python"


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


def test_get_projects_zip_templates_and_about_content(tmp_path, monkeypatch):
    export_apps = tmp_path / "exports"
    export_apps.mkdir()
    (export_apps / "alpha.zip").write_text("x", encoding="utf-8")
    (export_apps / "beta.zip").write_text("x", encoding="utf-8")
    apps_root = tmp_path / "apps"
    (apps_root / "templates" / "demo").mkdir(parents=True)
    agilab_pkg = tmp_path / "pkg"
    (agilab_pkg / "agilab" / "templates" / "builtin").mkdir(parents=True)

    class _ExportApps:
        def glob(self, pattern):
            assert pattern == "*.zip"
            return [export_apps / "beta.zip", export_apps / "alpha.zip"]

    monkeypatch.setattr(
        pagelib,
        "st",
        SimpleNamespace(
            session_state={
                "env": SimpleNamespace(
                    export_apps=_ExportApps(),
                    apps_path=apps_root,
                    agilab_pck=agilab_pkg,
                )
            }
        ),
    )

    about_text = pagelib.get_about_content()["About"]

    assert pagelib.get_projects_zip() == ["alpha.zip", "beta.zip"]
    assert pagelib.get_templates() == ["builtin", "demo"]
    assert "AGILAB" in about_text
    assert "Reproducible AI engineering, from project to proof." in about_text
    assert "Data Science in Engineering" not in about_text


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

    monkeypatch.setattr(ui_support.subprocess, "run", fake_run)

    version = ui_support.detect_agilab_version(SimpleNamespace(is_source_env=True, agilab_pck=tmp_path))

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

    version = ui_support.read_version_from_pyproject(SimpleNamespace(agilab_pck=foreign_root))

    assert version == "2026.4.11"


def test_detect_agilab_version_falls_back_to_installed_metadata(monkeypatch):
    monkeypatch.setattr(ui_support, "_importlib_metadata", SimpleNamespace(version=lambda _name: "9.9.9"))

    version = ui_support.detect_agilab_version(SimpleNamespace(is_source_env=False, agilab_pck=None))

    assert version == "9.9.9"


def test_sidebar_version_label_normalizes_prefix():
    assert pagelib._sidebar_version_label("2026.4.2") == "AGILAB v2026.4.2"
    assert pagelib._sidebar_version_label("v2026.4.2") == "AGILAB v2026.4.2"
    assert pagelib._sidebar_version_label(" V2026.4.2 ") == "AGILAB v2026.4.2"
    assert pagelib._sidebar_version_label("") == ""


def test_sidebar_version_style_uses_css_content_without_sidebar_block():
    style = pagelib._sidebar_version_style("AGILAB v2026.4.2")
    assert "content: \"AGILAB v2026.4.2\";" in style
    assert "::after" in style
    assert "agilab-sidebar-version" not in style


def test_render_logo_prefers_streamlit_logo_when_available(tmp_path, monkeypatch):
    logo_path = tmp_path / "agilab_logo.png"
    logo_path.write_text("png", encoding="utf-8")
    logo_calls = []
    sidebar = SimpleNamespace(
        image=lambda *_args, **_kwargs: setattr(sidebar, "image_called", True),
        caption=lambda text: setattr(sidebar, "caption_text", text),
        warning=lambda text: setattr(sidebar, "warning_text", text),
    )
    fake_st = SimpleNamespace(
        session_state={"env": SimpleNamespace(st_resources=tmp_path)},
        sidebar=sidebar,
        logo=lambda path, size="medium", **_kwargs: logo_calls.append((path, size)),
        html=lambda text: setattr(fake_st, "html_call", text),
        markdown=lambda text, unsafe_allow_html=False: setattr(fake_st, "markdown_call", (text, unsafe_allow_html)),
    )
    monkeypatch.setattr(pagelib, "st", fake_st)
    monkeypatch.setattr(pagelib, "_detect_agilab_version", lambda env: "2026.4.2")

    pagelib.render_logo()

    assert logo_calls == [(str(logo_path), "large")]
    assert not hasattr(sidebar, "image_called")
    assert "::after" in fake_st.html_call
    assert "content: \"AGILAB v2026.4.2\";" in fake_st.html_call
    assert "AGILAB v2026.4.2" in fake_st.html_call
    assert not hasattr(fake_st, "markdown_call")
    assert not hasattr(sidebar, "caption_text")


def test_render_logo_uses_root_html_footer_when_available(tmp_path, monkeypatch):
    logo_path = tmp_path / "agilab_logo.png"
    logo_path.write_text("png", encoding="utf-8")
    sidebar = SimpleNamespace(
        image=lambda path, width: setattr(sidebar, "image_call", (path, width)),
        caption=lambda text: setattr(sidebar, "caption_text", text),
        warning=lambda text: setattr(sidebar, "warning_text", text),
    )
    fake_st = SimpleNamespace(
        session_state={"env": SimpleNamespace(st_resources=tmp_path)},
        sidebar=sidebar,
        html=lambda text: setattr(fake_st, "html_call", text),
    )
    monkeypatch.setattr(pagelib, "st", fake_st)
    monkeypatch.setattr(pagelib, "_detect_agilab_version", lambda env: "2026.4.2")

    pagelib.render_logo()

    assert sidebar.image_call == (str(logo_path), 170)
    assert "AGILAB v2026.4.2" in fake_st.html_call
    assert not hasattr(sidebar, "caption_text")


def test_render_logo_falls_back_to_root_markdown_when_html_is_missing(tmp_path, monkeypatch):
    logo_path = tmp_path / "agilab_logo.png"
    logo_path.write_text("png", encoding="utf-8")
    sidebar = SimpleNamespace(
        image=lambda path, width: setattr(sidebar, "image_call", (path, width)),
        caption=lambda text: setattr(sidebar, "caption_text", text),
        warning=lambda text: setattr(sidebar, "warning_text", text),
    )
    fake_st = SimpleNamespace(
        session_state={"env": SimpleNamespace(st_resources=tmp_path)},
        sidebar=sidebar,
        markdown=lambda text, unsafe_allow_html=False: setattr(fake_st, "markdown_call", (text, unsafe_allow_html)),
    )
    monkeypatch.setattr(pagelib, "st", fake_st)
    monkeypatch.setattr(pagelib, "_detect_agilab_version", lambda env: "2026.4.2")

    pagelib.render_logo()

    assert sidebar.image_call == (str(logo_path), 170)
    assert "AGILAB v2026.4.2" in fake_st.markdown_call[0]
    assert fake_st.markdown_call[1] is True
    assert not hasattr(sidebar, "caption_text")


def test_render_logo_falls_back_to_caption_when_root_html_and_markdown_are_missing(tmp_path, monkeypatch):
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
    assert sidebar.caption_text == "AGILAB v2026.4.2"


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


def test_render_logo_returns_when_env_is_missing(monkeypatch):
    sidebar = SimpleNamespace(
        image=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("image should not be called")),
        caption=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("caption should not be called")),
        warning=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("warning should not be called")),
    )
    monkeypatch.setattr(pagelib, "st", SimpleNamespace(session_state={}, sidebar=sidebar))

    assert pagelib.render_logo() is None


def test_subproc_uses_absolute_cwd_and_returns_stdout(monkeypatch, tmp_path):
    calls = {}

    class FakeProcess:
        def __init__(self, stdout_value):
            self.stdout = stdout_value

    def fake_popen(command, shell, cwd, stdout, stderr, text, env):
        calls["command"] = command
        calls["shell"] = shell
        calls["cwd"] = cwd
        calls["stdout"] = stdout
        calls["stderr"] = stderr
        calls["text"] = text
        calls["env"] = env
        return FakeProcess("stream-output")

    monkeypatch.setattr(pagelib.subprocess, "Popen", fake_popen)

    stdout_value = pagelib.subproc("echo hello", tmp_path / ".." / tmp_path.name)

    assert stdout_value == "stream-output"
    assert calls["command"] == ["echo", "hello"]
    assert calls["shell"] is False
    assert calls["cwd"] == os.path.abspath(tmp_path / ".." / tmp_path.name)
    assert calls["stdout"] == subprocess.PIPE
    assert calls["stderr"] == subprocess.STDOUT
    assert isinstance(calls["env"], dict)
    assert calls["text"] is True


def test_mount_helpers_cover_proc_fstab_and_shell_fallbacks(monkeypatch):
    real_path = Path

    class FakeTextFile:
        def __init__(self, *, exists=True, text="", exc=None):
            self._exists = exists
            self._text = text
            self._exc = exc

        def exists(self):
            return self._exists

        def read_text(self, *args, **kwargs):
            if self._exc:
                raise self._exc
            return self._text

    proc_mounts = FakeTextFile(
        exists=True,
        text="server:/share /mnt/share nfs rw 0 0\nbad line\n/dev/disk /Volumes/demo apfs rw 0 0\n",
    )
    monkeypatch.setattr(
        pagelib,
        "Path",
        lambda value: proc_mounts if str(value) == "/proc/mounts" else real_path(value),
    )
    mounts = pagelib._current_mount_points()
    assert mounts[real_path("/mnt/share")] == "nfs"
    assert mounts[real_path("/Volumes/demo")] == "apfs"

    fstab = FakeTextFile(
        exists=True,
        text="# comment\nserver:/share /mnt/share nfs defaults 0 0\nUUID=1 /Volumes/demo apfs rw 0 0\n",
    )
    pagelib._fstab_mount_points.cache_clear()
    monkeypatch.setattr(
        pagelib,
        "Path",
        lambda value: fstab if str(value) == "/etc/fstab" else real_path(value),
    )
    assert pagelib._fstab_mount_points() == (real_path("/mnt/share"), real_path("/Volumes/demo"))

    pagelib._fstab_mount_points.cache_clear()
    broken_fstab = FakeTextFile(exists=True, exc=OSError("unreadable"))
    monkeypatch.setattr(
        pagelib,
        "Path",
        lambda value: broken_fstab if str(value) == "/etc/fstab" else real_path(value),
    )
    assert pagelib._fstab_mount_points() == ()

    no_proc = FakeTextFile(exists=False)

    class Result:
        stdout = "disk on /Volumes/data (apfs, local)\ninvalid line\n"

    monkeypatch.setattr(
        pagelib,
        "Path",
        lambda value: no_proc if str(value) == "/proc/mounts" else real_path(value),
    )
    monkeypatch.setattr(pagelib.subprocess, "run", lambda *args, **kwargs: Result())
    mounts = pagelib._current_mount_points()
    assert mounts[real_path("/Volumes/data")] == "apfs"

    monkeypatch.setattr(
        pagelib.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.CalledProcessError(1, "mount")),
    )
    assert pagelib._current_mount_points() == {}


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


def test_pagelib_ast_wrappers_use_source_analysis_support(monkeypatch, tmp_path):
    source_path = tmp_path / "symbols.py"
    source_path.write_text("class Demo:\n    pass\n", encoding="utf-8")
    captured = {}

    def _fake_functions(src_path_arg, class_name=None):
        captured["functions"] = (src_path_arg, class_name)
        return {"functions": ["run"], "attributes": ["demo"]}

    def _fake_classes(src_path_arg):
        captured["classes"] = src_path_arg
        return ["Demo"]

    def _fake_methods(src_path_arg, class_name_arg):
        captured["methods"] = (src_path_arg, class_name_arg)
        return ["run"]

    monkeypatch.setattr(pagelib, "get_functions_and_attributes", _fake_functions)
    monkeypatch.setattr(pagelib, "extract_class_names", _fake_classes)
    monkeypatch.setattr(pagelib, "extract_class_methods", _fake_methods)

    assert pagelib.get_fcts_and_attrs_name(source_path, class_name="Demo") == {
        "functions": ["run"],
        "attributes": ["demo"],
    }
    assert pagelib.get_classes_name(source_path) == ["Demo"]
    assert pagelib.get_class_methods(source_path, "Demo") == ["run"]
    assert captured["functions"] == (source_path, "Demo")
    assert captured["classes"] == source_path
    assert captured["methods"] == (source_path, "Demo")


def test_pagelib_source_analysis_compatibility_wrappers(monkeypatch):
    source = "import demo.base"
    captured = {}

    def _fake_get_import_mapping(source_arg, logger=None):
        captured["import_mapping_input"] = (source_arg, logger)
        return {"demo": "demo.base"}

    def _fake_extract_base_info(base_arg, mapping_arg):
        captured["extract_input"] = (base_arg, mapping_arg)
        return ("DemoWorker", "pkg")

    def _fake_full_name(node_arg):
        captured["full_name_input"] = node_arg
        return "mod.Demo"

    monkeypatch.setattr(pagelib, "_get_import_mapping", _fake_get_import_mapping)
    monkeypatch.setattr(pagelib, "_extract_base_info", _fake_extract_base_info)
    monkeypatch.setattr(pagelib, "_get_full_attribute_name", _fake_full_name)

    assert pagelib.get_import_mapping(source) == {"demo": "demo.base"}
    assert captured["import_mapping_input"] == (source, None)

    base_ast = ast.parse("x = mod.Demo").body[0].value
    assert pagelib.extract_base_info(base_ast, {"mod": "pkg"}) == ("DemoWorker", "pkg")
    assert captured["extract_input"] == (base_ast, {"mod": "pkg"})
    assert pagelib.get_full_attribute_name(base_ast) == "mod.Demo"
    assert captured["full_name_input"] is base_ast


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


def test_on_project_change_resets_state_and_reports_env_errors(monkeypatch, tmp_path):
    class FakeSessionState(dict):
        def __getattr__(self, name):
            try:
                return self[name]
            except KeyError as exc:
                raise AttributeError(name) from exc

        def __setattr__(self, name, value):
            self[name] = value

    changed: list[Path] = []
    stored: list[Path] = []
    errors: list[str] = []
    env = SimpleNamespace(
        apps_path=tmp_path / "apps",
        AGILAB_EXPORT_ABS=tmp_path / "exports",
        active_app=tmp_path / "apps" / "demo_project",
        target="demo_project",
    )

    def _change_app(path):
        changed.append(path)
        env.active_app = path
        env.target = "demo_project"

    env.change_app = _change_app
    session_state = FakeSessionState(
        {
            "env": env,
            "toggle_edit": True,
            "toggle_edit_ui": True,
            "preview_tree": True,
            "arg_name_alpha": "x",
            "view_checkbox_beta": True,
            "sample:app_args_form:field": "stale",
        }
    )
    fake_st = SimpleNamespace(session_state=session_state, error=lambda message: errors.append(str(message)))
    monkeypatch.setattr(pagelib, "st", fake_st)
    monkeypatch.setattr(pagelib, "store_last_active_app", lambda path: stored.append(path))

    pagelib.on_project_change("demo_project", switch_to_select=True)

    assert changed == [env.apps_path / "demo_project"]
    assert stored == [env.active_app]
    assert session_state.module_rel == Path("demo_project")
    assert session_state.datadir == env.AGILAB_EXPORT_ABS / "demo_project"
    assert session_state.datadir_str == str(env.AGILAB_EXPORT_ABS / "demo_project")
    assert session_state.df_export_file == str(env.AGILAB_EXPORT_ABS / "demo_project" / "export.csv")
    assert session_state.switch_to_select is True
    assert session_state.project_changed is True
    assert "toggle_edit" not in session_state
    assert "toggle_edit_ui" not in session_state
    assert "arg_name_alpha" not in session_state
    assert "view_checkbox_beta" not in session_state
    assert "sample:app_args_form:field" not in session_state
    for label in (
        "PYTHON-ENV",
        "PYTHON-ENV-EXTRA",
        "MANAGER",
        "WORKER",
        "EXPORT-APP-FILTER",
        "APP-SETTINGS",
        "ARGS-UI",
        "PRE-PROMPT",
    ):
        assert session_state[label] is False

    errors.clear()
    env.change_app = lambda _path: (_ for _ in ()).throw(RuntimeError("boom"))
    pagelib.on_project_change("broken_project")
    assert any("An error occurred while changing the project: boom" in message for message in errors)


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
    command = launched["call"][0]
    assert "gpt_oss.responses_api.serve" in command
    assert command[command.index("--inference-backend") + 1] == "stub"
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


def test_pagelib_io_helpers_cover_ports_browser_json_and_run_agi(monkeypatch, tmp_path):
    calls: list[tuple[str, bool]] = []
    errors: list[str] = []
    infos: list[str] = []
    warnings: list[str] = []
    st_resources = tmp_path / "resources"
    st_resources.mkdir()
    (st_resources / "custom_buttons.json").write_text('{"buttons": ["run"]}', encoding="utf-8")
    (st_resources / "info_bar.json").write_text('{"title": "AGILab"}', encoding="utf-8")

    def _stop():
        raise RuntimeError("stop")

    env = SimpleNamespace(
        st_resources=st_resources,
        agi_env=tmp_path / ".venv",
        target="demo_project",
        runenv=tmp_path / "runenv",
        envars={},
        MLFLOW_TRACKING_DIR="",
        home_abs=tmp_path,
    )
    fake_st = SimpleNamespace(
        session_state={"env": env},
        markdown=lambda text, unsafe_allow_html=False: calls.append((text, unsafe_allow_html)),
        warning=lambda message: warnings.append(str(message)),
        info=lambda message: infos.append(str(message)),
        error=lambda message: errors.append(str(message)),
        stop=_stop,
    )
    monkeypatch.setattr(pagelib, "st", fake_st)

    get_custom_buttons = getattr(pagelib.get_custom_buttons, "__wrapped__", pagelib.get_custom_buttons)
    get_info_bar = getattr(pagelib.get_info_bar, "__wrapped__", pagelib.get_info_bar)
    assert get_custom_buttons() == {"buttons": ["run"]}
    assert get_info_bar() == {"title": "AGILab"}

    class FakeSocket:
        def __init__(self, result):
            self.result = result

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def connect_ex(self, _addr):
            return self.result

    monkeypatch.setattr(pagelib.socket, "socket", lambda *args, **kwargs: FakeSocket(0))
    assert pagelib.is_port_in_use(1234) is True
    monkeypatch.setattr(pagelib.socket, "socket", lambda *args, **kwargs: FakeSocket(1))
    assert pagelib.is_port_in_use(1234) is False

    monkeypatch.setattr(pagelib.random, "randint", lambda low, high: 9123)
    assert pagelib.get_random_port() == 9123

    monkeypatch.setattr(pagelib.sys, "platform", "linux")
    assert pagelib._focus_existing_docs_tab("http://example/docs") is False

    monkeypatch.setattr(pagelib.sys, "platform", "darwin")
    monkeypatch.setattr(
        pagelib.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="true\n"),
    )
    assert pagelib._focus_existing_docs_tab("http://example/docs") is True

    monkeypatch.setattr(
        pagelib.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("osascript missing")),
    )
    assert pagelib._focus_existing_docs_tab("http://example/docs") is False

    pagelib.open_new_tab("http://example/docs")
    assert calls == [("<script>window.open('http://example/docs');</script>", True)]

    warnings.clear()
    assert pagelib.run_agi([], path=".") is None
    assert any("No code supplied" in message for message in warnings)

    captured: dict[str, object] = {}
    target_root = tmp_path / "project"
    venv_path = target_root / ".venv"
    venv_path.mkdir(parents=True)
    monkeypatch.setattr(
        pagelib,
        "run_with_output",
        lambda _env, cmd, cwd: captured.update(cmd=cmd, cwd=cwd) or "ok",
    )
    result = pagelib.run_agi(["a", "b", "await Agi.demo_run()"], path=venv_path)
    assert result == "ok"
    assert captured["cwd"] == str(target_root)
    assert any(str(part).endswith("demo_run_demo_project.py") for part in captured["cmd"])

    restricted = tmp_path / "restricted"
    real_exists = Path.exists

    def _exists(self):
        if self == restricted:
            raise PermissionError("denied")
        return real_exists(self)

    monkeypatch.setattr(Path, "exists", _exists)
    monkeypatch.setattr(pagelib, "diagnose_data_directory", lambda _path: "share hint")
    with pytest.raises(RuntimeError, match="stop"):
        pagelib.run_agi("print('x')", path=restricted)
    assert any("Permission denied while accessing" in message and "share hint" in message for message in errors)

    monkeypatch.setattr(Path, "exists", real_exists)
    with pytest.raises(RuntimeError, match="stop"):
        pagelib.run_agi("print('x')", path=tmp_path / "missing-project")
    assert any("Please do an install first" in message for message in infos)


def test_activate_mlflow_and_gpt_oss_cover_no_env_and_runtime_failures(monkeypatch, tmp_path):
    errors: list[str] = []
    warnings: list[str] = []
    _patch_mlflow_cli(monkeypatch)
    fake_st = SimpleNamespace(
        session_state={},
        error=lambda message: errors.append(str(message)),
        warning=lambda message: warnings.append(str(message)),
    )
    monkeypatch.setattr(pagelib, "st", fake_st)

    assert pagelib.activate_mlflow(None) is None
    assert pagelib.activate_gpt_oss(None) is False

    env = SimpleNamespace(
        MLFLOW_TRACKING_DIR="",
        home_abs=tmp_path,
        envars={},
    )
    monkeypatch.setattr(pagelib, "_ensure_default_mlflow_experiment", lambda _tracking_dir: "sqlite:///tmp/mlflow.db")
    monkeypatch.setattr(pagelib, "_resolve_mlflow_artifact_dir", lambda _tracking_dir: tmp_path / "artifacts")
    monkeypatch.setattr(pagelib, "get_random_port", lambda: 50123)
    monkeypatch.setattr(pagelib, "is_port_in_use", lambda _port: False)
    monkeypatch.setattr(pagelib, "_wait_for_listen_port", lambda _port: True)
    monkeypatch.setattr(pagelib, "subproc", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    pagelib.activate_mlflow(env)
    assert any("Failed to start the server: boom" in message for message in errors)

    errors.clear()
    fake_st.session_state["gpt_oss_server_started"] = True
    assert pagelib.activate_gpt_oss(SimpleNamespace(envars={})) is True

    fake_st.session_state.clear()
    monkeypatch.setitem(sys.modules, "gpt_oss", SimpleNamespace())
    monkeypatch.setattr(pagelib, "get_random_port", lambda: 50124)
    monkeypatch.setattr(pagelib, "is_port_in_use", lambda _port: False)
    monkeypatch.setattr(pagelib, "subproc", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("launch failed")))
    assert pagelib.activate_gpt_oss(SimpleNamespace(envars={})) is False
    assert any("Failed to start GPT-OSS server: launch failed" in message for message in errors)


def test_ensure_default_mlflow_experiment_returns_none_without_mlflow(tmp_path, monkeypatch):
    monkeypatch.setattr(pagelib, "_get_mlflow_module", lambda: None)

    assert pagelib._ensure_default_mlflow_experiment(tmp_path) is None


def test_ensure_default_mlflow_experiment_ignores_create_error_and_retries_only_once(tmp_path, monkeypatch):
    calls: dict[str, object] = {"create": 0, "set_tracking": []}

    class FakeMlflow:
        def set_tracking_uri(self, uri):
            calls["set_tracking"].append(uri)

        def get_experiment_by_name(self, _name):
            return None

        def create_experiment(self, _name, artifact_location=None):
            calls["create"] = int(calls["create"]) + 1
            raise RuntimeError("already exists")

        def set_experiment(self, name):
            calls["set_experiment"] = name

    monkeypatch.setattr(pagelib, "_get_mlflow_module", lambda: FakeMlflow())
    monkeypatch.setattr(pagelib, "_ensure_mlflow_backend_ready", lambda _tracking_dir: "sqlite:///tmp/mlflow.db")

    uri = pagelib._ensure_default_mlflow_experiment(tmp_path)

    assert uri == "sqlite:///tmp/mlflow.db"
    assert calls["create"] == 1
    assert calls["set_experiment"] == pagelib.DEFAULT_MLFLOW_EXPERIMENT_NAME


def test_activate_mlflow_keeps_server_stopped_when_port_never_opens(tmp_path, monkeypatch):
    errors: list[str] = []
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


def test_ensure_default_mlflow_experiment_reraises_non_schema_error(tmp_path, monkeypatch):
    class FakeMlflow:
        def set_tracking_uri(self, _uri):
            return None

        def get_experiment_by_name(self, _name):
            raise RuntimeError("plain failure")

    monkeypatch.setattr(pagelib, "_get_mlflow_module", lambda: FakeMlflow())
    monkeypatch.setattr(pagelib, "_ensure_mlflow_backend_ready", lambda _tracking_dir: "sqlite:///tmp/mlflow.db")

    with pytest.raises(RuntimeError, match="plain failure"):
        pagelib._ensure_default_mlflow_experiment(tmp_path)


def test_ensure_mlflow_backend_ready_raises_when_legacy_migration_fails(tmp_path, monkeypatch):
    tracking_dir = (tmp_path / ".mlflow").resolve()
    tracking_dir.mkdir(parents=True)
    (tracking_dir / "0").mkdir()
    (tracking_dir / "meta.yaml").write_text("legacy", encoding="utf-8")

    monkeypatch.setattr(
        pagelib.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="migrate boom"),
    )
    _patch_mlflow_cli(monkeypatch)

    with pytest.raises(RuntimeError, match="Failed to migrate the legacy MLflow file store"):
        pagelib._ensure_mlflow_backend_ready(tracking_dir)


def test_ensure_mlflow_sqlite_schema_current_resets_on_known_marker(tmp_path, monkeypatch):
    db_path = tmp_path / "mlflow.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.execute("INSERT INTO alembic_version (version_num) VALUES ('head')")
        conn.commit()

    resets: list[Path] = []
    monkeypatch.setattr(
        pagelib.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="duplicate column name: lifecycle_stage",
        ),
    )
    monkeypatch.setattr(pagelib, "_reset_mlflow_sqlite_backend", lambda path: resets.append(path) or path)
    monkeypatch.setattr(pagelib, "_MLFLOW_SQLITE_UPGRADE_CHECKED", set())
    _patch_mlflow_cli(monkeypatch)

    pagelib._ensure_mlflow_sqlite_schema_current(db_path)

    assert resets == [db_path]


def test_current_mount_points_parses_mount_output_and_skips_bad_lines(monkeypatch, tmp_path):
    real_path = Path
    monkeypatch.setattr(
        pagelib,
        "Path",
        lambda raw: tmp_path / "proc_mounts_missing"
        if str(raw) == "/proc/mounts"
        else real_path(raw),
    )
    monkeypatch.setattr(
        pagelib.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout="\n".join(
                [
                    "server:/share on /mnt/share (nfs, nodev)",
                    "invalid line",
                    "server:/blank on   (nfs, nodev)",
                ]
            )
        ),
    )

    mounts = pagelib._current_mount_points()

    assert mounts == {(Path("/mnt/share").resolve(strict=False)): "nfs"}


def test_current_mount_points_returns_empty_dict_when_mount_query_fails(monkeypatch, tmp_path):
    real_path = Path
    monkeypatch.setattr(
        pagelib,
        "Path",
        lambda raw: tmp_path / "proc_mounts_missing"
        if str(raw) == "/proc/mounts"
        else real_path(raw),
    )
    monkeypatch.setattr(
        pagelib.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("mount missing")),
    )

    assert pagelib._current_mount_points() == {}


def test_current_mount_points_handles_proc_mount_read_error_and_malformed_mount_output(monkeypatch, tmp_path):
    real_path = Path

    class FakeTextFile:
        def exists(self):
            return True

        def read_text(self, *args, **kwargs):
            raise OSError("unreadable")

    monkeypatch.setattr(
        pagelib,
        "Path",
        lambda raw: FakeTextFile() if str(raw) == "/proc/mounts" else real_path(raw),
    )
    assert pagelib._current_mount_points() == {}

    class MissingProc:
        def exists(self):
            return False

    monkeypatch.setattr(
        pagelib,
        "Path",
        lambda raw: MissingProc() if str(raw) == "/proc/mounts" else real_path(raw),
    )
    monkeypatch.setattr(
        pagelib.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout="server:/share on /mnt/share without-parenthesis\n"
        ),
    )

    assert pagelib._current_mount_points() == {}


def test_fstab_mount_points_handles_missing_file_and_short_lines(monkeypatch, tmp_path):
    real_path = Path
    pagelib._fstab_mount_points.cache_clear()

    class MissingFstab:
        def exists(self):
            return False

    monkeypatch.setattr(
        pagelib,
        "Path",
        lambda raw: MissingFstab() if str(raw) == "/etc/fstab" else real_path(raw),
    )
    assert pagelib._fstab_mount_points() == ()

    class FakeFstab:
        def exists(self):
            return True

        def read_text(self, *args, **kwargs):
            return "bogus\nserver:/share /mnt/share nfs defaults 0 0\n"

    pagelib._fstab_mount_points.cache_clear()
    monkeypatch.setattr(
        pagelib,
        "Path",
        lambda raw: FakeFstab() if str(raw) == "/etc/fstab" else real_path(raw),
    )
    assert pagelib._fstab_mount_points() == (real_path("/mnt/share"),)


def test_diagnose_data_directory_handles_resolve_runtimeerror_and_non_matching_mount(tmp_path, monkeypatch):
    original_resolve = Path.resolve

    def _patched_resolve(self, *args, **kwargs):
        if self == tmp_path / "share" / "payload":
            raise RuntimeError("resolve failed")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(pagelib.Path, "resolve", _patched_resolve, raising=False)
    monkeypatch.setattr(pagelib, "_fstab_mount_points", lambda: ())
    monkeypatch.setattr(pagelib, "_current_mount_points", lambda: {})
    assert pagelib.diagnose_data_directory(tmp_path / "share" / "payload") is None

    other_mount = tmp_path / "other"
    other_mount.mkdir()
    monkeypatch.setattr(pagelib, "_fstab_mount_points", lambda: (other_mount,))
    assert pagelib.diagnose_data_directory(tmp_path / "share" / "payload") is None


def test_diagnose_data_directory_reports_missing_fstype_autofs_and_iterdir_failure(tmp_path, monkeypatch):
    mount_dir = tmp_path / "data_share"
    mount_dir.mkdir()

    monkeypatch.setattr(pagelib, "_fstab_mount_points", lambda: (mount_dir,))
    monkeypatch.setattr(pagelib, "_current_mount_points", lambda: {})
    assert "not mounted" in pagelib.diagnose_data_directory(mount_dir / "payload")

    monkeypatch.setattr(pagelib, "_current_mount_points", lambda: {mount_dir: "autofs"})
    assert "not mounted" in pagelib.diagnose_data_directory(mount_dir / "payload")

    monkeypatch.setattr(pagelib, "_current_mount_points", lambda: {mount_dir: "nfs"})
    original_iterdir = Path.iterdir

    def _broken_iterdir(self):
        if self == mount_dir:
            raise OSError("share unavailable")
        return original_iterdir(self)

    monkeypatch.setattr(pagelib.Path, "iterdir", _broken_iterdir, raising=False)
    assert "unreachable" in pagelib.diagnose_data_directory(mount_dir / "payload")


def test_wait_for_listen_port_wrapper_delegates_to_runtime_impl(monkeypatch):
    captured = {}

    def _fake_wait(port, **kwargs):
        captured["port"] = port
        captured["kwargs"] = kwargs
        return "ready"

    monkeypatch.setattr(pagelib, "_wait_for_listen_port_impl", _fake_wait)

    assert pagelib._wait_for_listen_port(50123, timeout_sec=1.5, poll_interval_sec=0.2) == "ready"
    assert captured["port"] == 50123
    assert captured["kwargs"]["is_port_in_use_fn"] is pagelib.is_port_in_use


def test_pagelib_wrapper_functions_delegate_selection_helpers(monkeypatch):
    captured = {}
    session_state = {"demo": "state"}
    fake_st = SimpleNamespace(session_state=session_state, sidebar="sidebar", query_params={"app": "demo"})
    monkeypatch.setattr(pagelib, "st", fake_st)
    monkeypatch.setattr(pagelib, "logger", SimpleNamespace())

    def _capture_select(*args, **kwargs):
        captured["select"] = (args, kwargs)
        return "selected"

    def _capture_active(*args, **kwargs):
        captured["active"] = (args, kwargs)
        return ("demo_project", True)

    def _capture_sidebar(*args, **kwargs):
        captured["sidebar"] = (args, kwargs)
        return "sidebar-views"

    def _capture_df(*args, **kwargs):
        captured["df"] = (args, kwargs)
        return "df-changed"

    monkeypatch.setattr(pagelib, "_select_project_impl", _capture_select)
    monkeypatch.setattr(pagelib, "_resolve_active_app_impl", _capture_active)
    monkeypatch.setattr(pagelib, "_sidebar_views_impl", _capture_sidebar)
    monkeypatch.setattr(pagelib, "_on_df_change_impl", _capture_df)
    monkeypatch.setattr(pagelib, "on_lab_change", lambda *_args, **_kwargs: None, raising=False)
    monkeypatch.setattr(pagelib, "load_last_stage", lambda *_args, **_kwargs: None, raising=False)

    assert pagelib.select_project(["demo_project"], "demo_project") == "selected"
    assert pagelib.resolve_active_app(SimpleNamespace(app="demo_project")) == ("demo_project", True)
    assert pagelib.sidebar_views() == "sidebar-views"
    assert pagelib.on_df_change(Path("demo"), "page", None, None) == "df-changed"
    assert captured["select"][1]["session_state"] is session_state
    assert captured["active"][1]["query_params"] == {"app": "demo"}
    assert captured["sidebar"][1]["session_state"] is session_state
    assert captured["df"][1]["session_state"] is session_state


def test_update_views_ignores_missing_page_between_listdir_and_stat(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    pages_root = repo_root / "src" / "gui" / "pages"
    pages_root.mkdir(parents=True)
    session_state = SimpleNamespace(
        _env=SimpleNamespace(change_app=lambda _project: None),
        preview_tree=True,
    )
    monkeypatch.setattr(pagelib, "st", SimpleNamespace(session_state=session_state))
    monkeypatch.setattr(pagelib.os, "getcwd", lambda: str(repo_root))
    monkeypatch.setattr(pagelib.os, "listdir", lambda _path: ["ghost.py"])
    monkeypatch.setattr(
        pagelib.os,
        "stat",
        lambda _path: (_ for _ in ()).throw(FileNotFoundError("already removed")),
    )

    assert pagelib.update_views("demo_project", []) is False


def test_detect_agilab_version_returns_dev_suffix_when_git_metadata_fails(monkeypatch):
    monkeypatch.setattr(ui_support, "read_version_from_pyproject", lambda _env: "2026.04.13")
    monkeypatch.setattr(ui_support.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("git boom")))

    version = ui_support.detect_agilab_version(SimpleNamespace(is_source_env=True, agilab_pck=Path("/tmp/demo")))

    assert version == "2026.04.13+dev"


def test_load_df_covers_missing_json_directory_latin1_and_without_index(tmp_path):
    load_df = getattr(pagelib.load_df, "__wrapped__", pagelib.load_df)

    assert load_df(tmp_path / "missing.csv") is None

    json_dir = tmp_path / "json-dir"
    json_dir.mkdir()
    (json_dir / "a.json").write_text('[{"value": 1}, {"value": 2}]', encoding="utf-8")
    json_df = load_df(json_dir, with_index=False)
    assert list(json_df["value"]) == [1, 2]

    latin1_csv = tmp_path / "latin1.csv"
    latin1_csv.write_bytes("name,value\ncaf\xe9,3\n".encode("latin-1"))
    latin_df = load_df(latin1_csv, with_index=False)
    assert latin_df.iloc[0]["name"] == "café"
    assert latin_df.index.tolist() == [0]


def test_save_csv_handles_empty_dataframe_and_cache_clear_failure(tmp_path, monkeypatch):
    errors: list[str] = []
    monkeypatch.setattr(pagelib.st, "error", lambda message: errors.append(str(message)))

    class _ClearBroken:
        def clear(self):
            raise RuntimeError("cache busy")

    monkeypatch.setattr(pagelib, "find_files", _ClearBroken())
    df = pd.DataFrame({"value": [1]})
    output = tmp_path / "nested" / "out.csv"

    assert pagelib.save_csv(df, output) is True
    assert output.exists()
    assert pagelib.save_csv(pd.DataFrame(index=[0]), tmp_path / "empty.csv") is False
    assert errors == []


def test_get_df_index_returns_zero_when_defaulting_to_first_file(tmp_path):
    missing = tmp_path / "missing.csv"

    assert pagelib.get_df_index(["fallback.csv"], missing) == 0


def test_get_first_match_and_keyword_skips_invalid_items(capsys):
    found_text, found_keyword = pagelib.get_first_match_and_keyword(
        [123, "mission-time"],
        [None, "time"],
    )

    captured = capsys.readouterr()
    assert found_text == "mission-time"
    assert found_keyword == "time"
    assert "not a string" in captured.out
    assert "not a valid string" in captured.out


def test_handle_go_action_reports_selected_view(monkeypatch, tmp_path):
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        pagelib,
        "st",
        SimpleNamespace(
            success=lambda message: messages.append(("success", str(message))),
            write=lambda message: messages.append(("write", str(message))),
        ),
    )

    pagelib.handle_go_action("demo_view", tmp_path / "demo_view.py")

    assert messages == [
        ("success", "'Go' button clicked for view: demo_view"),
        ("write", f"View Path: {tmp_path / 'demo_view.py'}"),
    ]


def test_update_views_returns_false_when_everything_is_already_in_sync(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    pages_root = repo_root / "src" / "gui" / "pages"
    pages_root.mkdir(parents=True)
    source = tmp_path / "demo_view.py"
    source.write_text("print('demo')\n", encoding="utf-8")
    os.link(source, pages_root / "demo_view.py")

    session_state = SimpleNamespace(
        _env=SimpleNamespace(change_app=lambda _project: None),
        preview_tree=True,
    )
    monkeypatch.setattr(pagelib, "st", SimpleNamespace(session_state=session_state))
    monkeypatch.setattr(pagelib.os, "getcwd", lambda: str(repo_root))

    updated = pagelib.update_views("demo_project", [str(source)])

    assert updated is False
    assert session_state.preview_tree is False


def test_activate_gpt_oss_stub_backend_clears_checkpoint_and_extra_args(monkeypatch):
    fake_st = SimpleNamespace(
        session_state={
            "gpt_oss_checkpoint": "   ",
            "gpt_oss_extra_args": "   ",
            "gpt_oss_checkpoint_active": "old-checkpoint",
            "gpt_oss_extra_args_active": "--old",
        },
        warning=lambda *_args, **_kwargs: None,
        error=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(pagelib, "st", fake_st)
    monkeypatch.setitem(sys.modules, "gpt_oss", SimpleNamespace())
    monkeypatch.setattr(pagelib, "get_random_port", lambda: 50130)
    monkeypatch.setattr(pagelib, "is_port_in_use", lambda _port: False)
    monkeypatch.setattr(pagelib, "subproc", lambda *_args, **_kwargs: None)

    env = SimpleNamespace(envars={"GPT_OSS_BACKEND": "stub", "GPT_OSS_CHECKPOINT": "obsolete"})

    assert pagelib.activate_gpt_oss(env) is True
    assert "GPT_OSS_CHECKPOINT" not in env.envars
    assert "gpt_oss_checkpoint_active" not in fake_st.session_state
    assert "gpt_oss_extra_args_active" not in fake_st.session_state


def test_activate_gpt_oss_transformers_backend_retries_busy_port_and_keeps_active_flags(monkeypatch):
    fake_st = SimpleNamespace(
        session_state={
            "gpt_oss_backend": "transformers",
            "gpt_oss_checkpoint": "demo-checkpoint",
            "gpt_oss_extra_args": "--temperature 0.1",
        },
        warning=lambda *_args, **_kwargs: None,
        error=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(pagelib, "st", fake_st)
    monkeypatch.setitem(sys.modules, "gpt_oss", SimpleNamespace())

    ports = iter([50131, 50132])
    launched: dict[str, tuple[str, str]] = {}
    monkeypatch.setattr(pagelib, "get_random_port", lambda: next(ports))
    monkeypatch.setattr(pagelib, "is_port_in_use", lambda port: port == 50131)
    monkeypatch.setattr(
        pagelib,
        "subproc",
        lambda command, cwd: launched.setdefault("call", (command, cwd)),
    )

    env = SimpleNamespace(envars={})

    assert pagelib.activate_gpt_oss(env) is True
    command = launched["call"][0]
    assert command[command.index("--inference-backend") + 1] == "transformers"
    assert command[command.index("--checkpoint") + 1] == "demo-checkpoint"
    assert command[-2:] == ["--temperature", "0.1"]
    assert fake_st.session_state["gpt_oss_port"] == 50132
    assert fake_st.session_state["gpt_oss_checkpoint_active"] == "demo-checkpoint"
    assert fake_st.session_state["gpt_oss_extra_args_active"] == "--temperature 0.1"
    assert env.envars["GPT_OSS_CHECKPOINT"] == "demo-checkpoint"
    assert env.envars["GPT_OSS_EXTRA_ARGS"] == "--temperature 0.1"


def test_scan_dir_returns_empty_list_for_missing_path(tmp_path):
    assert pagelib.scan_dir(tmp_path / "missing") == []
