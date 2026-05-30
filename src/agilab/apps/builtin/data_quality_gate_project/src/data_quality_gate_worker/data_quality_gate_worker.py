"""Worker for the built-in data quality gate app."""

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
from data_quality_gate import (
    DataQualityGateArgs,
    build_data_quality_gate_artifacts,
    safe_reset_path,
    share_root_from_env,
)
from data_quality_gate.reduction import write_reduce_artifact

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


def _args_with_defaults(value: Any) -> DataQualityGateArgs:
    if isinstance(value, DataQualityGateArgs):
        return value
    if isinstance(value, dict):
        raw = dict(value)
    elif isinstance(value, SimpleNamespace):
        raw = vars(value).copy()
    else:
        raw = vars(value).copy()
    return DataQualityGateArgs(**{key: val for key, val in raw.items() if not key.startswith("_")})


def _resolve_optional_share_path(env: object, value: Path | None) -> Path | None:
    if value is None:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute() and callable(getattr(env, "resolve_share_path", None)):
        path = Path(env.resolve_share_path(path))
    return path


def _copy_artifacts(source: Path, destination: Path) -> None:
    if source.resolve() == destination.resolve():
        return
    destination.mkdir(parents=True, exist_ok=True)
    for source_file in sorted(path for path in source.rglob("*") if path.is_file()):
        target_file = destination / source_file.relative_to(source)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, target_file)


class DataQualityGateWorker(PandasWorker):
    """Run one data contract and drift gate, then export deterministic evidence."""

    pool_vars: dict[str, object] = {}

    def start(self):
        global _runtime
        self.args = _args_with_defaults(self.args)
        data_out = Path(self.args.data_out).expanduser()
        if not data_out.is_absolute() and callable(getattr(self.env, "resolve_share_path", None)):
            data_out = Path(self.env.resolve_share_path(data_out))
        self.args.data_out = data_out
        self.args.baseline_csv = _resolve_optional_share_path(self.env, self.args.baseline_csv)
        self.args.candidate_csv = _resolve_optional_share_path(self.env, self.args.candidate_csv)
        self.args.contract_json = _resolve_optional_share_path(self.env, self.args.contract_json)
        self.args.thresholds_json = _resolve_optional_share_path(self.env, self.args.thresholds_json)
        self.data_out = data_out
        if self.args.reset_target and self.data_out.exists():
            reset_path = safe_reset_path(self.data_out, share_root=share_root_from_env(self.env), label="data_out")
            shutil.rmtree(reset_path, ignore_errors=True)
        self.data_out.mkdir(parents=True, exist_ok=True)
        self.artifact_dir = _artifact_dir(self.env, "data_quality_gate")
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

    def _current_args(self) -> DataQualityGateArgs:
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
        summary = build_data_quality_gate_artifacts(
            output_dir=Path(self.data_out),
            baseline_csv=args.baseline_csv,
            candidate_csv=args.candidate_csv,
            contract_json=args.contract_json,
            thresholds_json=args.thresholds_json,
            baseline_rows=args.baseline_rows,
            candidate_rows=args.candidate_rows,
            drift_strength=args.drift_strength,
            seed=args.seed,
            include_quality_issues=args.include_quality_issues,
        )
        write_reduce_artifact([summary], self.data_out, worker_id=int(getattr(self, "_worker_id", 0)))
        _copy_artifacts(Path(self.data_out), Path(self.artifact_dir))
        metrics = {
            "decision": summary["decision"],
            "input_mode": summary["input_mode"],
            "max_psi": summary["drift"]["max_psi"],
            "max_ks_statistic": summary["drift"]["max_ks_statistic"],
            "recommended_action": summary["recommended_action"],
            "risk_score": summary["risk_score"],
            "warn_feature_count": summary["drift"]["warn_feature_count"],
            "block_feature_count": summary["drift"]["block_feature_count"],
            "worker_id": int(getattr(self, "_worker_id", 0)),
            "data_out": str(self.data_out),
            "artifact_dir": str(self.artifact_dir),
        }
        logger.info("wrote data quality gate evidence to %s", self.data_out)
        return pd.DataFrame([metrics])

    def work_done(self, df: pd.DataFrame | None = None) -> None:
        return None


__all__ = ["DataQualityGateWorker"]
