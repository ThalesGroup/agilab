import importlib.util
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

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

_pipeline_steps_module = import_agilab_module(
    "agilab.pipeline_steps",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "pipeline_steps.py",
    fallback_name="agilab_pipeline_steps_fallback",
)
ORCHESTRATE_LOCKED_SOURCE_KEY = _pipeline_steps_module.ORCHESTRATE_LOCKED_SOURCE_KEY
ORCHESTRATE_LOCKED_STEP_KEY = _pipeline_steps_module.ORCHESTRATE_LOCKED_STEP_KEY
get_available_virtualenvs = _pipeline_steps_module.get_available_virtualenvs
_is_displayable_step = _pipeline_steps_module.is_displayable_step
_is_orchestrate_locked_step = _pipeline_steps_module.is_orchestrate_locked_step
_load_sequence_preferences = _pipeline_steps_module.load_sequence_preferences
_module_keys = _pipeline_steps_module.module_keys
_normalize_imported_orchestrate_snippet = _pipeline_steps_module.normalize_imported_orchestrate_snippet
normalize_runtime_path = _pipeline_steps_module.normalize_runtime_path
_orchestrate_snippet_source = _pipeline_steps_module.orchestrate_snippet_source
_persist_sequence_preferences = _pipeline_steps_module.persist_sequence_preferences
_snippet_source_guidance = _pipeline_steps_module.snippet_source_guidance
_step_label_for_multiselect = _pipeline_steps_module.step_label_for_multiselect
_step_summary = _pipeline_steps_module.step_summary

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
delete_all_pipeline_steps_command = _pipeline_page_state_module.delete_all_pipeline_steps_command
delete_pipeline_step_command = _pipeline_page_state_module.delete_pipeline_step_command
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
render_log_actions = _workflow_ui_module.render_log_actions
render_latest_outputs = _workflow_ui_module.render_latest_outputs

_pipeline_runtime_module = import_agilab_module(
    "agilab.pipeline_runtime",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "pipeline_runtime.py",
    fallback_name="agilab_pipeline_runtime_fallback",
)
build_mlflow_process_env = _pipeline_runtime_module.build_mlflow_process_env
_is_valid_runtime_root = _pipeline_runtime_module.is_valid_runtime_root
_label_for_step_runtime = _pipeline_runtime_module.label_for_step_runtime
log_mlflow_artifacts = _pipeline_runtime_module.log_mlflow_artifacts
_python_for_step = _pipeline_runtime_module.python_for_step
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

_global_runner_state_module = import_agilab_module(
    "agilab.global_pipeline_runner_state",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "global_pipeline_runner_state.py",
    fallback_name="agilab_global_pipeline_runner_state_fallback",
)
dispatch_next_runnable = _global_runner_state_module.dispatch_next_runnable
load_runner_state = _global_runner_state_module.load_runner_state
persist_runner_state = _global_runner_state_module.persist_runner_state
write_runner_state = _global_runner_state_module.write_runner_state

logger = logging.getLogger(__name__)
GLOBAL_RUNNER_STATE_FILENAME = "runner_state.json"
GLOBAL_DAG_SAMPLE_RELATIVE_PATH = Path("docs/source/data/multi_app_dag_sample.json")
GLOBAL_DAG_FLIGHT_SAMPLE_RELATIVE_PATH = Path("docs/source/data/multi_app_dag_flight_sample.json")


def _normalize_editor_text(raw: Optional[str]) -> str:
    if raw is None:
        return ""
    text = str(raw)
    return text if text.strip() else ""


def _resolve_step_engine(entry_engine: str, ui_engine: str, venv_root: str) -> str:
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
    app_name = Path(str(getattr(env, "app", "") or getattr(env, "target", ""))).name
    preferred = (
        GLOBAL_DAG_FLIGHT_SAMPLE_RELATIVE_PATH
        if app_name in {"flight", "flight_project"}
        else GLOBAL_DAG_SAMPLE_RELATIVE_PATH
    )
    preferred_path = repo_root / preferred
    if preferred_path.is_file():
        return preferred_path
    fallback_path = repo_root / GLOBAL_DAG_SAMPLE_RELATIVE_PATH
    return fallback_path if fallback_path.is_file() else None


def _global_runner_state_path(lab_dir: Path) -> Path:
    return lab_dir / ".agilab" / GLOBAL_RUNNER_STATE_FILENAME


def _load_or_create_global_runner_state(env: AgiEnv, lab_dir: Path) -> tuple[dict[str, Any], Path, Path | None]:
    repo_root = _repo_root_for_global_dag()
    dag_path = _global_runner_dag_path(env, repo_root)
    state_path = _global_runner_state_path(lab_dir)
    if state_path.is_file():
        return load_runner_state(state_path), state_path, dag_path
    proof = persist_runner_state(
        repo_root=repo_root,
        output_path=state_path,
        dag_path=dag_path,
    )
    return proof.runner_state, state_path, dag_path


