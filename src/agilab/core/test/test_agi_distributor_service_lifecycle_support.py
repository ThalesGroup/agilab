import asyncio
import datetime
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from agi_cluster.agi_distributor import AGI
import agi_cluster.agi_distributor.agi_distributor as agi_distributor_module
from agi_cluster.agi_distributor import service_lifecycle_support, service_state_support
from agi_env import AgiEnv
from agi_node.agi_dispatcher import BaseWorker

_BUILTIN_APPS_PATH = (Path(__file__).resolve().parents[4] / "src/agilab/apps/builtin").resolve()


def _minimal_app_env(*, verbose: int = 0) -> AgiEnv:
    return AgiEnv(apps_path=_BUILTIN_APPS_PATH, app="minimal_app_project", verbose=verbose)

# Set AGI verbosity low to avoid extra prints during test.
AGI.verbose = 0


@pytest.fixture(autouse=True)
def _reset_agi_service_state():
    snapshot = {
        "_args": AGI._args,
        "_dask_client": AGI._dask_client,
        "_dask_workers": AGI._dask_workers,
        "_jobs": AGI._jobs,
        "_mode": AGI._mode,
        "_mode_auto": AGI._mode_auto,
        "_run_time": AGI._run_time,
        "_run_type": AGI._run_type,
        "_run_types": list(AGI._run_types),
        "_scheduler": AGI._scheduler,
        "_scheduler_ip": AGI._scheduler_ip,
        "_scheduler_port": AGI._scheduler_port,
        "_service_cleanup_done_max_files": AGI._service_cleanup_done_max_files,
        "_service_cleanup_done_ttl_sec": AGI._service_cleanup_done_ttl_sec,
        "_service_cleanup_failed_max_files": AGI._service_cleanup_failed_max_files,
        "_service_cleanup_failed_ttl_sec": AGI._service_cleanup_failed_ttl_sec,
        "_service_cleanup_heartbeat_max_files": AGI._service_cleanup_heartbeat_max_files,
        "_service_cleanup_heartbeat_ttl_sec": AGI._service_cleanup_heartbeat_ttl_sec,
        "_service_cleanup_unproven": AGI._service_cleanup_unproven,
        "_service_runtime_shutdown_proven": AGI._service_runtime_shutdown_proven,
        "_service_futures": dict(AGI._service_futures),
        "_service_heartbeat_timeout": AGI._service_heartbeat_timeout,
        "_service_poll_interval": AGI._service_poll_interval,
        "_service_queue_done": AGI._service_queue_done,
        "_service_queue_failed": AGI._service_queue_failed,
        "_service_queue_heartbeats": AGI._service_queue_heartbeats,
        "_service_queue_pending": AGI._service_queue_pending,
        "_service_queue_root": AGI._service_queue_root,
        "_service_queue_running": AGI._service_queue_running,
        "_service_shutdown_on_stop": AGI._service_shutdown_on_stop,
        "_service_started_at": AGI._service_started_at,
        "_service_stop_timeout": AGI._service_stop_timeout,
        "_service_submit_counter": AGI._service_submit_counter,
        "_service_worker_args": dict(AGI._service_worker_args),
        "_service_workers": list(AGI._service_workers),
        "_target": AGI._target,
        "_workers": AGI._workers,
        "env": AGI.env,
        "install_worker_group": getattr(AGI, "install_worker_group", None),
        "target_path": getattr(AGI, "target_path", None),
        "verbose": AGI.verbose,
    }

    env = _minimal_app_env()
    AGI._args = None
    AGI._dask_client = None
    AGI._dask_workers = None
    AGI._jobs = None
    AGI._mode = None
    AGI._mode_auto = False
    AGI._run_time = {}
    AGI._run_type = None
    AGI._run_types = []
    AGI._scheduler = None
    AGI._scheduler_ip = None
    AGI._scheduler_port = None
    AGI._service_futures = {}
    AGI._service_workers = []
    AGI._service_shutdown_on_stop = True
    AGI._service_stop_timeout = 30.0
    AGI._service_poll_interval = None
    AGI._service_heartbeat_timeout = None
    AGI._service_cleanup_unproven = False
    AGI._service_runtime_shutdown_proven = False
    AGI._service_started_at = None
    AGI._service_submit_counter = 0
    AGI._service_worker_args = {}
    AGI._reset_service_queue_state()
    AGI._service_clear_state(env)

    yield

    AGI._service_clear_state(env)
    AGI._args = snapshot["_args"]
    AGI._dask_client = snapshot["_dask_client"]
    AGI._dask_workers = snapshot["_dask_workers"]
    AGI._jobs = snapshot["_jobs"]
    AGI._mode = snapshot["_mode"]
    AGI._mode_auto = snapshot["_mode_auto"]
    AGI._run_time = snapshot["_run_time"]
    AGI._run_type = snapshot["_run_type"]
    AGI._run_types = snapshot["_run_types"]
    AGI._scheduler = snapshot["_scheduler"]
    AGI._scheduler_ip = snapshot["_scheduler_ip"]
    AGI._scheduler_port = snapshot["_scheduler_port"]
    AGI._service_cleanup_done_max_files = snapshot["_service_cleanup_done_max_files"]
    AGI._service_cleanup_done_ttl_sec = snapshot["_service_cleanup_done_ttl_sec"]
    AGI._service_cleanup_failed_max_files = snapshot["_service_cleanup_failed_max_files"]
    AGI._service_cleanup_failed_ttl_sec = snapshot["_service_cleanup_failed_ttl_sec"]
    AGI._service_cleanup_heartbeat_max_files = snapshot["_service_cleanup_heartbeat_max_files"]
    AGI._service_cleanup_heartbeat_ttl_sec = snapshot["_service_cleanup_heartbeat_ttl_sec"]
    AGI._service_cleanup_unproven = snapshot["_service_cleanup_unproven"]
    AGI._service_runtime_shutdown_proven = snapshot[
        "_service_runtime_shutdown_proven"
    ]
    AGI._service_futures = snapshot["_service_futures"]
    AGI._service_heartbeat_timeout = snapshot["_service_heartbeat_timeout"]
    AGI._service_poll_interval = snapshot["_service_poll_interval"]
    AGI._service_queue_done = snapshot["_service_queue_done"]
    AGI._service_queue_failed = snapshot["_service_queue_failed"]
    AGI._service_queue_heartbeats = snapshot["_service_queue_heartbeats"]
    AGI._service_queue_pending = snapshot["_service_queue_pending"]
    AGI._service_queue_root = snapshot["_service_queue_root"]
    AGI._service_queue_running = snapshot["_service_queue_running"]
    AGI._service_shutdown_on_stop = snapshot["_service_shutdown_on_stop"]
    AGI._service_started_at = snapshot["_service_started_at"]
    AGI._service_stop_timeout = snapshot["_service_stop_timeout"]
    AGI._service_submit_counter = snapshot["_service_submit_counter"]
    AGI._service_worker_args = snapshot["_service_worker_args"]
    AGI._service_workers = snapshot["_service_workers"]
    AGI._target = snapshot["_target"]
    AGI._workers = snapshot["_workers"]
    AGI.env = snapshot["env"]
    AGI.install_worker_group = snapshot["install_worker_group"]
    AGI.target_path = snapshot["target_path"]
    AGI.verbose = snapshot["verbose"]


class _FakeFuture:
    def __init__(
        self,
        status: str = "pending",
        *,
        key: str | None = None,
        kind: str | None = None,
    ):
        self.status = status
        self.key = key
        self.kind = kind
        self.cancel_calls = 0

    def cancel(self):
        self.cancel_calls += 1
        self.status = "cancelled"


class _FakeClient:
    def __init__(self, workers: list[str]):
        self._workers = workers
        self.status = "running"
        self.submissions: list[dict[str, object]] = []
        self.loop_futures: list[_FakeFuture] = []

    def submit(self, *args, **kwargs):
        fn = args[0] if args else None
        fn_name = getattr(fn, "__name__", str(fn))
        self.submissions.append(
            {
                "fn": fn_name,
                "args": args[1:],
                "kwargs": kwargs,
            }
        )
        future = _FakeFuture(
            status="running" if fn_name == "loop" else "finished",
            key=kwargs.get("key"),
            kind=fn_name,
        )
        if fn_name == "loop":
            self.loop_futures.append(future)
        return future

    def gather(self, futures, errors="raise"):
        if any(getattr(future, "kind", None) == "break_loop" for future in futures):
            for loop_future in self.loop_futures:
                loop_future.status = "finished"
        if isinstance(futures, list):
            return [None for _ in futures]
        return []

    def scheduler_info(self):
        return {"workers": {f"tcp://{worker}": {} for worker in self._workers}}


def _install_fake_future_reacquisition(monkeypatch, client: _FakeClient) -> None:
    def _reacquire(_client, key):
        assert _client is client
        future = _FakeFuture(status="running", key=str(key), kind="loop")
        client.loop_futures.append(future)
        return future

    monkeypatch.setattr(service_lifecycle_support, "_reacquire_service_future", _reacquire)


def _real_service_stub_new(**_kwargs):
    return {"status": "ready"}


def _real_service_stub_loop(*, poll_interval=None):
    delay = max(float(poll_interval or 0.05), 0.01)
    time.sleep(delay)
    return {"status": "loop-exited"}


def _real_service_stub_break_loop():
    return True


def test_wrap_worker_chunk_handles_non_list_and_out_of_range_index():
    assert service_lifecycle_support.wrap_worker_chunk("raw-payload", worker_index=0) == "raw-payload"
    wrapped = AGI._wrap_worker_chunk([["a"], ["b"]], worker_index=8)
    assert wrapped["__agi_worker_chunk__"] is True
    assert wrapped["chunk"] == []
    assert wrapped["total_workers"] == 2
    assert wrapped["worker_idx"] == 8


def test_service_task_json_default_serializes_supported_values(tmp_path):
    assert service_lifecycle_support._service_task_json_default(
        datetime.date(2026, 5, 30)
    ) == "2026-05-30"
    assert service_lifecycle_support._service_task_json_default(
        datetime.datetime(2026, 5, 30, 10, 15)
    ) == "2026-05-30T10:15:00"
    assert service_lifecycle_support._service_task_json_default(tmp_path) == str(tmp_path)
    assert service_lifecycle_support._service_task_json_default(
        test_service_task_json_default_serializes_supported_values
    ) == "test_service_task_json_default_serializes_supported_values"
    with pytest.raises(TypeError, match="not JSON serializable"):
        service_lifecycle_support._service_task_json_default(object())


def test_prepare_service_worker_args_sets_queue_bound_service_args(tmp_path):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    AGI._args = {"alpha": 1}
    AGI._service_apply_queue_root(tmp_path / "queue", create=True)

    worker_args = service_lifecycle_support._prepare_service_worker_args(AGI, env)

    assert worker_args["alpha"] == 1
    assert worker_args["_agi_service_mode"] is True
    assert worker_args["_agi_service_queue_dir"] == str(AGI._service_queue_root)
    assert AGI._service_worker_args == worker_args


def test_submit_service_worker_inits_submits_new_for_each_worker(tmp_path):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    client = _FakeClient(["127.0.0.1:8787", "127.0.0.1:8788"])
    AGI._args = {"alpha": 1}
    AGI._mode = AGI.DASK_MODE
    AGI.verbose = 3
    AGI._service_workers = ["127.0.0.1:8787"]
    AGI._service_apply_queue_root(tmp_path / "queue", create=True)

    initialized = service_lifecycle_support._submit_service_worker_inits(
        AGI,
        env,
        client,
        ["127.0.0.1:8787", "127.0.0.1:8788"],
        key_prefix="agi-test",
    )

    assert initialized == ["127.0.0.1:8787", "127.0.0.1:8788"]
    assert AGI._service_workers == ["127.0.0.1:8787", "127.0.0.1:8788"]
    submit_calls = [entry for entry in client.submissions if entry["fn"] == "_new"]
    assert len(submit_calls) == 2
    assert submit_calls[0]["kwargs"]["worker_id"] == 0
    assert submit_calls[1]["kwargs"]["worker_id"] == 1
    assert submit_calls[1]["kwargs"]["key"] == "agi-test-init-minimal_app-127.0.0.1-8788"


