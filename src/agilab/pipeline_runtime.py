from __future__ import annotations

import importlib.util
import os
import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Callable, Dict, List, Optional, Pattern, Sequence, Type

from agi_env import AgiEnv
from agi_env import mlflow_store
from agi_gui.pagelib import run_lab

_import_guard_path = Path(__file__).resolve().parent / "import_guard.py"
_import_guard_spec = importlib.util.spec_from_file_location("agilab_import_guard_local", _import_guard_path)
if _import_guard_spec is None or _import_guard_spec.loader is None:
    raise ModuleNotFoundError(f"Unable to load import_guard.py from {_import_guard_path}")
_import_guard_module = importlib.util.module_from_spec(_import_guard_spec)
_import_guard_spec.loader.exec_module(_import_guard_module)
import_agilab_module = _import_guard_module.import_agilab_module

_pipeline_runtime_support_module = import_agilab_module(
    "agilab.pipeline_runtime_support",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "pipeline_runtime_support.py",
    fallback_name="agilab_pipeline_runtime_support_fallback",
)
_build_mlflow_process_env_impl = _pipeline_runtime_support_module.build_mlflow_process_env
_ensure_safe_service_template_impl = _pipeline_runtime_support_module.ensure_safe_service_template
_ensure_default_mlflow_experiment_impl = _pipeline_runtime_support_module.ensure_default_mlflow_experiment
_ensure_mlflow_backend_ready_impl = _pipeline_runtime_support_module.ensure_mlflow_backend_ready
_ensure_mlflow_sqlite_schema_current_impl = _pipeline_runtime_support_module.ensure_mlflow_sqlite_schema_current
_get_mlflow_module_impl = _pipeline_runtime_support_module.get_mlflow_module
_is_valid_runtime_root_impl = _pipeline_runtime_support_module.is_valid_runtime_root
_legacy_mlflow_filestore_present_impl = _pipeline_runtime_support_module.legacy_mlflow_filestore_present
_label_for_step_runtime_impl = _pipeline_runtime_support_module.label_for_step_runtime
_log_mlflow_artifacts_impl = _pipeline_runtime_support_module.log_mlflow_artifacts
_mlflow_tracking_uri_impl = _pipeline_runtime_support_module.mlflow_tracking_uri
_python_for_venv_impl = _pipeline_runtime_support_module.python_for_venv
_python_for_step_impl = _pipeline_runtime_support_module.python_for_step
_repair_mlflow_default_experiment_db_impl = _pipeline_runtime_support_module.repair_mlflow_default_experiment_db
_reset_mlflow_sqlite_backend_impl = _pipeline_runtime_support_module.reset_mlflow_sqlite_backend
_run_locked_step_impl = _pipeline_runtime_support_module.run_locked_step
_resolve_mlflow_artifact_dir_impl = _pipeline_runtime_support_module.resolve_mlflow_artifact_dir
_resolve_mlflow_backend_db_impl = _pipeline_runtime_support_module.resolve_mlflow_backend_db
_resolve_mlflow_tracking_dir_impl = _pipeline_runtime_support_module.resolve_mlflow_tracking_dir
_safe_service_start_template_impl = _pipeline_runtime_support_module.safe_service_start_template
_sqlite_identifier_impl = _pipeline_runtime_support_module.sqlite_identifier
_sqlite_uri_for_path_impl = _pipeline_runtime_support_module.sqlite_uri_for_path
_start_mlflow_run_impl = _pipeline_runtime_support_module.start_mlflow_run
_start_tracker_run_impl = _pipeline_runtime_support_module.start_tracker_run
_stream_run_command_impl = _pipeline_runtime_support_module.stream_run_command
_temporary_env_overrides_impl = _pipeline_runtime_support_module.temporary_env_overrides
_to_bool_flag_impl = _pipeline_runtime_support_module.to_bool_flag
_truncate_mlflow_text_impl = _pipeline_runtime_support_module.truncate_mlflow_text
_uses_controller_python_impl = _pipeline_runtime_support_module.uses_controller_python
_wrap_code_with_mlflow_resume_impl = _pipeline_runtime_support_module.wrap_code_with_mlflow_resume

MLFLOW_STEP_RUN_ID_ENV = "AGILAB_PIPELINE_MLFLOW_RUN_ID"
MLFLOW_TEXT_LIMIT = 500
DEFAULT_MLFLOW_EXPERIMENT_NAME = "Default"
DEFAULT_MLFLOW_DB_NAME = "mlflow.db"
DEFAULT_MLFLOW_ARTIFACT_DIR = "artifacts"
_MLFLOW_SQLITE_UPGRADE_CHECKED: set[str] = set()
_MLFLOW_SCHEMA_RESET_MARKERS = (
    "Can't locate revision identified by",
    "No such revision or branch",
    "duplicate column name:",
)


