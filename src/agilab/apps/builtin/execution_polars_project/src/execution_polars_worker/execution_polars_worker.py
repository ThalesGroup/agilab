"""Polars-based worker for the execution playground."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

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
        agg = (
            agg.join(segment_weights, on="segment", how="left")
            .with_columns(
                (pl.col("score_mean") * pl.col("segment_weight") * pl.col("row_count")).alias("weighted_score"),
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
