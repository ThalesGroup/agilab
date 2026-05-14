import importlib.util
import hashlib
import json
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

import pandas as pd
import streamlit as st
import tomllib
from code_editor import code_editor

from agi_env import AgiEnv
from agi_gui.pagelib import (
    get_css_text,
    get_custom_buttons,
    get_info_bar,
    render_dataframe_preview,
    run_lab,
    save_csv,
)
from agi_gui.ux_widgets import action_button, compact_choice, confirm_button, empty_state, status_container, toast
from agi_env.snippet_contract import (
    clean_stale_snippet_files,
    stale_snippet_cleanup_message,
)

_import_guard_path = Path(__file__).resolve().parent / "import_guard.py"
_import_guard_spec = importlib.util.spec_from_file_location("agilab_import_guard_local", _import_guard_path)
if _import_guard_spec is None or _import_guard_spec.loader is None:
    raise ModuleNotFoundError(f"Unable to load import_guard.py from {_import_guard_path}")
_import_guard_module = importlib.util.module_from_spec(_import_guard_spec)
_import_guard_spec.loader.exec_module(_import_guard_module)
import_agilab_module = _import_guard_module.import_agilab_module

_code_editor_support_module = import_agilab_module(
    "agilab.code_editor_support",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "code_editor_support.py",
    fallback_name="agilab_code_editor_support_fallback",
)
normalize_custom_buttons = _code_editor_support_module.normalize_custom_buttons

_pipeline_stages_module = import_agilab_module(
    "agilab.pipeline_stages",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "pipeline_stages.py",
    fallback_name="agilab_pipeline_stages_fallback",
)
ORCHESTRATE_LOCKED_SOURCE_KEY = _pipeline_stages_module.ORCHESTRATE_LOCKED_SOURCE_KEY
ORCHESTRATE_LOCKED_STAGE_KEY = _pipeline_stages_module.ORCHESTRATE_LOCKED_STAGE_KEY
get_available_virtualenvs = _pipeline_stages_module.get_available_virtualenvs
_is_displayable_stage = _pipeline_stages_module.is_displayable_stage
_is_orchestrate_locked_stage = _pipeline_stages_module.is_orchestrate_locked_stage
_load_sequence_preferences = _pipeline_stages_module.load_sequence_preferences
_module_keys = _pipeline_stages_module.module_keys
_normalize_imported_orchestrate_snippet = _pipeline_stages_module.normalize_imported_orchestrate_snippet
normalize_runtime_path = _pipeline_stages_module.normalize_runtime_path
_orchestrate_snippet_source = _pipeline_stages_module.orchestrate_snippet_source
_persist_sequence_preferences = _pipeline_stages_module.persist_sequence_preferences
_snippet_source_guidance = _pipeline_stages_module.snippet_source_guidance
_stage_label_for_multiselect = _pipeline_stages_module.stage_label_for_multiselect
_stage_summary = _pipeline_stages_module.stage_summary

_generated_actions_module = import_agilab_module(
    "agilab.generated_actions",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "generated_actions.py",
    fallback_name="agilab_generated_actions_fallback",
)
GENERATION_MODE_PYTHON_SNIPPET = _generated_actions_module.GENERATION_MODE_PYTHON_SNIPPET
GENERATION_MODE_SAFE_ACTIONS = _generated_actions_module.GENERATION_MODE_SAFE_ACTIONS
STAGE_ACTION_CONTRACT_FIELD = _generated_actions_module.STAGE_ACTION_CONTRACT_FIELD
STAGE_GENERATION_MODE_FIELD = _generated_actions_module.STAGE_GENERATION_MODE_FIELD

GENERATION_MODE_LABELS = {
    GENERATION_MODE_SAFE_ACTIONS: "Safe actions",
    GENERATION_MODE_PYTHON_SNIPPET: "Python snippet (advanced)",
}
GENERATION_MODE_BY_LABEL = {label: mode for mode, label in GENERATION_MODE_LABELS.items()}

_pipeline_page_state_module = import_agilab_module(
    "agilab.pipeline_page_state",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "pipeline_page_state.py",
    fallback_name="agilab_pipeline_page_state_fallback",
)
PipelinePageStateDeps = _pipeline_page_state_module.PipelinePageStateDeps
PipelineAction = _pipeline_page_state_module.PipelineAction
build_pipeline_page_state = _pipeline_page_state_module.build_pipeline_page_state
clear_pipeline_run_logs = _pipeline_page_state_module.clear_pipeline_run_logs
delete_all_pipeline_stages_command = _pipeline_page_state_module.delete_all_pipeline_stages_command
delete_pipeline_stage_command = _pipeline_page_state_module.delete_pipeline_stage_command
finish_pipeline_run_command = _pipeline_page_state_module.finish_pipeline_run_command
start_pipeline_run_command = _pipeline_page_state_module.start_pipeline_run_command
undo_pipeline_delete_command = _pipeline_page_state_module.undo_pipeline_delete_command

_pinned_expander_module = import_agilab_module(
    "agilab.pinned_expander",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "pinned_expander.py",
    fallback_name="agilab_pinned_expander_fallback",
)
render_pinnable_code_editor = _pinned_expander_module.render_pinnable_code_editor

_workflow_ui_module = import_agilab_module(
    "agilab.workflow_ui",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "workflow_ui.py",
    fallback_name="agilab_workflow_ui_fallback",
)
record_action_history = _workflow_ui_module.record_action_history
is_dag_based_app = _workflow_ui_module.is_dag_based_app
render_action_history = _workflow_ui_module.render_action_history
render_artifact_drawer = _workflow_ui_module.render_artifact_drawer
render_log_actions = _workflow_ui_module.render_log_actions
render_latest_outputs = _workflow_ui_module.render_latest_outputs
render_latest_run_card = _workflow_ui_module.render_latest_run_card
render_workflow_timeline = _workflow_ui_module.render_workflow_timeline

_run_manifest_module = import_agilab_module(
    "agilab.run_manifest",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "run_manifest.py",
    fallback_name="agilab_run_manifest_fallback",
)
RUN_MANIFEST_FILENAME = _run_manifest_module.RUN_MANIFEST_FILENAME
load_run_manifest = _run_manifest_module.load_run_manifest
manifest_summary = _run_manifest_module.manifest_summary

_pipeline_runtime_module = import_agilab_module(
    "agilab.pipeline_runtime",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "pipeline_runtime.py",
    fallback_name="agilab_pipeline_runtime_fallback",
)
build_mlflow_process_env = _pipeline_runtime_module.build_mlflow_process_env
_is_valid_runtime_root = _pipeline_runtime_module.is_valid_runtime_root
_label_for_stage_runtime = _pipeline_runtime_module.label_for_stage_runtime
log_mlflow_artifacts = _pipeline_runtime_module.log_mlflow_artifacts
_python_for_stage = _pipeline_runtime_module.python_for_stage
start_mlflow_run = _pipeline_runtime_module.start_mlflow_run
wrap_code_with_mlflow_resume = _pipeline_runtime_module.wrap_code_with_mlflow_resume

_snippet_registry_module = import_agilab_module(
    "agilab.snippet_registry",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "snippet_registry.py",
    fallback_name="agilab_snippet_registry_fallback",
)
discover_pipeline_snippets = _snippet_registry_module.discover_pipeline_snippets

_src_root = Path(__file__).resolve().parents[1]
if str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))
_agilab_pkg = sys.modules.get("agilab")
if _agilab_pkg is not None:
    package_path = str(_src_root / "agilab")
    package_paths = list(getattr(_agilab_pkg, "__path__", []) or [])
    if package_path not in package_paths:
        _agilab_pkg.__path__ = [*package_paths, package_path]

_dag_run_engine_module = import_agilab_module(
    "agilab.dag_run_engine",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "dag_run_engine.py",
    fallback_name="agilab_dag_run_engine_fallback",
)
DagRunEngine = _dag_run_engine_module.DagRunEngine
GlobalDagBatchExecutionResult = _dag_run_engine_module.DagBatchExecutionResult
GlobalDagStageExecutionResult = _dag_run_engine_module.DagStageExecutionResult
GLOBAL_DAG_QUEUE_UNIT_ID = _dag_run_engine_module.GLOBAL_DAG_QUEUE_UNIT_ID
GLOBAL_DAG_RELAY_UNIT_ID = _dag_run_engine_module.GLOBAL_DAG_RELAY_UNIT_ID
GLOBAL_DAG_REAL_RUN_DIRNAME = _dag_run_engine_module.GLOBAL_DAG_REAL_RUN_DIRNAME
GLOBAL_DAG_REAL_EXECUTION_SCOPE = _dag_run_engine_module.GLOBAL_DAG_REAL_EXECUTION_SCOPE
GLOBAL_DAG_STAGE_BACKEND_LOCAL = _dag_run_engine_module.GLOBAL_DAG_STAGE_BACKEND_LOCAL
GLOBAL_DAG_STAGE_BACKEND_DISTRIBUTED = _dag_run_engine_module.GLOBAL_DAG_STAGE_BACKEND_DISTRIBUTED
GLOBAL_DAG_STAGE_BACKEND_LABELS = {
    GLOBAL_DAG_STAGE_BACKEND_LOCAL: "Local contracts",
    GLOBAL_DAG_STAGE_BACKEND_DISTRIBUTED: "Distributed backend",
}
available_artifact_ids = _dag_run_engine_module.available_artifact_ids
controlled_real_run_supported = _dag_run_engine_module.controlled_real_run_supported
dispatch_next_runnable = _dag_run_engine_module.dispatch_next_runnable
execution_history_rows = _dag_run_engine_module.execution_history_rows
load_runner_state = _dag_run_engine_module.load_runner_state
persist_runner_state = _dag_run_engine_module.persist_runner_state
repo_relative_text_for_dag = _dag_run_engine_module.repo_relative_text
run_global_dag_queue_baseline_app = _dag_run_engine_module.run_global_dag_queue_baseline_app
run_global_dag_relay_followup_app = _dag_run_engine_module.run_global_dag_relay_followup_app
run_next_controlled_global_dag_stage = _dag_run_engine_module.run_next_controlled_stage
run_ready_controlled_global_dag_stages = _dag_run_engine_module.run_ready_controlled_stages
runner_state_dag_matches = _dag_run_engine_module.runner_state_dag_matches
write_runner_state = _dag_run_engine_module.write_runner_state

_workflow_run_manifest_module = import_agilab_module(
    "agilab.workflow_run_manifest",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "workflow_run_manifest.py",
    fallback_name="agilab_workflow_run_manifest_fallback",
)
LATEST_WORKFLOW_EVIDENCE_FILENAME = _workflow_run_manifest_module.LATEST_WORKFLOW_EVIDENCE_FILENAME
WORKFLOW_EVIDENCE_DIRNAME = _workflow_run_manifest_module.WORKFLOW_EVIDENCE_DIRNAME
load_workflow_run_manifest = _workflow_run_manifest_module.load_workflow_run_manifest
workflow_manifest_summary = _workflow_run_manifest_module.workflow_manifest_summary
write_workflow_run_evidence = _workflow_run_manifest_module.write_workflow_run_evidence

_multi_app_dag_module = import_agilab_module(
    "agilab.multi_app_dag",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "multi_app_dag.py",
    fallback_name="agilab_multi_app_dag_fallback",
)
builtin_app_names = _multi_app_dag_module.builtin_app_names
MULTI_APP_DAG_SCHEMA = _multi_app_dag_module.SCHEMA

_multi_app_dag_draft_module = import_agilab_module(
    "agilab.multi_app_dag_draft",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "multi_app_dag_draft.py",
    fallback_name="agilab_multi_app_dag_draft_fallback",
)
build_dag_payload_from_editor = _multi_app_dag_draft_module.build_dag_payload_from_editor
clean_dag_cell = _multi_app_dag_draft_module.clean_dag_cell
CONTROLLED_CONTRACT_EXECUTION = _multi_app_dag_draft_module.CONTROLLED_CONTRACT_EXECUTION
dag_editor_rows = _multi_app_dag_draft_module.dag_editor_rows
format_validation_error_for_user = _multi_app_dag_draft_module.format_validation_error_for_user

_multi_app_dag_templates_module = import_agilab_module(
    "agilab.multi_app_dag_templates",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "multi_app_dag_templates.py",
    fallback_name="agilab_multi_app_dag_templates_fallback",
)
app_dag_template_paths = _multi_app_dag_templates_module.app_dag_template_paths

_dag_distributed_submitter_module = import_agilab_module(
    "agilab.dag_distributed_submitter",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "dag_distributed_submitter.py",
    fallback_name="agilab_dag_distributed_submitter_fallback",
)
build_global_dag_distributed_stage_submitter = (
    _dag_distributed_submitter_module.build_global_dag_distributed_stage_submitter
)
build_distributed_request_preview_rows = (
    _dag_distributed_submitter_module.build_distributed_request_preview_rows
)
dag_distributed_stage_config_from_settings = (
    _dag_distributed_submitter_module.dag_distributed_stage_config_from_settings
)
load_dag_distributed_settings = _dag_distributed_submitter_module.load_dag_distributed_settings

logger = logging.getLogger(__name__)
GLOBAL_RUNNER_STATE_FILENAME = "runner_state.json"
GENERATE_STAGE_SOURCE = "Generate stage"
GLOBAL_DAG_SAMPLE_RELATIVE_PATH = Path("docs/source/data/multi_app_dag_sample.json")
GLOBAL_DAG_FLIGHT_SAMPLE_RELATIVE_PATH = Path("docs/source/data/multi_app_dag_flight_sample.json")
GLOBAL_DAG_EMPTY_STATE = "No plan steps are available."
GLOBAL_DAG_DRAFT_DIRNAME = "global_dags"
GLOBAL_DAG_NODE_COLUMNS = ["id", "app", "purpose"]
GLOBAL_DAG_ARTIFACT_COLUMNS = ["node", "id", "kind", "path"]
GLOBAL_DAG_EDGE_COLUMNS = ["from", "to", "artifact", "handoff"]
GLOBAL_DAG_SOURCE_PROJECT_STAGES = "Project stages"
GLOBAL_DAG_SOURCE_PROJECT_STAGES_LEGACY = "Project stages"
GLOBAL_DAG_SOURCE_APP_TEMPLATES = "App templates"
GLOBAL_DAG_SOURCE_SAMPLES = "Sample library"
GLOBAL_DAG_SOURCE_WORKSPACE = "Workspace drafts"
GLOBAL_DAG_SOURCE_CUSTOM = "Custom path"
PIPELINE_SCOPE_PROJECT = "Project workflow"
PIPELINE_SCOPE_MULTI_APP_DAG = "Multi-app DAG"
PIPELINE_SCOPE_OPTIONS = [PIPELINE_SCOPE_PROJECT, PIPELINE_SCOPE_MULTI_APP_DAG]
GLOBAL_DAG_SOURCE_OPTIONS = [
    GLOBAL_DAG_SOURCE_PROJECT_STAGES,
    GLOBAL_DAG_SOURCE_APP_TEMPLATES,
    GLOBAL_DAG_SOURCE_SAMPLES,
    GLOBAL_DAG_SOURCE_WORKSPACE,
    GLOBAL_DAG_SOURCE_CUSTOM,
]
PIPELINE_STAGE_STARTED_RE = re.compile(r"\b(?:Running|Run)\s+(?:stage|stage)\s+(\d+)\b", re.IGNORECASE)
PIPELINE_STAGE_COMPLETED_RE = re.compile(r"\b(?:Stage|Stage)\s+(\d+):\s+engine=", re.IGNORECASE)


def _global_dag_pending_source_key(index_page_str: str) -> str:
    return f"{index_page_str}_global_runner_pending_source"


def _global_dag_notice_key(index_page_str: str) -> str:
    return f"{index_page_str}_global_runner_notice"


def _normalize_editor_text(raw: Optional[str]) -> str:
    if raw is None:
        return ""
    text = str(raw)
    return text if text.strip() else ""


def _resolve_stage_engine(entry_engine: str, ui_engine: str, venv_root: str) -> str:
    if ui_engine and ui_engine != entry_engine:
        if entry_engine.startswith("agi.") and ui_engine == "runpy":
            return entry_engine
        return ui_engine
    if entry_engine:
        return entry_engine
    return "agi.run" if venv_root else "runpy"


def _valid_runtime_path(raw: Any) -> str:
    normalized = normalize_runtime_path(raw)
    return normalized if normalized and _is_valid_runtime_root(normalized) else ""


def _valid_runtime_choices(raw_paths: List[Any]) -> List[str]:
    choices: List[str] = []
    seen: set[str] = set()
    for raw_path in raw_paths:
        runtime = _valid_runtime_path(raw_path)
        if runtime and runtime not in seen:
            seen.add(runtime)
            choices.append(runtime)
    return choices


def _repo_root_for_global_dag() -> Path:
    candidates = [
        Path.cwd(),
        Path(__file__).resolve().parents[2],
    ]
    for candidate in candidates:
        if (candidate / "docs" / "source" / "data").is_dir():
            return candidate.resolve()
    return Path(__file__).resolve().parents[2]


def _global_runner_dag_path(env: AgiEnv, repo_root: Path) -> Path | None:
    app_name = _active_app_name(env)
    app_templates = _global_dag_app_template_options(repo_root, app_name)
    if app_templates:
        template_path = _resolve_global_dag_input(app_templates[0], repo_root)
        if template_path is not None and template_path.is_file():
            return template_path
    preferred = (
        GLOBAL_DAG_FLIGHT_SAMPLE_RELATIVE_PATH
        if app_name in {"flight", "flight_telemetry_project"}
        else GLOBAL_DAG_SAMPLE_RELATIVE_PATH
    )
    preferred_path = repo_root / preferred
    if preferred_path.is_file():
        return preferred_path
    fallback_path = repo_root / GLOBAL_DAG_SAMPLE_RELATIVE_PATH
    return fallback_path if fallback_path.is_file() else None


def _global_dag_draft_dir(lab_dir: Path) -> Path:
    return lab_dir / ".agilab" / GLOBAL_DAG_DRAFT_DIRNAME


def _repo_relative_text(path: Path, repo_root: Path) -> str:
    return repo_relative_text_for_dag(path, repo_root)


def _resolve_global_dag_input(raw_value: Any, repo_root: Path) -> Path | None:
    raw_text = str(raw_value or "").strip()
    if not raw_text:
        return None
    candidate = Path(raw_text).expanduser()
    return candidate if candidate.is_absolute() else repo_root / candidate


def _global_dag_label(path_text: str, repo_root: Path) -> str:
    path = _resolve_global_dag_input(path_text, repo_root)
    if path is None:
        return "No plan selected"
    fallback = _repo_relative_text(path, repo_root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback
    if not isinstance(payload, dict):
        return fallback
    label = str(payload.get("label", "") or payload.get("dag_id", "")).strip()
    return f"{label} - {fallback}" if label else fallback


def _global_dag_display_name(path_text: str, repo_root: Path) -> str:
    path = _resolve_global_dag_input(path_text, repo_root)
    if path is None:
        return "not selected"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return path.stem or "custom plan"
    if not isinstance(payload, dict):
        return path.stem or "custom plan"
    for field_name in ("label", "dag_id"):
        value = str(payload.get(field_name, "")).strip()
        if value:
            return value
    return path.stem or "custom plan"


def _global_dag_sample_options(repo_root: Path) -> list[str]:
    docs_data_dir = repo_root / "docs" / "source" / "data"
    paths = sorted(docs_data_dir.glob("multi_app_dag*.json")) if docs_data_dir.is_dir() else []
    return [_repo_relative_text(path, repo_root) for path in paths]


def _active_app_name(env: AgiEnv) -> str:
    return Path(str(getattr(env, "app", "") or getattr(env, "target", ""))).name


def _global_dag_app_template_options(repo_root: Path, app_name: str) -> list[str]:
    return app_dag_template_paths(repo_root, app_name=app_name, include_all_when_empty=False)


def _global_dag_workspace_options(repo_root: Path, lab_dir: Path) -> list[str]:
    draft_dir = _global_dag_draft_dir(lab_dir)
    paths = sorted(draft_dir.glob("*.json")) if draft_dir.is_dir() else []
    return [_repo_relative_text(path, repo_root) for path in paths]


def _queue_global_dag_source_selection(
    index_page_str: str,
    *,
    source: str,
    dag_path: Path,
    repo_root: Path,
    notice: str,
) -> None:
    st.session_state[_global_dag_pending_source_key(index_page_str)] = {
        "source": source,
        "dag_path": _repo_relative_text(dag_path, repo_root),
    }
    st.session_state[_global_dag_notice_key(index_page_str)] = notice


def _apply_global_dag_pending_source_selection(
    index_page_str: str,
    *,
    source_key: str,
    app_template_key: str,
    library_key: str,
    workspace_key: str,
    dag_input_key: str,
    app_template_options: list[str],
    sample_options: list[str],
    workspace_options: list[str],
    source_options: list[str] | None = None,
) -> None:
    pending = st.session_state.pop(_global_dag_pending_source_key(index_page_str), None)
    if not isinstance(pending, dict):
        return
    source = str(pending.get("source", "")).strip()
    if source == GLOBAL_DAG_SOURCE_PROJECT_STAGES_LEGACY:
        source = GLOBAL_DAG_SOURCE_PROJECT_STAGES
    dag_text = str(pending.get("dag_path", "")).strip()
    valid_sources = source_options or GLOBAL_DAG_SOURCE_OPTIONS
    if source not in valid_sources or not dag_text:
        return

    st.session_state[source_key] = source
    if source == GLOBAL_DAG_SOURCE_APP_TEMPLATES:
        st.session_state[app_template_key] = dag_text if dag_text in app_template_options else ""
    elif source == GLOBAL_DAG_SOURCE_SAMPLES:
        st.session_state[library_key] = dag_text if dag_text in sample_options else ""
    elif source == GLOBAL_DAG_SOURCE_WORKSPACE:
        st.session_state[workspace_key] = dag_text if dag_text in workspace_options else ""
    else:
        st.session_state[dag_input_key] = dag_text


def _pipeline_scope_from_source(source_value: Any, has_project_stages: bool) -> str:
    if str(source_value or "") in {GLOBAL_DAG_SOURCE_PROJECT_STAGES, GLOBAL_DAG_SOURCE_PROJECT_STAGES_LEGACY}:
        return PIPELINE_SCOPE_PROJECT
    if source_value:
        return PIPELINE_SCOPE_MULTI_APP_DAG
    return PIPELINE_SCOPE_PROJECT if has_project_stages else PIPELINE_SCOPE_MULTI_APP_DAG


def _default_multi_app_dag_source(
    *,
    default_dag_text: str,
    app_template_options: list[str],
    sample_options: list[str],
    workspace_options: list[str],
) -> str:
    if default_dag_text in app_template_options or app_template_options:
        return GLOBAL_DAG_SOURCE_APP_TEMPLATES
    if default_dag_text in sample_options or sample_options:
        return GLOBAL_DAG_SOURCE_SAMPLES
    if workspace_options:
        return GLOBAL_DAG_SOURCE_WORKSPACE
    return GLOBAL_DAG_SOURCE_CUSTOM


def _global_dag_library_options(repo_root: Path, lab_dir: Path) -> list[str]:
    options: list[str] = []
    seen: set[str] = set()
    for option in [
        *app_dag_template_paths(repo_root),
        *_global_dag_sample_options(repo_root),
        *_global_dag_workspace_options(repo_root, lab_dir),
    ]:
        if option in seen:
            continue
        seen.add(option)
        options.append(option)
    return options


def _global_dag_editor_text(path: Path | None) -> str:
    if path is None or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _global_dag_payload_from_text(editor_text: str) -> tuple[dict[str, Any] | None, str]:
    try:
        payload = json.loads(editor_text)
    except json.JSONDecodeError as exc:
        return None, f"Invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
    if not isinstance(payload, dict):
        return None, "Plan JSON must be a JSON object."
    return payload, ""


def _load_global_dag_payload(path: Path | None) -> tuple[dict[str, Any], str]:
    editor_text = _global_dag_editor_text(path)
    if not editor_text.strip():
        return _empty_global_dag_payload(), "No plan is selected."
    payload, error = _global_dag_payload_from_text(editor_text)
    if error or payload is None:
        return _empty_global_dag_payload(), error
    return payload, ""


def _global_dag_validation_error(editor_text: str, repo_root: Path) -> str:
    payload, error = _global_dag_payload_from_text(editor_text)
    if error or payload is None:
        return error

    return format_validation_error_for_user(payload, repo_root=repo_root)


def _global_dag_has_controlled_contract_marker(payload: dict[str, Any]) -> bool:
    execution = payload.get("execution")
    if not isinstance(execution, dict):
        return False
    return all(
        str(execution.get(key, "")).strip() == str(value)
        for key, value in CONTROLLED_CONTRACT_EXECUTION.items()
    )


def _save_global_dag_app_template(
    repo_root: Path,
    *,
    active_app_name: str,
    editor_text: str,
) -> tuple[Path | None, str]:
    payload, parse_error = _global_dag_payload_from_text(editor_text)
    if parse_error or payload is None:
        return None, parse_error
    validation_error = format_validation_error_for_user(payload, repo_root=repo_root)
    if validation_error:
        return None, validation_error
    if not _global_dag_has_controlled_contract_marker(payload):
        return None, "Enable executable app template before saving an app-owned controlled workflow."

    active_app = Path(active_app_name).name.strip()
    available_apps = builtin_app_names(repo_root)
    if active_app not in available_apps:
        return None, f"Active project `{active_app or 'unknown'}` is not a checked-in built-in app."
    node_apps = {
        _clean_global_dag_cell(node.get("app"))
        for node in payload.get("nodes", [])
        if isinstance(node, dict)
    }
    if active_app not in node_apps:
        return None, f"App workflow templates for `{active_app}` must include a `{active_app}` step."

    template_dir = (
        repo_root / "src" / "agilab" / "apps" / "builtin" / active_app / "dag_templates"
    )
    template_dir.mkdir(parents=True, exist_ok=True)
    template_path = template_dir / f"{_portable_global_dag_stem(payload, 'global-dag-template')}.json"
    template_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return template_path, ""


def _portable_global_dag_stem(payload: dict[str, Any], fallback: str) -> str:
    raw_name = str(payload.get("dag_id", "") or payload.get("label", "") or fallback).strip()
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw_name).strip(".-")
    return stem or "global-dag-draft"


