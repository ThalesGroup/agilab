import json
import os
import shutil
import stat
import importlib.util
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import networkx as nx
from networkx.readwrite import json_graph
import pandas as pd
import streamlit as st

try:
    import matplotlib.pyplot as plt
except ModuleNotFoundError as exc:
    plt = None  # type: ignore[assignment]
    _MATPLOTLIB_IMPORT_ERROR = exc
else:
    _MATPLOTLIB_IMPORT_ERROR = None

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

PENDING_EXECUTE_ACTION_KEY = "_orchestrate_pending_action"
PREVIEW_FILE_PATTERNS = ("*.parquet", "*.csv", "*.json", "*.gml")
PREVIEW_MAX_SEARCH_FILES = int(os.environ.get("AGILAB_PREVIEW_MAX_SEARCH_FILES", "1000"))
PREVIEW_MAX_FILE_BYTES = int(os.environ.get("AGILAB_PREVIEW_MAX_FILE_BYTES", str(25 * 1024 * 1024)))


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

    def _attach_root(raw_path: Optional[Path | str]) -> None:
        if not raw_path:
            return
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = Path.home() / path
        candidate_roots.append(path)

    _attach_root(getattr(env, "dataframe_path", None))
    _attach_root(getattr(env, "app_data_rel", None))

    if isinstance(active_args, dict):
        _attach_root(active_args.get("data_in"))
        _attach_root(active_args.get("data_out"))

    unique_roots: list[Path] = []
    seen_roots: set[str] = set()
    for root in candidate_roots:
        key = str(root.resolve()) if root.exists() else str(root)
        if key not in seen_roots:
            seen_roots.add(key)
            unique_roots.append(root)
    return unique_roots


def _preview_candidate_paths(candidate_roots: list[Path]) -> list[Path]:
    search_files: list[Path] = []

    def _append_candidate(candidate: Path) -> bool:
        if len(search_files) >= PREVIEW_MAX_SEARCH_FILES:
            return False
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


def find_preview_target(candidate_roots: list[Path]) -> tuple[Optional[Path], list[Path]]:
    search_files = _preview_candidate_paths(candidate_roots)

    filtered_records: list[tuple[Path, float]] = []
    for file_path in search_files:
        if file_path.name.startswith("._"):
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
    session_state[PENDING_EXECUTE_ACTION_KEY] = action


def consume_pending_execute_action(session_state) -> Optional[str]:
    return session_state.pop(PENDING_EXECUTE_ACTION_KEY, None)


