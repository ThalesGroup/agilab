from __future__ import annotations

import asyncio
import io
import itertools
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agi_node.agi_dispatcher import BaseWorker
from agi_node.agi_dispatcher import base_worker as base_worker_mod
from agi_node.agi_dispatcher import base_worker_execution_support as execution_support


class DummyWorker(BaseWorker):
    def __init__(self):
        super().__init__()
        worker_id = 0
        BaseWorker._worker_id = worker_id
        BaseWorker._insts = {worker_id: self}

    def works(self, *_args, **_kwargs):
        pass


def teardown_function(_fn):
    BaseWorker._worker_id = None
    BaseWorker._worker = None
    BaseWorker._insts = {}
    BaseWorker._env = None
    BaseWorker.env = None


def test_baseworker_execution_wrappers_delegate(monkeypatch):
    calls: dict[str, object] = {}

    async def _fake_run_worker(**kwargs):
        calls["run"] = kwargs
        return "run-result"

    def _fake_initialize_worker(**kwargs):
        calls["new"] = kwargs

    def _fake_collect_worker_info(**kwargs):
        calls["info"] = kwargs
        return {"ok": 1}

    def _fake_build_worker_artifacts(**kwargs):
        calls["build"] = kwargs

    def _fake_execute_worker_plan(**kwargs):
        calls["do_works"] = kwargs
        return "logs"

    monkeypatch.setattr(base_worker_mod.execution_support, "run_worker", _fake_run_worker)
    monkeypatch.setattr(
        base_worker_mod.execution_support,
        "initialize_worker",
        _fake_initialize_worker,
    )
    monkeypatch.setattr(
        base_worker_mod.execution_support,
        "collect_worker_info",
        _fake_collect_worker_info,
    )
    monkeypatch.setattr(
        base_worker_mod.execution_support,
        "build_worker_artifacts",
        _fake_build_worker_artifacts,
    )
    monkeypatch.setattr(
        base_worker_mod.execution_support,
        "execute_worker_plan",
        _fake_execute_worker_plan,
    )

    env = SimpleNamespace(mode2str=lambda mode: f"mode-{mode}")
    BaseWorker.env = env

    assert (
        asyncio.run(
            BaseWorker._run(
                env=None,
                workers={"local": 1},
                mode=0,
                args={"payload": 1},
            )
        )
        == "run-result"
    )
    run_call = calls["run"]
    assert run_call["env"] is env
    assert run_call["workers"] == {"local": 1}
    assert run_call["mode"] == 0
    assert run_call["args"] == {"payload": 1}
    assert callable(run_call["dispatcher_loader"])

    BaseWorker._new(
        env=env,
        app="demo",
        mode=4,
        verbose=2,
        worker_id=3,
        worker="tcp://192.168.20.130:1234",
        args={"alpha": 1},
    )
    new_call = calls["new"]
    assert new_call["env"] is env
    assert new_call["base_worker_cls"] is BaseWorker
    assert new_call["args_namespace_cls"] is base_worker_mod.ArgsNamespace

    BaseWorker._share_path = "clustershare"
    BaseWorker._worker = "tcp://127.0.0.1:8787"
    assert BaseWorker._get_worker_info(1) == {"ok": 1}
    info_call = calls["info"]
    assert info_call["share_path"] == "clustershare"
    assert info_call["worker"] == "tcp://127.0.0.1:8787"

    BaseWorker._build("demo_worker", "/tmp/dask-home", "local-worker", mode=0, verbose=3)
    build_call = calls["build"]
    assert build_call["target_worker"] == "demo_worker"
    assert build_call["dask_home"] == "/tmp/dask-home"
    assert build_call["worker"] == "local-worker"

    BaseWorker._worker_id = 7
    BaseWorker._worker = "local-worker"
    BaseWorker._insts = {7: object()}
    assert BaseWorker._do_works(["p"], ["m"]) == "logs"
    do_works_call = calls["do_works"]
    assert do_works_call["worker_id"] == 7
    assert do_works_call["worker_name"] == "local-worker"


def test_baseworker_do_works_executes_tasks():
    dummy = DummyWorker()
    with patch.object(dummy, "works", return_value=None) as mocked:
        BaseWorker._do_works({}, {})
    mocked.assert_called_once()


def test_new_sets_worker_ids_on_instance(monkeypatch):
    class SpawnedWorker(BaseWorker):
        pass

    captured = {}

    monkeypatch.setattr(
        BaseWorker,
        "_ensure_managed_pc_share_dir",
        staticmethod(lambda env: None),
    )
    monkeypatch.setattr(
        BaseWorker,
        "_load_worker",
        staticmethod(lambda _mode: SpawnedWorker),
    )

    def _fake_start(worker_inst):
        captured["worker_id"] = worker_inst.worker_id
        captured["_worker_id"] = worker_inst._worker_id

    monkeypatch.setattr(BaseWorker, "start", staticmethod(_fake_start))

    env = SimpleNamespace()
    BaseWorker._new(env=env, mode=4, worker_id=3, worker="tcp://192.168.20.130:1234")

    assert captured == {"worker_id": 3, "_worker_id": 3}
    assert BaseWorker._insts[3].worker_id == 3
    assert BaseWorker._insts[3]._worker_id == 3


