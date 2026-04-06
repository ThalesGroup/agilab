"""Execution playground manager for the polars worker path."""

from __future__ import annotations

import csv
import json
import logging
import math
import random
import shutil
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from agi_node.agi_dispatcher import BaseWorker, WorkDispatcher

from .app_args import (
    ArgsOverrides,
    ExecutionPolarsArgs,
    dump_args,
    ensure_defaults,
    load_args,
    merge_args,
)

logger = logging.getLogger(__name__)


class ExecutionPolars(BaseWorker):
    """AGILab manager that generates the same workload as the pandas variant."""

    worker_vars: dict[str, Any] = {}

    def __init__(
        self,
        env,
        args: ExecutionPolarsArgs | None = None,
        **kwargs: ArgsOverrides,
    ) -> None:
        self.env = env
        self._ensure_managed_pc_share_dir(env)
        self.verbose = int(kwargs.pop("verbose", getattr(env, "verbose", 0) or 0))

        if args is None:
            try:
                args = ExecutionPolarsArgs(**kwargs)
            except ValidationError as exc:
                raise ValueError(f"Invalid ExecutionPolars arguments: {exc}") from exc

        self.args = ensure_defaults(args, env=env)
        self.args = self._apply_managed_pc_paths(self.args)
        self.args.data_in = env.resolve_share_path(self.args.data_in)
        self.args.data_out = env.resolve_share_path(self.args.data_out)
        self.data_out = self.args.data_out

        self.args.data_in.mkdir(parents=True, exist_ok=True)
        self._ensure_dataset(self.args.data_in)

        if self.args.reset_target and self.data_out.exists():
            shutil.rmtree(self.data_out, ignore_errors=True, onerror=WorkDispatcher._onerror)
        self.data_out.mkdir(parents=True, exist_ok=True)

        WorkDispatcher.args = self.args.model_dump(mode="json")

    @classmethod
    def from_toml(
        cls,
        env,
        settings_path: str | Path = "app_settings.toml",
        section: str = "args",
        **overrides: ArgsOverrides,
    ) -> "ExecutionPolars":
        base = load_args(settings_path, section=section)
        merged = ensure_defaults(merge_args(base, overrides or None), env=env)
        return cls(env, args=merged)

    def to_toml(
        self,
        settings_path: str | Path = "app_settings.toml",
        section: str = "args",
        create_missing: bool = True,
    ) -> None:
        dump_args(self.args, settings_path, section=section, create_missing=create_missing)

    def as_dict(self) -> dict[str, Any]:
        return self.args.model_dump(mode="json")

    def _manifest_path(self, data_in: Path) -> Path:
        return data_in / "_execution_playground_manifest.json"

    def _dataset_manifest(self) -> dict[str, int]:
        return {
            "n_partitions": int(self.args.n_partitions),
            "rows_per_file": int(self.args.rows_per_file),
            "n_groups": int(self.args.n_groups),
            "seed": int(self.args.seed),
        }

    def _ensure_dataset(self, data_in: Path) -> None:
        manifest_path = self._manifest_path(data_in)
        expected = self._dataset_manifest()
        existing_files = sorted(data_in.glob(self.args.files))
        regenerate = not existing_files

        if manifest_path.exists():
            try:
                current = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                current = {}
            regenerate = regenerate or current != expected
        else:
            regenerate = True

        if not regenerate:
            return

        for candidate in data_in.glob("*.csv"):
            candidate.unlink()

        segments = ("alpha", "beta", "gamma", "delta")
        for partition_idx in range(self.args.n_partitions):
            rng = random.Random(self.args.seed + partition_idx)
            output = data_in / f"part_{partition_idx:02d}.csv"
            with output.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(
                    ["row_id", "group_id", "bucket", "segment", "x", "y", "signal", "weight"]
                )
                for row_idx in range(self.args.rows_per_file):
                    group_id = row_idx % self.args.n_groups
                    bucket = (group_id + partition_idx) % 8
                    segment = segments[group_id % len(segments)]
                    x = round(rng.random() * 100.0 + group_id * 0.3, 6)
                    y = round(rng.random() * 50.0 + bucket * 0.7 + math.sin(row_idx / 17.0), 6)
                    signal = round(((row_idx % 97) - 48) * 0.15 + rng.random() * 0.25, 6)
                    weight = round(1.0 + (row_idx % 11) * 0.05 + partition_idx * 0.01, 6)
                    writer.writerow(
                        [f"{partition_idx}-{row_idx}", group_id, bucket, segment, x, y, signal, weight]
                    )

        manifest_path.write_text(json.dumps(expected, indent=2), encoding="utf-8")

    def build_distribution(self, workers):
        files = sorted(self.args.data_in.glob(self.args.files))
        if self.args.nfile > 0:
            files = files[: self.args.nfile]
        if not files:
            raise FileNotFoundError(
                f"No workload files found in {self.args.data_in} with pattern {self.args.files!r}"
            )

        weights = [(str(path), max(int(path.stat().st_size // 1024), 1)) for path in files]
        if len(weights) == 1:
            worker_chunks = [[weights[0]]]
        else:
            worker_chunks = WorkDispatcher.make_chunks(
                len(weights),
                weights,
                workers=workers,
                verbose=self.verbose,
                threshold=12,
            )

        work_plan = []
        work_plan_metadata = []
        for chunk in worker_chunks:
            file_batch = [file_path for file_path, _ in chunk]
            total_size_kb = sum(size_kb for _, size_kb in chunk)
            batch_label = (
                Path(file_batch[0]).name
                if len(file_batch) == 1
                else f"{len(file_batch)} files"
            )
            work_plan.append([file_batch])
            work_plan_metadata.append(
                [{"file": batch_label, "size_kb": total_size_kb}]
            )

        return work_plan, work_plan_metadata, "file", "size_kb", "KB"


class ExecutionPolarsApp(ExecutionPolars):
    """Compatibility alias retaining the historic *App suffix."""


__all__ = ["ExecutionPolars", "ExecutionPolarsApp"]
