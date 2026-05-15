from __future__ import annotations

import json
import os
import shutil
import stat
import importlib.util
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd
import streamlit as st
from code_editor import code_editor

try:
    import networkx as nx
    from networkx.readwrite import json_graph
except ModuleNotFoundError as exc:
    nx = None  # type: ignore[assignment]
    json_graph = None  # type: ignore[assignment]
    _NETWORKX_IMPORT_ERROR = exc
else:
    _NETWORKX_IMPORT_ERROR = None

try:
    import matplotlib.pyplot as plt
except ModuleNotFoundError as exc:
    plt = None  # type: ignore[assignment]
    _MATPLOTLIB_IMPORT_ERROR = exc
else:
    _MATPLOTLIB_IMPORT_ERROR = None

_NETWORKX_ERROR_TYPE = getattr(nx, "NetworkXError", RuntimeError) if nx is not None else RuntimeError
_PREVIEW_LOAD_EXCEPTIONS = (OSError, RuntimeError, TypeError, ValueError, _NETWORKX_ERROR_TYPE)


def _networkx_unavailable_message() -> str:
    return (
        f"networkx unavailable: {_NETWORKX_IMPORT_ERROR}. "
        "Install the UI dependencies with `pip install 'agilab[ui]'` or run `uv sync --extra ui`."
    )


def _require_networkx():
    if nx is None:
        raise RuntimeError(_networkx_unavailable_message())
    return nx


def _is_networkx_graph(value: object) -> bool:
    return nx is not None and isinstance(value, nx.Graph)


from agi_env import AgiEnv
from agi_gui.pagelib import cached_load_df, find_files, open_new_tab, render_dataframe_preview, save_csv

_import_guard_path = Path(__file__).resolve().parent / "import_guard.py"
_import_guard_spec = importlib.util.spec_from_file_location("agilab_import_guard_local", _import_guard_path)
if _import_guard_spec is None or _import_guard_spec.loader is None:
    raise ModuleNotFoundError(f"Unable to load import_guard.py from {_import_guard_path}")
_import_guard_module = importlib.util.module_from_spec(_import_guard_spec)
_import_guard_spec.loader.exec_module(_import_guard_module)
import_agilab_module = _import_guard_module.import_agilab_module

_orchestrate_page_state = import_agilab_module(
    "agilab.orchestrate_page_state",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "orchestrate_page_state.py",
    fallback_name="agilab_orchestrate_page_state_fallback",
)
build_orchestrate_execute_workflow_state = _orchestrate_page_state.build_orchestrate_execute_workflow_state
build_orchestrate_run_artifact_state = _orchestrate_page_state.build_orchestrate_run_artifact_state

_pinned_expander = import_agilab_module(
    "agilab.pinned_expander",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "pinned_expander.py",
    fallback_name="agilab_pinned_expander_fallback",
)
render_pinnable_code_editor = _pinned_expander.render_pinnable_code_editor

_workflow_ui = import_agilab_module(
    "agilab.workflow_ui",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "workflow_ui.py",
    fallback_name="agilab_workflow_ui_fallback",
)
render_action_readiness = _workflow_ui.render_action_readiness
is_dag_based_app = _workflow_ui.is_dag_based_app
is_dag_worker_base = _workflow_ui.is_dag_worker_base
record_action_history = _workflow_ui.record_action_history
render_action_history = _workflow_ui.render_action_history
render_artifact_drawer = _workflow_ui.render_artifact_drawer
render_latest_outputs = _workflow_ui.render_latest_outputs
render_latest_run_card = _workflow_ui.render_latest_run_card
render_log_actions = _workflow_ui.render_log_actions
render_workflow_timeline = _workflow_ui.render_workflow_timeline

_pending_actions = import_agilab_module(
    "agilab.orchestrate_pending_actions",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "orchestrate_pending_actions.py",
    fallback_name="agilab_orchestrate_pending_actions_fallback",
)

PENDING_EXECUTE_ACTION_KEY = _pending_actions.PENDING_EXECUTE_ACTION_KEY
EXECUTE_NOTICE_KEY = "_orchestrate_execute_notice"
RUN_LOGS_PIN_ID = "orchestrate_run_logs"
PREVIEW_FILE_PATTERNS = ("*.parquet", "*.csv", "*.json", "*.gml")
PREVIEW_MAX_SEARCH_FILES = int(os.environ.get("AGILAB_PREVIEW_MAX_SEARCH_FILES", "1000"))
PREVIEW_MAX_FILE_BYTES = int(os.environ.get("AGILAB_PREVIEW_MAX_FILE_BYTES", str(25 * 1024 * 1024)))
PREVIEW_METADATA_FILENAMES = {"run_manifest.json", "notebook_import_view_plan.json"}
PREVIEW_METADATA_PREFIXES = ("._", "reduce_summary_worker_")
RUN_FATAL_STDERR_PATTERNS = (
    "No virtual environment found",
    "Command failed",
    "Traceback",
    "RuntimeError:",
    "FileNotFoundError:",
    "ModuleNotFoundError:",
    "ImportError:",
    "Process exited with non-zero",
    "non-zero exit status",
)


