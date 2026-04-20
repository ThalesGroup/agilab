from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "agilab" / "notebook_colab_support.py"
MODULE_SPEC = importlib.util.spec_from_file_location("agilab.notebook_colab_support", MODULE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
colab_support = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = colab_support
MODULE_SPEC.loader.exec_module(colab_support)


def test_ensure_pathlib_unsupported_operation_injects_fallback():
    fake_pathlib = SimpleNamespace()

    colab_support.ensure_pathlib_unsupported_operation(fake_pathlib)

    assert fake_pathlib.UnsupportedOperation is colab_support.IOUnsupportedOperation


def test_configure_local_notebook_environ_forces_local_mode():
    environ = {
        "IS_SOURCE_ENV": "0",
        "IS_WORKER_ENV": "1",
        "AGI_CLUSTER_ENABLED": "1",
    }

    colab_support.configure_local_notebook_environ(environ)

    assert environ["IS_SOURCE_ENV"] == "1"
    assert environ["AGI_CLUSTER_ENABLED"] == "0"
    assert "IS_WORKER_ENV" not in environ


def test_configure_local_notebook_environ_can_clear_source_mode():
    environ = {
        "IS_SOURCE_ENV": "1",
        "IS_WORKER_ENV": "1",
        "AGI_CLUSTER_ENABLED": "1",
    }

    colab_support.configure_local_notebook_environ(environ, source_env=False)

    assert "IS_SOURCE_ENV" not in environ
    assert environ["AGI_CLUSTER_ENABLED"] == "0"
    assert "IS_WORKER_ENV" not in environ


def test_prepend_sys_path_entries_deduplicates(monkeypatch, tmp_path: Path):
    existing = str(tmp_path / "existing")
    fresh = tmp_path / "fresh"
    monkeypatch.setattr(colab_support.sys, "path", [existing])

    colab_support.prepend_sys_path_entries([fresh, Path(existing)])

    assert colab_support.sys.path[0] == str(fresh)
    assert colab_support.sys.path.count(existing) == 1


def test_worker_venv_path_uses_target_name(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(colab_support.Path, "home", staticmethod(lambda: tmp_path))

    path = colab_support.worker_venv_path(SimpleNamespace(target="demo", app="demo"))

    assert path == tmp_path / "wenv" / "demo_worker" / ".venv"


def test_resolve_builtin_root_handles_builtin_and_apps_roots(tmp_path: Path):
    builtin_root = tmp_path / "apps" / "builtin"
    builtin_root.mkdir(parents=True)

    assert colab_support.resolve_builtin_root(builtin_root) == builtin_root
    assert colab_support.resolve_builtin_root(builtin_root.parent) == builtin_root
    assert colab_support.resolve_builtin_root(tmp_path / "missing") is None


def test_installed_apps_path_resolves_from_agilab_module(monkeypatch, tmp_path: Path):
    fake_agilab = SimpleNamespace(__file__=str(tmp_path / "site-packages" / "agilab" / "__init__.py"))
    monkeypatch.setitem(sys.modules, "agilab", fake_agilab)

    assert colab_support.installed_apps_path() == tmp_path / "site-packages" / "agilab" / "apps"


def test_ensure_env_core_packages_uses_resolved_active_app():
    calls: list[Path] = []
    env = SimpleNamespace(active_app=Path("/repo/src/agilab/apps/builtin/mycode_project"))

    colab_support.ensure_env_core_packages(lambda app_root: calls.append(app_root), env)

    assert calls == [Path("/repo/src/agilab/apps/builtin/mycode_project")]


@pytest.mark.asyncio
async def test_install_if_needed_skips_existing_worker(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(colab_support.Path, "home", staticmethod(lambda: tmp_path))
    existing = tmp_path / "wenv" / "demo_worker" / ".venv"
    existing.mkdir(parents=True, exist_ok=True)
    calls: list[tuple] = []

    class _AGI:
        @staticmethod
        async def install(*args, **kwargs):
            calls.append((args, kwargs))

    installed = await colab_support.install_if_needed(
        _AGI,
        SimpleNamespace(target="demo", app="demo"),
    )

    assert installed is False
    assert calls == []


@pytest.mark.asyncio
async def test_install_if_needed_runs_install_when_worker_missing(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(colab_support.Path, "home", staticmethod(lambda: tmp_path))
    calls: list[tuple] = []
    messages: list[str] = []
    env = SimpleNamespace(target="demo", app="demo")

    class _AGI:
        @staticmethod
        async def install(*args, **kwargs):
            calls.append((args, kwargs))

    installed = await colab_support.install_if_needed(
        _AGI,
        env,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
        modes_enabled=0,
        print_fn=messages.append,
    )

    assert installed is True
    assert messages == ["Installing worker for demo..."]
    assert calls == [((env,), {"scheduler": "127.0.0.1", "workers": {"127.0.0.1": 1}, "modes_enabled": 0})]
