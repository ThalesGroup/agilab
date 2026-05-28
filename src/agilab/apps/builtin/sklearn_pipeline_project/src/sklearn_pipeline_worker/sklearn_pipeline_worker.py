"""Worker for the built-in scikit-learn pipeline app."""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd

from agi_node.agi_dispatcher import BaseWorker
from agi_node.pandas_worker import PandasWorker
from sklearn_pipeline import (
    SklearnPipelineArgs,
    build_sklearn_pipeline_artifacts,
    safe_reset_path,
    share_root_from_env,
)
from sklearn_pipeline.reduction import write_reduce_artifact

logger = logging.getLogger(__name__)
_runtime: dict[str, object] = {}


def _artifact_dir(env: object, leaf: str) -> Path:
    export_root = getattr(env, "AGILAB_EXPORT_ABS", None)
    target = str(getattr(env, "target", "") or "")
    relative = Path(target) / leaf if target else Path(leaf)
    if export_root is not None:
        return Path(export_root) / relative
    resolve_share_path = getattr(env, "resolve_share_path", None)
    if callable(resolve_share_path):
        return Path(resolve_share_path(relative))
    return Path.home() / "export" / relative


def _artifact_reset_root(env: object) -> Path:
    export_root = Path(getattr(env, "AGILAB_EXPORT_ABS", Path.home() / "export"))
    target = str(getattr(env, "target", "") or "")
    return export_root / target if target else export_root


def _args_with_defaults(value: Any) -> SklearnPipelineArgs:
    if isinstance(value, SklearnPipelineArgs):
        return value
    if isinstance(value, dict):
        raw = dict(value)
    elif isinstance(value, SimpleNamespace):
        raw = vars(value).copy()
    else:
        raw = vars(value).copy()
    return SklearnPipelineArgs(**{key: val for key, val in raw.items() if not key.startswith("_")})


def _copy_artifacts(source: Path, destination: Path) -> None:
    if source.resolve() == destination.resolve():
        return
    destination.mkdir(parents=True, exist_ok=True)
    for source_file in sorted(path for path in source.rglob("*") if path.is_file()):
        target_file = destination / source_file.relative_to(source)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, target_file)


class SklearnPipelineWorker(PandasWorker):
    """Train one sklearn configuration and export deterministic evidence."""

    pool_vars: dict[str, object] = {}

    def start(self):
        global _runtime
        self.args = _args_with_defaults(self.args)
        data_out = Path(self.args.data_out).expanduser()
        if not data_out.is_absolute() and callable(getattr(self.env, "resolve_share_path", None)):
            data_out = Path(self.env.resolve_share_path(data_out))
        self.args.data_out = data_out
        self.data_out = data_out
        if self.args.reset_target and self.data_out.exists():
            reset_path = safe_reset_path(self.data_out, share_root=share_root_from_env(self.env), label="data_out")
            shutil.rmtree(reset_path, ignore_errors=True)
        self.data_out.mkdir(parents=True, exist_ok=True)
        self.artifact_dir = _artifact_dir(self.env, "sklearn_pipeline")
        if self.args.reset_target and self.artifact_dir.exists():
            reset_path = safe_reset_path(
                self.artifact_dir,
                share_root=_artifact_reset_root(self.env),
                label="artifact_dir",
            )
            shutil.rmtree(reset_path, ignore_errors=True)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.pool_vars = {"args": self.args}
        _runtime = self.pool_vars

    def pool_init(self, worker_vars):
        global _runtime
        _runtime = worker_vars

    def _current_args(self) -> SklearnPipelineArgs:
        return _args_with_defaults(_runtime.get("args", self.args))

    def work_init(self) -> None:
        return None

    def works(self, workers_plan: Any, workers_plan_metadata: Any) -> float:
        assigned_batches: list[Any] = []
        if isinstance(workers_plan, list) and len(workers_plan) > self._worker_id:
            worker_batches = workers_plan[self._worker_id]
            if isinstance(worker_batches, list):
                assigned_batches = worker_batches

        self.work_init()
        for batch in assigned_batches:
            work_items = list(batch) if isinstance(batch, (list, tuple)) else [batch]
            for work_item in work_items:
                summary = self.work_pool(work_item)
                self.work_done(summary)

        self.stop()

        if BaseWorker._t0 is None:
            BaseWorker._t0 = time.time()
        return time.time() - BaseWorker._t0

    def work_pool(self, _work_item):
        args = self._current_args()
        summary = build_sklearn_pipeline_artifacts(
            output_dir=Path(self.data_out),
            seed=args.seed,
            sample_count=args.sample_count,
            test_size=args.test_size,
            regularization_c=args.regularization_c,
        )
        write_reduce_artifact([summary], self.data_out, worker_id=int(getattr(self, "_worker_id", 0)))
        _copy_artifacts(Path(self.data_out), Path(self.artifact_dir))
        metrics = dict(summary["metrics"])
        metrics["worker_id"] = int(getattr(self, "_worker_id", 0))
        metrics["data_out"] = str(self.data_out)
        metrics["artifact_dir"] = str(self.artifact_dir)
        logger.info("wrote sklearn pipeline evidence to %s", self.data_out)
        return pd.DataFrame([metrics])

    def work_done(self, df: pd.DataFrame | None = None) -> None:
        return None


__all__ = ["SklearnPipelineWorker"]
