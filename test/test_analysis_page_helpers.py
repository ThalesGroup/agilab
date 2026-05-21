from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import tomllib
import types
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = Path("src/agilab/pages/4_ANALYSIS.py")
STATE_MODULE_PATH = Path("src/agilab/analysis_page_state.py")


class _FakeAnalysisTemplateStreamlit:
    query_params: dict[str, str] = {}

    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    def set_page_config(self, **kwargs):
        self.events.append(("set_page_config", kwargs))

    def title(self, value):
        self.events.append(("title", value))

    def info(self, value):
        self.events.append(("info", value))

    def error(self, value):
        self.events.append(("error", value))

    def stop(self):
        raise RuntimeError("streamlit stop")

    def subheader(self, value):
        self.events.append(("subheader", value))

    def caption(self, value):
        self.events.append(("caption", value))

    def warning(self, value):
        self.events.append(("warning", value))

    def success(self, value):
        self.events.append(("success", value))

    def write(self, value):
        self.events.append(("write", value))

    def expander(self, *_args, **_kwargs):
        class _Context:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

        return _Context()


def _load_analysis_module():
    spec = importlib.util.spec_from_file_location("agilab_analysis_page_tests", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_analysis_state_module():
    spec = importlib.util.spec_from_file_location("agilab_analysis_page_state_tests", STATE_MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
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

    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert data == {
        "__meta__": {"schema": "agilab.app_settings.v1", "version": 1},
        "title": "demo",
    }


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


def test_analysis_sidebar_notebook_url_encodes_project_and_path(tmp_path: Path):
    module = _load_analysis_module()
    notebook_path = tmp_path / "flight notebook.ipynb"

    url = module._analysis_sidebar_notebook_url("flight_telemetry_project", notebook_path)

    assert url.startswith("?")
    assert "active_app=flight_telemetry_project" in url
    assert "current_notebook=" in url
    assert "flight+notebook.ipynb" in url or "flight%20notebook.ipynb" in url


def test_discover_project_notebooks_skips_checkpoints_and_sorts(tmp_path: Path):
    module = _load_analysis_module()
    module._NOTEBOOK_DISCOVERY_CACHE.clear()
    project_root = tmp_path / "flight_telemetry_project"
    notebooks_root = project_root / "notebooks"
    (notebooks_root / "extra").mkdir(parents=True)
    (notebooks_root / ".ipynb_checkpoints").mkdir()
    (notebooks_root / "lab_stages.ipynb").write_text("{}", encoding="utf-8")
    (notebooks_root / "extra" / "demo.ipynb").write_text("{}", encoding="utf-8")
    (notebooks_root / ".ipynb_checkpoints" / "lab_stages-checkpoint.ipynb").write_text(
        "{}",
        encoding="utf-8",
    )

    notebooks = module.discover_project_notebooks(project_root)

    assert list(notebooks) == ["extra/demo.ipynb", "lab_stages.ipynb"]
    assert notebooks["lab_stages.ipynb"] == (notebooks_root / "lab_stages.ipynb").resolve()


def test_discover_views_uses_cache_until_directory_signature_changes(tmp_path: Path, monkeypatch):
    module = _load_analysis_module()
    module._VIEW_DISCOVERY_CACHE.clear()
    pages_root = tmp_path / "apps-pages"
    pages_root.mkdir()
    first_view = (pages_root / "view_a.py").resolve()
    first_view.write_text("def main(): pass\n", encoding="utf-8")
    calls: list[Path] = []

    def fake_discover(root: Path) -> list[Path]:
        calls.append(root)
        return [path.resolve() for path in sorted(root.glob("*.py"))]

    monkeypatch.setattr(module, "_discover_views_uncached", fake_discover)

    assert module.discover_views(pages_root) == [first_view]
    assert module.discover_views(pages_root) == [first_view]
    assert calls == [pages_root.resolve()]

    second_view = (pages_root / "view_b.py").resolve()
    second_view.write_text("def main(): pass\n", encoding="utf-8")

    assert module.discover_views(pages_root) == [first_view, second_view]
    assert calls == [pages_root.resolve(), pages_root.resolve()]


def test_discover_views_skips_scaffold_templates(tmp_path: Path):
    module = _load_analysis_module()
    module._VIEW_DISCOVERY_CACHE.clear()
    pages_root = tmp_path / "apps-pages"
    real_view_root = pages_root / "view_real" / "src" / "view_real"
    template_root = pages_root / "templates" / "analysis_page_template" / "src" / "view_demo"
    real_view_root.mkdir(parents=True)
    template_root.mkdir(parents=True)
    real_view = (real_view_root / "view_real.py").resolve()
    template_view = (template_root / "view_demo.py").resolve()
    real_view.write_text("def main(): pass\n", encoding="utf-8")
    template_view.write_text("def main(): pass\n", encoding="utf-8")

    assert module.discover_views(pages_root) == [real_view]
    assert module._find_view_entry("templates", pages_root) is None


def test_discover_project_notebooks_uses_cache_until_directory_signature_changes(
    tmp_path: Path,
    monkeypatch,
):
    module = _load_analysis_module()
    module._NOTEBOOK_DISCOVERY_CACHE.clear()
    project_root = tmp_path / "flight_telemetry_project"
    notebooks_root = project_root / "notebooks"
    notebooks_root.mkdir(parents=True)
    first_notebook = (notebooks_root / "lab_stages.ipynb").resolve()
    first_notebook.write_text("{}", encoding="utf-8")
    calls: list[Path] = []

    def fake_discover(root: Path) -> dict[str, Path]:
        calls.append(root)
        return {
            path.resolve().relative_to(root).as_posix(): path.resolve()
            for path in sorted(root.rglob("*.ipynb"), key=lambda item: item.as_posix())
        }

    monkeypatch.setattr(module, "_discover_project_notebooks_uncached", fake_discover)

    assert module.discover_project_notebooks(project_root) == {
        "lab_stages.ipynb": first_notebook,
    }
    assert module.discover_project_notebooks(project_root) == {
        "lab_stages.ipynb": first_notebook,
    }
    assert calls == [notebooks_root.resolve()]

    extra_root = notebooks_root / "extra"
    extra_root.mkdir()
    second_notebook = (extra_root / "demo.ipynb").resolve()
    second_notebook.write_text("{}", encoding="utf-8")
    os.utime(extra_root)

    assert module.discover_project_notebooks(project_root) == {
        "extra/demo.ipynb": second_notebook,
        "lab_stages.ipynb": first_notebook,
    }
    assert calls == [notebooks_root.resolve(), notebooks_root.resolve()]


def test_configured_notebook_options_filters_unavailable_entries():
    module = _load_analysis_module()

    selected = module._configured_notebook_options(
        ["lab_stages.ipynb", "missing.ipynb", "extra\\demo.ipynb", "lab_stages.ipynb"],
        ["extra/demo.ipynb", "lab_stages.ipynb"],
    )

    assert selected == ["lab_stages.ipynb", "extra/demo.ipynb"]


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
    captions: list[str] = []
    code_blocks: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        module,
        "st",
        SimpleNamespace(
            error=lambda message: errors.append(str(message)),
            caption=lambda message: captions.append(str(message)),
            code=lambda body, language=None: code_blocks.append((str(body), language)),
        ),
    )

    async def _raise_render(_path: Path):
        raise RuntimeError("broken view")

    monkeypatch.setattr(module, "render_view_page", _raise_render)

    handled = asyncio.run(module._render_selected_view_route("/tmp/view.py"))

    assert handled is True
    assert errors == ["Failed to render view: broken view"]
    assert captions == ["Full traceback"]
    assert code_blocks
    assert "RuntimeError: broken view" in code_blocks[0][0]
    assert code_blocks[0][1] == "text"


def test_render_selected_view_route_ignores_main_route():
    module = _load_analysis_module()

    handled = asyncio.run(module._render_selected_view_route("main"))

    assert handled is False


def test_render_view_page_embeds_sidecar_with_streamlit_iframe(tmp_path: Path, monkeypatch):
    module = _load_analysis_module()
    view_path = tmp_path / "view_demo.py"
    view_path.write_text("", encoding="utf-8")
    calls: list[tuple[str, dict[str, object]]] = []

    class _Column:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    fake_logger = SimpleNamespace(info=lambda *_args, **_kwargs: None, error=lambda *_args, **_kwargs: None)
    fake_env = SimpleNamespace(
        apps_path=None,
        target=None,
        app=None,
        active_app="",
        AGILAB_LOG_ABS=tmp_path,
        logger=fake_logger,
    )
    fake_st = SimpleNamespace(
        session_state={"env": fake_env},
        query_params={"current_page": str(view_path), "datadir_rel": "sample"},
        columns=lambda _spec: [_Column(), _Column(), _Column()],
        button=lambda *_args, **_kwargs: False,
        subheader=lambda *_args, **_kwargs: None,
        iframe=lambda src, **kwargs: calls.append((src, kwargs)),
    )

    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module, "_hide_parent_sidebar", lambda: None)
    monkeypatch.setattr(module, "_is_hosted_analysis_runtime", lambda _env: False)
    monkeypatch.setattr(module, "_ensure_sidecar", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(module, "_port_for", lambda _key: 8765)

    asyncio.run(module.render_view_page(view_path))

    assert calls == [
        ("http://127.0.0.1:8765/?datadir_rel=sample&embed=true", {"height": 900})
    ]


def test_render_notebook_page_embeds_project_jupyter_sidecar(tmp_path: Path, monkeypatch):
    module = _load_analysis_module()
    project_root = tmp_path / "apps" / "flight_telemetry_project"
    notebook_path = project_root / "notebooks" / "lab_stages.ipynb"
    notebook_path.parent.mkdir(parents=True)
    notebook_path.write_text("{}", encoding="utf-8")
    calls: list[tuple[str, dict[str, object]]] = []

    class _Column:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    fake_logger = SimpleNamespace(info=lambda *_args, **_kwargs: None, error=lambda *_args, **_kwargs: None)
    fake_env = SimpleNamespace(
        apps_path=project_root.parent,
        target=None,
        app="flight_telemetry_project",
        active_app="",
        AGILAB_LOG_ABS=tmp_path,
        logger=fake_logger,
    )
    fake_st = SimpleNamespace(
        session_state={"env": fake_env},
        query_params={"current_notebook": str(notebook_path), "active_app": "flight_telemetry_project"},
        columns=lambda _spec: [_Column(), _Column(), _Column()],
        button=lambda *_args, **_kwargs: False,
        subheader=lambda *_args, **_kwargs: None,
        iframe=lambda src, **kwargs: calls.append((src, kwargs)),
    )

    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module, "_hide_parent_sidebar", lambda: None)
    monkeypatch.setattr(module, "_is_hosted_analysis_runtime", lambda _env: False)
    monkeypatch.setattr(module, "_ensure_notebook_sidecar", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(module, "_port_for", lambda _key: 8766)

    asyncio.run(module.render_notebook_page(notebook_path))

    assert calls == [
        (
            "http://127.0.0.1:8766/lab/tree/notebooks/lab_stages.ipynb?active_app=flight_telemetry_project&embed=true",
            {"height": 900},
        )
    ]


def test_ensure_notebook_sidecar_starts_lab_root_and_allows_iframe(tmp_path: Path, monkeypatch):
    module = _load_analysis_module()
    project_root = tmp_path / "apps" / "flight_telemetry_project"
    notebook_path = project_root / "notebooks" / "lab_stages.ipynb"
    notebook_path.parent.mkdir(parents=True)
    notebook_path.write_text("{}", encoding="utf-8")
    commands: list[tuple[object, str]] = []
    port_checks = iter([False, True])

    class _FakeProcess:
        returncode = None

        def poll(self):
            return None

    fake_logger = SimpleNamespace(info=lambda *_args, **_kwargs: None, error=lambda *_args, **_kwargs: None)
    fake_env = SimpleNamespace(
        envars={},
        uv="uv --quiet",
        AGILAB_LOG_ABS=tmp_path,
        logger=fake_logger,
    )
    fake_st = SimpleNamespace(session_state={"env": fake_env})

    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module, "_is_port_open", lambda _port: next(port_checks))

    def _fake_exec_bg(_env, cmd, cwd: str, process_env=None):
        commands.append((cmd, cwd))
        return _FakeProcess()

    monkeypatch.setattr(module, "exec_bg", _fake_exec_bg)

    assert module._ensure_notebook_sidecar("notebook-key", notebook_path, 8766, project_root) is True

    assert len(commands) == 1
    command, cwd = commands[0]
    assert isinstance(command, list)
    assert cwd == str(project_root.resolve())
    assert command[:3] == ["uv", "--quiet", "--preview-features"]
    assert command[command.index("--project") + 1] == str(project_root.resolve())
    assert f"--ServerApp.root_dir={project_root.resolve()}" in command
    assert "jupyter" in command
    assert "lab" in command
    assert "--no-browser" in command
    assert str(notebook_path.resolve()) not in command
    assert any(part.startswith("--ServerApp.tornado_settings=") for part in command)
    assert any("frame-ancestors *;" in part for part in command)
    assert not any("'" in part for part in command)


