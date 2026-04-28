from __future__ import annotations

import importlib
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, MutableMapping

from agi_env import mlflow_store

AGILAB_RUN_ID_ENV = "AGILAB_PIPELINE_MLFLOW_RUN_ID"
MLFLOW_RUN_ID_ENV = "MLFLOW_RUN_ID"
MLFLOW_TRACKING_DIR_ENV = "MLFLOW_TRACKING_DIR"
MLFLOW_TRACKING_URI_ENV = "MLFLOW_TRACKING_URI"
MLFLOW_PARENT_RUN_ID_TAG = "mlflow.parentRunId"
DEFAULT_MLFLOW_DB_NAME = "mlflow.db"
DEFAULT_MLFLOW_ARTIFACT_DIR = "artifacts"


def prepare_worker_tracking_environment(
    env: Any,
    *,
    environ: MutableMapping[str, str] = os.environ,
    logger_obj: Any | None = None,
    path_cls: type[Path] = Path,
) -> str | None:
    """Ensure workers inherit a usable MLflow tracking URI when configured."""
    existing_uri = _clean(environ.get(MLFLOW_TRACKING_URI_ENV))
    if existing_uri:
        return existing_uri

    tracking_dir_value = _clean(environ.get(MLFLOW_TRACKING_DIR_ENV)) or _clean(
        getattr(env, "MLFLOW_TRACKING_DIR", None)
    )
    if not tracking_dir_value:
        return None

    try:
        tracking_dir = path_cls(tracking_dir_value).expanduser()
        if not tracking_dir.is_absolute():
            home_abs = getattr(env, "home_abs", None)
            base = path_cls(home_abs).expanduser() if home_abs else path_cls.home()
            tracking_dir = base / tracking_dir
        tracking_dir.mkdir(parents=True, exist_ok=True)
        mlflow_store.resolve_mlflow_artifact_dir(
            tracking_dir,
            default_artifact_dir=DEFAULT_MLFLOW_ARTIFACT_DIR,
        )
        db_path = mlflow_store.resolve_mlflow_backend_db(
            tracking_dir,
            default_db_name=DEFAULT_MLFLOW_DB_NAME,
        )
        tracking_uri = mlflow_store.sqlite_uri_for_path(db_path, os_name=os.name, path_cls=path_cls)
    except Exception as exc:  # pragma: no cover - defensive tracking boundary
        _log_debug(logger_obj, "worker tracking disabled: failed to resolve MLflow URI: %s", exc)
        return None

    environ[MLFLOW_TRACKING_DIR_ENV] = str(tracking_dir)
    environ[MLFLOW_TRACKING_URI_ENV] = tracking_uri
    return tracking_uri


@contextmanager
def worker_tracking_run(
    *,
    worker_id: int,
    worker_name: str | None,
    plan_batch_count: int,
    plan_chunk_len: Any = None,
    metadata_chunk_len: Any = None,
    logger_obj: Any | None = None,
    environ: MutableMapping[str, str] = os.environ,
    import_module_fn: Callable[[str], Any] = importlib.import_module,
    time_fn: Callable[[], float] = time.time,
) -> Iterator[Any | None]:
    """Create an MLflow worker run linked to the parent pipeline run when configured."""
    tracking_uri = _clean(environ.get(MLFLOW_TRACKING_URI_ENV))
    if not tracking_uri:
        yield None
        return

    mlflow = _get_mlflow_module(import_module_fn=import_module_fn, logger_obj=logger_obj)
    if mlflow is None:
        yield None
        return

    worker_label = str(worker_name or "worker")
    run_name = f"worker:{worker_label}:{worker_id}"
    tags = _worker_tracking_tags(
        worker_id=worker_id,
        worker_name=worker_label,
        plan_batch_count=plan_batch_count,
    )
    params = _worker_tracking_params(
        plan_chunk_len=plan_chunk_len,
        metadata_chunk_len=metadata_chunk_len,
    )

    old_run_id = environ.get(MLFLOW_RUN_ID_ENV)
    old_agilab_run_id = environ.get(AGILAB_RUN_ID_ENV)
    parent_run_id = _clean(old_agilab_run_id) or _clean(old_run_id)
    entered_contexts: list[Any] = []
    started_at = time_fn()
    worker_run = None
    exit_exc_info = (None, None, None)

    try:
        _set_tracking_uri(mlflow, tracking_uri)
        if parent_run_id:
            tags[MLFLOW_PARENT_RUN_ID_TAG] = parent_run_id
            tags["agilab.parent_run_id"] = parent_run_id

        worker_context = mlflow.start_run(run_name=run_name, tags=tags)
        worker_run = worker_context.__enter__()
        entered_contexts.append(worker_context)

        worker_run_id = _run_id(worker_run)
        if worker_run_id:
            environ[MLFLOW_RUN_ID_ENV] = worker_run_id
            environ[AGILAB_RUN_ID_ENV] = worker_run_id

        _log_tracking_metadata(mlflow, tags=tags, params=params, logger_obj=logger_obj)
        try:
            yield worker_run
        except Exception as exc:
            exit_exc_info = sys.exc_info()
            _log_tracking_metadata(
                mlflow,
                tags={
                    "agilab.status": "failed",
                    "agilab.error_type": type(exc).__name__,
                    "agilab.error": _truncate(str(exc), 5000),
                },
                metrics={"agilab.worker.runtime_seconds": max(time_fn() - started_at, 0.0)},
                logger_obj=logger_obj,
            )
            raise
        else:
            _log_tracking_metadata(
                mlflow,
                tags={"agilab.status": "completed"},
                metrics={"agilab.worker.runtime_seconds": max(time_fn() - started_at, 0.0)},
                logger_obj=logger_obj,
            )
    except Exception as exc:
        if worker_run is None:
            _log_debug(logger_obj, "worker tracking disabled: failed to start MLflow run: %s", exc)
            yield None
        else:
            raise
    finally:
        _restore_env_value(environ, MLFLOW_RUN_ID_ENV, old_run_id)
        _restore_env_value(environ, AGILAB_RUN_ID_ENV, old_agilab_run_id)
        for context in reversed(entered_contexts):
            try:
                context.__exit__(*exit_exc_info)
            except Exception as exc:  # pragma: no cover - defensive tracking boundary
                _log_debug(logger_obj, "worker tracking cleanup failed: %s", exc)