@dataclass(frozen=True)
class OrchestrateExecuteDeps:
    clear_log: Callable[[], None]
    update_log: Callable[..., None]
    strip_ansi: Callable[[str], str]
    reset_traceback_skip: Callable[[], None]
    append_log_lines: Callable[[list[str], str], None]
    display_log: Callable[[str, str], None]
    rerun_fragment_or_app: Callable[[], None]
    update_delete_confirm_state: Callable[..., bool]
    capture_dataframe_preview_state: Callable[[], dict[str, Any]]
    restore_dataframe_preview_state: Callable[[dict[str, Any]], None]
    generate_profile_report: Callable[[pd.DataFrame], Any]
    log_display_max_lines: int
    live_log_min_height: int
    install_log_height: int

    def __replace__(self, **changes: Any) -> "OrchestrateExecuteDeps":
        return replace(self, **changes)


def collect_candidate_roots(env: Any, active_args: dict[str, Any] | None) -> list[Path]:
    candidate_roots: list[Path] = []

    def _resolve_root(
        raw_path: Path | str,
        *,
        prefer_share: bool,
        require_share: bool = False,
    ) -> Path:
        path = Path(raw_path).expanduser()
        if path.is_absolute():
            return path
        if prefer_share:
            resolve_share_path = getattr(env, "resolve_share_path", None)
            if callable(resolve_share_path):
                try:
                    return Path(resolve_share_path(path)).expanduser()
                except (OSError, TypeError, ValueError):
                    if require_share:
                        raise
        return Path.home() / path

    def _attach_root(
        raw_path: Optional[Path | str],
        *,
        prefer_share: bool = False,
        require_share: bool = False,
    ) -> None:
        if not raw_path:
            return
        try:
            candidate_roots.append(
                _resolve_root(
                    raw_path,
                    prefer_share=prefer_share,
                    require_share=require_share,
                ),
            )
        except (OSError, TypeError, ValueError):
            if require_share and prefer_share:
                return
            candidate_roots.append(Path.home() / Path(raw_path).expanduser())

    _attach_root(getattr(env, "dataframe_path", None))

    if isinstance(active_args, dict):
        _attach_root(active_args.get("data_out"), prefer_share=True)

    _attach_root(getattr(env, "app_data_rel", None))

    if isinstance(active_args, dict):
        _attach_root(active_args.get("data_in"), prefer_share=True, require_share=True)

    unique_roots: list[Path] = []
    seen_roots: set[str] = set()
    for root in candidate_roots:
        key = str(root.resolve()) if root.exists() else str(root)
        if key not in seen_roots:
            seen_roots.add(key)
            unique_roots.append(root)
    return unique_roots


def _run_stderr_indicates_failure(stderr: Any) -> bool:
    """Return whether returned stderr represents a failed AGILAB run."""
    text = str(stderr or "")
    return bool(text.strip()) and any(pattern in text for pattern in RUN_FATAL_STDERR_PATTERNS)


def _preview_candidate_paths(candidate_roots: list[Path]) -> list[Path]:
    search_files: list[Path] = []
    seen_files: set[str] = set()

    def _append_candidate(candidate: Path) -> bool:
        if len(search_files) >= PREVIEW_MAX_SEARCH_FILES:
            return False
        key = str(candidate)
        if key in seen_files:
            return True
        seen_files.add(key)
        search_files.append(candidate)
        return True

    for root in candidate_roots:
        if root.is_dir():
            for pattern in PREVIEW_FILE_PATTERNS:
                for candidate in sorted(root.rglob(pattern), key=lambda path: str(path)):
                    if not _append_candidate(candidate):
                        return search_files
        elif root.is_file():
            if not _append_candidate(root):
                return search_files
    return search_files


def _is_preview_metadata_file(file_path: Path) -> bool:
    name = file_path.name
    return name in PREVIEW_METADATA_FILENAMES or any(name.startswith(prefix) for prefix in PREVIEW_METADATA_PREFIXES)


def find_preview_target(candidate_roots: list[Path]) -> tuple[Optional[Path], list[Path]]:
    search_files = _preview_candidate_paths(candidate_roots)

    filtered_records: list[tuple[Path, float]] = []
    for file_path in search_files:
        if _is_preview_metadata_file(file_path):
            continue
        try:
            file_stat = file_path.stat()
        except (FileNotFoundError, OSError):
            continue
        if not stat.S_ISREG(file_stat.st_mode):
            continue
        if file_stat.st_size <= 0 or file_stat.st_size > PREVIEW_MAX_FILE_BYTES:
            continue
        filtered_records.append((file_path, file_stat.st_mtime))

    if not filtered_records:
        return None, []

    filtered_files = [file_path for file_path, _mtime in filtered_records]
    target_file = max(filtered_records, key=lambda item: (item[1], str(item[0])))[0]
    try:
        target_file.stat()
    except (FileNotFoundError, OSError):
        return None, filtered_files
    return target_file, filtered_files


def queue_pending_execute_action(session_state, action: str) -> None:
    _pending_actions.queue_pending_execute_action(session_state, action)


def consume_pending_execute_action(session_state) -> Optional[str]:
    return _pending_actions.consume_pending_execute_action(session_state)


def queue_execute_notice(session_state, *, kind: str, message: str) -> None:
    if kind not in {"success", "info", "warning", "error"}:
        kind = "info"
    session_state[EXECUTE_NOTICE_KEY] = {"kind": kind, "message": message}