def test_source_bootstrap_stamp_invalidates_when_core_path_changes(tmp_path: Path):
    module = _load_analysis_module()
    project_root = tmp_path / "page_project"
    (project_root / ".venv" / "bin").mkdir(parents=True)
    (project_root / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
    (project_root / "pyproject.toml").write_text("[project]\nname='page-project'\n", encoding="utf-8")

    first_core = tmp_path / "core" / "agi-env"
    second_core = tmp_path / "other-core" / "agi-env"
    first_core.mkdir(parents=True)
    second_core.mkdir(parents=True)
    (first_core / "pyproject.toml").write_text("[project]\nname='agi-env'\n", encoding="utf-8")
    (second_core / "pyproject.toml").write_text("[project]\nname='agi-env'\n", encoding="utf-8")

    assert module._source_bootstrap_is_fresh(project_root, first_core) is False

    module._write_source_bootstrap_stamp(project_root, first_core)

    assert module._source_bootstrap_is_fresh(project_root, first_core) is True
    assert module._source_bootstrap_is_fresh(project_root, second_core) is False


def test_ensure_sidecar_skips_source_bootstrap_when_stamp_is_fresh(tmp_path: Path, monkeypatch):
    module = _load_analysis_module()
    project_root = tmp_path / "page_project"
    (project_root / ".venv" / "bin").mkdir(parents=True)
    (project_root / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
    (project_root / "pyproject.toml").write_text("[project]\nname='page-project'\n", encoding="utf-8")
    view_path = project_root / "src" / "view_demo.py"
    view_path.parent.mkdir()
    view_path.write_text("", encoding="utf-8")

    core_root = tmp_path / "core" / "agi-env"
    env_package = core_root / "src" / "agi_env"
    env_package.mkdir(parents=True)
    (core_root / "pyproject.toml").write_text("[project]\nname='agi-env'\n", encoding="utf-8")
    module._write_page_sync_stamp(project_root)
    module._write_source_bootstrap_stamp(project_root, core_root)

    commands: list[tuple[object, str]] = []
    port_checks = iter([False, True])

    class _FakeProcess:
        returncode = None

        def wait(self):
            return 0

        def poll(self):
            return None

    fake_logger = SimpleNamespace(
        info=lambda *_args, **_kwargs: None,
        warning=lambda *_args, **_kwargs: None,
        error=lambda *_args, **_kwargs: None,
    )
    fake_env = SimpleNamespace(
        envars={},
        uv="uv --quiet",
        is_source_env=True,
        env_pck=env_package,
        AGILAB_LOG_ABS=tmp_path,
        logger=fake_logger,
    )
    fake_st = SimpleNamespace(session_state={"env": fake_env})

    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module, "_is_port_open", lambda _port: next(port_checks))

    def _fake_exec_bg(_env, cmd, cwd: str, process_env=None):
        commands.append((cmd, cwd))
        return _FakeProcess()

    monkeypatch.setattr(module, "exec_bg", _fake_exec_bg)

    assert module._ensure_sidecar("view-key", view_path, 8765, "flight_telemetry_project") is True

    assert len(commands) == 1
    command, cwd = commands[0]
    assert isinstance(command, list)
    assert cwd == str(project_root.resolve())
    assert "streamlit" in command
    assert "run" in command
    assert str(view_path) in command
    assert "--active-app" in command
    assert "flight_telemetry_project" in command
    assert "sync" not in command
    assert "ensurepip" not in command
    assert "pip" not in command
    assert not any("'" in part for part in command)


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


def test_migrate_legacy_flight_analysis_page_config_keeps_network_available():
    module = _load_analysis_module()
    cfg = {
        "pages": {
            "default_view": "view_maps_network",
            "view_module": ["view_maps_network", "custom_view", "custom_view"],
        }
    }

    changed = module._migrate_legacy_analysis_page_config("flight_telemetry_project", cfg)

    assert changed is True
    assert cfg["pages"]["default_view"] == "view_maps"
    assert cfg["pages"]["view_module"] == [
        "view_maps",
        "view_maps_network",
        "custom_view",
    ]
    assert "excluded_views" not in cfg["pages"]


def test_migrate_legacy_flight_analysis_page_config_unhides_network_page():
    module = _load_analysis_module()
    cfg = {
        "pages": {
            "default_view": "view_maps",
            "view_module": ["view_maps"],
            "excluded_views": ["view_maps_network", "custom_hidden"],
        }
    }

    changed = module._migrate_legacy_analysis_page_config("flight_telemetry_project", cfg)

    assert changed is True
    assert cfg["pages"]["default_view"] == "view_maps"
    assert cfg["pages"]["view_module"] == ["view_maps", "view_maps_network"]
    assert cfg["pages"]["excluded_views"] == ["custom_hidden"]


def test_migrate_legacy_analysis_page_config_leaves_network_apps_unchanged():
    module = _load_analysis_module()
    cfg = {
        "pages": {
            "default_view": "view_maps_network",
            "view_module": ["view_queue_resilience", "view_maps_network"],
        }
    }

    changed = module._migrate_legacy_analysis_page_config("uav_queue_project", cfg)

    assert changed is False
    assert cfg["pages"]["default_view"] == "view_maps_network"
    assert cfg["pages"]["view_module"] == ["view_queue_resilience", "view_maps_network"]


def test_migrate_legacy_analysis_page_config_preserves_custom_flight_defaults():
    module = _load_analysis_module()
    cfg = {
        "pages": {
            "default_view": "view_default",
            "view_module": [],
        }
    }

    changed = module._migrate_legacy_analysis_page_config("flight_telemetry_project", cfg)

    assert changed is False
    assert cfg["pages"] == {"default_view": "view_default", "view_module": []}


def test_configured_view_options_restricts_to_declared_available_views(tmp_path: Path):
    module = _load_analysis_module()
    view_maps = tmp_path / "view_maps.py"
    view_maps_network = tmp_path / "view_maps_network.py"

    options = module._configured_view_options(
        ["view_maps", "view_maps_network", "missing"],
        ["view_maps", "view_maps_network", "view_training_analysis"],
        {"view_maps": view_maps, "view_maps_network": view_maps_network},
    )

    assert options == ["view_maps", "view_maps_network"]


def test_analysis_sidebar_view_url_encodes_project_and_path(tmp_path: Path):
    module = _load_analysis_module()
    view_path = tmp_path / "view maps.py"

    url = module._analysis_sidebar_view_url("flight_telemetry_project", view_path)

    assert url.startswith("?")
    assert "active_app=flight_telemetry_project" in url
    assert "current_page=" in url
    assert "view+maps.py" in url or "view%20maps.py" in url


def test_excluded_view_options_normalizes_configured_names():
    module = _load_analysis_module()
    cfg = {"pages": {"excluded_views": [" view_maps_network ", "", 42]}}

    assert module._excluded_view_options(cfg) == {"view_maps_network"}


def test_page_apps_path_prefers_agilab_apps_over_legacy_src_apps(tmp_path: Path):
    module = _load_analysis_module()
    page_file = tmp_path / "src" / "agilab" / "pages" / "4_ANALYSIS.py"
    page_file.parent.mkdir(parents=True)
    page_file.write_text("", encoding="utf-8")
    legacy_apps = tmp_path / "src" / "apps"
    legacy_apps.mkdir(parents=True)
    bundled_apps = tmp_path / "src" / "agilab" / "apps"
    bundled_apps.mkdir(parents=True)

    assert module._page_apps_path(page_file) == bundled_apps.resolve()


def test_resolve_app_path_accepts_builtin_project_name(tmp_path: Path):
    module = _load_analysis_module()
    apps_path = tmp_path / "apps"
    flight_telemetry_project = apps_path / "builtin" / "flight_telemetry_project"
    flight_telemetry_project.mkdir(parents=True)

    assert module._resolve_app_path(apps_path, "flight_telemetry_project") == flight_telemetry_project.resolve()


def test_default_app_path_prefers_builtin_flight_telemetry_project(tmp_path: Path):
    module = _load_analysis_module()
    apps_path = tmp_path / "apps"
    generic_project = apps_path / "alpha_project"
    flight_telemetry_project = apps_path / "builtin" / "flight_telemetry_project"
    generic_project.mkdir(parents=True)
    flight_telemetry_project.mkdir(parents=True)

    assert module._default_app_path(apps_path) == flight_telemetry_project.resolve()


def test_initialize_analysis_env_uses_builtin_flight_for_query_shorthand(
    tmp_path: Path,
    monkeypatch,
):
    module = _load_analysis_module()
    apps_path = tmp_path / "apps"
    flight_telemetry_project = apps_path / "builtin" / "flight_telemetry_project"
    flight_telemetry_project.mkdir(parents=True)
    stored_apps: list[Path] = []

    class FakeAgiEnv:
        def __init__(self, *, apps_path: Path, app: str, verbose: int):
            self.apps_path = apps_path
            self.app = app
            self.verbose = verbose
            self.active_app = apps_path / "builtin" / app
            self.is_source_env = True
            self.is_worker_env = False

    fake_st = SimpleNamespace(
        session_state={},
        error=lambda message: (_ for _ in ()).throw(AssertionError(message)),
        stop=lambda: (_ for _ in ()).throw(AssertionError("st.stop should not be called")),
    )

    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module, "AgiEnv", FakeAgiEnv)
    monkeypatch.setattr(module, "_page_apps_path", lambda: apps_path)
    monkeypatch.setattr(module, "load_last_active_app", lambda: None)
    monkeypatch.setattr(module, "store_last_active_app", stored_apps.append)

    env = module._initialize_analysis_env("flight_telemetry_project")

    assert env.apps_path == apps_path.resolve()
    assert env.app == "flight_telemetry_project"
    assert fake_st.session_state["apps_path"] == str(apps_path.resolve())
    assert fake_st.session_state["app"] == "flight_telemetry_project"
    assert stored_apps == [flight_telemetry_project.resolve()]