def to_bool_flag(value: Any, default: bool = False) -> bool:
    """Convert settings values to bool with tolerant parsing."""
    return _to_bool_flag_impl(value, default)


def safe_service_start_template(env: AgiEnv, marker: str) -> str:
    """Build an idempotent AGI.serve(start) snippet for PIPELINE import."""
    return _safe_service_start_template_impl(env, marker)


def get_mlflow_module():
    """Import MLflow lazily so callers can degrade gracefully when unavailable."""
    return _get_mlflow_module_impl()


def truncate_mlflow_text(value: Any, limit: int = MLFLOW_TEXT_LIMIT) -> str:
    """Convert arbitrary values into bounded MLflow-safe strings."""
    return _truncate_mlflow_text_impl(value, limit)


def resolve_mlflow_tracking_dir(env: AgiEnv) -> Path:
    """Resolve the shared MLflow root, falling back to HOME when unset."""
    return _resolve_mlflow_tracking_dir_impl(env, home_factory=Path.home, path_cls=Path)


def resolve_mlflow_backend_db(env: AgiEnv) -> Path:
    """Return the SQLite backend file used for local MLflow tracking."""
    return _resolve_mlflow_backend_db_impl(
        env,
        resolve_tracking_dir_fn=resolve_mlflow_tracking_dir,
        default_db_name=DEFAULT_MLFLOW_DB_NAME,
    )


def resolve_mlflow_artifact_dir(env: AgiEnv) -> Path:
    """Return the local artifact root shared by MLflow runs."""
    return _resolve_mlflow_artifact_dir_impl(
        env,
        resolve_tracking_dir_fn=resolve_mlflow_tracking_dir,
        default_artifact_dir=DEFAULT_MLFLOW_ARTIFACT_DIR,
    )


def sqlite_uri_for_path(db_path: Path) -> str:
    """Return a SQLAlchemy SQLite URI for an absolute database path."""
    return _sqlite_uri_for_path_impl(db_path, os_name=os.name, path_cls=Path)


def legacy_mlflow_filestore_present(tracking_dir: Path) -> bool:
    """Detect an old MLflow file store that should be migrated to SQLite."""
    return _legacy_mlflow_filestore_present_impl(
        tracking_dir,
        default_db_name=DEFAULT_MLFLOW_DB_NAME,
        default_artifact_dir=DEFAULT_MLFLOW_ARTIFACT_DIR,
    )


def _sqlite_identifier(name: str) -> str:
    return _sqlite_identifier_impl(name)


def repair_mlflow_default_experiment_db(db_path: Path, artifact_uri: str | None = None) -> bool:
    """Repair stale SQLite stores where 'Default' exists but experiment id 0 does not."""
    return _repair_mlflow_default_experiment_db_impl(
        db_path,
        default_experiment_name=DEFAULT_MLFLOW_EXPERIMENT_NAME,
        sqlite_identifier_fn=_sqlite_identifier,
        artifact_uri=artifact_uri,
        connect_fn=sqlite3.connect,
    )


def ensure_mlflow_sqlite_schema_current(db_path: Path) -> None:
    """Upgrade a local SQLite MLflow backend to the current schema once per process."""
    _ensure_mlflow_sqlite_schema_current_impl(
        db_path,
        checked_uris=_MLFLOW_SQLITE_UPGRADE_CHECKED,
        sqlite_uri_for_path_fn=sqlite_uri_for_path,
        schema_reset_markers=_MLFLOW_SCHEMA_RESET_MARKERS,
        reset_backend_fn=reset_mlflow_sqlite_backend,
        connect_fn=sqlite3.connect,
        run_cmd=subprocess.run,
        sys_executable=sys.executable,
    )


def reset_mlflow_sqlite_backend(db_path: Path) -> Path | None:
    """Move aside a stale local MLflow SQLite store so MLflow can recreate it cleanly."""
    return _reset_mlflow_sqlite_backend_impl(
        db_path,
        checked_uris=_MLFLOW_SQLITE_UPGRADE_CHECKED,
        sqlite_uri_for_path_fn=sqlite_uri_for_path,
        timestamp_fn=lambda: time.strftime("%Y%m%d_%H%M%S", time.gmtime()),
    )