def test_configure_initialized_worker_sets_runtime_fields():
    class SpawnedWorker:
        pass

    worker_inst = execution_support._configure_initialized_worker(
        mode=4,
        worker_id=3,
        args={"alpha": 1},
        verbose=2,
        load_worker_fn=lambda _mode: SpawnedWorker,
        args_namespace_cls=base_worker_mod.ArgsNamespace,
    )

    assert isinstance(worker_inst, SpawnedWorker)
    assert worker_inst._mode == 4
    assert worker_inst.worker_id == 3
    assert worker_inst._worker_id == 3
    assert worker_inst.verbose == 2
    assert worker_inst.args.alpha == 1


def test_register_initialized_worker_updates_base_worker_state():
    worker_inst = SimpleNamespace()

    execution_support._register_initialized_worker(
        base_worker_cls=BaseWorker,
        worker_id=5,
        worker="tcp://192.168.20.130:1234",
        worker_inst=worker_inst,
        verbose=3,
        started_at=12.5,
    )

    assert BaseWorker.verbose == 3
    assert BaseWorker._insts[5] is worker_inst
    assert BaseWorker._built is False
    assert BaseWorker._worker == "192.168.20.130:1234"
    assert BaseWorker._worker_id == 5
    assert BaseWorker._t0 == 12.5


def test_log_worker_startup_context_reports_prefix_and_worker_origin():
    logged: list[str] = []
    logger = SimpleNamespace(
        info=lambda message, *args: logged.append(str(message % args if args else message))
    )

    execution_support._log_worker_startup_context(
        worker_id=3,
        worker="local-worker",
        file_path="/tmp/worker.py",
        logger_obj=logger,
        sys_module=SimpleNamespace(prefix="/tmp/venv"),
    )

    assert logged == [
        "venv: /tmp/venv",
        "worker #3: local-worker from: /tmp/worker.py",
    ]


def test_resolve_initialized_worker_env_reuses_or_builds_env():
    ensured_envs: list[object] = []
    existing_env = SimpleNamespace(name="existing")

    resolved_existing = execution_support._resolve_initialized_worker_env(
        env=existing_env,
        app="demo_project",
        verbose=2,
        base_worker_cls=BaseWorker,
        agi_env_factory=lambda **_kwargs: pytest.fail("unexpected env factory"),
        ensure_managed_pc_share_dir_fn=lambda env: ensured_envs.append(env),
    )

    assert resolved_existing is existing_env
    assert BaseWorker.env is existing_env
    assert ensured_envs == [existing_env]

    created_env = SimpleNamespace(name="created")
    factory_calls: list[dict[str, object]] = []
    ensured_envs.clear()

    resolved_created = execution_support._resolve_initialized_worker_env(
        env=None,
        app="demo_project",
        verbose=2,
        base_worker_cls=BaseWorker,
        agi_env_factory=lambda **kwargs: factory_calls.append(kwargs) or created_env,
        ensure_managed_pc_share_dir_fn=lambda env: ensured_envs.append(env),
    )

    assert resolved_created is created_env
    assert BaseWorker.env is created_env
    assert factory_calls == [{"app": "demo_project", "verbose": 2}]
    assert ensured_envs == [created_env]


def test_start_initialized_worker_configures_registers_logs_and_starts(monkeypatch):
    worker_inst = SimpleNamespace()
    calls: list[tuple[str, object]] = []
    logger_messages: list[str] = []
    logger = SimpleNamespace(
        info=lambda message, *args: logger_messages.append(str(message % args if args else message))
    )
    monkeypatch.setattr(
        execution_support,
        "_configure_initialized_worker",
        lambda **kwargs: calls.append(("configure", kwargs)) or worker_inst,
    )
    monkeypatch.setattr(
        execution_support,
        "_register_initialized_worker",
        lambda **kwargs: calls.append(("register", kwargs)),
    )

    started = execution_support._start_initialized_worker(
        mode=4,
        worker_id=3,
        worker="tcp://192.168.20.130:1234",
        args={"alpha": 1},
        verbose=2,
        base_worker_cls=BaseWorker,
        load_worker_fn=lambda _mode: pytest.fail("unexpected direct load_worker_fn execution"),
        start_fn=lambda inst: calls.append(("start", inst)),
        args_namespace_cls=base_worker_mod.ArgsNamespace,
        logger_obj=logger,
        time_module=SimpleNamespace(time=lambda: 12.5),
        path_cls=Path,
    )

    assert started is worker_inst
    assert [entry[0] for entry in calls] == ["configure", "register", "start"]
    configure_kwargs = calls[0][1]
    assert configure_kwargs["mode"] == 4
    assert configure_kwargs["worker_id"] == 3
    assert configure_kwargs["args"] == {"alpha": 1}
    assert configure_kwargs["verbose"] == 2
    assert configure_kwargs["args_namespace_cls"] is base_worker_mod.ArgsNamespace

    register_kwargs = calls[1][1]
    assert register_kwargs == {
        "base_worker_cls": BaseWorker,
        "worker_id": 3,
        "worker": "tcp://192.168.20.130:1234",
        "worker_inst": worker_inst,
        "verbose": 2,
        "started_at": 12.5,
        "path_cls": Path,
    }
    assert calls[2] == ("start", worker_inst)
    assert logger_messages == ["worker #3: tcp://192.168.20.130:1234 starting..."]


