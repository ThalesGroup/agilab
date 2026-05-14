from __future__ import annotations

import getpass
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

import agi_env.worker_runtime_support as worker_runtime_support
from agi_env.worker_runtime_support import configure_worker_runtime


def _dummy_env(tmp_path: Path, *, app_name: str = "demo_project") -> SimpleNamespace:
    active_app = tmp_path / "apps" / app_name
    (active_app / "src").mkdir(parents=True, exist_ok=True)
    agi_root = tmp_path / "site-packages" / "agilab"
    node_pck = agi_root / "core" / "agi-node" / "src" / "agi_node"
    node_pck.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        app=app_name,
        active_app=active_app,
        builtin_apps_path=None,
        agilab_pck=agi_root,
        node_pck=node_pck,
        is_worker_env=False,
        app_src=active_app / "src",
        uv="uv",
        _collect_pythonpath_entries=lambda: ["PYTHONPATH-entry"],
        _configure_pythonpath=lambda entries: setattr(sys.modules[__name__], "_last_pythonpath_entries", entries),
        _ensure_repository_app_link=lambda: False,
        copy_existing_projects=lambda *_args, **_kwargs: None,
        has_agilab_anywhere_under_home=lambda _path: False,
    )


def test_configure_worker_runtime_resolves_builtin_worker_copy(tmp_path: Path):
    env = _dummy_env(tmp_path, app_name="flight_telemetry_project")
    builtin_root = tmp_path / "apps" / "builtin"
    env.builtin_apps_path = builtin_root
    builtin_app = builtin_root / "flight_telemetry_project"
    (builtin_app / "src" / "flight").mkdir(parents=True, exist_ok=True)
    (builtin_app / "src" / "flight_worker").mkdir(parents=True, exist_ok=True)
    (builtin_app / "src" / "flight_worker" / "flight_worker.py").write_text("class FlightWorker:\n    pass\n", encoding="utf-8")

    configure_worker_runtime(
        env,
        target="flight",
        home_abs=tmp_path / "home",
        apps_path=tmp_path / "apps",
        apps_root=tmp_path / "apps",
        envars={},
        requested_active_app=env.active_app,
        ensure_dir_fn=lambda path: Path(path).mkdir(parents=True, exist_ok=True) or Path(path),
        normalize_path_fn=str,
        parse_int_env_value_fn=lambda *_args, **_kwargs: 0,
        python_supports_free_threading_fn=lambda: False,
        logger=mock.Mock(),
        sys_path=[],
    )

    assert env.active_app == builtin_app.resolve()
    assert env.worker_path == (builtin_app / "src" / "flight_worker" / "flight_worker.py").resolve()
    assert env.manager_path == builtin_app / "src" / "flight" / "flight.py"


def test_configure_worker_runtime_prefers_packaged_worker_sources(tmp_path: Path):
    env = _dummy_env(tmp_path)
    home_abs = tmp_path / "home"
    wenv_worker = home_abs / "wenv" / "demo_worker" / "src" / "demo_worker"
    wenv_worker.mkdir(parents=True, exist_ok=True)
    (wenv_worker / "demo_worker.py").write_text("class DemoWorker:\n    pass\n", encoding="utf-8")
    (wenv_worker / "pyproject.toml").write_text("[project]\nname='demo-worker'\n", encoding="utf-8")

    configure_worker_runtime(
        env,
        target="demo",
        home_abs=home_abs,
        apps_path=tmp_path / "apps",
        apps_root=tmp_path / "apps",
        envars={},
        requested_active_app=env.active_app,
        ensure_dir_fn=lambda path: Path(path).mkdir(parents=True, exist_ok=True) or Path(path),
        normalize_path_fn=str,
        parse_int_env_value_fn=lambda *_args, **_kwargs: 0,
        python_supports_free_threading_fn=lambda: False,
        logger=mock.Mock(),
        sys_path=[],
    )

    assert env.app_src == env.wenv_abs / "src"
    assert env.worker_path == wenv_worker / "demo_worker.py"
    assert env.worker_pyproject == wenv_worker / "pyproject.toml"


def test_configure_worker_runtime_copies_packaged_app_when_worker_is_missing(tmp_path: Path):
    env = _dummy_env(tmp_path)
    packaged_app = env.agilab_pck / "apps" / "demo_project"
    (packaged_app / "src" / "demo").mkdir(parents=True, exist_ok=True)
    (packaged_app / "src" / "demo_worker").mkdir(parents=True, exist_ok=True)
    (packaged_app / "src" / "demo_worker" / "demo_worker.py").write_text(
        "class DemoWorker:\n    pass\n",
        encoding="utf-8",
    )

    configure_worker_runtime(
        env,
        target="demo",
        home_abs=tmp_path / "home",
        apps_path=tmp_path / "apps",
        apps_root=tmp_path / "apps",
        envars={},
        requested_active_app=env.active_app,
        ensure_dir_fn=lambda path: Path(path).mkdir(parents=True, exist_ok=True) or Path(path),
        normalize_path_fn=str,
        parse_int_env_value_fn=lambda *_args, **_kwargs: 0,
        python_supports_free_threading_fn=lambda: False,
        logger=mock.Mock(),
        sys_path=[],
    )

    assert (env.active_app / "src" / "demo_worker" / "demo_worker.py").exists()
    assert env.worker_path == env.active_app / "src" / "demo_worker" / "demo_worker.py"


