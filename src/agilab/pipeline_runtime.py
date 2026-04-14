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
from typing import Any, Callable, Dict, List, Optional, Pattern, Type

from agi_env import AgiEnv
from agi_env import mlflow_store
from agi_env.pagelib import run_lab

try:
    from agilab.pipeline_runtime_support import (
        build_mlflow_process_env as _build_mlflow_process_env_impl,
        ensure_safe_service_template as _ensure_safe_service_template_impl,
        is_valid_runtime_root as _is_valid_runtime_root_impl,
        label_for_step_runtime as _label_for_step_runtime_impl,
        log_mlflow_artifacts as _log_mlflow_artifacts_impl,
        python_for_venv as _python_for_venv_impl,
        python_for_step as _python_for_step_impl,
        safe_service_start_template as _safe_service_start_template_impl,
        start_mlflow_run as _start_mlflow_run_impl,
        stream_run_command as _stream_run_command_impl,
        temporary_env_overrides as _temporary_env_overrides_impl,
        to_bool_flag as _to_bool_flag_impl,
        truncate_mlflow_text as _truncate_mlflow_text_impl,
        uses_controller_python as _uses_controller_python_impl,
        wrap_code_with_mlflow_resume as _wrap_code_with_mlflow_resume_impl,
    )
except ModuleNotFoundError:
    _pipeline_runtime_support_path = Path(__file__).resolve().parent / "pipeline_runtime_support.py"
    _pipeline_runtime_support_spec = importlib.util.spec_from_file_location(
        "agilab_pipeline_runtime_support_fallback",
        _pipeline_runtime_support_path,
    )
    if _pipeline_runtime_support_spec is None or _pipeline_runtime_support_spec.loader is None:
        raise
    _pipeline_runtime_support_module = importlib.util.module_from_spec(_pipeline_runtime_support_spec)
    _pipeline_runtime_support_spec.loader.exec_module(_pipeline_runtime_support_module)
    _build_mlflow_process_env_impl = _pipeline_runtime_support_module.build_mlflow_process_env
    _ensure_safe_service_template_impl = _pipeline_runtime_support_module.ensure_safe_service_template
    _is_valid_runtime_root_impl = _pipeline_runtime_support_module.is_valid_runtime_root
    _label_for_step_runtime_impl = _pipeline_runtime_support_module.label_for_step_runtime
    _log_mlflow_artifacts_impl = _pipeline_runtime_support_module.log_mlflow_artifacts
    _python_for_venv_impl = _pipeline_runtime_support_module.python_for_venv
    _python_for_step_impl = _pipeline_runtime_support_module.python_for_step
    _safe_service_start_template_impl = _pipeline_runtime_support_module.safe_service_start_template
    _start_mlflow_run_impl = _pipeline_runtime_support_module.start_mlflow_run
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
    return mlflow_store.get_mlflow_module()


def truncate_mlflow_text(value: Any, limit: int = MLFLOW_TEXT_LIMIT) -> str:
    """Convert arbitrary values into bounded MLflow-safe strings."""
    text = "" if value is None else str(value)
    if limit <= 0 or len(text) <= limit:
        return text
    if limit == 1:
        return text[:1]
    return text[: limit - 1] + "…"


def resolve_mlflow_tracking_dir(env: AgiEnv) -> Path:
    """Resolve the shared MLflow root, falling back to HOME when unset."""
    tracking_dir = mlflow_store.resolve_mlflow_tracking_dir(
        env,
        home_factory=Path.home,
        path_cls=Path,
    )
    tracking_dir.mkdir(parents=True, exist_ok=True)
    return tracking_dir.resolve()


def resolve_mlflow_backend_db(env: AgiEnv) -> Path:
    """Return the SQLite backend file used for local MLflow tracking."""
    return mlflow_store.resolve_mlflow_backend_db(
        resolve_mlflow_tracking_dir(env),
        default_db_name=DEFAULT_MLFLOW_DB_NAME,
    )


def resolve_mlflow_artifact_dir(env: AgiEnv) -> Path:
    """Return the local artifact root shared by MLflow runs."""
    return mlflow_store.resolve_mlflow_artifact_dir(
        resolve_mlflow_tracking_dir(env),
        default_artifact_dir=DEFAULT_MLFLOW_ARTIFACT_DIR,
    )


def sqlite_uri_for_path(db_path: Path) -> str:
    """Return a SQLAlchemy SQLite URI for an absolute database path."""
    return mlflow_store.sqlite_uri_for_path(db_path, os_name=os.name, path_cls=Path)


def legacy_mlflow_filestore_present(tracking_dir: Path) -> bool:
    """Detect an old MLflow file store that should be migrated to SQLite."""
    return mlflow_store.legacy_mlflow_filestore_present(
        tracking_dir,
        default_db_name=DEFAULT_MLFLOW_DB_NAME,
        default_artifact_dir=DEFAULT_MLFLOW_ARTIFACT_DIR,
    )


