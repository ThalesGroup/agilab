from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agi_cluster.agi_distributor import AGI, RunRequest, capacity_support
from agi_env import AgiEnv
from agi_node.agi_dispatcher import BaseWorker

_BUILTIN_APPS_PATH = (Path(__file__).resolve().parents[4] / "src/agilab/apps/builtin").resolve()


def _mycode_env(*, verbose: int = 0) -> AgiEnv:
    return AgiEnv(apps_path=_BUILTIN_APPS_PATH, app="mycode_project", verbose=verbose)


@pytest.fixture(autouse=True)
def _reset_agi_capacity_state():
    fields = [
        "_best_mode",
        "_mode_auto",
        "_dask_client",
        "_dask_workers",
        "_workers",
        "_capacity_predictor",
        "workers_info",
        "_run_time",
        "_capacity",
        "env",
        "target_path",
        "_target",
        "_args",
        "_worker_args",
        "_rapids_enabled",
        "_mode",
        "_capacity_data_file",
        "_capacity_model_file",
    ]
    snapshot = {field: getattr(AGI, field, None) for field in fields}
    try:
        AGI._best_mode = {}
        AGI._mode_auto = False
        AGI._dask_client = None
        AGI._dask_workers = []
        AGI._workers = {}
        AGI._capacity_predictor = None
        AGI.workers_info = {}
        AGI._run_time = []
        AGI._capacity = {}
        AGI.env = None
        AGI.target_path = None
        AGI._target = None
        AGI._args = {}
        AGI._worker_args = None
        AGI._rapids_enabled = False
        AGI._mode = 0
        AGI._capacity_data_file = "capacity_data.csv"
        AGI._capacity_model_file = "capacity_model.pkl"
        yield
    finally:
        for field, value in snapshot.items():
            setattr(AGI, field, value)


@pytest.mark.asyncio
async def test_benchmark_records_runs_and_writes_output(monkeypatch, tmp_path):
    env = _mycode_env()
    env.benchmark = tmp_path / "benchmark.json"
    env.benchmark.write_text("stale", encoding="utf-8")

    async def _fake_run(_env, request):
        mode = request.mode
        return f"mode{mode} {float(mode) + 1.0}"

    async def _fake_bench_dask(_env, request, _modes, _mask, runs):
        assert request.workers == {"127.0.0.1": 1}
        runs[4] = {"mode": "mode4", "timing": "4 seconds", "seconds": 4.0}

    monkeypatch.setattr(BaseWorker, "_is_cython_installed", staticmethod(lambda _env: True))
    monkeypatch.setattr(AGI, "run", staticmethod(_fake_run))
    monkeypatch.setattr(AGI, "_benchmark_dask_modes", staticmethod(_fake_bench_dask))

    payload = await capacity_support.benchmark(
        AGI,
        env,
        request=RunRequest(scheduler="127.0.0.1", workers={"127.0.0.1": 1}, mode=[0, 1, 4]),
    )
    data = json.loads(payload)
    assert set(data.keys()) == {"0", "1", "4"}
    assert data["0"]["order"] == 1
    assert data["1"]["order"] == 2
    assert data["4"]["order"] == 3
    assert AGI._best_mode[env.target]["mode"] == data["0"]["mode"]
    assert env.benchmark.exists()
    assert AGI._mode_auto is False


@pytest.mark.asyncio
async def test_benchmark_calls_install_when_cython_missing(monkeypatch, tmp_path):
    env = _mycode_env()
    env.benchmark = tmp_path / "benchmark.json"
    called = {"install": 0}

    async def _fake_install(*_args, **_kwargs):
        called["install"] += 1
        return None

    async def _fake_run(_env, request):
        return f"mode{request.mode} 1.0"

    monkeypatch.setattr(BaseWorker, "_is_cython_installed", staticmethod(lambda _env: False))
    monkeypatch.setattr(AGI, "install", staticmethod(_fake_install))
    monkeypatch.setattr(AGI, "run", staticmethod(_fake_run))
    monkeypatch.setattr(AGI, "_benchmark_dask_modes", staticmethod(lambda *_a, **_k: None))

    payload = await capacity_support.benchmark(AGI, env, request=RunRequest(mode=[0]))
    assert json.loads(payload)["0"]["mode"].startswith("mode")
    assert called["install"] == 1


@pytest.mark.asyncio
async def test_benchmark_raises_on_invalid_run_format(monkeypatch, tmp_path):
    env = _mycode_env()
    env.benchmark = tmp_path / "benchmark.json"

    async def _bad_run(*_args, **_kwargs):
        return "invalid-format"

    monkeypatch.setattr(BaseWorker, "_is_cython_installed", staticmethod(lambda _env: True))
    monkeypatch.setattr(AGI, "run", staticmethod(_bad_run))
    monkeypatch.setattr(AGI, "_benchmark_dask_modes", staticmethod(lambda *_a, **_k: None))

    with pytest.raises(ValueError, match="Unexpected run format"):
        await capacity_support.benchmark(AGI, env, request=RunRequest(mode=[0]))


