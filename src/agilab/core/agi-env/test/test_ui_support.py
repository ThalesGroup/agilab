from __future__ import annotations

import importlib
import importlib.util
import base64
import io
from pathlib import Path
from types import SimpleNamespace
import sys
from unittest.mock import patch

import pytest

from agi_env import ui_support


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
        sys_modules_backup = sys.modules.get(module_name)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        finally:
            if sys_modules_backup is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = sys_modules_backup
    return module


def test_ui_support_global_state_and_last_active_app_round_trip(tmp_path, monkeypatch):
    app_dir = tmp_path / "demo_project"
    app_dir.mkdir()
    state_file = tmp_path / "app_state.toml"
    legacy_file = tmp_path / ".last-active-app"
    state_file.write_text(f'last_active_app = "{app_dir}"\n', encoding="utf-8")

    monkeypatch.setattr(ui_support, "_GLOBAL_STATE_FILE", state_file)
    monkeypatch.setattr(ui_support, "_LEGACY_LAST_APP_FILE", legacy_file)

    assert ui_support.load_global_state() == {"last_active_app": str(app_dir)}
    assert ui_support.load_last_active_app() == app_dir

    dumped: list[dict[str, str]] = []

    def _dump_payload(data, handle):
        dumped.append(dict(data))
        handle.write(f'last_active_app = "{data["last_active_app"]}"\n'.encode("utf-8"))

    monkeypatch.setattr(ui_support, "_dump_toml_payload", _dump_payload)
    ui_support.persist_global_state({"last_active_app": str(app_dir)})

    assert dumped == [{"last_active_app": str(app_dir)}]
    assert state_file.read_text(encoding="utf-8").strip() == f'last_active_app = "{app_dir}"'

    current_state = {}
    persisted: list[dict[str, str]] = []
    monkeypatch.setattr(ui_support, "load_global_state", lambda: dict(current_state))
    monkeypatch.setattr(
        ui_support,
        "persist_global_state",
        lambda data: persisted.append(dict(data)) or current_state.update(data),
    )

    ui_support.store_last_active_app(object())
    ui_support.store_last_active_app(app_dir)
    ui_support.store_last_active_app(app_dir)

    assert persisted == [{"last_active_app": str(app_dir)}]


def test_ui_support_focus_existing_docs_tab_wrapper_passes_through(monkeypatch):
    captured = {}

    def _impl(target_url, *, platform, run_cmd):
        captured["target_url"] = target_url
        captured["platform"] = platform
        captured["run_cmd"] = run_cmd
        return True

    monkeypatch.setattr(ui_support, "_focus_existing_docs_tab_impl", _impl)

    assert ui_support.focus_existing_docs_tab("http://example/docs") is True
    assert captured == {
        "target_url": "http://example/docs",
        "platform": ui_support.sys.platform,
        "run_cmd": ui_support.subprocess.run,
    }


def test_ui_support_open_docs_url_refocuses_or_opens_new_tab(monkeypatch):
    opened: list[str] = []
    target_url = "http://example/docs"

    ui_support._DOCS_ALREADY_OPENED = True
    ui_support._LAST_DOCS_URL = target_url

    monkeypatch.setattr(ui_support, "focus_existing_docs_tab", lambda _url: False)
    monkeypatch.setattr(ui_support.webbrowser, "open_new_tab", lambda url: opened.append(url))

    ui_support.open_docs_url(target_url)

    assert opened == [target_url]
    assert ui_support._DOCS_ALREADY_OPENED is True
    assert ui_support._LAST_DOCS_URL == target_url


def test_ui_support_open_docs_url_keeps_existing_tab_when_focus_succeeds(monkeypatch):
    opened: list[str] = []
    target_url = "http://example/docs"

    monkeypatch.setattr(ui_support, "_DOCS_ALREADY_OPENED", True)
    monkeypatch.setattr(ui_support, "_LAST_DOCS_URL", target_url)
    monkeypatch.setattr(ui_support, "focus_existing_docs_tab", lambda _url: True)
    monkeypatch.setattr(ui_support.webbrowser, "open_new_tab", lambda url: opened.append(url))

    ui_support.open_docs_url(target_url)

    assert opened == []
    assert ui_support._DOCS_ALREADY_OPENED is True
    assert ui_support._LAST_DOCS_URL == target_url


