import asyncio
import json
import pickle
import time
from pathlib import Path

import pytest

from agi_cluster.agi_distributor import AGI
import agi_cluster.agi_distributor.agi_distributor as agi_distributor_module
from agi_cluster.agi_distributor import service_lifecycle_support
from agi_env import AgiEnv
from agi_node.agi_dispatcher import BaseWorker

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

    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
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
    def __init__(self, status: str = "pending"):
        self.status = status


class _FakeClient:
    def __init__(self, workers: list[str]):
        self._workers = workers
        self.status = "running"
        self.submissions: list[dict[str, object]] = []

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
        return _FakeFuture()

    def gather(self, futures, errors="raise"):
        if isinstance(futures, list):
            return [None for _ in futures]
        return []

    def scheduler_info(self):
        return {"workers": {f"tcp://{worker}": {} for worker in self._workers}}


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


def test_prepare_service_worker_args_sets_queue_bound_service_args(tmp_path):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    AGI._args = {"alpha": 1}
    AGI._service_apply_queue_root(tmp_path / "queue", create=True)

    worker_args = service_lifecycle_support._prepare_service_worker_args(AGI, env)

    assert worker_args["alpha"] == 1
    assert worker_args["_agi_service_mode"] is True
    assert worker_args["_agi_service_queue_dir"] == str(AGI._service_queue_root)
    assert AGI._service_worker_args == worker_args


def test_submit_service_worker_inits_submits_new_for_each_worker(tmp_path):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
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
    assert submit_calls[1]["kwargs"]["key"] == "agi-test-init-mycode-127.0.0.1-8788"


def test_submit_service_loops_returns_worker_future_map():
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
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
    assert loop_call["kwargs"]["key"] == "agi-loop-loop-mycode-127.0.0.1-8787"


@pytest.mark.asyncio
async def test_service_restart_workers_returns_empty_for_empty_input():
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    restarted = await AGI._service_restart_workers(env, client=_FakeClient([]), workers_to_restart=[])
    assert restarted == []


@pytest.mark.asyncio
async def test_service_restart_workers_restarts_and_tracks_futures(monkeypatch, tmp_path):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    AGI._args = {"sample": 1}
    AGI._mode = AGI.DASK_MODE
    AGI._service_poll_interval = 0.2
    AGI._service_queue_root = None
    AGI._service_workers = []
    AGI._service_futures = {}

    class _RestartClient:
        def __init__(self):
            self.calls = []
            self._gather_calls = 0

        def scheduler_info(self):
            return {"workers": {"tcp://127.0.0.1:8787": {}}}

        def submit(self, fn, *args, **kwargs):
            self.calls.append(getattr(fn, "__name__", str(fn)))
            return _FakeFuture(status="running")

        def gather(self, futures, errors="raise"):
            self._gather_calls += 1
            if self._gather_calls == 1:
                raise RuntimeError("ignore break gather failure")
            return [None for _ in futures]

    client = _RestartClient()

    def _fake_init_queue(_env):
        return AGI._service_apply_queue_root(tmp_path / "queue", create=True)

    monkeypatch.setattr(AGI, "_init_service_queue", staticmethod(_fake_init_queue))

    restarted = await AGI._service_restart_workers(env, client, ["127.0.0.1:8787"])
    assert restarted == ["127.0.0.1:8787"]
    assert AGI._service_futures["127.0.0.1:8787"].status == "running"
    assert {"break_loop", "_new", "loop"}.issubset(set(client.calls))