def _render_graph_preview(graph_preview: nx.Graph, source_preview_name: Optional[str]) -> None:
    if plt is None:
        raise RuntimeError(
            f"matplotlib unavailable: {_MATPLOTLIB_IMPORT_ERROR}. "
            "Install the optional visualization dependencies with `pip install 'agilab[viz]'`."
        )

    st.caption("Graph preview generated from JSON output")
    fig, ax = plt.subplots(figsize=(8, 6))
    pos = nx.spring_layout(graph_preview, seed=42)
    nx.draw_networkx_nodes(graph_preview, pos, node_color="skyblue", ax=ax)
    nx.draw_networkx_edges(graph_preview, pos, ax=ax, alpha=0.5)
    nx.draw_networkx_labels(graph_preview, pos, ax=ax, font_size=9)
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

    existing_run_log = st.session_state.get("run_log_cache", "").strip()
    run_log_expander = None
    log_container = None

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
            runtime_root = (
                Path(getattr(env, "agi_cluster"))
                if bool(getattr(env, "is_source_env", False) or getattr(env, "is_worker_env", False))
                and getattr(env, "agi_cluster", None)
                else project_path
            )
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

        with st.spinner("Running AGI..."):
            stderr = await _run_and_stream()
            st.session_state["run_log_cache"] = st.session_state.get("log_text", "")
        with target_expander:
            log_placeholder.empty()
            display_log(st.session_state["run_log_cache"], stderr)
            st.caption(f"Logs saved to {log_file_path}")
        st.session_state["dataframe_deleted"] = False
        return target_expander

    delete_confirm_key = "delete_data_main_confirm"
    delete_undo_key = "delete_data_main_undo_payload"
    def _queue_execute_action(action: str) -> None:
        queue_pending_execute_action(st.session_state, action)
        st.rerun()

    @st.fragment
    def _render_run_panel_controls() -> None:
        if show_run_panel:
            run_col, load_col, delete_col = st.columns(3)
            run_label = "RUN benchmark" if st.session_state.get("benchmark") else "EXECUTE"
            if execute_state.command_configured:
                if run_col.button(
                    run_label,
                    key="run_btn",
                    type="primary",
                    width="stretch",
                ):
                    _queue_execute_action("run")
            else:
                run_col.button(
                    run_label,
                    key="run_btn_disabled",
                    type="primary",
                    disabled=True,
                    help="Configure the run snippet to enable execution",
                    width="stretch",
                )

            if load_col.button(
                "LOAD dataframe",
                key="load_data_main",
                type="primary",
                width="stretch",
                help="Fetch the latest dataframe preview for export",
            ):
                _queue_execute_action("load")

            delete_armed_clicked = False
            delete_cancel_clicked = False
            if st.session_state.get(delete_confirm_key, False):
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
            else:
                delete_armed_clicked = delete_col.button(
                    "DELETE dataframe",
                    key="delete_data_main",
                    type="secondary",
                    width="stretch",
                    help="Clear the cached dataframe preview so the next load reflects a fresh EXECUTE run.",
                )

            if _update_delete_confirm_state(
                delete_confirm_key,
                delete_armed_clicked=delete_armed_clicked,
                delete_cancel_clicked=delete_cancel_clicked,
            ):
                _rerun_fragment_or_app()

            undo_delete_clicked = False
            undo_payload = st.session_state.get(delete_undo_key)
            if isinstance(undo_payload, dict):
                undo_delete_clicked = st.button(
                    "UNDO last delete dataframe",
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

            if execute_state.command_configured:
                if st.button(
                    "EXECUTE → LOAD → EXPORT",
                    key="combo_exec_load_export",
                    type="primary",
                    help="Run EXECUTE, LOAD dataframe, and EXPORT output in one click.",
                    width="stretch",
                ):
                    _queue_execute_action("combo")
        else:
            st.info("`Serve` mode selected. Switch to `Run now` to access EXECUTE / LOAD / EXPORT actions.")
            st.session_state.pop("_combo_load_trigger", None)
            st.session_state.pop("_combo_export_trigger", None)
            st.session_state.pop(delete_confirm_key, None)

    if controls_visible:
        st.markdown("#### 5. Execute and inspect outputs")
        st.caption("Run the configured command, load the latest result, and export the dataframe used by analysis pages.")
        _render_run_panel_controls()
    else:
        consume_pending_execute_action(st.session_state)

    pending_action = consume_pending_execute_action(st.session_state)
    run_clicked = pending_action == "run"
    load_clicked = pending_action == "load" or st.session_state.pop("_combo_load_trigger", False)
    delete_clicked = pending_action == "delete"
    combo_clicked = pending_action == "combo"

    if show_run_panel and load_clicked:
        if st.session_state.get("dataframe_deleted"):
            st.info("Dataframe preview was deleted. Run EXECUTE again before loading a new export.")
        else:
            active_args = st.session_state.app_settings.get("args", {})
            candidate_roots = collect_candidate_roots(env, active_args if isinstance(active_args, dict) else {})
            target_file, search_files = find_preview_target(candidate_roots)

            if not target_file:
                st.warning("No dataframe export found yet. Run EXECUTE to generate a fresh output.")
            else:
                st.session_state["loaded_source_path"] = target_file
                suffix = target_file.suffix.lower()
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
                            if len(candidate_batch) > 1:
                                st.success(
                                    f"Loaded dataframe preview from {len(candidate_batch)} files "
                                    f"(latest: {target_file.name})."
                                )
                            else:
                                st.success(f"Loaded dataframe preview from {target_file.name}.")
                        else:
                            st.warning(f"{target_file.name} is empty; nothing to preview.")
                    elif suffix == ".json":
                        payload = json.loads(target_file.read_text())
                        if isinstance(payload, dict) and "nodes" in payload and "links" in payload:
                            graph = json_graph.node_link_graph(payload, directed=payload.get("directed", True))
                            st.session_state["loaded_df"] = None
                            st.session_state["_force_export_open"] = False
                            st.session_state["loaded_graph"] = graph
                            st.success(f"Loaded network graph from {target_file.name}.")
                        else:
                            loaded_df = pd.json_normalize(payload)
                            st.session_state["loaded_df"] = loaded_df
                            st.session_state["_force_export_open"] = True
                            st.session_state.pop("loaded_graph", None)
                            st.info(f"Parsed JSON payload as tabular data from {target_file.name}.")
                    elif suffix == ".gml":
                        graph = nx.read_gml(target_file)
                        edge_df = nx.to_pandas_edgelist(graph)
                        if not edge_df.empty:
                            st.session_state["loaded_df"] = edge_df
                            st.session_state["_force_export_open"] = True
                            st.session_state["loaded_graph"] = graph
                            st.success(f"Loaded topology edges from {target_file.name}.")
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
                                st.info(f"Showing node metadata from {target_file.name}.")
                    else:
                        st.warning(f"Unsupported file format: {target_file.suffix}")
                except json.JSONDecodeError as exc:
                    st.error(f"Failed to decode JSON from {target_file.name}: {exc}")
                except (OSError, RuntimeError, TypeError, ValueError, nx.NetworkXError) as exc:
                    st.error(f"Unable to load {target_file.name}: {exc}")

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
            if st.session_state.get("benchmark"):
                st.session_state["_benchmark_expand"] = True
                st.rerun()
        else:
            st.error(run_action.disabled_reason)

    if show_run_panel and combo_clicked:
        combo_action = execute_state.combo_action
        if combo_action.enabled:
            run_log_expander = await _execute_with_logging(run_log_expander)
        else:
            st.error(combo_action.disabled_reason)

        st.session_state["_combo_load_trigger"] = True
        st.session_state["_combo_export_trigger"] = True
        st.rerun()

    if show_run_panel and existing_run_log and run_log_expander is None:
        expander = _ensure_run_log_expander(expanded=False)
        with expander:
            st.code(existing_run_log, language="python")

    df_preview = st.session_state.get("loaded_df")
    graph_preview = st.session_state.get("loaded_graph")
    source_preview_path = st.session_state.get("loaded_source_path")
    source_preview_name = None
    if source_preview_path:
        try:
            source_preview_name = Path(source_preview_path).name
        except (OSError, RuntimeError, TypeError, ValueError):
            source_preview_name = str(source_preview_path)

    if isinstance(df_preview, pd.DataFrame) and not df_preview.empty:
        render_dataframe_preview(
            df_preview,
            truncation_label="Browser preview limited",
        )
        if source_preview_name:
            st.caption(f"Previewing {source_preview_name}")
    elif isinstance(graph_preview, nx.Graph):
        try:
            _render_graph_preview(graph_preview, source_preview_name)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            st.error(f"Unable to render graph preview: {exc}")

    export_expanded = st.session_state.pop("_force_export_open", False)
    loaded_df = st.session_state.get("loaded_df")

    if isinstance(loaded_df, pd.DataFrame) and not loaded_df.empty:
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
                    width="stretch",
                )
            with action_col_export:
                export_clicked_manual = st.button(
                    "EXPORT dataframe",
                    key="export_df_main",
                    type="primary",
                    width="stretch",
                    help="Save the current run output to export/export.csv so Experiment/Explore can load it.",
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
                        st.session_state["_reset_export_checkboxes"] = True
                        st.session_state["_experiment_reload_required"] = True

                if st.session_state.profile_report_file.exists():
                    os.remove(st.session_state.profile_report_file)
    else:
        st.session_state.df_cols = []
        st.session_state.selected_cols = []
        st.session_state.check_all = False
        if controls_visible:
            st.info("No data loaded yet. Click 'LOAD dataframe' in Execute to populate it before export.")
