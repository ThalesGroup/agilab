"""Pandas-based worker for the execution playground."""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
import time

import cython
import numpy as np
import pandas as pd

from agi_node.pandas_worker import PandasWorker
from execution_pandas.reduction import write_reduce_artifact

logger = logging.getLogger(__name__)
_runtime: dict[str, object] = {}
DATAFRAME_DTYPE_CONTRACT = "pandas-dataframe"
TYPED_NUMERIC_DTYPE_CONTRACT = "float64-contiguous"


@cython.boundscheck(False)
@cython.wraparound(False)
def _typed_numeric_score_kernel(
    x_values: cython.double[::1],
    y_values: cython.double[::1],
    signal_values: cython.double[::1],
    weight_values: cython.double[::1],
    score_0_out: cython.double[::1],
    score_last_out: cython.double[::1],
    pass_count: cython.Py_ssize_t,
    sample_stride: cython.Py_ssize_t,
) -> cython.double:
    """Fill score arrays through a Cython-friendly typed numeric loop."""
    n_rows: cython.Py_ssize_t = x_values.shape[0]
    row_idx: cython.Py_ssize_t
    pass_idx: cython.Py_ssize_t
    tail_idx: cython.Py_ssize_t
    tail_passes: cython.Py_ssize_t = pass_count * 8
    checksum: cython.double = 0.0
    score_value: cython.double = 0.0
    score_first: cython.double = 0.0
    score_last: cython.double = 0.0
    score_work: cython.double = 0.0
    tail_value: cython.double = 0.0
    x_value: cython.double = 0.0
    y_value: cython.double = 0.0
    signal_value: cython.double = 0.0
    weight_value: cython.double = 0.0

    for row_idx in range(n_rows):
        x_value = x_values[row_idx]
        y_value = y_values[row_idx]
        signal_value = signal_values[row_idx]
        weight_value = weight_values[row_idx]
        score_work = 0.0

        for pass_idx in range(pass_count):
            score_value = abs(
                (x_value * (pass_idx + 1.3))
                - (y_value * (0.35 + pass_idx * 0.05))
                + (signal_value * weight_value)
            )
            if pass_idx == 0:
                score_first = score_value
            score_last = score_value
            score_work += score_value * 0.000000001

        score_0_out[row_idx] = score_first
        score_last_out[row_idx] = score_last

        if sample_stride > 0 and row_idx % sample_stride == 0:
            tail_value = x_value + y_value * 0.01
            for tail_idx in range(tail_passes):
                tail_value = abs(
                    (tail_value * 1.0000007)
                    + signal_value * 0.17
                    - weight_value * 0.03
                )
            checksum += tail_value + score_work * 0.000001

    return checksum


def _kernel_runtime_label() -> str:
    return "cython" if cython.compiled else "python"


def _as_contiguous_float64(series: pd.Series) -> np.ndarray:
    return np.ascontiguousarray(series.to_numpy(dtype=np.float64, copy=False))


def _fill_vectorized_score_array(
    x_values: np.ndarray,
    y_values: np.ndarray,
    weighted_signal: np.ndarray,
    *,
    x_scale: float,
    y_scale: float,
    out: np.ndarray,
) -> None:
    """Fill one score output array with a low-allocation NumPy expression."""
    np.multiply(x_values, x_scale, out=out)
    out -= y_values * y_scale
    out += weighted_signal
    np.abs(out, out=out)


def _tail_checksum_from_arrays(
    x_values: np.ndarray,
    y_values: np.ndarray,
    signal_values: np.ndarray,
    weight_values: np.ndarray,
    *,
    pass_count: int,
    sample_stride: int = 64,
) -> float:
    loop_passes = max(pass_count, 1) * 8
    if sample_stride <= 0 or len(x_values) == 0:
        return 0.0
    x_sample = x_values[::sample_stride]
    y_sample = y_values[::sample_stride]
    signal_sample = signal_values[::sample_stride]
    weight_sample = weight_values[::sample_stride]
    values = x_sample + y_sample * 0.01
    for _ in range(loop_passes):
        values = np.abs((values * 1.0000007) + signal_sample * 0.17 - weight_sample * 0.03)
    return float(values.sum())


