from __future__ import annotations

from pathlib import Path

import pytest

from agi_cluster.agi_distributor import AGI
import agi_cluster.agi_distributor.agi_distributor as agi_distributor_module
from agi_env import AgiEnv

_BUILTIN_APPS_PATH = (Path(__file__).resolve().parents[4] / "src/agilab/apps/builtin").resolve()


def _mycode_env(*, verbose: int = 0) -> AgiEnv:
    return AgiEnv(apps_path=_BUILTIN_APPS_PATH, app="mycode_project", verbose=verbose)


@pytest.fixture(autouse=True)
def _reset_agi_run_state():
    fields = [
        "_run_type",
        "_best_mode",
        "agi_workers",
        "install_worker_group",
        "verbose",
    ]
    snapshot = {field: getattr(AGI, field, None) for field in fields}
    try:
        AGI._run_type = None
        AGI._best_mode = {}
        AGI.verbose = 0
        yield
    finally:
        for field, value in snapshot.items():
            setattr(AGI, field, value)


@pytest.mark.asyncio
async def test_agi_run_delegates_to_benchmark_with_sorted_mode_list(monkeypatch):
    env = _mycode_env()
    captured = {}

    async def _fake_benchmark(env_, scheduler, workers, verbose, mode_range, rapids_enabled, **args):
        captured["env"] = env_
        captured["scheduler"] = scheduler
        captured["workers"] = workers
        captured["verbose"] = verbose
        captured["mode_range"] = list(mode_range)
        captured["rapids_enabled"] = rapids_enabled
        captured["args"] = dict(args)
        return {"status": "bench"}

    monkeypatch.setattr(AGI, "_benchmark", staticmethod(_fake_benchmark))

    result = await AGI.run(
        env,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
        verbose=2,
        mode=[5, 1, 3],
        rapids_enabled=True,
        example_flag=True,
    )

    assert result == {"status": "bench"}
    assert captured["env"] is env
    assert captured["scheduler"] == "127.0.0.1"
    assert captured["workers"] == {"127.0.0.1": 1}
    assert captured["verbose"] == 2
    assert captured["mode_range"] == [1, 3, 5]
    assert captured["rapids_enabled"] is True
    assert captured["args"]["example_flag"] is True


@pytest.mark.asyncio
async def test_agi_run_uses_default_workers_in_benchmark(monkeypatch):
    env = _mycode_env(verbose=1)
    captured = {}

    async def _fake_benchmark(_env, _scheduler, workers, _verbose, mode_range, _rapids_enabled, **_args):
        captured["workers"] = workers
        captured["modes"] = list(mode_range)
        return {"status": "bench-default-workers"}

    monkeypatch.setattr(AGI, "_benchmark", staticmethod(_fake_benchmark))

    result = await AGI.run(
        env,
        scheduler="127.0.0.1",
        workers=None,
        mode=None,
    )
    assert result == {"status": "bench-default-workers"}
    assert captured["workers"] == agi_distributor_module._workers_default
    assert captured["modes"] == list(range(8))


@pytest.mark.asyncio
async def test_agi_run_rejects_invalid_workers_type():
    env = _mycode_env()
    with pytest.raises(ValueError, match=r"workers must be a dict"):
        await AGI.run(
            env,
            workers=["127.0.0.1"],  # type: ignore[arg-type]
            mode=AGI.DASK_MODE,
        )


@pytest.mark.asyncio
async def test_agi_run_rejects_invalid_mode_string():
    env = _mycode_env()
    with pytest.raises(ValueError, match=r"parameter <mode> must only contain the letters"):
        await AGI.run(
            env,
            workers={"127.0.0.1": 1},
            mode="dcx",
        )


@pytest.mark.asyncio
async def test_agi_run_rejects_invalid_mode_type():
    env = _mycode_env()
    with pytest.raises(ValueError, match=r"parameter <mode> must be an int"):
        await AGI.run(
            env,
            workers={"127.0.0.1": 1},
            mode={"bad": "type"},
        )


