"""Polars-based worker for the execution playground."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import time

import polars as pl

from agi_node.polars_worker import PolarsWorker

_runtime: dict[str, object] = {}


class ExecutionPolarsWorker(PolarsWorker):
    """Execute the benchmark workload through the PolarsWorker path."""

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
        """Keep parity with the PolarsWorker execution contract."""
        return None

    def _python_tail_checksum(self, df: pl.DataFrame) -> float:
        """Add a small GIL-bound scalar tail so execution modes separate more clearly."""
        args = self._current_args()
        loop_passes = max(int(getattr(args, "compute_passes", 1)), 1) * 8
        sample_stride = 64
        checksum = 0.0
        x_values = df["x"].to_list()
        y_values = df["y"].to_list()
        signal_values = df["signal"].to_list()
        weight_values = df["weight"].to_list()
        for idx in range(0, len(x_values), sample_stride):
            value = float(x_values[idx]) + float(y_values[idx]) * 0.01
            signal = float(signal_values[idx])
            weight = float(weight_values[idx])
            for _ in range(loop_passes):
                value = abs((value * 1.0000007) + signal * 0.17 - weight * 0.03)
            checksum += value
        return checksum

    def works(self, workers_plan, workers_plan_metadata) -> float:
        """Treat pool and dask bits as parallel paths for this benchmark worker."""
        if workers_plan:
            if self._mode & 0b0101:
                self._exec_multi_process(workers_plan, workers_plan_metadata)
            else:
                self._exec_mono_process(workers_plan, workers_plan_metadata)

        self.stop()

        if getattr(PolarsWorker, "_t0", None) is None:
            PolarsWorker._t0 = time.time()
        return time.time() - PolarsWorker._t0

    def work_pool(self, file_path):
        args = self._current_args()
        source = Path(str(file_path)).expanduser()
        df = pl.read_csv(source)

        passes = max(int(getattr(args, "compute_passes", 1)), 1)
        for idx in range(passes):
            column = f"score_{idx}"
            df = df.with_columns(
                (
                    (pl.col("x") * (idx + 1.3))
                    - (pl.col("y") * (0.35 + idx * 0.05))
                    + (pl.col("signal") * pl.col("weight"))
                )
                .abs()
                .alias(column)
            )

        agg = (
            df.group_by(["group_id", "bucket", "segment"])
            .agg(
                pl.len().alias("row_count"),
                pl.col("x").sum().alias("x_sum"),
                pl.col("y").mean().alias("y_mean"),
                pl.col("score_0").mean().alias("score_mean"),
                pl.col(f"score_{passes - 1}").max().alias("score_max"),
                pl.col("weight").sum().alias("weight_sum"),
            )
            .sort(["bucket", "group_id"])
        )

        segment_weights = pl.DataFrame(
            {
                "segment": ["alpha", "beta", "gamma", "delta"],
                "segment_weight": [1.00, 1.08, 1.14, 1.22],
            }
        )
        python_tail_checksum = self._python_tail_checksum(df)
        agg = (
            agg.join(segment_weights, on="segment", how="left")
            .with_columns(
                (pl.col("score_mean") * pl.col("segment_weight") * pl.col("row_count")).alias("weighted_score"),
                pl.lit(python_tail_checksum).alias("python_tail_checksum"),
                pl.lit(source.name).alias("source_file"),
                pl.lit("polars").alias("engine"),
                pl.lit("threads").alias("execution_model"),
            )
        )
        return agg

    def work_done(self, df: pl.DataFrame | None = None) -> None:
        if df is None or df.is_empty():
            return
        output_format = getattr(self._current_args(), "output_format", "csv")
        output_path = Path(self.data_out) / f"{self._worker_id}_output"
        if output_format == "parquet":
            df.write_parquet(output_path.with_suffix(".parquet"))
        else:
            df.write_csv(output_path.with_suffix(".csv"))