def test_initialize_worker_runtime_orchestrates_startup_helpers(monkeypatch):
    calls: list[tuple[str, object]] = []
    started_worker = SimpleNamespace(name="worker")

    monkeypatch.setattr(
        execution_support,
        "_log_worker_startup_context",
        lambda **kwargs: calls.append(("log", kwargs)),
    )
    monkeypatch.setattr(
        execution_support,
        "_resolve_initialized_worker_env",
        lambda **kwargs: calls.append(("env", kwargs)) or SimpleNamespace(name="env"),
    )
    monkeypatch.setattr(
        execution_support,
        "_start_initialized_worker",
        lambda **kwargs: calls.append(("start", kwargs)) or started_worker,
    )

    result = execution_support._initialize_worker_runtime(
        env=None,
        app="demo_project",
        mode=4,
        verbose=2,
        worker_id=3,
        worker="tcp://192.168.20.130:1234",
        args={"alpha": 1},
        base_worker_cls=BaseWorker,
        agi_env_factory=lambda **_kwargs: pytest.fail("unexpected env factory direct call"),
        ensure_managed_pc_share_dir_fn=lambda _env: pytest.fail("unexpected share-dir call"),
        load_worker_fn=lambda _mode: pytest.fail("unexpected direct load worker"),
        start_fn=lambda _inst: pytest.fail("unexpected direct start call"),
        args_namespace_cls=base_worker_mod.ArgsNamespace,
        logger_obj=SimpleNamespace(),
        time_module=SimpleNamespace(time=lambda: 12.5),
        sys_module=SimpleNamespace(prefix="/tmp/venv"),
        file_path="/tmp/worker.py",
        path_cls=Path,
    )

    assert result is started_worker
    assert [name for name, _ in calls] == ["log", "env", "start"]
    assert calls[0][1] == {
        "worker_id": 3,
        "worker": "tcp://192.168.20.130:1234",
        "file_path": "/tmp/worker.py",
        "logger_obj": calls[0][1]["logger_obj"],
        "sys_module": calls[0][1]["sys_module"],
        "path_cls": Path,
    }
    assert calls[1][1] == {
        "env": None,
        "app": "demo_project",
        "verbose": 2,
        "base_worker_cls": BaseWorker,
        "agi_env_factory": calls[1][1]["agi_env_factory"],
        "ensure_managed_pc_share_dir_fn": calls[1][1]["ensure_managed_pc_share_dir_fn"],
    }
    assert calls[2][1] == {
        "mode": 4,
        "worker_id": 3,
        "worker": "tcp://192.168.20.130:1234",
        "args": {"alpha": 1},
        "verbose": 2,
        "base_worker_cls": BaseWorker,
        "load_worker_fn": calls[2][1]["load_worker_fn"],
        "start_fn": calls[2][1]["start_fn"],
        "args_namespace_cls": base_worker_mod.ArgsNamespace,
        "logger_obj": calls[2][1]["logger_obj"],
        "time_module": calls[2][1]["time_module"],
        "path_cls": Path,
    }


def test_initialize_worker_logs_traceback_and_reraises_startup_bug(monkeypatch):
    logged: list[str] = []

    monkeypatch.setattr(
        execution_support,
        "_initialize_worker_runtime",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("worker startup bug")),
    )

    with pytest.raises(AssertionError, match="worker startup bug"):
        execution_support.initialize_worker(
            env=None,
            app="demo_project",
            mode=4,
            verbose=2,
            worker_id=3,
            worker="tcp://192.168.20.130:1234",
            args={"alpha": 1},
            base_worker_cls=BaseWorker,
            agi_env_factory=lambda **_kwargs: pytest.fail("unexpected env factory"),
            ensure_managed_pc_share_dir_fn=lambda _env: pytest.fail("unexpected share-dir call"),
            load_worker_fn=lambda _mode: pytest.fail("unexpected direct load worker"),
            start_fn=lambda _inst: pytest.fail("unexpected direct start call"),
            args_namespace_cls=base_worker_mod.ArgsNamespace,
            logger_obj=SimpleNamespace(error=lambda message, *args: logged.append(str(message % args if args else message))),
            time_module=SimpleNamespace(time=lambda: 12.5),
            traceback_module=SimpleNamespace(format_exc=lambda: "startup traceback"),
            sys_module=SimpleNamespace(prefix="/tmp/venv"),
            file_path="/tmp/worker.py",
            path_cls=Path,
        )

    assert logged == ["startup traceback"]


def test_baseworker_run_cython_mode_adds_paths_and_executes_plan(monkeypatch, tmp_path):
    wenv_abs = tmp_path / "demo_worker"
    cy_dist = wenv_abs / "dist"
    cy_dist.mkdir(parents=True)
    (cy_dist / "demo_cy_stub").mkdir()

    sibling_dist = tmp_path / "other_worker" / "dist"
    sibling_dist.mkdir(parents=True)

    env = SimpleNamespace(
        wenv_abs=wenv_abs,
        _run_time=None,
        mode2str=lambda mode: f"mode-{mode}",
    )
    calls: list[tuple[object, object]] = []

    class FakeDispatcher:
        @staticmethod
        async def _do_distrib(_env, workers, args):
            assert workers == {"local": 1}
            assert args == {"payload": 1}
            return workers, {"plan": 1}, {"meta": 2}

    monkeypatch.setitem(
        sys.modules,
        "agi_node.agi_dispatcher.agi_dispatcher",
        SimpleNamespace(WorkDispatcher=FakeDispatcher),
    )
    monkeypatch.setattr(
        BaseWorker,
        "_do_works",
        staticmethod(lambda plan, meta: calls.append((plan, meta))),
    )
    time_values = iter([10.0, 13.0])
    monkeypatch.setattr(base_worker_mod.time, "time", lambda: next(time_values))

    original_sys_path = list(sys.path)
    try:
        result = asyncio.run(
            BaseWorker._run(env=env, workers={"local": 1}, mode=2, args={"payload": 1})
        )
    finally:
        sys.path[:] = original_sys_path

    assert calls == [({"plan": 1}, {"meta": 2})]
    assert env._run_time == 3.0
    assert result.startswith("mode-2 ")