@pytest.mark.asyncio
async def test_agi_run_rejects_unsupported_base_worker_class(monkeypatch):
    env = _mycode_env()
    env.base_worker_cls = "UnknownWorker"
    monkeypatch.setattr(AGI, "_train_capacity", staticmethod(lambda *_args, **_kwargs: None))

    with pytest.raises(ValueError, match=r"Unsupported base worker class"):
        await AGI.run(
            env,
            workers={"127.0.0.1": 1},
            mode=AGI.DASK_MODE,
        )


@pytest.mark.asyncio
async def test_agi_run_resolves_sb3_trainer_worker_to_dag_group(monkeypatch):
    env = _mycode_env()
    env.base_worker_cls = "Sb3TrainerWorker"
    env._base_worker_module = "sb3_trainer_worker"

    async def _fake_main(_scheduler):
        return {"status": "ok"}

    monkeypatch.setattr(AGI, "_main", staticmethod(_fake_main))
    monkeypatch.setattr(AGI, "_train_capacity", staticmethod(lambda *_args, **_kwargs: None))

    result = await AGI.run(
        env,
        workers={"127.0.0.1": 1},
        mode=AGI.DASK_MODE,
    )

    assert result == {"status": "ok"}
    assert AGI.install_worker_group == ["dag-worker"]


@pytest.mark.asyncio
async def test_agi_run_mode_string_valid_path_calls_mode2int_and_main(monkeypatch):
    env = _mycode_env()
    env.base_worker_cls = "PandasWorker"
    called = {"mode2int": None, "main": None}

    def _mode2int(mode):
        called["mode2int"] = mode
        return 5

    async def _fake_main(scheduler):
        called["main"] = scheduler
        return {"status": "ok"}

    monkeypatch.setattr(env, "mode2int", _mode2int)
    monkeypatch.setattr(AGI, "_main", staticmethod(_fake_main))
    monkeypatch.setattr(AGI, "_train_capacity", staticmethod(lambda *_args, **_kwargs: None))

    result = await AGI.run(
        env,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
        mode="dc",
    )
    assert result == {"status": "ok"}
    assert called["mode2int"] == "dc"
    assert called["main"] == "127.0.0.1"


@pytest.mark.asyncio
async def test_agi_run_mode_zero_sets_run_type(monkeypatch):
    env = _mycode_env()
    env.base_worker_cls = "PandasWorker"

    async def _fake_main(_scheduler):
        return {"status": "ok"}

    monkeypatch.setattr(AGI, "_main", staticmethod(_fake_main))
    monkeypatch.setattr(AGI, "_train_capacity", staticmethod(lambda *_args, **_kwargs: None))

    result = await AGI.run(
        env,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
        mode=0,
    )
    assert result == {"status": "ok"}
    assert AGI._run_type == "run --no-sync"


@pytest.mark.asyncio
async def test_agi_run_trains_capacity_when_model_is_missing(monkeypatch):
    env = _mycode_env()
    env.base_worker_cls = "PandasWorker"
    called = {"train": 0}

    async def _fake_main(_scheduler):
        return {"status": "ok"}

    monkeypatch.setattr(Path, "is_file", lambda self: False, raising=False)
    monkeypatch.setattr(AGI, "_main", staticmethod(_fake_main))
    monkeypatch.setattr(
        AGI,
        "_train_capacity",
        staticmethod(lambda *_args, **_kwargs: called.__setitem__("train", called["train"] + 1)),
    )

    result = await AGI.run(
        env,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
        mode=AGI.DASK_MODE,
    )
    assert result == {"status": "ok"}
    assert called["train"] == 1