def _state_units_for_display(state: Dict[str, Any]) -> list[dict[str, str]]:
    units = state.get("units", [])
    if not isinstance(units, list):
        return []
    rows: list[dict[str, str]] = []
    for unit in units:
        if not isinstance(unit, dict):
            continue
        rows.append(
            {
                "unit": str(unit.get("id", "")),
                "app": str(unit.get("app", "")),
                "status": str(unit.get("dispatch_status", "")),
                "depends_on": ", ".join(str(item) for item in unit.get("depends_on", []) if str(item)),
            }
        )
    return rows


def _render_global_runner_state_panel(env: AgiEnv, lab_dir: Path, index_page_str: str) -> None:
    try:
        state, state_path, dag_path = _load_or_create_global_runner_state(env, lab_dir)
    except Exception as exc:
        st.caption(f"Global DAG runner preview is unavailable: {exc}")
        return

    summary = state.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}
    with st.expander("Global DAG runner", expanded=False):
        st.caption("Operator preview only: dispatch changes state, but does not execute apps or synthesize artifacts.")
        if dag_path is not None:
            st.caption(f"DAG contract: `{dag_path}`")
        st.caption(f"State file: `{state_path}`")
        planned_col, running_col, completed_col, failed_col = st.columns(4)
        planned_col.metric("Planned", int(summary.get("planned_count", 0) or 0))
        running_col.metric("Running", int(summary.get("running_count", 0) or 0))
        completed_col.metric("Completed", int(summary.get("completed_count", 0) or 0))
        failed_col.metric("Failed", int(summary.get("failed_count", 0) or 0))

        rows = _state_units_for_display(state)
        if rows:
            st.dataframe(rows, hide_index=True, width="stretch")
        else:
            st.caption("No global DAG units are available.")

        dispatch_clicked = action_button(
            st,
            "Dispatch next runnable",
            key=f"{index_page_str}_global_runner_dispatch_next",
            kind="run",
            help="Move the next runnable global DAG unit to running state without executing the app.",
        )
        if dispatch_clicked:
            result = dispatch_next_runnable(state)
            if result.ok:
                write_runner_state(state_path, result.state)
                st.success(result.message)
                st.rerun()
            else:
                st.warning(result.message)


@dataclass(frozen=True)
class PipelineLabDeps:
    load_all_steps: Callable[..., Any]
    save_step: Callable[..., Any]
    remove_step: Callable[..., Any]
    force_persist_step: Callable[..., Any]
    capture_pipeline_snapshot: Callable[..., Any]
    restore_pipeline_snapshot: Callable[..., Any]
    run_all_steps: Callable[..., Any]
    prepare_run_log_file: Callable[..., Any]
    get_run_placeholder: Callable[..., Any]
    push_run_log: Callable[..., Any]
    rerun_fragment_or_app: Callable[..., Any]
    bump_history_revision: Callable[..., Any]
    ask_gpt: Callable[..., Any]
    maybe_autofix_generated_code: Callable[..., Any]
    load_df_cached: Callable[..., Any]
    ensure_safe_service_template: Callable[..., Any]
    inspect_pipeline_run_lock: Callable[..., Any]
    refresh_pipeline_run_lock: Callable[..., Any]
    acquire_pipeline_run_lock: Callable[..., Any]
    release_pipeline_run_lock: Callable[..., Any]
    label_for_step_runtime: Callable[..., Any]
    python_for_step: Callable[..., Any]
    python_for_venv: Callable[..., Any]
    stream_run_command: Callable[..., Any]
    run_locked_step: Callable[..., Any]
    load_pipeline_conceptual_dot: Callable[..., Any]
    render_pipeline_view: Callable[..., Any]
    default_df: str
    safe_service_template_filename: str
    safe_service_template_marker: str