def test_resolve_primary_cython_dist_path_and_append_sibling_worker_dist_paths(tmp_path):
    wenv_abs = tmp_path / "demo_worker"
    cy_dist = wenv_abs / "dist"
    cy_dist.mkdir(parents=True)
    (cy_dist / "demo_cy_stub").mkdir()

    resolved = execution_support._resolve_primary_cython_dist_path(wenv_abs)
    assert resolved == str(cy_dist.resolve())

    sibling_dist = tmp_path / "other_worker" / "dist"
    sibling_dist.mkdir(parents=True)
    sys_path = [str(cy_dist.resolve())]
    execution_support._append_sibling_worker_dist_paths(
        tmp_path,
        sys_path=sys_path,
    )

    assert sys_path == [
        str(cy_dist.resolve()),
        str(sibling_dist.resolve()),
    ]


def test_resolve_primary_cython_dist_path_handles_missing_primary_and_skips_missing_sibling(tmp_path, monkeypatch):
    assert execution_support._resolve_primary_cython_dist_path(tmp_path / "missing_worker") is None

    sibling_root = tmp_path / "siblings"
    sibling_root.mkdir()
    missing_dist = sibling_root / "broken_worker" / "dist"
    missing_dist.mkdir(parents=True)

    original_resolve = Path.resolve

    def _fake_resolve(self, *args, **kwargs):
        if self == missing_dist:
            raise FileNotFoundError("gone")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", _fake_resolve)

    sys_path: list[str] = []
    execution_support._append_sibling_worker_dist_paths(
        sibling_root,
        sys_path=sys_path,
    )

    assert sys_path == []


def test_append_sibling_worker_dist_paths_skips_missing_root(tmp_path):
    sys_path = ["existing"]

    execution_support._append_sibling_worker_dist_paths(
        tmp_path / "missing",
        sys_path=sys_path,
    )

    assert sys_path == ["existing"]


def test_baseworker_run_plan_mode_and_distribution_failures(monkeypatch, tmp_path):
    env = SimpleNamespace(
        wenv_abs=tmp_path / "demo_worker",
        mode2str=lambda mode: f"mode-{mode}",
    )

    class PlanDispatcher:
        @staticmethod
        async def _do_distrib(_env, workers, args):
            return workers, {"plan": "only"}, {"meta": True}

    monkeypatch.setitem(
        sys.modules,
        "agi_node.agi_dispatcher.agi_dispatcher",
        SimpleNamespace(WorkDispatcher=PlanDispatcher),
    )
    assert (
        asyncio.run(BaseWorker._run(env=env, workers={"local": 1}, mode=48, args=None))
        == {"plan": "only"}
    )

    class BrokenDispatcher:
        @staticmethod
        async def _do_distrib(_env, workers, args):
            raise ValueError("bad distrib")

    monkeypatch.setitem(
        sys.modules,
        "agi_node.agi_dispatcher.agi_dispatcher",
        SimpleNamespace(WorkDispatcher=BrokenDispatcher),
    )
    with pytest.raises(RuntimeError, match="Failed to build distribution plan"):
        asyncio.run(BaseWorker._run(env=env, workers={"local": 1}, mode=0, args=None))

    class RuntimeDispatcher:
        @staticmethod
        async def _do_distrib(_env, workers, args):
            raise RuntimeError("boom")

    monkeypatch.setitem(
        sys.modules,
        "agi_node.agi_dispatcher.agi_dispatcher",
        SimpleNamespace(WorkDispatcher=RuntimeDispatcher),
    )
    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(BaseWorker._run(env=env, workers={"local": 1}, mode=0, args=None))


def test_build_distribution_plan_wraps_expected_planning_failures():
    logger = SimpleNamespace(error=lambda *_args, **_kwargs: None)
    traceback_module = SimpleNamespace(format_exc=lambda: "traceback")

    class BrokenDispatcher:
        @staticmethod
        async def _do_distrib(_env, _workers, _args):
            raise ValueError("bad distrib")

    with pytest.raises(RuntimeError, match="Failed to build distribution plan"):
        asyncio.run(
            execution_support._build_distribution_plan(
                env=SimpleNamespace(),
                workers={"local": 1},
                args=None,
                dispatcher_loader=lambda: BrokenDispatcher,
                logger_obj=logger,
                traceback_module=traceback_module,
            )
        )