@pytest.mark.asyncio
async def test_benchmark_raises_when_no_runs(monkeypatch, tmp_path):
    env = _mycode_env()
    env.benchmark = tmp_path / "benchmark.json"

    async def _non_str_run(*_args, **_kwargs):
        return {"status": "not-a-string"}

    monkeypatch.setattr(BaseWorker, "_is_cython_installed", staticmethod(lambda _env: True))
    monkeypatch.setattr(AGI, "run", staticmethod(_non_str_run))
    monkeypatch.setattr(AGI, "_benchmark_dask_modes", staticmethod(lambda *_a, **_k: None))

    with pytest.raises(RuntimeError, match="No ordered runs available"):
        await capacity_support.benchmark(AGI, env, request=RunRequest(mode=[0]))


@pytest.mark.asyncio
async def test_benchmark_dask_modes_records_runs_and_stops(monkeypatch):
    env = _mycode_env()
    calls = {"start": 0, "stop": 0, "update": 0}
    runs = {}
    sequence = iter(["m4 2.0", "m5 1.0"])

    async def _start(_scheduler):
        calls["start"] += 1
        return True

    async def _stop():
        calls["stop"] += 1

    async def _distribute():
        return next(sequence)

    monkeypatch.setattr(AGI, "_start", staticmethod(_start))
    monkeypatch.setattr(AGI, "_stop", staticmethod(_stop))
    monkeypatch.setattr(AGI, "_distribute", staticmethod(_distribute))
    monkeypatch.setattr(
        AGI,
        "_update_capacity",
        staticmethod(lambda: calls.__setitem__("update", calls["update"] + 1)),
    )

    await capacity_support.benchmark_dask_modes(
        AGI,
        env,
        request=RunRequest(scheduler="127.0.0.1", workers={"127.0.0.1": 1}),
        mode_range=[4, 5],
        rapids_mode_mask=AGI._RAPIDS_RESET,
        runs=runs,
    )
    assert calls["start"] == 1
    assert calls["stop"] == 1
    assert calls["update"] == 2
    assert runs[4]["seconds"] == 2.0
    assert runs[5]["seconds"] == 1.0


@pytest.mark.asyncio
async def test_benchmark_dask_modes_stops_even_when_run_format_is_invalid(monkeypatch):
    env = _mycode_env()
    calls = {"stop": 0}

    async def _start(_scheduler):
        return True

    async def _stop():
        calls["stop"] += 1

    async def _distribute():
        return "bad-run"

    monkeypatch.setattr(AGI, "_start", staticmethod(_start))
    monkeypatch.setattr(AGI, "_stop", staticmethod(_stop))
    monkeypatch.setattr(AGI, "_distribute", staticmethod(_distribute))
    monkeypatch.setattr(AGI, "_update_capacity", staticmethod(lambda: None))

    with pytest.raises(ValueError, match="Unexpected run format"):
        await capacity_support.benchmark_dask_modes(
            AGI,
            env,
            request=RunRequest(scheduler="127.0.0.1", workers={"127.0.0.1": 1}),
            mode_range=[4],
            rapids_mode_mask=AGI._RAPIDS_RESET,
            runs={},
        )
    assert calls["stop"] == 1


@pytest.mark.asyncio
async def test_calibration_fallback_uses_worker_counts_when_no_worker_keys_exist():
    class _Client:
        def run(self, *_args, **_kwargs):
            return {}

        def gather(self, payload):
            return payload

    AGI._dask_client = _Client()
    AGI._dask_workers = []
    AGI._workers = {"10.0.0.1": 2}
    AGI._capacity_predictor = SimpleNamespace(predict=lambda _x: [1.0])

    await capacity_support.calibration(AGI)

    assert AGI._capacity == {"10.0.0.1:0": 1.0, "10.0.0.1:1": 1.0}
    assert AGI.workers_info == {"10.0.0.1:0": {"label": 1.0}, "10.0.0.1:1": {"label": 1.0}}


@pytest.mark.asyncio
async def test_calibration_computes_normalized_capacity():
    class _Predictor:
        def predict(self, _data):
            return [4.0]

    class _Client:
        def run(self, *_args, **_kwargs):
            return {
                "tcp://127.0.0.1:8787": {
                    "ram_total": [10.0],
                    "ram_available": [5.0],
                    "cpu_count": [4.0],
                    "cpu_frequency": [2.5],
                    "network_speed": [1.0],
                }
            }

        def gather(self, payload):
            return payload

    AGI._dask_client = _Client()
    AGI._dask_workers = ["127.0.0.1:8787"]
    AGI._workers = {"127.0.0.1": 1}
    AGI._capacity_predictor = _Predictor()

    await capacity_support.calibration(AGI)

    assert AGI.workers_info["127.0.0.1:8787"]["label"] == 4.0
    assert AGI._capacity["127.0.0.1:8787"] == 1.0


