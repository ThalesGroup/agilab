from __future__ import annotations

import importlib.util
import os
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


def test_clear_agilab_core_modules_removes_prefixed_modules_and_invalidates(monkeypatch):
    cleared = []
    monkeypatch.setattr(colab_support.importlib, "invalidate_caches", lambda: cleared.append("invalidate"))
    monkeypatch.setitem(sys.modules, "agi_cluster", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "agi_cluster.agi_distributor", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "agi_env", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "agi_env.runtime_bootstrap_support", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "agi_node", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "agi_node.agi_dispatcher", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "other.module", SimpleNamespace())

    colab_support.clear_agilab_core_modules()

    assert "agi_cluster" not in sys.modules
    assert "agi_cluster.agi_distributor" not in sys.modules
    assert "agi_env" not in sys.modules
    assert "agi_env.runtime_bootstrap_support" not in sys.modules
    assert "agi_node" not in sys.modules
    assert "agi_node.agi_dispatcher" not in sys.modules
    assert "other.module" in sys.modules
    assert cleared == ["invalidate"]


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


def test_worker_env_ready_returns_false_when_missing(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(colab_support.Path, "home", staticmethod(lambda: tmp_path))

    assert colab_support.worker_env_ready(SimpleNamespace(target="demo", app="demo")) is False


def test_worker_env_ready_checks_agi_imports(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(colab_support.Path, "home", staticmethod(lambda: tmp_path))
    worker_venv = tmp_path / "wenv" / "demo_worker" / ".venv"
    worker_venv.mkdir(parents=True, exist_ok=True)
    calls: list[list[str]] = []

    def _fake_run(cmd, **_kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0)

    ready = colab_support.worker_env_ready(
        SimpleNamespace(target="demo", app="demo", pyvers_worker="3.13"),
        run_fn=_fake_run,
    )

    assert ready is True
    assert calls == [[
        "uv",
        "--quiet",
        "run",
        "--no-sync",
        "--project",
        str(worker_venv.parent),
        "--python",
        "3.13",
        "python",
        "-c",
        "import agi_env, agi_node",
    ]]


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


def test_bootstrap_installed_colab_uses_explicit_apps_path(monkeypatch, tmp_path: Path):
    calls: list[object] = []
    fake_agi = object()
    fake_env_cls = type("FakeAgiEnv", (), {})
    fake_builtin_root = tmp_path / "apps" / "builtin"
    fake_builtin_root.mkdir(parents=True)

    fake_cluster_pkg = SimpleNamespace(__path__=[])
    fake_distributor = SimpleNamespace(AGI=fake_agi)
    fake_env_module = SimpleNamespace(AgiEnv=fake_env_cls)

    monkeypatch.setitem(sys.modules, "agi_cluster", fake_cluster_pkg)
    monkeypatch.setitem(sys.modules, "agi_cluster.agi_distributor", fake_distributor)
    monkeypatch.setitem(sys.modules, "agi_env", fake_env_module)
    monkeypatch.setattr(colab_support, "configure_local_notebook_environ", lambda *args, **kwargs: calls.append(("configure", kwargs)))
    monkeypatch.setattr(colab_support, "ensure_pathlib_unsupported_operation", lambda: calls.append("pathlib"))
    monkeypatch.setattr(colab_support, "clear_agilab_core_modules", lambda *args, **kwargs: calls.append(("clear", args, kwargs)))

    ctx = colab_support.bootstrap_installed_colab(tmp_path / "apps")

    assert ctx.repo_root is None
    assert ctx.apps_path == tmp_path / "apps"
    assert ctx.builtin_root == fake_builtin_root
    assert ctx.AGI is fake_agi
    assert ctx.AgiEnv is fake_env_cls
    assert calls[0] == ("configure", {"source_env": False})
    assert "pathlib" in calls
    assert any(call[0] == "clear" for call in calls if isinstance(call, tuple))


def test_bootstrap_colab_core_prepares_paths_and_installs_core_packages(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "agilab"
    core_env = repo_root / "src" / "agilab" / "core" / "agi-env"
    core_node = repo_root / "src" / "agilab" / "core" / "agi-node"
    core_cluster = repo_root / "src" / "agilab" / "core" / "agi-cluster"
    apps_path = repo_root / "src" / "agilab" / "apps"
    builtin_root = apps_path / "builtin"
    for path in (
        core_env / "src",
        core_node / "src" / "agi_node",
        core_cluster / "src" / "agi_cluster",
        builtin_root,
    ):
        path.mkdir(parents=True, exist_ok=True)

    fake_agi = object()
    fake_env_cls = type("FakeAgiEnv", (), {})
    fake_cluster_pkg = SimpleNamespace(__path__=[])
    fake_distributor = SimpleNamespace(AGI=fake_agi)
    fake_env_module = SimpleNamespace(AgiEnv=fake_env_cls)
    fake_node_module = SimpleNamespace()
    subprocess_calls: list[list[str]] = []

    monkeypatch.setitem(sys.modules, "agi_cluster", fake_cluster_pkg)
    monkeypatch.setitem(sys.modules, "agi_cluster.agi_distributor", fake_distributor)
    monkeypatch.setitem(sys.modules, "agi_env", fake_env_module)
    monkeypatch.setitem(sys.modules, "agi_node", fake_node_module)
    monkeypatch.setattr(colab_support, "configure_local_notebook_environ", lambda *args, **kwargs: None)
    monkeypatch.setattr(colab_support, "ensure_pathlib_unsupported_operation", lambda: None)
    monkeypatch.setattr(colab_support, "clear_agilab_core_modules", lambda *args, **kwargs: None)
    monkeypatch.setattr(colab_support.subprocess, "run", lambda cmd, check=True: subprocess_calls.append(cmd))
    monkeypatch.setattr(colab_support, "prepend_sys_path_entries", colab_support.prepend_sys_path_entries)
    monkeypatch.setenv("PYTHONPATH", "existing_path")
    monkeypatch.setattr(colab_support.sys, "path", [])

    ctx = colab_support.bootstrap_colab_core(repo_root)

    assert ctx.repo_root == repo_root
    assert ctx.apps_path == apps_path
    assert ctx.builtin_root == builtin_root
    assert ctx.AGI is fake_agi
    assert ctx.AgiEnv is fake_env_cls
    assert str(repo_root / "src") in colab_support.sys.path
    assert str(core_node / "src") in os.environ["PYTHONPATH"]
    assert os.environ["PYTHONPATH"].endswith("existing_path")

    env = SimpleNamespace(active_app=repo_root / "src" / "agilab" / "apps" / "builtin" / "mycode_project")
    ctx.ensure_env_core_packages(env)
    ctx.ensure_env_core_packages(env)

    assert len(subprocess_calls) == 1
    assert subprocess_calls[0] == [
        "uv",
        "--preview-features",
        "extra-build-dependencies",
        "pip",
        "install",
        "--project",
        str(env.active_app),
        "-e",
        str(core_env),
        "-e",
        str(core_node),
        "-e",
        str(core_cluster),
    ]


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

    monkeypatch.setattr(colab_support, "worker_env_ready", lambda _app_env: True)

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


@pytest.mark.asyncio
async def test_install_if_needed_reinstalls_broken_existing_worker(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(colab_support.Path, "home", staticmethod(lambda: tmp_path))
    existing = tmp_path / "wenv" / "demo_worker" / ".venv"
    existing.mkdir(parents=True, exist_ok=True)
    (existing.parent / "stale.txt").write_text("x", encoding="utf-8")
    calls: list[tuple] = []
    messages: list[str] = []
    env = SimpleNamespace(target="demo", app="demo")

    class _AGI:
        @staticmethod
        async def install(*args, **kwargs):
            calls.append((args, kwargs))

    monkeypatch.setattr(colab_support, "worker_env_ready", lambda _app_env: False)

    installed = await colab_support.install_if_needed(
        _AGI,
        env,
        print_fn=messages.append,
    )

    assert installed is True
    assert messages == ["Reinstalling worker for demo..."]
    assert calls == [((env,), {"scheduler": "127.0.0.1", "workers": {"127.0.0.1": 1}, "modes_enabled": 0})]
    assert not existing.parent.exists()