def test_initialize_analysis_env_defaults_to_builtin_flight_telemetry_project(
    tmp_path: Path,
    monkeypatch,
):
    module = _load_analysis_module()
    apps_path = tmp_path / "apps"
    flight_telemetry_project = apps_path / "builtin" / "flight_telemetry_project"
    flight_telemetry_project.mkdir(parents=True)

    class FakeAgiEnv:
        def __init__(self, *, apps_path: Path, app: str, verbose: int):
            self.apps_path = apps_path
            self.app = app
            self.verbose = verbose
            self.active_app = apps_path / "builtin" / app
            self.is_source_env = True
            self.is_worker_env = False

    fake_st = SimpleNamespace(
        session_state={},
        error=lambda message: (_ for _ in ()).throw(AssertionError(message)),
        stop=lambda: (_ for _ in ()).throw(AssertionError("st.stop should not be called")),
    )

    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module, "AgiEnv", FakeAgiEnv)
    monkeypatch.setattr(module, "_page_apps_path", lambda: apps_path)
    monkeypatch.setattr(module, "load_last_active_app", lambda: None)
    monkeypatch.setattr(module, "store_last_active_app", lambda _path: None)

    env = module._initialize_analysis_env(None)

    assert env.apps_path == apps_path.resolve()
    assert env.app == "flight_telemetry_project"


