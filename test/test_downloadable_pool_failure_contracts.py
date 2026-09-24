"""Keep failure and result provenance contracts consistent in downloadable pools."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
from concurrent.futures import Future

import pytest


@pytest.fixture(params=[
    "free_threading_demo", "free_threading_demo_astra", "free_threading_demo_rtx",
    "milp_energy_demo", "milp_energy_demo_astra", "milp_energy_demo_rtx",
])
def pool(request, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "src/agilab/demos/resources" / request.param / "agilab_pool.py"
    name = "_download_pool_contract_" + request.param
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def frame_hooks(pool):
    return pool.PoolFrameHooks(
        family="contract", executor_kind="process", executor_factory=object,
        is_frame=lambda value: isinstance(value, list), is_empty=lambda value: not value,
        concat_labeled=lambda frames, labels: list(zip(labels, frames)), empty_frame=list,
    )


def test_filtered_results_preserve_original_item_identity(pool, caplog):
    observed = []
    worker = SimpleNamespace(_worker_id=7, work_done=observed.append)
    pool._finish_chunk(worker, frame_hooks(pool),
                       [(0, None), (1, "invalid"), (2, []), (3, ["accepted"])])
    assert observed == [[("(7, 3)", ["accepted"])]]
    assert "work item index 1" in caplog.text
    assert "treating it as an empty result" in caplog.text


@pytest.mark.parametrize("probe_kind", ["missing", "fails"])
def test_unknown_gil_state_preserves_default_executor(pool, monkeypatch, caplog, probe_kind):
    def probe():
        raise RuntimeError("runtime observation unavailable")
    monkeypatch.setattr(pool, "sys", SimpleNamespace(
        **({"_is_gil_enabled": probe} if probe_kind == "fails" else {})
    ))
    monkeypatch.setattr(pool, "os", SimpleNamespace(environ={pool.POOL_EXECUTOR_ENV: "typo"}))
    assert pool.resolve_executor(frame_hooks(pool)) == (object, "process")
    assert "Ignoring invalid" in caplog.text


def test_pool_abandonment_attempts_all_owned_children_after_failures(pool):
    attempts = []
    def shutdown(**kwargs):
        attempts.append(("shutdown", kwargs))
        raise OSError("shutdown race")
    def terminate():
        attempts.append("first")
        raise ProcessLookupError("already gone")
    executor = SimpleNamespace(
        shutdown=shutdown,
        _processes={1: SimpleNamespace(terminate=terminate),
                    2: SimpleNamespace(terminate=lambda: attempts.append("second"))},
    )
    pool._abandon_stuck_pool(executor)
    assert attempts == [("shutdown", {"wait": False, "cancel_futures": True}), "first", "second"]


def test_empty_chunk_does_not_submit_work(pool):
    def forbidden(*args, **kwargs):
        pytest.fail("empty chunk submitted work")
    assert pool._run_chunk(SimpleNamespace(submit=forbidden), None,
                           frame_hooks(pool), 4, [], 2) == []


def test_many_failed_items_keep_compact_summary_and_full_diagnostics(pool, caplog):
    def submit(fn, batch):
        future = Future()
        future.set_result([(index, None, "failure:" + item) for index, item in batch])
        return future
    with pytest.raises(RuntimeError, match=r"failed for 5 of 5.*\.\.\.") as failure:
        pool._run_chunk(SimpleNamespace(submit=submit), None, frame_hooks(pool),
                        9, [f"item-{n}" for n in range(5)], 2)
    assert str(failure.value).count("'item-") == 3
    for n in range(5):
        assert f"failure:item-{n}" in caplog.text


def test_timeout_names_pending_items_and_abandons_only_owned_pool(pool, monkeypatch):
    observed = []
    def submit(fn, batch):
        return Future()
    def timed_out(futures, timeout):
        assert timeout > 0
        raise pool.FuturesTimeoutError()
    executor = SimpleNamespace(submit=submit,
        shutdown=lambda **kwargs: observed.append(kwargs), _processes={})
    monkeypatch.setattr(pool, "as_completed", timed_out)
    with pytest.raises(RuntimeError, match=r"5 item\(s\).*item-0.*item-1.*item-2.*\.\.\."):
        pool._run_chunk(executor, None, frame_hooks(pool), 9,
                        [f"item-{n}" for n in range(5)], 2, item_timeout=1)
    assert observed == [{"wait": False, "cancel_futures": True}]


@pytest.mark.parametrize("mode,plan,expected", [(0, [[1]], "mono"), (1, [[1]], "pool"), (4, [[1]], "pool"), (1, [], None)])
def test_dispatch_restarts_chunk_identity_for_reused_workers(pool, monkeypatch, mode, plan, expected):
    calls = []
    def record(kind, given_plan, metadata):
        assert worker._work_done_chunk == 0
        assert given_plan is plan
        assert metadata == {"generation": 2}
        calls.append(kind)
    worker = SimpleNamespace(
        _mode=mode, _work_done_chunk=12,
        _exec_multi_process=lambda plan, meta: record("pool", plan, meta),
        _exec_mono_process=lambda plan, meta: record("mono", plan, meta),
        stop=lambda: calls.append("stop"),
    )
    times = iter([100.0, 100.25])
    monkeypatch.setattr(pool, "time", SimpleNamespace(perf_counter=lambda: next(times)))
    assert pool.run_works(worker, plan, {"generation": 2}) == 0.25
    assert calls == ([expected, "stop"] if expected else ["stop"])
    assert worker._work_done_chunk == 0


@pytest.mark.parametrize("invalid_cap", [0, -2])
def test_invalid_per_call_cap_falls_back_to_environment(pool, monkeypatch, caplog, invalid_cap):
    monkeypatch.setattr(pool, "os", SimpleNamespace(environ={pool.POOL_MAX_WORKERS_ENV: "3"}))
    assert pool._resolve_pool_cap({pool.POOL_MAX_WORKERS_ARG: invalid_cap}) == 3
    assert "Ignoring non-positive" in caplog.text
