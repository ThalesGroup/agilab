"""The minimal template runs its real manager and worker on small tables."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest

from minimal_app import MinimalApp, MinimalAppArgs
from minimal_app_worker import MinimalAppWorker


def environment(tmp_path):
    share = tmp_path / "share"
    share.mkdir()
    return SimpleNamespace(
        verbose=0, home_abs=tmp_path, _is_managed_pc=False,
        AGI_LOCAL_SHARE=str(share), workflow_data_root=share,
        resolve_share_path=lambda value: Path(value) if Path(value).is_absolute() else share / value,
    )


@pytest.mark.parametrize("suffix", ["csv", "parquet"])
def test_minimal_manager_worker_preserves_table_and_writes_parquet(tmp_path, suffix):
    env = environment(tmp_path)
    manager = MinimalApp(env, args=MinimalAppArgs())
    expected = pl.DataFrame({"value": [1, 2, 3], "label": ["first", None, "last"]})
    source = manager.args.data_in / ("input." + suffix)
    getattr(expected, "write_" + suffix)(source)

    plan, metadata, *_ = manager.build_distribution({"127.0.0.1": 1})
    assert plan == [[[str(source)]]]
    worker = MinimalAppWorker()
    worker.env = env
    worker.args = manager.args.model_dump(mode="json")
    worker._worker_id = 0
    worker.worker_id = 0
    worker._mode = 0
    worker.verbose = 0
    worker.start()
    assert worker.works(plan, metadata) >= 0
    persisted = pl.read_parquet(worker.data_out / "0_output.parquet")
    assert persisted.select(expected.columns).equals(expected)
    assert persisted["worker_id"].n_unique() == 1
    assert getattr(pl, "read_" + suffix)(source).equals(expected)


def test_minimal_manager_reports_missing_data_before_worker_dispatch(tmp_path):
    manager = MinimalApp(environment(tmp_path))
    with pytest.raises(FileNotFoundError, match="No CSV or Parquet"):
        manager.build_distribution({"127.0.0.1": 1})


def test_minimal_worker_respects_row_slice_and_rejects_unsupported_input(tmp_path):
    env = environment(tmp_path)
    manager = MinimalApp(env, args=MinimalAppArgs(nskip=1, nread=1))
    source = manager.args.data_in / "input.csv"
    pl.DataFrame({"value": [1, 2, 3]}).write_csv(source)
    worker = MinimalAppWorker()
    worker.env = env
    worker.args = manager.args.model_dump(mode="json")
    worker.start()
    assert worker.work_pool(source).to_dict(as_series=False) == {"value": [2]}
    with pytest.raises(ValueError, match="CSV or Parquet"):
        worker.work_pool(source.with_suffix(".txt"))