def _worker_tracking_tags(*, worker_id: int, worker_name: str, plan_batch_count: int) -> dict[str, str]:
    return {
        "agilab.component": "worker",
        "agilab.worker.id": str(worker_id),
        "agilab.worker.name": worker_name,
        "agilab.worker.plan_batches": str(plan_batch_count),
    }


def _worker_tracking_params(*, plan_chunk_len: Any = None, metadata_chunk_len: Any = None) -> dict[str, str]:
    params: dict[str, str] = {}
    if plan_chunk_len is not None:
        params["plan_chunk_len"] = str(plan_chunk_len)
    if metadata_chunk_len is not None:
        params["metadata_chunk_len"] = str(metadata_chunk_len)
    return params


def _get_mlflow_module(*, import_module_fn: Callable[[str], Any], logger_obj: Any | None) -> Any | None:
    try:
        return import_module_fn("mlflow")
    except ImportError:
        _log_debug(logger_obj, "worker tracking disabled: MLflow is not importable")
        return None


def _set_tracking_uri(mlflow: Any, tracking_uri: str) -> None:
    set_tracking_uri = getattr(mlflow, "set_tracking_uri", None)
    if set_tracking_uri is not None:
        set_tracking_uri(tracking_uri)


def _log_tracking_metadata(
    mlflow: Any,
    *,
    tags: Mapping[str, Any] | None = None,
    params: Mapping[str, Any] | None = None,
    metrics: Mapping[str, float] | None = None,
    logger_obj: Any | None = None,
) -> None:
    try:
        if tags:
            mlflow.set_tags(
                {str(key): _truncate(value, 5000) for key, value in tags.items() if value is not None}
            )
        if params:
            mlflow.log_params(
                {str(key): _truncate(value, 500) for key, value in params.items() if value is not None}
            )
        if metrics:
            for key, value in metrics.items():
                if value is not None:
                    mlflow.log_metric(str(key), float(value))
    except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
        _log_debug(logger_obj, "worker tracking metadata log failed: %s", exc)


def _run_id(run: Any) -> str | None:
    run_id = getattr(getattr(run, "info", None), "run_id", None)
    return str(run_id) if run_id else None


def _restore_env_value(environ: MutableMapping[str, str], key: str, value: str | None) -> None:
    if value is None:
        environ.pop(key, None)
    else:
        environ[key] = value


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _truncate(value: Any, limit: int) -> str:
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1] + "..."


def _log_debug(logger_obj: Any | None, message: str, *args: Any) -> None:
    debug = getattr(logger_obj, "debug", None)
    if debug is not None:
        debug(message, *args)


__all__ = [
    "AGILAB_RUN_ID_ENV",
    "MLFLOW_RUN_ID_ENV",
    "MLFLOW_PARENT_RUN_ID_TAG",
    "MLFLOW_TRACKING_DIR_ENV",
    "MLFLOW_TRACKING_URI_ENV",
    "prepare_worker_tracking_environment",
    "worker_tracking_run",
]
