"""Tests for the shared in-worker pool engine (agi_node.agi_dispatcher.worker_pool_support)."""

import logging
import time
from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool

import pandas as pd
import pytest

from agi_node.agi_dispatcher import BaseWorker, worker_pool_support
from agi_node.pandas_worker import PandasWorker
import agi_node.pandas_worker.pandas_worker as pandas_module


class RecordingPool:
    """Inline executor fake that records construction and submissions."""

    instances = []

    def __init__(self, max_workers=None, initializer=None, initargs=(), mp_context=None):
        self.max_workers = max_workers
        self._initializer = initializer
        self._initargs = initargs
        self.submitted = []
        RecordingPool.instances.append(self)

    def __enter__(self):
        if self._initializer:
            self._initializer(*self._initargs)
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def submit(self, fn, *args):
        self.submitted.append(args)
        future = Future()
        try:
            future.set_result(fn(*args))
        except Exception as exc:  # pragma: no cover - mirrors executor behavior
            future.set_exception(exc)
        return future


class EngineWorker(PandasWorker):
    def __init__(self, worker_id=0, mode=1):
        self._worker_id = worker_id
        self._mode = mode
        self.verbose = 0
        self.args = {"output_format": "csv"}
        self.data_out = None
        self.pool_vars = {"args": "shared"}
        self.last_dfs = []
        self.stopped = 0

    def _actual_work_pool(self, x):
        return pd.DataFrame({"col": [x]})

    def work_init(self):
        pass

    def pool_init(self, pool_vars):
        self.seen_pool_vars = pool_vars

    def stop(self):
        self.stopped += 1

    def work_done(self, df=None):
        self.last_dfs.append(df)


class NoneReturningWorker(EngineWorker):
    def _actual_work_pool(self, x):
        if x == "bad":
            return None
        return pd.DataFrame({"col": [x]})


class FailingWorker(EngineWorker):
    def _actual_work_pool(self, x):
        if x == "boom":
            raise ValueError("exploding item")
        return pd.DataFrame({"col": [x]})


@pytest.fixture(autouse=True)
def _patch_pool(monkeypatch):
    RecordingPool.instances = []
    monkeypatch.setattr(pandas_module, "ProcessPoolExecutor", RecordingPool)
    yield


# --- mode dispatch -----------------------------------------------------


@pytest.mark.parametrize(
    "mode,expected",
    [(0, False), (1, True), (2, False), (4, True), (5, True), (7, True), (None, False)],
)
def test_pool_mode_requested_mask(mode, expected):
    # Pool bit (1) and the historical dask bit (4) both select in-worker
    # pooling; this is the single source of truth for the 0b0101 mask.
    assert worker_pool_support.pool_mode_requested(mode) is expected


# --- pool width and chunksize ------------------------------------------


def test_resolve_pool_width_guards_cpu_count_none(monkeypatch):
    monkeypatch.setattr(worker_pool_support.os, "cpu_count", lambda: None)
    assert worker_pool_support.resolve_pool_width([8]) == 1


def test_resolve_pool_width_env_cap(monkeypatch):
    monkeypatch.setattr(worker_pool_support.os, "cpu_count", lambda: 64)
    monkeypatch.setenv(worker_pool_support.POOL_MAX_WORKERS_ENV, "3")
    assert worker_pool_support.resolve_pool_width([10]) == 3


def test_resolve_pool_width_args_cap_wins_over_env(monkeypatch):
    monkeypatch.setattr(worker_pool_support.os, "cpu_count", lambda: 64)
    monkeypatch.setenv(worker_pool_support.POOL_MAX_WORKERS_ENV, "9")
    width = worker_pool_support.resolve_pool_width([10], {"pool_max_workers": 2})
    assert width == 2


def test_resolve_pool_width_ignores_invalid_cap(monkeypatch):
    monkeypatch.setattr(worker_pool_support.os, "cpu_count", lambda: 4)
    monkeypatch.setenv(worker_pool_support.POOL_MAX_WORKERS_ENV, "not-a-number")
    assert worker_pool_support.resolve_pool_width([10]) == 4


def test_map_chunksize_bounds():
    assert worker_pool_support.map_chunksize(0, 4) == 1
    assert worker_pool_support.map_chunksize(16, 4) == 4
    assert worker_pool_support.map_chunksize(10_000, 4) == 32


# --- executor lifecycle -------------------------------------------------