def get_existing_snippets(env: AgiEnv, steps_file: Path, deps: "PipelineLabDeps") -> Dict[str, Path]:
    """Discover reusable snippet files and return a label->path mapping."""
    _ensure_safe_service_template = deps.ensure_safe_service_template
    SAFE_SERVICE_START_TEMPLATE_FILENAME = deps.safe_service_template_filename
    SAFE_SERVICE_START_TEMPLATE_MARKER = deps.safe_service_template_marker

    snippet_file = st.session_state.get("snippet_file")
    safe_service_template = _ensure_safe_service_template(
        env,
        steps_file,
        template_filename=SAFE_SERVICE_START_TEMPLATE_FILENAME,
        marker=SAFE_SERVICE_START_TEMPLATE_MARKER,
        debug_log=logger.debug,
    )

    registry = discover_pipeline_snippets(
        steps_file=steps_file,
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
    steps_file: Path,
    module_path: Path,
    env: AgiEnv,
    deps: "PipelineLabDeps",
) -> None:
    load_all_steps = deps.load_all_steps
    save_step = deps.save_step
    remove_step = deps.remove_step
    _force_persist_step = deps.force_persist_step
    _capture_pipeline_snapshot = deps.capture_pipeline_snapshot
    _restore_pipeline_snapshot = deps.restore_pipeline_snapshot
    run_all_steps = deps.run_all_steps
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
    _label_for_step_runtime = deps.label_for_step_runtime
    _python_for_step = deps.python_for_step
    _python_for_venv = deps.python_for_venv
    _stream_run_command = deps.stream_run_command
    _run_locked_step = deps.run_locked_step
    load_pipeline_conceptual_dot = deps.load_pipeline_conceptual_dot
    render_pipeline_view = deps.render_pipeline_view
    DEFAULT_DF = deps.default_df
    # Reset active step and count to reflect persisted steps
    persisted_steps = load_all_steps(module_path, steps_file, index_page_str) or []
    if not persisted_steps and steps_file.exists():
        try:
            import tomllib
            with open(steps_file, "rb") as f:
                raw = tomllib.load(f)
            module_key = _module_keys(module_path)[0]
            fallback_steps = raw.get(module_key, [])
            if isinstance(fallback_steps, list):
                persisted_steps = [s for s in fallback_steps if _is_displayable_step(s)]
        except (AttributeError, OSError, TypeError, tomllib.TOMLDecodeError):
            pass
    total_steps = len(persisted_steps)
    safe_prefix = index_page_str.replace("/", "_")
    total_steps_key = f"{safe_prefix}_total_steps"
    prev_total = st.session_state.get(total_steps_key)
    st.session_state[index_page_str][0] = 0
    st.session_state[index_page_str][-1] = total_steps

    sequence_state_key = f"{index_page_str}__run_sequence"
    stored_sequence = st.session_state.get(sequence_state_key)
    if stored_sequence is None:
        stored_sequence = _load_sequence_preferences(module_path, steps_file)
        st.session_state[sequence_state_key] = stored_sequence

    if total_steps == 0:
        if stored_sequence:
            st.session_state[sequence_state_key] = []
            _persist_sequence_preferences(module_path, steps_file, [])
    else:
        current_sequence = [idx for idx in stored_sequence if 0 <= idx < total_steps]
        if not current_sequence:
            current_sequence = list(range(total_steps))
        elif isinstance(prev_total, int) and total_steps > prev_total:
            for idx in range(prev_total, total_steps):
                if idx not in current_sequence:
                    current_sequence.append(idx)
        if current_sequence != st.session_state[sequence_state_key]:
            st.session_state[sequence_state_key] = current_sequence
            _persist_sequence_preferences(module_path, steps_file, current_sequence)

    if prev_total != total_steps:
        st.session_state[total_steps_key] = total_steps
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

    snippet_option_map = get_existing_snippets(env, steps_file, deps)
    snippet_guidance = _snippet_source_guidance(
        bool(snippet_option_map),
        env.app,
    )
    _render_global_runner_state_panel(env, lab_dir, index_page_str)
    step_source_key = f"{safe_prefix}_new_step_source"
    source_options = ["gen step"] + list(snippet_option_map.keys())
    if st.session_state.get(step_source_key) not in source_options:
        st.session_state[step_source_key] = source_options[0]

    # No steps yet: allow creating the first one via Generate code
    if total_steps == 0:
        st.info("No steps recorded yet. Generate your first step below.")
        st.info(snippet_guidance)
        new_q_key = f"{index_page_str}_new_q"
        new_venv_key = f"{index_page_str}_new_venv"
        if new_q_key not in st.session_state:
            st.session_state[new_q_key] = ""
        with st.expander("New step", expanded=True):
            step_source = compact_choice(
                st,
                "Step source",
                source_options,
                key=step_source_key,
                help="Select `gen step` to use the code generator, or choose an existing snippet to import as read-only.",
                inline_limit=5,
            )

            if step_source == "gen step":
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
                    help="Choose which virtual environment should execute this step.",
                    inline_limit=4,
                )
                selected_path = "" if selected_new_venv == venv_labels[0] else _valid_runtime_path(selected_new_venv)
                run_new = action_button(
                    st,
                    "Generate code",
                    key=f"{safe_prefix}_add_first_step_btn",
                    kind="generate",
                )
                if run_new:
                    prompt_text = st.session_state.get(new_q_key, "").strip()
                    if not prompt_text:
                        st.warning("Enter a prompt before generating code.")
                    else:
                        df_path = Path(st.session_state.df_file) if st.session_state.get("df_file") else Path()
                        answer = ask_gpt(prompt_text, df_path, index_page_str, env.envars)
                        venv_map = {0: selected_path} if selected_path else {}
                        eng_map = {0: "agi.run" if selected_path else "runpy"}
                        expander_state_key = f"{safe_prefix}_expander_open"
                        expander_state = st.session_state.setdefault(expander_state_key, {})
                        expander_state[0] = True
                        st.session_state[expander_state_key] = expander_state
                        save_step(
                            module_path,
                            answer,
                            0,
                            1,
                            steps_file,
                            venv_map=venv_map,
                            engine_map=eng_map,
                        )
                        _bump_history_revision()
                        st.rerun()
            else:
                snippet_path = snippet_option_map.get(step_source)
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
                        question = f"Imported snippet: {snippet_path.name if snippet_path else step_source}"
                        detail = f"Imported from {snippet_path}" if snippet_path else ""
                        answer = [df_path, question, "snippet", normalized_code, detail]
                        venv_map = {0: import_runtime} if import_runtime else {}
                        eng_map = {0: import_engine}
                        extra_fields = {
                            ORCHESTRATE_LOCKED_STEP_KEY: True,
                            ORCHESTRATE_LOCKED_SOURCE_KEY: str(snippet_path) if snippet_path else "",
                        }
                        expander_state_key = f"{safe_prefix}_expander_open"
                        expander_state = st.session_state.setdefault(expander_state_key, {})
                        expander_state[0] = True
                        st.session_state[expander_state_key] = expander_state
                        save_step(
                            module_path,
                            answer,
                            0,
                            1,
                            steps_file,
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
            steps_file=steps_file,
            steps=persisted_steps,
            sequence=st.session_state.get(sequence_state_key, []),
            session_state=st.session_state,
            selected_lab=lab_dir,
            env=env,
            deps=PipelinePageStateDeps(
                is_displayable_step=lambda entry: _is_displayable_step(dict(entry)),
                is_runnable_step=lambda entry: _pipeline_steps_module.is_runnable_step(dict(entry)),
                step_summary=lambda entry: _step_summary(dict(entry), width=80),
                step_label=lambda idx, entry: _step_label_for_multiselect(idx, dict(entry), env=env),
                find_legacy_agi_run_steps=_pipeline_steps_module.find_legacy_agi_run_steps,
                inspect_pipeline_run_lock=_inspect_pipeline_run_lock if include_lock else None,
            ),
        )

    render_page_state = _build_page_state()

    @st.fragment
    def _render_pipeline_step_fragment(step: int, entry: Dict[str, Any]) -> None:
        # Per-step keys
        q_key = f"{safe_prefix}_q_step_{step}"
        code_val_key = f"{safe_prefix}_code_step_{step}"
        select_key = f"{safe_prefix}_venv_{step}"
        rev_key = f"{safe_prefix}_editor_rev_{step}"
        pending_q_key = f"{safe_prefix}_pending_q_{step}"
        pending_c_key = f"{safe_prefix}_pending_c_{step}"
        undo_key = f"{safe_prefix}_undo_{step}"
        apply_q_key = f"{q_key}_apply_pending"
        apply_c_key = f"{code_val_key}_apply_pending"
        confirm_delete_key = f"{safe_prefix}_confirm_delete_{step}"

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
        init_key = f"{safe_prefix}_step_init_{step}"
        resync_sig_key = f"{safe_prefix}_editor_resync_sig_{step}"
        ignore_blank_key = f"{safe_prefix}_ignore_blank_editor_{step}"
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

        current_path = _valid_runtime_path(selected_map.get(step, ""))
        if not current_path:
            entry_venv = _valid_runtime_path(entry.get("E", ""))
            if entry_venv:
                selected_map[step] = entry_venv
                current_path = entry_venv
        venv_labels = ["Use AGILAB environment"] + available_venvs
        if current_path and current_path not in venv_labels:
            venv_labels.append(current_path)

        live_entry = {
            "Q": st.session_state.get(q_key, entry.get("Q", "")),
            "C": st.session_state.get(code_val_key, entry.get("C", "")),
        }
        summary = _step_summary(live_entry, width=80)
        dirty_key = f"{q_key}_dirty"
        if st.session_state.pop(dirty_key, False):
            _rerun_fragment_or_app()
        expanded_flag = expander_state.get(step, False)
        title_suffix = summary if summary else "No description yet"
        expander_title = f"{step + 1} {title_suffix}"
        is_locked_step = _is_orchestrate_locked_step(entry)
        locked_source = _orchestrate_snippet_source(entry)
        if is_locked_step:
            expander_title = f"{step + 1} 🔒 ORCHESTRATE • {title_suffix}"

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
                    help="Choose which virtual environment should execute this step.",
                    disabled=is_locked_step,
                    inline_limit=4,
                )
                selected_path = "" if selected_label == venv_labels[0] else _valid_runtime_path(selected_label)
                if selected_path:
                    selected_map[step] = selected_path
                else:
                    selected_map.pop(step, None)

            computed_engine = "agi.run" if selected_map.get(step) else "runpy"
            engine_map[step] = computed_engine
            st.session_state["lab_selected_engine"] = computed_engine

            if is_locked_step:
                if locked_source:
                    source_name = Path(locked_source).name if locked_source else locked_source
                    if source_name:
                        st.caption(f"Imported from ORCHESTRATE: `{source_name}`.")
                else:
                    st.caption("Imported from ORCHESTRATE.")
                st.caption("This step is locked. Re-run ORCHESTRATE and re-import it here if you need changes.")
                st.code(st.session_state.get(code_val_key, entry.get("C", "")) or "# Empty snippet", language="python")

                if action_button(
                    st,
                    "Run imported step",
                    key=f"{safe_prefix}_run_locked_{step}",
                    kind="run",
                ):
                    _run_locked_step(
                        env,
                        index_page_str,
                        steps_file,
                        step,
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
                        step_summary=_step_summary,
                    )

                if st.session_state.get(confirm_delete_key, False):
                    delete_clicked = action_button(
                        st,
                        "Confirm remove",
                        key=f"{safe_prefix}_delete_confirm_{step}",
                        kind="destructive",
                        type="primary",
                    )
                    cancel_delete_clicked = action_button(
                        st,
                        "Cancel",
                        key=f"{safe_prefix}_delete_cancel_{step}",
                        kind="cancel",
                    )
                    arm_delete_clicked = False
                else:
                    delete_clicked = False
                    cancel_delete_clicked = False
                    arm_delete_clicked = action_button(
                        st,
                        "Remove",
                        key=f"{safe_prefix}_delete_{step}",
                        kind="remove",
                    )

                if arm_delete_clicked:
                    st.session_state[confirm_delete_key] = True
                    _rerun_fragment_or_app()
                if cancel_delete_clicked:
                    st.session_state.pop(confirm_delete_key, None)
                    _rerun_fragment_or_app()
                if delete_clicked:
                    result = delete_pipeline_step_command(
                        session_state=st.session_state,
                        index_page=index_page_str,
                        step_index=step,
                        lab_dir=lab_dir,
                        steps_file=steps_file,
                        persisted_steps=persisted_steps,
                        selected_map=selected_map,
                        capture_pipeline_snapshot=_capture_pipeline_snapshot,
                        remove_step=remove_step,
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
                    key=f"{safe_prefix}_save_{step}",
                    kind="save",
                    type="secondary",
                )
            with btn_run:
                run_pressed = action_button(
                    st,
                    "Gen code",
                    key=f"{safe_prefix}_run_{step}",
                    kind="generate",
                )
            with btn_revert:
                revert_pressed = action_button(
                    st,
                    "Undo",
                    key=f"{safe_prefix}_revert_{step}",
                    kind="revert",
                )
            with btn_delete:
                if st.session_state.get(confirm_delete_key, False):
                    delete_clicked = action_button(
                        st,
                        "Confirm remove",
                        key=f"{safe_prefix}_delete_confirm_{step}",
                        kind="destructive",
                        type="primary",
                    )
                    cancel_delete_clicked = action_button(
                        st,
                        "Cancel",
                        key=f"{safe_prefix}_delete_cancel_{step}",
                        kind="cancel",
                    )
                else:
                    arm_delete_clicked = action_button(
                        st,
                        "Remove",
                        key=f"{safe_prefix}_delete_{step}",
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
            editor_key = f"{safe_prefix}a{step}-{rev}"
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
                save_step(
                    module_path,
                    [entry.get("D", ""), restored_q, entry.get("M", ""), restored_c],
                    step,
                    total_steps,
                    steps_file,
                    venv_map=selected_map,
                    engine_map=engine_map,
                )
                _bump_history_revision()
                expander_state[step] = True
                st.session_state[expander_state_key] = expander_state
                st.session_state[rev_key] = st.session_state.get(rev_key, 0) + 1
                _rerun_fragment_or_app()

            if save_pressed:
                undo_stack = st.session_state.get(undo_key, [])
                undo_stack.append((st.session_state.get(q_key, ""), st.session_state.get(code_val_key, "")))
                st.session_state[undo_key] = undo_stack
                st.session_state[code_val_key] = code_current
                st.session_state[rev_key] = st.session_state.get(rev_key, 0) + 1
                expander_state[step] = True
                st.session_state[expander_state_key] = expander_state
                save_step(
                    module_path,
                    [entry.get("D", ""), st.session_state.get(q_key, ""), entry.get("M", ""), code_current],
                    step,
                    total_steps,
                    steps_file,
                    venv_map=selected_map,
                    engine_map=engine_map,
                )
                _force_persist_step(
                    module_path,
                    steps_file,
                    step,
                    {
                        "D": entry.get("D", ""),
                        "Q": st.session_state.get(q_key, ""),
                        "M": entry.get("M", ""),
                        "C": code_current,
                        "E": normalize_runtime_path(selected_map.get(step, "")),
                        "R": engine_map.get(step, "") or ("agi.run" if selected_map.get(step) else "runpy"),
                    },
                )
                st.session_state[pending_q_key] = st.session_state.get(q_key, "")
                st.session_state[pending_c_key] = code_current
                st.session_state.pop(q_key, None)
                st.session_state.pop(code_val_key, None)
                _bump_history_revision()
                _rerun_fragment_or_app()

            overlay_type = snippet_dict.get("type") if snippet_dict else None
            overlay_flag_key = f"{safe_prefix}_overlay_done_{step}"
            overlay_sig_key = f"{safe_prefix}_overlay_sig_{step}"
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
                expander_state[step] = True
                st.session_state[expander_state_key] = expander_state
                save_step(
                    module_path,
                    [entry.get("D", ""), st.session_state.get(q_key, ""), entry.get("M", ""), code_current],
                    step,
                    total_steps,
                    steps_file,
                    venv_map=selected_map,
                    engine_map=engine_map,
                )
                _force_persist_step(
                    module_path,
                    steps_file,
                    step,
                    {
                        "D": entry.get("D", ""),
                        "Q": st.session_state.get(q_key, ""),
                        "M": entry.get("M", ""),
                        "C": code_current,
                        "E": normalize_runtime_path(selected_map.get(step, "")),
                        "R": engine_map.get(step, "") or ("agi.run" if selected_map.get(step) else "runpy"),
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
                venv_root = normalize_runtime_path(selected_map.get(step, ""))
                entry_runtime_raw = normalize_runtime_path(entry.get("E", ""))
                entry_runtime = entry_runtime_raw if _is_valid_runtime_root(entry_runtime_raw) else ""
                if not venv_root and entry_runtime:
                    venv_root = entry_runtime
                    selected_map[step] = entry_runtime
                if not venv_root:
                    fallback_venv = normalize_runtime_path(st.session_state.get("lab_selected_venv", ""))
                    if fallback_venv and _is_valid_runtime_root(fallback_venv):
                        venv_root = fallback_venv
                        selected_map[step] = fallback_venv
                        if fallback_venv not in venv_labels:
                            venv_labels.append(fallback_venv)
                        st.session_state[select_key] = fallback_venv
                entry_engine = str(entry.get("R", "") or "")
                ui_engine = str(engine_map.get(step) or "")
                engine = _resolve_step_engine(entry_engine, ui_engine, venv_root)
                if venv_root and engine == "runpy":
                    engine = "agi.run"
                if engine.startswith("agi.") and not venv_root:
                    fallback_runtime = normalize_runtime_path(getattr(env, "active_app", "") or "")
                    if _is_valid_runtime_root(fallback_runtime):
                        venv_root = fallback_runtime
                        st.session_state["lab_selected_venv"] = venv_root
                engine_map[step] = engine
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
                        prefix=f"step_{step + 1}",
                    )
                    if log_file_path:
                        _push_run_log(
                            index_page_str,
                            f"Run step {step + 1} started… logs will be saved to {log_file_path}",
                            stored_placeholder,
                        )
                    else:
                        _push_run_log(
                            index_page_str,
                            f"Run step {step + 1} started… (unable to prepare log file: {log_error})",
                            stored_placeholder,
                        )
                    try:
                        target_base = Path(steps_file).parent.resolve()
                        target_base.mkdir(parents=True, exist_ok=True)
                        run_output = ""
                        summary = _step_summary({"Q": entry.get("Q", ""), "C": code_to_run})
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
                            "question": st.session_state.get(q_key, ""),
                            "model": entry.get("M", ""),
                            "runtime": venv_root or "",
                            "engine": engine,
                        }
                        step_files: List[Any] = []
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
                            if engine == "runpy":
                                run_output = run_lab(
                                    [entry.get("D", ""), st.session_state.get(q_key, ""), code_to_run],
                                    snippet_file,
                                    env.copilot_file,
                                    env_overrides=step_env,
                                )
                                step_files.append(Path(snippet_file))
                            else:
                                script_path = (target_base / "AGI_run.py").resolve()
                                script_path.write_text(wrap_code_with_mlflow_resume(code_to_run))
                                step_files.append(script_path)
                                python_cmd = _python_for_step(venv_root, engine=engine, code=code_to_run)
                                run_output = _stream_run_command(
                                    env,
                                    index_page_str,
                                    f"{python_cmd} {script_path}",
                                    cwd=target_base,
                                    placeholder=stored_placeholder,
                                    extra_env=step_env,
                                )
                            env_label = _label_for_step_runtime(venv_root, engine=engine, code=code_to_run)
                            _push_run_log(
                                index_page_str,
                                f"Step {step + 1}: engine={engine}, env={env_label}, summary=\"{summary}\"",
                                stored_placeholder,
                            )
                            preview = (run_output or "").strip()
                            if preview:
                                _push_run_log(
                                    index_page_str,
                                    f"Output (step {step + 1}):\n{preview}",
                                    stored_placeholder,
                                )
                                if "No such file or directory" in preview:
                                    _push_run_log(
                                        index_page_str,
                                        "Hint: for AGI app steps, input/output data is normally resolved under "
                                        "agi_env.AGI_CLUSTER_SHARE. Check whether the upstream step created the "
                                        "expected file there before this step ran.",
                                        stored_placeholder,
                                    )
                            elif engine == "runpy":
                                _push_run_log(
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
                                    text_artifacts={
                                        f"step_{step + 1}/stdout.txt": preview or "",
                                    },
                                    file_artifacts=step_files,
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
                answer = ask_gpt(prompt_text, df_path, index_page_str, env.envars)
                merged_code = None
                code_txt = answer[3] if len(answer) > 3 else ""
                detail_txt = (answer[4] or "").strip() if len(answer) > 4 else ""
                if code_txt:
                    summary_line = f"# {detail_txt}\n" if detail_txt else ""
                    merged_code = f"{summary_line}{code_txt}"
                    if len(answer) > 3:
                        answer[3] = merged_code
                else:
                    merged_code = st.session_state.get(code_val_key, "")
                    if len(answer) > 3:
                        answer[3] = merged_code

                if merged_code:
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

                save_step(
                    module_path,
                    answer,
                    step,
                    total_steps,
                    steps_file,
                    venv_map=selected_map,
                    engine_map=engine_map,
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
                    detail_store[step] = detail
                env_label = (
                    Path(selected_map.get(step, "")).name
                    if selected_map.get(step)
                    else "default env"
                )
                summary = _step_summary(
                    {
                        "Q": answer[1] if len(answer) > 1 else "",
                        "C": answer[4] if len(answer) > 4 else "",
                    }
                )
                _push_run_log(
                    index_page_str,
                    f"Step {step + 1}: engine={engine_map.get(step,'')}, env={env_label}, summary=\"{summary}\"",
                    _get_run_placeholder(index_page_str),
                )
                expander_state[step] = True
                st.session_state[expander_state_key] = expander_state
                _rerun_fragment_or_app()

            if delete_clicked:
                st.session_state.pop(confirm_delete_key, None)
                result = delete_pipeline_step_command(
                    session_state=st.session_state,
                    index_page=index_page_str,
                    step_index=step,
                    lab_dir=lab_dir,
                    steps_file=steps_file,
                    persisted_steps=persisted_steps,
                    selected_map=selected_map,
                    capture_pipeline_snapshot=_capture_pipeline_snapshot,
                    remove_step=remove_step,
                )
                if not result.ok:
                    st.warning(result.message)
                else:
                    st.rerun()

    _conceptual_source, conceptual_dot = load_pipeline_conceptual_dot(env, lab_dir)
    if conceptual_dot:
        with st.expander("Conceptual view", expanded=False):
            st.graphviz_chart(conceptual_dot, width="content")

    render_steps = [persisted_steps[item.index] for item in render_page_state.visible_steps]
    render_pipeline_view(
        render_steps,
        title="Execution view" if conceptual_dot else "Pipeline view",
    )

    for visible_step in render_page_state.visible_steps:
        _render_pipeline_step_fragment(visible_step.index, persisted_steps[visible_step.index])

    # Add-step expander to append a new step at the end
    new_q_key = f"{safe_prefix}_new_q"
    new_venv_key = f"{safe_prefix}_new_venv"
    if new_q_key not in st.session_state:
        st.session_state[new_q_key] = ""
    with st.expander("Add step", expanded=False):
        st.info(snippet_guidance)
        step_source = compact_choice(
            st,
            "Step source",
            source_options,
            key=step_source_key,
            help="Select `gen step` to use the code generator, or choose an existing snippet to import as read-only.",
            inline_limit=5,
        )
        if step_source == "gen step":
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
                help="Choose which virtual environment should execute this step.",
                inline_limit=4,
            )
            selected_path = "" if selected_new_venv == venv_labels[0] else _valid_runtime_path(selected_new_venv)
            run_new = action_button(st, "Generate code", key=f"{safe_prefix}_add_step_btn", kind="generate")
            if run_new:
                prompt_text = st.session_state.get(new_q_key, "").strip()
                if prompt_text:
                    df_path = Path(st.session_state.df_file) if st.session_state.get("df_file") else Path()
                    answer = ask_gpt(prompt_text, df_path, index_page_str, env.envars)
                    merged_code = None
                    code_txt = answer[3] if len(answer) > 3 else ""
                    detail_txt = (answer[4] or "").strip() if len(answer) > 4 else ""
                    if code_txt:
                        summary_line = f"# {detail_txt}\n" if detail_txt else ""
                        merged_code = f"{summary_line}{code_txt}"
                        if len(answer) > 3:
                            answer[3] = merged_code

                    if merged_code:
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
                    new_idx = len(persisted_steps)
                    venv_map = selected_map.copy()
                    engine_map_local = engine_map.copy()
                    if selected_path:
                        venv_map[new_idx] = selected_path
                        engine_map_local[new_idx] = "agi.run"
                    else:
                        engine_map_local[new_idx] = "runpy"
                    save_step(
                        module_path,
                        answer,
                        new_idx,
                        new_idx + 1,
                        steps_file,
                        venv_map=venv_map,
                        engine_map=engine_map_local,
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
            snippet_path = snippet_option_map.get(step_source)
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
                key=f"{safe_prefix}_add_step_snippet_btn",
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
                    new_idx = len(persisted_steps)
                    question = f"Imported snippet: {snippet_path.name if snippet_path else step_source}"
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
                        ORCHESTRATE_LOCKED_STEP_KEY: True,
                        ORCHESTRATE_LOCKED_SOURCE_KEY: str(snippet_path) if snippet_path else "",
                    }
                    save_step(
                        module_path,
                        answer,
                        new_idx,
                        new_idx + 1,
                        steps_file,
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
    if total_steps > 0:
        sequence_options = [item.index for item in render_page_state.visible_steps]
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
            return _step_label_for_multiselect(idx, persisted_steps[idx], env=env)

        selected_sequence = st.multiselect(
            "Execution sequence",
            options=sequence_options,
            key=sequence_widget_key,
            format_func=_format_sequence_option,
            help="Select which steps to run. They execute in the order shown.",
        )
        sanitized_selection = [idx for idx in selected_sequence if idx in sequence_options]
        final_sequence = sanitized_selection or sequence_options
        if st.session_state.get(sequence_state_key) != final_sequence:
            st.session_state[sequence_state_key] = final_sequence
            _persist_sequence_preferences(module_path, steps_file, final_sequence)

    page_state = _build_page_state(include_lock=True)
    if page_state.stale_step_refs and page_state.run_disabled_reason:
        st.warning(page_state.run_disabled_reason)

    lock_state = page_state.lock_state
    if lock_state:
        owner_text = str(lock_state.get("owner_text") or "unknown owner")
        stale_reason = lock_state.get("stale_reason")
        if stale_reason:
            st.info(
                f"Pipeline lock detected for this app, but it looks stale: {owner_text}. "
                f"Reason: {stale_reason}."
            )
        else:
            st.warning(
                f"Pipeline lock detected for this app: {owner_text}. "
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
            "Run pipeline",
            key=f"{index_page_str}_run_all",
            kind="run",
            help=run_blocked_reason or "Execute every step sequentially using its saved virtual environment.",
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
                    help=force_blocked_reason or "Remove the stale pipeline lock and start a new run.",
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
                    or "Use only when a previous pipeline run was interrupted and left a lock behind.",
                    disabled=PipelineAction.FORCE_RUN not in page_state.available_actions,
                )

    if run_all_clicked and PipelineAction.RUN_PIPELINE not in page_state.available_actions:
        st.warning(
            page_state.blocked_actions.get(
                PipelineAction.RUN_PIPELINE,
                "Pipeline cannot run in the current state.",
            )
        )
        run_all_clicked = False
    if force_run_clicked and PipelineAction.FORCE_RUN not in page_state.available_actions:
        st.warning(
            page_state.blocked_actions.get(
                PipelineAction.FORCE_RUN,
                "Pipeline cannot be force-run in the current state.",
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
                help="Permanently remove every step in this lab.",
                kind="destructive",
                type="primary",
            )
        else:
            arm_delete_all_clicked = action_button(
                st,
                "Delete all",
                key=f"{index_page_str}_delete_all",
                help="Remove every step in this lab.",
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
    if isinstance(undo_payload, dict) and isinstance(undo_payload.get("steps"), list):
        undo_label = str(undo_payload.get("label", "last delete"))
        undo_delete_clicked = action_button(
            st,
            "Undo delete",
            key=f"{index_page_str}_undo_delete",
            help=f"Restore the pipeline state before the latest delete action ({undo_label}).",
            kind="revert",
        )

    if undo_delete_clicked:
        result = undo_pipeline_delete_command(
            session_state=st.session_state,
            index_page=index_page_str,
            module_path=module_path,
            steps_file=steps_file,
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
        # Collapse all step expanders after running the pipeline
        st.session_state[expander_state_key] = {}
        try:
            with status_container(st, "Running pipeline…", state="running", expanded=True) as run_status:
                try:
                    run_all_steps(
                        lab_dir,
                        index_page_str,
                        steps_file,
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
                    run_status.update(label=finish_result.message, state="error", expanded=True)
                    toast(st, finish_result.message, state="error")
                    raise
                else:
                    finish_result = finish_pipeline_run_command(
                        session_state=st.session_state,
                        index_page=index_page_str,
                        succeeded=True,
                        message="Pipeline run finished. Inspect Run logs.",
                    )
                    run_status.update(label=finish_result.message, state="complete", expanded=False)
                    toast(st, finish_result.message, state="success")
        finally:
            st.session_state.pop(f"{index_page_str}__run_log_file", None)
        st.rerun()

    if delete_all_clicked:
        result = delete_all_pipeline_steps_command(
            session_state=st.session_state,
            index_page=index_page_str,
            lab_dir=lab_dir,
            module_path=module_path,
            steps_file=steps_file,
            persisted_steps=persisted_steps,
            sequence_widget_key=sequence_widget_key,
            capture_pipeline_snapshot=_capture_pipeline_snapshot,
            remove_step=remove_step,
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
            load_df_cached(Path(df_source)) if df_source else None
        )
    loaded_df = st.session_state["loaded_df"]
    render_latest_outputs(
        st,
        source_path=st.session_state.get("df_file"),
        dataframe=loaded_df,
        key_prefix=f"pipeline:{index_page_str}",
    )
    if isinstance(loaded_df, pd.DataFrame) and not loaded_df.empty:
        render_dataframe_preview(
            loaded_df,
            truncation_label="PIPELINE preview limited",
        )
    else:
        empty_state(
            st,
            "No data loaded yet.",
            body=f"Generate and execute a step so the latest {DEFAULT_DF} appears under the Dataframe selector.",
        )

    with st.expander("Run logs", expanded=True):
        log_page_state = _build_page_state()
        logs = list(log_page_state.run_logs)
        log_body = "\n".join(logs)
        clear_logs = render_log_actions(
            st,
            body=log_body,
            download_key=f"{index_page_str}__download_logs_global",
            file_name=f"{index_page_str}_pipeline.log",
            clear_key=f"{index_page_str}__clear_logs_global",
        )
        if clear_logs:
            result = clear_pipeline_run_logs(st.session_state, index_page_str)
            if result.ok:
                toast(st, result.message, state="info")
            else:
                st.warning(result.message)
            log_page_state = _build_page_state()
            logs = list(log_page_state.run_logs)
            log_body = "\n".join(logs)
        log_placeholder = st.empty()
        st.session_state[run_placeholder_key] = log_placeholder
        last_log_file = log_page_state.last_run_log_file
        if last_log_file:
            st.caption(f"Most recent run log: {last_log_file}")
        source = f"PIPELINE {last_log_file}" if last_log_file else "PIPELINE"
        render_pinnable_code_editor(
            st,
            code_editor,
            f"pipeline_run_logs:{index_page_str}",
            title=f"Pipeline logs: {getattr(env, 'app', None) or index_page_str}",
            body=log_body,
            key=f"{index_page_str}__run_logs_editor",
            body_format="code",
            language="text",
            source=source,
            empty_message="No runs recorded yet.",
            info_name="Run logs",
        )