def _save_global_dag_draft(lab_dir: Path, editor_text: str, repo_root: Path) -> tuple[Path | None, str]:
    validation_error = _global_dag_validation_error(editor_text, repo_root)
    if validation_error:
        return None, validation_error
    payload = json.loads(editor_text)
    assert isinstance(payload, dict)
    draft_dir = _global_dag_draft_dir(lab_dir)
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_path = draft_dir / f"{_portable_global_dag_stem(payload, 'global-dag-draft')}.json"
    draft_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return draft_path, ""


def _empty_global_dag_payload() -> dict[str, Any]:
    return {
        "schema": MULTI_APP_DAG_SCHEMA,
        "dag_id": "new-global-dag",
        "label": "New multi-app DAG",
        "description": "",
        "execution": {
            "mode": "sequential_dependency_order",
            "runner_status": "contract_only",
        },
        "nodes": [],
        "edges": [],
    }


def _global_dag_source_token(path_text: str) -> str:
    raw = path_text or "empty"
    compact = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw).strip(".-")[:28]
    checksum = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    return f"{compact or 'dag'}-{checksum}"


def _clean_global_dag_cell(value: Any) -> str:
    return clean_dag_cell(value)


def _editor_rows(value: Any, columns: list[str]) -> list[dict[str, str]]:
    return dag_editor_rows(value, columns)


def _rows_dataframe(rows: list[dict[str, str]], columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=columns)


def _global_dag_editor_tables(payload: dict[str, Any]) -> dict[str, pd.DataFrame]:
    nodes = payload.get("nodes", [])
    if not isinstance(nodes, list):
        nodes = []

    node_rows: list[dict[str, str]] = []
    produces_rows: list[dict[str, str]] = []
    consumes_rows: list[dict[str, str]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = _clean_global_dag_cell(node.get("id"))
        node_rows.append(
            {
                "id": node_id,
                "app": _clean_global_dag_cell(node.get("app")),
                "purpose": _clean_global_dag_cell(node.get("purpose")),
            }
        )
        for artifact in node.get("produces", []) if isinstance(node.get("produces"), list) else []:
            if isinstance(artifact, dict):
                produces_rows.append(
                    {
                        "node": node_id,
                        "id": _clean_global_dag_cell(artifact.get("id")),
                        "kind": _clean_global_dag_cell(artifact.get("kind")),
                        "path": _clean_global_dag_cell(artifact.get("path")),
                    }
                )
        for artifact in node.get("consumes", []) if isinstance(node.get("consumes"), list) else []:
            if isinstance(artifact, dict):
                consumes_rows.append(
                    {
                        "node": node_id,
                        "id": _clean_global_dag_cell(artifact.get("id")),
                        "kind": _clean_global_dag_cell(artifact.get("kind")),
                        "path": _clean_global_dag_cell(artifact.get("path")),
                    }
                )

    edge_rows = [
        {
            "from": _clean_global_dag_cell(edge.get("from")),
            "to": _clean_global_dag_cell(edge.get("to")),
            "artifact": _clean_global_dag_cell(edge.get("artifact")),
            "handoff": _clean_global_dag_cell(edge.get("handoff")),
        }
        for edge in payload.get("edges", [])
        if isinstance(edge, dict)
    ]
    return {
        "nodes": _rows_dataframe(node_rows, GLOBAL_DAG_NODE_COLUMNS),
        "produces": _rows_dataframe(produces_rows, GLOBAL_DAG_ARTIFACT_COLUMNS),
        "consumes": _rows_dataframe(consumes_rows, GLOBAL_DAG_ARTIFACT_COLUMNS),
        "edges": _rows_dataframe(edge_rows, GLOBAL_DAG_EDGE_COLUMNS),
    }


def _default_stage_id_for_app(app_name: str) -> str:
    stage_id = app_name.removesuffix("_project")
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", stage_id).strip("_.-") or app_name


def _stage_label(stage_id: str, stages: dict[str, dict[str, str]]) -> str:
    stage = stages.get(stage_id, {})
    app = stage.get("app", "")
    purpose = stage.get("purpose", "")
    details = " - ".join(item for item in (app, purpose) if item)
    return f"{stage_id} ({details})" if details else stage_id


def _global_dag_stage_options(repo_root: Path, payload: dict[str, Any]) -> dict[str, dict[str, str]]:
    stages: dict[str, dict[str, str]] = {}
    nodes = payload.get("nodes", [])
    for node in nodes if isinstance(nodes, list) else []:
        if not isinstance(node, dict):
            continue
        stage_id = _clean_global_dag_cell(node.get("id"))
        if not stage_id:
            continue
        stages[stage_id] = {
            "id": stage_id,
            "app": _clean_global_dag_cell(node.get("app")),
            "purpose": _clean_global_dag_cell(node.get("purpose")),
        }

    for app_name in sorted(builtin_app_names(repo_root)):
        stage_id = _default_stage_id_for_app(app_name)
        if stage_id in stages:
            stage_id = app_name
        if stage_id in stages:
            continue
        stages[stage_id] = {
            "id": stage_id,
            "app": app_name,
            "purpose": f"Run {app_name.removesuffix('_project').replace('_', ' ')}.",
        }
    return stages


def _selected_stage_rows(stage_ids: list[str], stages: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "id": stage["id"],
            "app": stage["app"],
            "purpose": stage.get("purpose", ""),
        }
        for stage_id in stage_ids
        if (stage := stages.get(stage_id))
    ]


def _global_dag_existing_handoffs(payload: dict[str, Any]) -> dict[tuple[str, str, str], str]:
    edges = payload.get("edges", [])
    handoffs: dict[tuple[str, str, str], str] = {}
    for edge in edges if isinstance(edges, list) else []:
        if not isinstance(edge, dict):
            continue
        source = _clean_global_dag_cell(edge.get("from"))
        target = _clean_global_dag_cell(edge.get("to"))
        artifact = _clean_global_dag_cell(edge.get("artifact"))
        if source and target and artifact:
            handoffs[(source, target, artifact)] = _clean_global_dag_cell(edge.get("handoff"))
    return handoffs


def _global_dag_artifact_options(
    stage_ids: list[str],
    tables: dict[str, pd.DataFrame],
) -> dict[str, dict[str, str]]:
    selected_stage_set = set(stage_ids)
    options: dict[str, dict[str, str]] = {}
    for row in _editor_rows(tables["produces"], GLOBAL_DAG_ARTIFACT_COLUMNS):
        node_id = row["node"]
        artifact_id = row["id"]
        if node_id not in selected_stage_set or not artifact_id:
            continue
        options[f"{node_id}::{artifact_id}"] = row

    for node_id in stage_ids:
        if any(option["node"] == node_id for option in options.values()):
            continue
        artifact_id = f"{node_id}_summary"
        options[f"{node_id}::{artifact_id}"] = {
            "node": node_id,
            "id": artifact_id,
            "kind": "summary_metrics",
            "path": f"{node_id}/summary.json",
        }
    return options


def _artifact_option_label(option_key: str, artifact_options: dict[str, dict[str, str]]) -> str:
    artifact = artifact_options.get(option_key, {})
    node_id = artifact.get("node", option_key)
    artifact_id = artifact.get("id", "")
    kind = artifact.get("kind", "")
    path = artifact.get("path", "")
    suffix = ", ".join(item for item in (kind, path) if item)
    return f"{node_id} creates {artifact_id} ({suffix})" if suffix else f"{node_id} creates {artifact_id}"


def _handoff_key(source: str, target: str, artifact_id: str) -> str:
    return f"{source}::{target}::{artifact_id}"


def _parse_handoff_key(option_key: str) -> tuple[str, str, str]:
    parts = option_key.split("::", 2)
    if len(parts) != 3:
        return "", "", ""
    return parts[0], parts[1], parts[2]


def _global_dag_handoff_options(
    stage_ids: list[str],
    artifact_options: dict[str, dict[str, str]],
    payload: dict[str, Any],
) -> dict[str, dict[str, str]]:
    existing_handoffs = _global_dag_existing_handoffs(payload)
    options: dict[str, dict[str, str]] = {}
    for artifact in artifact_options.values():
        source = artifact["node"]
        artifact_id = artifact["id"]
        for target in stage_ids:
            if target == source:
                continue
            handoff = existing_handoffs.get(
                (source, target, artifact_id),
                f"Use {artifact_id} from {source} in {target}.",
            )
            option_key = _handoff_key(source, target, artifact_id)
            options[option_key] = {
                "from": source,
                "to": target,
                "artifact": artifact_id,
                "handoff": handoff,
            }
    return options


def _handoff_option_label(option_key: str, handoff_options: dict[str, dict[str, str]]) -> str:
    handoff = handoff_options.get(option_key, {})
    source = handoff.get("from", "")
    target = handoff.get("to", "")
    artifact = handoff.get("artifact", "")
    return f"{target} uses {artifact} from {source}"


def _default_artifact_keys(artifact_options: dict[str, dict[str, str]], tables: dict[str, pd.DataFrame]) -> list[str]:
    existing = {
        f"{row['node']}::{row['id']}"
        for row in _editor_rows(tables["produces"], GLOBAL_DAG_ARTIFACT_COLUMNS)
        if row["node"] and row["id"]
    }
    defaults = [key for key in artifact_options if key in existing]
    return defaults or list(artifact_options)


def _default_handoff_keys(
    handoff_options: dict[str, dict[str, str]],
    payload: dict[str, Any],
) -> list[str]:
    defaults: list[str] = []
    for source, target, artifact in _global_dag_existing_handoffs(payload):
        option_key = _handoff_key(source, target, artifact)
        if option_key in handoff_options:
            defaults.append(option_key)
    return defaults


def _selected_artifact_rows(
    artifact_keys: list[str],
    artifact_options: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    return [artifact_options[key] for key in artifact_keys if key in artifact_options]


def _selected_handoff_rows(
    handoff_keys: list[str],
    handoff_options: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    return [handoff_options[key] for key in handoff_keys if key in handoff_options]


def _workplan_output_rows(artifact_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "Step": row.get("node", ""),
            "Creates": row.get("id", ""),
            "Type": row.get("kind", ""),
            "Path": row.get("path", ""),
        }
        for row in artifact_rows
    ]


def _need_option_label(option_key: str, need_options: dict[str, dict[str, str]]) -> str:
    need = need_options.get(option_key, {})
    target = need.get("to", "")
    artifact = need.get("artifact", "")
    source = need.get("from", "")
    return f"{target} uses {artifact} from {source}"


def _workplan_need_rows(need_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "Step": row.get("to", ""),
            "Uses": row.get("artifact", ""),
            "From step": row.get("from", ""),
            "How it is used": row.get("handoff", ""),
        }
        for row in need_rows
    ]


def _workplan_step_rows(stage_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "Step": row.get("id", ""),
            "App": row.get("app", ""),
            "Why": row.get("purpose", ""),
        }
        for row in stage_rows
    ]