def test_builtin_flight_telemetry_project_defaults_to_view_maps_and_enables_network_page():
    settings_path = Path("src/agilab/apps/builtin/flight_telemetry_project/src/app_settings.toml")
    cfg = _load_analysis_module()._read_config(settings_path)

    assert cfg["pages"]["default_view"] == "view_maps"
    assert cfg["pages"]["view_module"] == ["view_maps", "view_maps_network"]
    assert cfg["pages"].get("excluded_views", []) == []


def test_analysis_page_state_defaults_flight_to_view_maps_and_enables_network(tmp_path: Path):
    state_module = _load_analysis_state_module()
    view_maps = tmp_path / "view_maps.py"
    view_maps_network = tmp_path / "view_maps_network.py"
    view_barycentric = tmp_path / "view_barycentric.py"

    state = state_module.build_analysis_view_selection_state(
        pages_cfg={
            "default_view": "view_maps",
            "view_module": ["view_maps", "view_maps_network"],
        },
        current_page=None,
        configured_views=["view_maps", "view_maps_network"],
        resolved_pages={
            "view_maps": view_maps,
            "view_maps_network": view_maps_network,
            "view_barycentric": view_barycentric,
        },
        custom_view_lookup={},
    )

    assert state.view_names == ("view_barycentric", "view_maps", "view_maps_network")
    assert state.default_view_name == "view_maps"
    assert state.default_view_names == ("view_maps",)
    assert state.widget_selection == ("view_maps", "view_maps_network")
    assert state.selected_views == ("view_maps", "view_maps_network")
    assert state.config_view_module == ("view_maps", "view_maps_network")
    assert state.default_route_path is None


