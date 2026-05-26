"""Worker for the built-in R stage smoke app."""

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
from r_stage_smoke import RStageSmokeArgs, build_r_stage_smoke_artifacts
from r_stage_smoke.reduction import write_reduce_artifact

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


def _args_with_defaults(value: Any) -> RStageSmokeArgs:
    if isinstance(value, RStageSmokeArgs):
        return value
    if isinstance(value, dict):
        raw = dict(value)
    elif isinstance(value, SimpleNamespace):
        raw = vars(value).copy()
    else:
        raw = vars(value).copy()
    return RStageSmokeArgs(**{key: val for key, val in raw.items() if not key.startswith("_")})


def _copy_artifacts(source: Path, destination: Path) -> None:
    if source.resolve() == destination.resolve():
        return
    destination.mkdir(parents=True, exist_ok=True)
    for source_file in sorted(path for path in source.rglob("*") if path.is_file()):
        target_file = destination / source_file.relative_to(source)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, target_file)


class RStageSmokeWorker(PandasWorker):
    """Execute one Rscript stage through the AGILAB worker evidence path."""

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
            shutil.rmtree(self.data_out, ignore_errors=True)
        self.data_out.mkdir(parents=True, exist_ok=True)

        self.artifact_dir = _artifact_dir(self.env, "r_stage_smoke")
        if self.args.reset_target and self.artifact_dir.exists():
            shutil.rmtree(self.artifact_dir, ignore_errors=True)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

        self.script_path = self._resolve_script_path(self.args.script_path)
        self.pool_vars = {"args": self.args, "script_path": self.script_path}
        _runtime = self.pool_vars

    def _resolve_script_path(self, value: Path | str) -> Path:
        script = Path(value).expanduser()
        if script.is_absolute():
            return script
        active_app = getattr(self.env, "active_app", None)
        if active_app not in (None, ""):
            return Path(active_app) / script
        return Path.cwd() / script

    def pool_init(self, worker_vars):
        global _runtime
        _runtime = worker_vars

    def _current_args(self) -> RStageSmokeArgs:
        return _args_with_defaults(_runtime.get("args", self.args))

    def _current_script_path(self) -> Path:
        return Path(_runtime.get("script_path", self.script_path))

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
        summary = build_r_stage_smoke_artifacts(
            output_dir=Path(self.data_out),
            script_path=self._current_script_path(),
            x=args.x,
            rscript=args.rscript,
            timeout_seconds=args.timeout_seconds,
        )
        write_reduce_artifact([summary], self.data_out, worker_id=int(getattr(self, "_worker_id", 0)))
        _copy_artifacts(Path(self.data_out), Path(self.artifact_dir))
        metrics = dict(summary["metrics"])
        metrics["worker_id"] = int(getattr(self, "_worker_id", 0))
        metrics["data_out"] = str(self.data_out)
        metrics["artifact_dir"] = str(self.artifact_dir)
        metrics["output_json"] = str(Path(self.data_out) / "output.json")
        metrics["stdout_log"] = str(Path(self.data_out) / "stage_stdout.log")
        metrics["stderr_log"] = str(Path(self.data_out) / "stage_stderr.log")
        logger.info("wrote R stage smoke evidence to %s", self.data_out)
        return pd.DataFrame([metrics])

    def work_done(self, df: pd.DataFrame | None = None) -> None:
        return None


__all__ = ["RStageSmokeWorker"]