def test_build_distribution_plan_propagates_unexpected_planning_bug():
    logger = SimpleNamespace(error=lambda *_args, **_kwargs: None)
    traceback_module = SimpleNamespace(format_exc=lambda: "traceback")

    class BrokenDispatcher:
        @staticmethod
        async def _do_distrib(_env, _workers, _args):
            raise AssertionError("planner bug")

    with pytest.raises(AssertionError, match="planner bug"):
        asyncio.run(
            execution_support._build_distribution_plan(
                env=SimpleNamespace(),
                workers={"local": 1},
                args=None,
                dispatcher_loader=lambda: BrokenDispatcher,
                logger_obj=logger,
                traceback_module=traceback_module,
            )
        )


def test_baseworker_run_cython_without_compiled_library_raises(tmp_path):
    env = SimpleNamespace(
        wenv_abs=tmp_path / "demo_worker",
        mode2str=lambda mode: f"mode-{mode}",
    )
    (env.wenv_abs / "dist").mkdir(parents=True)

    with pytest.raises(
        RuntimeError,
        match="Cython mode requested but no compiled library found",
    ):
        asyncio.run(BaseWorker._run(env=env, workers={"local": 1}, mode=2, args=None))


def test_baseworker_build_uses_managed_pc_home_prefix(monkeypatch, tmp_path):
    monkeypatch.setattr(base_worker_mod.getpass, "getuser", lambda: "T012345")

    with pytest.raises(FileNotFoundError):
        BaseWorker._build("demo_worker", str(tmp_path), "tcp://127.0.0.1:8787", mode=0, verbose=0)

    assert BaseWorker._home_dir == Path("~/MyApp/").expanduser().absolute()
    assert BaseWorker._logs == BaseWorker._home_dir / "demo_worker_trace.txt"


def test_baseworker_new_without_env_initializes_agienv_and_logs_start_failures(monkeypatch):
    created_env = SimpleNamespace()

    class BrokenWorker(BaseWorker):
        def start(self):
            raise RuntimeError("worker boom")

    monkeypatch.setattr(base_worker_mod, "AgiEnv", lambda app=None, verbose=0: created_env)
    monkeypatch.setattr(
        BaseWorker,
        "_ensure_managed_pc_share_dir",
        staticmethod(lambda _env: None),
    )
    monkeypatch.setattr(
        BaseWorker,
        "_load_worker",
        staticmethod(lambda _mode: BrokenWorker),
    )

    with pytest.raises(RuntimeError, match="worker boom"):
        BaseWorker._new(
            env=None,
            app="demo_project",
            mode=0,
            verbose=1,
            worker_id=2,
            worker="local",
            args=None,
        )

    assert BaseWorker.env is created_env


def test_baseworker_get_worker_info_creates_temp_share_dir(monkeypatch, tmp_path):
    BaseWorker._share_path = None
    BaseWorker._worker = "127.0.0.1:8787"
    created_dirs: list[tuple[str, bool]] = []
    removed_files: list[str] = []
    monkeypatch.setattr(
        base_worker_mod.tempfile,
        "gettempdir",
        lambda: str(tmp_path / "temp-share"),
    )
    monkeypatch.setattr(base_worker_mod.os.path, "exists", lambda path: False)
    monkeypatch.setattr(
        base_worker_mod.os,
        "makedirs",
        lambda path, exist_ok=True: created_dirs.append((path, exist_ok))
        or Path(path).mkdir(parents=True, exist_ok=exist_ok),
    )
    monkeypatch.setattr(
        base_worker_mod.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(total=8_000_000_000, available=4_000_000_000),
    )
    monkeypatch.setattr(base_worker_mod.psutil, "cpu_count", lambda: 4)
    monkeypatch.setattr(
        base_worker_mod.psutil,
        "cpu_freq",
        lambda: SimpleNamespace(current=3200),
    )
    monkeypatch.setattr(base_worker_mod.time, "sleep", lambda *_args, **_kwargs: None)
    time_values = itertools.count(1.0)
    monkeypatch.setattr(base_worker_mod.time, "time", lambda: next(time_values))
    monkeypatch.setattr(
        base_worker_mod.os,
        "remove",
        lambda path: removed_files.append(path),
    )

    info = BaseWorker._get_worker_info(0)

    assert created_dirs == [(str(tmp_path / "temp-share"), True)]
    assert removed_files
    assert info["network_speed"][0] > 0


def test_resolve_worker_info_path_uses_tempdir_and_creates_missing_dir(tmp_path):
    created_dirs: list[tuple[str, bool]] = []
    logged: list[str] = []
    resolved_path = execution_support._resolve_worker_info_path(
        share_path=None,
        normalize_path_fn=lambda path: f"normalized::{path}",
        logger_obj=SimpleNamespace(
            info=lambda message, *args: logged.append(str(message % args if args else message))
        ),
        tempfile_module=SimpleNamespace(gettempdir=lambda: str(tmp_path / "temp-share")),
        os_module=SimpleNamespace(
            path=SimpleNamespace(exists=lambda _path: False),
            makedirs=lambda path, exist_ok=True: created_dirs.append((path, exist_ok)),
        ),
    )

    assert resolved_path == str(tmp_path / "temp-share")
    assert created_dirs == [(str(tmp_path / "temp-share"), True)]
    assert logged == [f"mkdir {tmp_path / 'temp-share'}"]


