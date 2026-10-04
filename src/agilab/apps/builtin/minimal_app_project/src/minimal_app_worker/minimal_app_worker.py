"""Default CSV/Parquet pass-through worker for the minimal app template."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl

from agi_node.polars_worker.polars_worker import PolarsWorker

_runtime: dict[str, Any] = {}


class MinimalAppWorker(PolarsWorker):
    """Read dispatched tables and persist their rows as Parquet."""

    pool_vars: dict[str, Any] = {}

    def start(self) -> None:
        global _runtime
        raw = self.args.model_dump() if hasattr(self.args, "model_dump") else self.args
        self.args = dict(raw) if isinstance(raw, dict) else vars(raw).copy()
        paths = self.setup_data_directories(
            source_path=self.args.get("data_in", "minimal_app/dataset"),
            target_path=self.args.get("data_out", "minimal_app/dataframe"),
            target_subdir="dataframe",
            reset_target=bool(self.args.get("reset_target", False)),
        )
        self.args["data_in"] = paths.normalized_input
        self.args["data_out"] = paths.normalized_output
        self.args["output_format"] = "parquet"
        self.data_out = paths.output_path
        self.pool_vars = {"args": self.args}
        _runtime = self.pool_vars

    def pool_init(self, worker_vars: dict[str, Any]) -> None:
        global _runtime
        _runtime = worker_vars

    def work_init(self) -> None:
        pass

    def work_pool(self, file_path: str | Path) -> pl.DataFrame:
        """Keep input columns, types and values; optionally slice input rows."""
        source = Path(file_path)
        if source.suffix.lower() == ".csv":
            frame = pl.read_csv(source)
        elif source.suffix.lower() == ".parquet":
            frame = pl.read_parquet(source)
        else:
            raise ValueError(f"Minimal app supports CSV or Parquet input: {source}")
        args = _runtime.get("args", self.args)
        skip = max(int(args.get("nskip", 0)), 0)
        read = max(int(args.get("nread", 0)), 0)
        return frame.slice(skip, read if read else None)