def _is_dag_based_app(env: Any, app_state_name: str) -> bool:
    return is_dag_based_app(env, app_state_name)


def render_execute_notice(streamlit_api, session_state) -> None:
    notice = session_state.pop(EXECUTE_NOTICE_KEY, None)
    if not isinstance(notice, dict):
        return
    message = str(notice.get("message") or "").strip()
    if not message:
        return
    renderer = getattr(streamlit_api, str(notice.get("kind") or "info"), None)
    if not callable(renderer):
        renderer = streamlit_api.info
    renderer(message)


def _render_graph_preview(graph_preview: "nx.Graph", source_preview_name: Optional[str]) -> None:
    nx_module = _require_networkx()
    if plt is None:
        raise RuntimeError(
            f"matplotlib unavailable: {_MATPLOTLIB_IMPORT_ERROR}. "
            "Install the optional visualization dependencies with `pip install 'agilab[viz]'`."
        )

    st.caption("Graph preview generated from JSON output")
    fig, ax = plt.subplots(figsize=(8, 6))
    pos = nx_module.spring_layout(graph_preview, seed=42)
    nx_module.draw_networkx_nodes(graph_preview, pos, node_color="skyblue", ax=ax)
    nx_module.draw_networkx_edges(graph_preview, pos, ax=ax, alpha=0.5)
    nx_module.draw_networkx_labels(graph_preview, pos, ax=ax, font_size=9)
    ax.axis("off")
    st.pyplot(fig, width="stretch")
    plt.close(fig)
    if source_preview_name:
        st.caption(f"Source: {source_preview_name}")