def test_resolve_worker_info_path_normalizes_share_path_and_skips_existing_dir():
    resolved_path = execution_support._resolve_worker_info_path(
        share_path="clustershare",
        normalize_path_fn=lambda path: f"normalized::{path}",
        logger_obj=SimpleNamespace(info=lambda *_args, **_kwargs: pytest.fail("unexpected log")),
        tempfile_module=SimpleNamespace(gettempdir=lambda: pytest.fail("unexpected tempdir")),
        os_module=SimpleNamespace(
            path=SimpleNamespace(exists=lambda _path: True),
            makedirs=lambda *_args, **_kwargs: pytest.fail("unexpected mkdir"),
        ),
    )

    assert resolved_path == "normalized::clustershare"


def test_measure_worker_write_speed_writes_probe_file_and_removes_it():
    removed_paths: list[str] = []
    written_payloads: list[str] = []
    time_values = iter([1.0, 3.0])

    class _FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def write(self, payload):
            written_payloads.append(payload)

    write_speed = execution_support._measure_worker_write_speed(
        path="/tmp/share",
        worker="127.0.0.1:8787",
        time_module=SimpleNamespace(
            time=lambda: next(time_values),
            sleep=lambda *_args, **_kwargs: None,
        ),
        os_module=SimpleNamespace(
            path=SimpleNamespace(join=base_worker_mod.os.path.join),
            remove=lambda path: removed_paths.append(path),
        ),
        open_fn=lambda *_args, **_kwargs: _FakeStream(),
        size=8,
    )

    assert written_payloads == ["\x00" * 8]
    assert removed_paths == ["/tmp/share/127.0.0.1_8787"]
    assert write_speed == [4.0]


def test_baseworker_build_verbose_non_managed_path_updates_sys_path(monkeypatch, tmp_path):
    monkeypatch.setattr(base_worker_mod.getpass, "getuser", lambda: "demo")
    copied: list[tuple[str, Path]] = []
    logged: list[str] = []
    monkeypatch.setattr(
        base_worker_mod.logger,
        "info",
        lambda message, *args: logged.append(str(message % args if args else message)),
    )
    monkeypatch.setattr(
        base_worker_mod.shutil,
        "copyfile",
        lambda src, dst: copied.append((src, dst)),
    )

    dask_home = tmp_path / "dask-home"
    dask_home.mkdir()
    (dask_home / "entry.txt").write_text("x", encoding="utf-8")

    original_sys_path = list(sys.path)
    try:
        BaseWorker._build("demo_worker", str(dask_home), "local-worker", mode=0, verbose=3)
    finally:
        sys.path[:] = original_sys_path

    assert BaseWorker._home_dir == Path("~/").expanduser().absolute()
    assert copied and copied[0][0].endswith("/some_egg_file")
    assert any("home_dir:" in message for message in logged)
    assert any("entry.txt" in message for message in logged)
    assert copied[0][1] == Path("~/").expanduser().absolute() / "wenv" / "demo_worker" / "some_egg_file.egg"


def test_log_build_worker_context_only_logs_for_verbose_builds(tmp_path):
    logged: list[str] = []
    dask_home = tmp_path / "dask-home"
    dask_home.mkdir()
    (dask_home / "entry.txt").write_text("x", encoding="utf-8")
    logger = SimpleNamespace(
        info=lambda message, *args: logged.append(str(message % args if args else message))
    )

    execution_support._log_build_worker_context(
        home_dir=tmp_path / "home",
        target_worker="demo_worker",
        dask_home=str(dask_home),
        mode=4,
        verbose=2,
        worker="local-worker",
        logger_obj=logger,
    )
    assert logged == []

    execution_support._log_build_worker_context(
        home_dir=tmp_path / "home",
        target_worker="demo_worker",
        dask_home=str(dask_home),
        mode=4,
        verbose=3,
        worker="local-worker",
        logger_obj=logger,
    )

    assert any("home_dir:" in message for message in logged)
    assert any("target_worker=demo_worker" in message for message in logged)
    assert any("entry.txt" in message for message in logged)


def test_resolve_worker_home_dir_covers_managed_and_default_prefixes():
    managed_home = execution_support._resolve_worker_home_dir(
        getuser_fn=lambda: "T012345",
    )
    default_home = execution_support._resolve_worker_home_dir(
        getuser_fn=lambda: "demo",
    )

    assert managed_home == Path("~/MyApp/").expanduser().absolute()
    assert default_home == Path("~/").expanduser().absolute()


def test_configure_build_worker_state_updates_base_worker_class_attrs():
    home_dir = execution_support._configure_build_worker_state(
        target_worker="demo_worker",
        dask_home="/tmp/dask-home",
        worker="local-worker",
        base_worker_cls=BaseWorker,
        getuser_fn=lambda: "demo",
    )

    assert home_dir == Path("~/").expanduser().absolute()
    assert BaseWorker._home_dir == home_dir
    assert BaseWorker._logs == home_dir / "demo_worker_trace.txt"
    assert BaseWorker._dask_home == "/tmp/dask-home"
    assert BaseWorker._worker == "local-worker"


def test_resolve_worker_egg_install_paths_uses_home_wenv_target():
    egg_src, extract_path = execution_support._resolve_worker_egg_install_paths(
        home_dir=Path("/tmp/home"),
        target_worker="demo_worker",
        dask_home="/tmp/dask-home",
    )

    assert egg_src == "/tmp/dask-home/some_egg_file"
    assert extract_path == Path("/tmp/home") / "wenv" / "demo_worker"