@pytest.mark.asyncio
async def test_agi_run_returns_none_on_process_error(monkeypatch):
    env = _mycode_env()
    env.base_worker_cls = "PandasWorker"

    class _FakeProcessError(Exception):
        pass

    async def _fake_main(_scheduler):
        raise _FakeProcessError("process failed")

    monkeypatch.setattr(agi_distributor_module, "ProcessError", _FakeProcessError)
    monkeypatch.setattr(AGI, "_main", staticmethod(_fake_main))
    monkeypatch.setattr(AGI, "_train_capacity", staticmethod(lambda *_args, **_kwargs: None))

    result = await AGI.run(
        env,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
        mode=AGI.DASK_MODE,
    )
    assert result is None


@pytest.mark.asyncio
async def test_agi_run_returns_connection_error_payload(monkeypatch):
    env = _mycode_env()
    env.base_worker_cls = "PandasWorker"
    monkeypatch.setattr(AGI, "_train_capacity", staticmethod(lambda *_args, **_kwargs: None))

    async def _boom(_scheduler):
        raise ConnectionError("scheduler unavailable")

    monkeypatch.setattr(AGI, "_main", staticmethod(_boom))
    result = await AGI.run(
        env,
        workers={"127.0.0.1": 1},
        mode=AGI.DASK_MODE,
    )
    assert result["status"] == "error"
    assert result["kind"] == "connection"
    assert "scheduler unavailable" in result["message"]


@pytest.mark.asyncio
async def test_agi_run_returns_none_on_module_not_found(monkeypatch):
    env = _mycode_env()
    env.base_worker_cls = "PandasWorker"
    monkeypatch.setattr(AGI, "_train_capacity", staticmethod(lambda *_args, **_kwargs: None))

    async def _missing(_scheduler):
        raise ModuleNotFoundError("missing module")

    monkeypatch.setattr(AGI, "_main", staticmethod(_missing))
    assert await AGI.run(env, workers={"127.0.0.1": 1}, mode=AGI.DASK_MODE) is None


@pytest.mark.asyncio
async def test_agi_run_reraises_unhandled_exception(monkeypatch):
    env = _mycode_env()
    env.base_worker_cls = "PandasWorker"
    monkeypatch.setattr(AGI, "_train_capacity", staticmethod(lambda *_args, **_kwargs: None))

    async def _unexpected(_scheduler):
        raise RuntimeError("unexpected failure")

    monkeypatch.setattr(AGI, "_main", staticmethod(_unexpected))
    with pytest.raises(RuntimeError, match="unexpected failure"):
        await AGI.run(env, workers={"127.0.0.1": 1}, mode=AGI.DASK_MODE)


@pytest.mark.asyncio
async def test_agi_run_logs_debug_traceback_when_debug_enabled(monkeypatch):
    env = _mycode_env()
    env.base_worker_cls = "PandasWorker"
    monkeypatch.setattr(AGI, "_train_capacity", staticmethod(lambda *_args, **_kwargs: None))

    class _FakeLogger:
        def __init__(self):
            self.debug_calls = 0

        def info(self, *args, **kwargs):
            return None

        def error(self, *args, **kwargs):
            return None

        def warning(self, *args, **kwargs):
            return None

        def isEnabledFor(self, _level):
            return True

        def debug(self, *args, **kwargs):
            self.debug_calls += 1

    async def _unexpected(_scheduler):
        raise RuntimeError("boom-debug")

    fake_logger = _FakeLogger()
    monkeypatch.setattr(AGI, "_main", staticmethod(_unexpected))
    monkeypatch.setattr(agi_distributor_module, "logger", fake_logger)

    with pytest.raises(RuntimeError, match="boom-debug"):
        await AGI.run(env, workers={"127.0.0.1": 1}, mode=AGI.DASK_MODE)
    assert fake_logger.debug_calls >= 1


@pytest.mark.asyncio
async def test_agi_run_requires_base_worker_cls():
    env = _mycode_env()
    env.base_worker_cls = None
    with pytest.raises(ValueError, match=r"Missing .* definition; expected"):
        await AGI.run(
            env,
            scheduler="127.0.0.1",
            workers={"127.0.0.1": 1},
            verbose=0,
            mode=AGI.DASK_MODE,
        )