def _sqlite_identifier(name: str) -> str:
    return mlflow_store.sqlite_identifier(name)


def repair_mlflow_default_experiment_db(db_path: Path, artifact_uri: str | None = None) -> bool:
    """Repair stale SQLite stores where 'Default' exists but experiment id 0 does not."""
    return mlflow_store.repair_mlflow_default_experiment_db(
        db_path,
        default_experiment_name=DEFAULT_MLFLOW_EXPERIMENT_NAME,
        sqlite_identifier_fn=_sqlite_identifier,
        artifact_uri=artifact_uri,
        connect_fn=sqlite3.connect,
    )


def ensure_mlflow_sqlite_schema_current(db_path: Path) -> None:
    """Upgrade a local SQLite MLflow backend to the current schema once per process."""
    mlflow_store.ensure_mlflow_sqlite_schema_current(
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
    return mlflow_store.reset_mlflow_sqlite_backend(
        db_path,
        checked_uris=_MLFLOW_SQLITE_UPGRADE_CHECKED,
        sqlite_uri_for_path_fn=sqlite_uri_for_path,
        timestamp_fn=lambda: time.strftime("%Y%m%d_%H%M%S", time.gmtime()),
    )


def ensure_mlflow_backend_ready(env: AgiEnv) -> str:
    """Ensure the local MLflow backend is SQLite, migrating legacy file stores when needed."""
    tracking_dir = resolve_mlflow_tracking_dir(env)
    return mlflow_store.ensure_mlflow_backend_ready(
        tracking_dir,
        resolve_mlflow_backend_db_fn=lambda td: mlflow_store.resolve_mlflow_backend_db(
            td,
            default_db_name=DEFAULT_MLFLOW_DB_NAME,
        ),
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
    )


def mlflow_tracking_uri(env: AgiEnv) -> str:
    """Return the shared MLflow tracking URI used by AGILab pipeline tracking."""
    return ensure_mlflow_backend_ready(env)


def ensure_default_mlflow_experiment(env: AgiEnv, mlflow: Any | None = None) -> str | None:
    """Create the default experiment when the backend store is still empty."""
    tracking_dir = resolve_mlflow_tracking_dir(env)
    return mlflow_store.ensure_default_mlflow_experiment(
        tracking_dir,
        get_mlflow_module_fn=lambda: mlflow or get_mlflow_module(),
        resolve_mlflow_artifact_dir_fn=lambda _tracking_dir: resolve_mlflow_artifact_dir(env),
        resolve_mlflow_backend_db_fn=lambda _tracking_dir: resolve_mlflow_backend_db(env),
        ensure_mlflow_backend_ready_fn=lambda _tracking_dir: mlflow_tracking_uri(env),
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
    mlflow = get_mlflow_module()
    if mlflow is None:
        yield None
        return

    tracking_uri = ensure_default_mlflow_experiment(env, mlflow)
    clean_tags = {
        str(key): truncate_mlflow_text(value, 5000)
        for key, value in (tags or {}).items()
        if value is not None
    }
    clean_params = {
        str(key): truncate_mlflow_text(value, MLFLOW_TEXT_LIMIT)
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


def log_mlflow_artifacts(
    tracking: Optional[Dict[str, Any]],
    *,
    text_artifacts: Optional[Dict[str, Any]] = None,
    file_artifacts: Optional[List[str | Path]] = None,
    tags: Optional[Dict[str, Any]] = None,
    metrics: Optional[Dict[str, float]] = None,
) -> None:
    """Log text/file artifacts plus final tags/metrics to an active MLflow run."""
    if not tracking:
        return

    mlflow = tracking["mlflow"]
    if tags:
        mlflow.set_tags(
            {
                str(key): truncate_mlflow_text(value, 5000)
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
            except Exception:
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
    cmd: str,
    cwd: Path,
    *,
    push_run_log: Callable[[str, str, Optional[Any]], None],
    ansi_escape_re: Pattern[str],
    jump_exception_cls: Type[BaseException],
    placeholder: Optional[Any] = None,
    extra_env: Optional[Dict[str, str]] = None,
    timeout: Optional[int] = None,
) -> str:
    """Run a shell command and stream its output into the run log."""
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
    stored_placeholder = get_run_placeholder(index_page_str)
    import streamlit as st

    st.session_state[f"{index_page_str}__run_logs"] = []
    if stored_placeholder is not None:
        stored_placeholder.caption("Starting step execution…")
    snippet_file = st.session_state.get("snippet_file")
    if not snippet_file:
        st.error("Snippet file is not configured. Reload the page and try again.")
        return
    lock_handle = acquire_pipeline_run_lock(env, index_page_str, stored_placeholder)
    if lock_handle is None:
        return

    try:
        selected_map_entry = normalize_runtime_path(selected_map.get(step, ""))
        entry_runtime_raw = normalize_runtime_path(entry.get("E", ""))
        venv_root = selected_map_entry or (entry_runtime_raw if is_valid_runtime_root(entry_runtime_raw) else "")
        if not venv_root:
            fallback = normalize_runtime_path(st.session_state.get("lab_selected_venv", ""))
            if fallback and is_valid_runtime_root(fallback):
                venv_root = fallback
        if not venv_root:
            fallback = normalize_runtime_path(getattr(env, "active_app", ""))
            if is_valid_runtime_root(fallback):
                venv_root = fallback

        entry_engine = str(entry.get("R", "") or "")
        engine = entry_engine or ("agi.run" if venv_root else "runpy")
        if engine.startswith("agi.") and not venv_root:
            fallback = normalize_runtime_path(getattr(env, "active_app", "") or "")
            if is_valid_runtime_root(fallback):
                venv_root = fallback
        if venv_root:
            selected_map[step] = venv_root
            st.session_state["lab_selected_venv"] = venv_root
            if engine == "runpy":
                engine = "agi.run"

        code_to_run = str(entry.get("C", ""))
        engine_map[step] = engine
        st.session_state["lab_selected_engine"] = engine

        log_file_path, log_error = prepare_run_log_file(index_page_str, env, f"step_{step + 1}")
        if log_file_path:
            push_run_log(
                index_page_str,
                f"Run step {step + 1} started… logs will be saved to {log_file_path}",
                stored_placeholder,
            )
        else:
            push_run_log(
                index_page_str,
                f"Run step {step + 1} started… (unable to prepare log file: {log_error})",
                stored_placeholder,
            )

        try:
            refresh_pipeline_run_lock(lock_handle)
            target_base = Path(steps_file).parent.resolve()
            target_base.mkdir(parents=True, exist_ok=True)
            env_label = label_for_step_runtime(venv_root, engine=engine, code=code_to_run)
            summary = step_summary({"Q": entry.get("Q", ""), "C": code_to_run}, 60)
            step_tags = {
                "agilab.component": "pipeline-step",
                "agilab.app": str(getattr(env, "app", "") or ""),
                "agilab.lab": Path(steps_file).parent.name,
                "agilab.step_index": step + 1,
                "agilab.engine": engine,
                "agilab.runtime": venv_root or "",
                "agilab.summary": summary,
            }
            step_params = {
                "description": entry.get("D", ""),
                "question": entry.get("Q", ""),
                "model": entry.get("M", ""),
                "runtime": venv_root or "",
                "engine": engine,
            }
            with start_mlflow_run(
                env,
                run_name=f"{getattr(env, 'app', 'agilab')}:{Path(steps_file).parent.name}:step_{step + 1}",
                tags=step_tags,
                params=step_params,
            ) as step_tracking:
                step_env = build_mlflow_process_env(
                    env,
                    run_id=step_tracking["run"].info.run_id if step_tracking else None,
                )
                step_files: List[Any] = []
                if engine == "runpy":
                    run_output = run_lab(
                        [entry.get("D", ""), entry.get("Q", ""), code_to_run],
                        snippet_file,
                        env.copilot_file,
                        env_overrides=step_env,
                    )
                    step_files.append(Path(snippet_file))
                else:
                    script_path = (target_base / "AGI_run.py").resolve()
                    script_path.write_text(wrap_code_with_mlflow_resume(code_to_run))
                    step_files.append(script_path)
                    python_cmd = python_for_step(venv_root, engine=engine, code=code_to_run)
                    run_output = stream_run_command(
                        env,
                        index_page_str,
                        f"{python_cmd} {script_path}",
                        cwd=target_base,
                        placeholder=stored_placeholder,
                        extra_env=step_env,
                    )
                refresh_pipeline_run_lock(lock_handle)
                push_run_log(
                    index_page_str,
                    f"Step {step + 1}: engine={engine}, env={env_label}, summary=\"{summary}\"",
                    stored_placeholder,
                )
                preview = run_output.strip() if run_output else ""
                if preview:
                    push_run_log(
                        index_page_str,
                        f"Output (step {step + 1}):\n{preview}",
                        stored_placeholder,
                    )
                elif engine == "runpy":
                    push_run_log(
                        index_page_str,
                        f"Output (step {step + 1}): runpy executed (no captured stdout)",
                        stored_placeholder,
                    )
                export_target = st.session_state.get("df_file_out", "")
                if export_target:
                    step_files.append(export_target)
                if step_tracking:
                    log_mlflow_artifacts(
                        step_tracking,
                        text_artifacts={f"step_{step + 1}/stdout.txt": preview or ""},
                        file_artifacts=step_files,
                        tags={"agilab.status": "completed"},
                    )
        finally:
            st.session_state.pop(f"{index_page_str}__run_log_file", None)
    finally:
        release_pipeline_run_lock(lock_handle, index_page_str, stored_placeholder)
