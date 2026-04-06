from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from agi_node.agi_dispatcher import BaseWorker


APP_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = APP_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from execution_pandas.execution_pandas import ExecutionPandas
from execution_pandas.app_args import ExecutionPandasArgs
from execution_pandas_worker.execution_pandas_worker import ExecutionPandasWorker


def _make_env(tmp_path: Path) -> SimpleNamespace:
    share_root = tmp_path / "share"
    share_root.mkdir(parents=True, exist_ok=True)

    def _resolve_share_path(path):
        candidate = Path(path)
        return candidate if candidate.is_absolute() else share_root / candidate

    return SimpleNamespace(
        verbose=0,
        resolve_share_path=_resolve_share_path,
        home_abs=tmp_path,
        _is_managed_pc=False,
        AGI_LOCAL_SHARE=str(share_root),
        target="execution_pandas_project",
    )


def test_execution_pandas_generates_dataset_and_distribution(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    args = ExecutionPandasArgs(n_partitions=3, nfile=3, rows_per_file=24, n_groups=6)

    manager = ExecutionPandas(env, args=args)
    files = sorted(manager.args.data_in.glob("*.csv"))

    assert len(files) == 3

    workers = {"127.0.0.1": 1}
    work_plan, metadata, partition_key, weights_key, unit = manager.build_distribution(workers)

    assert len(work_plan) == 1
    assert len(work_plan[0]) == 3
    assert partition_key == "file"
    assert weights_key == "size_kb"
    assert unit == "KB"
    assert metadata[0][0][0].endswith(".csv")
    assert "dir_path" not in manager.as_dict()


def test_execution_pandas_worker_processes_a_file(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    args = ExecutionPandasArgs(n_partitions=1, nfile=1, rows_per_file=16, n_groups=4)
    manager = ExecutionPandas(env, args=args)
    source = sorted(manager.args.data_in.glob("*.csv"))[0]

    worker = ExecutionPandasWorker()
    worker.env = env
    worker.args = manager.args.model_dump(mode="json")
    worker._worker_id = 0
    worker.verbose = 0
    worker.start()

    result = worker.work_pool(str(source))

    assert isinstance(result, pd.DataFrame)
    assert {"engine", "execution_model", "weighted_score", "source_file"} <= set(result.columns)
    assert set(result["engine"]) == {"pandas"}
    assert set(result["execution_model"]) == {"process"}


def test_execution_pandas_worker_runs_monoprocess_plan(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    args = ExecutionPandasArgs(n_partitions=2, nfile=2, rows_per_file=24, n_groups=6, reset_target=True)
    manager = ExecutionPandas(env, args=args)
    workers = {"127.0.0.1": 1}
    work_plan, metadata, *_ = manager.build_distribution(workers)

    worker = ExecutionPandasWorker()
    worker.env = env
    worker.args = manager.args.model_dump(mode="json")
    worker._worker_id = 0
    worker.worker_id = 0
    worker.verbose = 0
    worker._mode = 0

    BaseWorker._t0 = time.time()
    worker.start()
    seconds = worker.works(work_plan, metadata)

    assert seconds >= 0.0
    assert any(Path(worker.data_out).glob("*.csv"))