async def render_execute_section(
    *,
    env: AgiEnv,
    project_path: Path,
    app_state_name: str,
    controls_visible: bool,
    show_run_panel: bool,
    cmd: Optional[str],
    deps: OrchestrateExecuteDeps,
) -> None:
    clear_log = deps.clear_log
    update_log = deps.update_log
    strip_ansi = deps.strip_ansi
    _reset_traceback_skip = deps.reset_traceback_skip
    _append_log_lines = deps.append_log_lines
    display_log = deps.display_log
    _rerun_fragment_or_app = deps.rerun_fragment_or_app
    _update_delete_confirm_state = deps.update_delete_confirm_state
    _capture_dataframe_preview_state = deps.capture_dataframe_preview_state
    _restore_dataframe_preview_state = deps.restore_dataframe_preview_state
    generate_profile_report = deps.generate_profile_report
    LOG_DISPLAY_MAX_LINES = deps.log_display_max_lines
    LIVE_LOG_MIN_HEIGHT = deps.live_log_min_height
    INSTALL_LOG_HEIGHT = deps.install_log_height
    execute_state = build_orchestrate_execute_workflow_state(
        show_run_panel=show_run_panel,
        cmd=cmd,
        project_path=project_path,
        worker_env_path=getattr(env, "wenv_abs", None),
    )
    dag_based_app = _is_dag_based_app(env, app_state_name)

    existing_run_log = st.session_state.get("run_log_cache", "").strip()
    run_log_expander = None
    log_container = None
    if controls_visible:
        render_execute_notice(st, st.session_state)

    def _run_log_pin_title() -> str:
        app_name = str(getattr(env, "app", "") or "project")
        return f"Run logs: {app_name}"

    def _run_log_source() -> str:
        log_path = str(st.session_state.get("last_run_log_path") or "").strip()
        return f"ORCHESTRATE {log_path}" if log_path else "ORCHESTRATE"

    def _render_run_log_viewer(log_text: str, *, key: str) -> None:
        render_pinnable_code_editor(
            st,
            code_editor,
            RUN_LOGS_PIN_ID,
            title=_run_log_pin_title(),
            body=log_text,
            key=key,
            body_format="code",
            language="text",
            source=_run_log_source(),
            empty_message="No run logs yet.",
            info_name="Run logs",
            theme="dark",
        )

    def _ensure_run_log_expander(*, expanded: bool):
        nonlocal run_log_expander, log_container
        if run_log_expander is None:
            if log_container is None:
                log_container = st.container()
            with log_container:
                run_log_expander = st.expander("Run logs", expanded=expanded)
        return run_log_expander

    async def _execute_with_logging(current_expander):
        clear_log()
        st.session_state["run_log_cache"] = ""
        st.session_state["_last_execute_failed"] = False
        target_expander = current_expander or _ensure_run_log_expander(expanded=True)
        with target_expander:
            log_placeholder = st.empty()
        _reset_traceback_skip()
        log_dir = Path(env.runenv or (Path.home() / "log" / "execute" / env.app))
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file_path = log_dir / f"run_{timestamp}.log"
        st.session_state["last_run_log_path"] = str(log_file_path)

        async def _run_and_stream():
            nonlocal log_file_path
            runtime_root = Path(project_path)
            with log_file_path.open("w", encoding="utf-8") as log_file:
                def _fanout(message: str) -> None:
                    clean = strip_ansi(message or "").rstrip()
                    if clean:
                        log_file.write(clean + "\n")
                        log_file.flush()
                    update_log(log_placeholder, message)

                _, stderr_text = await env.run_agi(
                    cmd.replace("asyncio.run(main())", env.snippet_tail),
                    log_callback=_fanout,
                    venv=runtime_root,
                )
                return stderr_text

        run_error: Exception | None = None
        stderr = ""
        with st.spinner("Running AGI..."):
            try:
                stderr = await _run_and_stream()
            except (RuntimeError, OSError, TypeError, ValueError, AttributeError, KeyError) as exc:
                run_error = exc
                stderr = str(exc)
                st.session_state["_last_execute_failed"] = True
            st.session_state["run_log_cache"] = st.session_state.get("log_text", "")
        fatal_stderr = _run_stderr_indicates_failure(stderr)
        if fatal_stderr:
            st.session_state["_last_execute_failed"] = True
        with target_expander:
            log_placeholder.empty()
            log_body = st.session_state["run_log_cache"]
            if run_error is not None or fatal_stderr:
                st.error("AGI execution failed.")
                if log_body:
                    st.caption("Full run diagnostic")
                    st.code(log_body, language="text")
                if str(stderr or "").strip() and str(stderr).strip() not in log_body:
                    st.caption("Execution error")
                    st.code(str(stderr), language="text")
            elif str(stderr or "").strip():
                display_log(log_body, stderr)
            else:
                _render_run_log_viewer(log_body, key="orchestrate_run_logs_editor")
            st.caption(f"Logs saved to {log_file_path}")
            if render_log_actions(
                st,
                body=log_body,
                download_key="orchestrate_run_logs_download",
                file_name=f"{getattr(env, 'app', 'agilab')}_run.log",
                clear_key="orchestrate_run_logs_clear",
            ):
                record_action_history(
                    st.session_state,
                    page_label="ORCHESTRATE",
                    env=env,
                    title="Run logs cleared",
                    status="info",
                )
                st.session_state["run_log_cache"] = ""
                st.session_state["log_text"] = ""
                st.rerun()
        if run_error is not None or fatal_stderr:
            record_action_history(
                st.session_state,
                page_label="ORCHESTRATE",
                env=env,
                title="Run failed",
                status="error",
                detail=f"Logs saved to {log_file_path}",
                artifact=log_file_path,
            )
        else:
            record_action_history(
                st.session_state,
                page_label="ORCHESTRATE",
                env=env,
                title="Run finished",
                status="done",
                detail=f"Logs saved to {log_file_path}",
                artifact=log_file_path,
            )
        st.session_state["dataframe_deleted"] = False
        return target_expander

    delete_confirm_key = "delete_data_main_confirm"
    delete_undo_key = "delete_data_main_undo_payload"
    def _queue_execute_action(action: str) -> None:
        queue_pending_execute_action(st.session_state, action)
        st.rerun()

    def _current_artifact_state():
        return build_orchestrate_run_artifact_state(
            show_run_panel=show_run_panel,
            loaded_dataframe=st.session_state.get("loaded_df"),
            loaded_graph=st.session_state.get("loaded_graph"),
            loaded_source_path=st.session_state.get("loaded_source_path"),
            dataframe_deleted=bool(st.session_state.get("dataframe_deleted")),
        )

    @st.fragment
    def _render_run_panel_controls() -> None:
        artifact_state = _current_artifact_state()
        if show_run_panel:
            run_label = (
                "Run workflow"
                if dag_based_app
                else ("Run benchmark" if st.session_state.get("benchmark") else "Run")
            )
            readiness_actions = [
                (
                    run_label,
                    execute_state.run_action.enabled,
                    execute_state.run_action.disabled_reason,
                )
            ]
            if not dag_based_app:
                readiness_actions.extend(
                    [
                        ("Load output", artifact_state.load_action.enabled, artifact_state.load_action.disabled_reason),
                        ("Export dataframe", artifact_state.export_action.enabled, artifact_state.export_action.disabled_reason),
                    ]
                )
            render_action_readiness(st, actions=tuple(readiness_actions))
            if dag_based_app:
                (run_col,) = st.columns(1)
                load_col = delete_col = None
            else:
                run_col, load_col, delete_col = st.columns(3)
            if run_col.button(
                run_label,
                key="run_btn",
                type="primary",
                disabled=not execute_state.run_action.enabled,
                help=execute_state.run_action.disabled_reason
                or ("Run the selected DAG workflow." if dag_based_app else "Run the configured AGILAB command."),
                width="stretch",
            ):
                _queue_execute_action("run")

            if not dag_based_app and load_col is not None and load_col.button(
                "Load output",
                key="load_data_main",
                type="primary",
                disabled=not artifact_state.load_action.enabled,
                width="stretch",
                help=artifact_state.load_action.disabled_reason or "Fetch the latest dataframe preview for export",
            ):
                _queue_execute_action("load")

            delete_armed_clicked = False
            delete_cancel_clicked = False
            if dag_based_app:
                st.session_state.pop(delete_confirm_key, None)
            elif st.session_state.get(delete_confirm_key, False):
                if delete_col.button(
                    "Confirm delete",
                    key="delete_data_main_confirm_btn",
                    type="primary",
                    width="stretch",
                    help="Confirm deletion of the loaded dataframe/export file.",
                ):
                    _queue_execute_action("delete")
                delete_cancel_clicked = delete_col.button(
                    "Cancel",
                    key="delete_data_main_cancel_btn",
                    type="secondary",
                    width="stretch",
                )
            elif delete_col is not None:
                delete_armed_clicked = delete_col.button(
                    "Delete output",
                    key="delete_data_main",
                    type="secondary",
                    disabled=not artifact_state.delete_action.enabled,
                    width="stretch",
                    help=artifact_state.delete_action.disabled_reason
                    or "Clear the cached dataframe preview so the next load reflects a fresh EXECUTE run.",
                )

            if not dag_based_app and _update_delete_confirm_state(
                delete_confirm_key,
                delete_armed_clicked=delete_armed_clicked,
                delete_cancel_clicked=delete_cancel_clicked,
            ):
                _rerun_fragment_or_app()

            undo_delete_clicked = False
            undo_payload = st.session_state.get(delete_undo_key)
            if not dag_based_app and isinstance(undo_payload, dict):
                undo_delete_clicked = st.button(
                    "Undo last delete",
                    key="delete_data_main_undo_btn",
                    type="secondary",
                    width="stretch",
                    help="Restore the most recently deleted dataframe preview and file.",
                )

            if undo_delete_clicked and isinstance(undo_payload, dict):
                restored_file = False
                backup_file = undo_payload.get("backup_file")
                source_file = undo_payload.get("source_file")
                if backup_file and source_file:
                    backup_path = Path(backup_file)
                    source_path = Path(source_file)
                    try:
                        if backup_path.exists():
                            source_path.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(backup_path), str(source_path))
                            restored_file = True
                        elif not source_path.exists():
                            st.warning("Undo could not restore file from disk backup (backup not found).")
                    except OSError as exc:
                        st.error(f"Failed to restore deleted file: {exc}")

                _restore_dataframe_preview_state(undo_payload)
                st.session_state["dataframe_deleted"] = False
                st.session_state.pop(delete_undo_key, None)
                st.session_state.pop(delete_confirm_key, None)
                try:
                    cached_load_df.clear()
                except (AttributeError, RuntimeError):
                    pass
                try:
                    find_files.clear()
                except (AttributeError, RuntimeError):
                    pass
                if restored_file:
                    st.success("Dataframe delete undone and file restored.")
                else:
                    st.success("Dataframe preview restore completed.")
                _rerun_fragment_or_app()

            if not dag_based_app and st.button(
                "Run -> Load -> Export",
                key="combo_exec_load_export",
                type="primary",
                disabled=not execute_state.combo_action.enabled,
                help=execute_state.combo_action.disabled_reason
                or "Run the workflow, load the latest previewable output, and export tabular output when available.",
                width="stretch",
            ):
                _queue_execute_action("combo")
        else:
            st.info("`Serve` mode selected. Switch to `Run now` to access EXECUTE / LOAD actions.")
            st.session_state.pop("_combo_load_trigger", None)
            st.session_state.pop("_combo_export_trigger", None)
            st.session_state.pop(delete_confirm_key, None)

    if controls_visible:
        st.markdown("#### 5. Execute and inspect outputs")
        if dag_based_app:
            st.caption("Run the selected DAG workflow. Inspect stage artifacts and run evidence from WORKFLOW.")
        else:
            st.caption("Run the configured command, load the latest previewable output, and export tabular data when available.")
        _render_run_panel_controls()
    else:
        pending_hidden_action = consume_pending_execute_action(st.session_state)
        if pending_hidden_action:
            st.error("RUN is not available yet. Run INSTALL first, then retry RUN.")

    pending_action = consume_pending_execute_action(st.session_state)
    run_clicked = pending_action == "run"
    if dag_based_app:
        st.session_state.pop("_combo_load_trigger", None)
        st.session_state.pop("_combo_export_trigger", None)
        load_clicked = False
        delete_clicked = False
        combo_clicked = False
    else:
        load_clicked = pending_action == "load" or st.session_state.pop("_combo_load_trigger", False)
        delete_clicked = pending_action == "delete"
        combo_clicked = pending_action == "combo"

    if show_run_panel and load_clicked:
        load_action = _current_artifact_state().load_action
        if st.session_state.get("_last_execute_failed"):
            st.info("Latest EXECUTE failed. Check Run logs, fix the failure, then rerun before loading output.")
        elif not load_action.enabled:
            st.info(load_action.disabled_reason)
        else:
            active_args = st.session_state.app_settings.get("args", {})
            candidate_roots = collect_candidate_roots(env, active_args if isinstance(active_args, dict) else {})
            target_file, search_files = find_preview_target(candidate_roots)

            if not target_file:
                st.warning(
                    "No previewable output found yet. Run the workflow to generate stage artifacts, "
                    "then return here to inspect them."
                )
            else:
                st.session_state["loaded_source_path"] = target_file
                suffix = target_file.suffix.lower()
                loaded_output_changed = False
                load_notice: tuple[str, str] | None = None
                try:
                    if suffix in {".csv", ".parquet"}:
                        latest_mtime = target_file.stat().st_mtime
                        batch_window = st.session_state.get("export_batch_window_seconds", 600)
                        try:
                            batch_window = int(batch_window)
                        except (TypeError, ValueError):
                            batch_window = 600

                        candidate_batch = sorted(
                            {
                                target_file,
                                *[
                                    file_path
                                    for file_path in search_files
                                    if file_path.suffix.lower() == suffix
                                    and file_path.parent == target_file.parent
                                    and abs(latest_mtime - file_path.stat().st_mtime) <= batch_window
                                ],
                            },
                            key=lambda p: p.stat().st_mtime,
                        )

                        frames = []
                        for file_path in candidate_batch:
                            df_piece = cached_load_df(file_path, with_index=False, nrows=0)
                            if isinstance(df_piece, pd.DataFrame) and not df_piece.empty:
                                df_piece = df_piece.copy()
                                df_piece["__source__"] = file_path.name
                                frames.append(df_piece)

                        loaded_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

                        if isinstance(loaded_df, pd.DataFrame) and not loaded_df.empty:
                            st.session_state["loaded_df"] = loaded_df
                            st.session_state["_force_export_open"] = True
                            st.session_state.pop("loaded_graph", None)
                            loaded_output_changed = True
                            if len(candidate_batch) > 1:
                                message = (
                                    f"Loaded dataframe preview from {len(candidate_batch)} files "
                                    f"(latest: {target_file.name})."
                                )
                                st.success(message)
                                load_notice = ("success", message)
                            else:
                                message = f"Loaded dataframe preview from {target_file.name}."
                                st.success(message)
                                load_notice = ("success", message)
                        else:
                            st.warning(f"{target_file.name} is empty; nothing to preview.")
                    elif suffix == ".json":
                        payload = json.loads(target_file.read_text())
                        if isinstance(payload, dict) and "nodes" in payload and "links" in payload:
                            if json_graph is None:
                                raise RuntimeError(_networkx_unavailable_message())
                            graph = json_graph.node_link_graph(payload, directed=payload.get("directed", True))
                            st.session_state["loaded_df"] = None
                            st.session_state["_force_export_open"] = False
                            st.session_state["loaded_graph"] = graph
                            loaded_output_changed = True
                            message = f"Loaded network graph from {target_file.name}."
                            st.success(message)
                            load_notice = ("success", message)
                        else:
                            loaded_df = pd.json_normalize(payload)
                            st.session_state["loaded_df"] = loaded_df
                            st.session_state["_force_export_open"] = True
                            st.session_state.pop("loaded_graph", None)
                            loaded_output_changed = True
                            message = f"Parsed JSON payload as tabular data from {target_file.name}."
                            st.info(message)
                            load_notice = ("info", message)
                    elif suffix == ".gml":
                        nx_module = _require_networkx()
                        graph = nx_module.read_gml(target_file)
                        edge_df = nx_module.to_pandas_edgelist(graph)
                        if not edge_df.empty:
                            st.session_state["loaded_df"] = edge_df
                            st.session_state["_force_export_open"] = True
                            st.session_state["loaded_graph"] = graph
                            loaded_output_changed = True
                            message = f"Loaded topology edges from {target_file.name}."
                            st.success(message)
                            load_notice = ("success", message)
                        else:
                            node_df = pd.DataFrame(
                                [(node, data) for node, data in graph.nodes(data=True)],
                                columns=["node", "attributes"],
                            )
                            if node_df.empty:
                                st.warning(f"{target_file.name} did not contain edges or node attributes to display.")
                            else:
                                st.session_state["loaded_df"] = node_df
                                st.session_state["_force_export_open"] = True
                                st.session_state["loaded_graph"] = graph
                                loaded_output_changed = True
                                message = f"Showing node metadata from {target_file.name}."
                                st.info(message)
                                load_notice = ("info", message)
                    else:
                        st.warning(f"Unsupported file format: {target_file.suffix}")
                except json.JSONDecodeError as exc:
                    st.error(f"Failed to decode JSON from {target_file.name}: {exc}")
                except _PREVIEW_LOAD_EXCEPTIONS as exc:
                    st.error(f"Unable to load {target_file.name}: {exc}")
                if loaded_output_changed:
                    if load_notice:
                        queue_execute_notice(st.session_state, kind=load_notice[0], message=load_notice[1])
                    record_action_history(
                        st.session_state,
                        page_label="ORCHESTRATE",
                        env=env,
                        title="Output loaded",
                        status="done",
                        detail=f"Previewing {target_file.name}",
                        artifact=target_file,
                    )
                    st.session_state["dataframe_deleted"] = False
                    _rerun_fragment_or_app()

    if show_run_panel and delete_clicked:
        delete_action = _current_artifact_state().delete_action
        if not delete_action.enabled:
            st.info(delete_action.disabled_reason)
            delete_clicked = False

    if show_run_panel and delete_clicked:
        st.session_state.pop(delete_confirm_key, None)
        undo_payload = _capture_dataframe_preview_state()
        undo_payload["deleted_at"] = datetime.now().isoformat(timespec="seconds")
        st.session_state["dataframe_deleted"] = True
        source_path = st.session_state.get("loaded_source_path")
        undo_payload["source_file"] = str(source_path) if source_path else ""
        undo_payload["backup_file"] = ""
        st.session_state.pop("loaded_source_path", None)
        st.session_state["loaded_df"] = None
        st.session_state.pop("df_cols", None)
        st.session_state.pop("selected_cols", None)
        st.session_state["check_all"] = False
        st.session_state["_force_export_open"] = False
        st.session_state.pop("loaded_graph", None)

        deleted = False
        if source_path:
            file_path = Path(source_path)
            try:
                if file_path.exists():
                    trash_dir = file_path.parent / ".agilab-trash"
                    trash_dir.mkdir(parents=True, exist_ok=True)
                    backup_name = f"{file_path.name}.{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.bak"
                    backup_path = trash_dir / backup_name
                    shutil.move(str(file_path), str(backup_path))
                    undo_payload["backup_file"] = str(backup_path)
                    try:
                        cached_load_df.clear()
                    except (AttributeError, RuntimeError):
                        pass
                    try:
                        find_files.clear()
                    except (AttributeError, RuntimeError):
                        pass
                    st.success(f"Deleted {file_path.name} from disk.")
                    deleted = True
                else:
                    st.info("Loaded file already removed from disk.")
            except OSError as exc:
                st.error(f"Failed to delete {file_path}: {exc}")

        if not deleted:
            st.info("Dataframe preview cleared. Run EXECUTE then LOAD to refresh with new output.")
        st.session_state[delete_undo_key] = undo_payload

    if show_run_panel and run_clicked:
        run_action = execute_state.run_action
        if run_action.enabled:
            run_log_expander = await _execute_with_logging(run_log_expander)
            if st.session_state.get("benchmark") and not st.session_state.get("_last_execute_failed"):
                st.session_state["_benchmark_expand"] = True
                st.rerun()
        else:
            st.error(run_action.disabled_reason)

    if show_run_panel and combo_clicked:
        combo_action = execute_state.combo_action
        if combo_action.enabled:
            run_log_expander = await _execute_with_logging(run_log_expander)
            if not st.session_state.get("_last_execute_failed"):
                st.session_state["_combo_load_trigger"] = True
                st.session_state["_combo_export_trigger"] = True
                st.rerun()
        else:
            st.error(combo_action.disabled_reason)

    if show_run_panel and run_log_expander is None:
        expander = _ensure_run_log_expander(expanded=False)
        with expander:
            _render_run_log_viewer(
                existing_run_log,
                key="orchestrate_run_logs_editor_existing",
            )
            if render_log_actions(
                st,
                body=existing_run_log,
                download_key="orchestrate_run_logs_download_existing",
                file_name=f"{getattr(env, 'app', 'agilab')}_run.log",
                clear_key="orchestrate_run_logs_clear_existing",
            ):
                record_action_history(
                    st.session_state,
                    page_label="ORCHESTRATE",
                    env=env,
                    title="Run logs cleared",
                    status="info",
                )
                st.session_state["run_log_cache"] = ""
                st.session_state["log_text"] = ""
                st.rerun()

    df_preview = st.session_state.get("loaded_df")
    graph_preview = st.session_state.get("loaded_graph")
    source_preview_path = st.session_state.get("loaded_source_path")
    source_preview_name = None
    if source_preview_path:
        try:
            source_preview_name = Path(source_preview_path).name
        except (OSError, RuntimeError, TypeError, ValueError):
            source_preview_name = str(source_preview_path)

    latest_log_path = st.session_state.get("last_run_log_path")
    current_artifact_state = _current_artifact_state()
    timeline_items = [
        {
            "label": "Configure",
            "state": "done" if cmd else "blocked",
            "detail": str(project_path),
        },
        {
            "label": "Run workflow" if dag_based_app else "Run",
            "state": "done" if latest_log_path or existing_run_log else (
                "ready" if execute_state.run_action.enabled else "blocked"
            ),
            "detail": execute_state.run_action.disabled_reason or "",
        },
    ]
    if not dag_based_app:
        timeline_items.extend(
            [
                {
                    "label": "Load output",
                    "state": "done" if source_preview_path else (
                        "ready" if current_artifact_state.load_action.enabled else "waiting"
                    ),
                    "detail": current_artifact_state.load_action.disabled_reason or "",
                },
                {
                    "label": "Export",
                    "state": "ready" if current_artifact_state.export_action.enabled else "waiting",
                    "detail": current_artifact_state.export_action.disabled_reason or "",
                },
            ]
        )
    render_workflow_timeline(st, items=tuple(timeline_items))
    render_latest_run_card(
        st,
        status="done" if latest_log_path or existing_run_log else "waiting",
        output_path=source_preview_path,
        log_path=latest_log_path,
        key_prefix=f"orchestrate:{app_state_name}",
    )
    artifacts = [
        {"label": "Loaded output", "path": source_preview_path, "kind": "output", "preview": False},
        {"label": "Run log", "path": latest_log_path, "kind": "log"},
    ]
    if not dag_based_app:
        artifacts.extend(
            [
                {"label": "Export target", "path": st.session_state.get("df_export_file"), "kind": "csv", "preview": False},
                {
                    "label": "Profile report",
                    "path": st.session_state.get("profile_report_file"),
                    "kind": "html",
                    "preview": False,
                },
            ]
        )
    render_artifact_drawer(st, artifacts=tuple(artifacts), key_prefix=f"orchestrate:{app_state_name}")
    render_action_history(
        st,
        session_state=st.session_state,
        page_label="ORCHESTRATE",
        env=env,
    )
    render_latest_outputs(
        st,
        source_path=source_preview_path,
        dataframe=df_preview,
        graph=graph_preview,
        key_prefix=f"orchestrate:{app_state_name}",
    )

    if isinstance(df_preview, pd.DataFrame) and not df_preview.empty:
        render_dataframe_preview(
            df_preview,
            truncation_label="Browser preview limited",
        )
        if source_preview_name:
            st.caption(f"Previewing {source_preview_name}")
    elif _is_networkx_graph(graph_preview):
        try:
            _render_graph_preview(graph_preview, source_preview_name)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            st.error(f"Unable to render graph preview: {exc}")

    export_expanded = st.session_state.pop("_force_export_open", False)
    loaded_df = st.session_state.get("loaded_df")
    artifact_state = _current_artifact_state()

    if (
        not dag_based_app
        and artifact_state.export_action.enabled
        and isinstance(loaded_df, pd.DataFrame)
        and not loaded_df.empty
    ):
        expander = st.expander("Prepare data for experiment and exploration", expanded=export_expanded)
        with expander:
            loaded_df.columns = [
                col if col.strip() != "" else f"Unnamed Column {idx}"
                for idx, col in enumerate(loaded_df.columns)
            ]

            if (
                "export_tab_previous_project" not in st.session_state
                or st.session_state.export_tab_previous_project != app_state_name
                or st.session_state.get("df_cols") != loaded_df.columns.tolist()
            ):
                st.session_state.export_tab_previous_project = app_state_name
                st.session_state.df_cols = loaded_df.columns.tolist()
                st.session_state.selected_cols = loaded_df.columns.tolist()
                st.session_state.check_all = True

            if st.session_state.pop("_reset_export_checkboxes", False):
                st.session_state.selected_cols = st.session_state.df_cols.copy()
                st.session_state.check_all = True
                for idx in range(len(st.session_state.df_cols)):
                    st.session_state[f"export_col_{idx}"] = True
                st.session_state["_force_export_open"] = True

            def on_select_all_changed():
                st.session_state.selected_cols = (
                    st.session_state.df_cols.copy() if st.session_state.check_all else []
                )
                for idx in range(len(st.session_state.df_cols)):
                    st.session_state[f"export_col_{idx}"] = st.session_state.check_all
                st.session_state["_force_export_open"] = True

            st.checkbox("Select All", key="check_all", on_change=on_select_all_changed)

            def on_individual_checkbox_change(col_name, state_key):
                if st.session_state.get(state_key):
                    st.session_state.selected_cols = list(dict.fromkeys([*st.session_state.selected_cols, col_name]))
                else:
                    st.session_state.selected_cols = [
                        selected for selected in st.session_state.selected_cols if selected != col_name
                    ]
                st.session_state.check_all = len(st.session_state.selected_cols) == len(st.session_state.df_cols)
                st.session_state["_force_export_open"] = True

            cols_layout = st.columns(5)
            for idx, col in enumerate(st.session_state.df_cols):
                label = col if col.strip() != "" else f"Unnamed Column {idx}"
                state_key = f"export_col_{idx}"
                st.session_state.setdefault(state_key, col in st.session_state.selected_cols)
                with cols_layout[idx % 5]:
                    st.checkbox(
                        label,
                        key=state_key,
                        on_change=on_individual_checkbox_change,
                        args=(col, state_key),
                    )

            export_file_input = st.text_input(
                "Export to filename:",
                value=st.session_state.df_export_file,
                key="input_df_export_file_main",
            )
            st.session_state.df_export_file = export_file_input.strip()

            action_col_stats, action_col_export = st.columns([1, 1])
            with action_col_stats:
                stats_clicked = st.button(
                    "STATS report",
                    key="stats_report_main",
                    type="primary",
                    disabled=not artifact_state.stats_action.enabled,
                    width="stretch",
                )
            with action_col_export:
                export_clicked_manual = st.button(
                    "EXPORT dataframe",
                    key="export_df_main",
                    type="primary",
                    disabled=not artifact_state.export_action.enabled,
                    width="stretch",
                    help=artifact_state.export_action.disabled_reason
                    or "Save the current run output to export/export.csv so Experiment/Explore can load it.",
                )
            combo_export_trigger = st.session_state.pop("_combo_export_trigger", False)
            export_clicked = export_clicked_manual or combo_export_trigger

            if stats_clicked:
                profile_file = st.session_state.profile_report_file
                if not profile_file.exists():
                    profile = generate_profile_report(loaded_df)
                    with st.spinner("Generating profile report..."):
                        profile.to_file(profile_file, silent=False)
                open_new_tab(profile_file.as_uri())

            if export_clicked:
                target_path = st.session_state.df_export_file
                if not st.session_state.selected_cols:
                    st.warning("No columns selected for export.")
                elif not target_path:
                    st.warning("Please provide a filename for the export.")
                else:
                    exported_df = loaded_df[st.session_state.selected_cols]
                    if save_csv(exported_df, target_path):
                        st.success(f"Dataframe exported successfully to {target_path}.")
                        record_action_history(
                            st.session_state,
                            page_label="ORCHESTRATE",
                            env=env,
                            title="Dataframe exported",
                            status="done",
                            detail=f"{len(exported_df)} row(s), {len(exported_df.columns)} column(s)",
                            artifact=target_path,
                        )
                        st.session_state["_reset_export_checkboxes"] = True
                        st.session_state["_experiment_reload_required"] = True

                if st.session_state.profile_report_file.exists():
                    os.remove(st.session_state.profile_report_file)
    else:
        st.session_state.df_cols = []
        st.session_state.selected_cols = []
        st.session_state.check_all = False
        if controls_visible and not dag_based_app:
            st.info("No data loaded yet. Click 'LOAD dataframe' in Execute to populate it before export.")