@pytest.mark.asyncio
async def test_service_auto_restart_unhealthy_returns_empty_without_workers(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    AGI._service_workers = []

    async def _connected(_client):
        return []

    monkeypatch.setattr(AGI, "_service_connected_workers", staticmethod(_connected))
    result = await AGI._service_auto_restart_unhealthy(env, client=object())
    assert result == {"restarted": [], "reasons": {}}


@pytest.mark.asyncio
async def test_service_auto_restart_unhealthy_restarts_and_persists(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
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
async def test_service_recover_allow_stale_cleanup_clears_state_on_failure(tmp_path, monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
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
            "queue_dir": str(queue_dir),
            "args": {},
        },
    )

    async def _fail_connect(*_args, **_kwargs):
        raise RuntimeError("connect failed")

    monkeypatch.setattr(AGI, "_connect_scheduler_with_retry", staticmethod(_fail_connect))

    recovered = await AGI._service_recover(env, allow_stale_cleanup=True)
    assert recovered is False
    assert AGI._service_read_state(env) is None
    assert AGI._service_queue_root is None
    assert AGI._service_workers == []
    assert AGI._service_futures == {}


@pytest.mark.asyncio
async def test_service_recover_without_stale_cleanup_keeps_state_on_failure(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    state_path = AGI._service_state_path(env)
    AGI._service_write_state(
        env,
        {
            "schema": "agi.service.state.v1",
            "target": env.target,
            "app": env.app,
            "mode": AGI.DASK_MODE,
            "run_type": "run --no-sync",
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
async def test_service_recover_fails_when_no_workers_attached(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
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
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    status = await AGI.serve(env, action="status")
    assert status["status"] == "idle"
    assert status["workers"] == []
    assert status["pending"] == []
    assert status["health"]["schema"] == "agi.service.health.v1"
    assert status["health_path"]
    assert Path(status["health_path"]).exists()


@pytest.mark.asyncio
async def test_agi_serve_rejects_invalid_action():
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    with pytest.raises(ValueError, match=r"action must be"):
        await AGI.serve(env, action="invalid-action")


@pytest.mark.asyncio
async def test_agi_serve_stop_returns_idle_when_nothing_to_stop(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
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
async def test_agi_serve_stop_returns_error_when_client_missing(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    AGI._dask_client = None
    AGI._jobs = object()
    AGI._service_futures = {"w1": _FakeFuture("running")}
    AGI._service_workers = ["w1"]
    calls = {"clean": 0}

    monkeypatch.setattr(
        AGI,
        "_clean_job",
        staticmethod(lambda *_a, **_k: calls.__setitem__("clean", calls["clean"] + 1)),
    )

    result = await AGI.serve(env, action="stop", shutdown_on_stop=False)
    assert result["status"] == "error"
    assert "w1" in result["pending"]
    assert calls["clean"] == 1


@pytest.mark.asyncio
async def test_agi_serve_stop_handles_empty_targets_and_shuts_down(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
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
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
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
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
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
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
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
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)

    async def _recover(_env, allow_stale_cleanup=False):
        return False

    monkeypatch.setattr(AGI, "_service_recover", staticmethod(_recover))
    with pytest.raises(ValueError, match=r"workers must be a dict"):
        await AGI.serve(env, action="start", workers=["127.0.0.1"], mode=AGI.DASK_MODE)


@pytest.mark.asyncio
async def test_agi_serve_start_rejects_modes_without_dask(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)

    async def _recover(_env, allow_stale_cleanup=False):
        return False

    monkeypatch.setattr(AGI, "_service_recover", staticmethod(_recover))
    with pytest.raises(ValueError, match=r"requires Dask mode"):
        await AGI.serve(env, action="start", workers={"127.0.0.1": 1}, mode=AGI.PYTHON_MODE)


@pytest.mark.asyncio
async def test_agi_serve_start_rejects_invalid_mode_string(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)

    async def _recover(_env, allow_stale_cleanup=False):
        return False

    monkeypatch.setattr(AGI, "_service_recover", staticmethod(_recover))
    with pytest.raises(ValueError, match=r"parameter <mode> must only contain the letters"):
        await AGI.serve(env, action="start", workers={"127.0.0.1": 1}, mode="xyz")


@pytest.mark.asyncio
async def test_agi_serve_start_rejects_invalid_mode_type(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)

    async def _recover(_env, allow_stale_cleanup=False):
        return False

    monkeypatch.setattr(AGI, "_service_recover", staticmethod(_recover))
    with pytest.raises(ValueError, match=r"parameter <mode> must be an int or a string"):
        await AGI.serve(env, action="start", workers={"127.0.0.1": 1}, mode=[AGI.DASK_MODE])  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_agi_serve_start_uses_sync_when_client_already_running(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
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
async def test_agi_serve_start_raises_when_client_not_obtained(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    env.base_worker_cls = "PandasWorker"
    AGI._dask_client = None

    async def _recover(_env, allow_stale_cleanup=False):
        return False

    async def _start(_scheduler):
        return True

    monkeypatch.setattr(AGI, "_service_recover", staticmethod(_recover))
    monkeypatch.setattr(AGI, "_start", staticmethod(_start))

    with pytest.raises(RuntimeError, match=r"Failed to obtain Dask client"):
        await AGI.serve(env, action="start", workers={"127.0.0.1": 1}, mode=AGI.DASK_MODE)


@pytest.mark.asyncio
async def test_agi_serve_rejects_unsupported_base_worker():
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
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
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
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
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    with pytest.raises(RuntimeError, match=r"Service is not running"):
        await AGI.submit(env, work_plan=[], work_plan_metadata=[])


@pytest.mark.asyncio
async def test_agi_submit_requires_env_when_not_initialized():
    AGI.env = None
    with pytest.raises(ValueError, match=r"env is required"):
        await AGI.submit(env=None, work_plan=[], work_plan_metadata=[])


@pytest.mark.asyncio
async def test_agi_submit_fails_when_dask_client_is_unavailable():
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    AGI._service_futures = {"w1": _FakeFuture("running")}
    AGI._service_workers = ["w1"]
    AGI._dask_client = None
    with pytest.raises(RuntimeError, match=r"Dask client is unavailable"):
        await AGI.submit(env, work_plan=[["step"]], work_plan_metadata=[[{}]])


@pytest.mark.asyncio
async def test_agi_submit_rejects_invalid_workers_type_when_running(tmp_path):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
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
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
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
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
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
    with open(queued_file, "rb") as stream:
        payload = pickle.load(stream)
    assert payload["task_name"] == "test-batch"
    assert payload["worker_idx"] == 0
    assert payload["worker"] == "127.0.0.1:8787"

    stopped = await AGI.serve(env, action="stop", shutdown_on_stop=False)
    assert stopped["status"] == "stopped"


@pytest.mark.asyncio
async def test_agi_serve_status_recovers_persistent_state(monkeypatch, tmp_path):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
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
            "queue_dir": str(queue_dir),
            "args": {},
            "poll_interval": 1.0,
            "stop_timeout": 30.0,
            "shutdown_on_stop": True,
        },
    )

    fake_client = _FakeClient(["127.0.0.1:8787"])

    async def _fake_connect(*_args, **_kwargs):
        return fake_client

    monkeypatch.setattr(AGI, "_connect_scheduler_with_retry", staticmethod(_fake_connect))

    status = await AGI.serve(env, action="status")
    assert status["status"] == "running"
    assert status["workers"] == ["127.0.0.1:8787"]
    assert status["queue_dir"] == str(queue_dir)


@pytest.mark.asyncio
async def test_agi_submit_recovers_persistent_state(monkeypatch, tmp_path):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
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
            "queue_dir": str(queue_dir),
            "args": {},
            "poll_interval": 1.0,
            "stop_timeout": 30.0,
            "shutdown_on_stop": True,
        },
    )

    fake_client = _FakeClient(["127.0.0.1:8787"])

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
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
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

    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
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