def test_analysis_page_state_sanitizes_stale_session_selection_before_widget(tmp_path: Path):
    state_module = _load_analysis_state_module()
    view_maps = tmp_path / "view_maps.py"
    view_maps_network = tmp_path / "view_maps_network.py"

    state = state_module.build_analysis_view_selection_state(
        pages_cfg={
            "default_view": "view_maps",
            "excluded_views": ["view_maps_network"],
        },
        current_page=None,
        configured_views=[],
        resolved_pages={
            "view_maps": view_maps,
            "view_maps_network": view_maps_network,
        },
        custom_view_lookup={},
        session_selection=["view_maps_network", "missing"],
        has_session_selection=True,
    )

    assert state.view_names == ("view_maps",)
    assert state.widget_selection == ("view_maps",)
    assert state.default_route_path is None


def test_analysis_page_state_supports_multiple_default_views(tmp_path: Path):
    state_module = _load_analysis_state_module()
    view_maps = tmp_path / "view_maps.py"
    view_barycentric = tmp_path / "view_barycentric.py"

    state = state_module.build_analysis_view_selection_state(
        pages_cfg={
            "default_views": ["view_maps", "view_barycentric"],
            "view_module": [],
        },
        current_page=None,
        configured_views=[],
        resolved_pages={
            "view_maps": view_maps,
            "view_barycentric": view_barycentric,
        },
        custom_view_lookup={},
    )

    assert state.default_view_name == "view_maps"
    assert state.default_view_names == ("view_maps", "view_barycentric")
    assert state.widget_selection == ("view_maps", "view_barycentric")
    assert state.config_view_module == ("view_maps", "view_barycentric")
    assert state.default_route_path is None