def test_install_worker_egg_deduplicates_sys_path_and_returns_destination(tmp_path):
    copied: list[tuple[str, Path]] = []
    logged: list[str] = []
    extract_path = tmp_path / "wenv" / "demo_worker"
    sys_path = [str(extract_path / "some_egg_file.egg"), "/tmp/existing"]
    logger = SimpleNamespace(
        info=lambda message, *args: logged.append(str(message % args if args else message))
    )

    egg_dest = execution_support._install_worker_egg(
        egg_src="/tmp/build/some_egg_file",
        extract_path=extract_path,
        sys_path=sys_path,
        logger_obj=logger,
        shutil_module=SimpleNamespace(
            copyfile=lambda src, dst: copied.append((src, dst))
        ),
    )

    assert egg_dest == extract_path / "some_egg_file.egg"
    assert copied == [("/tmp/build/some_egg_file", extract_path / "some_egg_file.egg")]
    assert sys_path == [str(extract_path / "some_egg_file.egg"), "/tmp/existing"]
    assert any("copy: /tmp/build/some_egg_file" in message for message in logged)
    assert "sys.path:" in logged
    assert "done!" in logged


def test_expand_worker_payload_preserves_original_when_chunk_expand_returns_none():
    expanded_payload, chunk_len, total_workers = execution_support._expand_worker_payload(
        ["plan-a"],
        1,
        expand_chunk_fn=lambda payload, worker_id: (None, worker_id + 2, len(payload)),
    )

    assert expanded_payload == ["plan-a"]
    assert chunk_len == 3
    assert total_workers == 1


def test_select_worker_batch_entry_uses_worker_slot_or_empty_list():
    assert execution_support._select_worker_batch_entry([["a"], ["b"]], 1) == ["b"]
    assert execution_support._select_worker_batch_entry([["a"]], 3) == []
    assert execution_support._select_worker_batch_entry({"not": "a list"}, 0) == []


def test_count_worker_batches_and_resolve_total_workers_cover_fallbacks():
    assert execution_support._count_worker_batches(5, ["ignored"]) == 5
    assert execution_support._count_worker_batches(None, ["a", "b"]) == 2
    assert execution_support._resolve_total_workers(4, ["ignored"]) == 4
    assert execution_support._resolve_total_workers(None, ["a", "b"]) == 2
    assert execution_support._resolve_total_workers(None, {"not": "a list"}) == "?"


def test_log_worker_plan_progress_reports_counts_and_returns_plan_batch_count():
    logged: list[str] = []
    logger = SimpleNamespace(
        info=lambda message, *args: logged.append(str(message % args if args else message))
    )

    plan_batch_count = execution_support._log_worker_plan_progress(
        worker_id=1,
        worker_name="local-worker",
        file_path="/tmp/worker.py",
        expanded_plan=[["a"], ["b", "c"]],
        plan_total_workers=None,
        plan_chunk_len=None,
        plan_entry=["b", "c"],
        meta_chunk_len=3,
        metadata_entry=["ignored"],
        logger_obj=logger,
    )

    assert plan_batch_count == 2
    assert logged == [
        "worker #1: local-worker from /tmp/worker.py",
        "work #2 / 2 - plan batches=2 metadata batches=3",
    ]


def test_execute_initialized_worker_plan_expands_payloads_runs_worker_and_logs_completion(monkeypatch):
    logged: list[str] = []
    works_calls: list[tuple[object, object]] = []
    tracking_calls: list[dict[str, object]] = []
    logger = SimpleNamespace(
        info=lambda message, *args: logged.append(str(message % args if args else message))
    )
    worker_inst = SimpleNamespace(
        works=lambda plan, meta: works_calls.append((plan, meta))
    )

    @contextmanager
    def fake_worker_tracking_run(**kwargs):
        tracking_calls.append(kwargs)
        yield object()

    monkeypatch.setattr(
        execution_support.worker_tracking_support,
        "worker_tracking_run",
        fake_worker_tracking_run,
    )

    plan_batch_count = execution_support._execute_initialized_worker_plan(
        workers_plan=[["plan-a"], ["plan-b"]],
        workers_plan_metadata=[["meta-a"], ["meta-b"]],
        worker_id=1,
        worker_name="local-worker",
        insts={1: worker_inst},
        expand_chunk_fn=lambda payload, worker_id: (payload, None, len(payload)),
        logger_obj=logger,
        file_path="/tmp/worker.py",
    )

    assert tracking_calls == [
        {
            "worker_id": 1,
            "worker_name": "local-worker",
            "plan_batch_count": 1,
            "plan_chunk_len": None,
            "metadata_chunk_len": None,
            "logger_obj": logger,
        }
    ]
    assert plan_batch_count == 1
    assert works_calls == [
        ([["plan-a"], ["plan-b"]], [["meta-a"], ["meta-b"]])
    ]
    assert logged == [
        "worker #1: local-worker from /tmp/worker.py",
        "work #2 / 2 - plan batches=1 metadata batches=1",
        "worker #1 completed 1 plan batches",
    ]