def test_configure_worker_runtime_sets_free_threading_and_clears_distribution_tree(tmp_path: Path):
    env = _dummy_env(tmp_path)
    home_abs = tmp_path / "home"
    worker_dir = home_abs / "wenv" / "demo_worker" / "src" / "demo_worker"
    worker_dir.mkdir(parents=True, exist_ok=True)
    (worker_dir / "demo_worker.py").write_text("class DemoWorker:\n    pass\n", encoding="utf-8")
    (worker_dir / "pyproject.toml").write_text(
        "[project]\nname='demo-worker'\n\n[tool.freethread_info]\nis_app_freethreaded = true\n",
        encoding="utf-8",
    )
    stale_plan = home_abs / "wenv" / "demo_worker" / "distribution_tree.json"
    stale_plan.parent.mkdir(parents=True, exist_ok=True)
    stale_plan.write_text("{}", encoding="utf-8")

    sys_path = []
    pythonpath_entries = []
    env._configure_pythonpath = lambda entries: pythonpath_entries.extend(entries)

    configure_worker_runtime(
        env,
        target="demo",
        home_abs=home_abs,
        apps_path=tmp_path / "apps",
        apps_root=tmp_path / "apps",
        envars={"AGI_PYTHON_FREE_THREADED": "1", "AGI_PYTHON_VERSION": "3.13"},
        requested_active_app=env.active_app,
        ensure_dir_fn=lambda path: Path(path).mkdir(parents=True, exist_ok=True) or Path(path),
        normalize_path_fn=str,
        parse_int_env_value_fn=lambda envs, key, default: int(envs.get(key, default)),
        python_supports_free_threading_fn=lambda: True,
        logger=mock.Mock(),
        sys_path=sys_path,
    )

    assert env.distribution_tree == stale_plan
    assert not stale_plan.exists()
    assert env.uv_worker == "PYTHON_GIL=0 uv"
    assert env.pyvers_worker == "3.13t"
    assert pythonpath_entries == ["PYTHONPATH-entry"]
    assert str(env.dist_abs) in sys_path
    assert str((tmp_path / "apps" / "demo_project" / "src")) in sys_path


def test_configure_worker_runtime_uses_module_sys_path_when_not_provided(tmp_path: Path, monkeypatch):
    env = _dummy_env(tmp_path)
    home_abs = tmp_path / "home"
    worker_dir = home_abs / "wenv" / "demo_worker" / "src" / "demo_worker"
    worker_dir.mkdir(parents=True, exist_ok=True)
    (worker_dir / "demo_worker.py").write_text("class DemoWorker:\n    pass\n", encoding="utf-8")
    (worker_dir / "pyproject.toml").write_text("[project]\nname='demo-worker'\n", encoding="utf-8")

    module_sys_path: list[str] = []
    monkeypatch.setattr(worker_runtime_support.sys, "path", module_sys_path)

    configure_worker_runtime(
        env,
        target="demo",
        home_abs=home_abs,
        apps_path=tmp_path / "apps",
        apps_root=tmp_path / "apps",
        envars={},
        requested_active_app=env.active_app,
        ensure_dir_fn=lambda path: Path(path).mkdir(parents=True, exist_ok=True) or Path(path),
        normalize_path_fn=str,
        parse_int_env_value_fn=lambda *_args, **_kwargs: 0,
        python_supports_free_threading_fn=lambda: False,
        logger=mock.Mock(),
    )

    assert str(env.dist_abs) in module_sys_path


def test_configure_worker_runtime_warns_when_project_worker_copy_fails(tmp_path: Path):
    env = _dummy_env(tmp_path, app_name="demo_worker")
    env.target = "demo"
    apps_root = tmp_path / "apps"
    project_worker_dir = apps_root / "demo_project" / "src" / "demo_worker"
    project_worker_dir.mkdir(parents=True, exist_ok=True)
    logger = mock.Mock()

    configure_worker_runtime(
        env,
        target="demo",
        home_abs=tmp_path / "home",
        apps_path=apps_root,
        apps_root=apps_root,
        envars={},
        requested_active_app=env.active_app,
        ensure_dir_fn=lambda path: Path(path).mkdir(parents=True, exist_ok=True) or Path(path),
        normalize_path_fn=str,
        parse_int_env_value_fn=lambda *_args, **_kwargs: 0,
        python_supports_free_threading_fn=lambda: False,
        logger=logger,
        sys_path=[],
        copytree_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("copy failed")),
    )

    assert logger.warning.called
