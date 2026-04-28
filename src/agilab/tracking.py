from __future__ import annotations

import atexit
import importlib
import os
from pathlib import Path
from typing import Any, Mapping

AGILAB_RUN_ID_ENV = "AGILAB_PIPELINE_MLFLOW_RUN_ID"
MLFLOW_RUN_ID_ENV = "MLFLOW_RUN_ID"
MLFLOW_TRACKING_URI_ENV = "MLFLOW_TRACKING_URI"


class Tracker:
    """Small AGILAB tracking facade backed by MLflow when MLflow is available."""

    def __init__(self) -> None:
        self._mlflow: Any | None = None
        self._mlflow_import_attempted = False
        self._started_run = False

    @property
    def backend(self) -> str:
        return "mlflow" if self.available else "none"

    @property
    def available(self) -> bool:
        return self._get_mlflow() is not None

    @property
    def active_run_id(self) -> str | None:
        mlflow = self._get_mlflow()
        if mlflow is None:
            return None
        active_run = self._active_run(mlflow)
        if active_run is None:
            return None
        return getattr(getattr(active_run, "info", None), "run_id", None)

    def configure(self, *, tracking_uri: str | None = None, run_id: str | None = None) -> bool:
        mlflow = self._get_mlflow()
        if mlflow is None:
            return False
        return self._configure_mlflow(mlflow, tracking_uri=tracking_uri, run_id=run_id)

    def log_param(self, key: str, value: Any) -> bool:
        mlflow = self._ready_mlflow()
        if mlflow is None:
            return False
        mlflow.log_param(str(key), value)
        return True

    def log_params(self, params: Mapping[str, Any]) -> bool:
        mlflow = self._ready_mlflow()
        if mlflow is None:
            return False
        clean_params = {str(key): value for key, value in params.items()}
        if clean_params:
            mlflow.log_params(clean_params)
        return True

    def log_metric(self, key: str, value: float, *, step: int | None = None) -> bool:
        mlflow = self._ready_mlflow()
        if mlflow is None:
            return False
        kwargs = {"step": step} if step is not None else {}
        mlflow.log_metric(str(key), float(value), **kwargs)
        return True

    def log_metrics(self, metrics: Mapping[str, float], *, step: int | None = None) -> bool:
        mlflow = self._ready_mlflow()
        if mlflow is None:
            return False
        clean_metrics = {str(key): float(value) for key, value in metrics.items()}
        if clean_metrics:
            kwargs = {"step": step} if step is not None else {}
            mlflow.log_metrics(clean_metrics, **kwargs)
        return True

    def set_tag(self, key: str, value: Any) -> bool:
        mlflow = self._ready_mlflow()
        if mlflow is None:
            return False
        mlflow.set_tag(str(key), value)
        return True

    def set_tags(self, tags: Mapping[str, Any]) -> bool:
        mlflow = self._ready_mlflow()
        if mlflow is None:
            return False
        clean_tags = {str(key): value for key, value in tags.items()}
        if clean_tags:
            mlflow.set_tags(clean_tags)
        return True

    def log_artifact(self, artifact: str | Path, *, artifact_path: str | None = None) -> bool:
        mlflow = self._ready_mlflow()
        if mlflow is None:
            return False
        artifact_file = Path(artifact).expanduser()
        if not artifact_file.exists():
            return False
        kwargs = {"artifact_path": artifact_path} if artifact_path else {}
        mlflow.log_artifact(str(artifact_file), **kwargs)
        return True

    def log_text(self, text: Any, artifact_file: str) -> bool:
        mlflow = self._ready_mlflow()
        if mlflow is None:
            return False
        if not hasattr(mlflow, "log_text"):
            return False
        mlflow.log_text(str(text), artifact_file)
        return True

    def _ready_mlflow(self) -> Any | None:
        mlflow = self._get_mlflow()
        if mlflow is None:
            return None
        if not self._configure_mlflow(mlflow):
            return None
        return mlflow

    def _get_mlflow(self) -> Any | None:
        if self._mlflow_import_attempted:
            return self._mlflow
        self._mlflow_import_attempted = True
        try:
            self._mlflow = importlib.import_module("mlflow")
        except ImportError:
            self._mlflow = None
        return self._mlflow

    def _configure_mlflow(
        self,
        mlflow: Any,
        *,
        tracking_uri: str | None = None,
        run_id: str | None = None,
    ) -> bool:
        tracking_uri = tracking_uri or os.environ.get(MLFLOW_TRACKING_URI_ENV)
        if tracking_uri and hasattr(mlflow, "set_tracking_uri"):
            mlflow.set_tracking_uri(tracking_uri)

        active_run = self._active_run(mlflow)
        if active_run is not None:
            return True

        run_id = run_id or os.environ.get(AGILAB_RUN_ID_ENV) or os.environ.get(MLFLOW_RUN_ID_ENV)
        if not run_id:
            return True
        try:
            mlflow.start_run(run_id=run_id)
        except (RuntimeError, ValueError, TypeError, AttributeError):
            return False
        if not self._started_run:
            self._started_run = True
            atexit.register(self._end_started_run)
        return True

    @staticmethod
    def _active_run(mlflow: Any) -> Any | None:
        active_run_fn = getattr(mlflow, "active_run", None)
        if active_run_fn is None:
            return None
        try:
            return active_run_fn()
        except (RuntimeError, AttributeError):
            return None

    def _end_started_run(self) -> None:
        mlflow = self._mlflow
        if mlflow is None or not self._started_run:
            return
        try:
            mlflow.end_run()
        except (RuntimeError, AttributeError):
            pass


tracker = Tracker()


__all__ = [
    "AGILAB_RUN_ID_ENV",
    "MLFLOW_RUN_ID_ENV",
    "MLFLOW_TRACKING_URI_ENV",
    "Tracker",
    "tracker",
]