def test_submit_service_loops_returns_worker_future_map():
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    client = _FakeClient(["127.0.0.1:8787"])
    AGI._service_poll_interval = 2.5

    futures = service_lifecycle_support._submit_service_loops(
        AGI,
        env,
        client,
        ["127.0.0.1:8787"],
        key_prefix="agi-loop",
    )

    assert list(futures.keys()) == ["127.0.0.1:8787"]
    loop_call = [entry for entry in client.submissions if entry["fn"] == "loop"][0]
    assert loop_call["kwargs"]["poll_interval"] == 2.5
    assert str(loop_call["kwargs"]["key"]).startswith(
        "agi-loop-loop-minimal_app-127.0.0.1-8787-"
    )
    AGI._service_workers = ["127.0.0.1:8787"]
    AGI._service_futures = futures
    state = AGI._service_state_payload(env)
    assert state["service_loop_keys"] == {
        "127.0.0.1:8787": loop_call["kwargs"]["key"]
    }


@pytest.mark.asyncio
async def test_service_restart_workers_returns_empty_for_empty_input():
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    restarted = await AGI._service_restart_workers(env, client=_FakeClient([]), workers_to_restart=[])
    assert restarted == []


@pytest.mark.asyncio
async def test_service_restart_workers_restarts_and_tracks_futures(monkeypatch, tmp_path):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    AGI._args = {"sample": 1}
    AGI._mode = AGI.DASK_MODE
    AGI._service_poll_interval = 0.2
    AGI._service_queue_root = None
    worker = "127.0.0.1:8787"
    old_loop = _FakeFuture(status="running", key="old-loop")
    AGI._service_workers = [worker]
    AGI._service_futures = {worker: old_loop}

    class _RestartClient:
        def __init__(self):
            self.calls = []

        def scheduler_info(self):
            return {"workers": {f"tcp://{worker}": {}}}

        def submit(self, fn, *args, **kwargs):
            fn_name = getattr(fn, "__name__", str(fn))
            self.calls.append(fn_name)
            if fn_name == "loop":
                # The replacement must never be submitted while the prior
                # worker execution can still overlap it.
                assert old_loop.status == "finished"
                return _FakeFuture(
                    status="running",
                    key=str(kwargs["key"]),
                    kind=fn_name,
                )
            return _FakeFuture(status="finished", kind=fn_name)

        def gather(self, futures, errors="raise"):
            if any(future.kind == "break_loop" for future in futures):
                old_loop.status = "finished"
            return [None for _ in futures]

    client = _RestartClient()

    def _fake_init_queue(_env):
        return AGI._service_apply_queue_root(tmp_path / "queue", create=True)

    monkeypatch.setattr(AGI, "_init_service_queue", staticmethod(_fake_init_queue))

    restarted = await AGI._service_restart_workers(env, client, [worker])
    assert restarted == [worker]
    assert AGI._service_futures[worker] is not old_loop
    assert AGI._service_futures[worker].status == "running"
    assert {"break_loop", "_new", "loop"}.issubset(set(client.calls))


@pytest.mark.asyncio
async def test_service_restart_workers_propagates_unexpected_break_loop_bug(monkeypatch, tmp_path):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    AGI._args = {"sample": 1}
    AGI._mode = AGI.DASK_MODE
    AGI._service_poll_interval = 0.2
    AGI._service_queue_root = None
    worker = "127.0.0.1:8787"
    old_loop = _FakeFuture(status="running", key="old-loop")
    AGI._service_workers = [worker]
    AGI._service_futures = {worker: old_loop}

    class _RestartClient:
        def scheduler_info(self):
            return {"workers": {f"tcp://{worker}": {}}}

        def submit(self, fn, *args, **kwargs):
            return _FakeFuture(status="finished", kind=getattr(fn, "__name__", ""))

        def gather(self, futures, errors="raise"):
            raise ValueError("unexpected break gather bug")

    def _fake_init_queue(_env):
        return AGI._service_apply_queue_root(tmp_path / "queue", create=True)

    monkeypatch.setattr(AGI, "_init_service_queue", staticmethod(_fake_init_queue))

    with pytest.raises(ValueError, match="unexpected break gather bug"):
        await AGI._service_restart_workers(env, _RestartClient(), [worker])
    assert AGI._service_futures == {worker: old_loop}
    assert AGI._service_cleanup_unproven is True


@pytest.mark.asyncio
async def test_service_restart_partial_loop_submission_retains_unproven_replacement(
    monkeypatch,
    tmp_path,
):
    env = _minimal_app_env()
    workers = ["w1", "w2"]
    old_futures = {
        worker: _FakeFuture(status="running", key=f"old-{worker}")
        for worker in workers
    }
    AGI._args = {"sample": 1}
    AGI._mode = AGI.DASK_MODE
    AGI._service_workers = list(workers)
    AGI._service_futures = dict(old_futures)
    AGI._service_apply_queue_root(tmp_path / "queue", create=True)

    class _PartialRestartClient:
        def __init__(self):
            self.break_gathers = 0
            self.loop_submissions = 0
            self.replacement: _FakeFuture | None = None

        def scheduler_info(self):
            return {"workers": {f"tcp://{worker}": {} for worker in workers}}

        def submit(self, fn, *args, **kwargs):
            fn_name = getattr(fn, "__name__", "")
            if fn_name == "loop":
                self.loop_submissions += 1
                if self.loop_submissions == 2:
                    raise RuntimeError("injected second replacement submit failure")
                self.replacement = _FakeFuture(
                    status="running",
                    key=str(kwargs["key"]),
                    kind=fn_name,
                )
                return self.replacement
            return _FakeFuture(status="finished", kind=fn_name)

        def gather(self, futures, errors="raise"):
            if any(future.kind == "break_loop" for future in futures):
                self.break_gathers += 1
                if self.break_gathers == 1:
                    for future in old_futures.values():
                        future.status = "finished"
            return [None for _ in futures]

    client = _PartialRestartClient()
    monkeypatch.setattr(AGI, "_service_write_state", staticmethod(lambda *_args: None))

    def _wait(futures, **_kwargs):
        return (
            {future for future in futures if future.status in {"finished", "error"}},
            {future for future in futures if future.status not in {"finished", "error"}},
        )

    with pytest.raises(
        RuntimeError,
        match="injected second replacement submit failure",
    ):
        await service_lifecycle_support.service_restart_workers(
            AGI,
            env,
            client,
            workers,
            wait_fn=_wait,
        )

    assert client.replacement is not None
    assert AGI._service_futures == {"w1": client.replacement}
    assert AGI._service_cleanup_unproven is True
    assert client.replacement.status == "running"


