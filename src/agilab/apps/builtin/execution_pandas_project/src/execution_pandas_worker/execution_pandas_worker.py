"""Pandas-based worker for the execution playground."""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from agi_node.pandas_worker import PandasWorker

logger = logging.getLogger(__name__)
_runtime: dict[str, object] = {}


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

    def work_pool(self, file_path):
        args = self._current_args()
        source = Path(str(file_path)).expanduser()
        df = pd.read_csv(source)

        passes = max(int(getattr(args, "compute_passes", 1)), 1)
        for idx in range(passes):
            column = f"score_{idx}"
            df[column] = (
                (df["x"] * (idx + 1.3))
                - (df["y"] * (0.35 + idx * 0.05))
                + (df["signal"] * df["weight"])
            ).abs()

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
