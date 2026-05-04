from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Callable, Dict, List, Optional

from agi_env import AgiEnv
from agi_env import mlflow_store


def build_mlflow_process_env(
    env: AgiEnv,
    *,
    tracking_uri: str,
    step_run_id_env: str,
    run_id: str | None = None,
    base_env: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Inject the shared tracking URI into a child process environment."""
    process_env = dict(base_env or os.environ.copy())
    process_env["MLFLOW_TRACKING_URI"] = tracking_uri
    apps_path = getattr(env, "apps_path", None)
    if apps_path:
        process_env["APPS_PATH"] = str(apps_path)
    if run_id:
        process_env[step_run_id_env] = str(run_id)
        process_env["MLFLOW_RUN_ID"] = str(run_id)
    else:
        process_env.pop(step_run_id_env, None)
        process_env.pop("MLFLOW_RUN_ID", None)
    return process_env


def get_mlflow_module():
    """Import MLflow lazily so callers can degrade gracefully when unavailable."""
    return mlflow_store.get_mlflow_module()


def truncate_mlflow_text(value: Any, limit: int = 500) -> str:
    """Convert arbitrary values into bounded MLflow-safe strings."""
    text = "" if value is None else str(value)
    if limit <= 0 or len(text) <= limit:
        return text
    if limit == 1:
        return text[:1]
    return text[: limit - 1] + "…"


def resolve_mlflow_tracking_dir(
    env: AgiEnv,
    *,
    home_factory: Callable[[], Path] = Path.home,
    path_cls: type[Path] = Path,
) -> Path:
    """Resolve the shared MLflow root, falling back to HOME when unset."""
    tracking_dir = mlflow_store.resolve_mlflow_tracking_dir(
        env,
        home_factory=home_factory,
        path_cls=path_cls,
    )
    tracking_dir.mkdir(parents=True, exist_ok=True)
    return tracking_dir.resolve()


def resolve_mlflow_backend_db(
    env: AgiEnv,
    *,
    resolve_tracking_dir_fn: Callable[[AgiEnv], Path],
    default_db_name: str,
) -> Path:
    """Return the SQLite backend file used for local MLflow tracking."""
    return mlflow_store.resolve_mlflow_backend_db(
        resolve_tracking_dir_fn(env),
        default_db_name=default_db_name,
    )


def resolve_mlflow_artifact_dir(
    env: AgiEnv,
    *,
    resolve_tracking_dir_fn: Callable[[AgiEnv], Path],
    default_artifact_dir: str,
) -> Path:
    """Return the local artifact root shared by MLflow runs."""
    return mlflow_store.resolve_mlflow_artifact_dir(
        resolve_tracking_dir_fn(env),
        default_artifact_dir=default_artifact_dir,
    )


def sqlite_uri_for_path(db_path: Path, *, os_name: str = os.name, path_cls: type[Path] = Path) -> str:
    """Return a SQLAlchemy SQLite URI for an absolute database path."""
    return mlflow_store.sqlite_uri_for_path(db_path, os_name=os_name, path_cls=path_cls)


def legacy_mlflow_filestore_present(
    tracking_dir: Path,
    *,
    default_db_name: str,
    default_artifact_dir: str,
) -> bool:
    """Detect an old MLflow file store that should be migrated to SQLite."""
    return mlflow_store.legacy_mlflow_filestore_present(
        tracking_dir,
        default_db_name=default_db_name,
        default_artifact_dir=default_artifact_dir,
    )


def sqlite_identifier(name: str) -> str:
    return mlflow_store.sqlite_identifier(name)


def repair_mlflow_default_experiment_db(
    db_path: Path,
    *,
    default_experiment_name: str,
    sqlite_identifier_fn: Callable[[str], str] = sqlite_identifier,
    artifact_uri: str | None = None,
    connect_fn: Callable[..., Any] = sqlite3.connect,
) -> bool:
    """Repair stale SQLite stores where 'Default' exists but experiment id 0 does not."""
    return mlflow_store.repair_mlflow_default_experiment_db(
        db_path,
        default_experiment_name=default_experiment_name,
        sqlite_identifier_fn=sqlite_identifier_fn,
        artifact_uri=artifact_uri,
        connect_fn=connect_fn,
    )


def ensure_mlflow_sqlite_schema_current(
    db_path: Path,
    *,
    checked_uris: set[str],
    sqlite_uri_for_path_fn: Callable[[Path], str],
    schema_reset_markers: tuple[str, ...],
    reset_backend_fn: Callable[[Path], Path | None],
    connect_fn: Callable[..., Any] = sqlite3.connect,
    run_cmd: Callable[..., Any] = subprocess.run,
    sys_executable: str = sys.executable,
) -> None:
    """Upgrade a local SQLite MLflow backend to the current schema once per process."""
    mlflow_store.ensure_mlflow_sqlite_schema_current(
        db_path,
        checked_uris=checked_uris,
        sqlite_uri_for_path_fn=sqlite_uri_for_path_fn,
        schema_reset_markers=schema_reset_markers,
        reset_backend_fn=reset_backend_fn,
        connect_fn=connect_fn,
        run_cmd=run_cmd,
        sys_executable=sys_executable,
    )


def reset_mlflow_sqlite_backend(
    db_path: Path,
    *,
    checked_uris: set[str],
    sqlite_uri_for_path_fn: Callable[[Path], str],
    timestamp_fn: Callable[[], str] = lambda: time.strftime("%Y%m%d_%H%M%S", time.gmtime()),
) -> Path | None:
    """Move aside a stale local MLflow SQLite store so MLflow can recreate it cleanly."""
    return mlflow_store.reset_mlflow_sqlite_backend(
        db_path,
        checked_uris=checked_uris,
        sqlite_uri_for_path_fn=sqlite_uri_for_path_fn,
        timestamp_fn=timestamp_fn,
    )


def ensure_mlflow_backend_ready(
    env: AgiEnv,
    *,
    resolve_tracking_dir_fn: Callable[[AgiEnv], Path],
    legacy_mlflow_filestore_present_fn: Callable[[Path], bool],
    sqlite_uri_for_path_fn: Callable[[Path], str],
    ensure_mlflow_sqlite_schema_current_fn: Callable[[Path], None],
    resolve_mlflow_artifact_dir_fn: Callable[[Path], Path],
    repair_mlflow_default_experiment_db_fn: Callable[[Path, str | None], bool],
    run_cmd: Callable[..., Any] = subprocess.run,
    sys_executable: str = sys.executable,
    default_db_name: str = "mlflow.db",
    default_artifact_dir: str = "artifacts",
) -> str:
    """Ensure the local MLflow backend is SQLite, migrating legacy file stores when needed."""
    tracking_dir = resolve_tracking_dir_fn(env)
    return mlflow_store.ensure_mlflow_backend_ready(
        tracking_dir,
        resolve_mlflow_backend_db_fn=lambda td: mlflow_store.resolve_mlflow_backend_db(
            td,
            default_db_name=default_db_name,
        ),
        legacy_mlflow_filestore_present_fn=legacy_mlflow_filestore_present_fn,
        sqlite_uri_for_path_fn=sqlite_uri_for_path_fn,
        ensure_mlflow_sqlite_schema_current_fn=ensure_mlflow_sqlite_schema_current_fn,
        resolve_mlflow_artifact_dir_fn=lambda td: mlflow_store.resolve_mlflow_artifact_dir(
            td,
            default_artifact_dir=default_artifact_dir,
        ),
        repair_mlflow_default_experiment_db_fn=repair_mlflow_default_experiment_db_fn,
        run_cmd=run_cmd,
        sys_executable=sys_executable,
    )


def mlflow_tracking_uri(env: AgiEnv, *, ensure_mlflow_backend_ready_fn: Callable[[AgiEnv], str]) -> str:
    """Return the shared MLflow tracking URI used by AGILab pipeline tracking."""
    return ensure_mlflow_backend_ready_fn(env)


def ensure_default_mlflow_experiment(
    env: AgiEnv,
    *,
    mlflow: Any | None = None,
    resolve_tracking_dir_fn: Callable[[AgiEnv], Path],
    get_mlflow_module_fn: Callable[[], Any | None],
    resolve_mlflow_artifact_dir_fn: Callable[[AgiEnv], Path],
    resolve_mlflow_backend_db_fn: Callable[[AgiEnv], Path],
    ensure_mlflow_backend_ready_fn: Callable[[AgiEnv], str],
    reset_mlflow_sqlite_backend_fn: Callable[[Path], Path | None],
    default_experiment_name: str,
    schema_reset_markers: tuple[str, ...],
) -> str | None:
    """Create the default experiment when the backend store is still empty."""
    tracking_dir = resolve_tracking_dir_fn(env)
    return mlflow_store.ensure_default_mlflow_experiment(
        tracking_dir,
        get_mlflow_module_fn=lambda: mlflow or get_mlflow_module_fn(),
        resolve_mlflow_artifact_dir_fn=lambda _tracking_dir: resolve_mlflow_artifact_dir_fn(env),
        resolve_mlflow_backend_db_fn=lambda _tracking_dir: resolve_mlflow_backend_db_fn(env),
        ensure_mlflow_backend_ready_fn=lambda _tracking_dir: ensure_mlflow_backend_ready_fn(env),
        reset_mlflow_sqlite_backend_fn=reset_mlflow_sqlite_backend_fn,
        default_experiment_name=default_experiment_name,
        schema_reset_markers=schema_reset_markers,
    )


@contextmanager
def temporary_env_overrides(overrides: Optional[Dict[str, Any]]):
    """Temporarily apply environment overrides for in-process step execution."""
    if not overrides:
        yield
        return

    sentinel = object()
    previous = {key: os.environ.get(key, sentinel) for key in overrides}
    try:
        for key, value in overrides.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = str(value)
        yield
    finally:
        for key, value in previous.items():
            if value is sentinel:
                os.environ.pop(key, None)
            else:
                os.environ[key] = str(value)


@contextmanager
def start_mlflow_run(
    env: AgiEnv,
    *,
    run_name: str,
    tags: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    nested: bool = False,
    get_mlflow_module_fn: Callable[[], Any | None],
    ensure_default_mlflow_experiment_fn: Callable[[AgiEnv, Any], str | None],
    truncate_text_fn: Callable[[Any, int], str] = truncate_mlflow_text,
):
    """Open an MLflow run against the sidebar tracking store when MLflow is available."""
    mlflow = get_mlflow_module_fn()
    if mlflow is None:
        yield None
        return

    tracking_uri = ensure_default_mlflow_experiment_fn(env, mlflow)
    clean_tags = {
        str(key): truncate_text_fn(value, 5000)
        for key, value in (tags or {}).items()
        if value is not None
    }
    clean_params = {
        str(key): truncate_text_fn(value, 500)
        for key, value in (params or {}).items()
        if value is not None
    }
    run_kwargs: Dict[str, Any] = {"run_name": run_name}
    if nested:
        run_kwargs["nested"] = True

    with mlflow.start_run(**run_kwargs) as run:
        if clean_tags:
            mlflow.set_tags(clean_tags)
        if clean_params:
            mlflow.log_params(clean_params)
        yield {"mlflow": mlflow, "run": run, "tracking_uri": tracking_uri}


class AgilabTrackerRun:
    """Small tracking facade used by AGILAB code without exposing MLflow payloads."""

    def __init__(
        self,
        tracking: Optional[Dict[str, Any]],
        *,
        log_artifacts_fn: Callable[..., None],
    ) -> None:
        self._tracking = tracking
        self._log_artifacts_fn = log_artifacts_fn

    def __bool__(self) -> bool:
        return bool(self._tracking)

    @property
    def enabled(self) -> bool:
        return bool(self)

    @property
    def run_id(self) -> str | None:
        run = (self._tracking or {}).get("run")
        return getattr(getattr(run, "info", None), "run_id", None)

    @property
    def tracking_uri(self) -> str | None:
        tracking_uri = (self._tracking or {}).get("tracking_uri")
        return str(tracking_uri) if tracking_uri else None

    def log_artifacts(
        self,
        *,
        text_artifacts: Optional[Dict[str, Any]] = None,
        file_artifacts: Optional[List[str | Path]] = None,
        tags: Optional[Dict[str, Any]] = None,
        metrics: Optional[Dict[str, float]] = None,
    ) -> None:
        self._log_artifacts_fn(
            self._tracking,
            text_artifacts=text_artifacts,
            file_artifacts=file_artifacts,
            tags=tags,
            metrics=metrics,
        )

    def log_metric(self, key: str, value: float) -> None:
        self.log_artifacts(metrics={key: value})

    def log_metrics(self, metrics: Dict[str, float]) -> None:
        self.log_artifacts(metrics=metrics)

    def set_tag(self, key: str, value: Any) -> None:
        self.log_artifacts(tags={key: value})

    def set_tags(self, tags: Dict[str, Any]) -> None:
        self.log_artifacts(tags=tags)

    def log_text(self, artifact_name: str, text: Any) -> None:
        self.log_artifacts(text_artifacts={artifact_name: text})

    def log_artifact(self, artifact: str | Path) -> None:
        self.log_artifacts(file_artifacts=[artifact])


@contextmanager
def start_tracker_run(
    env: AgiEnv,
    *,
    run_name: str,
    tags: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    nested: bool = False,
    start_mlflow_run_fn: Callable[..., Any],
    log_mlflow_artifacts_fn: Callable[..., None],
):
    """Open an AGILAB tracker run backed by MLflow when MLflow is installed."""
    with start_mlflow_run_fn(
        env,
        run_name=run_name,
        tags=tags,
        params=params,
        nested=nested,
    ) as tracking:
        yield AgilabTrackerRun(
            tracking,
            log_artifacts_fn=log_mlflow_artifacts_fn,
        )


def log_mlflow_artifacts(
    tracking: Optional[Dict[str, Any]],
    *,
    text_artifacts: Optional[Dict[str, Any]] = None,
    file_artifacts: Optional[List[str | Path]] = None,
    tags: Optional[Dict[str, Any]] = None,
    metrics: Optional[Dict[str, float]] = None,
    truncate_text_fn: Callable[[Any, int], str] = truncate_mlflow_text,
) -> None:
    """Log text/file artifacts plus final tags/metrics to an active MLflow run."""
    if not tracking:
        return

    mlflow = tracking["mlflow"]
    if tags:
        mlflow.set_tags(
            {
                str(key): truncate_text_fn(value, 5000)
                for key, value in tags.items()
                if value is not None
            }
        )
    if metrics:
        for key, value in metrics.items():
            if value is None:
                continue
            try:
                mlflow.log_metric(str(key), float(value))
            except (TypeError, ValueError, RuntimeError, OverflowError):
                continue
    for artifact_name, text in (text_artifacts or {}).items():
        if text is None:
            continue
        payload = str(text)
        if hasattr(mlflow, "log_text"):
            mlflow.log_text(payload, artifact_name)
        else:
            with NamedTemporaryFile("w", encoding="utf-8", suffix=Path(artifact_name).suffix or ".txt", delete=False) as tmp:
                tmp.write(payload)
                tmp_path = Path(tmp.name)
            try:
                mlflow.log_artifact(str(tmp_path), artifact_path=str(Path(artifact_name).parent))
            finally:
                tmp_path.unlink(missing_ok=True)
    for artifact in file_artifacts or []:
        if not artifact:
            continue
        artifact_path = Path(artifact).expanduser()
        if artifact_path.exists():
            mlflow.log_artifact(str(artifact_path))


def wrap_code_with_mlflow_resume(code: str, *, step_run_id_env: str) -> str:
    """Resume a controller-created MLflow run inside subprocess-executed user code."""
    body = code if code.endswith("\n") else code + "\n"
    indented = "".join(f"    {line}\n" for line in body.splitlines()) if body.strip() else "    pass\n"
    return (
        "import os\n"
        "_agilab_mlflow = None\n"
        "_agilab_active_run = None\n"
        "try:\n"
        "    import mlflow as _agilab_mlflow\n"
        "    _agilab_tracking_uri = os.environ.get('MLFLOW_TRACKING_URI')\n"
        "    if _agilab_tracking_uri:\n"
        "        _agilab_mlflow.set_tracking_uri(_agilab_tracking_uri)\n"
        f"    _agilab_run_id = os.environ.get('{step_run_id_env}') or os.environ.get('MLFLOW_RUN_ID')\n"
        "    if _agilab_run_id:\n"
        "        _agilab_active_run = _agilab_mlflow.start_run(run_id=_agilab_run_id)\n"
        "except (ImportError, RuntimeError, AttributeError, ValueError, TypeError):\n"
        "    _agilab_mlflow = None\n"
        "    _agilab_active_run = None\n"
        "\n"
        "try:\n"
        f"{indented}"
        "finally:\n"
        "    if _agilab_active_run is not None and _agilab_mlflow is not None:\n"
        "        try:\n"
        "            _agilab_mlflow.end_run()\n"
        "        except (RuntimeError, AttributeError):\n"
        "            pass\n"
    )
