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

_import_guard_path = Path(__file__).resolve().parent / "import_guard.py"
_import_guard_spec = importlib.util.spec_from_file_location("agilab_import_guard_local", _import_guard_path)
if _import_guard_spec is None or _import_guard_spec.loader is None:
    raise ModuleNotFoundError(f"Unable to load import_guard.py from {_import_guard_path}")
_import_guard_module = importlib.util.module_from_spec(_import_guard_spec)
_import_guard_spec.loader.exec_module(_import_guard_module)
import_agilab_symbols = _import_guard_module.import_agilab_symbols

import_agilab_symbols(
    globals(),
    "agilab.pipeline_runtime_execution_support",
    _EXECUTION_EXPORTS,
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "pipeline_runtime_execution_support.py",
    fallback_name="agilab_pipeline_runtime_execution_support_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.pipeline_runtime_mlflow_support",
    _MLFLOW_EXPORTS,
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "pipeline_runtime_mlflow_support.py",
    fallback_name="agilab_pipeline_runtime_mlflow_support_fallback",
)


__all__ = [
    *_EXECUTION_EXPORTS,
    *_MLFLOW_EXPORTS,
]
