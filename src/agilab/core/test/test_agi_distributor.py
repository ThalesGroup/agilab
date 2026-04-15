import os
from types import SimpleNamespace
from pathlib import Path, PurePosixPath

import pytest

from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv, normalize_path

# Set AGI verbosity low to avoid extra prints during test.
AGI.verbose = 0


def test_agi_singleton_guard_raises_when_already_instantiated(monkeypatch):
    monkeypatch.setattr(AGI, "_instantiated", True, raising=False)
    try:
        with pytest.raises(RuntimeError, match="singleton"):
            AGI("demo")
    finally:
        monkeypatch.setattr(AGI, "_instantiated", False, raising=False)


@pytest.mark.asyncio
async def test_install_sets_sync_run_type_and_install_mode(monkeypatch):
    captured: dict[str, object] = {}

    async def _fake_run(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(AGI, "run", staticmethod(_fake_run))

    env = SimpleNamespace()
    await AGI.install(
        env=env,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
        workers_data_path="/tmp/workers",
        modes_enabled=AGI.PYTHON_MODE,
        verbose=3,
        force_update=True,
    )

    assert AGI._run_type == "sync"
    assert captured["env"] is env
    assert captured["mode"] == (AGI._INSTALL_MODE | AGI.PYTHON_MODE)
    assert captured["workers_data_path"] == "/tmp/workers"
    assert captured["rapids_enabled"] == (AGI._INSTALL_MODE & AGI.PYTHON_MODE)
    assert captured["force_update"] is True


@pytest.mark.asyncio
async def test_stop_handles_scheduler_info_and_retire_failures(monkeypatch):
    closed = {"count": 0}

    async def _fake_close_all():
        closed["count"] += 1

    class _SchedulerInfoFailsClient:
        shutdown_calls = 0

        async def scheduler_info(self):
            raise RuntimeError("scheduler down")

        async def shutdown(self):
            self.shutdown_calls += 1

    AGI._mode_auto = False
    AGI._dask_client = _SchedulerInfoFailsClient()
    monkeypatch.setattr(AGI, "_close_all_connections", staticmethod(_fake_close_all))
    await AGI._stop()
    assert AGI._dask_client.shutdown_calls == 1
    assert closed["count"] == 1

    closed["count"] = 0

    class _RetireFailsClient:
        shutdown_calls = 0

        async def scheduler_info(self):
            return {"workers": {"tcp://127.0.0.1:8787": {}}}

        async def retire_workers(self, **_kwargs):
            raise RuntimeError("retire failed")

        async def shutdown(self):
            self.shutdown_calls += 1

    AGI._dask_client = _RetireFailsClient()
    monkeypatch.setattr(AGI, "_close_all_connections", staticmethod(_fake_close_all))
    await AGI._stop()
    assert AGI._dask_client.shutdown_calls == 1
    assert closed["count"] == 1


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


def test_mode_constants_exposed():
    assert AGI.PYTHON_MODE == 1
    assert AGI.CYTHON_MODE == 2
    assert AGI.DASK_MODE == 4
    assert AGI.RAPIDS_MODE == 16


def test_is_local():
    # Test that known local IP addresses are detected as local.
    assert AgiEnv.is_local("127.0.0.1"), "127.0.0.1 should be local."
    # Use a public IP that is likely not local.
    assert not AgiEnv.is_local("8.8.8.8"), "8.8.8.8 should not be considered local."
