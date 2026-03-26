import importlib.util
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pandas as pd
import streamlit as st
import tomllib
from code_editor import code_editor

from agi_env import AgiEnv
from agi_env.pagelib import get_css_text, get_custom_buttons, get_info_bar, run_lab, save_csv

try:
    from agilab.pipeline_steps import (
        ORCHESTRATE_LOCKED_SOURCE_KEY,
        ORCHESTRATE_LOCKED_STEP_KEY,
        get_available_virtualenvs,
        is_displayable_step as _is_displayable_step,
        is_orchestrate_locked_step as _is_orchestrate_locked_step,
        load_sequence_preferences as _load_sequence_preferences,
        module_keys as _module_keys,
        normalize_runtime_path,
        orchestrate_snippet_source as _orchestrate_snippet_source,
        persist_sequence_preferences as _persist_sequence_preferences,
        snippet_source_guidance as _snippet_source_guidance,
        step_summary as _step_summary,
    )
except ModuleNotFoundError:
    _pipeline_steps_path = Path(__file__).resolve().parent / "pipeline_steps.py"
    _pipeline_steps_spec = importlib.util.spec_from_file_location("agilab_pipeline_steps_fallback", _pipeline_steps_path)
    if _pipeline_steps_spec is None or _pipeline_steps_spec.loader is None:
        raise
    _pipeline_steps_module = importlib.util.module_from_spec(_pipeline_steps_spec)
    _pipeline_steps_spec.loader.exec_module(_pipeline_steps_module)
    ORCHESTRATE_LOCKED_SOURCE_KEY = _pipeline_steps_module.ORCHESTRATE_LOCKED_SOURCE_KEY
    ORCHESTRATE_LOCKED_STEP_KEY = _pipeline_steps_module.ORCHESTRATE_LOCKED_STEP_KEY
    get_available_virtualenvs = _pipeline_steps_module.get_available_virtualenvs
    _is_displayable_step = _pipeline_steps_module.is_displayable_step
    _is_orchestrate_locked_step = _pipeline_steps_module.is_orchestrate_locked_step
    _load_sequence_preferences = _pipeline_steps_module.load_sequence_preferences
    _module_keys = _pipeline_steps_module.module_keys
    normalize_runtime_path = _pipeline_steps_module.normalize_runtime_path
    _orchestrate_snippet_source = _pipeline_steps_module.orchestrate_snippet_source
    _persist_sequence_preferences = _pipeline_steps_module.persist_sequence_preferences
    _snippet_source_guidance = _pipeline_steps_module.snippet_source_guidance
    _step_summary = _pipeline_steps_module.step_summary

try:
    from agilab.pipeline_runtime import is_valid_runtime_root as _is_valid_runtime_root
except ModuleNotFoundError:
    _pipeline_runtime_path = Path(__file__).resolve().parent / "pipeline_runtime.py"
    _pipeline_runtime_spec = importlib.util.spec_from_file_location("agilab_pipeline_runtime_fallback", _pipeline_runtime_path)
    if _pipeline_runtime_spec is None or _pipeline_runtime_spec.loader is None:
        raise
    _pipeline_runtime_module = importlib.util.module_from_spec(_pipeline_runtime_spec)
    _pipeline_runtime_spec.loader.exec_module(_pipeline_runtime_module)
    _is_valid_runtime_root = _pipeline_runtime_module.is_valid_runtime_root

