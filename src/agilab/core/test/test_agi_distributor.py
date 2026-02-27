import json
import os
import pickle
import socket
from pathlib import Path, PurePosixPath
import asyncio
import time
import pytest
from agi_cluster.agi_distributor import AGI
import agi_cluster.agi_distributor.agi_distributor as agi_distributor_module
from agi_env import AgiEnv, normalize_path
from agi_node.agi_dispatcher import BaseWorker

# Set AGI verbosity low to avoid extra prints during test.
AGI.verbose = 0


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


@pytest.fixture(autouse=True)
def _reset_agi_service_state(monkeypatch, tmp_path):
    state_file = tmp_path / "service_state.json"
    monkeypatch.setattr(AGI, "_service_state_path", staticmethod(lambda _env: state_file))
    health_file = tmp_path / "service_health.json"

    def _health_path(_env, health_output_path=None):
        if health_output_path is None:
            health_file.parent.mkdir(parents=True, exist_ok=True)
            return health_file
        explicit = Path(str(health_output_path))
        if explicit.is_absolute():
            explicit.parent.mkdir(parents=True, exist_ok=True)
            return explicit
        resolved = (tmp_path / explicit).resolve(strict=False)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        return resolved

    monkeypatch.setattr(AGI, "_service_health_path", staticmethod(_health_path))
    AGI._service_futures = {}
    AGI._service_workers = []
    AGI._dask_client = None
    AGI._jobs = None
    AGI._reset_service_queue_state()
    yield
    AGI._service_futures = {}
    AGI._service_workers = []
    AGI._dask_client = None
    AGI._jobs = None
    AGI._reset_service_queue_state()


def test_normalize_path():
    # Given a relative path "."
    input_path = ""
    normalized = normalize_path(input_path)
    if os.name == "nt":
        assert os.path.isabs(normalized), "On Windows the normalized path should be absolute."
    else:
        # On POSIX, compare with the PurePosixPath version.
        expected = str(PurePosixPath(Path(input_path)))
        assert normalized == expected, f"Expected {expected} but got {normalized}"


def test_find_free_port():
    # Verify that find_free_port returns an integer that can be bound.
    port = AGI.find_free_port(start=5000, end=6000, attempts=10)
    assert isinstance(port, int), "find_free_port should return an integer."
    # Attempt to bind a socket to the port to ensure it is free.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("localhost", port))
        except Exception as e:
            pytest.fail(f"find_free_port returned a port that is not free: {e}")


def test_mode_constants_exposed():
    assert AGI.PYTHON_MODE == 1
    assert AGI.CYTHON_MODE == 2
    assert AGI.DASK_MODE == 4
    assert AGI.RAPIDS_MODE == 16


def test_get_default_local_ip():
    # Check that get_default_local_ip returns a plausible IPv4 address.
    ip = AGI.get_default_local_ip()
    assert ip != "Unable to determine local IP", "Local IP could not be determined."
    parts = ip.split('.')
    assert len(parts) == 4, f"IP address {ip} does not have 4 parts."
    for part in parts:
        assert part.isdigit(), f"IP part '{part}' is not numeric."


def test_is_local():
    # Test that known local IP addresses are detected as local.
    assert AgiEnv.is_local("127.0.0.1"), "127.0.0.1 should be local."
    # Use a public IP that is likely not local.
    assert not AgiEnv.is_local("8.8.8.8"), "8.8.8.8 should not be considered local."


@pytest.mark.asyncio
async def test_agi_run_requires_base_worker_cls():
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    env.base_worker_cls = None
    with pytest.raises(ValueError, match=r"Missing .* definition; expected"):
        await AGI.run(
            env,
            scheduler="127.0.0.1",
            workers={"127.0.0.1": 1},
            verbose=0,
            mode=AGI.DASK_MODE,
        )


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
async def test_agi_submit_requires_running_service():
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    with pytest.raises(RuntimeError, match=r"Service is not running"):
        await AGI.submit(env, work_plan=[], work_plan_metadata=[])


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
    LocalCluster = distributed.LocalCluster
    Client = distributed.Client

    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    env.base_worker_cls = "AgiDataWorker"

    cluster = LocalCluster(
        n_workers=1,
        threads_per_worker=2,
        processes=False,
        host="127.0.0.1",
        protocol="tcp",
        dashboard_address=None,
    )
    client = Client(cluster)

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
