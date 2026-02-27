import os
import socket
from pathlib import Path, PurePosixPath
import asyncio
import pytest
from agi_cluster.agi_distributor import AGI
import agi_cluster.agi_distributor.agi_distributor as agi_distributor_module
from agi_env import AgiEnv, normalize_path

# Set AGI verbosity low to avoid extra prints during test.
AGI.verbose = 0


class _FakeFuture:
    def __init__(self, status: str = "pending"):
        self.status = status


class _FakeClient:
    def __init__(self, workers: list[str]):
        self._workers = workers
        self.status = "running"

    def submit(self, *_args, **_kwargs):
        return _FakeFuture()

    def gather(self, futures, errors="raise"):
        if isinstance(futures, list):
            return [None for _ in futures]
        return []

    def scheduler_info(self):
        return {"workers": {f"tcp://{worker}": {} for worker in self._workers}}


@pytest.fixture(autouse=True)
def _reset_agi_service_state():
    AGI._service_futures = {}
    AGI._service_workers = []
    AGI._dask_client = None
    AGI._jobs = None
    yield
    AGI._service_futures = {}
    AGI._service_workers = []
    AGI._dask_client = None
    AGI._jobs = None


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

    status = await AGI.serve(env, action="status")
    assert status["status"] == "running"
    assert status["workers"] == ["127.0.0.1:8787"]

    stopped = await AGI.serve(env, action="stop", shutdown_on_stop=False)
    assert stopped["status"] == "stopped"


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