logger = logging.getLogger(__name__)


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
    refresh_pipeline_run_lock: Callable[..., Any]
    acquire_pipeline_run_lock: Callable[..., Any]
    release_pipeline_run_lock: Callable[..., Any]
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
    discovered: List[Path] = []
    seen: set[str] = set()

    def _add_path(candidate: Path) -> None:
        try:
            path = candidate.expanduser()
        except Exception:
            path = candidate
        if not path.exists() or not path.is_file() or path.suffix.lower() != ".py":
            return
        try:
            unique_key = str(path.resolve())
        except Exception:
            unique_key = str(path)
        if unique_key in seen:
            return
        seen.add(unique_key)
        discovered.append(path)

    snippet_file = st.session_state.get("snippet_file")
    if snippet_file:
        _add_path(Path(snippet_file))

    run_script = steps_file.parent / "AGI_run.py"
    _add_path(run_script)
    safe_service_template = _ensure_safe_service_template(
        env,
        steps_file,
        template_filename=SAFE_SERVICE_START_TEMPLATE_FILENAME,
        marker=SAFE_SERVICE_START_TEMPLATE_MARKER,
        debug_log=logger.debug,
    )
    if safe_service_template:
        _add_path(safe_service_template)

    # Avoid importing arbitrary execute logs (stale app_args) from runenv.
    # Only keep a short-lived, app-scoped run snippet that is still
    # aligned with the current app_settings modification timestamp.
    runenv_root = getattr(env, "runenv", None)
    if runenv_root:
        try:
            runenv_path = Path(runenv_root).expanduser()
            app_settings_mtime = Path(env.app_settings_file).stat().st_mtime if Path(env.app_settings_file).exists() else None
            expected_suffix = f"_{env.app}.py"
            for py_file in sorted(runenv_path.glob("AGI_*.py")):
                if not py_file.name.endswith(expected_suffix):
                    continue
                if app_settings_mtime is not None:
                    try:
                        if py_file.stat().st_mtime < app_settings_mtime:
                            continue
                    except Exception:
                        continue
                _add_path(py_file)
        except Exception:
            pass

    discovered.sort(key=lambda p: (p.name.lower(), str(p).lower()))

    option_map: Dict[str, Path] = {}
    for path in discovered:
        base_label = path.name
        label = base_label
        if label in option_map:
            parent_name = path.parent.name or str(path.parent)
            label = f"{base_label} ({parent_name})"
            idx = 2
            while label in option_map:
                label = f"{base_label} ({parent_name} #{idx})"
                idx += 1
        option_map[label] = path
    return option_map

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
    _refresh_pipeline_run_lock = deps.refresh_pipeline_run_lock
    _acquire_pipeline_run_lock = deps.acquire_pipeline_run_lock
    _release_pipeline_run_lock = deps.release_pipeline_run_lock
    _python_for_venv = deps.python_for_venv
    _stream_run_command = deps.stream_run_command
    _run_locked_step = deps.run_locked_step
    load_pipeline_conceptual_dot = deps.load_pipeline_conceptual_dot
    render_pipeline_view = deps.render_pipeline_view
    DEFAULT_DF = deps.default_df
    def _normalize_editor_text(raw: Optional[str]) -> str:
        if raw is None:
            return ""
        text = str(raw)
        return text if text.strip() else ""
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
        except Exception:
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

    available_venvs = [
        normalize_runtime_path(path) for path in get_available_virtualenvs(env)
    ]
    available_venvs = [path for path in dict.fromkeys(available_venvs) if path]
    env_active_app = normalize_runtime_path(env.active_app)
    manager_runtime = env_active_app
    if env_active_app:
        available_venvs = [env_active_app] + [p for p in available_venvs if p != env_active_app]

    venv_state_key = f"{index_page_str}__venv_map"
    selected_map: Dict[int, str] = st.session_state.setdefault(venv_state_key, {})
    engine_state_key = f"{index_page_str}__engine_map"
    engine_map: Dict[int, str] = st.session_state.setdefault(engine_state_key, {})
    for idx_key, raw_value in list(selected_map.items()):
        normalized_value = normalize_runtime_path(raw_value)
        if normalized_value:
            selected_map[idx_key] = normalized_value
        else:
            selected_map.pop(idx_key, None)

    snippet_option_map = get_existing_snippets(env, steps_file, deps)
    snippet_guidance = _snippet_source_guidance(
        bool(snippet_option_map),
        env.app,
    )
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
            step_source = st.selectbox(
                "Step source",
                source_options,
                key=step_source_key,
                help="Select `gen step` to use the code generator, or choose an existing snippet to import as read-only.",
            )

            if step_source == "gen step":
                st.text_area(
                    "Ask code generator:",
                    key=new_q_key,
                    placeholder="Enter a prompt describing the code you want generated",
                    label_visibility="collapsed",
                )
                venv_labels = ["Use AGILAB environment"] + available_venvs
                selected_new_venv = st.selectbox(
                    "venv",
                    venv_labels,
                    key=new_venv_key,
                    help="Choose which virtual environment should execute this step.",
                )
                selected_path = (
                    "" if selected_new_venv == venv_labels[0] else normalize_runtime_path(selected_new_venv)
                )
                run_new = st.button(
                    "Generate code",
                    type="primary",
                    use_container_width=True,
                    key=f"{safe_prefix}_add_first_step_btn",
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
                    except Exception as exc:
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
                import_new = st.button(
                    "Add snippet",
                    type="primary",
                    use_container_width=True,
                    key=f"{safe_prefix}_add_first_snippet_btn",
                )
                if import_new:
                    if not snippet_code.strip():
                        st.warning("Selected snippet is empty.")
                    else:
                        df_path = Path(st.session_state.df_file) if st.session_state.get("df_file") else Path()
                        question = f"Imported snippet: {snippet_path.name if snippet_path else step_source}"
                        detail = f"Imported from {snippet_path}" if snippet_path else ""
                        answer = [df_path, question, "snippet", snippet_code, detail]
                        venv_map = {0: manager_runtime} if manager_runtime else {}
                        eng_map = {0: "agi.run"}
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

        current_path_raw = normalize_runtime_path(selected_map.get(step, ""))
        current_path = current_path_raw if _is_valid_runtime_root(current_path_raw) else ""
        if not current_path:
            entry_venv_raw = normalize_runtime_path(entry.get("E", ""))
            entry_venv = entry_venv_raw if _is_valid_runtime_root(entry_venv_raw) else ""
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
                session_label = st.session_state.get(select_key, "")
                initial_label = session_label or current_path or ""
                if initial_label and initial_label not in venv_labels:
                    venv_labels.append(initial_label)
                default_label = initial_label or venv_labels[0]
                if default_label not in venv_labels:
                    venv_labels.append(default_label)
                if select_key not in st.session_state or st.session_state[select_key] not in venv_labels:
                    st.session_state[select_key] = default_label
                selected_label = st.selectbox(
                    "venv",
                    venv_labels,
                    key=select_key,
                    help="Choose which virtual environment should execute this step.",
                    disabled=is_locked_step,
                )
                selected_path = "" if selected_label == venv_labels[0] else normalize_runtime_path(selected_label)
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

                if st.button(
                    "Run imported step",
                    type="primary",
                    use_container_width=True,
                    key=f"{safe_prefix}_run_locked_{step}",
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
                    delete_clicked = st.button(
                        "Confirm remove",
                        type="primary",
                        use_container_width=True,
                        key=f"{safe_prefix}_delete_confirm_{step}",
                    )
                    cancel_delete_clicked = st.button(
                        "Cancel",
                        type="secondary",
                        use_container_width=True,
                        key=f"{safe_prefix}_delete_cancel_{step}",
                    )
                    arm_delete_clicked = False
                else:
                    delete_clicked = False
                    cancel_delete_clicked = False
                    arm_delete_clicked = st.button(
                        "Remove",
                        type="secondary",
                        use_container_width=True,
                        key=f"{safe_prefix}_delete_{step}",
                    )

                if arm_delete_clicked:
                    st.session_state[confirm_delete_key] = True
                    _rerun_fragment_or_app()
                if cancel_delete_clicked:
                    st.session_state.pop(confirm_delete_key, None)
                    _rerun_fragment_or_app()
                if delete_clicked:
                    delete_snapshot = _capture_pipeline_snapshot(index_page_str, persisted_steps)
                    delete_snapshot["label"] = f"remove step {step + 1}"
                    delete_snapshot["timestamp"] = datetime.now().isoformat(timespec="seconds")
                    st.session_state[delete_undo_key] = delete_snapshot
                    selected_map.pop(step, None)
                    remove_step(lab_dir, str(step), steps_file, index_page_str)
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
                save_pressed = st.button(
                    "Save",
                    type="secondary",
                    use_container_width=True,
                    key=f"{safe_prefix}_save_{step}",
                )
            with btn_run:
                run_pressed = st.button(
                    "Gen code",
                    type="primary",
                    use_container_width=True,
                    key=f"{safe_prefix}_run_{step}",
                )
            with btn_revert:
                revert_pressed = st.button(
                    "Undo",
                    type="secondary",
                    use_container_width=True,
                    key=f"{safe_prefix}_revert_{step}",
                )
            with btn_delete:
                if st.session_state.get(confirm_delete_key, False):
                    delete_clicked = st.button(
                        "Confirm remove",
                        type="primary",
                        use_container_width=True,
                        key=f"{safe_prefix}_delete_confirm_{step}",
                    )
                    cancel_delete_clicked = st.button(
                        "Cancel",
                        type="secondary",
                        use_container_width=True,
                        key=f"{safe_prefix}_delete_cancel_{step}",
                    )
                else:
                    arm_delete_clicked = st.button(
                        "Remove",
                        type="secondary",
                        use_container_width=True,
                        key=f"{safe_prefix}_delete_{step}",
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
                buttons=get_custom_buttons(),
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
                if ui_engine and ui_engine != entry_engine:
                    if entry_engine.startswith("agi.") and ui_engine == "runpy":
                        engine = entry_engine
                    else:
                        engine = ui_engine
                elif entry_engine:
                    engine = entry_engine
                else:
                    engine = "agi.run" if venv_root else "runpy"
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
                        if engine == "runpy":
                            run_output = run_lab(
                                [entry.get("D", ""), st.session_state.get(q_key, ""), code_to_run],
                                snippet_file,
                                env.copilot_file,
                            )
                        else:
                            script_path = (target_base / "AGI_run.py").resolve()
                            script_path.write_text(code_to_run)
                            python_cmd = _python_for_venv(venv_root)
                            run_output = _stream_run_command(
                                env,
                                index_page_str,
                                f"{python_cmd} {script_path}",
                                cwd=target_base,
                                placeholder=stored_placeholder,
                            )
                        env_label = Path(venv_root).name if venv_root else "default env"
                        summary = _step_summary({"Q": entry.get("Q", ""), "C": code_to_run})
                        _push_run_log(
                            index_page_str,
                            f"Step {step + 1}: engine={engine}, env={env_label}, summary=\"{summary}\"",
                            stored_placeholder,
                        )
                        if run_output:
                            preview = run_output.strip()
                            if preview:
                                _push_run_log(
                                    index_page_str,
                                    f"Output (step {step + 1}):\n{preview}",
                                    stored_placeholder,
                                )
                                if "No such file or directory" in preview:
                                    _push_run_log(
                                        index_page_str,
                                        "Hint: the code tried to call a file that is not present in the export environment. "
                                        "Adjust the step to use a path that exists under the export/lab directory.",
                                        stored_placeholder,
                                    )
                        elif engine == "runpy":
                            _push_run_log(
                                index_page_str,
                                f"Output (step {step + 1}): runpy executed (no captured stdout)",
                                stored_placeholder,
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
                delete_snapshot = _capture_pipeline_snapshot(index_page_str, persisted_steps)
                delete_snapshot["label"] = f"remove step {step + 1}"
                delete_snapshot["timestamp"] = datetime.now().isoformat(timespec="seconds")
                st.session_state[delete_undo_key] = delete_snapshot
                selected_map.pop(step, None)
                remove_step(lab_dir, str(step), steps_file, index_page_str)
                st.rerun()

    _conceptual_source, conceptual_dot = load_pipeline_conceptual_dot(env, lab_dir)
    if conceptual_dot:
        with st.expander("Conceptual view", expanded=False):
            st.graphviz_chart(conceptual_dot, use_container_width=False)

    render_pipeline_view(
        persisted_steps,
        title="Execution view" if conceptual_dot else "Pipeline view",
    )

    for step, entry in enumerate(persisted_steps):
        _render_pipeline_step_fragment(step, entry)

    # Add-step expander to append a new step at the end
    new_q_key = f"{safe_prefix}_new_q"
    new_venv_key = f"{safe_prefix}_new_venv"
    if new_q_key not in st.session_state:
        st.session_state[new_q_key] = ""
    with st.expander("Add step", expanded=False):
        st.info(snippet_guidance)
        step_source = st.selectbox(
            "Step source",
            source_options,
            key=step_source_key,
            help="Select `gen step` to use the code generator, or choose an existing snippet to import as read-only.",
        )
        if step_source == "gen step":
            st.text_area(
                "Ask code generator:",
                key=new_q_key,
                placeholder="Enter a prompt describing the code you want generated",
                label_visibility="collapsed",
            )
            venv_labels = ["Use AGILAB environment"] + available_venvs
            selected_new_venv = st.selectbox(
                "venv",
                venv_labels,
                key=new_venv_key,
                help="Choose which virtual environment should execute this step.",
            )
            selected_path = "" if selected_new_venv == venv_labels[0] else normalize_runtime_path(selected_new_venv)
            run_new = st.button("Generate code", type="primary", use_container_width=True, key=f"{safe_prefix}_add_step_btn")
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
                except Exception as exc:
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
            import_new = st.button(
                "Add snippet",
                type="primary",
                use_container_width=True,
                key=f"{safe_prefix}_add_step_snippet_btn",
            )
            if import_new:
                if not snippet_code.strip():
                    st.warning("Selected snippet is empty.")
                else:
                    df_path = Path(st.session_state.df_file) if st.session_state.get("df_file") else Path()
                    new_idx = len(persisted_steps)
                    question = f"Imported snippet: {snippet_path.name if snippet_path else step_source}"
                    detail = f"Imported from {snippet_path}" if snippet_path else ""
                    answer = [df_path, question, "snippet", snippet_code, detail]
                    venv_map = selected_map.copy()
                    engine_map_local = engine_map.copy()
                    if manager_runtime:
                        venv_map[new_idx] = manager_runtime
                    else:
                        venv_map.pop(new_idx, None)
                    engine_map_local[new_idx] = "agi.run"
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
    st.subheader("Execution")
    st.caption("Choose the step order and run the pipeline. Experiment tracking is available separately from the sidebar.")
    if total_steps > 0:
        sequence_options = list(range(total_steps))
        summary_labels = {}
        for idx in sequence_options:
            label = _step_summary(persisted_steps[idx], width=80)
            summary_labels[idx] = label if label else f"{idx + 1}"
        stored_sequence = [idx for idx in st.session_state.get(sequence_state_key, sequence_options) if idx in sequence_options]
        if not stored_sequence:
            stored_sequence = sequence_options
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
            label = summary_labels.get(idx, f"{idx + 1}")
            return f"{idx + 1} {label}"

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

    run_all_clicked = st.button(
        "Run pipeline steps",
        key=f"{index_page_str}_run_all",
        help="Execute every step sequentially using its saved virtual environment.",
        type="secondary",
        use_container_width=True,
    )

    st.divider()
    st.subheader("Pipeline management")
    st.caption("Delete or restore the saved pipeline definition without affecting experiment tracking.")

    delete_all_col, cancel_col = st.columns(2)
    delete_all_clicked = False
    arm_delete_all_clicked = False
    cancel_delete_all_clicked = False
    delete_all_confirm_key = f"{index_page_str}_confirm_delete_all"
    with delete_all_col:
        if st.session_state.get(delete_all_confirm_key, False):
            delete_all_clicked = st.button(
                "Confirm delete all",
                key=f"{index_page_str}_delete_all_confirm",
                help="Permanently remove every step in this lab.",
                type="primary",
                use_container_width=True,
            )
        else:
            arm_delete_all_clicked = st.button(
                "Delete pipeline",
                key=f"{index_page_str}_delete_all",
                help="Remove every step in this lab.",
                type="secondary",
                use_container_width=True,
            )
    with cancel_col:
        if st.session_state.get(delete_all_confirm_key, False):
            cancel_delete_all_clicked = st.button(
                "Cancel",
                key=f"{index_page_str}_delete_all_cancel",
                type="secondary",
                use_container_width=True,
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
        undo_delete_clicked = st.button(
            f"Undo {undo_label}",
            key=f"{index_page_str}_undo_delete",
            help="Restore the pipeline state before the latest delete action.",
            type="secondary",
            use_container_width=True,
        )

    if undo_delete_clicked:
        restore_error = _restore_pipeline_snapshot(
            module_path,
            steps_file,
            index_page_str,
            sequence_widget_key,
            undo_payload,
        )
        if restore_error:
            st.error(f"Undo failed: {restore_error}")
        else:
            st.session_state.pop(delete_undo_key, None)
            st.success("Deleted steps restored.")
            st.rerun()

    if run_all_clicked:
        run_placeholder = _get_run_placeholder(index_page_str)
        log_file_path, log_error = _prepare_run_log_file(index_page_str, env, prefix="pipeline")
        if log_file_path:
            _push_run_log(
                index_page_str,
                f"Run pipeline started… logs will be saved to {log_file_path}",
                run_placeholder,
            )
        else:
            _push_run_log(
                index_page_str,
                f"Run pipeline started… (unable to prepare log file: {log_error})",
                run_placeholder,
            )
        # Collapse all step expanders after running the pipeline
        st.session_state[expander_state_key] = {}
        try:
            run_all_steps(lab_dir, index_page_str, steps_file, module_path, env, log_placeholder=run_placeholder)
        finally:
            st.session_state.pop(f"{index_page_str}__run_log_file", None)
        st.rerun()

    if delete_all_clicked:
        st.session_state.pop(delete_all_confirm_key, None)
        delete_snapshot = _capture_pipeline_snapshot(index_page_str, persisted_steps)
        delete_snapshot["label"] = "delete pipeline"
        delete_snapshot["timestamp"] = datetime.now().isoformat(timespec="seconds")
        st.session_state[delete_undo_key] = delete_snapshot
        total_steps = st.session_state[index_page_str][-1]
        for idx_remove in reversed(range(total_steps)):
            remove_step(lab_dir, str(idx_remove), steps_file, index_page_str)
        st.session_state[index_page_str] = [0, "", "", "", "", "", 0]
        st.session_state[f"{index_page_str}__details"] = {}
        st.session_state[f"{index_page_str}__venv_map"] = {}
        st.session_state[f"{index_page_str}__run_sequence"] = []
        st.session_state.pop(sequence_widget_key, None)
        st.session_state["lab_selected_venv"] = ""
        st.session_state[f"{index_page_str}__clear_q"] = True
        st.session_state[f"{index_page_str}__force_blank_q"] = True
        st.session_state[f"{index_page_str}__q_rev"] = st.session_state.get(f"{index_page_str}__q_rev", 0) + 1
        _bump_history_revision()
        _persist_sequence_preferences(module_path, steps_file, [])
        st.rerun()

    if st.session_state.pop("_experiment_reload_required", False):
        st.session_state.pop("loaded_df", None)

    if "loaded_df" not in st.session_state:
        df_source = st.session_state.get("df_file")
        st.session_state["loaded_df"] = (
            load_df_cached(Path(df_source)) if df_source else None
        )
    loaded_df = st.session_state["loaded_df"]
    if isinstance(loaded_df, pd.DataFrame) and not loaded_df.empty:
        st.dataframe(loaded_df)
    else:
        st.info(
            f"No data loaded yet. Generate and execute a step so the latest {DEFAULT_DF} appears under the Dataframe selector."
        )

    with st.expander("Run logs", expanded=True):
        clear_logs = st.button(
            "Clear logs",
            key=f"{index_page_str}__clear_logs_global",
            type="secondary",
            use_container_width=True,
        )
        if clear_logs:
            st.session_state[run_logs_key] = []
        log_placeholder = st.empty()
        st.session_state[run_placeholder_key] = log_placeholder
        logs = st.session_state.get(run_logs_key, [])
        if logs:
            log_placeholder.code("\n".join(logs))
        else:
            log_placeholder.caption("No runs recorded yet.")
        last_log_file = st.session_state.get(f"{index_page_str}__last_run_log_file")
        if last_log_file:
            st.caption(f"Most recent run log: {last_log_file}")
