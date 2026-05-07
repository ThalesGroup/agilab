"""Worker for the public Data IO 2026 autonomous mission decision demo."""

from __future__ import annotations

import csv
import json
import logging
import re
import shutil
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from agi_node.agi_dispatcher import BaseWorker
from agi_node.pandas_worker import PandasWorker
from data_io_2026 import DataIo2026Args
from data_io_2026.artifacts import build_decision_artifacts
from data_io_2026.reduction import write_reduce_artifact

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


def _sanitize_slug(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_-]+", "_", value.strip())
    cleaned = cleaned.strip("_")
    return cleaned or "data_io_2026_run"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _args_with_defaults(value: Any) -> SimpleNamespace:
    if isinstance(value, dict):
        raw = dict(value)
    elif isinstance(value, SimpleNamespace):
        raw = vars(value).copy()
    else:
        raw = vars(value).copy()
    defaults = DataIo2026Args().model_dump(mode="json")
    defaults.update({key: val for key, val in raw.items() if not key.startswith("_")})
    return SimpleNamespace(**defaults)


class DataIo2026Worker(PandasWorker):
    """Execute one mission scenario and export decision evidence artifacts."""

    pool_vars: dict[str, object] = {}

    def start(self):
        global _runtime
        self.args = _args_with_defaults(self.args)

        data_paths = self.setup_data_directories(
            source_path=self.args.data_in,
            target_path=self.args.data_out,
            target_subdir="results",
            reset_target=bool(getattr(self.args, "reset_target", False)),
        )
        self.args.data_in = data_paths.normalized_input
        self.args.data_out = data_paths.normalized_output
        self.data_out = data_paths.output_path
        self.artifact_dir = _artifact_dir(self.env, "data_io_decision")
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
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
        return None

    def works(self, workers_plan: Any, workers_plan_metadata: Any) -> float:
        """Execute assigned mission scenario batches."""

        assigned_batches: list[Any] = []
        if isinstance(workers_plan, list) and len(workers_plan) > self._worker_id:
            worker_batches = workers_plan[self._worker_id]
            if isinstance(worker_batches, list):
                assigned_batches = worker_batches

        self.work_init()
        for batch in assigned_batches:
            work_items = list(batch) if isinstance(batch, (list, tuple)) else [batch]
            for work_item in work_items:
                result = self.work_pool(work_item)
                self.work_done(result)

        self.stop()

        if BaseWorker._t0 is None:
            BaseWorker._t0 = time.time()
        return time.time() - BaseWorker._t0

    def _load_scenario(self, file_path: str | Path) -> dict[str, Any]:
        source = Path(str(file_path)).expanduser()
        payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Scenario file must contain a JSON object: {source}")
        if not isinstance(payload.get("routes"), list):
            raise ValueError(f"Scenario file must declare candidate routes: {source}")
        return payload

    def work_pool(self, file_path):
        scenario = self._load_scenario(file_path)
        artifacts = build_decision_artifacts(scenario, self._current_args())
        artifacts["source_file"] = str(file_path)
        artifacts["worker_id"] = int(getattr(self, "_worker_id", 0))
        return artifacts

    def _write_artifact_bundle(self, root: Path, artifacts: dict[str, Any]) -> None:
        stem = _sanitize_slug(str(artifacts["artifact_stem"]))
        run_root = root / stem
        if run_root.exists() and bool(getattr(self._current_args(), "reset_target", False)):
            shutil.rmtree(run_root)
        run_root.mkdir(parents=True, exist_ok=True)

        summary = dict(artifacts["summary"])
        summary["worker_id"] = artifacts.get("worker_id", 0)
        summary["source_file"] = artifacts.get("source_file", "")

        _write_json(run_root / f"{stem}_summary_metrics.json", summary)
        write_reduce_artifact(
            summary,
            run_root,
            worker_id=artifacts.get("worker_id", 0),
        )
        _write_json(run_root / f"{stem}_mission_decision.json", artifacts["mission_decision"])
        _write_json(run_root / f"{stem}_generated_pipeline.json", artifacts["generated_pipeline"])
        _write_csv(run_root / f"{stem}_sensor_stream.csv", artifacts["sensor_stream"])
        _write_csv(run_root / f"{stem}_feature_table.csv", artifacts["feature_table"])
        _write_csv(run_root / f"{stem}_candidate_routes.csv", artifacts["candidate_routes"])
        _write_csv(run_root / f"{stem}_decision_timeline.csv", artifacts["decision_timeline"])

    def work_done(self, artifacts: dict[str, Any] | None = None) -> None:
        if not artifacts:
            return
        self._write_artifact_bundle(Path(self.data_out), artifacts)
        self._write_artifact_bundle(self.artifact_dir, artifacts)
        logger.info("wrote Data IO 2026 decision artifacts for %s", artifacts["artifact_stem"])


__all__ = ["DataIo2026Worker"]
