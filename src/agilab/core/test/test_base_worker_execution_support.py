from __future__ import annotations

import asyncio
import sys
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
    time_values = iter([1.0, 2.0])
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