def test_analysis_page_state_keeps_custom_selection_as_resolved_config_path(tmp_path: Path):
    state_module = _load_analysis_state_module()
    custom_view = tmp_path / "custom_view.py"
    custom_key = str(custom_view)

    state = state_module.build_analysis_view_selection_state(
        pages_cfg={},
        current_page="main",
        configured_views=[],
        resolved_pages={},
        custom_view_lookup={custom_key: custom_view},
        session_selection=[custom_key],
        has_session_selection=True,
    )

    assert state.view_names == (custom_key,)
    assert state.selected_views == (custom_key,)
    assert state.config_view_module == (str(custom_view.resolve()),)
    assert state.default_route_path is None


def test_analysis_page_state_uses_default_only_before_explicit_session_selection(tmp_path: Path):
    state_module = _load_analysis_state_module()
    default_view = tmp_path / "view_barycentric.py"

    initial_state = state_module.build_analysis_view_selection_state(
        pages_cfg={"default_view": "view_barycentric", "view_module": []},
        current_page="main",
        configured_views=[],
        resolved_pages={"view_barycentric": default_view},
        custom_view_lookup={},
    )
    explicit_state = state_module.build_analysis_view_selection_state(
        pages_cfg={"default_view": "view_barycentric", "view_module": []},
        current_page="main",
        configured_views=[],
        resolved_pages={"view_barycentric": default_view},
        custom_view_lookup={},
        session_selection=[],
        has_session_selection=True,
    )

    assert initial_state.config_view_module == ("view_barycentric",)
    assert explicit_state.config_view_module == ()