def test_ui_support_open_docs_uses_local_path_when_available(monkeypatch, tmp_path):
    docs_file = tmp_path / "docs" / "index.html"
    docs_file.parent.mkdir(parents=True)
    docs_file.write_text("docs", encoding="utf-8")
    opened = []

    monkeypatch.setattr(ui_support, "resolve_docs_path", lambda _env, _html_file="index.html": docs_file)
    monkeypatch.setattr(ui_support, "open_docs_url", lambda url: opened.append(url))

    ui_support.open_docs(SimpleNamespace(agilab_pck=tmp_path), anchor="section")

    assert opened == [f"{docs_file.as_uri()}#section"]


def test_ui_support_open_docs_falls_back_to_online_when_missing(monkeypatch):
    opened = []

    monkeypatch.setattr(ui_support, "resolve_docs_path", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ui_support, "open_docs_url", lambda url: opened.append(url))

    ui_support.open_docs(SimpleNamespace(agilab_pck=Path("/tmp")), anchor="intro")

    assert opened == [f"{ui_support.ONLINE_DOCS_INDEX}#intro"]


def test_ui_support_open_local_docs_raises_when_missing(monkeypatch):
    monkeypatch.setattr(ui_support, "resolve_docs_path", lambda *_args, **_kwargs: None)

    try:
        ui_support.open_local_docs(SimpleNamespace(agilab_pck=Path("/tmp")))
    except FileNotFoundError as exc:
        assert "index.html" in str(exc)
    else:
        raise AssertionError("open_local_docs should raise when docs are missing")


def test_ui_support_read_helpers_and_version_detection(tmp_path, monkeypatch):
    image_file = tmp_path / "image.bin"
    image_bytes = b"\x89PNG\r\n"
    image_file.write_bytes(image_bytes)
    assert ui_support.read_base64_image(image_file) == base64.b64encode(image_bytes).decode()

    resources = tmp_path / "resources"
    resources.mkdir()
    (resources / "code_editor.scss").write_text("body { color: red; }", encoding="utf-8")
    assert ui_support.read_css_text(resources) == "body { color: red; }"

    pkg_root = tmp_path / "pkg"
    resources_root = pkg_root / "resources"
    resources_root.mkdir(parents=True)
    theme_file = resources_root / "theme.css"
    theme_file.write_text("body { color: blue; }", encoding="utf-8")
    assert ui_support.read_theme_css(None, module_file=str(pkg_root / "nested" / "module.py")) == "body { color: blue; }"
    theme_file.write_bytes(b"body {\xff color: green; }")
    assert "color: green" in ui_support.read_theme_css(None, module_file=str(pkg_root / "nested" / "module.py"))

    (pkg_root / "pyproject.toml").write_text(
        "[project]\nname = \"agilab\"\nversion = \"1.2.3\"\n",
        encoding="utf-8",
    )
    source_env = SimpleNamespace(agilab_pck=pkg_root, is_source_env=True)
    monkeypatch.setattr(ui_support, "detect_dev_version_suffix", lambda *_args, **_kwargs: "+dev.abc")
    assert ui_support.read_version_from_pyproject(source_env) == "1.2.3"
    assert ui_support.detect_agilab_version(source_env) == "1.2.3+dev.abc"

    installed_module = SimpleNamespace(version=lambda _name: "9.9.9", PackageNotFoundError=RuntimeError)
    monkeypatch.setattr(ui_support, "_importlib_metadata", installed_module)
    assert ui_support.detect_agilab_version(SimpleNamespace(is_source_env=False)) == "9.9.9"


def test_ui_support_detect_agilab_version_falls_back_when_source_version_missing(monkeypatch):
    monkeypatch.setattr(ui_support, "read_version_from_pyproject", lambda _env: None)
    monkeypatch.setattr(ui_support, "detect_installed_version", lambda _module: "installed")

    assert ui_support.detect_agilab_version(SimpleNamespace(is_source_env=True, agilab_pck=Path("/tmp"))) == "installed"


def test_ui_support_dump_toml_payload_falls_back_to_tomlkit_when_tomli_w_missing():
    fallback = _load_ui_support_with_missing("agi_env.ui_support_tomlkit_fallback", "tomli_w")
    sink = io.BytesIO()

    fallback._dump_toml_payload({"last_active_app": "/tmp/demo"}, sink)

    assert b"last_active_app" in sink.getvalue()


def test_ui_support_dump_toml_payload_raises_when_no_writer_available():
    broken = _load_ui_support_with_missing("agi_env.ui_support_no_toml_writer", "tomli_w", "tomlkit")

    with pytest.raises(RuntimeError, match="Writing settings requires"):
        broken._dump_toml_payload({"demo": "value"}, io.BytesIO())
