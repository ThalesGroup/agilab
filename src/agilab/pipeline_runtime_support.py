from __future__ import annotations

import importlib.util
from pathlib import Path

_EXECUTION_EXPORTS = (
    "to_bool_flag",
    "safe_service_start_template",
    "ensure_safe_service_template",
    "python_for_venv",
    "uses_controller_python",
    "python_for_step",
    "label_for_step_runtime",
    "is_valid_runtime_root",
    "stream_run_command",
    "run_locked_step",
)

_MLFLOW_EXPORTS = (
    "build_mlflow_process_env",
    "get_mlflow_module",
    "truncate_mlflow_text",
    "resolve_mlflow_tracking_dir",
    "resolve_mlflow_backend_db",
    "resolve_mlflow_artifact_dir",
    "sqlite_uri_for_path",
    "legacy_mlflow_filestore_present",
    "sqlite_identifier",
    "repair_mlflow_default_experiment_db",
    "ensure_mlflow_sqlite_schema_current",
    "reset_mlflow_sqlite_backend",
    "ensure_mlflow_backend_ready",
    "mlflow_tracking_uri",
    "ensure_default_mlflow_experiment",
    "temporary_env_overrides",
    "start_mlflow_run",
    "log_mlflow_artifacts",
    "wrap_code_with_mlflow_resume",
)


def _load_fallback(module_filename: str, module_name: str):
    module_path = Path(__file__).resolve().parent / module_filename
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ModuleNotFoundError(f"Unable to load {module_filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


try:
    from agilab.pipeline_runtime_execution_support import (
        ensure_safe_service_template,
        is_valid_runtime_root,
        label_for_step_runtime,
        python_for_step,
        python_for_venv,
        run_locked_step,
        safe_service_start_template,
        stream_run_command,
        to_bool_flag,
        uses_controller_python,
    )
    from agilab.pipeline_runtime_mlflow_support import (
        build_mlflow_process_env,
        ensure_default_mlflow_experiment,
        ensure_mlflow_backend_ready,
        ensure_mlflow_sqlite_schema_current,
        get_mlflow_module,
        legacy_mlflow_filestore_present,
        log_mlflow_artifacts,
        mlflow_tracking_uri,
        repair_mlflow_default_experiment_db,
        reset_mlflow_sqlite_backend,
        resolve_mlflow_artifact_dir,
        resolve_mlflow_backend_db,
        resolve_mlflow_tracking_dir,
        sqlite_identifier,
        sqlite_uri_for_path,
        start_mlflow_run,
        temporary_env_overrides,
        truncate_mlflow_text,
        wrap_code_with_mlflow_resume,
    )
except ModuleNotFoundError:
    _execution_module = _load_fallback(
        "pipeline_runtime_execution_support.py",
        "agilab_pipeline_runtime_execution_support_fallback",
    )
    _mlflow_module = _load_fallback(
        "pipeline_runtime_mlflow_support.py",
        "agilab_pipeline_runtime_mlflow_support_fallback",
    )

    for _name in _EXECUTION_EXPORTS:
        globals()[_name] = getattr(_execution_module, _name)
    for _name in _MLFLOW_EXPORTS:
        globals()[_name] = getattr(_mlflow_module, _name)


__all__ = [
    *_EXECUTION_EXPORTS,
    *_MLFLOW_EXPORTS,
]