def test_analysis_page_state_restricts_to_configured_normalized_views(tmp_path: Path):
    state_module = _load_analysis_state_module()
    view_maps = tmp_path / "view_maps.py"
    view_network = tmp_path / "view_maps_network.py"

    state = state_module.build_analysis_view_selection_state(
        pages_cfg={
            "restrict_to_view_module": True,
            "default_views": ["!! view_maps", "view_maps", "missing_view"],
        },
        current_page=None,
        configured_views=["?? view_maps", "view_maps", "view_maps_network"],
        resolved_pages={
            "view_maps": view_maps,
            "view_maps_network": view_network,
        },
        custom_view_lookup={},
    )

    assert state.view_names == ("view_maps", "view_maps_network")
    assert state.default_view_names == ("view_maps",)
    assert state.widget_selection == ("view_maps", "view_maps_network")
    assert state.config_view_module == ("view_maps", "view_maps_network")


def test_analysis_page_state_falls_back_to_all_views_when_restrict_config_is_empty(tmp_path: Path):
    state_module = _load_analysis_state_module()
    view_maps = tmp_path / "view_maps.py"
    custom_view = tmp_path / "custom.py"
    custom_key = str(custom_view)

    state = state_module.build_analysis_view_selection_state(
        pages_cfg={"restrict_to_view_module": True},
        current_page=None,
        configured_views=["missing_view"],
        resolved_pages={"view_maps": view_maps},
        custom_view_lookup={custom_key: custom_view},
    )

    assert state.view_names == (custom_key, "view_maps")
    assert state.widget_selection == ()


def test_analysis_page_state_handles_invalid_and_unresolved_defaults(tmp_path: Path):
    state_module = _load_analysis_state_module()

    assert state_module.normalize_view_name(None) == ""
    assert state_module.normalize_view_name("") == ""
    assert state_module._resolve_default_view(42, (), {}, {}) == (None, None)
    assert state_module._resolve_default_view("   ", (), {}, {}) == (None, None)
    assert state_module._resolve_default_view("missing_path", ("missing_path",), {}, {}) == (None, None)