@pytest.mark.asyncio
async def test_service_restart_partial_publication_failure_forces_runtime_shutdown(
    monkeypatch,
    tmp_path,
):
    env = _minimal_app_env()
    workers = ["w1", "w2"]
    old_futures = {
        worker: _FakeFuture(status="running", key=f"old-{worker}")
        for worker in workers
    }
    AGI._args = {"sample": 1}
    AGI._mode = AGI.DASK_MODE
    AGI._service_workers = list(workers)
    AGI._service_futures = dict(old_futures)
    AGI._service_apply_queue_root(tmp_path / "queue", create=True)

    class _PartialRestartClient:
        def __init__(self):
            self.break_gathers = 0
            self.loop_submissions = 0
            self.replacement: _FakeFuture | None = None

        def scheduler_info(self):
            return {"workers": {f"tcp://{worker}": {} for worker in workers}}

        def submit(self, fn, *args, **kwargs):
            fn_name = getattr(fn, "__name__", "")
            if fn_name == "loop":
                self.loop_submissions += 1
                if self.loop_submissions == 2:
                    raise RuntimeError("injected second replacement submit failure")
                self.replacement = _FakeFuture(
                    status="running",
                    key=str(kwargs["key"]),
                    kind=fn_name,
                )
                return self.replacement
            return _FakeFuture(status="finished", kind=fn_name)

        def gather(self, futures, errors="raise"):
            if any(future.kind == "break_loop" for future in futures):
                self.break_gathers += 1
                if self.break_gathers == 1:
                    for future in old_futures.values():
                        future.status = "finished"
            return [None for _ in futures]

    client = _PartialRestartClient()
    AGI._dask_client = client
    stop_calls = 0

    async def _stop():
        nonlocal stop_calls
        stop_calls += 1
        assert client.replacement is not None
        client.replacement.status = "finished"
        AGI._dask_client = None

    def _wait(futures, **_kwargs):
        return (
            {future for future in futures if future.status in {"finished", "error"}},
            {
                future
                for future in futures
                if future.status not in {"finished", "error"}
            },
        )

    monkeypatch.setattr(AGI, "_stop", staticmethod(_stop))
    monkeypatch.setattr(
        AGI,
        "_service_write_state",
        staticmethod(
            lambda *_args: (_ for _ in ()).throw(
                service_state_support.ServiceStateUnavailableError(
                    "partial restart state replace remains locked"
                )
            )
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="injected second replacement submit failure",
    ):
        await service_lifecycle_support.service_restart_workers(
            AGI,
            env,
            client,
            workers,
            wait_fn=_wait,
        )

    assert stop_calls == 1
    assert client.replacement is not None
    assert client.replacement.status == "finished"
    assert AGI._dask_client is None
    assert AGI._service_futures == old_futures
    assert AGI._service_workers == workers
    assert AGI._service_runtime_shutdown_proven is True
    assert AGI._service_cleanup_unproven is True


@pytest.mark.asyncio
async def test_service_auto_restart_unhealthy_returns_empty_without_workers(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    AGI._service_workers = []

    async def _connected(_client):
        return []

    monkeypatch.setattr(AGI, "_service_connected_workers", staticmethod(_connected))
    result = await AGI._service_auto_restart_unhealthy(env, client=object())
    assert result == {"restarted": [], "reasons": {}}


@pytest.mark.asyncio
async def test_service_auto_restart_unhealthy_restarts_and_persists(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    AGI._service_workers = []
    calls = {"write": 0}

    async def _connected(_client):
        return ["w1"]

    async def _restart(_env, _client, _workers):
        return ["w1"]

    monkeypatch.setattr(AGI, "_service_connected_workers", staticmethod(_connected))
    monkeypatch.setattr(AGI, "_service_unhealthy_workers", staticmethod(lambda _workers: {"w1": "missing-heartbeat"}))
    monkeypatch.setattr(AGI, "_service_restart_workers", staticmethod(_restart))
    monkeypatch.setattr(AGI, "_service_state_payload", staticmethod(lambda _env: {"schema": "state"}))
    monkeypatch.setattr(
        AGI,
        "_service_write_state",
        staticmethod(lambda _env, _payload: calls.__setitem__("write", calls["write"] + 1)),
    )

    result = await AGI._service_auto_restart_unhealthy(env, client=object())
    assert result["restarted"] == ["w1"]
    assert result["reasons"]["w1"] == "missing-heartbeat"
    assert calls["write"] == 1


@pytest.mark.asyncio
async def test_service_auto_restart_state_publish_failure_forces_runtime_shutdown(
    monkeypatch,
):
    env = _minimal_app_env()
    old_future = _FakeFuture(status="finished", key="old-loop-w1", kind="loop")
    replacement = _FakeFuture(status="running", key="new-loop-w1", kind="loop")
    AGI._service_workers = ["w1"]
    AGI._service_futures = {"w1": old_future}

    class _PendingReplacementClient(_FakeClient):
        def gather(self, futures, errors="raise"):
            if isinstance(futures, list):
                return [None for _ in futures]
            return []

    client = _PendingReplacementClient(["w1"])
    AGI._dask_client = client
    stop_calls = 0

    async def _connected(_client):
        assert _client is client
        return ["w1"]

    async def _restart(_env, _client, _workers):
        assert _client is client
        assert _workers == ["w1"]
        AGI._service_futures = {"w1": replacement}
        return ["w1"]

    async def _stop():
        nonlocal stop_calls
        stop_calls += 1
        replacement.status = "finished"
        AGI._dask_client = None

    def _wait(futures, **_kwargs):
        return (
            {
                future
                for future in futures
                if future.status in {"finished", "error"}
            },
            {
                future
                for future in futures
                if future.status not in {"finished", "error"}
            },
        )

    monkeypatch.setattr(AGI, "_service_connected_workers", staticmethod(_connected))
    monkeypatch.setattr(
        AGI,
        "_service_unhealthy_workers",
        staticmethod(lambda _workers: {"w1": "missing-heartbeat"}),
    )
    monkeypatch.setattr(AGI, "_service_restart_workers", staticmethod(_restart))
    monkeypatch.setattr(AGI, "_stop", staticmethod(_stop))
    monkeypatch.setattr(
        AGI,
        "_service_write_state",
        staticmethod(
            lambda *_args: (_ for _ in ()).throw(
                service_state_support.ServiceStateUnavailableError(
                    "restart state replace remains locked"
                )
            )
        ),
    )

    with pytest.raises(
        service_state_support.ServiceStateUnavailableError,
        match="restart state replace remains locked",
    ):
        await service_lifecycle_support.service_auto_restart_unhealthy(
            AGI,
            env,
            client,
            wait_fn=_wait,
        )

    assert stop_calls == 1
    assert AGI._service_futures == {"w1": old_future}
    assert AGI._service_workers == ["w1"]
    assert AGI._service_cleanup_unproven is True
    assert AGI._service_runtime_shutdown_proven is True
    assert replacement.status == "finished"
    assert AGI._dask_client is None
    break_submissions = [
        submission
        for submission in client.submissions
        if submission["fn"] == "break_loop"
    ]
    assert len(break_submissions) == 1
    assert break_submissions[0]["kwargs"]["workers"] == ["w1"]
    assert break_submissions[0]["kwargs"]["allow_other_workers"] is False


@pytest.mark.asyncio
async def test_service_recover_preserves_state_on_transient_failure(tmp_path, monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    queue_dir = tmp_path / "service_queue"
    queue_dir.mkdir(parents=True, exist_ok=True)

    AGI._service_write_state(
        env,
        {
            "schema": "agi.service.state.v1",
            "target": env.target,
            "app": env.app,
            "mode": AGI.DASK_MODE,
            "run_type": "run --no-sync",
            "scheduler": "127.0.0.1:8786",
            "workers": {"127.0.0.1": 1},
            "service_workers": ["127.0.0.1:8787"],
            "service_loop_keys": {"127.0.0.1:8787": "persisted-loop-8787"},
            "queue_dir": str(queue_dir),
            "args": {},
        },
    )

    async def _fail_connect(*_args, **_kwargs):
        raise RuntimeError("connect failed")

    monkeypatch.setattr(AGI, "_connect_scheduler_with_retry", staticmethod(_fail_connect))

    recovered = await AGI._service_recover(env, allow_stale_cleanup=True)
    assert recovered is False
    assert AGI._service_read_state(env) is not None
    assert AGI._service_queue_root == queue_dir
    assert AGI._service_workers == ["127.0.0.1:8787"]
    assert AGI._service_futures == {}
    assert AGI._service_cleanup_unproven is True


@pytest.mark.asyncio
@pytest.mark.parametrize("shutdown_on_stop", [False, True])
async def test_legacy_v1_state_requires_or_performs_full_runtime_shutdown(
    monkeypatch,
    tmp_path,
    shutdown_on_stop,
):
    env = _minimal_app_env()
    worker = "127.0.0.1:8787"
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir(parents=True)
    state_path = AGI._service_state_path(env)
    AGI._service_write_state(
        env,
        {
            "schema": "agi.service.state.v1",
            "target": env.target,
            "app": env.app,
            "mode": AGI.DASK_MODE,
            "run_type": "run --no-sync",
            "scheduler": "127.0.0.1:8786",
            "workers": {"127.0.0.1": 1},
            "service_workers": [worker],
            # Legacy v1 intentionally has no service_loop_keys field.
            "queue_dir": str(queue_dir),
            "args": {},
        },
    )
    client = _FakeClient([worker])
    stops = []

    async def _connect(*_args, **_kwargs):
        return client

    async def _stop():
        stops.append("stop")
        AGI._dask_client = None

    monkeypatch.setattr(AGI, "_connect_scheduler_with_retry", staticmethod(_connect))
    monkeypatch.setattr(AGI, "_stop", staticmethod(_stop))

    result = await AGI.serve(
        env,
        action="stop",
        shutdown_on_stop=shutdown_on_stop,
    )

    if shutdown_on_stop:
        assert result["status"] == "stopped"
        assert result["legacy_full_shutdown"] is True
        assert stops == ["stop"]
        assert not state_path.exists()
        assert AGI._service_workers == []
        assert AGI._service_cleanup_unproven is False
        assert AGI._lifecycle_service_token is None
    else:
        assert result["status"] == "error"
        assert result["recovery_required"] is True
        assert stops == []
        assert state_path.exists()
        assert AGI._service_workers == [worker]
        assert AGI._service_cleanup_unproven is True
        assert AGI._lifecycle_service_token is not None


@pytest.mark.asyncio
async def test_legacy_v1_stop_retries_state_clear_from_runtime_shutdown_proof(
    monkeypatch,
    tmp_path,
):
    env = _minimal_app_env()
    worker = "127.0.0.1:8787"
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir(parents=True)
    AGI._service_write_state(
        env,
        {
            "schema": "agi.service.state.v1",
            "target": env.target,
            "app": env.app,
            "mode": AGI.DASK_MODE,
            "run_type": "run --no-sync",
            "scheduler": "127.0.0.1:8786",
            "workers": {"127.0.0.1": 1},
            "service_workers": [worker],
            "queue_dir": str(queue_dir),
            "args": {},
        },
    )
    client = _FakeClient([worker])
    stop_calls = 0
    clear_calls = 0
    real_clear_state = AGI._service_clear_state

    async def _connect(*_args, **_kwargs):
        return client

    async def _stop():
        nonlocal stop_calls
        stop_calls += 1
        AGI._dask_client = None

    def _clear_state(service_env):
        nonlocal clear_calls
        clear_calls += 1
        if clear_calls == 1:
            raise service_state_support.ServiceStateUnavailableError(
                "legacy state unlink remains locked"
            )
        real_clear_state(service_env)

    monkeypatch.setattr(AGI, "_connect_scheduler_with_retry", staticmethod(_connect))
    monkeypatch.setattr(AGI, "_stop", staticmethod(_stop))
    monkeypatch.setattr(AGI, "_service_clear_state", staticmethod(_clear_state))

    with pytest.raises(
        service_state_support.ServiceStateUnavailableError,
        match="legacy state unlink remains locked",
    ):
        await AGI.serve(env, action="stop", shutdown_on_stop=True)

    assert stop_calls == 1
    assert AGI._dask_client is None
    assert AGI._service_futures == {}
    assert AGI._service_workers == [worker]
    assert AGI._service_runtime_shutdown_proven is True
    assert AGI._service_cleanup_unproven is True
    assert AGI._lifecycle_service_token is not None

    result = await AGI.serve(env, action="stop", shutdown_on_stop=True)

    assert result["status"] == "stopped"
    assert result["pending"] == []
    assert stop_calls == 1
    assert clear_calls == 2
    assert AGI._service_futures == {}
    assert AGI._service_workers == []
    assert AGI._service_runtime_shutdown_proven is False
    assert AGI._service_cleanup_unproven is False
    assert AGI._lifecycle_service_token is None


@pytest.mark.asyncio
async def test_service_recover_without_stale_cleanup_keeps_state_on_failure(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    state_path = AGI._service_state_path(env)
    AGI._service_write_state(
        env,
        {
            "schema": "agi.service.state.v1",
            "target": env.target,
            "app": env.app,
            "mode": AGI.DASK_MODE,
            "run_type": "run --no-sync",
            "scheduler": "127.0.0.1:8786",
            "workers": {"127.0.0.1": 1},
            "args": {},
        },
    )

    async def _fail_connect(*_args, **_kwargs):
        raise RuntimeError("connect failed")

    monkeypatch.setattr(AGI, "_connect_scheduler_with_retry", staticmethod(_fail_connect))
    recovered = await AGI._service_recover(env, allow_stale_cleanup=False)
    assert recovered is False
    assert state_path.exists()


@pytest.mark.asyncio
async def test_service_recover_propagates_unexpected_attribute_error(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    AGI._service_write_state(
        env,
        {
            "schema": "agi.service.state.v1",
            "target": env.target,
            "app": env.app,
            "mode": AGI.DASK_MODE,
            "run_type": "run --no-sync",
            "workers": {"127.0.0.1": 1},
            "args": {"sample": 1},
        },
    )

    def _boom(_args):
        raise AttributeError("unexpected args mapper bug")

    monkeypatch.setattr(AGI, "_service_public_args", staticmethod(_boom))

    with pytest.raises(AttributeError, match="unexpected args mapper bug"):
        await AGI._service_recover(env, allow_stale_cleanup=True)


@pytest.mark.asyncio
async def test_service_recover_propagates_unexpected_value_error(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    AGI._service_write_state(
        env,
        {
            "schema": "agi.service.state.v1",
            "target": env.target,
            "app": env.app,
            "mode": AGI.DASK_MODE,
            "run_type": "run --no-sync",
            "workers": {"127.0.0.1": 1},
            "args": {"sample": 1},
        },
    )

    def _boom(_args):
        raise ValueError("unexpected service arg mapping")

    monkeypatch.setattr(AGI, "_service_public_args", staticmethod(_boom))

    with pytest.raises(ValueError, match="unexpected service arg mapping"):
        await AGI._service_recover(env, allow_stale_cleanup=True)


@pytest.mark.asyncio
async def test_service_recover_fails_when_no_workers_attached(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    AGI._service_write_state(
        env,
        {
            "schema": "agi.service.state.v1",
            "target": env.target,
            "app": env.app,
            "mode": AGI.DASK_MODE,
            "run_type": "run --no-sync",
            "scheduler": "127.0.0.1:8786",
            "workers": {"127.0.0.1": 1},
            "args": {},
        },
    )

    class _NoWorkerClient:
        status = "running"

        def scheduler_info(self):
            return {"workers": {}}

    async def _connect(*_args, **_kwargs):
        return _NoWorkerClient()

    monkeypatch.setattr(AGI, "_connect_scheduler_with_retry", staticmethod(_connect))
    recovered = await AGI._service_recover(env, allow_stale_cleanup=False)
    assert recovered is False


@pytest.mark.asyncio
async def test_agi_serve_status_idle_when_not_started():
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    status = await AGI.serve(env, action="status")
    assert status["status"] == "idle"
    assert status["workers"] == []
    assert status["pending"] == []
    assert status["health"]["schema"] == "agi.service.health.v1"
    assert status["health_path"]
    assert Path(status["health_path"]).exists()


@pytest.mark.asyncio
async def test_agi_serve_rejects_invalid_action():
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    with pytest.raises(ValueError, match=r"action must be"):
        await AGI.serve(env, action="invalid-action")


@pytest.mark.asyncio
async def test_agi_serve_stop_returns_idle_when_nothing_to_stop(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    calls = {"stop": 0, "clean": 0}
    AGI._dask_client = _FakeClient([])
    AGI._jobs = object()
    AGI._service_futures = {}
    AGI._service_workers = []

    async def _recover(_env, allow_stale_cleanup=False):
        return False

    async def _stop():
        calls["stop"] += 1

    monkeypatch.setattr(AGI, "_service_recover", staticmethod(_recover))
    monkeypatch.setattr(AGI, "_stop", staticmethod(_stop))
    monkeypatch.setattr(
        AGI,
        "_clean_job",
        staticmethod(lambda *_a, **_k: calls.__setitem__("clean", calls["clean"] + 1)),
    )

    result = await AGI.serve(env, action="stop", shutdown_on_stop=True)
    assert result["status"] == "idle"
    assert calls["stop"] == 1
    assert calls["clean"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("shutdown_on_stop", [False, True])
async def test_agi_serve_stop_retains_ownership_when_client_missing(
    monkeypatch,
    shutdown_on_stop,
):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    state_path = AGI._service_state_path(env)
    AGI._service_write_state(
        env,
        {
            "schema": "agi.service.state.v1",
            "service_workers": ["w1"],
            "service_loop_keys": {"w1": "loop-w1"},
        },
    )
    AGI._dask_client = None
    AGI._jobs = object()
    loop_future = _FakeFuture("running", key="loop-w1")
    AGI._service_futures = {"w1": loop_future}
    AGI._service_workers = ["w1"]
    calls = {"clean": 0, "stop": 0, "clear": 0, "reset": 0}

    async def _stop():
        calls["stop"] += 1

    monkeypatch.setattr(AGI, "_stop", staticmethod(_stop))
    monkeypatch.setattr(
        AGI,
        "_clean_job",
        staticmethod(lambda *_a, **_k: calls.__setitem__("clean", calls["clean"] + 1)),
    )
    monkeypatch.setattr(
        AGI,
        "_service_clear_state",
        staticmethod(lambda _env: calls.__setitem__("clear", calls["clear"] + 1)),
    )
    monkeypatch.setattr(
        AGI,
        "_reset_service_queue_state",
        staticmethod(lambda: calls.__setitem__("reset", calls["reset"] + 1)),
    )

    result = await AGI.serve(
        env,
        action="stop",
        shutdown_on_stop=shutdown_on_stop,
    )
    assert result["status"] == "error"
    assert result["recovery_required"] is True
    assert "w1" in result["pending"]
    assert calls == {"clean": 0, "stop": 0, "clear": 0, "reset": 0}
    assert AGI._service_futures == {"w1": loop_future}
    assert AGI._service_workers == ["w1"]
    assert AGI._service_cleanup_unproven is True
    assert AGI._lifecycle_service_token is not None
    assert state_path.exists()


@pytest.mark.asyncio
async def test_serve_stop_retains_ownership_when_state_clear_fails(monkeypatch):
    env = _minimal_app_env()
    worker = "127.0.0.1:8787"
    client = _FakeClient([worker])
    loop_future = _FakeFuture(status="finished", key="loop-8787")
    AGI._dask_client = client
    AGI._service_futures = {worker: loop_future}
    AGI._service_workers = [worker]

    with monkeypatch.context() as scoped:
        scoped.setattr(
            AGI,
            "_service_clear_state",
            staticmethod(
                lambda _env: (_ for _ in ()).throw(
                    service_state_support.ServiceStateUnavailableError(
                        "state unlink remains locked"
                    )
                )
            ),
        )

        with pytest.raises(
            service_state_support.ServiceStateUnavailableError,
            match="state unlink remains locked",
        ):
            await AGI.serve(env, action="stop", shutdown_on_stop=False)

    assert AGI._service_futures == {worker: loop_future}
    assert AGI._service_workers == [worker]
    assert AGI._service_cleanup_unproven is True
    assert AGI._lifecycle_service_token is not None


@pytest.mark.asyncio
async def test_serve_stop_retries_state_clear_after_runtime_already_shut_down(monkeypatch):
    env = _minimal_app_env()
    worker = "127.0.0.1:8787"

    class _CloseAwareClient(_FakeClient):
        def __init__(self):
            super().__init__([])
            self.shutdown_calls = 0

        def scheduler_info(self):
            if self.status == "closed":
                raise RuntimeError("Dask client is already closed")
            return super().scheduler_info()

        def submit(self, *args, **kwargs):
            if self.status == "closed":
                raise RuntimeError("Dask client is already closed")
            return super().submit(*args, **kwargs)

        async def shutdown(self):
            if self.status == "closed":
                raise RuntimeError("Dask client is already closed")
            self.shutdown_calls += 1
            self.status = "closed"

    client = _CloseAwareClient()
    loop_future = _FakeFuture(status="finished", key="loop-8787")
    AGI._dask_client = client
    AGI._service_futures = {worker: loop_future}
    AGI._service_workers = [worker]
    AGI._service_write_state(env, AGI._service_state_payload(env))

    async def _close_connections():
        return None

    monkeypatch.setattr(AGI, "_close_all_connections", staticmethod(_close_connections))
    monkeypatch.setattr(AGI, "_runtime_cleanup_task", None, raising=False)
    monkeypatch.setattr(AGI, "_runtime_cleanup_phase", None, raising=False)
    monkeypatch.setattr(AGI, "_worker_launch_tasks", [], raising=False)
    monkeypatch.setattr(AGI, "_scheduler_launch_tasks", [], raising=False)
    monkeypatch.setattr(AGI, "_startup_in_progress", False, raising=False)

    clear_calls = 0
    real_clear_state = AGI._service_clear_state

    def _clear_state(service_env):
        nonlocal clear_calls
        clear_calls += 1
        if clear_calls == 1:
            raise service_state_support.ServiceStateUnavailableError(
                "state unlink remains locked"
            )
        real_clear_state(service_env)

    monkeypatch.setattr(AGI, "_service_clear_state", staticmethod(_clear_state))

    with pytest.raises(
        service_state_support.ServiceStateUnavailableError,
        match="state unlink remains locked",
    ):
        await AGI.serve(env, action="stop", shutdown_on_stop=True)

    assert client.status == "closed"
    assert client.shutdown_calls == 1
    assert AGI._dask_client is None
    assert AGI._service_futures == {worker: loop_future}
    assert AGI._service_workers == [worker]
    assert AGI._service_cleanup_unproven is True
    assert AGI._lifecycle_service_token is not None

    result = await AGI.serve(env, action="stop", shutdown_on_stop=True)

    assert result["status"] == "stopped"
    assert result["pending"] == []
    assert client.shutdown_calls == 1
    assert clear_calls == 2
    assert AGI._service_futures == {}
    assert AGI._service_workers == []
    assert AGI._service_cleanup_unproven is False
    assert AGI._lifecycle_service_token is None


@pytest.mark.asyncio
async def test_serve_stop_missing_future_retries_state_clear_from_shutdown_proof(
    monkeypatch,
):
    env = _minimal_app_env()
    worker = "127.0.0.1:8787"
    client = _FakeClient([worker])
    AGI._dask_client = client
    AGI._service_futures = {}
    AGI._service_workers = [worker]
    AGI._service_write_state(
        env,
        {
            "schema": "agi.service.state.v1",
            "service_workers": [worker],
            "service_loop_keys": {},
        },
    )

    stop_calls = 0
    clear_calls = 0
    real_clear_state = AGI._service_clear_state

    async def _stop():
        nonlocal stop_calls
        stop_calls += 1
        AGI._dask_client = None

    def _clear_state(service_env):
        nonlocal clear_calls
        clear_calls += 1
        if clear_calls == 1:
            raise service_state_support.ServiceStateUnavailableError(
                "missing-Future state unlink remains locked"
            )
        real_clear_state(service_env)

    monkeypatch.setattr(AGI, "_stop", staticmethod(_stop))
    monkeypatch.setattr(AGI, "_service_clear_state", staticmethod(_clear_state))

    with pytest.raises(
        service_state_support.ServiceStateUnavailableError,
        match="missing-Future state unlink remains locked",
    ):
        await AGI.serve(env, action="stop", shutdown_on_stop=True)

    assert stop_calls == 1
    assert AGI._dask_client is None
    assert AGI._service_futures == {}
    assert AGI._service_workers == [worker]
    assert AGI._service_runtime_shutdown_proven is True
    assert AGI._service_cleanup_unproven is True
    assert AGI._lifecycle_service_token is not None

    result = await AGI.serve(env, action="stop", shutdown_on_stop=True)

    assert result["status"] == "stopped"
    assert result["pending"] == []
    assert stop_calls == 1
    assert clear_calls == 2
    assert AGI._service_futures == {}
    assert AGI._service_workers == []
    assert AGI._service_runtime_shutdown_proven is False
    assert AGI._service_cleanup_unproven is False
    assert AGI._lifecycle_service_token is None


@pytest.mark.asyncio
async def test_agi_serve_stop_handles_empty_targets_and_shuts_down(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    AGI._dask_client = _FakeClient([])
    AGI._service_futures = {}
    AGI._service_workers = []
    calls = {"stop": 0}

    async def _recover(_env, allow_stale_cleanup=False):
        AGI._dask_client = _FakeClient([])
        return True

    async def _connected(_client):
        return []

    async def _stop():
        calls["stop"] += 1

    monkeypatch.setattr(AGI, "_service_recover", staticmethod(_recover))
    monkeypatch.setattr(AGI, "_service_connected_workers", staticmethod(_connected))
    monkeypatch.setattr(AGI, "_stop", staticmethod(_stop))

    result = await AGI.serve(env, action="stop", shutdown_on_stop=True)
    assert result["status"] == "idle"
    assert calls["stop"] == 1


@pytest.mark.asyncio
async def test_agi_serve_health_action_writes_json(tmp_path):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    health_path = tmp_path / "export" / "health.json"
    payload = await AGI.serve(env, action="health", health_output_path=health_path)
    assert payload["schema"] == "agi.service.health.v1"
    assert payload["status"] == "idle"
    assert payload["path"] == str(health_path)
    assert health_path.exists()
    written = json.loads(health_path.read_text(encoding="utf-8"))
    assert written["schema"] == "agi.service.health.v1"
    assert written["status"] == "idle"


@pytest.mark.asyncio
async def test_agi_serve_start_status_stop_supports_agidataworker(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    env.base_worker_cls = "AgiDataWorker"
    fake_client = _FakeClient(["127.0.0.1:8787"])
    _install_fake_future_reacquisition(monkeypatch, fake_client)

    async def _fake_start(_scheduler):
        AGI._dask_client = fake_client

    async def _fake_sync():
        return None

    async def _fake_stop():
        return None

    monkeypatch.setattr(AGI, "_start", staticmethod(_fake_start))
    monkeypatch.setattr(AGI, "_sync", staticmethod(_fake_sync))
    monkeypatch.setattr(AGI, "_stop", staticmethod(_fake_stop))
    monkeypatch.setattr(
        agi_distributor_module,
        "wait",
        lambda futures, **_kwargs: (set(futures), set()),
    )

    started = await AGI.serve(
        env,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
        mode=AGI.DASK_MODE,
        action="start",
    )
    assert started["status"] == "running"
    assert AGI.install_worker_group == ["pandas-worker"]
    assert started["health"]["schema"] == "agi.service.health.v1"
    assert Path(started["health_path"]).exists()

    status = await AGI.serve(env, action="status")
    assert status["status"] == "running"
    assert status["workers"] == ["127.0.0.1:8787"]
    assert status["health"]["status"] == "running"
    assert Path(status["health_path"]).exists()

    stopped = await AGI.serve(env, action="stop", shutdown_on_stop=False)
    assert stopped["status"] == "stopped"
    assert stopped["health"]["status"] == "stopped"
    assert Path(stopped["health_path"]).exists()


@pytest.mark.asyncio
async def test_agi_serve_start_reuses_recovered_service(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    AGI._service_workers = ["127.0.0.1:8787"]
    AGI._dask_client = _FakeClient(["127.0.0.1:8787"])

    async def _recover(_env, allow_stale_cleanup=False):
        return True

    async def _auto_restart(_env, _client):
        return {"restarted": ["127.0.0.1:8787"], "reasons": {"127.0.0.1:8787": "stale-heartbeat"}}

    monkeypatch.setattr(AGI, "_service_recover", staticmethod(_recover))
    monkeypatch.setattr(AGI, "_service_auto_restart_unhealthy", staticmethod(_auto_restart))
    monkeypatch.setattr(AGI, "_service_cleanup_artifacts", staticmethod(lambda: {"done": 0, "failed": 0, "heartbeats": 0}))
    monkeypatch.setattr(AGI, "_service_worker_health", staticmethod(lambda workers: [{"worker": w, "healthy": True} for w in workers]))
    monkeypatch.setattr(AGI, "_service_queue_counts", staticmethod(lambda: {"pending": 0, "running": 0, "done": 0, "failed": 0}))

    started = await AGI.serve(env, action="start", mode=AGI.DASK_MODE)
    assert started["status"] == "running"
    assert started["recovered"] is True
    assert started["restarted_workers"] == ["127.0.0.1:8787"]


@pytest.mark.asyncio
async def test_agi_serve_start_rejects_invalid_workers_type(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)

    async def _recover(_env, allow_stale_cleanup=False):
        return False

    monkeypatch.setattr(AGI, "_service_recover", staticmethod(_recover))
    with pytest.raises(ValueError, match=r"workers must be a dict"):
        await AGI.serve(env, action="start", workers=["127.0.0.1"], mode=AGI.DASK_MODE)


@pytest.mark.asyncio
async def test_agi_serve_start_rejects_modes_without_dask(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)

    async def _recover(_env, allow_stale_cleanup=False):
        return False

    monkeypatch.setattr(AGI, "_service_recover", staticmethod(_recover))
    with pytest.raises(ValueError, match=r"requires Dask mode"):
        await AGI.serve(env, action="start", workers={"127.0.0.1": 1}, mode=AGI.PYTHON_MODE)


@pytest.mark.asyncio
async def test_agi_serve_start_rejects_invalid_mode_string(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)

    async def _recover(_env, allow_stale_cleanup=False):
        return False

    monkeypatch.setattr(AGI, "_service_recover", staticmethod(_recover))
    with pytest.raises(ValueError, match=r"parameter <mode> must only contain the letters"):
        await AGI.serve(env, action="start", workers={"127.0.0.1": 1}, mode="xyz")


@pytest.mark.asyncio
async def test_agi_serve_start_rejects_invalid_mode_type(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)

    async def _recover(_env, allow_stale_cleanup=False):
        return False

    monkeypatch.setattr(AGI, "_service_recover", staticmethod(_recover))
    with pytest.raises(ValueError, match=r"parameter <mode> must be an int or a string"):
        await AGI.serve(env, action="start", workers={"127.0.0.1": 1}, mode=[AGI.DASK_MODE])  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_agi_serve_start_uses_sync_when_client_already_running(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    env.base_worker_cls = "PandasWorker"
    AGI._dask_client = _FakeClient(["127.0.0.1:8787"])
    calls = {"sync": 0}

    async def _recover(_env, allow_stale_cleanup=False):
        return False

    async def _sync():
        calls["sync"] += 1
        return None

    monkeypatch.setattr(AGI, "_service_recover", staticmethod(_recover))
    monkeypatch.setattr(AGI, "_sync", staticmethod(_sync))

    result = await AGI.serve(
        env,
        action="start",
        workers={"127.0.0.1": 1},
        mode=AGI.DASK_MODE,
        shutdown_on_stop=False,
    )
    assert result["status"] == "running"
    assert calls["sync"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_stage",
    ["queue-init", "loop-submit", "state-write", "final-response"],
)
async def test_serve_start_failure_releases_owned_runtime_and_futures(
    monkeypatch,
    tmp_path,
    failure_stage,
):
    env = _minimal_app_env()
    env.base_worker_cls = "PandasWorker"
    calls = {"stop": 0, "clear": 0, "reset": 0, "clean_job": 0}

    class _StartupClient(_FakeClient):
        def __init__(self):
            super().__init__(["127.0.0.1:8787", "127.0.0.1:8788"])
            self.loop_futures: list[_FakeFuture] = []

        def submit(self, *args, **kwargs):
            fn = args[0] if args else None
            if getattr(fn, "__name__", "") == "loop":
                if failure_stage == "loop-submit" and self.loop_futures:
                    raise RuntimeError("injected loop-submit failure")
                future = _FakeFuture()
                self.loop_futures.append(future)
                return future
            return super().submit(*args, **kwargs)

    client = _StartupClient()

    async def _recover(*_args, **_kwargs):
        return False

    async def _start(_scheduler):
        AGI._dask_client = client

    async def _stop():
        calls["stop"] += 1

    monkeypatch.setattr(AGI, "_service_recover", staticmethod(_recover))
    monkeypatch.setattr(AGI, "_start", staticmethod(_start))
    monkeypatch.setattr(AGI, "_stop", staticmethod(_stop))
    monkeypatch.setattr(
        AGI,
        "_service_clear_state",
        staticmethod(lambda _env: calls.__setitem__("clear", calls["clear"] + 1)),
    )
    monkeypatch.setattr(
        AGI,
        "_reset_service_queue_state",
        staticmethod(lambda: calls.__setitem__("reset", calls["reset"] + 1)),
    )
    monkeypatch.setattr(
        AGI,
        "_clean_job",
        staticmethod(lambda *_args, **_kwargs: calls.__setitem__("clean_job", calls["clean_job"] + 1)),
    )

    if failure_stage == "queue-init":
        monkeypatch.setattr(
            AGI,
            "_init_service_queue",
            staticmethod(
                lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    RuntimeError("injected queue-init failure")
                )
            ),
        )

    monkeypatch.setattr(
        AGI,
        "_service_write_state",
        staticmethod(
            lambda *_args, **_kwargs: (
                (_ for _ in ()).throw(RuntimeError("injected state-write failure"))
                if failure_stage == "state-write"
                else None
            )
        ),
    )
    monkeypatch.setattr(
        AGI,
        "_service_finalize_response",
        staticmethod(
            lambda _env, payload, **_kwargs: (
                (_ for _ in ()).throw(RuntimeError("injected final-response failure"))
                if failure_stage == "final-response"
                else payload
            )
        ),
    )

    with pytest.raises(RuntimeError, match=f"injected {failure_stage} failure"):
        await service_lifecycle_support.serve(
            AGI,
            env,
            workers={"127.0.0.1": 2},
            mode=AGI.DASK_MODE,
            action="start",
            service_queue_dir=tmp_path / "queue",
            background_job_manager_factory=lambda: object(),
        )

    assert calls["stop"] == 1
    assert calls["clear"] == 1
    assert calls["reset"] == 1
    assert calls["clean_job"] == 1
    assert AGI._service_futures == {}
    assert AGI._service_workers == []
    if failure_stage == "loop-submit":
        assert len(client.loop_futures) == 1
    if failure_stage in {"loop-submit", "state-write", "final-response"}:
        assert client.loop_futures
        assert all(future.cancel_calls == 1 for future in client.loop_futures)


@pytest.mark.asyncio
async def test_failed_start_cleanup_retains_ownership_when_runtime_stop_is_unproven():
    warnings = []

    class _BadFuture:
        def cancel(self):
            raise RuntimeError("cancel cleanup failed")

    async def _bad_stop():
        raise RuntimeError("runtime cleanup failed")

    def _raise(message):
        raise RuntimeError(message)

    agi = SimpleNamespace(
        _service_futures={"worker": object()},
        _service_workers=["worker"],
        _jobs=object(),
        _service_clear_state=lambda _env: _raise("state cleanup must remain retained"),
        _reset_service_queue_state=lambda: _raise("queue cleanup must remain retained"),
        _stop=_bad_stop,
        _clean_job=lambda _force: _raise("job cleanup failed"),
    )
    future = _BadFuture()

    await service_lifecycle_support._cleanup_failed_service_start(
        agi,
        env=object(),
        owned_futures={"worker": future},
        runtime_started_here=True,
        log=SimpleNamespace(
            warning=lambda message, *args: warnings.append(message % args if args else message)
        ),
    )

    assert agi._service_futures == {"worker": future}
    assert agi._service_workers == ["worker"]
    assert agi._service_cleanup_unproven is True
    assert len(warnings) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime_stop_fails", [False, True])
async def test_failed_start_on_reused_runtime_uses_shutdown_for_unpublished_future(
    monkeypatch,
    tmp_path,
    runtime_stop_fails,
):
    env = _minimal_app_env()
    env.base_worker_cls = "PandasWorker"
    cleanup_calls = {"clear": 0, "reset": 0, "stop": 0}

    class _RunningAfterCancelFuture(_FakeFuture):
        def __init__(self):
            super().__init__(status="running", key="reused-runtime-loop")

        def cancel(self):
            self.cancel_calls += 1
            # Dask can acknowledge client-side cancellation while the worker
            # function continues to execute. Keep the execution status running
            # to reproduce that distinction.

    class _ReusedClient(_FakeClient):
        def __init__(self):
            super().__init__(["127.0.0.1:8787"])
            self.loop_future = _RunningAfterCancelFuture()
            self.break_futures: list[_FakeFuture] = []

        def submit(self, *args, **kwargs):
            fn = args[0] if args else None
            fn_name = getattr(fn, "__name__", "")
            self.submissions.append(
                {"fn": fn_name, "args": args[1:], "kwargs": kwargs}
            )
            if fn_name == "loop":
                return self.loop_future
            if fn_name == "break_loop":
                future = _FakeFuture(status="finished")
                self.break_futures.append(future)
                return future
            return _FakeFuture(status="finished")

    client = _ReusedClient()
    AGI._dask_client = client

    async def _recover(*_args, **_kwargs):
        return False

    async def _sync():
        return None

    async def _stop():
        cleanup_calls["stop"] += 1
        if runtime_stop_fails:
            raise RuntimeError("injected full runtime stop failure")
        client.loop_future.status = "finished"
        AGI._dask_client = None

    def _wait(futures, **_kwargs):
        if all(future in client.break_futures for future in futures):
            return set(futures), set()
        return set(), set(futures)

    monkeypatch.setattr(AGI, "_service_recover", staticmethod(_recover))
    monkeypatch.setattr(AGI, "_sync", staticmethod(_sync))
    monkeypatch.setattr(AGI, "_stop", staticmethod(_stop))
    monkeypatch.setattr(
        AGI,
        "_service_write_state",
        staticmethod(
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("injected state-write failure")
            )
        ),
    )
    monkeypatch.setattr(
        AGI,
        "_service_clear_state",
        staticmethod(
            lambda _env: cleanup_calls.__setitem__(
                "clear",
                cleanup_calls["clear"] + 1,
            )
        ),
    )
    monkeypatch.setattr(
        AGI,
        "_reset_service_queue_state",
        staticmethod(
            lambda: cleanup_calls.__setitem__(
                "reset",
                cleanup_calls["reset"] + 1,
            )
        ),
    )
    monkeypatch.setattr(AGI, "_clean_job", staticmethod(lambda *_args, **_kwargs: None))

    with pytest.raises(RuntimeError, match="injected state-write failure"):
        await service_lifecycle_support.serve(
            AGI,
            env,
            workers={"127.0.0.1": 1},
            mode=AGI.DASK_MODE,
            action="start",
            service_queue_dir=tmp_path / "queue",
            background_job_manager_factory=lambda: object(),
            wait_fn=_wait,
        )

    break_submissions = [
        submission
        for submission in client.submissions
        if submission["fn"] == "break_loop"
    ]
    assert len(break_submissions) == 1
    assert break_submissions[0]["kwargs"]["workers"] == ["127.0.0.1:8787"]
    assert break_submissions[0]["kwargs"]["allow_other_workers"] is False
    assert client.loop_future.cancel_calls == 1
    assert cleanup_calls["stop"] == 1
    if runtime_stop_fails:
        assert client.loop_future.status == "running"
        assert AGI._service_futures == {"127.0.0.1:8787": client.loop_future}
        assert AGI._service_workers == ["127.0.0.1:8787"]
        assert AGI._service_cleanup_unproven is True
        assert AGI._service_runtime_shutdown_proven is False
        assert cleanup_calls == {"clear": 0, "reset": 0, "stop": 1}
    else:
        assert client.loop_future.status == "finished"
        assert AGI._service_futures == {}
        assert AGI._service_workers == []
        assert AGI._service_cleanup_unproven is False
        assert AGI._service_runtime_shutdown_proven is False
        assert cleanup_calls == {"clear": 1, "reset": 1, "stop": 1}


@pytest.mark.asyncio
async def test_agi_serve_start_raises_when_client_not_obtained(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    env.base_worker_cls = "PandasWorker"
    AGI._dask_client = None

    async def _recover(_env, allow_stale_cleanup=False):
        return False

    async def _start(_scheduler):
        return True

    cleanup_calls = []

    async def _stop():
        cleanup_calls.append("stop")

    monkeypatch.setattr(AGI, "_service_recover", staticmethod(_recover))
    monkeypatch.setattr(AGI, "_start", staticmethod(_start))
    monkeypatch.setattr(AGI, "_stop", staticmethod(_stop))

    with pytest.raises(RuntimeError, match=r"Failed to obtain Dask client"):
        await AGI.serve(env, action="start", workers={"127.0.0.1": 1}, mode=AGI.DASK_MODE)
    assert cleanup_calls == ["stop"]
    assert AGI._startup_in_progress is False


@pytest.mark.asyncio
async def test_agi_serve_rejects_unsupported_base_worker():
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    env.base_worker_cls = "UnknownWorker"
    with pytest.raises(ValueError, match=r"Unsupported base worker class"):
        await AGI.serve(
            env,
            workers={"127.0.0.1": 1},
            mode=AGI.DASK_MODE,
            action="start",
        )


@pytest.mark.asyncio
async def test_agi_serve_resolves_sb3_trainer_worker_to_dag_group(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    env.base_worker_cls = "Sb3TrainerWorker"
    env._base_worker_module = "sb3_trainer_worker"
    fake_client = _FakeClient(["127.0.0.1:8787"])

    async def _recover(_env, allow_stale_cleanup=False):
        return False

    async def _fake_start(_scheduler):
        AGI._dask_client = fake_client

    async def _fake_sync():
        return None

    async def _fake_stop():
        return None

    monkeypatch.setattr(AGI, "_service_recover", staticmethod(_recover))
    monkeypatch.setattr(AGI, "_start", staticmethod(_fake_start))
    monkeypatch.setattr(AGI, "_sync", staticmethod(_fake_sync))
    monkeypatch.setattr(AGI, "_stop", staticmethod(_fake_stop))
    monkeypatch.setattr(
        agi_distributor_module,
        "wait",
        lambda futures, **_kwargs: (set(futures), set()),
    )

    started = await AGI.serve(
        env,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
        mode=AGI.DASK_MODE,
        action="start",
    )

    assert started["status"] == "running"
    assert AGI.install_worker_group == ["dag-worker"]


@pytest.mark.asyncio
async def test_agi_submit_requires_running_service():
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    with pytest.raises(RuntimeError, match=r"Service is not running"):
        await AGI.submit(env, work_plan=[], work_plan_metadata=[])


@pytest.mark.asyncio
async def test_agi_submit_requires_env_when_not_initialized():
    AGI.env = None
    with pytest.raises(ValueError, match=r"env is required"):
        await AGI.submit(env=None, work_plan=[], work_plan_metadata=[])


@pytest.mark.asyncio
async def test_agi_submit_fails_when_dask_client_is_unavailable():
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    AGI._service_futures = {"w1": _FakeFuture("running")}
    AGI._service_workers = ["w1"]
    AGI._dask_client = None
    with pytest.raises(RuntimeError, match=r"Dask client is unavailable"):
        await AGI.submit(env, work_plan=[["step"]], work_plan_metadata=[[{}]])


@pytest.mark.asyncio
async def test_agi_submit_rejects_invalid_workers_type_when_running(tmp_path):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    AGI._service_futures = {"w1": _FakeFuture("running")}
    AGI._service_workers = ["w1"]
    AGI._dask_client = _FakeClient(["127.0.0.1:8787"])
    AGI._service_apply_queue_root(tmp_path / "queue", create=True)
    with pytest.raises(ValueError, match=r"workers must be a dict"):
        await AGI.submit(
            env,
            workers=["127.0.0.1"],  # type: ignore[arg-type]
            work_plan=[["step"]],
            work_plan_metadata=[[{}]],
        )


@pytest.mark.asyncio
async def test_agi_submit_builds_distribution_when_plan_missing(monkeypatch, tmp_path):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    AGI._service_futures = {"w1": _FakeFuture("running")}
    AGI._service_workers = ["w1"]
    AGI._dask_client = _FakeClient(["127.0.0.1:8787"])
    AGI._workers = {"127.0.0.1": 1}
    AGI._args = {"alpha": 1}
    AGI._service_apply_queue_root(tmp_path / "queue", create=True)

    async def _do_distrib(_env, _workers, _args):
        return {"127.0.0.1": 1}, [["gen-step"]], [[{"auto": True}]]

    monkeypatch.setattr(agi_distributor_module.WorkDispatcher, "_do_distrib", staticmethod(_do_distrib))

    result = await AGI.submit(env, work_plan=None, work_plan_metadata=None, task_name="auto-plan")
    assert result["status"] == "queued"
    assert len(result["queued_files"]) == 1


@pytest.mark.asyncio
async def test_agi_submit_queues_tasks_for_service_workers(monkeypatch, tmp_path):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    env.base_worker_cls = "AgiDataWorker"
    fake_client = _FakeClient(["127.0.0.1:8787"])

    async def _fake_start(_scheduler):
        AGI._dask_client = fake_client

    async def _fake_sync():
        return None

    async def _fake_stop():
        return None

    monkeypatch.setattr(AGI, "_start", staticmethod(_fake_start))
    monkeypatch.setattr(AGI, "_sync", staticmethod(_fake_sync))
    monkeypatch.setattr(AGI, "_stop", staticmethod(_fake_stop))
    monkeypatch.setattr(
        agi_distributor_module,
        "wait",
        lambda futures, **_kwargs: (set(futures), set()),
    )

    await AGI.serve(
        env,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
        mode=AGI.DASK_MODE,
        action="start",
        service_queue_dir=tmp_path / "service_queue",
    )

    result = await AGI.submit(
        env,
        work_plan=[["mock-step"]],
        work_plan_metadata=[[{"step": 1}]],
        task_name="test-batch",
    )
    assert result["status"] == "queued"
    assert len(result["queued_files"]) == 1

    queued_file = Path(result["queued_files"][0])
    assert queued_file.exists()
    assert queued_file.name.endswith(".task.json")
    payload = json.loads(queued_file.read_text(encoding="utf-8"))
    assert payload["schema"] == "agi.service.task.v1"
    assert payload["task_name"] == "test-batch"
    # New contract: tasks are targeted by worker name only. A positional
    # worker_idx drifts after service_recover reorders _service_workers, so
    # submit() writes None and workers match on the stable name instead.
    assert payload["worker_idx"] is None
    assert payload["worker"] == "127.0.0.1:8787"

    stopped = await AGI.serve(env, action="stop", shutdown_on_stop=False)
    assert stopped["status"] == "stopped"


@pytest.mark.asyncio
async def test_agi_serve_status_recovers_persistent_state(monkeypatch, tmp_path):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    queue_dir = tmp_path / "service_queue"
    for name in ("pending", "running", "done", "failed"):
        (queue_dir / name).mkdir(parents=True, exist_ok=True)

    AGI._service_write_state(
        env,
        {
            "schema": "agi.service.state.v1",
            "target": env.target,
            "app": env.app,
            "mode": AGI.DASK_MODE,
            "run_type": "run --no-sync",
            "scheduler": "127.0.0.1:8786",
            "scheduler_ip": "127.0.0.1",
            "scheduler_port": 8786,
            "workers": {"127.0.0.1": 1},
            "service_workers": ["127.0.0.1:8787"],
            "service_loop_keys": {"127.0.0.1:8787": "persisted-loop-8787"},
            "queue_dir": str(queue_dir),
            "args": {},
            "poll_interval": 1.0,
            "stop_timeout": 30.0,
            "shutdown_on_stop": True,
        },
    )

    fake_client = _FakeClient(["127.0.0.1:8787"])
    _install_fake_future_reacquisition(monkeypatch, fake_client)

    async def _fake_connect(*_args, **_kwargs):
        return fake_client

    monkeypatch.setattr(AGI, "_connect_scheduler_with_retry", staticmethod(_fake_connect))
    recovery_calls = []
    monkeypatch.setattr(
        AGI,
        "_recover_orphaned_service_tasks",
        staticmethod(lambda: recovery_calls.append("recover") or {"recovered": 0, "preserved": 0}),
    )

    status = await AGI.serve(env, action="status")
    assert status["status"] == "running"
    assert status["workers"] == ["127.0.0.1:8787"]
    assert status["queue_dir"] == str(queue_dir)
    assert recovery_calls == ["recover"]
    assert AGI._service_futures["127.0.0.1:8787"].key == "persisted-loop-8787"

    stopped = await AGI.serve(env, action="stop", shutdown_on_stop=False)
    assert stopped["status"] == "stopped"
    assert stopped["pending"] == []
    assert AGI._service_read_state(env) is None


@pytest.mark.asyncio
async def test_serve_status_reports_recovery_required_for_legacy_ownership(
    monkeypatch,
    tmp_path,
):
    env = _minimal_app_env()
    worker = "127.0.0.1:8787"
    queue_dir = tmp_path / "service_queue"
    queue_dir.mkdir(parents=True)
    AGI._service_write_state(
        env,
        {
            "schema": "agi.service.state.v1",
            "target": env.target,
            "app": env.app,
            "mode": AGI.DASK_MODE,
            "run_type": "run --no-sync",
            "scheduler": "127.0.0.1:8786",
            "workers": {"127.0.0.1": 1},
            "service_workers": [worker],
            "queue_dir": str(queue_dir),
            "args": {},
        },
    )
    client = _FakeClient([worker])

    async def _connect(*_args, **_kwargs):
        return client

    async def _unexpected_restart(*_args, **_kwargs):
        raise AssertionError("auto-restart must not run without Future ownership")

    monkeypatch.setattr(AGI, "_connect_scheduler_with_retry", staticmethod(_connect))
    monkeypatch.setattr(
        AGI,
        "_service_auto_restart_unhealthy",
        staticmethod(_unexpected_restart),
    )

    status = await AGI.serve(env, action="status")

    assert status["status"] == "error"
    assert status["recovery_required"] is True
    assert status["pending"] == [worker]
    assert AGI._service_workers == [worker]
    assert AGI._service_futures == {}
    assert AGI._service_cleanup_unproven is True
    assert AGI._lifecycle_service_token is not None


@pytest.mark.asyncio
async def test_serve_status_treats_unreadable_state_as_retained_ownership():
    env = _minimal_app_env()
    state_path = AGI._service_state_path(env)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("{not-json", encoding="utf-8")

    status = await AGI.serve(env, action="status")

    assert status["status"] == "error"
    assert status["recovery_required"] is True
    assert AGI._service_cleanup_unproven is True
    assert AGI._lifecycle_service_token is not None
    assert state_path.exists()


@pytest.mark.asyncio
async def test_agi_submit_recovers_persistent_state(monkeypatch, tmp_path):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    queue_dir = tmp_path / "service_queue"
    for name in ("pending", "running", "done", "failed"):
        (queue_dir / name).mkdir(parents=True, exist_ok=True)

    AGI._service_write_state(
        env,
        {
            "schema": "agi.service.state.v1",
            "target": env.target,
            "app": env.app,
            "mode": AGI.DASK_MODE,
            "run_type": "run --no-sync",
            "scheduler": "127.0.0.1:8786",
            "scheduler_ip": "127.0.0.1",
            "scheduler_port": 8786,
            "workers": {"127.0.0.1": 1},
            "service_workers": ["127.0.0.1:8787"],
            "service_loop_keys": {"127.0.0.1:8787": "persisted-loop-8787"},
            "queue_dir": str(queue_dir),
            "args": {},
            "poll_interval": 1.0,
            "stop_timeout": 30.0,
            "shutdown_on_stop": True,
        },
    )

    fake_client = _FakeClient(["127.0.0.1:8787"])
    _install_fake_future_reacquisition(monkeypatch, fake_client)

    async def _fake_connect(*_args, **_kwargs):
        return fake_client

    monkeypatch.setattr(AGI, "_connect_scheduler_with_retry", staticmethod(_fake_connect))

    result = await AGI.submit(
        env,
        work_plan=[["recovered-step"]],
        work_plan_metadata=[[{"meta": "ok"}]],
        task_name="recovered-batch",
    )

    assert result["status"] == "queued"
    assert len(result["queued_files"]) == 1
    queued_file = Path(result["queued_files"][0])
    assert queued_file.exists()


@pytest.mark.asyncio
async def test_agi_status_auto_restarts_stale_heartbeat(monkeypatch, tmp_path):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    queue_dir = tmp_path / "service_queue"
    for name in ("pending", "running", "done", "failed", "heartbeats"):
        (queue_dir / name).mkdir(parents=True, exist_ok=True)

    AGI._service_write_state(
        env,
        {
            "schema": "agi.service.state.v1",
            "target": env.target,
            "app": env.app,
            "mode": AGI.DASK_MODE,
            "run_type": "run --no-sync",
            "scheduler": "127.0.0.1:8786",
            "scheduler_ip": "127.0.0.1",
            "scheduler_port": 8786,
            "workers": {"127.0.0.1": 1},
            "service_workers": ["127.0.0.1:8787"],
            "service_loop_keys": {"127.0.0.1:8787": "persisted-loop-8787"},
            "queue_dir": str(queue_dir),
            "args": {},
            "poll_interval": 0.1,
            "stop_timeout": 30.0,
            "shutdown_on_stop": True,
            "heartbeat_timeout": 0.5,
            "started_at": time.time() - 30.0,
        },
    )

    stale_hb = queue_dir / "heartbeats" / "000-127.0.0.1-8787.json"
    stale_hb.write_text(
        json.dumps(
            {
                "worker_id": 0,
                "worker": "127.0.0.1:8787",
                "timestamp": time.time() - 20.0,
                "state": "running",
            }
        ),
        encoding="utf-8",
    )

    fake_client = _FakeClient(["127.0.0.1:8787"])
    _install_fake_future_reacquisition(monkeypatch, fake_client)

    async def _fake_connect(*_args, **_kwargs):
        return fake_client

    monkeypatch.setattr(AGI, "_connect_scheduler_with_retry", staticmethod(_fake_connect))

    status = await AGI.serve(env, action="status")
    assert status["status"] == "running"
    assert status["restarted_workers"] == ["127.0.0.1:8787"]
    assert status["restart_reasons"]["127.0.0.1:8787"].startswith("stale-heartbeat")

    submitted = [entry["fn"] for entry in fake_client.submissions]
    assert "break_loop" in submitted
    assert "_new" in submitted
    assert "loop" in submitted


@pytest.mark.asyncio
async def test_agi_service_real_dask_e2e_self_heal_submit_stop(monkeypatch, tmp_path):
    distributed = pytest.importorskip("dask.distributed")
    local_cluster = distributed.LocalCluster
    client_cls = distributed.Client

    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    env.base_worker_cls = "AgiDataWorker"

    cluster = local_cluster(
        n_workers=1,
        threads_per_worker=2,
        processes=False,
        host="127.0.0.1",
        protocol="tcp",
        dashboard_address=None,
    )
    client = client_cls(cluster)

    async def _fake_start(_scheduler):
        AGI._dask_client = client
        AGI._scheduler = "127.0.0.1:8786"
        AGI._scheduler_ip = "127.0.0.1"
        AGI._scheduler_port = 8786

    async def _fake_sync():
        return None

    async def _fake_stop():
        return None

    monkeypatch.setattr(AGI, "_start", staticmethod(_fake_start))
    monkeypatch.setattr(AGI, "_sync", staticmethod(_fake_sync))
    monkeypatch.setattr(AGI, "_stop", staticmethod(_fake_stop))
    monkeypatch.setattr(BaseWorker, "_new", staticmethod(_real_service_stub_new))
    monkeypatch.setattr(BaseWorker, "loop", staticmethod(_real_service_stub_loop))
    monkeypatch.setattr(BaseWorker, "break_loop", staticmethod(_real_service_stub_break_loop))

    try:
        started = await asyncio.wait_for(
            AGI.serve(
                env,
                scheduler="127.0.0.1",
                workers={"127.0.0.1": 1},
                mode=AGI.DASK_MODE,
                action="start",
                service_queue_dir=tmp_path / "service_queue",
                poll_interval=0.05,
                heartbeat_timeout=0.2,
                stop_timeout=3.0,
            ),
            timeout=20.0,
        )
        assert started["status"] == "running"
        assert started["workers"], "expected at least one running service worker"
        worker = started["workers"][0]

        await asyncio.sleep(0.15)

        status = await asyncio.wait_for(
            AGI.serve(
                env,
                action="status",
                heartbeat_timeout=0.2,
            ),
            timeout=20.0,
        )
        assert worker in (status.get("restarted_workers") or [])

        submitted = await asyncio.wait_for(
            AGI.submit(
                env,
                work_plan=[["step"]],
                work_plan_metadata=[[{"meta": 1}]],
                task_name="e2e-batch",
            ),
            timeout=20.0,
        )
        assert submitted["status"] == "queued"
        assert submitted["queued_files"], "submit should enqueue at least one file"

        stopped = await asyncio.wait_for(
            AGI.serve(
                env,
                action="stop",
                shutdown_on_stop=False,
                stop_timeout=3.0,
            ),
            timeout=20.0,
        )
        assert stopped["status"] in {"stopped", "partial"}
    finally:
        try:
            AGI._dask_client = None
            client.close()
        except Exception:
            pass
        try:
            cluster.close()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_service_recover_missing_scheduler_preserves_ownership(monkeypatch, tmp_path):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    queue_root = tmp_path / "queue"
    queue_root.mkdir(parents=True, exist_ok=True)
    calls = {"cleared": 0, "reset": 0}

    monkeypatch.setattr(
        AGI,
        "_service_read_state",
        staticmethod(
            lambda _env: {
                "mode": AGI.DASK_MODE,
                "run_type": "run --no-sync",
                "workers": {"127.0.0.1": 1},
                "queue_dir": str(queue_root),
                "service_workers": [],
            }
        ),
    )
    monkeypatch.setattr(
        AGI,
        "_service_clear_state",
        staticmethod(lambda _env: calls.__setitem__("cleared", calls["cleared"] + 1)),
    )
    monkeypatch.setattr(
        AGI,
        "_reset_service_queue_state",
        staticmethod(lambda: calls.__setitem__("reset", calls["reset"] + 1)),
    )

    recovered = await AGI._service_recover(env, allow_stale_cleanup=True)

    assert recovered is False
    assert calls == {"cleared": 0, "reset": 0}
    assert AGI._service_cleanup_unproven is True


@pytest.mark.asyncio
async def test_serve_stop_transient_recovery_failure_preserves_state_and_lease(
    monkeypatch,
    tmp_path,
):
    env = _minimal_app_env()
    queue_root = tmp_path / "queue"
    queue_root.mkdir(parents=True)
    state_path = AGI._service_state_path(env)
    AGI._service_write_state(
        env,
        {
            "schema": "agi.service.state.v1",
            "target": env.target,
            "app": env.app,
            "mode": AGI.DASK_MODE,
            "run_type": "run --no-sync",
            "scheduler": "127.0.0.1:8786",
            "workers": {"127.0.0.1": 1},
            "service_workers": ["127.0.0.1:8787"],
            "service_loop_keys": {"127.0.0.1:8787": "persisted-loop-8787"},
            "queue_dir": str(queue_root),
            "args": {},
        },
    )

    async def _fail_connect(*_args, **_kwargs):
        raise RuntimeError("transient scheduler connection failure")

    monkeypatch.setattr(AGI, "_connect_scheduler_with_retry", staticmethod(_fail_connect))

    result = await AGI.serve(env, action="stop", shutdown_on_stop=True)

    assert result["status"] == "error"
    assert result["recovery_required"] is True
    assert result["pending"] == ["127.0.0.1:8787"]
    assert AGI._service_workers == ["127.0.0.1:8787"]
    assert AGI._service_cleanup_unproven is True
    assert AGI._lifecycle_service_token is not None
    assert state_path.exists()


@pytest.mark.asyncio
async def test_serve_status_reports_missing_client_and_future_states(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    AGI._service_workers = ["w-finished", "w-running"]
    AGI._service_futures = {
        "w-finished": _FakeFuture(status="finished"),
        "w-running": _FakeFuture(status="running"),
    }
    AGI._service_queue_root = Path("/tmp/service-queue")
    AGI._dask_client = None

    monkeypatch.setattr(AGI, "_service_cleanup_artifacts", staticmethod(lambda: {"done": 0}))
    monkeypatch.setattr(AGI, "_service_queue_counts", staticmethod(lambda: {"pending": 0}))
    monkeypatch.setattr(
        AGI,
        "_service_worker_health",
        staticmethod(lambda workers: [{"worker": worker, "healthy": True} for worker in workers]),
    )
    monkeypatch.setattr(AGI, "_service_finalize_response", staticmethod(lambda _env, payload, **_kwargs: payload))
    
    async def _no_restart(_env, _client):
        return {"restarted": [], "reasons": {}}

    monkeypatch.setattr(AGI, "_service_auto_restart_unhealthy", staticmethod(_no_restart))

    missing = await service_lifecycle_support.serve(
        AGI,
        env,
        action="status",
        background_job_manager_factory=lambda: object(),
    )

    assert missing["status"] == "error"
    assert missing["pending"] == ["w-finished", "w-running"]

    AGI._dask_client = SimpleNamespace(status="running")
    degraded = await service_lifecycle_support.serve(
        AGI,
        env,
        action="status",
        background_job_manager_factory=lambda: object(),
    )
    assert degraded["status"] == "degraded"
    assert degraded["workers"] == ["w-running"]
    assert degraded["pending"] == ["w-finished"]

    AGI._service_futures = {"w-finished": _FakeFuture(status="finished")}
    stopped = await service_lifecycle_support.serve(
        AGI,
        env,
        action="status",
        background_job_manager_factory=lambda: object(),
    )
    assert stopped["status"] == "stopped"
    assert stopped["workers"] == []
    assert stopped["pending"] == ["w-finished"]


@pytest.mark.asyncio
async def test_serve_status_reports_dead_retained_launch_ownership(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)

    class _DoneLaunchTask:
        def done(self):
            return True

        def cancelled(self):
            return False

        def exception(self):
            return ConnectionError("scheduler transport exited")

    AGI._service_workers = ["w1"]
    AGI._service_futures = {"w1": _FakeFuture(status="running")}
    AGI._dask_client = SimpleNamespace(status="running")
    AGI._scheduler_launch_tasks = {_DoneLaunchTask()}
    monkeypatch.setattr(
        AGI,
        "_service_finalize_response",
        staticmethod(lambda _env, payload, **_kwargs: payload),
    )

    result = await service_lifecycle_support.serve(
        AGI,
        env,
        action="status",
        background_job_manager_factory=lambda: object(),
    )

    assert result["status"] == "error"
    assert result["launch_errors"] == ["scheduler transport exited"]
    assert "action='stop'" in result["message"]

    with pytest.raises(RuntimeError, match="launch ownership is unhealthy"):
        await service_lifecycle_support.serve(
            AGI,
            env,
            action="start",
            background_job_manager_factory=lambda: object(),
        )


@pytest.mark.asyncio
async def test_serve_stop_handles_partial_timeout_and_empty_future_map(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    class _PartialStopClient:
        def submit(self, fn, *_args, **_kwargs):
            return _FakeFuture(
                status="finished",
                kind=getattr(fn, "__name__", ""),
            )

        def gather(self, *_args, **_kwargs):
            return None

        def scheduler_info(self):
            return {"workers": {"tcp://w1": {}, "tcp://w2": {}}}

    AGI._dask_client = _PartialStopClient()
    first = _FakeFuture(status="running", key="loop-w1")
    second = _FakeFuture(status="running", key="loop-w2")
    AGI._service_futures = {"w1": first, "w2": second}
    AGI._service_workers = ["w1", "w2"]
    warnings = []
    stops = []
    cleanups = {"clear": 0, "reset": 0}

    monkeypatch.setattr(AGI, "_service_finalize_response", staticmethod(lambda _env, payload, **_kwargs: payload))
    monkeypatch.setattr(
        AGI,
        "_service_clear_state",
        staticmethod(lambda _env: cleanups.__setitem__("clear", cleanups["clear"] + 1)),
    )
    monkeypatch.setattr(
        AGI,
        "_reset_service_queue_state",
        staticmethod(lambda: cleanups.__setitem__("reset", cleanups["reset"] + 1)),
    )
    monkeypatch.setattr(AGI, "_service_write_state", staticmethod(lambda *_args: None))

    async def _fake_stop():
        stops.append("stop")

    monkeypatch.setattr(AGI, "_stop", staticmethod(_fake_stop))

    def _partial_wait(futures, **_kwargs):
        futures[0].status = "finished"
        return {futures[0]}, set(futures[1:])

    result = await service_lifecycle_support.serve(
        AGI,
        env,
        action="stop",
        wait_fn=_partial_wait,
        log=SimpleNamespace(
            info=lambda *_args, **_kwargs: None,
            warning=lambda message, *args: warnings.append(message % args if args else message),
            error=lambda *_args, **_kwargs: None,
        ),
        background_job_manager_factory=lambda: object(),
    )

    assert result["status"] == "partial"
    assert result["pending"] == ["w2"]
    assert warnings
    assert stops == []
    assert cleanups == {"clear": 0, "reset": 0}
    assert AGI._service_futures == {"w2": second}
    assert AGI._service_workers == ["w2"]
    assert AGI._service_cleanup_unproven is True

    AGI._service_futures = {}
    AGI._service_workers = ["w3"]
    AGI._service_cleanup_unproven = False
    result = await service_lifecycle_support.serve(
        AGI,
        env,
        action="stop",
        shutdown_on_stop=False,
        log=SimpleNamespace(
            info=lambda *_args, **_kwargs: None,
            warning=lambda *_args, **_kwargs: None,
            error=lambda *_args, **_kwargs: None,
        ),
        background_job_manager_factory=lambda: object(),
    )

    assert result["status"] == "partial"
    assert result["workers"] == []
    assert result["pending"] == ["w3"]
    assert result["recovery_required"] is True
    assert AGI._service_workers == ["w3"]
    assert AGI._service_cleanup_unproven is True


@pytest.mark.asyncio
async def test_serve_stop_skips_dead_workers_and_tolerates_break_gather_error(monkeypatch):
    env = _minimal_app_env()
    submissions = []

    class _StopClient:
        status = "running"

        def submit(self, *_args, **kwargs):
            submissions.append(kwargs)
            return _FakeFuture(status="submitted")

        _gather_calls = 0

        def gather(self, futures, errors="raise"):
            # First gather is the break_loop batch: simulate a dead worker.
            _StopClient._gather_calls += 1
            if _StopClient._gather_calls == 1:
                raise RuntimeError("break_loop gather failed: worker is gone")
            return [None for _ in futures]

        def scheduler_info(self):
            return {"workers": {"tcp://w-alive": {}}}

    AGI._dask_client = _StopClient()
    AGI._service_futures = {
        "w-alive": _FakeFuture(status="finished"),
        "w-dead": _FakeFuture(status="finished"),
    }
    AGI._service_workers = ["w-alive", "w-dead"]
    cleanups = {"clear_state": 0, "reset_queue": 0}
    stops = []

    monkeypatch.setattr(AGI, "_service_finalize_response", staticmethod(lambda _env, payload, **_kwargs: payload))
    monkeypatch.setattr(
        AGI,
        "_service_clear_state",
        staticmethod(lambda _env: cleanups.__setitem__("clear_state", cleanups["clear_state"] + 1)),
    )
    monkeypatch.setattr(
        AGI,
        "_reset_service_queue_state",
        staticmethod(lambda: cleanups.__setitem__("reset_queue", cleanups["reset_queue"] + 1)),
    )

    async def _fake_stop():
        stops.append("stop")

    monkeypatch.setattr(AGI, "_stop", staticmethod(_fake_stop))

    result = await service_lifecycle_support.serve(
        AGI,
        env,
        action="stop",
        wait_fn=lambda futures, **_kwargs: (set(futures), set()),
        background_job_manager_factory=lambda: object(),
    )

    # break_loop is only submitted to workers still attached to the
    # scheduler, and a failing gather no longer aborts the stop: cleanup and
    # _stop() must always run.
    break_keys = [entry["key"] for entry in submissions]
    assert any("w-alive" in key for key in break_keys)
    assert not any("w-dead" in key for key in break_keys)
    assert result["status"] == "stopped"
    assert cleanups == {"clear_state": 1, "reset_queue": 1}
    assert stops == ["stop"]
    assert AGI._service_futures == {}


@pytest.mark.asyncio
async def test_serve_stop_handles_wait_timeout_error_as_partial(monkeypatch):
    env = _minimal_app_env()
    AGI._dask_client = SimpleNamespace(
        submit=lambda *_args, **_kwargs: _FakeFuture(status="submitted"),
        gather=lambda futures, errors="raise": None,
    )
    finished = _FakeFuture(status="finished")
    pending = _FakeFuture(status="pending")
    AGI._service_futures = {"w-done": finished, "w-stuck": pending}
    AGI._service_workers = ["w-done", "w-stuck"]
    cleanups = {"clear_state": 0, "reset_queue": 0}

    monkeypatch.setattr(AGI, "_service_finalize_response", staticmethod(lambda _env, payload, **_kwargs: payload))
    monkeypatch.setattr(
        AGI,
        "_service_clear_state",
        staticmethod(lambda _env: cleanups.__setitem__("clear_state", cleanups["clear_state"] + 1)),
    )
    monkeypatch.setattr(
        AGI,
        "_reset_service_queue_state",
        staticmethod(lambda: cleanups.__setitem__("reset_queue", cleanups["reset_queue"] + 1)),
    )

    def _raising_wait(_futures, **_kwargs):
        # Real dask.distributed.wait raises TimeoutError on timeout instead
        # of returning a partial (done, not_done) tuple.
        raise TimeoutError("waited too long")

    result = await service_lifecycle_support.serve(
        AGI,
        env,
        action="stop",
        shutdown_on_stop=False,
        wait_fn=_raising_wait,
        background_job_manager_factory=lambda: object(),
    )

    assert result["status"] == "partial"
    assert result["workers"] == ["w-done"]
    assert result["pending"] == ["w-stuck"]
    assert cleanups == {"clear_state": 0, "reset_queue": 0}
    assert AGI._service_futures == {"w-stuck": pending}
    assert AGI._service_workers == ["w-stuck"]
    assert AGI._service_cleanup_unproven is True


@pytest.mark.asyncio
async def test_serve_start_rejects_duplicate_service_loops(monkeypatch):
    env = _minimal_app_env()
    AGI._service_futures = {"w1": _FakeFuture(status="running")}

    async def _fake_recover(*_args, **_kwargs):
        return False

    monkeypatch.setattr(AGI, "_service_recover", staticmethod(_fake_recover))

    with pytest.raises(RuntimeError, match="Service loop already running"):
        await AGI.serve(env, action="start")


@pytest.mark.asyncio
async def test_serve_start_uses_worker_default_when_workers_missing(monkeypatch):
    env = _minimal_app_env()
    AGI._service_futures = {}
    AGI._service_state = None
    AGI._worker_default = {"127.0.0.1": 1}
    AGI._run_type = "run --no-sync"
    AGI._mode = AGI.DASK_MODE
    AGI._service_queue_pending = None
    AGI._service_queue_running = None
    AGI._service_queue_done = None
    AGI._service_queue_failed = None
    AGI._service_queue_heartbeats = None
    AGI._service_workers = []
    AGI._dask_client = _FakeClient(["127.0.0.1:8787"])

    async def _fake_recover(*_args, **_kwargs):
        return False

    async def _fake_sync(*_args, **_kwargs):
        return None

    monkeypatch.setattr(AGI, "_service_recover", staticmethod(_fake_recover))
    monkeypatch.setattr(AGI, "_sync", staticmethod(_fake_sync))
    monkeypatch.setattr(AGI, "_service_state_path", staticmethod(lambda _env: Path("/tmp/service_state.json")))
    monkeypatch.setattr(AGI, "_service_health_path", staticmethod(lambda _env: Path("/tmp/service_health.json")))
    monkeypatch.setattr(AGI, "_service_queue_paths", staticmethod(lambda _env: {"pending": Path("/tmp/pending"), "running": Path("/tmp/running"), "done": Path("/tmp/done"), "failed": Path("/tmp/failed"), "heartbeats": Path("/tmp/heartbeats")}))
    monkeypatch.setattr(AGI, "_service_connected_workers", staticmethod(lambda _client: []))
    monkeypatch.setattr(AGI, "_service_write_state", staticmethod(lambda *_a, **_k: None))
    monkeypatch.setattr(AGI, "_service_write_health_payload", staticmethod(lambda *_a, **_k: {}))
    monkeypatch.setattr(AGI, "_service_finalize_response", staticmethod(lambda _env, payload, **_kwargs: payload))
    monkeypatch.setattr(AGI, "_service_clear_state", staticmethod(lambda _env: None))
    monkeypatch.setattr(AGI, "_reset_service_queue_state", staticmethod(lambda: None))

    await AGI.serve(env, action="start")

    assert AGI._workers == {"127.0.0.1": 1}


@pytest.mark.asyncio
async def test_submit_initializes_queue_and_raises_without_active_service_workers(monkeypatch, tmp_path):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="minimal_app_project", verbose=0)
    AGI.env = env
    AGI._service_queue_pending = None
    AGI._service_futures = {}
    AGI._service_workers = []
    AGI._workers = {"127.0.0.1": 1}
    AGI._dask_client = SimpleNamespace(status="running")

    calls = {"init_queue": 0}

    async def _fake_recover(_env):
        return True

    async def _fake_connected(_client):
        return []

    monkeypatch.setattr(AGI, "_service_recover", staticmethod(_fake_recover))
    monkeypatch.setattr(
        AGI,
        "_init_service_queue",
        staticmethod(
            lambda _env, service_queue_dir=None: calls.__setitem__("init_queue", calls["init_queue"] + 1)
            or AGI._service_apply_queue_root(tmp_path / "queue", create=True)
        ),
    )
    monkeypatch.setattr(AGI, "_service_connected_workers", staticmethod(_fake_connected))

    with pytest.raises(RuntimeError, match="No active service workers available"):
        await AGI.submit(env=env, work_plan=[], work_plan_metadata=[])

    assert calls["init_queue"] == 1