def ensure_mlflow_backend_ready(env: AgiEnv) -> str:
    """Ensure the local MLflow backend is SQLite, migrating legacy file stores when needed."""
    return _ensure_mlflow_backend_ready_impl(
        env,
        resolve_tracking_dir_fn=resolve_mlflow_tracking_dir,
        legacy_mlflow_filestore_present_fn=legacy_mlflow_filestore_present,
        sqlite_uri_for_path_fn=sqlite_uri_for_path,
        ensure_mlflow_sqlite_schema_current_fn=ensure_mlflow_sqlite_schema_current,
        resolve_mlflow_artifact_dir_fn=lambda td: mlflow_store.resolve_mlflow_artifact_dir(
            td,
            default_artifact_dir=DEFAULT_MLFLOW_ARTIFACT_DIR,
        ),
        repair_mlflow_default_experiment_db_fn=repair_mlflow_default_experiment_db,
        run_cmd=subprocess.run,
        sys_executable=sys.executable,
        default_db_name=DEFAULT_MLFLOW_DB_NAME,
        default_artifact_dir=DEFAULT_MLFLOW_ARTIFACT_DIR,
    )


def mlflow_tracking_uri(env: AgiEnv) -> str:
    """Return the shared MLflow tracking URI used by AGILab pipeline tracking."""
    return _mlflow_tracking_uri_impl(env, ensure_mlflow_backend_ready_fn=ensure_mlflow_backend_ready)


def ensure_default_mlflow_experiment(env: AgiEnv, mlflow: Any | None = None) -> str | None:
    """Create the default experiment when the backend store is still empty."""
    return _ensure_default_mlflow_experiment_impl(
        env,
        mlflow=mlflow,
        resolve_tracking_dir_fn=resolve_mlflow_tracking_dir,
        get_mlflow_module_fn=get_mlflow_module,
        resolve_mlflow_artifact_dir_fn=resolve_mlflow_artifact_dir,
        resolve_mlflow_backend_db_fn=resolve_mlflow_backend_db,
        ensure_mlflow_backend_ready_fn=mlflow_tracking_uri,
        reset_mlflow_sqlite_backend_fn=reset_mlflow_sqlite_backend,
        default_experiment_name=DEFAULT_MLFLOW_EXPERIMENT_NAME,
        schema_reset_markers=_MLFLOW_SCHEMA_RESET_MARKERS,
    )