def test_create_analysis_page_bundle_writes_blank_template(tmp_path: Path, monkeypatch):
    module = _load_analysis_module()

    entrypoint = module._create_analysis_page_bundle(tmp_path, "demo_view", "")

    assert entrypoint == tmp_path / "demo_view" / "src" / "demo_view" / "demo_view.py"
    assert entrypoint.exists()
    assert (tmp_path / "demo_view" / "README.md").is_file()
    assert (tmp_path / "demo_view" / "src" / "demo_view" / "__init__.py").is_file()

    contract = tomllib.loads((tmp_path / "demo_view" / "agilab.template.toml").read_text(encoding="utf-8"))
    assert contract["entrypoint"] == "src/demo_view/demo_view.py"
    assert "src/demo_view/view_demo.py" not in (tmp_path / "demo_view" / "agilab.template.toml").read_text(
        encoding="utf-8"
    )

    pyproject = tomllib.loads((tmp_path / "demo_view" / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["name"] == "view-demo-view"
    dependencies = pyproject["project"]["dependencies"]
    assert "streamlit>=1.56,<1.57" in dependencies
    assert any(dependency.startswith("agi-env>=") for dependency in dependencies)

    template_text = entrypoint.read_text(encoding="utf-8")
    assert "except (ImportError, ModuleNotFoundError, OSError) as exc" in template_text
    assert 'PAGE_TITLE = "demo_view"' in template_text
    assert "src/view_demo/view_demo.py" not in template_text
    assert 'get_docs_menu_items(html_file="explore-help.html")' in template_text

    fake_streamlit = _FakeAnalysisTemplateStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)
    spec = importlib.util.spec_from_file_location("generated_demo_view", entrypoint)
    assert spec is not None and spec.loader is not None
    generated_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generated_module)

    generated_module.main()

    assert ("title", "demo_view") in fake_streamlit.events
    assert any(event == "info" and "AGILAB Analysis" in str(value) for event, value in fake_streamlit.events)


def test_clone_source_label_falls_back_to_absolute_path(tmp_path: Path):
    module = _load_analysis_module()
    page_file = tmp_path / "view_demo.py"
    page_file.write_text("", encoding="utf-8")
    foreign_root = tmp_path / "other_root"
    foreign_root.mkdir()

    label = module._clone_source_label(page_file, foreign_root)

    assert label == f"view_demo ({page_file})"


def test_analysis_view_profile_describes_known_and_custom_views():
    module = _load_analysis_module()

    assert module._analysis_view_profile("view_maps")[0] == "Map evidence"
    assert module._analysis_view_profile("/tmp/custom_page.py")[0] == "Custom analysis"


def test_scan_analysis_artifacts_counts_supported_outputs(tmp_path: Path):
    module = _load_analysis_module()
    data_root = tmp_path / "export" / "flight"
    (data_root / "dataset").mkdir(parents=True)
    (data_root / "dataset" / "tracks.csv").write_text("x\n", encoding="utf-8")
    (data_root / "dataset" / "summary.json").write_text("{}\n", encoding="utf-8")
    (data_root / "dataset" / "notes.txt").write_text("ignore\n", encoding="utf-8")

    summary = module._scan_analysis_artifacts(data_root)

    assert summary["count"] == 2
    assert summary["examples"] == ["dataset/summary.json", "dataset/tracks.csv"]
    assert summary["exists"] is True


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


def test_is_hosted_analysis_runtime_uses_process_environment(monkeypatch):
    module = _load_analysis_module()

    monkeypatch.setenv("SPACE_ID", "user/demo")

    assert module._is_hosted_analysis_runtime(SimpleNamespace(envars={})) is True


def test_render_view_page_uses_inline_rendering_in_hf_space(tmp_path: Path, monkeypatch):
    module = _load_analysis_module()
    view_path = tmp_path / "view_demo.py"
    view_path.write_text("", encoding="utf-8")
    inline_calls: list[tuple[Path, str]] = []

    class _Column:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    fake_logger = SimpleNamespace(info=lambda *_args, **_kwargs: None, error=lambda *_args, **_kwargs: None)
    fake_env = SimpleNamespace(
        apps_path=None,
        target=None,
        app=None,
        active_app="",
        AGILAB_LOG_ABS=tmp_path,
        envars={},
        logger=fake_logger,
    )
    fake_st = SimpleNamespace(
        session_state={"env": fake_env},
        columns=lambda _spec: [_Column(), _Column(), _Column()],
        button=lambda *_args, **_kwargs: False,
        subheader=lambda *_args, **_kwargs: None,
        markdown=lambda *_args, **_kwargs: None,
    )

    async def _capture_inline(path: Path, active_app: str) -> None:
        inline_calls.append((path, active_app))

    monkeypatch.setenv("SPACE_ID", "user/demo")
    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module, "_render_view_page_inline", _capture_inline)
    monkeypatch.setattr(
        module,
        "_ensure_sidecar",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("HF Space must not launch localhost sidecar")),
    )

    asyncio.run(module.render_view_page(view_path))

    assert inline_calls == [(view_path, "")]


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

    active_app = tmp_path / "flight_telemetry_project"
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