def _consumes_rows_from_handoffs(
    handoff_rows: list[dict[str, str]],
    artifact_options: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    artifact_by_source_id = {
        (artifact["node"], artifact["id"]): artifact
        for artifact in artifact_options.values()
    }
    seen: set[tuple[str, str]] = set()
    rows: list[dict[str, str]] = []
    for handoff in handoff_rows:
        source = handoff["from"]
        target = handoff["to"]
        artifact_id = handoff["artifact"]
        if (target, artifact_id) in seen:
            continue
        artifact = artifact_by_source_id.get((source, artifact_id), {})
        rows.append(
            {
                "node": target,
                "id": artifact_id,
                "kind": artifact.get("kind", ""),
                "path": artifact.get("path", ""),
            }
        )
        seen.add((target, artifact_id))
    return rows


def _global_dag_payload_from_visual_editor(
    base_payload: dict[str, Any],
    *,
    dag_id: str,
    label: str,
    description: str,
    nodes_value: Any,
    produces_value: Any,
    consumes_value: Any,
    edges_value: Any,
    controlled_contract_execution: bool = False,
) -> dict[str, Any]:
    return build_dag_payload_from_editor(
        base_payload,
        dag_id=dag_id,
        label=label,
        description=description,
        stage_rows=_editor_rows(nodes_value, GLOBAL_DAG_NODE_COLUMNS),
        produced_artifact_rows=_editor_rows(produces_value, GLOBAL_DAG_ARTIFACT_COLUMNS),
        consumed_artifact_rows=_editor_rows(consumes_value, GLOBAL_DAG_ARTIFACT_COLUMNS),
        handoff_rows=_editor_rows(edges_value, GLOBAL_DAG_EDGE_COLUMNS),
        controlled_contract_execution=controlled_contract_execution,
    )


def _global_runner_state_path(lab_dir: Path) -> Path:
    return lab_dir / ".agilab" / GLOBAL_RUNNER_STATE_FILENAME


def _global_dag_engine(
    repo_root: Path,
    lab_dir: Path,
    dag_path: Path | None,
    env: AgiEnv | None = None,
) -> DagRunEngine:
    stage_submitter = None
    if env is not None:
        stage_submitter = build_global_dag_distributed_stage_submitter(
            env=env,
            app_settings=st.session_state.get("app_settings"),
            verbose=int(st.session_state.get("cluster_verbose", 0) or 0),
        )
    return DagRunEngine(
        repo_root=repo_root,
        lab_dir=lab_dir,
        dag_path=dag_path,
        run_queue_fn=run_global_dag_queue_baseline_app,
        run_relay_fn=run_global_dag_relay_followup_app,
        stage_submit_fn=stage_submitter,
    )


def _global_dag_distributed_request_preview_rows(
    env: AgiEnv,
    state: dict[str, Any],
    repo_root: Path,
) -> list[dict[str, str]]:
    settings = load_dag_distributed_settings(env, st.session_state.get("app_settings"))
    config = dag_distributed_stage_config_from_settings(
        settings,
        verbose=int(st.session_state.get("cluster_verbose", 0) or 0),
    )
    if config is None:
        return []
    return build_distributed_request_preview_rows(state, repo_root=repo_root, config=config)


def _runner_state_dag_matches(
    state: Dict[str, Any],
    dag_path: Path | None,
    repo_root: Path,
) -> bool:
    return runner_state_dag_matches(state, dag_path, repo_root)


def _load_or_create_global_runner_state(
    env: AgiEnv,
    lab_dir: Path,
    dag_path: Path | None = None,
    *,
    reset: bool = False,
) -> tuple[dict[str, Any], Path, Path | None]:
    repo_root = _repo_root_for_global_dag()
    dag_path = dag_path or _global_runner_dag_path(env, repo_root)
    return _global_dag_engine(repo_root, lab_dir, dag_path, env=env).load_or_create_state(reset=reset)


def _global_dag_now_iso() -> str:
    return _dag_run_engine_module._now_iso()


def _run_next_controlled_global_dag_stage(
    state: Dict[str, Any],
    *,
    repo_root: Path,
    dag_path: Path | None,
    lab_dir: Path,
    run_queue_fn: Callable[..., Dict[str, Any]] | None = None,
    run_relay_fn: Callable[..., Dict[str, Any]] | None = None,
    now_fn: Callable[[], str] = _global_dag_now_iso,
) -> GlobalDagStageExecutionResult:
    return run_next_controlled_global_dag_stage(
        state,
        repo_root=repo_root,
        dag_path=dag_path,
        lab_dir=lab_dir,
        run_queue_fn=run_queue_fn or run_global_dag_queue_baseline_app,
        run_relay_fn=run_relay_fn or run_global_dag_relay_followup_app,
        now_fn=now_fn,
    )


def _run_ready_controlled_global_dag_stages(
    state: Dict[str, Any],
    *,
    repo_root: Path,
    dag_path: Path | None,
    lab_dir: Path,
    run_queue_fn: Callable[..., Dict[str, Any]] | None = None,
    run_relay_fn: Callable[..., Dict[str, Any]] | None = None,
    stage_submit_fn: Callable[..., Dict[str, Any]] | None = None,
    now_fn: Callable[[], str] = _global_dag_now_iso,
    max_workers: int | None = None,
    execution_backend: str = GLOBAL_DAG_STAGE_BACKEND_LOCAL,
) -> GlobalDagBatchExecutionResult:
    return run_ready_controlled_global_dag_stages(
        state,
        repo_root=repo_root,
        dag_path=dag_path,
        lab_dir=lab_dir,
        run_queue_fn=run_queue_fn or run_global_dag_queue_baseline_app,
        run_relay_fn=run_relay_fn or run_global_dag_relay_followup_app,
        stage_submit_fn=stage_submit_fn,
        now_fn=now_fn,
        max_workers=max_workers,
        execution_backend=execution_backend,
    )


def _available_artifact_ids(state: Dict[str, Any]) -> set[str]:
    return available_artifact_ids(state)


def _global_dag_executor_label(unit: Dict[str, Any]) -> str:
    executor = str(unit.get("executor", "") or "").strip()
    if executor:
        return executor

    contract = unit.get("execution_contract")
    if not isinstance(contract, dict):
        return "preview"

    entrypoint = str(contract.get("entrypoint", "")).strip()
    if entrypoint:
        return entrypoint

    command = contract.get("command")
    if isinstance(command, str) and command.strip():
        return f"command: {command.strip()}"
    if isinstance(command, list):
        command_text = " ".join(str(part).strip() for part in command if str(part).strip())
        if command_text:
            return f"command: {command_text}"
    return "preview"


def _controlled_global_dag_real_run_supported(
    state: Dict[str, Any],
    dag_path: Path | None,
    repo_root: Path,
) -> bool:
    return controlled_real_run_supported(state, dag_path, repo_root)


def _state_units_for_display(state: Dict[str, Any]) -> list[dict[str, str]]:
    units = state.get("units", [])
    if not isinstance(units, list):
        return []
    rows: list[dict[str, str]] = []
    for unit in units:
        if not isinstance(unit, dict):
            continue
        operator_ui = unit.get("operator_ui", {})
        blocked_by = operator_ui.get("blocked_by_artifacts", []) if isinstance(operator_ui, dict) else []
        rows.append(
            {
                "unit": str(unit.get("id", "")),
                "app": str(unit.get("app", "")),
                "executor": _global_dag_executor_label(unit),
                "status": str(unit.get("dispatch_status", "")),
                "depends_on": ", ".join(str(item) for item in unit.get("depends_on", []) if str(item)),
                "blocked_by": ", ".join(
                    str(item)
                    for item in blocked_by
                    if str(item)
                ),
            }
        )
    return rows


def _workplan_artifact_id(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    return str(row.get("artifact", "") or row.get("id", "") or "").strip()


def _global_dag_workplan_state(unit: dict[str, Any]) -> str:
    status = str(
        unit.get("dispatch_status", "")
        or unit.get("status", "")
        or unit.get("plan_status", "")
        or ""
    ).strip()
    return {
        "blocked": "waiting",
        "completed": "done",
        "failed": "failed",
        "planned": "planned",
        "runnable": "ready",
        "running": "running",
        "stale": "stale",
    }.get(status, status or "planned")


def _global_dag_workplan_needs(unit: dict[str, Any]) -> str:
    dependencies = unit.get("artifact_dependencies", [])
    if not isinstance(dependencies, list):
        return "none"
    labels: list[str] = []
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            continue
        artifact_id = _workplan_artifact_id(dependency)
        producer = str(dependency.get("from", "") or "").strip()
        if artifact_id and producer:
            labels.append(f"{artifact_id} from {producer}")
        elif artifact_id:
            labels.append(artifact_id)
    return ", ".join(labels) if labels else "none"


def _global_dag_workplan_produces(unit: dict[str, Any]) -> str:
    produced = unit.get("produces", [])
    if not isinstance(produced, list):
        return "none"
    labels = [_workplan_artifact_id(artifact) for artifact in produced]
    labels = [label for label in labels if label]
    return ", ".join(labels) if labels else "none"


def _global_dag_workplan_rows_for_display(state: Dict[str, Any]) -> list[dict[str, str]]:
    units = state.get("units", [])
    if not isinstance(units, list):
        return []
    rows: list[dict[str, str]] = []
    for unit in units:
        if not isinstance(unit, dict):
            continue
        rows.append(
            {
                "Step": str(unit.get("id", "")),
                "App": str(unit.get("app", "")),
                "Runs with": _global_dag_executor_label(unit),
                "Uses": _global_dag_workplan_needs(unit),
                "Creates": _global_dag_workplan_produces(unit),
                "Status": _global_dag_workplan_state(unit),
            }
        )
    return rows


def _render_project_stage_snippet_preview(
    snippet_rows: list[dict[str, str]] | None,
    *,
    index_page_str: str,
) -> None:
    if not snippet_rows:
        return
    show_snippets = st.checkbox(
        "Show snippet code",
        key=f"{index_page_str}_global_runner_show_snippets",
        help="Review the Python code for one project stage, like ORCHESTRATE generated snippets.",
    )
    if not show_snippets:
        return

    row_by_unit = {row["unit"]: row for row in snippet_rows}
    options = list(row_by_unit)
    selected_key = f"{index_page_str}_global_runner_snippet_stage"
    if st.session_state.get(selected_key) not in row_by_unit:
        st.session_state[selected_key] = options[0]

    def _format_snippet_option(unit_id: str) -> str:
        row = row_by_unit.get(str(unit_id))
        return str(row.get("label", unit_id)) if row else str(unit_id)

    selected_unit = st.selectbox(
        "Snippet stage",
        options,
        key=selected_key,
        format_func=_format_snippet_option,
        help="Choose the project stage whose snippet should be shown.",
    )
    row = row_by_unit.get(str(selected_unit), snippet_rows[0])
    source = str(row.get("source", "") or "").strip()
    model = str(row.get("model", "") or "").strip()
    prompt = str(row.get("prompt", "") or "").strip()
    if source:
        st.caption(f"Snippet source: `{source}`")
    if model:
        st.caption(f"Model: `{model}`")
    if prompt:
        st.caption(f"Prompt: {prompt}")
    st.code(str(row.get("code", "") or "# Empty snippet"), language="python")


def _artifact_handoffs_for_display(state: Dict[str, Any]) -> list[dict[str, str]]:
    available = _available_artifact_ids(state)
    units = state.get("units", [])
    if not isinstance(units, list):
        return []
    rows: list[dict[str, str]] = []
    for unit in units:
        if not isinstance(unit, dict):
            continue
        target_id = str(unit.get("id", ""))
        target_app = str(unit.get("app", ""))
        dependencies = unit.get("artifact_dependencies", [])
        if not isinstance(dependencies, list):
            continue
        for dependency in dependencies:
            if not isinstance(dependency, dict):
                continue
            artifact_id = str(dependency.get("artifact", "")).strip()
            if not artifact_id:
                continue
            rows.append(
                {
                    "Output": artifact_id,
                    "From step": str(dependency.get("from", "")),
                    "From app": str(dependency.get("from_app", "")),
                    "Used by step": target_id,
                    "Used by app": target_app,
                    "Status": "available" if artifact_id in available else "missing",
                    "Path": str(dependency.get("source_path", "")),
                    "How it is used": str(dependency.get("handoff", "")),
                }
            )
    return rows


def _global_dag_execution_history_rows(state: Dict[str, Any]) -> list[dict[str, str]]:
    return execution_history_rows(state)


def _global_dag_units(state: Dict[str, Any]) -> list[dict[str, Any]]:
    units = state.get("units", [])
    if not isinstance(units, list):
        return []
    return [unit for unit in units if isinstance(unit, dict)]


def _global_dag_status_ids(state: Dict[str, Any], status: str) -> list[str]:
    summary = state.get("summary", {})
    summary_key = f"{status}_unit_ids"
    if isinstance(summary, dict) and isinstance(summary.get(summary_key), list):
        return [str(unit_id) for unit_id in summary[summary_key] if str(unit_id)]
    return [
        str(unit.get("id", ""))
        for unit in _global_dag_units(state)
        if unit.get("dispatch_status") == status and str(unit.get("id", ""))
    ]


def _global_dag_unit_count(state: Dict[str, Any]) -> int:
    summary = state.get("summary", {})
    if isinstance(summary, dict) and summary.get("unit_count") is not None:
        try:
            return int(summary.get("unit_count") or 0)
        except (TypeError, ValueError):
            pass
    return len(_global_dag_units(state))


def _global_dag_dependency_count(state: Dict[str, Any]) -> int:
    count = 0
    for unit in _global_dag_units(state):
        dependencies = unit.get("artifact_dependencies", [])
        if isinstance(dependencies, list):
            count += sum(1 for dependency in dependencies if isinstance(dependency, dict))
    return count


def _global_dag_next_action(state: Dict[str, Any]) -> str:
    stale = _global_dag_status_ids(state, "stale")
    if stale:
        return "Run the workflow again or reset the preview after editing project stages."
    failed = _global_dag_status_ids(state, "failed")
    if failed:
        return f"Inspect failed step `{failed[0]}`."
    running = _global_dag_status_ids(state, "running")
    if running:
        return f"Monitor running step `{running[0]}`."
    runnable = _global_dag_status_ids(state, "runnable")
    if runnable:
        return f"Preview `{runnable[0]}`."
    blocked = _global_dag_status_ids(state, "blocked")
    if blocked:
        blocked_artifacts: list[str] = []
        for unit in _global_dag_units(state):
            if str(unit.get("id", "")) != blocked[0]:
                continue
            operator_ui = unit.get("operator_ui", {})
            raw_blocked = operator_ui.get("blocked_by_artifacts", []) if isinstance(operator_ui, dict) else []
            if isinstance(raw_blocked, list):
                blocked_artifacts = [str(item) for item in raw_blocked if str(item)]
            break
        suffix = f" until `{', '.join(blocked_artifacts)}` is ready" if blocked_artifacts else ""
        return f"Wait for `{blocked[0]}`{suffix}."
    completed = _global_dag_status_ids(state, "completed")
    if completed and len(completed) == _global_dag_unit_count(state):
        return "All steps completed."
    return "No ready step is available."


def _global_dag_execution_scope(state: Dict[str, Any]) -> str:
    provenance = state.get("provenance", {})
    if not isinstance(provenance, dict):
        return "preview only, no app run"
    if bool(provenance.get("real_app_execution")):
        return "live app execution"
    if bool(provenance.get("controlled_execution")):
        dispatch_mode = str(provenance.get("dispatch_mode", ""))
        if dispatch_mode == "controlled_contract_stage_execution":
            return "controlled contract execution"
        return "controlled step execution"
    return "preview only, no app run"


def _global_dag_execution_status(state: Dict[str, Any], support: Any) -> str:
    if _global_dag_status_ids(state, "stale"):
        return "Stale: project stages changed"
    if not bool(getattr(support, "supported", False)):
        return str(getattr(support, "status", "Preview-only") or "Preview-only")
    failed = _global_dag_status_ids(state, "failed")
    if failed:
        return "Blocked: failed step"
    if _global_dag_unit_count(state) and len(_global_dag_status_ids(state, "completed")) == _global_dag_unit_count(state):
        return "Completed"
    if _global_dag_status_ids(state, "blocked") and not _global_dag_status_ids(state, "runnable"):
        return "Blocked: missing output"
    return str(getattr(support, "status", "Executable") or "Executable")


def _global_dag_readiness_summary(state: Dict[str, Any]) -> dict[str, Any]:
    return {
        "stage_count": _global_dag_unit_count(state),
        "dependency_count": _global_dag_dependency_count(state),
        "runnable_count": len(_global_dag_status_ids(state, "runnable")),
        "blocked_count": len(_global_dag_status_ids(state, "blocked")),
        "running_count": len(_global_dag_status_ids(state, "running")),
        "completed_count": len(_global_dag_status_ids(state, "completed")),
        "failed_count": len(_global_dag_status_ids(state, "failed")),
        "stale_count": len(_global_dag_status_ids(state, "stale")),
        "next_action": _global_dag_next_action(state),
        "execution_scope": _global_dag_execution_scope(state),
    }


def _render_global_dag_readiness(state: Dict[str, Any]) -> None:
    summary = _global_dag_readiness_summary(state)
    st.markdown("**Plan readiness**")
    stage_col, dependency_col, runnable_col, blocked_col = st.columns(4)
    stage_col.metric("Steps", int(summary["stage_count"]))
    dependency_col.metric("Inputs", int(summary["dependency_count"]))
    runnable_col.metric("Ready", int(summary["runnable_count"]))
    blocked_col.metric("Waiting", int(summary["blocked_count"]))
    st.caption(f"Next action: {summary['next_action']}")
    st.caption(f"Run mode: {summary['execution_scope']}")


def _render_global_dag_execution_capability(
    *,
    contract_name: str,
    execution_status: str,
    real_run_support: Any,
) -> None:
    st.markdown("**Run mode**")
    contract_col, mode_col, adapter_col = st.columns(3)
    contract_col.metric("Plan", contract_name or "not selected")
    mode_col.metric("Run mode", execution_status)
    adapter_col.metric(
        "Runner",
        str(getattr(real_run_support, "adapter", "") or "preview only"),
    )
    message = str(getattr(real_run_support, "message", "")).strip()
    if message:
        st.caption(message)


def _workflow_evidence_latest_path(state_path: Path) -> Path:
    return state_path.expanduser().parent / WORKFLOW_EVIDENCE_DIRNAME / LATEST_WORKFLOW_EVIDENCE_FILENAME


def _resolve_workflow_evidence_path(raw_path: Any, latest_path: Path) -> Path:
    candidate = Path(str(raw_path or "")).expanduser()
    if candidate.is_absolute():
        return candidate
    return latest_path.parent / candidate


def _workflow_evidence_status_label(status: str, run_status: str = "") -> str:
    normalized = str(status or "").strip().lower()
    if normalized == "pass":
        return "completed"
    if normalized == "fail":
        return "failed"
    run_status = str(run_status or "").strip().lower()
    if run_status in {"planned", "running", "stale", "completed", "failed"}:
        return run_status
    if normalized == "unknown":
        return "planned/running"
    return normalized or "not recorded"


def _run_manifest_status_label(status: str) -> str:
    normalized = str(status or "").strip().lower()
    if normalized == "pass":
        return "done"
    if normalized == "fail":
        return "failed"
    return normalized or "waiting"


def _workflow_run_log_dir(env: Any) -> Path | None:
    raw_runenv = getattr(env, "runenv", None)
    if raw_runenv:
        return Path(raw_runenv).expanduser()
    target = str(getattr(env, "target", "") or getattr(env, "app", "") or "").strip()
    if not target:
        return None
    return Path.home() / "log" / "execute" / target


def _latest_run_log_file(run_log_dir: Path) -> Path | None:
    try:
        candidates = [path for path in run_log_dir.expanduser().glob("run_*.log") if path.is_file()]
    except (OSError, RuntimeError, ValueError):
        return None
    if not candidates:
        return None

    def _sort_key(path: Path) -> tuple[float, str]:
        try:
            return path.stat().st_mtime, path.name
        except OSError:
            return 0.0, path.name

    return sorted(candidates, key=_sort_key)[-1]


def _format_duration_seconds(value: Any) -> str:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return ""
    if seconds < 0:
        return ""
    if seconds < 60:
        return f"{seconds:.2f}s"
    minutes, remainder = divmod(seconds, 60)
    return f"{int(minutes)}m {remainder:.0f}s"


def _latest_operational_run_summary(run_log_dir: Path | None) -> dict[str, Any]:
    if run_log_dir is None:
        return {
            "available": False,
            "status": "waiting",
            "message": "No execution log directory is configured for this project.",
            "run_log_dir": "",
        }
    run_log_dir = run_log_dir.expanduser()
    manifest_path = run_log_dir / RUN_MANIFEST_FILENAME
    latest_log_path = _latest_run_log_file(run_log_dir)
    summary: dict[str, Any] = {
        "available": bool(latest_log_path or manifest_path.is_file()),
        "status": "done" if latest_log_path else "waiting",
        "message": f"Execution logs are read from `{run_log_dir}`.",
        "run_log_dir": str(run_log_dir),
        "log_path": str(latest_log_path) if latest_log_path is not None else "",
        "manifest_path": str(manifest_path) if manifest_path.is_file() else "",
        "started_at": "",
        "duration": "",
        "run_id": "",
    }
    if manifest_path.is_file():
        try:
            manifest = load_run_manifest(manifest_path)
            manifest_payload = manifest_summary(manifest)
            summary.update(
                {
                    "available": True,
                    "status": _run_manifest_status_label(str(manifest_payload.get("status", ""))),
                    "started_at": manifest.timing.started_at,
                    "duration": _format_duration_seconds(manifest.timing.duration_seconds),
                    "run_id": str(manifest_payload.get("run_id", "")),
                }
            )
        except Exception as exc:
            summary.update(
                {
                    "available": True,
                    "status": "warning",
                    "message": f"Run manifest could not be read: {exc}",
                    "manifest_path": str(manifest_path),
                }
            )
    return summary


def _render_existing_execution_log(run_log_dir: Path | None, *, key_prefix: str) -> None:
    run_summary = _latest_operational_run_summary(run_log_dir)
    st.markdown("**Execution log**")
    if not run_summary.get("available"):
        st.caption(str(run_summary.get("message", "No execution log has been recorded yet.")))
        if run_summary.get("run_log_dir"):
            st.caption(f"Log directory: `{run_summary['run_log_dir']}`")
        return

    render_latest_run_card(
        st,
        status=run_summary.get("status", ""),
        log_path=run_summary.get("log_path", ""),
        started_at=run_summary.get("started_at", ""),
        duration=run_summary.get("duration", ""),
        key_prefix=key_prefix,
        title="Latest execution",
    )
    st.caption(str(run_summary.get("message", "")))
    manifest_path = str(run_summary.get("manifest_path", ""))
    if manifest_path:
        st.caption(f"Run manifest: `{manifest_path}`")


def _latest_workflow_evidence_summary(state_path: Path) -> dict[str, Any]:
    latest_path = _workflow_evidence_latest_path(state_path)
    if not latest_path.is_file():
        return {
            "available": False,
            "status_label": "not recorded",
            "message": "No workflow evidence has been recorded for this plan yet.",
            "latest_path": str(latest_path),
        }
    try:
        latest_payload = json.loads(latest_path.read_text(encoding="utf-8"))
        if not isinstance(latest_payload, dict):
            raise ValueError("latest evidence pointer must be a JSON object")
        manifest_path = _resolve_workflow_evidence_path(latest_payload.get("manifest_path"), latest_path)
        manifest = load_workflow_run_manifest(manifest_path)
    except Exception as exc:
        return {
            "available": False,
            "status_label": "unreadable",
            "message": f"Latest workflow evidence could not be read: {exc}",
            "latest_path": str(latest_path),
        }

    manifest_summary = workflow_manifest_summary(manifest)
    runner_state = manifest.get("runner_state", {})
    runner_state = runner_state if isinstance(runner_state, Mapping) else {}
    runtime_contract = manifest.get("runtime_contract", {})
    runtime_contract = runtime_contract if isinstance(runtime_contract, Mapping) else {}
    ledger_payload = manifest.get("evidence_ledger", {})
    ledger_payload = ledger_payload if isinstance(ledger_payload, Mapping) else {}
    ledger_path = _resolve_workflow_evidence_path(
        latest_payload.get("ledger_path") or ledger_payload.get("path"),
        latest_path,
    )
    graph_payload = manifest.get("evidence_graph", {})
    graph_payload = graph_payload if isinstance(graph_payload, Mapping) else {}
    graph_path_value = latest_payload.get("graph_path") or graph_payload.get("path") or ""
    graph_path = _resolve_workflow_evidence_path(graph_path_value, latest_path) if graph_path_value else None
    status_label = _workflow_evidence_status_label(
        str(manifest.get("status", "")),
        str(runner_state.get("run_status", "")),
    )
    return {
        "available": True,
        "status_label": status_label,
        "message": f"Latest workflow evidence: {status_label}.",
        "latest_path": str(latest_path),
        "manifest_path": str(manifest_path),
        "ledger_path": str(ledger_path),
        "graph_path": str(graph_path) if graph_path else "",
        "manifest_id": manifest_summary.get("manifest_id", ""),
        "run_id": manifest_summary.get("run_id", ""),
        "unit_count": manifest_summary.get("unit_count", 0),
        "produced_count": manifest_summary.get("produced_count", 0),
        "consumed_count": manifest_summary.get("consumed_count", 0),
        "phase": manifest_summary.get("phase", runtime_contract.get("phase", "unknown")),
        "event_count": manifest_summary.get("event_count", runtime_contract.get("event_count", 0)),
        "enabled_controls": _enabled_workflow_control_labels(runtime_contract),
        "runner_state_sha256": str(runner_state.get("snapshot_sha256", "")),
    }


def _render_workflow_run_evidence(state_path: Path) -> None:
    evidence = _latest_workflow_evidence_summary(state_path)
    st.markdown("**Plan evidence**")
    if not evidence.get("available"):
        st.caption(str(evidence.get("message", "No workflow evidence has been recorded yet.")))
        st.caption(f"Evidence pointer: `{evidence.get('latest_path', '')}`")
        return

    status_col, steps_col, creates_col, uses_col = st.columns(4)
    status_col.metric("Evidence", str(evidence.get("status_label", "unknown")))
    steps_col.metric("Steps", int(evidence.get("unit_count", 0) or 0))
    creates_col.metric("Creates", int(evidence.get("produced_count", 0) or 0))
    uses_col.metric("Uses", int(evidence.get("consumed_count", 0) or 0))
    st.caption(str(evidence.get("message", "Latest workflow evidence recorded.")))
    st.caption(
        "Runtime phase: "
        f"`{evidence.get('phase', 'unknown')}`; "
        f"events: {int(evidence.get('event_count', 0) or 0)}; "
        f"enabled controls: {', '.join(evidence.get('enabled_controls', ())) or 'none'}"
    )
    manifest_path = str(evidence.get("manifest_path", ""))
    ledger_path = str(evidence.get("ledger_path", ""))
    graph_path = str(evidence.get("graph_path", ""))
    if manifest_path:
        st.caption(f"Manifest: `{manifest_path}`")
    if ledger_path:
        st.caption(f"Ledger: `{ledger_path}`")
    if graph_path:
        st.caption(f"Evidence graph: `{graph_path}`")


def _enabled_workflow_control_labels(runtime_contract: Mapping[str, Any]) -> tuple[str, ...]:
    controls = runtime_contract.get("controls", [])
    if not isinstance(controls, list):
        return ()
    return tuple(
        str(control.get("label", "") or "")
        for control in controls
        if isinstance(control, Mapping) and bool(control.get("enabled")) and str(control.get("label", "") or "")
    )


def _dot_quote(value: Any) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _global_dag_dot(state: Dict[str, Any]) -> str:
    units = state.get("units", [])
    if not isinstance(units, list) or not units:
        return ""
    available = _available_artifact_ids(state)
    lines = [
        "digraph AGILABGlobalDAG {",
        "  rankdir=LR;",
        '  graph [bgcolor="transparent", pad="0.25", nodesep="0.6", ranksep="0.75"];',
        '  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=10, margin="0.08,0.05"];',
        '  edge [fontname="Helvetica", fontsize=9, color="#6b7280"];',
    ]
    status_colors = {
        "runnable": "#dcfce7",
        "running": "#dbeafe",
        "completed": "#e0f2fe",
        "blocked": "#fef3c7",
        "failed": "#fee2e2",
        "stale": "#f1f5f9",
    }
    artifact_nodes: dict[str, str] = {}
    for unit in units:
        if not isinstance(unit, dict):
            continue
        unit_id = str(unit.get("id", ""))
        if not unit_id:
            continue
        status = str(unit.get("dispatch_status", ""))
        app = str(unit.get("app", ""))
        executor = _global_dag_executor_label(unit)
        executor_line = f"\\nexec: {executor}" if executor != "preview" else ""
        label = f"{unit_id}\\n{app}\\n{status}{executor_line}"
        fill = status_colors.get(status, "#f8fafc")
        lines.append(f"  {_dot_quote(unit_id)} [label={_dot_quote(label)}, fillcolor={_dot_quote(fill)}];")
        for artifact in unit.get("produces", []):
            if not isinstance(artifact, dict):
                continue
            artifact_id = str(artifact.get("artifact", "")).strip()
            if not artifact_id:
                continue
            artifact_nodes[artifact_id] = "available" if artifact_id in available else "planned"
            lines.append(f"  {_dot_quote(unit_id)} -> {_dot_quote('artifact:' + artifact_id)};")
        dependencies = unit.get("artifact_dependencies", [])
        if isinstance(dependencies, list):
            for dependency in dependencies:
                if not isinstance(dependency, dict):
                    continue
                artifact_id = str(dependency.get("artifact", "")).strip()
                if not artifact_id:
                    continue
                artifact_nodes.setdefault(artifact_id, "available" if artifact_id in available else "missing")
                lines.append(f"  {_dot_quote('artifact:' + artifact_id)} -> {_dot_quote(unit_id)};")
    for artifact_id, status in sorted(artifact_nodes.items()):
        fill = "#dcfce7" if status == "available" else "#fff7ed" if status == "missing" else "#f8fafc"
        label = f"{artifact_id}\\n{status}"
        lines.append(
            f"  {_dot_quote('artifact:' + artifact_id)} "
            f"[label={_dot_quote(label)}, shape=note, fillcolor={_dot_quote(fill)}];"
        )
    lines.append("}")
    return "\n".join(lines)


def _pipeline_dag_stage_rows(pipeline_stages: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for stage in pipeline_stages or []:
        if isinstance(stage, dict) and _is_displayable_stage(stage):
            rows.append(stage)
    return rows


def _pipeline_stage_unit_id(index: int) -> str:
    return f"stage_{index + 1:03d}"


def _pipeline_stage_artifact_id(unit_id: str) -> str:
    return f"{unit_id}_complete"


def _pipeline_stage_executor_label(stage: dict[str, Any]) -> str:
    engine = str(stage.get("R", "") or "").strip()
    runtime = str(stage.get("E", "") or "").strip()
    if engine:
        return engine
    if runtime:
        return "agi.run"
    return "runpy"


def _pipeline_stage_purpose(stage: dict[str, Any], index: int) -> str:
    description = str(stage.get("D", "") or "").strip()
    if description:
        return description
    summary = _stage_summary(stage, width=96)
    return summary or f"Project stage {index + 1}"


def _pipeline_stages_digest(pipeline_stages: list[dict[str, Any]]) -> str:
    normalized = [
        {
            "D": str(stage.get("D", "") or ""),
            "Q": str(stage.get("Q", "") or ""),
            "M": str(stage.get("M", "") or ""),
            "C": str(stage.get("C", "") or ""),
            "E": str(stage.get("E", "") or ""),
            "R": str(stage.get("R", "") or ""),
        }
        for stage in pipeline_stages
    ]
    payload = json.dumps(normalized, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _pipeline_stage_snippet_rows(pipeline_stages: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for index, stage in enumerate(_pipeline_dag_stage_rows(pipeline_stages)):
        code = str(stage.get("C", "") or "")
        if not code.strip():
            continue
        unit_id = _pipeline_stage_unit_id(index)
        summary = _pipeline_stage_purpose(stage, index)
        label = f"{unit_id} - {summary}" if summary else unit_id
        rows.append(
            {
                "unit": unit_id,
                "label": label,
                "summary": summary,
                "prompt": str(stage.get("Q", "") or "").strip(),
                "model": str(stage.get("M", "") or "").strip(),
                "source": _orchestrate_snippet_source(stage),
                "code": code,
            }
        )
    return rows


def _path_mtime(path_text: str | Path | None) -> float | None:
    if not path_text:
        return None
    try:
        return Path(path_text).expanduser().stat().st_mtime
    except (OSError, TypeError, ValueError):
        return None


def _pipeline_log_lines_from_session(index_page: str, session_state: Mapping[str, Any] | None) -> list[str]:
    if session_state is None:
        return []
    lines: list[str] = []
    raw_logs = session_state.get(f"{index_page}__run_logs", [])
    if isinstance(raw_logs, list):
        lines.extend(str(line) for line in raw_logs)
    elif isinstance(raw_logs, tuple):
        lines.extend(str(line) for line in raw_logs)
    log_file = str(session_state.get(f"{index_page}__last_run_log_file") or "").strip()
    if log_file:
        try:
            file_lines = Path(log_file).expanduser().read_text(encoding="utf-8", errors="replace").splitlines()
        except (OSError, TypeError, ValueError):
            file_lines = []
        lines.extend(file_lines)
    return lines


def _stage_indices_from_log_pattern(
    lines: list[str],
    pattern: re.Pattern[str],
    *,
    stage_count: int,
) -> list[int]:
    indices: list[int] = []
    for line in lines:
        for match in pattern.finditer(line):
            try:
                index = int(match.group(1)) - 1
            except (TypeError, ValueError):
                continue
            if 0 <= index < stage_count:
                indices.append(index)
    return indices


def _pipeline_stages_execution_evidence(
    *,
    index_page: str,
    session_state: Mapping[str, Any] | None,
    stages_file: Path | None,
    stage_count: int,
) -> dict[str, Any]:
    if not index_page or session_state is None or stage_count <= 0:
        return {"has_evidence": False}
    lines = _pipeline_log_lines_from_session(index_page, session_state)
    last_status = str(session_state.get(f"{index_page}__last_run_status") or "").strip().lower()
    started_order = _stage_indices_from_log_pattern(lines, PIPELINE_STAGE_STARTED_RE, stage_count=stage_count)
    completed_order = _stage_indices_from_log_pattern(lines, PIPELINE_STAGE_COMPLETED_RE, stage_count=stage_count)
    completed = sorted(set(completed_order))
    running: list[int] = []
    failed: list[int] = []
    last_started = started_order[-1] if started_order else None
    if last_status in {"failed", "error"} and last_started is not None and last_started not in completed:
        failed = [last_started]
    elif last_status == "running" and last_started is not None and last_started not in completed:
        running = [last_started]

    log_file = str(session_state.get(f"{index_page}__last_run_log_file") or "").strip()
    log_mtime = _path_mtime(log_file)
    stages_mtime = _path_mtime(stages_file)
    stale = bool(last_status or completed or started_order) and (
        log_mtime is not None and stages_mtime is not None and stages_mtime > log_mtime
    )
    sync_payload = {
        "last_status": last_status,
        "completed": completed,
        "running": running,
        "failed": failed,
        "log_file": log_file,
        "log_mtime": log_mtime,
        "stages_mtime": stages_mtime,
        "stale": stale,
    }
    sync_token = hashlib.sha256(json.dumps(sync_payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return {
        "has_evidence": bool(completed or running or failed or stale),
        "last_status": last_status,
        "completed": completed,
        "running": running,
        "failed": failed,
        "started": sorted(set(started_order)),
        "log_file": log_file,
        "log_mtime": log_mtime,
        "stages_mtime": stages_mtime,
        "stale": stale,
        "sync_token": sync_token,
    }


def _pipeline_stages_unit_index(unit: Mapping[str, Any]) -> int | None:
    try:
        index = int(unit.get("order_index", -1))
    except (TypeError, ValueError):
        return None
    return index if index >= 0 else None


def _pipeline_stages_update_operator_ui(
    unit: dict[str, Any],
    *,
    status: str,
    message: str,
    blocked_artifacts: list[str] | None = None,
) -> None:
    severity = {
        "completed": "success",
        "failed": "error",
        "running": "info",
        "runnable": "info",
        "blocked": "warning",
        "stale": "warning",
    }.get(status, "info")
    unit["operator_ui"] = {
        "state": status,
        "severity": severity,
        "message": message,
        "blocked_by_artifacts": blocked_artifacts or [],
    }


def _pipeline_stages_set_artifact_statuses(
    state: dict[str, Any],
    available_artifacts: set[str],
    status: str = "planned",
) -> None:
    artifacts = state.get("artifacts", [])
    if not isinstance(artifacts, list):
        return
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        artifact_id = str(artifact.get("artifact", "")).strip()
        artifact["status"] = "available" if artifact_id in available_artifacts else status


def _apply_pipeline_stages_execution_evidence(state: dict[str, Any], evidence: Mapping[str, Any]) -> None:
    if not evidence.get("has_evidence"):
        return
    completed = {int(index) for index in evidence.get("completed", [])}
    running = {int(index) for index in evidence.get("running", [])}
    failed = {int(index) for index in evidence.get("failed", [])}
    available_artifacts = {
        _pipeline_stage_artifact_id(_pipeline_stage_unit_id(index))
        for index in completed
    }
    units = [unit for unit in state.get("units", []) if isinstance(unit, dict)]
    for unit in units:
        index = _pipeline_stages_unit_index(unit)
        if index is None:
            continue
        unit_id = _pipeline_stage_unit_id(index)
        artifact_id = _pipeline_stage_artifact_id(unit_id)
        dependency_ids = [
            str(dependency.get("artifact", ""))
            for dependency in unit.get("artifact_dependencies", [])
            if isinstance(dependency, dict) and str(dependency.get("artifact", ""))
        ]
        if index in completed:
            unit["dispatch_status"] = "completed"
            _pipeline_stages_update_operator_ui(
                unit,
                status="completed",
                message=f"{unit_id} is completed according to the latest workflow run log.",
            )
        elif index in failed:
            unit["dispatch_status"] = "failed"
            _pipeline_stages_update_operator_ui(
                unit,
                status="failed",
                message=f"{unit_id} failed in the latest workflow run log.",
            )
        elif index in running:
            unit["dispatch_status"] = "running"
            _pipeline_stages_update_operator_ui(
                unit,
                status="running",
                message=f"{unit_id} is running according to the latest workflow run log.",
            )
        elif all(dependency_id in available_artifacts for dependency_id in dependency_ids):
            unit["dispatch_status"] = "runnable"
            _pipeline_stages_update_operator_ui(
                unit,
                status="runnable",
                message=f"{unit_id} is ready because its project-stage dependencies are satisfied.",
            )
        else:
            missing = [dependency_id for dependency_id in dependency_ids if dependency_id not in available_artifacts]
            unit["dispatch_status"] = "blocked"
            _pipeline_stages_update_operator_ui(
                unit,
                status="blocked",
                message=f"{unit_id} waits for previous project-stage evidence.",
                blocked_artifacts=missing,
            )
        for produced in unit.get("produces", []):
            if isinstance(produced, dict) and produced.get("artifact") == artifact_id:
                produced["status"] = "available" if artifact_id in available_artifacts else "planned"

    _pipeline_stages_set_artifact_statuses(state, available_artifacts)
    source = state.setdefault("source", {})
    if isinstance(source, dict):
        source["execution_sync"] = {
            "has_evidence": True,
            "status": str(evidence.get("last_status", "")),
            "completed_stage_indices": list(evidence.get("completed", [])),
            "running_stage_indices": list(evidence.get("running", [])),
            "failed_stage_indices": list(evidence.get("failed", [])),
            "log_file": str(evidence.get("log_file", "")),
            "sync_token": str(evidence.get("sync_token", "")),
            "stale": bool(evidence.get("stale")),
        }
    provenance = state.setdefault("provenance", {})
    if isinstance(provenance, dict):
        provenance["dispatch_mode"] = "pipeline_stages_log_sync"
        provenance["real_app_execution"] = False
    _pipeline_stages_dag_summary(state)


def _pipeline_stages_state_has_execution_sync(state: Mapping[str, Any]) -> bool:
    source = state.get("source", {})
    if not isinstance(source, Mapping):
        return False
    sync = source.get("execution_sync", {})
    return isinstance(sync, Mapping) and bool(sync.get("has_evidence"))


def _mark_pipeline_stages_state_stale(
    state: dict[str, Any],
    *,
    reason: str,
    previous_digest: str = "",
) -> None:
    for unit in state.get("units", []):
        if not isinstance(unit, dict):
            continue
        unit["dispatch_status"] = "stale"
        _pipeline_stages_update_operator_ui(
            unit,
            status="stale",
            message=reason,
        )
    _pipeline_stages_set_artifact_statuses(state, set(), status="stale")
    state["run_status"] = "stale"
    source = state.setdefault("source", {})
    if isinstance(source, dict):
        source["stale_from_digest"] = True
        source["previous_stages_digest"] = previous_digest
        source["execution_sync"] = {
            "has_evidence": True,
            "status": "stale",
            "completed_stage_indices": [],
            "running_stage_indices": [],
            "failed_stage_indices": [],
            "log_file": "",
            "sync_token": "",
            "stale": True,
            "reason": reason,
        }
    provenance = state.setdefault("provenance", {})
    if isinstance(provenance, dict):
        provenance["dispatch_mode"] = "pipeline_stages_stale_preview"
        provenance["real_app_execution"] = False
    events = state.get("events")
    if not isinstance(events, list):
        events = []
        state["events"] = events
    events.append(
        {
            "timestamp": _global_dag_now_iso(),
            "kind": "run_stale",
            "unit_id": "",
            "from_status": "",
            "to_status": "stale",
            "detail": reason,
        }
    )
    _pipeline_stages_dag_summary(state)


def _pipeline_stages_dag_summary(state: dict[str, Any]) -> dict[str, Any]:
    units = [unit for unit in state.get("units", []) if isinstance(unit, dict)]
    events = state.get("events", [])
    running_ids = [str(unit.get("id", "")) for unit in units if unit.get("dispatch_status") == "running"]
    completed_ids = [str(unit.get("id", "")) for unit in units if unit.get("dispatch_status") == "completed"]
    failed_ids = [str(unit.get("id", "")) for unit in units if unit.get("dispatch_status") == "failed"]
    stale_ids = [str(unit.get("id", "")) for unit in units if unit.get("dispatch_status") == "stale"]
    available_artifacts = sorted(_available_artifact_ids(state))
    summary = {
        "unit_count": len(units),
        "planned_count": sum(1 for unit in units if unit.get("dispatch_status") in {"runnable", "blocked"}),
        "running_count": len(running_ids),
        "completed_count": len(completed_ids),
        "failed_count": len(failed_ids),
        "stale_count": len(stale_ids),
        "runnable_unit_ids": [str(unit.get("id", "")) for unit in units if unit.get("dispatch_status") == "runnable"],
        "blocked_unit_ids": [str(unit.get("id", "")) for unit in units if unit.get("dispatch_status") == "blocked"],
        "running_unit_ids": running_ids,
        "completed_unit_ids": completed_ids,
        "failed_unit_ids": failed_ids,
        "stale_unit_ids": stale_ids,
        "available_artifact_ids": available_artifacts,
        "event_count": len(events) if isinstance(events, list) else 0,
    }
    state["summary"] = summary
    if stale_ids:
        state["run_status"] = "stale"
    elif failed_ids:
        state["run_status"] = "failed"
    elif units and len(completed_ids) == len(units):
        state["run_status"] = "completed"
    elif running_ids or completed_ids:
        state["run_status"] = "running"
    else:
        state["run_status"] = "planned"
    return summary


def _build_pipeline_stages_runner_state(
    env: AgiEnv,
    *,
    stages_file: Path | None,
    pipeline_stages: list[dict[str, Any]],
    now: str | None = None,
) -> dict[str, Any]:
    timestamp = now or _global_dag_now_iso()
    app_name = _active_app_name(env) or "project"
    stages_digest = _pipeline_stages_digest(pipeline_stages)
    units: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    for index, stage in enumerate(pipeline_stages):
        unit_id = _pipeline_stage_unit_id(index)
        artifact_id = _pipeline_stage_artifact_id(unit_id)
        previous_unit_id = _pipeline_stage_unit_id(index - 1) if index else ""
        previous_artifact_id = _pipeline_stage_artifact_id(previous_unit_id) if previous_unit_id else ""
        dependencies = []
        if previous_artifact_id:
            dependencies.append(
                {
                    "artifact": previous_artifact_id,
                    "from": previous_unit_id,
                    "from_app": app_name,
                    "source_path": f"pipeline/{previous_unit_id}.json",
                    "handoff": f"Run after `{previous_unit_id}` completes.",
                }
            )
        status = "runnable" if index == 0 else "blocked"
        blocked_artifacts = [previous_artifact_id] if previous_artifact_id else []
        units.append(
            {
                "id": unit_id,
                "order_index": index,
                "app": app_name,
                "executor": _pipeline_stage_executor_label(stage),
                "plan_status": "planned",
                "plan_runner_status": "lab_stages_preview",
                "dispatch_status": status,
                "depends_on": [previous_unit_id] if previous_unit_id else [],
                "artifact_dependencies": dependencies,
                "produces": [
                    {
                        "artifact": artifact_id,
                        "kind": "pipeline_stage_completion",
                        "path": f"pipeline/{unit_id}.json",
                    }
                ],
                "transitions": [
                    {"from": "runnable", "to": "running", "condition": "operator preview dispatch"},
                    {"from": "running", "to": "completed", "condition": "existing workflow runner completes the stage"},
                ],
                "retry": {
                    "policy": "existing_pipeline_controls",
                    "attempt": 0,
                    "max_attempts": 0,
                    "status": "not_scheduled",
                    "last_error": "",
                    "next_action": "use existing workflow stage controls for execution and retry",
                },
                "partial_rerun": {
                    "policy": "existing_pipeline_controls",
                    "requested": False,
                    "eligible_after_completion": True,
                    "requires_completed_dependencies": [previous_unit_id] if previous_unit_id else [],
                    "artifact_scope": [artifact_id],
                },
                "operator_ui": {
                    "state": "ready_to_dispatch" if status == "runnable" else "blocked",
                    "severity": "info" if status == "runnable" else "warning",
                    "message": (
                        f"{unit_id} is ready for preview."
                        if status == "runnable"
                        else f"{unit_id} waits for `{previous_artifact_id}` from the previous project stage."
                    ),
                    "blocked_by_artifacts": blocked_artifacts,
                },
                "provenance": {
                    "source_plan_schema": "agilab.lab_stages_dag_preview.v1",
                    "source_plan_runner_status": "lab_stages_preview",
                    "source_dag": "project stages",
                    "source_unit_id": unit_id,
                    "source_app": app_name,
                    "pipeline_view": "single_app_lab_stages",
                    "runner_state_mode": "read_only_preview",
                    "planning_mode": "lab_stages_compatibility",
                    "lab_stage_index": index,
                    "lab_stage_model": str(stage.get("M", "") or ""),
                    "lab_stage_summary": _pipeline_stage_purpose(stage, index),
                },
            }
        )
        artifacts.append(
            {
                "artifact": artifact_id,
                "kind": "pipeline_stage_completion",
                "producer": unit_id,
                "status": "planned",
                "path": f"pipeline/{unit_id}.json",
            }
        )
    state = {
        "schema": "agilab.global_pipeline_runner_state.v1",
        "run_id": "project-stages-dag-preview",
        "persistence_format": "json",
        "run_status": "planned",
        "created_at": timestamp,
        "updated_at": timestamp,
        "ok": bool(units),
        "issues": [],
        "source": {
            "dag_path": GLOBAL_DAG_SOURCE_PROJECT_STAGES,
            "source_type": "lab_stages",
            "stages_file": str(stages_file.expanduser()) if stages_file is not None else "",
            "stages_digest": stages_digest,
            "stage_count": len(pipeline_stages),
            "execution_order": [unit["id"] for unit in units],
            "plan_schema": "agilab.lab_stages_dag_preview.v1",
            "plan_runner_status": "lab_stages_preview",
            "runner_state_mode": "read_only_preview",
        },
        "units": units,
        "artifacts": artifacts,
        "events": [
            {
                "timestamp": timestamp,
                "kind": "run_planned",
                "unit_id": "",
                "from_status": "",
                "to_status": "planned",
                "detail": "project lab_stages.toml rendered as a preview-only single-app stage DAG",
            }
        ],
        "provenance": {
            "source_dag": "project stages",
            "source_plan_schema": "agilab.lab_stages_dag_preview.v1",
            "source_runner_state_schema": "agilab.global_pipeline_runner_state.v1",
            "dispatch_mode": "pipeline_stages_preview",
            "real_app_execution": False,
        },
    }
    _pipeline_stages_dag_summary(state)
    return state


def _pipeline_stages_state_matches(
    state: dict[str, Any],
    *,
    stages_file: Path | None,
    pipeline_stages: list[dict[str, Any]],
) -> bool:
    source = state.get("source", {})
    if not isinstance(source, dict) or source.get("source_type") != "lab_stages":
        return False
    expected_stages_file = str(stages_file.expanduser()) if stages_file is not None else ""
    return (
        str(source.get("stages_file", "")) == expected_stages_file
        and str(source.get("stages_digest", "")) == _pipeline_stages_digest(pipeline_stages)
    )


def _write_pipeline_stages_runner_state_with_evidence(
    state_path: Path,
    state: Mapping[str, Any],
    *,
    lab_dir: Path,
    trigger: Mapping[str, Any],
) -> Path:
    written_path = write_runner_state(state_path, state)
    write_workflow_run_evidence(
        state=state,
        state_path=written_path,
        repo_root=_repo_root_for_global_dag(),
        lab_dir=lab_dir,
        dag_path=None,
        trigger=trigger,
    )
    return written_path


def _load_or_create_pipeline_stages_runner_state(
    env: AgiEnv,
    lab_dir: Path,
    *,
    stages_file: Path | None,
    pipeline_stages: list[dict[str, Any]],
    index_page: str = "",
    session_state: Mapping[str, Any] | None = None,
    reset: bool = False,
) -> tuple[dict[str, Any], Path]:
    state_path = lab_dir / ".agilab" / GLOBAL_RUNNER_STATE_FILENAME
    evidence = _pipeline_stages_execution_evidence(
        index_page=index_page,
        session_state=session_state,
        stages_file=stages_file,
        stage_count=len(pipeline_stages),
    )
    if state_path.is_file() and not reset:
        state = load_runner_state(state_path)
        if _pipeline_stages_state_matches(
            state,
            stages_file=stages_file,
            pipeline_stages=pipeline_stages,
        ):
            source = state.get("source", {})
            execution_sync = source.get("execution_sync", {}) if isinstance(source, dict) else {}
            if not evidence.get("has_evidence") or (
                isinstance(execution_sync, dict)
                and str(execution_sync.get("sync_token", "")) == str(evidence.get("sync_token", ""))
            ):
                return state, state_path
        elif _pipeline_stages_state_has_execution_sync(state) and not evidence.get("has_evidence"):
            previous_source = state.get("source", {})
            previous_digest = (
                str(previous_source.get("stages_digest", ""))
                if isinstance(previous_source, dict)
                else ""
            )
            stale_state = _build_pipeline_stages_runner_state(
                env,
                stages_file=stages_file,
                pipeline_stages=pipeline_stages,
            )
            _mark_pipeline_stages_state_stale(
                stale_state,
                reason="lab_stages.toml changed after the last observed workflow run.",
                previous_digest=previous_digest,
            )
            _write_pipeline_stages_runner_state_with_evidence(
                state_path,
                stale_state,
                lab_dir=lab_dir,
                trigger={"surface": "workflow", "action": "project_stages_stale"},
            )
            return stale_state, state_path

    state = _build_pipeline_stages_runner_state(
        env,
        stages_file=stages_file,
        pipeline_stages=pipeline_stages,
    )
    if evidence.get("has_evidence"):
        if evidence.get("stale"):
            _mark_pipeline_stages_state_stale(
                state,
                reason="lab_stages.toml is newer than the latest workflow run log.",
                previous_digest=(
                    str(state.get("source", {}).get("stages_digest", ""))
                    if isinstance(state.get("source"), dict)
                    else ""
                ),
            )
        else:
            _apply_pipeline_stages_execution_evidence(state, evidence)
    _write_pipeline_stages_runner_state_with_evidence(
        state_path,
        state,
        lab_dir=lab_dir,
        trigger={"surface": "workflow", "action": "project_stages_state_written"},
    )
    return state, state_path


def _render_global_runner_state_view(
    *,
    state: dict[str, Any],
    state_path: Path,
    dag_path: Path | None,
    dag_engine: Any,
    repo_root: Path,
    index_page_str: str,
    dag_label_override: str = "",
    run_log_dir: Path | None = None,
    project_stage_snippet_rows: list[dict[str, str]] | None = None,
    distributed_request_preview_rows: list[dict[str, str]] | None = None,
) -> None:
    summary = state.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}
    source = state.get("source", {})
    if not isinstance(source, dict):
        source = {}
    dag_label = dag_label_override or str(source.get("dag_path", "")) or (
        _repo_relative_text(dag_path, repo_root) if dag_path is not None else ""
    )
    if dag_label:
        st.caption(f"Plan path: `{dag_label}`")
    st.caption(f"State file: `{state_path}`")
    real_run_support = dag_engine.real_run_support(state)
    execution_status = _global_dag_execution_status(state, real_run_support)
    _render_global_dag_execution_capability(
        contract_name=dag_label_override or _global_dag_display_name(dag_label, repo_root),
        execution_status=execution_status,
        real_run_support=real_run_support,
    )
    _render_global_dag_readiness(state)
    _render_existing_execution_log(run_log_dir, key_prefix=f"workflow:{index_page_str}:execution")
    _render_workflow_run_evidence(state_path)
    running_col, completed_col, failed_col = st.columns(3)
    running_col.metric("Running", int(summary.get("running_count", 0) or 0))
    completed_col.metric("Completed", int(summary.get("completed_count", 0) or 0))
    failed_col.metric("Failed", int(summary.get("failed_count", 0) or 0))

    dag_dot = _global_dag_dot(state)
    show_graph = bool(
        dag_dot
        and st.checkbox(
            "Show graph",
            key=f"{index_page_str}_global_runner_show_graph",
            help="Show the generated graph if the current screen has enough room to read it.",
        )
    )
    if show_graph:
        st.graphviz_chart(dag_dot, width="stretch")

    workplan_rows = _global_dag_workplan_rows_for_display(state)
    if workplan_rows:
        st.caption("Multi-app plan")
        st.dataframe(workplan_rows, hide_index=True, width="stretch")
    else:
        st.caption(GLOBAL_DAG_EMPTY_STATE)
    _render_project_stage_snippet_preview(
        project_stage_snippet_rows,
        index_page_str=index_page_str,
    )

    artifact_rows = _artifact_handoffs_for_display(state)
    show_artifacts = bool(
        artifact_rows
        and st.checkbox(
            "Show technical output details",
            key=f"{index_page_str}_global_runner_show_artifacts",
            help="Show the output handoffs used behind the plan.",
        )
    )
    if show_artifacts:
        st.caption("Output handoffs")
        st.dataframe(artifact_rows, hide_index=True, width="stretch")

    history_rows = _global_dag_execution_history_rows(state)
    if history_rows:
        st.caption("Execution history")
        st.dataframe(history_rows, hide_index=True, width="stretch")
    else:
        st.caption("Execution history: no step has been started yet.")

    real_run_supported = real_run_support.supported
    if real_run_supported:
        stage_backend = GLOBAL_DAG_STAGE_BACKEND_LOCAL
        distributed_stage_supported = bool(getattr(dag_engine, "distributed_stage_supported", lambda: False)())
        if distributed_stage_supported:
            stage_backend = st.selectbox(
                "Stage backend",
                [GLOBAL_DAG_STAGE_BACKEND_LOCAL, GLOBAL_DAG_STAGE_BACKEND_DISTRIBUTED],
                key=f"{index_page_str}_global_runner_stage_backend",
                format_func=lambda value: GLOBAL_DAG_STAGE_BACKEND_LABELS.get(str(value), str(value)),
                help=(
                    "Choose how ready multi-app DAG stages are submitted. Local contracts run in this "
                    "Streamlit process; distributed backend delegates each ready stage to the configured submitter."
                ),
            )
            if stage_backend == GLOBAL_DAG_STAGE_BACKEND_DISTRIBUTED:
                st.caption("Distributed stage request preview")
                if distributed_request_preview_rows:
                    st.dataframe(distributed_request_preview_rows, hide_index=True, width="stretch")
                else:
                    st.warning(
                        "Distributed backend is selected, but the active ORCHESTRATE cluster settings "
                        "do not provide a complete scheduler, workers, and Workers Data Path request."
                    )
        run_next_col, run_ready_col = st.columns(2)
        with run_next_col:
            run_stage_clicked = action_button(
                run_next_col,
                "Run next stage",
                key=f"{index_page_str}_global_runner_run_next_stage",
                kind="run",
                help=(
                    f"Execute the next ready stage through `{real_run_support.adapter}`. "
                    "Only checked-in DAGs with a controlled adapter marker can run from this view."
                ),
            )
        with run_ready_col:
            run_ready_clicked = action_button(
                run_ready_col,
                "Run ready stages",
                key=f"{index_page_str}_global_runner_run_ready_stages",
                kind="run",
                help=(
                    "Execute every currently ready controlled stage in one batch. "
                    "Independent stages can run concurrently; each stage still owns its app runtime."
                ),
            )
        if run_stage_clicked:
            try:
                result = dag_engine.run_next_controlled_stage(state)
            except Exception as exc:
                st.error("Controlled workflow step execution failed.")
                st.caption("Full diagnostic")
                st.code(str(exc), language="text")
                return
            if result.ok:
                dag_engine.write_state(result.state)
                st.success(result.message)
                st.rerun()
            else:
                st.warning(result.message)
        if run_ready_clicked:
            try:
                result = dag_engine.run_ready_controlled_stages(state, execution_backend=stage_backend)
            except Exception as exc:
                st.error("Controlled DAG batch execution failed.")
                st.caption("Full diagnostic")
                st.code(str(exc), language="text")
                return
            if result.executed_unit_ids or result.failed_unit_ids:
                dag_engine.write_state(result.state)
                if result.ok:
                    st.success(result.message)
                else:
                    st.warning(result.message)
                st.rerun()
            else:
                st.warning(result.message)
    else:
        st.caption(
            "Live runs require an approved checked-in workflow file; other plans stay preview-only."
        )

    provenance = state.get("provenance", {})
    controlled_run_started = (
        bool(provenance.get("controlled_execution") or provenance.get("real_app_execution"))
        if isinstance(provenance, dict)
        else False
    )
    dispatch_disabled = real_run_supported and controlled_run_started
    dispatch_clicked = action_button(
        st,
        "Preview next ready step",
        key=f"{index_page_str}_global_runner_dispatch_next",
        kind="run",
        help=(
            "Mark the next ready stage as running in the preview without executing the app."
            if not dispatch_disabled
            else "Preview is disabled after a controlled live run starts; use Run next ready step."
        ),
        disabled=dispatch_disabled,
    )
    if dispatch_clicked:
        result = dag_engine.dispatch_next_runnable(state)
        if result.ok:
            dag_engine.write_state(result.state)
            st.success(result.message)
            st.rerun()
        else:
            st.warning(result.message)


def _render_global_runner_state_panel(
    env: AgiEnv,
    lab_dir: Path,
    index_page_str: str,
    *,
    pipeline_stages: list[dict[str, Any]] | None = None,
    stages_file: Path | None = None,
) -> None:
    with st.expander("Workflow graph", expanded=True):
        repo_root = _repo_root_for_global_dag()
        default_dag_path = _global_runner_dag_path(env, repo_root)
        scope_key = f"{index_page_str}_pipeline_scope"
        source_key = f"{index_page_str}_global_runner_source"
        app_template_key = f"{index_page_str}_global_runner_app_template"
        library_key = f"{index_page_str}_global_runner_library"
        workspace_key = f"{index_page_str}_global_runner_workspace_dag"
        dag_input_key = f"{index_page_str}_global_runner_dag_path"
        app_template_options = _global_dag_app_template_options(repo_root, _active_app_name(env))
        sample_options = _global_dag_sample_options(repo_root)
        workspace_options = _global_dag_workspace_options(repo_root, lab_dir)
        library_options = [*app_template_options, *sample_options, *workspace_options]
        project_stage_rows = _pipeline_dag_stage_rows(pipeline_stages)
        default_dag_text = (
            _repo_relative_text(default_dag_path, repo_root)
            if default_dag_path is not None
            else ""
        )
        if scope_key not in st.session_state or st.session_state[scope_key] not in PIPELINE_SCOPE_OPTIONS:
            st.session_state[scope_key] = _pipeline_scope_from_source(
                st.session_state.get(source_key),
                bool(project_stage_rows),
            )
        pipeline_scope = compact_choice(
            st,
            "Workflow scope",
            PIPELINE_SCOPE_OPTIONS,
            key=scope_key,
            help=(
                "Use Project workflow for the current lab_stages.toml graph, or Multi-app DAG "
                "for cross-app artifact contracts."
            ),
            inline_limit=2,
        )
        if pipeline_scope == PIPELINE_SCOPE_PROJECT:
            st.session_state[source_key] = GLOBAL_DAG_SOURCE_PROJECT_STAGES
        source_options = (
            [GLOBAL_DAG_SOURCE_PROJECT_STAGES]
            if pipeline_scope == PIPELINE_SCOPE_PROJECT
            else [source for source in GLOBAL_DAG_SOURCE_OPTIONS if source != GLOBAL_DAG_SOURCE_PROJECT_STAGES]
        )
        _apply_global_dag_pending_source_selection(
            index_page_str,
            source_key=source_key,
            app_template_key=app_template_key,
            library_key=library_key,
            workspace_key=workspace_key,
            dag_input_key=dag_input_key,
            app_template_options=app_template_options,
            sample_options=sample_options,
            workspace_options=workspace_options,
            source_options=source_options,
        )
        if source_key not in st.session_state or st.session_state[source_key] not in source_options:
            st.session_state[source_key] = (
                GLOBAL_DAG_SOURCE_PROJECT_STAGES
                if pipeline_scope == PIPELINE_SCOPE_PROJECT
                else _default_multi_app_dag_source(
                    default_dag_text=default_dag_text,
                    app_template_options=app_template_options,
                    sample_options=sample_options,
                    workspace_options=workspace_options,
                )
            )
        if app_template_key not in st.session_state or st.session_state[app_template_key] not in app_template_options:
            st.session_state[app_template_key] = (
                default_dag_text
                if default_dag_text in app_template_options
                else app_template_options[0] if app_template_options else ""
            )
        if library_key not in st.session_state or st.session_state[library_key] not in library_options:
            st.session_state[library_key] = (
                default_dag_text
                if default_dag_text in sample_options
                else sample_options[0] if sample_options else ""
            )
        if workspace_key not in st.session_state or st.session_state[workspace_key] not in workspace_options:
            st.session_state[workspace_key] = workspace_options[0] if workspace_options else ""
        if dag_input_key not in st.session_state:
            st.session_state[dag_input_key] = ""

        save_notice = st.session_state.pop(_global_dag_notice_key(index_page_str), "")
        if save_notice:
            st.success(str(save_notice))

        st.caption("Choose a plan, check what is ready, then run approved templates.")
        dag_source = st.session_state[source_key]
        selected_dag_text = ""
        if dag_source == GLOBAL_DAG_SOURCE_PROJECT_STAGES:
            reset_clicked = action_button(
                st,
                "Reset preview state",
                key=f"{index_page_str}_global_runner_reset",
                kind="reset",
                help="Rebuild the preview runner state from the current project stages.",
            )
            if not project_stage_rows:
                st.info("No project stages are recorded yet.")
            else:
                st.caption(
                    "Read-only compatibility view of the current project stages. "
                    "Use the existing stage controls below for real execution."
                )
            try:
                state, state_path = _load_or_create_pipeline_stages_runner_state(
                    env,
                    lab_dir,
                    stages_file=stages_file,
                    pipeline_stages=project_stage_rows,
                    index_page=index_page_str,
                    session_state=st.session_state,
                    reset=reset_clicked,
                )
            except Exception as exc:
                st.error("Project stages DAG preview is unavailable.")
                st.caption("Full diagnostic")
                st.code(str(exc), language="text")
                return
            _render_global_runner_state_view(
                state=state,
                state_path=state_path,
                dag_path=None,
                dag_engine=_global_dag_engine(repo_root, lab_dir, None, env=env),
                repo_root=repo_root,
                index_page_str=index_page_str,
                dag_label_override=GLOBAL_DAG_SOURCE_PROJECT_STAGES,
                run_log_dir=_workflow_run_log_dir(env),
                project_stage_snippet_rows=_pipeline_stage_snippet_rows(project_stage_rows),
            )
            return
        st.caption(
            "Safety boundary: preview dispatch updates runner state only; it does not claim live app execution."
        )
        st.markdown("**Choose workplan**")
        dag_source = st.selectbox(
            "Workplan source",
            source_options,
            key=source_key,
            help=(
                "Use templates for checked-in executable contracts, samples for guided demos, "
                "workspace drafts for saved edits, or a custom path for an external contract."
            ),
        )
        if dag_source == GLOBAL_DAG_SOURCE_APP_TEMPLATES:
            if not app_template_options:
                st.info("No app workflow template is bundled for this active project yet.")
            selected_dag_text = st.selectbox(
                "App template",
                app_template_options or [""],
                key=app_template_key,
                format_func=lambda value: _global_dag_label(value, repo_root),
                help="Choose an app workflow template bundled with the active project.",
            )
        elif dag_source == GLOBAL_DAG_SOURCE_SAMPLES:
            selected_dag_text = st.selectbox(
                "Sample",
                sample_options or [""],
                key=library_key,
                format_func=lambda value: _global_dag_label(value, repo_root),
                help="Choose a checked-in sample. The UAV queue to relay sample is the only live-run enabled plan.",
            )
        elif dag_source == GLOBAL_DAG_SOURCE_WORKSPACE:
            if not workspace_options:
                st.info("No workspace plan has been saved for this project yet.")
            selected_dag_text = st.selectbox(
                "Saved draft",
                workspace_options or [""],
                key=workspace_key,
                format_func=lambda value: _global_dag_label(value, repo_root),
                help="Choose a plan saved from this project workspace.",
            )
        else:
            selected_dag_text = st.text_input(
                "Custom JSON path",
                key=dag_input_key,
                help=(
                    "Relative paths resolve from the AGILAB checkout root. Custom plans stay preview-only "
                    "until a controlled executor is explicitly implemented."
                ),
            )
        dag_text = str(selected_dag_text or "").strip()
        dag_path = _resolve_global_dag_input(dag_text, repo_root)
        base_payload, load_error = _load_global_dag_payload(dag_path)
        if load_error:
            st.warning(load_error)

        token = _global_dag_source_token(dag_text)
        reset_clicked = action_button(
            st,
            "Reset preview state",
            key=f"{index_page_str}_global_runner_reset",
            kind="reset",
            help="Rebuild the preview state from the selected plan.",
        )
        edit_contract_key = f"{index_page_str}_global_runner_edit_contract_{token}"
        edit_contract = st.checkbox(
            "Edit plan",
            key=edit_contract_key,
            help="Change steps, outputs, inputs, or save a new plan.",
        )
        if not edit_contract:
            try:
                state, state_path, dag_path = _load_or_create_global_runner_state(
                    env,
                    lab_dir,
                    dag_path=dag_path,
                    reset=reset_clicked,
                )
                dag_engine = _global_dag_engine(repo_root, lab_dir, dag_path, env=env)
            except Exception as exc:
                st.error("Multi-app plan preview is unavailable.")
                st.caption("Full diagnostic")
                st.code(str(exc), language="text")
                return

            _render_global_runner_state_view(
                state=state,
                state_path=state_path,
                dag_path=dag_path,
                dag_engine=dag_engine,
                repo_root=repo_root,
                index_page_str=index_page_str,
                run_log_dir=_workflow_run_log_dir(env),
            )
            return

        metadata_keys = {
            "dag_id": f"{index_page_str}_global_runner_dag_id_{token}",
            "label": f"{index_page_str}_global_runner_label_{token}",
            "description": f"{index_page_str}_global_runner_description_{token}",
        }
        st.session_state.setdefault(metadata_keys["dag_id"], str(base_payload.get("dag_id", "")))
        st.session_state.setdefault(metadata_keys["label"], str(base_payload.get("label", "")))
        st.session_state.setdefault(metadata_keys["description"], str(base_payload.get("description", "")))

        st.markdown("**Name this plan**")
        metadata_cols = st.columns([1, 1], gap="medium")
        dag_id = metadata_cols[0].text_input(
            "Plan id",
            key=metadata_keys["dag_id"],
            help="Portable identifier used as the saved draft file name.",
        )
        label = metadata_cols[1].text_input(
            "Readable name",
            key=metadata_keys["label"],
            help="Short label displayed in selectors and reports.",
        )
        description = st.text_area(
            "Purpose",
            key=metadata_keys["description"],
            height=80,
            help="One sentence explaining why these apps are connected.",
        )
        controlled_contract_key = f"{index_page_str}_global_runner_controlled_contract_{token}"
        st.session_state.setdefault(
            controlled_contract_key,
            _global_dag_has_controlled_contract_marker(base_payload),
        )
        controlled_contract_enabled = st.checkbox(
            "Make executable app template",
            key=controlled_contract_key,
            help=(
                "Add the controlled adapter marker. Only checked-in app-owned workflow templates "
                "saved under src/agilab/apps/builtin/<app>/dag_templates can execute from this view."
            ),
        )
        if controlled_contract_enabled:
            st.caption("This draft will be saved with the controlled execution marker.")
        else:
            st.caption("Workspace drafts stay preview-only. Enable this to save a checked-in executable template.")

        tables = _global_dag_editor_tables(base_payload)
        stage_options = _global_dag_stage_options(repo_root, base_payload)
        stage_option_ids = list(stage_options)
        default_stage_ids = [
            row["id"]
            for row in _editor_rows(tables["nodes"], GLOBAL_DAG_NODE_COLUMNS)
            if row["id"] in stage_options
        ]
        if not default_stage_ids:
            default_stage_ids = stage_option_ids[:2]
        table_keys = {
            "stages": f"{index_page_str}_global_runner_stages_{token}",
            "produces": f"{index_page_str}_global_runner_produces_{token}",
            "needs": f"{index_page_str}_global_runner_needs_{token}",
        }
        selected_stage_ids = st.session_state.get(table_keys["stages"])
        if (
            not isinstance(selected_stage_ids, list)
            or any(stage_id not in stage_options for stage_id in selected_stage_ids)
        ):
            st.session_state[table_keys["stages"]] = default_stage_ids

        st.markdown("**Pick steps and outputs**")
        selected_stage_ids = st.multiselect(
            "Steps",
            stage_option_ids,
            key=table_keys["stages"],
            format_func=lambda stage_id: _stage_label(stage_id, stage_options),
            help="Choose app-level steps from checked-in workflow templates and built-in apps.",
        )
        selected_stage_rows = _selected_stage_rows(selected_stage_ids, stage_options)
        nodes_value = selected_stage_rows
        if selected_stage_rows:
            st.dataframe(_workplan_step_rows(selected_stage_rows), hide_index=True, width="stretch")
        else:
            st.warning("Select at least two steps to create a valid multi-app plan.")

        st.markdown("**Outputs each step creates**")
        artifact_options = _global_dag_artifact_options(selected_stage_ids, tables)
        artifact_option_keys = list(artifact_options)
        default_artifact_keys = _default_artifact_keys(artifact_options, tables)
        selected_artifact_keys = st.session_state.get(table_keys["produces"])
        if (
            not isinstance(selected_artifact_keys, list)
            or any(key not in artifact_options for key in selected_artifact_keys)
        ):
            st.session_state[table_keys["produces"]] = default_artifact_keys
        selected_artifact_keys = st.multiselect(
            "Creates",
            artifact_option_keys,
            key=table_keys["produces"],
            format_func=lambda key: _artifact_option_label(key, artifact_options),
            help="Choose outputs created by the selected steps. Other steps can use these outputs.",
        )
        produces_value = _selected_artifact_rows(selected_artifact_keys, artifact_options)
        if produces_value:
            st.dataframe(_workplan_output_rows(produces_value), hide_index=True, width="stretch")
        else:
            st.warning("Select at least one output before adding step inputs.")

        st.markdown("**Inputs each step uses**")
        selected_artifact_options = {
            key: artifact_options[key]
            for key in selected_artifact_keys
            if key in artifact_options
        }
        need_options = _global_dag_handoff_options(
            selected_stage_ids,
            selected_artifact_options,
            base_payload,
        )
        need_option_keys = list(need_options)
        default_need_keys = _default_handoff_keys(need_options, base_payload)
        selected_need_keys = st.session_state.get(table_keys["needs"])
        if (
            not isinstance(selected_need_keys, list)
            or any(key not in need_options for key in selected_need_keys)
        ):
            st.session_state[table_keys["needs"]] = default_need_keys
        selected_need_keys = st.multiselect(
            "Uses",
            need_option_keys,
            key=table_keys["needs"],
            format_func=lambda key: _need_option_label(key, need_options),
            help="Choose which step uses an output from another step. Links are generated automatically.",
        )
        edges_value = _selected_handoff_rows(selected_need_keys, need_options)
        consumes_value = _consumes_rows_from_handoffs(edges_value, selected_artifact_options)
        if edges_value:
            st.dataframe(_workplan_need_rows(edges_value), hide_index=True, width="stretch")
        else:
            st.warning("Select at least one step input to create a cross-app plan.")
        if consumes_value:
            st.caption("Technical input records are created from selected uses.")
            st.dataframe(consumes_value, hide_index=True, width="stretch")

        visual_payload = _global_dag_payload_from_visual_editor(
            base_payload,
            dag_id=dag_id,
            label=label,
            description=description,
            nodes_value=nodes_value,
            produces_value=produces_value,
            consumes_value=consumes_value,
            edges_value=edges_value,
            controlled_contract_execution=controlled_contract_enabled,
        )
        editor_text = json.dumps(visual_payload, indent=2) + "\n"

        show_json_preview = st.checkbox(
            "Show generated JSON",
            key=f"{index_page_str}_global_runner_show_json_preview",
            help="For export or review. Normal editing stays in the fields above.",
        )
        if show_json_preview:
            st.caption("Read-only workflow file generated from the fields above.")
            st.code(editor_text, language="json")
            st.download_button(
                "Download plan JSON",
                data=editor_text,
                file_name=f"{_portable_global_dag_stem(visual_payload, 'global-dag-draft')}.json",
                mime="application/json",
                key=f"{index_page_str}_global_runner_download_json",
            )

        validate_clicked = action_button(
            st,
            "Check plan",
            key=f"{index_page_str}_global_runner_validate",
            kind="check",
            help="Check schema, app names, inputs, and outputs before saving.",
        )
        save_clicked = action_button(
            st,
            "Save as workspace plan",
            key=f"{index_page_str}_global_runner_save_draft",
            kind="save",
            help="Save the plan to this project workspace and rebuild the preview state from it.",
        )
        save_app_template_clicked = False
        if controlled_contract_enabled:
            save_app_template_clicked = action_button(
                st,
                "Save as app template",
                key=f"{index_page_str}_global_runner_save_app_template",
                kind="save",
                help=(
                    "Save a validated controlled workflow under the active app's checked-in "
                    "dag_templates directory so it can execute from this view."
                ),
            )
        if validate_clicked:
            validation_error = _global_dag_validation_error(editor_text, repo_root)
            if validation_error:
                st.error("Plan draft is not valid.")
                st.caption("Validation details")
                st.code(validation_error, language="text")
            else:
                st.success("Plan draft is valid.")

        if save_clicked:
            draft_path, validation_error = _save_global_dag_draft(lab_dir, editor_text, repo_root)
            if validation_error:
                st.error("Plan draft was not saved.")
                st.caption("Validation details")
                st.code(validation_error, language="text")
            else:
                assert draft_path is not None
                dag_path = draft_path
                reset_clicked = True
                notice = f"Saved plan draft to `{draft_path}` and selected it for this preview."
                _queue_global_dag_source_selection(
                    index_page_str,
                    source=GLOBAL_DAG_SOURCE_WORKSPACE,
                    dag_path=draft_path,
                    repo_root=repo_root,
                    notice=notice,
                )
                st.success(notice)
                st.rerun()

        if save_app_template_clicked:
            template_path, validation_error = _save_global_dag_app_template(
                repo_root,
                active_app_name=_active_app_name(env),
                editor_text=editor_text,
            )
            if validation_error:
                st.error("App workflow template was not saved.")
                st.caption("Validation details")
                st.code(validation_error, language="text")
            else:
                assert template_path is not None
                dag_path = template_path
                reset_clicked = True
                notice = f"Saved executable app workflow template to `{template_path}`."
                _queue_global_dag_source_selection(
                    index_page_str,
                    source=GLOBAL_DAG_SOURCE_APP_TEMPLATES,
                    dag_path=template_path,
                    repo_root=repo_root,
                    notice=notice,
                )
                st.success(notice)
                st.rerun()

        try:
            state, state_path, dag_path = _load_or_create_global_runner_state(
                env,
                lab_dir,
                dag_path=dag_path,
                reset=reset_clicked,
            )
            dag_engine = _global_dag_engine(repo_root, lab_dir, dag_path, env=env)
            distributed_preview_rows = _global_dag_distributed_request_preview_rows(env, state, repo_root)
        except Exception as exc:
            st.error("Multi-app DAG preview is unavailable.")
            st.caption("Full diagnostic")
            st.code(str(exc), language="text")
            return

        _render_global_runner_state_view(
            state=state,
            state_path=state_path,
            dag_path=dag_path,
            dag_engine=dag_engine,
            repo_root=repo_root,
            index_page_str=index_page_str,
            run_log_dir=_workflow_run_log_dir(env),
            distributed_request_preview_rows=distributed_preview_rows,
        )


@dataclass(frozen=True)
class PipelineLabDeps:
    load_all_stages: Callable[..., Any]
    save_stage: Callable[..., Any]
    remove_stage: Callable[..., Any]
    force_persist_stage: Callable[..., Any]
    capture_pipeline_snapshot: Callable[..., Any]
    restore_pipeline_snapshot: Callable[..., Any]
    run_all_stages: Callable[..., Any]
    prepare_run_log_file: Callable[..., Any]
    get_run_placeholder: Callable[..., Any]
    push_run_log: Callable[..., Any]
    rerun_fragment_or_app: Callable[..., Any]
    bump_history_revision: Callable[..., Any]
    ask_gpt: Callable[..., Any]
    configure_assistant_engine: Callable[..., Any]
    maybe_autofix_generated_code: Callable[..., Any]
    load_df_cached: Callable[..., Any]
    ensure_safe_service_template: Callable[..., Any]
    inspect_pipeline_run_lock: Callable[..., Any]
    refresh_pipeline_run_lock: Callable[..., Any]
    acquire_pipeline_run_lock: Callable[..., Any]
    release_pipeline_run_lock: Callable[..., Any]
    label_for_stage_runtime: Callable[..., Any]
    python_for_stage: Callable[..., Any]
    python_for_venv: Callable[..., Any]
    stream_run_command: Callable[..., Any]
    run_locked_stage: Callable[..., Any]
    load_pipeline_conceptual_dot: Callable[..., Any]
    render_pipeline_view: Callable[..., Any]
    default_df: str
    safe_service_template_filename: str
    safe_service_template_marker: str


def get_existing_snippets(env: AgiEnv, stages_file: Path, deps: "PipelineLabDeps") -> Dict[str, Path]:
    """Discover reusable snippet files and return a label->path mapping."""
    _ensure_safe_service_template = deps.ensure_safe_service_template
    SAFE_SERVICE_START_TEMPLATE_FILENAME = deps.safe_service_template_filename
    SAFE_SERVICE_START_TEMPLATE_MARKER = deps.safe_service_template_marker

    snippet_file = st.session_state.get("snippet_file")
    safe_service_template = _ensure_safe_service_template(
        env,
        stages_file,
        template_filename=SAFE_SERVICE_START_TEMPLATE_FILENAME,
        marker=SAFE_SERVICE_START_TEMPLATE_MARKER,
        debug_log=logger.debug,
    )

    registry = discover_pipeline_snippets(
        stages_file=stages_file,
        app_name=str(getattr(env, "app", "")),
        explicit_snippet=snippet_file,
        safe_service_template=safe_service_template,
        runenv_root=getattr(env, "runenv", None),
        app_settings_file=getattr(env, "app_settings_file", None),
    )
    stale_snippets = list(registry.stale_snippets)
    if stale_snippets:
        try:
            cleanup_message = stale_snippet_cleanup_message(stale_snippets)
            st.warning(cleanup_message)
            if confirm_button(
                st,
                "Clean stale snippets",
                key=f"clean_stale_snippets_{getattr(env, 'app', 'app')}",
                message=cleanup_message,
                confirm_label="Delete stale snippets",
                help="Delete only old generated AGI_*.py snippets that no longer match this AGILAB core API.",
            ):
                deleted, failed = clean_stale_snippet_files(stale_snippets)
                if deleted:
                    st.success(f"Deleted {len(deleted)} stale generated snippet(s).")
                    toast(st, f"Deleted {len(deleted)} stale snippet(s).", state="success")
                if failed:
                    st.warning(f"Could not delete {len(failed)} stale generated snippet(s).")
                    toast(st, f"Could not delete {len(failed)} stale snippet(s).", state="warning")
        except AttributeError:
            pass

    return registry.as_option_map()

def display_lab_tab(
    lab_dir: Path,
    index_page_str: str,
    stages_file: Path,
    module_path: Path,
    env: AgiEnv,
    deps: "PipelineLabDeps",
) -> None:
    load_all_stages = deps.load_all_stages
    save_stage = deps.save_stage
    remove_stage = deps.remove_stage
    _force_persist_stage = deps.force_persist_stage
    _capture_pipeline_snapshot = deps.capture_pipeline_snapshot
    _restore_pipeline_snapshot = deps.restore_pipeline_snapshot
    run_all_stages = deps.run_all_stages
    _prepare_run_log_file = deps.prepare_run_log_file
    _get_run_placeholder = deps.get_run_placeholder
    _push_run_log = deps.push_run_log
    _rerun_fragment_or_app = deps.rerun_fragment_or_app
    _bump_history_revision = deps.bump_history_revision
    ask_gpt = deps.ask_gpt
    _maybe_autofix_generated_code = deps.maybe_autofix_generated_code
    load_df_cached = deps.load_df_cached
    _inspect_pipeline_run_lock = deps.inspect_pipeline_run_lock
    _refresh_pipeline_run_lock = deps.refresh_pipeline_run_lock
    _acquire_pipeline_run_lock = deps.acquire_pipeline_run_lock
    _release_pipeline_run_lock = deps.release_pipeline_run_lock
    _label_for_stage_runtime = deps.label_for_stage_runtime
    _python_for_stage = deps.python_for_stage
    _python_for_venv = deps.python_for_venv
    _stream_run_command = deps.stream_run_command
    _run_locked_stage = deps.run_locked_stage
    load_pipeline_conceptual_dot = deps.load_pipeline_conceptual_dot
    render_pipeline_view = deps.render_pipeline_view
    DEFAULT_DF = deps.default_df

    def _render_assistant_engine_near_prompt() -> None:
        try:
            deps.configure_assistant_engine(env, container=st)
        except TypeError:
            deps.configure_assistant_engine(env)

    def _render_generation_mode_control(key: str, *, existing_mode: str = "") -> str:
        labels = list(GENERATION_MODE_LABELS.values())
        mode = existing_mode if existing_mode in GENERATION_MODE_LABELS else GENERATION_MODE_SAFE_ACTIONS
        default_label = GENERATION_MODE_LABELS[mode]
        if st.session_state.get(key) not in labels:
            st.session_state[key] = default_label
        selected_label = compact_choice(
            st,
            "Generation mode",
            labels,
            key=key,
            help=(
                "Safe actions asks the model for a validated JSON action contract. "
                "Python snippet is for advanced manual code generation."
            ),
            inline_limit=4,
        )
        selected_mode = GENERATION_MODE_BY_LABEL.get(str(selected_label), GENERATION_MODE_SAFE_ACTIONS)
        if selected_mode == GENERATION_MODE_SAFE_ACTIONS:
            st.caption("Safe actions: model JSON is validated, then AGILAB writes deterministic pandas code.")
        else:
            st.caption("Advanced: raw model Python is saved for review; auto-fix requires an explicit sandbox acknowledgement.")
        return selected_mode

    def _ask_stage_generator(prompt_text: str, df_path: Path, generation_mode: str) -> List[Any]:
        return ask_gpt(
            prompt_text,
            df_path,
            index_page_str,
            env.envars,
            generation_mode=generation_mode,
            load_df_cached=load_df_cached,
        )

    def _generation_extra_fields(answer: List[Any], generation_mode: str) -> Dict[str, Any]:
        if len(answer) > 5 and isinstance(answer[5], dict):
            return dict(answer[5])
        return {
            STAGE_GENERATION_MODE_FIELD: generation_mode,
            STAGE_ACTION_CONTRACT_FIELD: None,
        }

    def _warn_generation_without_code(answer: List[Any]) -> None:
        detail = str(answer[4] if len(answer) > 4 else "").strip()
        if detail:
            st.warning(detail)
        else:
            st.warning("The assistant did not return runnable stage code.")

    # Reset active stage and count to reflect persisted stages
    persisted_stages = load_all_stages(module_path, stages_file, index_page_str) or []
    if not persisted_stages and stages_file.exists():
        try:
            import tomllib
            with open(stages_file, "rb") as f:
                raw = tomllib.load(f)
            module_key = _module_keys(module_path)[0]
            fallback_stages = raw.get(module_key, [])
            if isinstance(fallback_stages, list):
                persisted_stages = [s for s in fallback_stages if _is_displayable_stage(s)]
        except (AttributeError, OSError, TypeError, tomllib.TOMLDecodeError):
            pass
    total_stages = len(persisted_stages)
    safe_prefix = index_page_str.replace("/", "_")
    total_stages_key = f"{safe_prefix}_total_stages"
    prev_total = st.session_state.get(total_stages_key)
    st.session_state[index_page_str][0] = 0
    st.session_state[index_page_str][-1] = total_stages

    sequence_state_key = f"{index_page_str}__run_sequence"
    stored_sequence = st.session_state.get(sequence_state_key)
    if stored_sequence is None:
        stored_sequence = _load_sequence_preferences(module_path, stages_file)
        st.session_state[sequence_state_key] = stored_sequence

    if total_stages == 0:
        if stored_sequence:
            st.session_state[sequence_state_key] = []
            _persist_sequence_preferences(module_path, stages_file, [])
    else:
        current_sequence = [idx for idx in stored_sequence if 0 <= idx < total_stages]
        if not current_sequence:
            current_sequence = list(range(total_stages))
        elif isinstance(prev_total, int) and total_stages > prev_total:
            for idx in range(prev_total, total_stages):
                if idx not in current_sequence:
                    current_sequence.append(idx)
        if current_sequence != st.session_state[sequence_state_key]:
            st.session_state[sequence_state_key] = current_sequence
            _persist_sequence_preferences(module_path, stages_file, current_sequence)

    if prev_total != total_stages:
        st.session_state[total_stages_key] = total_stages
        expander_reset_key = f"{safe_prefix}_expander_open"
        st.session_state[expander_reset_key] = {}

    available_venvs = _valid_runtime_choices(list(get_available_virtualenvs(env)))
    env_active_app = _valid_runtime_path(getattr(env, "active_app", ""))
    manager_runtime = env_active_app
    if env_active_app:
        available_venvs = [env_active_app] + [p for p in available_venvs if p != env_active_app]

    venv_state_key = f"{index_page_str}__venv_map"
    selected_map: Dict[int, str] = st.session_state.setdefault(venv_state_key, {})
    engine_state_key = f"{index_page_str}__engine_map"
    engine_map: Dict[int, str] = st.session_state.setdefault(engine_state_key, {})
    for idx_key, raw_value in list(selected_map.items()):
        normalized_value = _valid_runtime_path(raw_value)
        if normalized_value:
            selected_map[idx_key] = normalized_value
        else:
            selected_map.pop(idx_key, None)

    snippet_option_map = get_existing_snippets(env, stages_file, deps)
    snippet_guidance = _snippet_source_guidance(
        bool(snippet_option_map),
        env.app,
    )
    _render_global_runner_state_panel(
        env,
        lab_dir,
        index_page_str,
        pipeline_stages=persisted_stages,
        stages_file=stages_file,
    )
    stage_source_key = f"{safe_prefix}_new_stage_source"
    source_options = [GENERATE_STAGE_SOURCE] + list(snippet_option_map.keys())
    if st.session_state.get(stage_source_key) not in source_options:
        st.session_state[stage_source_key] = source_options[0]

    # No stages yet: allow creating the first one via Generate code
    if total_stages == 0:
        st.info("No stages recorded yet. Generate your first stage below.")
        st.info(snippet_guidance)
        new_q_key = f"{index_page_str}_new_q"
        new_venv_key = f"{index_page_str}_new_venv"
        first_generation_mode_key = f"{safe_prefix}_first_generation_mode"
        if new_q_key not in st.session_state:
            st.session_state[new_q_key] = ""
        with st.expander("New stage", expanded=True):
            stage_source = compact_choice(
                st,
                "Stage source",
                source_options,
                key=stage_source_key,
                help="Select `Generate stage` to use the code generator, or choose an existing snippet to import as read-only.",
                inline_limit=5,
            )

            if stage_source == GENERATE_STAGE_SOURCE:
                _render_assistant_engine_near_prompt()
                generation_mode = _render_generation_mode_control(first_generation_mode_key)
                st.text_area(
                    "Ask code generator:",
                    key=new_q_key,
                    placeholder="Enter a prompt describing the code you want generated",
                    label_visibility="collapsed",
                )
                venv_labels = ["Use AGILAB environment"] + available_venvs
                selected_new_venv = compact_choice(
                    st,
                    "venv",
                    venv_labels,
                    key=new_venv_key,
                    help="Choose which virtual environment should execute this stage.",
                    inline_limit=4,
                )
                selected_path = "" if selected_new_venv == venv_labels[0] else _valid_runtime_path(selected_new_venv)
                run_new = action_button(
                    st,
                    "Generate code",
                    key=f"{safe_prefix}_add_first_stage_btn",
                    kind="generate",
                )
                if run_new:
                    prompt_text = st.session_state.get(new_q_key, "").strip()
                    if not prompt_text:
                        st.warning("Enter a prompt before generating code.")
                    else:
                        df_path = Path(st.session_state.df_file) if st.session_state.get("df_file") else Path()
                        answer = _ask_stage_generator(prompt_text, df_path, generation_mode)
                        if not str(answer[3] if len(answer) > 3 else "").strip():
                            _warn_generation_without_code(answer)
                            return
                        venv_map = {0: selected_path} if selected_path else {}
                        eng_map = {0: "agi.run" if selected_path else "runpy"}
                        extra_fields = _generation_extra_fields(answer, generation_mode)
                        expander_state_key = f"{safe_prefix}_expander_open"
                        expander_state = st.session_state.setdefault(expander_state_key, {})
                        expander_state[0] = True
                        st.session_state[expander_state_key] = expander_state
                        save_stage(
                            module_path,
                            answer,
                            0,
                            1,
                            stages_file,
                            venv_map=venv_map,
                            engine_map=eng_map,
                            extra_fields=extra_fields,
                        )
                        _bump_history_revision()
                        st.rerun()
            else:
                snippet_path = snippet_option_map.get(stage_source)
                snippet_code = ""
                if snippet_path:
                    try:
                        snippet_code = snippet_path.read_text(encoding="utf-8")
                    except (OSError, UnicodeError) as exc:
                        st.warning(f"Unable to read snippet `{snippet_path}`: {exc}")
                st.text_input(
                    "venv",
                    value=manager_runtime or "Use AGILAB environment",
                    disabled=True,
                    key=f"{safe_prefix}_first_snippet_venv_ro",
                )
                st.caption("Imported snippets use the project manager runtime (read-only).")
                st.caption("Edit a copied version if you need to adjust this snippet.")
                if snippet_path:
                    st.caption(f"Snippet source: `{snippet_path}`")
                st.code(snippet_code or "# Empty snippet", language="python")
                import_new = action_button(
                    st,
                    "Add snippet",
                    key=f"{safe_prefix}_add_first_snippet_btn",
                    kind="add",
                )
                if import_new:
                    if not snippet_code.strip():
                        st.warning("Selected snippet is empty.")
                    else:
                        normalized_code, import_engine, import_runtime = _normalize_imported_orchestrate_snippet(
                            snippet_code,
                            default_runtime=manager_runtime or "",
                        )
                        df_path = Path(st.session_state.df_file) if st.session_state.get("df_file") else Path()
                        question = f"Imported snippet: {snippet_path.name if snippet_path else stage_source}"
                        detail = f"Imported from {snippet_path}" if snippet_path else ""
                        answer = [df_path, question, "snippet", normalized_code, detail]
                        venv_map = {0: import_runtime} if import_runtime else {}
                        eng_map = {0: import_engine}
                        extra_fields = {
                            ORCHESTRATE_LOCKED_STAGE_KEY: True,
                            ORCHESTRATE_LOCKED_SOURCE_KEY: str(snippet_path) if snippet_path else "",
                        }
                        expander_state_key = f"{safe_prefix}_expander_open"
                        expander_state = st.session_state.setdefault(expander_state_key, {})
                        expander_state[0] = True
                        st.session_state[expander_state_key] = expander_state
                        save_stage(
                            module_path,
                            answer,
                            0,
                            1,
                            stages_file,
                            venv_map=venv_map,
                            engine_map=eng_map,
                            extra_fields=extra_fields,
                        )
                        if detail:
                            detail_store = st.session_state.setdefault(f"{index_page_str}__details", {})
                            detail_store[0] = detail
                    _bump_history_revision()
                    st.rerun()
        return

    run_logs_key = f"{index_page_str}__run_logs"
    run_placeholder_key = f"{index_page_str}__run_placeholder"
    delete_undo_key = f"{index_page_str}__undo_delete_snapshot"
    st.session_state.setdefault(run_logs_key, [])
    expander_state_key = f"{safe_prefix}_expander_open"
    expander_state: Dict[int, bool] = st.session_state.setdefault(expander_state_key, {})

    def _build_page_state(*, include_lock: bool = False):
        return build_pipeline_page_state(
            index_page=index_page_str,
            stages_file=stages_file,
            stages=persisted_stages,
            sequence=st.session_state.get(sequence_state_key, []),
            session_state=st.session_state,
            selected_lab=lab_dir,
            env=env,
            deps=PipelinePageStateDeps(
                is_displayable_stage=lambda entry: _is_displayable_stage(dict(entry)),
                is_runnable_stage=lambda entry: _pipeline_stages_module.is_runnable_stage(dict(entry)),
                stage_summary=lambda entry: _stage_summary(dict(entry), width=80),
                stage_label=lambda idx, entry: _stage_label_for_multiselect(idx, dict(entry), env=env),
                find_legacy_agi_run_stages=_pipeline_stages_module.find_legacy_agi_run_stages,
                inspect_pipeline_run_lock=_inspect_pipeline_run_lock if include_lock else None,
            ),
        )

    render_page_state = _build_page_state()

    @st.fragment
    def _render_pipeline_stage_fragment(stage: int, entry: Dict[str, Any]) -> None:
        # Per-stage keys
        q_key = f"{safe_prefix}_q_stage_{stage}"
        code_val_key = f"{safe_prefix}_code_stage_{stage}"
        select_key = f"{safe_prefix}_venv_{stage}"
        rev_key = f"{safe_prefix}_editor_rev_{stage}"
        pending_q_key = f"{safe_prefix}_pending_q_{stage}"
        pending_c_key = f"{safe_prefix}_pending_c_{stage}"
        undo_key = f"{safe_prefix}_undo_{stage}"
        apply_q_key = f"{q_key}_apply_pending"
        apply_c_key = f"{code_val_key}_apply_pending"
        confirm_delete_key = f"{safe_prefix}_confirm_delete_{stage}"

        # Apply any pending updates (set during a previous run-trigger) before rendering widgets.
        pending_q = st.session_state.pop(pending_q_key, None)
        pending_c = st.session_state.pop(pending_c_key, None)
        if pending_q is not None:
            st.session_state[apply_q_key] = pending_q
        if pending_c is not None:
            st.session_state[apply_c_key] = pending_c
        if (pending_q is not None or pending_c is not None) and (q_key in st.session_state or code_val_key in st.session_state):
            st.session_state.pop(q_key, None)
            st.session_state.pop(code_val_key, None)
            _rerun_fragment_or_app()

        initial_q = entry.get("Q", "")
        initial_c = entry.get("C", "")
        apply_q = st.session_state.pop(apply_q_key, None)
        apply_c = st.session_state.pop(apply_c_key, None)
        init_key = f"{safe_prefix}_stage_init_{stage}"
        resync_sig_key = f"{safe_prefix}_editor_resync_sig_{stage}"
        ignore_blank_key = f"{safe_prefix}_ignore_blank_editor_{stage}"
        seeded_c: Optional[str] = None
        if not st.session_state.get(init_key):
            st.session_state[q_key] = apply_q if apply_q is not None else initial_q
            seeded_code = apply_c if apply_c is not None else initial_c
            st.session_state[code_val_key] = seeded_code
            seeded_c = seeded_code or None
            st.session_state[init_key] = True
        else:
            if apply_q is not None or q_key not in st.session_state:
                st.session_state[q_key] = apply_q if apply_q is not None else initial_q
            if apply_c is not None:
                seeded_c = apply_c
                st.session_state[code_val_key] = apply_c
            else:
                current_c = st.session_state.get(code_val_key, "")
                if code_val_key not in st.session_state or (not current_c and initial_c):
                    seeded_c = initial_c
                    st.session_state[code_val_key] = initial_c
        if seeded_c is not None:
            last_sig = st.session_state.get(resync_sig_key)
            if last_sig != seeded_c:
                st.session_state[resync_sig_key] = seeded_c
                st.session_state[ignore_blank_key] = True
                st.session_state[rev_key] = st.session_state.get(rev_key, 0) + 1
        if rev_key not in st.session_state:
            st.session_state[rev_key] = 0
        if undo_key not in st.session_state or not st.session_state[undo_key]:
            initial_snapshot = (entry.get("Q", ""), entry.get("C", ""))
            st.session_state[undo_key] = [initial_snapshot]

        current_path = _valid_runtime_path(selected_map.get(stage, ""))
        if not current_path:
            entry_venv = _valid_runtime_path(entry.get("E", ""))
            if entry_venv:
                selected_map[stage] = entry_venv
                current_path = entry_venv
        venv_labels = ["Use AGILAB environment"] + available_venvs
        if current_path and current_path not in venv_labels:
            venv_labels.append(current_path)

        live_entry = {
            "Q": st.session_state.get(q_key, entry.get("Q", "")),
            "C": st.session_state.get(code_val_key, entry.get("C", "")),
        }
        summary = _stage_summary(live_entry, width=80)
        dirty_key = f"{q_key}_dirty"
        if st.session_state.pop(dirty_key, False):
            _rerun_fragment_or_app()
        expanded_flag = expander_state.get(stage, False)
        title_suffix = summary if summary else "No description yet"
        expander_title = f"{stage + 1} {title_suffix}"
        is_locked_stage = _is_orchestrate_locked_stage(entry)
        locked_source = _orchestrate_snippet_source(entry)
        if is_locked_stage:
            expander_title = f"{stage + 1} 🔒 ORCHESTRATE • {title_suffix}"

        with st.expander(expander_title, expanded=expanded_flag):
            venv_col, _ = st.columns([3, 2], gap="small")
            with venv_col:
                session_label = _valid_runtime_path(st.session_state.get(select_key, ""))
                initial_label = session_label or current_path or ""
                if initial_label and initial_label not in venv_labels:
                    venv_labels.append(initial_label)
                default_label = initial_label or venv_labels[0]
                if select_key not in st.session_state or st.session_state[select_key] not in venv_labels:
                    st.session_state[select_key] = default_label
                selected_label = compact_choice(
                    st,
                    "venv",
                    venv_labels,
                    key=select_key,
                    help="Choose which virtual environment should execute this stage.",
                    disabled=is_locked_stage,
                    inline_limit=4,
                )
                selected_path = "" if selected_label == venv_labels[0] else _valid_runtime_path(selected_label)
                if selected_path:
                    selected_map[stage] = selected_path
                else:
                    selected_map.pop(stage, None)

            computed_engine = "agi.run" if selected_map.get(stage) else "runpy"
            engine_map[stage] = computed_engine
            st.session_state["lab_selected_engine"] = computed_engine

            if is_locked_stage:
                if locked_source:
                    source_name = Path(locked_source).name if locked_source else locked_source
                    if source_name:
                        st.caption(f"Imported from ORCHESTRATE: `{source_name}`.")
                else:
                    st.caption("Imported from ORCHESTRATE.")
                st.caption("This stage is locked. Re-run ORCHESTRATE and re-import it here if you need changes.")
                st.code(st.session_state.get(code_val_key, entry.get("C", "")) or "# Empty snippet", language="python")

                if action_button(
                    st,
                    "Run imported stage",
                    key=f"{safe_prefix}_run_locked_{stage}",
                    kind="run",
                ):
                    _run_locked_stage(
                        env,
                        index_page_str,
                        stages_file,
                        stage,
                        entry,
                        selected_map,
                        engine_map,
                        normalize_runtime_path=normalize_runtime_path,
                        prepare_run_log_file=_prepare_run_log_file,
                        push_run_log=_push_run_log,
                        refresh_pipeline_run_lock=_refresh_pipeline_run_lock,
                        acquire_pipeline_run_lock=_acquire_pipeline_run_lock,
                        release_pipeline_run_lock=_release_pipeline_run_lock,
                        get_run_placeholder=_get_run_placeholder,
                        is_valid_runtime_root=_is_valid_runtime_root,
                        python_for_venv=_python_for_venv,
                        stream_run_command=_stream_run_command,
                        stage_summary=_stage_summary,
                    )

                if st.session_state.get(confirm_delete_key, False):
                    delete_clicked = action_button(
                        st,
                        "Confirm remove",
                        key=f"{safe_prefix}_delete_confirm_{stage}",
                        kind="destructive",
                        type="primary",
                    )
                    cancel_delete_clicked = action_button(
                        st,
                        "Cancel",
                        key=f"{safe_prefix}_delete_cancel_{stage}",
                        kind="cancel",
                    )
                    arm_delete_clicked = False
                else:
                    delete_clicked = False
                    cancel_delete_clicked = False
                    arm_delete_clicked = action_button(
                        st,
                        "Remove",
                        key=f"{safe_prefix}_delete_{stage}",
                        kind="remove",
                    )

                if arm_delete_clicked:
                    st.session_state[confirm_delete_key] = True
                    _rerun_fragment_or_app()
                if cancel_delete_clicked:
                    st.session_state.pop(confirm_delete_key, None)
                    _rerun_fragment_or_app()
                if delete_clicked:
                    result = delete_pipeline_stage_command(
                        session_state=st.session_state,
                        index_page=index_page_str,
                        stage_index=stage,
                        lab_dir=lab_dir,
                        stages_file=stages_file,
                        persisted_stages=persisted_stages,
                        selected_map=selected_map,
                        capture_pipeline_snapshot=_capture_pipeline_snapshot,
                        remove_stage=remove_stage,
                    )
                    if not result.ok:
                        st.warning(result.message)
                    else:
                        st.rerun()
                return

            run_pressed = False
            revert_pressed = False
            save_pressed = False
            delete_clicked = False
            arm_delete_clicked = False
            cancel_delete_clicked = False
            snippet_dict: Optional[Dict[str, Any]] = None
            generation_mode_key = f"{safe_prefix}_generation_mode_{stage}"
            generation_mode = _render_generation_mode_control(
                generation_mode_key,
                existing_mode=str(entry.get(STAGE_GENERATION_MODE_FIELD) or ""),
            )
            st.text_area(
                "Ask code generator:",
                key=q_key,
                placeholder="Enter a prompt describing the code you want generated",
                label_visibility="collapsed",
                on_change=lambda k=q_key: st.session_state.__setitem__(f"{q_key}_dirty", True),
            )
            btn_save, btn_run, btn_revert, btn_delete = st.columns([1, 1, 1, 1], gap="small")
            with btn_save:
                save_pressed = action_button(
                    st,
                    "Save",
                    key=f"{safe_prefix}_save_{stage}",
                    kind="save",
                    type="secondary",
                )
            with btn_run:
                run_pressed = action_button(
                    st,
                    "Gen code",
                    key=f"{safe_prefix}_run_{stage}",
                    kind="generate",
                )
            with btn_revert:
                revert_pressed = action_button(
                    st,
                    "Undo",
                    key=f"{safe_prefix}_revert_{stage}",
                    kind="revert",
                )
            with btn_delete:
                if st.session_state.get(confirm_delete_key, False):
                    delete_clicked = action_button(
                        st,
                        "Confirm remove",
                        key=f"{safe_prefix}_delete_confirm_{stage}",
                        kind="destructive",
                        type="primary",
                    )
                    cancel_delete_clicked = action_button(
                        st,
                        "Cancel",
                        key=f"{safe_prefix}_delete_cancel_{stage}",
                        kind="cancel",
                    )
                else:
                    arm_delete_clicked = action_button(
                        st,
                        "Remove",
                        key=f"{safe_prefix}_delete_{stage}",
                        kind="remove",
                    )

            if arm_delete_clicked:
                st.session_state[confirm_delete_key] = True
                _rerun_fragment_or_app()
            if cancel_delete_clicked:
                st.session_state.pop(confirm_delete_key, None)
                _rerun_fragment_or_app()

            code_text = st.session_state.get(code_val_key, "")
            rev = st.session_state.get(rev_key, 0)
            editor_key = f"{safe_prefix}a{stage}-{rev}"
            snippet_dict = code_editor(
                code_text if code_text.endswith("\n") else code_text + "\n",
                height=(min(30, len(code_text)) if code_text else 100),
                theme="contrast",
                buttons=normalize_custom_buttons(get_custom_buttons()),
                info=get_info_bar(),
                component_props=get_css_text(),
                props={"style": {"borderRadius": "0px 0px 8px 8px"}},
                key=editor_key,
            )

            if snippet_dict and snippet_dict.get("text") is not None:
                normalized_text = _normalize_editor_text(snippet_dict.get("text"))
                if normalized_text == "" and st.session_state.get(ignore_blank_key) and st.session_state.get(code_val_key):
                    st.session_state.pop(ignore_blank_key, None)
                else:
                    st.session_state[code_val_key] = normalized_text
                    st.session_state.pop(ignore_blank_key, None)
            code_current = st.session_state.get(code_val_key, "")

            if revert_pressed:
                undo_stack = st.session_state.get(undo_key, [])
                if len(undo_stack) > 1:
                    undo_stack.pop()
                restored_q, restored_c = undo_stack[-1] if undo_stack else ("", "")
                st.session_state[undo_key] = undo_stack if undo_stack else [(restored_q, restored_c)]
                st.session_state[pending_q_key] = restored_q
                st.session_state[pending_c_key] = restored_c
                save_stage(
                    module_path,
                    [entry.get("D", ""), restored_q, entry.get("M", ""), restored_c],
                    stage,
                    total_stages,
                    stages_file,
                    venv_map=selected_map,
                    engine_map=engine_map,
                )
                _bump_history_revision()
                expander_state[stage] = True
                st.session_state[expander_state_key] = expander_state
                st.session_state[rev_key] = st.session_state.get(rev_key, 0) + 1
                _rerun_fragment_or_app()

            if save_pressed:
                undo_stack = st.session_state.get(undo_key, [])
                undo_stack.append((st.session_state.get(q_key, ""), st.session_state.get(code_val_key, "")))
                st.session_state[undo_key] = undo_stack
                st.session_state[code_val_key] = code_current
                st.session_state[rev_key] = st.session_state.get(rev_key, 0) + 1
                expander_state[stage] = True
                st.session_state[expander_state_key] = expander_state
                save_stage(
                    module_path,
                    [entry.get("D", ""), st.session_state.get(q_key, ""), entry.get("M", ""), code_current],
                    stage,
                    total_stages,
                    stages_file,
                    venv_map=selected_map,
                    engine_map=engine_map,
                )
                _force_persist_stage(
                    module_path,
                    stages_file,
                    stage,
                    {
                        "D": entry.get("D", ""),
                        "Q": st.session_state.get(q_key, ""),
                        "M": entry.get("M", ""),
                        "C": code_current,
                        "E": normalize_runtime_path(selected_map.get(stage, "")),
                        "R": engine_map.get(stage, "") or ("agi.run" if selected_map.get(stage) else "runpy"),
                    },
                )
                st.session_state[pending_q_key] = st.session_state.get(q_key, "")
                st.session_state[pending_c_key] = code_current
                st.session_state.pop(q_key, None)
                st.session_state.pop(code_val_key, None)
                _bump_history_revision()
                _rerun_fragment_or_app()

            overlay_type = snippet_dict.get("type") if snippet_dict else None
            overlay_flag_key = f"{safe_prefix}_overlay_done_{stage}"
            overlay_sig_key = f"{safe_prefix}_overlay_sig_{stage}"
            current_sig = (
                overlay_type,
                snippet_dict.get("text") if snippet_dict else None,
            )
            last_sig = st.session_state.get(overlay_sig_key)
            if overlay_type is None:
                st.session_state.pop(overlay_flag_key, None)
                st.session_state.pop(overlay_sig_key, None)
            elif overlay_type in {"save", "run"} and current_sig == last_sig:
                return
            if snippet_dict and overlay_type == "save":
                if st.session_state.get(overlay_flag_key):
                    st.session_state.pop(overlay_flag_key, None)
                    snippet_dict = None
                else:
                    st.session_state[overlay_flag_key] = True
                    st.session_state[overlay_sig_key] = current_sig
                if snippet_dict is None:
                    return
                undo_stack = st.session_state.get(undo_key, [])
                undo_stack.append((st.session_state.get(q_key, ""), st.session_state.get(code_val_key, "")))
                st.session_state[undo_key] = undo_stack
                code_current = snippet_dict.get("text")
                if code_current is None:
                    code_current = st.session_state.get(code_val_key, "")
                code_current = _normalize_editor_text(code_current)
                st.session_state[code_val_key] = code_current
                st.session_state[rev_key] = st.session_state.get(rev_key, 0) + 1
                expander_state[stage] = True
                st.session_state[expander_state_key] = expander_state
                save_stage(
                    module_path,
                    [entry.get("D", ""), st.session_state.get(q_key, ""), entry.get("M", ""), code_current],
                    stage,
                    total_stages,
                    stages_file,
                    venv_map=selected_map,
                    engine_map=engine_map,
                )
                _force_persist_stage(
                    module_path,
                    stages_file,
                    stage,
                    {
                        "D": entry.get("D", ""),
                        "Q": st.session_state.get(q_key, ""),
                        "M": entry.get("M", ""),
                        "C": code_current,
                        "E": normalize_runtime_path(selected_map.get(stage, "")),
                        "R": engine_map.get(stage, "") or ("agi.run" if selected_map.get(stage) else "runpy"),
                    },
                )
                _bump_history_revision()
                st.session_state[pending_q_key] = st.session_state.get(q_key, "")
                st.session_state[pending_c_key] = code_current
                st.session_state.pop(q_key, None)
                st.session_state.pop(code_val_key, None)
                st.session_state[expander_state_key] = expander_state
                _rerun_fragment_or_app()
            elif snippet_dict and overlay_type == "run":
                if st.session_state.get(overlay_flag_key):
                    st.session_state.pop(overlay_flag_key, None)
                    snippet_dict = None
                else:
                    st.session_state[overlay_flag_key] = True
                    st.session_state[overlay_sig_key] = current_sig
                if snippet_dict is None:
                    return
                code_to_run = snippet_dict.get("text", st.session_state.get(code_val_key, ""))
                venv_root = normalize_runtime_path(selected_map.get(stage, ""))
                entry_runtime_raw = normalize_runtime_path(entry.get("E", ""))
                entry_runtime = entry_runtime_raw if _is_valid_runtime_root(entry_runtime_raw) else ""
                if not venv_root and entry_runtime:
                    venv_root = entry_runtime
                    selected_map[stage] = entry_runtime
                if not venv_root:
                    fallback_venv = normalize_runtime_path(st.session_state.get("lab_selected_venv", ""))
                    if fallback_venv and _is_valid_runtime_root(fallback_venv):
                        venv_root = fallback_venv
                        selected_map[stage] = fallback_venv
                        if fallback_venv not in venv_labels:
                            venv_labels.append(fallback_venv)
                        st.session_state[select_key] = fallback_venv
                entry_engine = str(entry.get("R", "") or "")
                ui_engine = str(engine_map.get(stage) or "")
                engine = _resolve_stage_engine(entry_engine, ui_engine, venv_root)
                if venv_root and engine == "runpy":
                    engine = "agi.run"
                if engine.startswith("agi.") and not venv_root:
                    fallback_runtime = normalize_runtime_path(getattr(env, "active_app", "") or "")
                    if _is_valid_runtime_root(fallback_runtime):
                        venv_root = fallback_runtime
                        st.session_state["lab_selected_venv"] = venv_root
                engine_map[stage] = engine
                if venv_root:
                    st.session_state["lab_selected_venv"] = venv_root
                stored_placeholder = st.session_state.get(run_placeholder_key)
                st.session_state[run_logs_key] = []
                if stored_placeholder is not None:
                    stored_placeholder.caption("Starting overlay run…")
                snippet_file = st.session_state.get("snippet_file")
                if not snippet_file:
                    st.error("Snippet file is not configured. Reload the page and try again.")
                else:
                    log_file_path, log_error = _prepare_run_log_file(
                        index_page_str,
                        env,
                        prefix=f"stage_{stage + 1}",
                    )
                    if log_file_path:
                        _push_run_log(
                            index_page_str,
                            f"Run stage {stage + 1} started… logs will be saved to {log_file_path}",
                            stored_placeholder,
                        )
                    else:
                        _push_run_log(
                            index_page_str,
                            f"Run stage {stage + 1} started… (unable to prepare log file: {log_error})",
                            stored_placeholder,
                        )
                    try:
                        target_base = Path(stages_file).parent.resolve()
                        target_base.mkdir(parents=True, exist_ok=True)
                        run_output = ""
                        summary = _stage_summary({"Q": entry.get("Q", ""), "C": code_to_run})
                        stage_tags = {
                            "agilab.component": "pipeline-stage",
                            "agilab.app": str(getattr(env, "app", "") or ""),
                            "agilab.lab": Path(stages_file).parent.name,
                            "agilab.stage_index": stage + 1,
                            "agilab.engine": engine,
                            "agilab.runtime": venv_root or "",
                            "agilab.summary": summary,
                        }
                        stage_params = {
                            "description": entry.get("D", ""),
                            "question": st.session_state.get(q_key, ""),
                            "model": entry.get("M", ""),
                            "runtime": venv_root or "",
                            "engine": engine,
                        }
                        stage_files: List[Any] = []
                        with start_mlflow_run(
                            env,
                            run_name=f"{getattr(env, 'app', 'agilab')}:{Path(stages_file).parent.name}:stage_{stage + 1}",
                            tags=stage_tags,
                            params=stage_params,
                        ) as stage_tracking:
                            stage_env = build_mlflow_process_env(
                                env,
                                run_id=stage_tracking["run"].info.run_id if stage_tracking else None,
                            )
                            if engine == "runpy":
                                run_output = run_lab(
                                    [entry.get("D", ""), st.session_state.get(q_key, ""), code_to_run],
                                    snippet_file,
                                    env.copilot_file,
                                    env_overrides=stage_env,
                                )
                                stage_files.append(Path(snippet_file))
                            else:
                                script_path = (target_base / "AGI_run.py").resolve()
                                script_path.write_text(wrap_code_with_mlflow_resume(code_to_run))
                                stage_files.append(script_path)
                                python_cmd = _python_for_stage(venv_root, engine=engine, code=code_to_run)
                                run_output = _stream_run_command(
                                    env,
                                    index_page_str,
                                    [str(python_cmd), str(script_path)],
                                    cwd=target_base,
                                    placeholder=stored_placeholder,
                                    extra_env=stage_env,
                                )
                            env_label = _label_for_stage_runtime(venv_root, engine=engine, code=code_to_run)
                            _push_run_log(
                                index_page_str,
                                f"Stage {stage + 1}: engine={engine}, env={env_label}, summary=\"{summary}\"",
                                stored_placeholder,
                            )
                            preview = (run_output or "").strip()
                            if preview:
                                _push_run_log(
                                    index_page_str,
                                    f"Output (stage {stage + 1}):\n{preview}",
                                    stored_placeholder,
                                )
                                if "No such file or directory" in preview:
                                    _push_run_log(
                                        index_page_str,
                                        "Hint: for AGI app stages, input/output data is normally resolved under "
                                        "agi_env.AGI_CLUSTER_SHARE. Check whether the upstream stage created the "
                                        "expected file there before this stage ran.",
                                        stored_placeholder,
                                    )
                            elif engine == "runpy":
                                _push_run_log(
                                    index_page_str,
                                    f"Output (stage {stage + 1}): runpy executed (no captured stdout)",
                                    stored_placeholder,
                                )
                            export_target = st.session_state.get("df_file_out", "")
                            if export_target:
                                stage_files.append(export_target)
                            if stage_tracking:
                                log_mlflow_artifacts(
                                    stage_tracking,
                                    text_artifacts={
                                        f"stage_{stage + 1}/stdout.txt": preview or "",
                                    },
                                    file_artifacts=stage_files,
                                    tags={"agilab.status": "completed"},
                                )
                    finally:
                        st.session_state.pop(f"{index_page_str}__run_log_file", None)

            if run_pressed:
                undo_stack = st.session_state.get(undo_key, [])
                undo_stack.append(
                    (
                        st.session_state.get(q_key, ""),
                        st.session_state.get(code_val_key, ""),
                    )
                )
                st.session_state[undo_key] = undo_stack
                prompt_text = st.session_state.get(q_key, "")
                df_path = (
                    Path(st.session_state.df_file)
                    if st.session_state.get("df_file")
                    else Path()
                )
                answer = _ask_stage_generator(prompt_text, df_path, generation_mode)
                merged_code = None
                code_txt = answer[3] if len(answer) > 3 else ""
                detail_txt = (answer[4] or "").strip() if len(answer) > 4 else ""
                if code_txt:
                    summary_line = f"# {detail_txt}\n" if detail_txt else ""
                    merged_code = f"{summary_line}{code_txt}"
                    if len(answer) > 3:
                        answer[3] = merged_code
                elif generation_mode == GENERATION_MODE_SAFE_ACTIONS:
                    _warn_generation_without_code(answer)
                    return
                else:
                    merged_code = st.session_state.get(code_val_key, "")
                    if len(answer) > 3:
                        answer[3] = merged_code

                if merged_code and generation_mode != GENERATION_MODE_SAFE_ACTIONS:
                    fixed_code, fixed_model, fixed_detail = _maybe_autofix_generated_code(
                        original_request=prompt_text,
                        df_path=df_path,
                        index_page=index_page_str,
                        env=env,
                        merged_code=str(merged_code),
                        model_label=str(answer[2] if len(answer) > 2 else ""),
                        detail=str(answer[4] if len(answer) > 4 else ""),
                        load_df_cached=load_df_cached,
                        push_run_log=_push_run_log,
                        get_run_placeholder=_get_run_placeholder,
                    )
                    merged_code = fixed_code
                    if len(answer) > 3:
                        answer[3] = fixed_code
                    if len(answer) > 2:
                        answer[2] = fixed_model
                    if len(answer) > 4:
                        answer[4] = fixed_detail

                extra_fields = _generation_extra_fields(answer, generation_mode)
                save_stage(
                    module_path,
                    answer,
                    stage,
                    total_stages,
                    stages_file,
                    venv_map=selected_map,
                    engine_map=engine_map,
                    extra_fields=extra_fields,
                )
                if len(answer) > 1:
                    st.session_state[pending_q_key] = answer[1]
                st.session_state[pending_c_key] = (
                    merged_code
                    if merged_code is not None
                    else st.session_state.get(code_val_key, "")
                )
                st.session_state[rev_key] = st.session_state.get(rev_key, 0) + 1

                detail_store = st.session_state.setdefault(
                    f"{index_page_str}__details", {}
                )
                detail = answer[4] if len(answer) > 4 else ""
                if detail:
                    detail_store[stage] = detail
                env_label = (
                    Path(selected_map.get(stage, "")).name
                    if selected_map.get(stage)
                    else "default env"
                )
                summary = _stage_summary(
                    {
                        "Q": answer[1] if len(answer) > 1 else "",
                        "C": answer[4] if len(answer) > 4 else "",
                    }
                )
                _push_run_log(
                    index_page_str,
                    f"Stage {stage + 1}: engine={engine_map.get(stage,'')}, env={env_label}, summary=\"{summary}\"",
                    _get_run_placeholder(index_page_str),
                )
                expander_state[stage] = True
                st.session_state[expander_state_key] = expander_state
                _rerun_fragment_or_app()

            if delete_clicked:
                st.session_state.pop(confirm_delete_key, None)
                result = delete_pipeline_stage_command(
                    session_state=st.session_state,
                    index_page=index_page_str,
                    stage_index=stage,
                    lab_dir=lab_dir,
                    stages_file=stages_file,
                    persisted_stages=persisted_stages,
                    selected_map=selected_map,
                    capture_pipeline_snapshot=_capture_pipeline_snapshot,
                    remove_stage=remove_stage,
                )
                if not result.ok:
                    st.warning(result.message)
                else:
                    st.rerun()

    _conceptual_source, conceptual_dot = load_pipeline_conceptual_dot(env, lab_dir)
    if conceptual_dot:
        with st.expander("Conceptual view", expanded=False):
            st.graphviz_chart(conceptual_dot, width="content")

    render_stages = [persisted_stages[item.index] for item in render_page_state.visible_stages]
    render_pipeline_view(
        render_stages,
        title="Execution view" if conceptual_dot else "Workflow view",
    )

    for visible_stage in render_page_state.visible_stages:
        _render_pipeline_stage_fragment(visible_stage.index, persisted_stages[visible_stage.index])

    # Add-stage expander to append a new stage at the end
    new_q_key = f"{safe_prefix}_new_q"
    new_venv_key = f"{safe_prefix}_new_venv"
    add_generation_mode_key = f"{safe_prefix}_new_generation_mode"
    if new_q_key not in st.session_state:
        st.session_state[new_q_key] = ""
    with st.expander("Add stage", expanded=False):
        st.info(snippet_guidance)
        stage_source = compact_choice(
            st,
            "Stage source",
            source_options,
            key=stage_source_key,
            help="Select `Generate stage` to use the code generator, or choose an existing snippet to import as read-only.",
            inline_limit=5,
        )
        if stage_source == GENERATE_STAGE_SOURCE:
            _render_assistant_engine_near_prompt()
            generation_mode = _render_generation_mode_control(add_generation_mode_key)
            st.text_area(
                "Ask code generator:",
                key=new_q_key,
                placeholder="Enter a prompt describing the code you want generated",
                label_visibility="collapsed",
            )
            venv_labels = ["Use AGILAB environment"] + available_venvs
            selected_new_venv = compact_choice(
                st,
                "venv",
                venv_labels,
                key=new_venv_key,
                help="Choose which virtual environment should execute this stage.",
                inline_limit=4,
            )
            selected_path = "" if selected_new_venv == venv_labels[0] else _valid_runtime_path(selected_new_venv)
            run_new = action_button(st, "Generate code", key=f"{safe_prefix}_add_stage_btn", kind="generate")
            if run_new:
                prompt_text = st.session_state.get(new_q_key, "").strip()
                if prompt_text:
                    df_path = Path(st.session_state.df_file) if st.session_state.get("df_file") else Path()
                    answer = _ask_stage_generator(prompt_text, df_path, generation_mode)
                    merged_code = None
                    code_txt = answer[3] if len(answer) > 3 else ""
                    detail_txt = (answer[4] or "").strip() if len(answer) > 4 else ""
                    if code_txt:
                        summary_line = f"# {detail_txt}\n" if detail_txt else ""
                        merged_code = f"{summary_line}{code_txt}"
                        if len(answer) > 3:
                            answer[3] = merged_code
                    elif generation_mode == GENERATION_MODE_SAFE_ACTIONS:
                        _warn_generation_without_code(answer)
                        return

                    if merged_code and generation_mode != GENERATION_MODE_SAFE_ACTIONS:
                        fixed_code, fixed_model, fixed_detail = _maybe_autofix_generated_code(
                            original_request=prompt_text,
                            df_path=df_path,
                            index_page=index_page_str,
                            env=env,
                            merged_code=str(merged_code),
                            model_label=str(answer[2] if len(answer) > 2 else ""),
                            detail=str(answer[4] if len(answer) > 4 else ""),
                            load_df_cached=load_df_cached,
                            push_run_log=_push_run_log,
                            get_run_placeholder=_get_run_placeholder,
                        )
                        merged_code = fixed_code
                        if len(answer) > 3:
                            answer[3] = fixed_code
                        if len(answer) > 2:
                            answer[2] = fixed_model
                        if len(answer) > 4:
                            answer[4] = fixed_detail
                    new_idx = len(persisted_stages)
                    venv_map = selected_map.copy()
                    engine_map_local = engine_map.copy()
                    if selected_path:
                        venv_map[new_idx] = selected_path
                        engine_map_local[new_idx] = "agi.run"
                    else:
                        engine_map_local[new_idx] = "runpy"
                    extra_fields = _generation_extra_fields(answer, generation_mode)
                    save_stage(
                        module_path,
                        answer,
                        new_idx,
                        new_idx + 1,
                        stages_file,
                        venv_map=venv_map,
                        engine_map=engine_map_local,
                        extra_fields=extra_fields,
                    )
                    detail_store = st.session_state.setdefault(f"{index_page_str}__details", {})
                    detail = answer[4] if len(answer) > 4 else ""
                    if detail:
                        detail_store[new_idx] = detail
                    _bump_history_revision()
                    st.rerun()
                else:
                    st.warning("Enter a prompt before generating code.")
        else:
            snippet_path = snippet_option_map.get(stage_source)
            snippet_code = ""
            if snippet_path:
                try:
                    snippet_code = snippet_path.read_text(encoding="utf-8")
                except (OSError, UnicodeError) as exc:
                    st.warning(f"Unable to read snippet `{snippet_path}`: {exc}")
            st.text_input(
                "venv",
                value=manager_runtime or "Use AGILAB environment",
                disabled=True,
                key=f"{safe_prefix}_add_snippet_venv_ro",
            )
            st.caption("Imported snippets use the project manager runtime (read-only).")
            st.caption("Edit a copied version if you need to adjust this snippet.")
            if snippet_path:
                st.caption(f"Snippet source: `{snippet_path}`")
            st.code(snippet_code or "# Empty snippet", language="python")
            import_new = action_button(
                st,
                "Add snippet",
                key=f"{safe_prefix}_add_stage_snippet_btn",
                kind="add",
            )
            if import_new:
                if not snippet_code.strip():
                    st.warning("Selected snippet is empty.")
                else:
                    normalized_code, import_engine, import_runtime = _normalize_imported_orchestrate_snippet(
                        snippet_code,
                        default_runtime=manager_runtime or "",
                    )
                    df_path = Path(st.session_state.df_file) if st.session_state.get("df_file") else Path()
                    new_idx = len(persisted_stages)
                    question = f"Imported snippet: {snippet_path.name if snippet_path else stage_source}"
                    detail = f"Imported from {snippet_path}" if snippet_path else ""
                    answer = [df_path, question, "snippet", normalized_code, detail]
                    venv_map = selected_map.copy()
                    engine_map_local = engine_map.copy()
                    if import_runtime:
                        venv_map[new_idx] = import_runtime
                    else:
                        venv_map.pop(new_idx, None)
                    engine_map_local[new_idx] = import_engine
                    extra_fields = {
                        ORCHESTRATE_LOCKED_STAGE_KEY: True,
                        ORCHESTRATE_LOCKED_SOURCE_KEY: str(snippet_path) if snippet_path else "",
                    }
                    save_stage(
                        module_path,
                        answer,
                        new_idx,
                        new_idx + 1,
                        stages_file,
                        venv_map=venv_map,
                        engine_map=engine_map_local,
                        extra_fields=extra_fields,
                    )
                    if detail:
                        detail_store = st.session_state.setdefault(f"{index_page_str}__details", {})
                        detail_store[new_idx] = detail
                    _bump_history_revision()
                    st.rerun()

    sequence_state_key = f"{index_page_str}__run_sequence"
    sequence_widget_key = f"{safe_prefix}_run_sequence_widget"
    if total_stages > 0:
        sequence_options = [item.index for item in render_page_state.visible_stages]
        stored_sequence = [idx for idx in st.session_state.get(sequence_state_key, sequence_options) if idx in sequence_options]
        stored_sequence = stored_sequence or sequence_options
        st.session_state[sequence_state_key] = stored_sequence
        if sequence_widget_key not in st.session_state:
            st.session_state[sequence_widget_key] = stored_sequence
        else:
            st.session_state[sequence_widget_key] = [
                idx for idx in st.session_state[sequence_widget_key] if idx in sequence_options
            ]
            if not st.session_state[sequence_widget_key]:
                st.session_state[sequence_widget_key] = stored_sequence

        def _format_sequence_option(idx: int) -> str:
            return _stage_label_for_multiselect(idx, persisted_stages[idx], env=env)

        selected_sequence = st.multiselect(
            "Execution sequence",
            options=sequence_options,
            key=sequence_widget_key,
            format_func=_format_sequence_option,
            help="Select which stages to run. They execute in the order shown.",
        )
        sanitized_selection = [idx for idx in selected_sequence if idx in sequence_options]
        final_sequence = sanitized_selection or sequence_options
        if st.session_state.get(sequence_state_key) != final_sequence:
            st.session_state[sequence_state_key] = final_sequence
            _persist_sequence_preferences(module_path, stages_file, final_sequence)

    page_state = _build_page_state(include_lock=True)
    if page_state.stale_stage_refs and page_state.run_disabled_reason:
        st.warning(page_state.run_disabled_reason)

    lock_state = page_state.lock_state
    if lock_state:
        owner_text = str(lock_state.get("owner_text") or "unknown owner")
        stale_reason = lock_state.get("stale_reason")
        if stale_reason:
            st.info(
                f"Workflow lock detected for this app, but it looks stale: {owner_text}. "
                f"Reason: {stale_reason}."
            )
        else:
            st.warning(
                f"Workflow lock detected for this app: {owner_text}. "
                "Use force unlock only if the previous run was interrupted."
            )

    force_run_clicked = False
    force_run_arm_clicked = False
    force_run_cancel_clicked = False
    force_run_confirm_key = f"{index_page_str}_confirm_force_run"
    run_col, force_col = st.columns(2)
    with run_col:
        run_blocked_reason = page_state.blocked_actions.get(
            PipelineAction.RUN_PIPELINE,
            "",
        )
        run_all_clicked = action_button(
            st,
            "Run workflow",
            key=f"{index_page_str}_run_all",
            kind="run",
            help=run_blocked_reason or "Execute every stage sequentially using its saved virtual environment.",
            disabled=PipelineAction.RUN_PIPELINE not in page_state.available_actions,
        )
    with force_col:
        if lock_state:
            force_blocked_reason = page_state.blocked_actions.get(
                PipelineAction.FORCE_RUN,
                "",
            )
            if lock_state.get("is_stale"):
                force_run_clicked = action_button(
                    st,
                    "Clear stale lock and run",
                    key=f"{index_page_str}_force_run_stale",
                    kind="run",
                    help=force_blocked_reason or "Remove the stale workflow lock and start a new run.",
                    disabled=PipelineAction.FORCE_RUN not in page_state.available_actions,
                )
            elif st.session_state.get(force_run_confirm_key, False):
                force_run_clicked = action_button(
                    st,
                    "Confirm force unlock",
                    key=f"{index_page_str}_force_run_confirm",
                    kind="run",
                    help=force_blocked_reason
                    or "Remove the current lock and start a new run. Use this only if the previous run is gone.",
                    disabled=PipelineAction.FORCE_RUN not in page_state.available_actions,
                )
            else:
                force_run_arm_clicked = action_button(
                    st,
                    "Force unlock and run",
                    key=f"{index_page_str}_force_run_arm",
                    kind="destructive",
                    help=force_blocked_reason
                    or "Use only when a previous workflow run was interrupted and left a lock behind.",
                    disabled=PipelineAction.FORCE_RUN not in page_state.available_actions,
                )

    if run_all_clicked and PipelineAction.RUN_PIPELINE not in page_state.available_actions:
        st.warning(
            page_state.blocked_actions.get(
                PipelineAction.RUN_PIPELINE,
                "Workflow cannot run in the current state.",
            )
        )
        run_all_clicked = False
    if force_run_clicked and PipelineAction.FORCE_RUN not in page_state.available_actions:
        st.warning(
            page_state.blocked_actions.get(
                PipelineAction.FORCE_RUN,
                "Workflow cannot be force-run in the current state.",
            )
        )
        force_run_clicked = False

    if force_run_arm_clicked:
        st.session_state[force_run_confirm_key] = True
        st.rerun()

    if st.session_state.get(force_run_confirm_key, False) and not (force_run_clicked or force_run_arm_clicked):
        force_run_cancel_clicked = action_button(
            st,
            "Cancel force unlock",
            key=f"{index_page_str}_force_run_cancel",
            kind="cancel",
        )
    if force_run_cancel_clicked:
        st.session_state.pop(force_run_confirm_key, None)
        st.rerun()

    st.divider()

    delete_all_col, cancel_col = st.columns(2)
    delete_all_clicked = False
    arm_delete_all_clicked = False
    cancel_delete_all_clicked = False
    delete_all_confirm_key = f"{index_page_str}_confirm_delete_all"
    with delete_all_col:
        if st.session_state.get(delete_all_confirm_key, False):
            delete_all_clicked = action_button(
                st,
                "Confirm delete",
                key=f"{index_page_str}_delete_all_confirm",
                help="Permanently remove every stage in this project.",
                kind="destructive",
                type="primary",
            )
        else:
            arm_delete_all_clicked = action_button(
                st,
                "Delete all",
                key=f"{index_page_str}_delete_all",
                help="Remove every stage in this project.",
                kind="delete",
            )
    with cancel_col:
        if st.session_state.get(delete_all_confirm_key, False):
            cancel_delete_all_clicked = action_button(
                st,
                "Cancel",
                key=f"{index_page_str}_delete_all_cancel",
                kind="cancel",
            )

    if arm_delete_all_clicked:
        st.session_state[delete_all_confirm_key] = True
        st.rerun()
    if cancel_delete_all_clicked:
        st.session_state.pop(delete_all_confirm_key, None)
        st.rerun()

    undo_delete_clicked = False
    undo_payload = st.session_state.get(delete_undo_key)
    if isinstance(undo_payload, dict) and isinstance(undo_payload.get("stages"), list):
        undo_label = str(undo_payload.get("label", "last delete"))
        undo_delete_clicked = action_button(
            st,
            "Undo delete",
            key=f"{index_page_str}_undo_delete",
            help=f"Restore the workflow state before the latest delete action ({undo_label}).",
            kind="revert",
        )

    if undo_delete_clicked:
        result = undo_pipeline_delete_command(
            session_state=st.session_state,
            index_page=index_page_str,
            module_path=module_path,
            stages_file=stages_file,
            sequence_widget_key=sequence_widget_key,
            restore_pipeline_snapshot=_restore_pipeline_snapshot,
        )
        if not result.ok:
            st.error(result.message)
        else:
            st.success(result.message)
            st.rerun()

    if run_all_clicked or force_run_clicked:
        requested_action = PipelineAction.FORCE_RUN if force_run_clicked else PipelineAction.RUN_PIPELINE
        start_result = start_pipeline_run_command(
            page_state=page_state,
            requested_action=requested_action,
            session_state=st.session_state,
            env=env,
            prepare_run_log_file=_prepare_run_log_file,
            get_run_placeholder=_get_run_placeholder,
            push_run_log=_push_run_log,
            force_confirm_key=force_run_confirm_key,
        )
        if not start_result.ok:
            st.warning(start_result.message)
            st.rerun()
            return
        run_placeholder = start_result.details.get("log_placeholder")
        # Collapse all stage expanders after running the pipeline
        st.session_state[expander_state_key] = {}
        try:
            with status_container(st, "Running workflow...", state="running", expanded=True) as run_status:
                try:
                    run_all_stages(
                        lab_dir,
                        index_page_str,
                        stages_file,
                        module_path,
                        env,
                        log_placeholder=run_placeholder,
                        force_lock_clear=bool(start_result.details.get("force_lock_clear")),
                    )
                except Exception:
                    finish_result = finish_pipeline_run_command(
                        session_state=st.session_state,
                        index_page=index_page_str,
                        succeeded=False,
                    )
                    record_action_history(
                        st.session_state,
                        page_label="WORKFLOW",
                        env=env,
                        title="Workflow run failed",
                        status="failed",
                        detail=finish_result.message,
                        artifact=start_result.details.get("log_file_path", ""),
                    )
                    run_status.update(label=finish_result.message, state="error", expanded=True)
                    toast(st, finish_result.message, state="error")
                    raise
                else:
                    finish_result = finish_pipeline_run_command(
                        session_state=st.session_state,
                        index_page=index_page_str,
                        succeeded=True,
                        message="Workflow run finished. Inspect Run logs.",
                    )
                    record_action_history(
                        st.session_state,
                        page_label="WORKFLOW",
                        env=env,
                        title="Workflow run finished",
                        status="done",
                        detail=finish_result.message,
                        artifact=start_result.details.get("log_file_path", ""),
                    )
                    run_status.update(label=finish_result.message, state="complete", expanded=False)
                    toast(st, finish_result.message, state="success")
        finally:
            st.session_state.pop(f"{index_page_str}__run_log_file", None)
        st.rerun()

    if delete_all_clicked:
        result = delete_all_pipeline_stages_command(
            session_state=st.session_state,
            index_page=index_page_str,
            lab_dir=lab_dir,
            module_path=module_path,
            stages_file=stages_file,
            persisted_stages=persisted_stages,
            sequence_widget_key=sequence_widget_key,
            capture_pipeline_snapshot=_capture_pipeline_snapshot,
            remove_stage=remove_stage,
            bump_history_revision=_bump_history_revision,
            persist_sequence_preferences=_persist_sequence_preferences,
            confirm_key=delete_all_confirm_key,
        )
        if not result.ok:
            st.warning(result.message)
        else:
            st.rerun()

    if st.session_state.pop("_experiment_reload_required", False):
        st.session_state.pop("loaded_df", None)
        st.rerun()

    if "loaded_df" not in st.session_state:
        df_source = st.session_state.get("df_file")
        st.session_state["loaded_df"] = (
            load_df_cached(Path(df_source), with_index=False) if df_source else None
        )
    dag_based_app = is_dag_based_app(env, index_page_str)
    if dag_based_app and not st.session_state.get("df_file"):
        st.session_state["loaded_df"] = None
    loaded_df = st.session_state["loaded_df"]
    has_loaded_dataframe = isinstance(loaded_df, pd.DataFrame) and not loaded_df.empty
    dataframe_output_visible = (not dag_based_app) or bool(st.session_state.get("df_file"))
    log_page_state = _build_page_state()
    logs = list(log_page_state.run_logs)
    log_body = "\n".join(logs)
    last_log_file = log_page_state.last_run_log_file
    last_run_status = st.session_state.get(f"{index_page_str}__last_run_status")
    latest_status = last_run_status or ("done" if last_log_file or log_body else "waiting")
    pipeline_artifacts: list[dict[str, Any]] = [
        {"label": "Stage contract", "path": stages_file, "kind": "toml", "preview": False},
        {"label": "Run log", "path": last_log_file, "kind": "log"},
    ]
    if dataframe_output_visible:
        pipeline_artifacts.insert(
            0,
            {"label": "Dataframe", "path": st.session_state.get("df_file"), "kind": "dataframe", "preview": False},
        )
    for pipeline_view_path in (lab_dir / "pipeline_view.json", lab_dir / "pipeline_view.dot"):
        if pipeline_view_path.is_file():
            pipeline_artifacts.append(
                {
                    "label": pipeline_view_path.name,
                    "path": pipeline_view_path,
                    "kind": pipeline_view_path.suffix.lower().lstrip("."),
                }
            )

    timeline_items: list[dict[str, Any]] = [
        {
            "label": "Define stages",
            "state": "done" if total_stages else "waiting",
            "detail": f"{total_stages} stage(s)",
        },
        {
            "label": "Run workflow",
            "state": "ready" if page_state.can_run else "blocked",
            "detail": page_state.run_disabled_reason or "",
        },
    ]
    if dataframe_output_visible:
        timeline_items.append(
            {
                "label": "Load dataframe",
                "state": "done" if has_loaded_dataframe else "waiting",
                "detail": st.session_state.get("df_file") or "",
            }
        )
    timeline_items.append(
        {
            "label": "Inspect artifacts",
            "state": "done" if last_log_file or st.session_state.get("df_file") else "waiting",
            "detail": last_log_file or "",
        }
    )
    render_workflow_timeline(st, items=tuple(timeline_items))
    render_latest_run_card(
        st,
        status=latest_status,
        output_path=st.session_state.get("df_file") if dataframe_output_visible else None,
        log_path=last_log_file,
        key_prefix=f"pipeline:{index_page_str}",
    )
    render_artifact_drawer(
        st,
        artifacts=pipeline_artifacts,
        key_prefix=f"pipeline:{index_page_str}",
    )
    render_action_history(
        st,
        session_state=st.session_state,
        page_label="WORKFLOW",
        env=env,
    )
    if dataframe_output_visible:
        render_latest_outputs(
            st,
            source_path=st.session_state.get("df_file"),
            dataframe=loaded_df,
            key_prefix=f"pipeline:{index_page_str}",
        )
    if has_loaded_dataframe:
        render_dataframe_preview(
            loaded_df,
            truncation_label="WORKFLOW preview limited",
        )
    elif dataframe_output_visible:
        empty_state(
            st,
            "No data loaded yet.",
            body=f"Generate and execute a stage so the latest {DEFAULT_DF} appears under the Dataframe selector.",
        )
    elif dag_based_app:
        st.caption("This DAG workflow tracks stage contracts, workplan state, and run logs instead of a dataframe export.")

    with st.expander("Run logs", expanded=True):
        clear_logs = render_log_actions(
            st,
            body=log_body,
            download_key=f"{index_page_str}__download_logs_global",
            file_name=f"{index_page_str}_workflow.log",
            clear_key=f"{index_page_str}__clear_logs_global",
        )
        if clear_logs:
            result = clear_pipeline_run_logs(st.session_state, index_page_str)
            if result.ok:
                record_action_history(
                    st.session_state,
                    page_label="WORKFLOW",
                    env=env,
                    title="Workflow logs cleared",
                    status="info",
                    detail=result.message,
                )
                toast(st, result.message, state="info")
            else:
                st.warning(result.message)
            log_page_state = _build_page_state()
            logs = list(log_page_state.run_logs)
            log_body = "\n".join(logs)
            last_log_file = log_page_state.last_run_log_file
        log_placeholder = st.empty()
        st.session_state[run_placeholder_key] = log_placeholder
        if last_log_file:
            st.caption(f"Most recent run log: {last_log_file}")
        source = f"WORKFLOW {last_log_file}" if last_log_file else "WORKFLOW"
        render_pinnable_code_editor(
            st,
            code_editor,
            f"pipeline_run_logs:{index_page_str}",
            title=f"Workflow logs: {getattr(env, 'app', None) or index_page_str}",
            body=log_body,
            key=f"{index_page_str}__run_logs_editor",
            body_format="code",
            language="text",
            source=source,
            empty_message="No runs recorded yet.",
            info_name="Run logs",
            theme="dark",
        )