class ExecutionPandasWorker(PandasWorker):
    """Execute the benchmark workload through the PandasWorker path."""

    pool_vars: dict[str, object] = {}

    def start(self):
        global _runtime
        if isinstance(self.args, dict):
            self.args = SimpleNamespace(**self.args)
        elif not isinstance(self.args, SimpleNamespace):
            self.args = SimpleNamespace(**vars(self.args))

        data_paths = self.setup_data_directories(
            source_path=self.args.data_in,
            target_path=self.args.data_out,
            target_subdir="results",
            reset_target=bool(getattr(self.args, "reset_target", False)),
        )
        self.args.data_in = data_paths.normalized_input
        self.args.data_out = data_paths.normalized_output
        self.data_out = data_paths.output_path
        self.pool_vars = {"args": self.args}
        _runtime = self.pool_vars

    def pool_init(self, worker_vars):
        global _runtime
        _runtime = worker_vars

    def _current_args(self) -> SimpleNamespace:
        args = _runtime.get("args", self.args)
        if isinstance(args, dict):
            return SimpleNamespace(**args)
        return args

    def work_init(self) -> None:
        """Keep parity with the PandasWorker execution contract."""
        return None

    def _python_tail_checksum(self, df: pd.DataFrame) -> float:
        """Add a small GIL-bound scalar tail so execution modes separate more clearly."""
        args = self._current_args()
        return _tail_checksum_from_arrays(
            _as_contiguous_float64(df["x"]),
            _as_contiguous_float64(df["y"]),
            _as_contiguous_float64(df["signal"]),
            _as_contiguous_float64(df["weight"]),
            pass_count=max(int(getattr(args, "compute_passes", 1)), 1),
        )

    def _prepare_dataframe_scores(self, df: pd.DataFrame, passes: int) -> float:
        for idx in range(passes):
            column = f"score_{idx}"
            df[column] = (
                (df["x"] * (idx + 1.3))
                - (df["y"] * (0.35 + idx * 0.05))
                + (df["signal"] * df["weight"])
            ).abs()
        return self._python_tail_checksum(df)

    def _prepare_typed_numeric_scores(self, df: pd.DataFrame, passes: int) -> float:
        x_values = _as_contiguous_float64(df["x"])
        y_values = _as_contiguous_float64(df["y"])
        signal_values = _as_contiguous_float64(df["signal"])
        weight_values = _as_contiguous_float64(df["weight"])
        score_0 = np.empty(len(df), dtype=np.float64)
        score_last = np.empty(len(df), dtype=np.float64)
        if not cython.compiled:
            weighted_signal = np.multiply(signal_values, weight_values)
            _fill_vectorized_score_array(
                x_values,
                y_values,
                weighted_signal,
                x_scale=1.3,
                y_scale=0.35,
                out=score_0,
            )
            last_idx = passes - 1
            _fill_vectorized_score_array(
                x_values,
                y_values,
                weighted_signal,
                x_scale=last_idx + 1.3,
                y_scale=0.35 + last_idx * 0.05,
                out=score_last,
            )
            checksum = _tail_checksum_from_arrays(
                x_values,
                y_values,
                signal_values,
                weight_values,
                pass_count=passes,
            )
            df["score_0"] = score_0
            df[f"score_{passes - 1}"] = score_last
            return float(checksum)

        checksum = _typed_numeric_score_kernel(
            x_values,
            y_values,
            signal_values,
            weight_values,
            score_0,
            score_last,
            passes,
            64,
        )
        df["score_0"] = score_0
        df[f"score_{passes - 1}"] = score_last
        return float(checksum)

    def _prepare_scores(self, df: pd.DataFrame, passes: int, kernel_mode: str) -> tuple[str, str, float]:
        if kernel_mode == "dataframe":
            return (
                "dataframe",
                DATAFRAME_DTYPE_CONTRACT,
                self._prepare_dataframe_scores(df, passes),
            )
        return (
            "typed_numeric",
            TYPED_NUMERIC_DTYPE_CONTRACT,
            self._prepare_typed_numeric_scores(df, passes),
        )

    def works(self, workers_plan, workers_plan_metadata) -> float:
        """Treat pool and dask bits as parallel paths for this benchmark worker."""
        if workers_plan:
            if self._mode & 0b0101:
                self._exec_multi_process(workers_plan, workers_plan_metadata)
            else:
                self._exec_mono_process(workers_plan, workers_plan_metadata)

        self.stop()

        if getattr(PandasWorker, "_t0", None) is None:
            PandasWorker._t0 = time.time()
        return time.time() - PandasWorker._t0

    def work_pool(self, file_path):
        args = self._current_args()
        source = Path(str(file_path)).expanduser()
        df = pd.read_csv(source)

        passes = max(int(getattr(args, "compute_passes", 1)), 1)
        kernel_mode, dtype_contract, python_tail_checksum = self._prepare_scores(
            df,
            passes,
            str(getattr(args, "kernel_mode", "typed_numeric")),
        )

        agg = (
            df.groupby(["group_id", "bucket", "segment"], as_index=False)
            .agg(
                row_count=("row_id", "size"),
                x_sum=("x", "sum"),
                y_mean=("y", "mean"),
                score_mean=("score_0", "mean"),
                score_max=(f"score_{passes - 1}", "max"),
                weight_sum=("weight", "sum"),
            )
            .sort_values(["bucket", "group_id"])
        )

        segment_weights = pd.DataFrame(
            {
                "segment": ["alpha", "beta", "gamma", "delta"],
                "segment_weight": [1.00, 1.08, 1.14, 1.22],
            }
        )
        agg = agg.merge(segment_weights, on="segment", how="left")
        agg["weighted_score"] = agg["score_mean"] * agg["segment_weight"] * agg["row_count"]
        agg["python_tail_checksum"] = python_tail_checksum
        agg["kernel_mode"] = kernel_mode
        agg["kernel_runtime"] = _kernel_runtime_label()
        agg["dtype_contract"] = dtype_contract
        agg["source_file"] = source.name
        agg["engine"] = "pandas"
        agg["execution_model"] = "process"
        return agg

    def work_done(self, df: pd.DataFrame | None = None) -> None:
        if df is None or df.empty:
            return
        output_format = getattr(self._current_args(), "output_format", "csv")
        output_path = Path(self.data_out) / f"{self._worker_id}_output"
        if output_format == "parquet":
            df.to_parquet(output_path.with_suffix(".parquet"))
        else:
            df.to_csv(output_path.with_suffix(".csv"), index=False)
        artifact_path = write_reduce_artifact(
            df,
            self.data_out,
            worker_id=getattr(self, "_worker_id", 0),
        )
        logger.info("wrote execution_pandas reduce artifact: %s", artifact_path)
