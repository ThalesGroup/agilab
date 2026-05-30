"""Worker for the built-in PyTorch playground app."""

from __future__ import annotations

import logging
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd

from agi_node.agi_dispatcher import BaseWorker
from agi_node.pandas_worker import PandasWorker
from pytorch_playground import PytorchPlaygroundArgs, to_playground_config
from pytorch_playground.core import (
    _build_evidence_manifest,
    _build_evidence_pack,
    _evidence_artifact_files,
    _empty_loss_landscape,
    _json_bytes,
    _loss_landscape,
    _loss_landscape_summary,
    _train_playground,
)
from pytorch_playground.reduction import write_reduce_artifact

logger = logging.getLogger(__name__)
_runtime: dict[str, object] = {}


def _args_model() -> type[Any]:
    module = sys.modules.get("pytorch_playground.app_args")
    model = getattr(module, "PytorchPlaygroundArgs", None)
    if isinstance(model, type) and model.__name__ == "PytorchPlaygroundArgs":
        return model
    return PytorchPlaygroundArgs


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


def _args_with_defaults(value: Any) -> PytorchPlaygroundArgs:
    args_model = _args_model()
    if isinstance(value, (PytorchPlaygroundArgs, args_model)):
        return value
    model_dump = getattr(value, "model_dump", None)
    if value.__class__.__name__ == "PytorchPlaygroundArgs" and callable(model_dump):
        if value.__class__.__module__ == args_model.__module__:
            return value
        raw = model_dump(mode="json")
    elif isinstance(value, dict):
        raw = dict(value)
    elif isinstance(value, SimpleNamespace):
        raw = vars(value).copy()
    else:
        raw = vars(value).copy()
    return args_model(**{key: val for key, val in raw.items() if not key.startswith("_")})


def _write_artifact_files(root: Path, files: dict[str, bytes]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for relative_name, payload in sorted(files.items()):
        destination = root / relative_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)


class PytorchPlaygroundWorker(PandasWorker):
    """Train one playground configuration and export deterministic evidence."""

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
        self.artifact_dir = _artifact_dir(self.env, "pytorch_playground")
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.pool_vars = {"args": self.args}
        _runtime = self.pool_vars

    def pool_init(self, worker_vars):
        global _runtime
        _runtime = worker_vars

    def _current_args(self) -> PytorchPlaygroundArgs:
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
        config = to_playground_config(args)
        result = _train_playground(config)
        loss_landscape = _empty_loss_landscape()
        if args.compute_loss_landscape and result.get("status") == "ok":
            landscape_result = _loss_landscape(
                config,
                resolution=args.landscape_resolution,
                span=args.landscape_span,
            )
            loss_landscape = landscape_result.get("loss_landscape", _empty_loss_landscape())
            result["loss_landscape"] = loss_landscape
            result["landscape_summary"] = landscape_result.get(
                "landscape_summary",
                _loss_landscape_summary(loss_landscape),
            )

        files = _evidence_artifact_files(config, result)
        manifest = _build_evidence_manifest(config, result)
        files["manifest.json"] = _json_bytes(manifest)
        files["pytorch_playground_evidence.zip"] = _build_evidence_pack(config, result)

        for root in (Path(self.data_out), Path(self.artifact_dir)):
            _write_artifact_files(root, files)

        summary = dict(result.get("summary", {}))
        summary["worker_id"] = int(getattr(self, "_worker_id", 0))
        summary["data_out"] = str(self.data_out)
        summary["artifact_dir"] = str(self.artifact_dir)
        summary["loss_landscape_points"] = int(len(loss_landscape))
        for root in (Path(self.data_out), Path(self.artifact_dir)):
            write_reduce_artifact(
                summary,
                root,
                worker_id=int(getattr(self, "_worker_id", 0)),
            )
        logger.info("wrote PyTorch playground evidence to %s", self.data_out)
        return pd.DataFrame([summary])

    def work_done(self, df: pd.DataFrame | None = None) -> None:
        return None


__all__ = ["PytorchPlaygroundWorker"]