def build_mlflow_process_env(
    env: AgiEnv,
    *,
    run_id: str | None = None,
    base_env: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Inject the shared tracking URI into a child process environment."""
    return _build_mlflow_process_env_impl(
        env,
        tracking_uri=mlflow_tracking_uri(env),
        step_run_id_env=MLFLOW_STEP_RUN_ID_ENV,
        run_id=run_id,
        base_env=base_env,
    )


@contextmanager
def temporary_env_overrides(overrides: Optional[Dict[str, Any]]):
    """Temporarily apply environment overrides for in-process step execution."""
    with _temporary_env_overrides_impl(overrides):
        yield


@contextmanager
def start_mlflow_run(
    env: AgiEnv,
    *,
    run_name: str,
    tags: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    nested: bool = False,
):
    """Open an MLflow run against the sidebar tracking store when MLflow is available."""
    with _start_mlflow_run_impl(
        env,
        run_name=run_name,
        tags=tags,
        params=params,
        nested=nested,
        get_mlflow_module_fn=get_mlflow_module,
        ensure_default_mlflow_experiment_fn=ensure_default_mlflow_experiment,
        truncate_text_fn=truncate_mlflow_text,
    ) as tracking:
        yield tracking


@contextmanager
def start_tracker_run(
    env: AgiEnv,
    *,
    run_name: str,
    tags: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    nested: bool = False,
):
    """Open a backend-neutral AGILAB tracker run backed by MLflow today."""
    with _start_tracker_run_impl(
        env,
        run_name=run_name,
        tags=tags,
        params=params,
        nested=nested,
        start_mlflow_run_fn=start_mlflow_run,
        log_mlflow_artifacts_fn=log_mlflow_artifacts,
    ) as tracker:
        yield tracker


def log_mlflow_artifacts(
    tracking: Optional[Dict[str, Any]],
    *,
    text_artifacts: Optional[Dict[str, Any]] = None,
    file_artifacts: Optional[List[str | Path]] = None,
    tags: Optional[Dict[str, Any]] = None,
    metrics: Optional[Dict[str, float]] = None,
) -> None:
    """Log text/file artifacts plus final tags/metrics to an active MLflow run."""
    _log_mlflow_artifacts_impl(
        tracking,
        text_artifacts=text_artifacts,
        file_artifacts=file_artifacts,
        tags=tags,
        metrics=metrics,
        truncate_text_fn=truncate_mlflow_text,
    )


def wrap_code_with_mlflow_resume(code: str) -> str:
    """Resume a controller-created MLflow run inside subprocess-executed user code."""
    return _wrap_code_with_mlflow_resume_impl(code, step_run_id_env=MLFLOW_STEP_RUN_ID_ENV)


def ensure_safe_service_template(
    env: AgiEnv,
    steps_file: Path,
    *,
    template_filename: str,
    marker: str,
    debug_log: Callable[[str, Any], None],
) -> Optional[Path]:
    """Create or update an autogenerated safe service snippet file near lab steps."""
    return _ensure_safe_service_template_impl(
        env,
        steps_file,
        template_filename=template_filename,
        marker=marker,
        debug_log=debug_log,
    )


def python_for_venv(venv_root: str | Path | None) -> Path:
    """Return a python executable for a runtime selection."""
    return _python_for_venv_impl(venv_root, sys_executable=sys.executable)


def uses_controller_python(engine: str | None, code: str | None) -> bool:
    """Return True when a step should execute in the current AGILab/controller env."""
    return _uses_controller_python_impl(engine, code)


def python_for_step(venv_root: str | Path | None, *, engine: str | None, code: str | None) -> Path:
    """Choose the python executable for one step."""
    return _python_for_step_impl(venv_root, engine=engine, code=code, sys_executable=sys.executable)


def label_for_step_runtime(venv_root: str | Path | None, *, engine: str | None, code: str | None) -> str:
    """Return a readable runtime label for the step log."""
    return _label_for_step_runtime_impl(venv_root, engine=engine, code=code, sys_executable=sys.executable)


def is_valid_runtime_root(venv_root: str | Path | None) -> bool:
    """Return True when the runtime root points at an existing project/venv."""
    return _is_valid_runtime_root_impl(venv_root)


def stream_run_command(
    env: AgiEnv,
    index_page: str,
    cmd: str | Sequence[str],
    cwd: Path,
    *,
    push_run_log: Callable[[str, str, Optional[Any]], None],
    ansi_escape_re: Pattern[str],
    jump_exception_cls: Type[BaseException],
    placeholder: Optional[Any] = None,
    extra_env: Optional[Dict[str, str]] = None,
    timeout: Optional[int] = None,
) -> str:
    """Run a command and stream its output into the run log."""
    return _stream_run_command_impl(
        env,
        index_page,
        cmd,
        cwd,
        push_run_log=push_run_log,
        ansi_escape_re=ansi_escape_re,
        jump_exception_cls=jump_exception_cls,
        placeholder=placeholder,
        extra_env=extra_env,
        timeout=timeout,
        env_vars=os.environ.copy(),
        popen_factory=subprocess.Popen,
        path_separator=os.pathsep,
    )


def run_locked_step(
    env: AgiEnv,
    index_page_str: str,
    steps_file: Path,
    step: int,
    entry: Dict[str, Any],
    selected_map: Dict[int, str],
    engine_map: Dict[int, str],
    *,
    normalize_runtime_path: Callable[[Any], str],
    prepare_run_log_file: Callable[[str, AgiEnv, str], tuple[Optional[Path], Optional[str]]],
    push_run_log: Callable[[str, str, Optional[Any]], None],
    refresh_pipeline_run_lock: Callable[[Optional[Dict[str, Any]]], None],
    acquire_pipeline_run_lock: Callable[[AgiEnv, str, Optional[Any]], Optional[Dict[str, Any]]],
    release_pipeline_run_lock: Callable[[Optional[Dict[str, Any]], str, Optional[Any]], None],
    get_run_placeholder: Callable[[str], Optional[Any]],
    is_valid_runtime_root: Callable[[str | Path | None], bool],
    python_for_venv: Callable[[str | Path | None], Path],
    stream_run_command: Callable[..., str],
    step_summary: Callable[[Optional[Dict[str, Any]], int], str],
) -> None:
    """Execute one immutable ORCHESTRATE-derived step."""
    _run_locked_step_impl(
        env,
        index_page_str,
        steps_file,
        step,
        entry,
        selected_map,
        engine_map,
        normalize_runtime_path=normalize_runtime_path,
        prepare_run_log_file=prepare_run_log_file,
        push_run_log=push_run_log,
        refresh_pipeline_run_lock=refresh_pipeline_run_lock,
        acquire_pipeline_run_lock=acquire_pipeline_run_lock,
        release_pipeline_run_lock=release_pipeline_run_lock,
        get_run_placeholder=get_run_placeholder,
        is_valid_runtime_root=is_valid_runtime_root,
        python_for_venv=python_for_venv,
        stream_run_command=stream_run_command,
        step_summary=step_summary,
        label_for_step_runtime_fn=label_for_step_runtime,
        start_mlflow_run_fn=start_mlflow_run,
        build_mlflow_process_env_fn=build_mlflow_process_env,
        log_mlflow_artifacts_fn=log_mlflow_artifacts,
        run_lab_fn=run_lab,
        python_for_step_fn=python_for_step,
        wrap_code_with_mlflow_resume_fn=wrap_code_with_mlflow_resume,
    )
