from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = Path("src/agilab/pages/4_▶️ ANALYSIS.py")


def _load_analysis_module():
    spec = importlib.util.spec_from_file_location("agilab_analysis_page_tests", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_read_config_loads_valid_toml(tmp_path: Path):
    module = _load_analysis_module()
    config_path = tmp_path / "view.toml"
    config_path.write_text('title = "demo"\n', encoding="utf-8")

    assert module._read_config(config_path) == {"title": "demo"}


def test_read_config_reports_invalid_toml(tmp_path: Path, monkeypatch):
    module = _load_analysis_module()
    errors: list[str] = []
    monkeypatch.setattr(module, "st", SimpleNamespace(error=lambda message: errors.append(str(message))))
    config_path = tmp_path / "view.toml"
    config_path.write_text("title = \n", encoding="utf-8")

    assert module._read_config(config_path) == {}
    assert any(message.startswith("Error loading configuration:") for message in errors)


def test_write_config_creates_parent_and_persists_toml(tmp_path: Path):
    module = _load_analysis_module()
    config_path = tmp_path / "nested" / "view.toml"

    module._write_config(config_path, {"title": "demo"})

    assert config_path.read_text(encoding="utf-8") == 'title = "demo"\n'


def test_write_config_reports_oserror(tmp_path: Path, monkeypatch):
    module = _load_analysis_module()
    errors: list[str] = []
    monkeypatch.setattr(module, "st", SimpleNamespace(error=lambda message: errors.append(str(message))))

    def _raise_dump(_cfg, _stream):
        raise OSError("disk full")

    monkeypatch.setattr(module.tomli_w, "dump", _raise_dump)
    config_path = tmp_path / "nested" / "view.toml"

    module._write_config(config_path, {"title": "demo"})

    assert errors == ["Error updating configuration: disk full"]


def test_resolve_discovered_views_skips_broken_entry(tmp_path: Path, monkeypatch):
    module = _load_analysis_module()
    good_view = tmp_path / "good_view.py"
    broken_view = tmp_path / "broken_view.py"
    good_view.write_text("", encoding="utf-8")
    broken_view.write_text("", encoding="utf-8")

    def _fake_root(path: Path):
        if path == broken_view:
            raise OSError("bad path")
        return None

    monkeypatch.setattr(module, "_resolve_page_project_root", _fake_root)
    monkeypatch.setattr(module, "_find_view_entrypoint", lambda path: path)

    resolved = module._resolve_discovered_views([good_view, broken_view])

    assert resolved == {"good_view": good_view}


def test_render_selected_view_route_reports_error(monkeypatch):
    module = _load_analysis_module()
    errors: list[str] = []
    monkeypatch.setattr(module, "st", SimpleNamespace(error=lambda message: errors.append(str(message))))

    async def _raise_render(_path: Path):
        raise RuntimeError("broken view")

    monkeypatch.setattr(module, "render_view_page", _raise_render)

    handled = asyncio.run(module._render_selected_view_route("/tmp/view.py"))

    assert handled is True
    assert errors == ["Failed to render view: broken view"]


def test_render_selected_view_route_ignores_main_route():
    module = _load_analysis_module()

    handled = asyncio.run(module._render_selected_view_route("main"))

    assert handled is False


def test_resolve_default_view_accepts_named_view(tmp_path: Path):
    module = _load_analysis_module()
    view_path = tmp_path / "view_maps_network.py"
    view_path.write_text("", encoding="utf-8")

    key, resolved = module._resolve_default_view(
        "view_maps_network",
        ["view_maps_network", "view_maps"],
        {"view_maps_network": view_path},
        {},
    )

    assert key == "view_maps_network"
    assert resolved == view_path


def test_resolve_default_view_returns_none_when_missing():
    module = _load_analysis_module()

    key, resolved = module._resolve_default_view(
        "view_maps_network",
        ["view_maps"],
        {},
        {},
    )

    assert key is None
    assert resolved is None


def test_create_analysis_page_bundle_writes_blank_template(tmp_path: Path):
    module = _load_analysis_module()

    entrypoint = module._create_analysis_page_bundle(tmp_path, "demo_view", "")

    assert entrypoint == tmp_path / "demo_view" / "src" / "demo_view" / "demo_view.py"
    assert entrypoint.exists()
    template_text = entrypoint.read_text(encoding="utf-8")
    assert "except (ImportError, ModuleNotFoundError, OSError) as exc" in template_text


def test_clone_source_label_falls_back_to_absolute_path(tmp_path: Path):
    module = _load_analysis_module()
    page_file = tmp_path / "view_demo.py"
    page_file.write_text("", encoding="utf-8")
    foreign_root = tmp_path / "other_root"
    foreign_root.mkdir()

    label = module._clone_source_label(page_file, foreign_root)

    assert label == f"view_demo ({page_file})"


def test_terminate_process_quietly_ignores_timeout():
    module = _load_analysis_module()

    class _FakeProcess:
        def __init__(self):
            self.terminated = False
            self.wait_calls = 0

        def terminate(self):
            self.terminated = True

        def wait(self, timeout: int):
            self.wait_calls += 1
            raise module.subprocess.TimeoutExpired(cmd="demo", timeout=timeout)

    process = _FakeProcess()

    module._terminate_process_quietly(process)

    assert process.terminated is True
    assert process.wait_calls == 1


def test_is_hosted_analysis_runtime_uses_agi_env_envars():
    module = _load_analysis_module()

    assert module._is_hosted_analysis_runtime(SimpleNamespace(envars={})) is False
    assert module._is_hosted_analysis_runtime(SimpleNamespace(envars={"SPACE_HOST": "demo.hf.space"})) is True
    assert module._is_hosted_analysis_runtime(SimpleNamespace(envars={"SPACE_ID": "user/demo"})) is True


def test_render_view_page_inline_executes_page_main_with_active_app(tmp_path: Path, monkeypatch):
    module = _load_analysis_module()
    fake_streamlit = types.ModuleType("streamlit")
    fake_streamlit.session_state = {}
    fake_streamlit.error = lambda *_args, **_kwargs: None
    fake_streamlit.info = lambda *_args, **_kwargs: None
    fake_streamlit.warning = lambda *_args, **_kwargs: None
    fake_streamlit.caption = lambda *_args, **_kwargs: None

    def _forbidden_set_page_config(*_args, **_kwargs):
        raise AssertionError("set_page_config should be suppressed during inline render")

    fake_streamlit.set_page_config = _forbidden_set_page_config
    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)
    monkeypatch.setattr(module, "st", fake_streamlit)

    active_app = tmp_path / "flight_project"
    active_app.mkdir()
    page_path = tmp_path / "demo_view.py"
    page_path.write_text(
        """
import argparse
import streamlit as st

def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--active-app", required=True)
    args, _ = parser.parse_known_args()
    st.session_state["inline_active_app"] = args.active_app
    st.set_page_config(layout="wide")
""",
        encoding="utf-8",
    )

    asyncio.run(module._render_view_page_inline(page_path, str(active_app)))

    assert fake_streamlit.session_state["inline_active_app"] == str(active_app)