@pytest.mark.asyncio
async def test_calibration_fallback_when_predictor_has_no_data():
    class _Client:
        def run(self, *_args, **_kwargs):
            return {}

        def gather(self, payload):
            return payload

    AGI._dask_client = _Client()
    AGI._dask_workers = ["127.0.0.1:8787"]
    AGI._workers = {"127.0.0.1": 1}
    AGI._capacity_predictor = SimpleNamespace(predict=lambda _x: [1.0])

    await capacity_support.calibration(AGI)

    assert AGI._capacity["127.0.0.1:8787"] == 1.0


@pytest.mark.asyncio
async def test_calibration_fallback_uses_localhost_when_no_workers_exist():
    class _Client:
        def run(self, *_args, **_kwargs):
            return {}

        def gather(self, payload):
            return payload

    AGI._dask_client = _Client()
    AGI._dask_workers = []
    AGI._workers = {}
    AGI._capacity_predictor = SimpleNamespace(predict=lambda _x: [1.0])

    await capacity_support.calibration(AGI)

    assert AGI._capacity == {"localhost:0": 1.0}
    assert AGI.workers_info == {"localhost:0": {"label": 1.0}}


def test_update_capacity_success_and_guard_paths(tmp_path, monkeypatch):
    AGI._workers = {"127.0.0.1": 1}
    AGI.workers_info = {
        "127.0.0.1:8787": {
            "nb_workers": 1,
            "ram_total": 10.0,
            "ram_available": 5.0,
            "cpu_count": 4.0,
            "cpu_frequency": 2.5,
            "network_speed": 1.0,
            "label": 1.0,
        }
    }
    AGI._run_time = ["error-line"]
    AGI._capacity_data_file = str(tmp_path / "capacity.csv")
    AGI.env = SimpleNamespace(home_abs=str(tmp_path))
    train_calls = {"count": 0}
    monkeypatch.setattr(
        AGI,
        "_train_capacity",
        staticmethod(lambda _path: train_calls.__setitem__("count", train_calls["count"] + 1)),
    )

    capacity_support.update_capacity(AGI)
    assert train_calls["count"] == 0

    AGI._run_time = [{"127.0.0.1:8787": 2.0}]
    capacity_support.update_capacity(AGI)
    assert train_calls["count"] == 1
    assert Path(AGI._capacity_data_file).exists()

    AGI.workers_info["127.0.0.1:8787"]["label"] = 0.0
    AGI._run_time = [{"127.0.0.1:8787": 2.0}]
    with pytest.raises(RuntimeError, match="workers BaseWorker.do_works failed"):
        capacity_support.update_capacity(AGI)


def test_update_capacity_adjusts_against_other_workers(tmp_path, monkeypatch):
    AGI._workers = {"127.0.0.1": 1, "10.0.0.2": 1}
    AGI.workers_info = {
        "127.0.0.1:8787": {
            "nb_workers": 1,
            "ram_total": 10.0,
            "ram_available": 5.0,
            "cpu_count": 4.0,
            "cpu_frequency": 2.5,
            "network_speed": 1.0,
            "label": 1.0,
        },
        "10.0.0.2:8788": {
            "nb_workers": 1,
            "ram_total": 20.0,
            "ram_available": 10.0,
            "cpu_count": 8.0,
            "cpu_frequency": 3.0,
            "network_speed": 2.0,
            "label": 2.0,
        },
    }
    AGI._run_time = [
        {"127.0.0.1:8787": 2.0},
        {"10.0.0.2:8788": 1.0},
    ]
    AGI._capacity_data_file = str(tmp_path / "capacity.csv")
    AGI.env = SimpleNamespace(home_abs=str(tmp_path))
    train_calls = {"count": 0}
    monkeypatch.setattr(
        AGI,
        "_train_capacity",
        staticmethod(lambda _path: train_calls.__setitem__("count", train_calls["count"] + 1)),
    )

    capacity_support.update_capacity(AGI)

    assert Path(AGI._capacity_data_file).exists()
    assert train_calls["count"] == 1


def test_train_capacity_missing_and_success(tmp_path):
    AGI._capacity_data_file = "capacity_data.csv"
    AGI._capacity_model_file = "capacity_model.pkl"

    with pytest.raises(FileNotFoundError):
        capacity_support.train_capacity(AGI, tmp_path)

    csv_path = tmp_path / AGI._capacity_data_file
    rows = [
        "nb_workers,ram_total,ram_available,cpu_count,cpu_frequency,network_speed,label",
        "skip,skip,skip,skip,skip,skip,skip",
        "skip,skip,skip,skip,skip,skip,skip",
        "1,32,16,8,2.5,100,1.0",
        "1,32,15,8,2.4,95,0.9",
        "1,32,14,8,2.3,90,0.8",
        "2,64,30,16,2.6,120,1.4",
        "2,64,28,16,2.5,115,1.3",
        "2,64,26,16,2.4,110,1.2",
        "3,96,40,24,2.7,140,1.8",
        "3,96,38,24,2.6,135,1.7",
    ]
    csv_path.write_text("\n".join(rows), encoding="utf-8")

    capacity_support.train_capacity(AGI, tmp_path)

    model_path = tmp_path / AGI._capacity_model_file
    assert model_path.exists()
    assert hasattr(AGI._capacity_predictor, "predict")
