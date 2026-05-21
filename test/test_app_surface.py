from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

MODULE_PATH = Path("src/agilab/app_surface.py")


def _load_app_surface_module():
    spec = importlib.util.spec_from_file_location("agilab_app_surface_tests", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_app_surface_project(tmp_path: Path) -> Path:
    app = tmp_path / "demo_project"
    surface = app / "src" / "demo" / "app_surface.py"
    surface.parent.mkdir(parents=True)
    (app / "src" / "app_settings.toml").write_text(
        "\n".join(
            [
                "[app_surface]",
                'title = "Demo Surface"',
                'entrypoint = "demo/app_surface.py"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    surface.write_text(
        "\n".join(
            [
                "def render(*, mode, active_app, env=None, container=None, streamlit=None):",
                "    container.append({",
                "        'mode': mode,",
                "        'active_app': active_app.name,",
                "        'env_app': getattr(env, 'app', None),",
                "    })",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return app


def test_app_surface_resolves_project_local_entrypoint(tmp_path: Path) -> None:
    module = _load_app_surface_module()
    app = _write_app_surface_project(tmp_path)

    assert module.app_surface_config(app) == {
        "title": "Demo Surface",
        "entrypoint": "demo/app_surface.py",
    }
    assert module.configured_app_surface_entrypoint(app) == app / "src" / "demo" / "app_surface.py"


def test_render_app_surface_calls_project_render_hook_and_restores_argv(tmp_path: Path) -> None:
    module = _load_app_surface_module()
    app = _write_app_surface_project(tmp_path)
    events: list[dict[str, object]] = []
    before_argv = list(sys.argv)

    rendered = module.render_app_surface(
        app,
        mode="configure",
        env=SimpleNamespace(app="demo_project"),
        container=events,
    )

    assert rendered is True
    assert events == [
        {
            "mode": "configure",
            "active_app": "demo_project",
            "env_app": "demo_project",
        }
    ]
    assert sys.argv == before_argv