def test_single_executor_serves_all_chunks():
    # Regression: a fresh pool used to be created and torn down per chunk.
    worker = EngineWorker(mode=1)
    worker._exec_multi_process({0: [[1, 2], [3], [4, 5, 6]]}, None)
    assert len(RecordingPool.instances) == 1
    assert len(worker.last_dfs) == 3  # per-chunk work_done cadence preserved


def test_pool_entry_is_module_level_and_instance_ships_via_initializer():
    worker = EngineWorker(mode=1)
    worker._exec_multi_process({0: [[1, 2]]}, None)
    pool = RecordingPool.instances[0]
    # The instance and pool_vars travel once through the initializer...
    assert pool._initializer is worker_pool_support._pool_child_init
    assert pool._initargs == (worker, worker.pool_vars)
    assert worker.seen_pool_vars == {"args": "shared"}
    # ...and submitted tasks carry only (index, item) batches, not the worker.
    for (batch,) in pool.submitted:
        assert all(isinstance(idx, int) for idx, _item in batch)


# --- result handling ----------------------------------------------------


def test_worker_id_labels_use_original_item_index_in_pool_mode():
    worker = NoneReturningWorker(mode=1)
    worker._exec_multi_process({0: [["a", "bad", "c"]]}, None)
    df = worker.last_dfs[0]
    # "bad" returned None and is dropped; labels keep original indices 0 and 2.
    assert df["worker_id"].tolist() == [str((0, 0)), str((0, 2))]


def test_mono_and_multi_paths_label_identically():
    multi = EngineWorker(mode=1)
    multi._exec_multi_process({0: [[10, 20]]}, None)
    mono = EngineWorker(mode=0)
    mono._exec_mono_process({0: [[10, 20]]}, None)
    assert multi.last_dfs[0]["worker_id"].tolist() == mono.last_dfs[0]["worker_id"].tolist()


def test_none_and_non_frame_results_treated_as_empty_in_both_paths(caplog):
    for mode, runner in ((1, "_exec_multi_process"), (0, "_exec_mono_process")):
        worker = NoneReturningWorker(mode=mode)
        with caplog.at_level(logging.WARNING):
            getattr(worker, runner)({0: [["bad"]]}, None)
        assert worker.last_dfs[0].empty


def test_pool_failure_raises_with_item_context_and_logs_each(caplog):
    worker = FailingWorker(mode=1)
    with caplog.at_level(logging.ERROR):
        with pytest.raises(RuntimeError, match="1 of 3 work item\\(s\\).*'boom'"):
            worker._exec_multi_process({0: [["a", "boom", "c"]]}, None)
    assert any(
        "work_pool failed for work item 'boom'" in record.message
        for record in caplog.records
    )


def test_broken_pool_raises_actionable_error():
    class BrokenPool(RecordingPool):
        def submit(self, fn, *args):
            future = Future()
            future.set_exception(BrokenProcessPool("terminated abruptly"))
            return future

    worker = EngineWorker(mode=1)
    with pytest.raises(RuntimeError, match="pool_init"):
        worker_pool_support.exec_multi_process(
            worker,
            {0: [[1, 2]]},
            None,
            worker_pool_support.PoolFrameHooks(
                family="PandasWorker",
                executor_kind="process",
                executor_factory=BrokenPool,
                is_frame=lambda r: isinstance(r, pd.DataFrame),
                is_empty=lambda df: df.empty,
                concat_labeled=pandas_module._concat_labeled,
                empty_frame=pd.DataFrame,
            ),
        )


# --- plan validation ----------------------------------------------------


def test_plan_with_fewer_partitions_than_worker_id_raises_clear_error():
    worker = EngineWorker(worker_id=3, mode=1)
    with pytest.raises(RuntimeError, match="1 partition\\(s\\).*worker_id is 3"):
        worker._exec_multi_process([[[1]]], None)


def test_run_works_resets_chunk_counter_per_call():
    worker = EngineWorker(mode=0)
    worker._work_done_chunk = 7  # leftover from a previous service-mode run
    worker_pool_support.run_works(worker, {0: [[1]]}, None)
    # EngineWorker overrides work_done (no suffix bookkeeping), so the counter
    # must show the per-call reset; filename behavior is pinned in
    # test_pandas_worker.test_pandas_worker_work_done_chunk_counter_resets_between_works_calls.
    assert worker._work_done_chunk == 0
    assert worker.stopped == 1


def test_run_works_returns_per_call_elapsed_not_t0_age():
    BaseWorker._t0 = time.time() - 5000.0
    worker = EngineWorker(mode=0)
    elapsed = worker_pool_support.run_works(worker, {0: [[1]]}, None)
    assert 0.0 <= elapsed < 100.0