def test_execute_initialized_worker_plan_preserves_tracking_exception_boundary(monkeypatch):
    logged: list[str] = []
    logger = SimpleNamespace(
        info=lambda message, *args: logged.append(str(message % args if args else message))
    )
    worker_inst = SimpleNamespace(
        works=lambda *_args: (_ for _ in ()).throw(RuntimeError("worker failed"))
    )

    @contextmanager
    def fake_worker_tracking_run(**_kwargs):
        yield object()

    monkeypatch.setattr(
        execution_support.worker_tracking_support,
        "worker_tracking_run",
        fake_worker_tracking_run,
    )

    with pytest.raises(RuntimeError, match="worker failed"):
        execution_support._execute_initialized_worker_plan(
            workers_plan=[["plan-a"]],
            workers_plan_metadata=[["meta-a"]],
            worker_id=0,
            worker_name="local-worker",
            insts={0: worker_inst},
            expand_chunk_fn=lambda payload, worker_id: (payload, None, len(payload)),
            logger_obj=logger,
            file_path="/tmp/worker.py",
        )


def test_run_worker_prepares_tracking_environment(monkeypatch):
    calls: list[object] = []

    async def fake_build_distribution_plan(**_kwargs):
        return {"local": 1}, {"plan": 1}, {"meta": 2}

    monkeypatch.setattr(
        execution_support,
        "_build_distribution_plan",
        fake_build_distribution_plan,
    )
    monkeypatch.setattr(
        execution_support.worker_tracking_support,
        "prepare_worker_tracking_environment",
        lambda env, **kwargs: calls.append((env, kwargs)) or "sqlite:///tmp/mlflow.db",
    )

    env = SimpleNamespace(_run_time=None, mode2str=lambda mode: f"mode-{mode}")
    time_values = iter([10.0, 11.0])

    result = asyncio.run(
        execution_support.run_worker(
            env=env,
            workers={"local": 1},
            mode=0,
            args={"payload": 1},
            do_works_fn=lambda plan, meta: calls.append((plan, meta)),
            dispatcher_loader=lambda: object,
            sys_path=[],
            logger_obj=SimpleNamespace(info=lambda *_args: None),
            traceback_module=SimpleNamespace(format_exc=lambda: ""),
            time_module=SimpleNamespace(time=lambda: next(time_values)),
            humanize_module=SimpleNamespace(precisedelta=lambda delta: "1 second"),
            datetime_module=SimpleNamespace(timedelta=lambda seconds: seconds),
        )
    )

    assert calls[0][0] is env
    assert calls[0][1]["logger_obj"] is not None
    assert calls[1] == ({"plan": 1}, {"meta": 2})
    assert env._run_time == 1.0
    assert result == "mode-0 1 second"

def test_attach_and_detach_worker_log_capture_manage_handler_lifecycle():
    root_logger = base_worker_mod.logging.getLogger("test.worker.capture")
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    log_stream, handler, active_root_logger = execution_support._attach_worker_log_capture(
        root_logger=root_logger,
    )

    assert active_root_logger is root_logger
    assert handler in root_logger.handlers

    execution_support._detach_worker_log_capture(
        active_root_logger=active_root_logger,
        handler=handler,
    )

    assert handler not in root_logger.handlers
    assert log_stream.getvalue() == ""


def test_baseworker_expand_chunk_scalar_and_do_works_fallback_paths(monkeypatch):
    reconstructed, chunk_len, total = BaseWorker._expand_chunk(
        {
            "__agi_worker_chunk__": True,
            "chunk": "work",
            "worker_idx": 2,
        },
        worker_id=2,
    )
    assert reconstructed == [None, None, "work"]
    assert chunk_len == 4
    assert total == 3

    worker = DummyWorker()
    worker_calls: list[tuple[object, object]] = []
    worker.works = lambda plan, meta: worker_calls.append((plan, meta))
    BaseWorker._worker_id = 0
    BaseWorker._insts = {0: worker}
    monkeypatch.setattr(
        BaseWorker,
        "_expand_chunk",
        staticmethod(lambda payload, worker_id: (None, None, None)),
    )

    logs = BaseWorker._do_works(["p"], ["m"])

    assert worker_calls == [(["p"], ["m"])]
    assert isinstance(logs, str)


def test_baseworker_do_works_requires_initialized_worker_context():
    BaseWorker._worker_id = None
    BaseWorker._insts = {}

    with pytest.raises(RuntimeError, match="failed to do_works"):
        BaseWorker._do_works(["p"], ["m"])


def test_execute_worker_plan_logs_traceback_and_reraises_worker_bug(monkeypatch):
    logged: list[str] = []
    detached: list[tuple[object, object]] = []
    handler = object()
    root_logger = object()

    monkeypatch.setattr(
        execution_support,
        "_attach_worker_log_capture",
        lambda **_kwargs: (io.StringIO(), handler, root_logger),
    )
    monkeypatch.setattr(
        execution_support,
        "_detach_worker_log_capture",
        lambda *, active_root_logger, handler: detached.append((active_root_logger, handler)),
    )
    monkeypatch.setattr(
        execution_support,
        "_execute_initialized_worker_plan",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("worker bug")),
    )

    with pytest.raises(AssertionError, match="worker bug"):
        execution_support.execute_worker_plan(
            workers_plan=[["plan-a"]],
            workers_plan_metadata=[["meta-a"]],
            worker_id=1,
            worker_name="local-worker",
            insts={1: object()},
            expand_chunk_fn=lambda payload, worker_id: (payload, None, None),
            logger_obj=SimpleNamespace(error=lambda message, *args: logged.append(str(message % args if args else message))),
            traceback_module=SimpleNamespace(format_exc=lambda: "worker traceback"),
            file_path="/tmp/worker.py",
        )

    assert logged == ["worker traceback"]
    assert detached == [(root_logger, handler)]
