"""Project and dataframe selection helpers extracted from pagelib."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence


def select_project(
    projects: Sequence[str],
    current_project: str,
    *,
    session_state,
    sidebar,
    build_project_selection_fn,
    on_project_change_fn,
) -> None:
    """
    Render the project selector with filtering and bounded shortlist rendering.
    """
    env = session_state.get("env")
    if env is not None:
        try:
            projects = env.get_projects(env.apps_path, env.builtin_apps_path)
            env.projects = projects
        except (OSError, TypeError, RuntimeError):
            pass

    search_term = sidebar.text_input("Filter projects", key="project_filter")
    selection_state = build_project_selection_fn(projects, current_project, search_term, limit=50)
    shortlist = selection_state.shortlist

    if not shortlist:
        sidebar.info("No projects match that filter.")
        return

    if selection_state.needs_caption:
        sidebar.caption(
            f"Showing first {len(shortlist)} of {selection_state.total_matches} matches"
        )

    selection = sidebar.selectbox(
        "Project name",
        shortlist,
        index=selection_state.default_index,
        key="project_selectbox",
    )

    if selection != current_project:
        on_project_change_fn(selection)


def resolve_active_app(
    env,
    *,
    query_params,
    normalize_query_param_value_fn,
    active_app_candidates_fn,
    store_last_active_app_fn,
    load_last_active_app_fn,
    preferred_base: Path | None = None,
    path_cls=Path,
) -> tuple[str, bool]:
    """
    Resolve the active app from query params or the last persisted active app.
    """
    project_changed = False
    requested_val = normalize_query_param_value_fn(query_params.get("active_app"))

    if requested_val and requested_val != env.app:
        for candidate in active_app_candidates_fn(
            requested_val,
            path_cls(env.apps_path),
            env.projects or [],
            preferred_base=preferred_base,
        ):
            if not candidate.exists():
                continue
            try:
                env.change_app(candidate)
                project_changed = True
                store_last_active_app_fn(env.active_app)
                break
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
                continue
    elif not requested_val:
        last_app = load_last_active_app_fn()
        if last_app and last_app != env.active_app and last_app.exists():
            try:
                env.change_app(last_app)
                project_changed = True
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
                pass

    return env.app, project_changed


def sidebar_views(
    *,
    session_state,
    sidebar,
    scan_dir_fn,
    find_files_fn,
    resolve_default_selection_fn,
    build_sidebar_dataframe_selection_fn,
    on_lab_change_fn,
    on_df_change_fn,
    path_cls=Path,
) -> None:
    """
    Create sidebar controls for lab and dataframe selection.
    """
    env = session_state["env"]
    export_root = path_cls(env.AGILAB_EXPORT_ABS)
    modules = session_state.get("modules", scan_dir_fn(export_root))

    _, lab_index = resolve_default_selection_fn(
        modules,
        session_state.get("lab_dir"),
        env.target,
    )
    session_state["lab_dir"] = sidebar.selectbox(
        "Lab directory",
        modules,
        index=lab_index,
        on_change=lambda: on_lab_change_fn(session_state.lab_dir_selectbox),
        key="lab_dir_selectbox",
    )

    lab_dir = export_root / session_state["lab_dir_selectbox"]
    session_state.df_dir = lab_dir

    df_files = find_files_fn(lab_dir)
    session_state.df_files = df_files

    sidebar_state = build_sidebar_dataframe_selection_fn(
        export_root,
        session_state["lab_dir_selectbox"],
        df_files,
        session_state.get("index_page"),
        env.target,
    )
    session_state["index_page"] = sidebar_state.index_page
    index_page_str = str(sidebar_state.index_page)
    session_state["module_path"] = sidebar_state.module_path
    sidebar.selectbox(
        "Dataframe",
        sidebar_state.df_files_rel,
        key=sidebar_state.key_df,
        index=sidebar_state.default_index,
        on_change=lambda: on_df_change_fn(
            sidebar_state.module_path,
            index_page_str,
            session_state.get("df_file"),
        ),
    )

    if session_state[sidebar_state.key_df]:
        session_state["df_file"] = export_root / path_cls(session_state[sidebar_state.key_df])
    else:
        session_state["df_file"] = None


def on_df_change(
    module_dir,
    index_page,
    df_file=None,
    steps_file=None,
    *,
    session_state,
    resolve_selected_df_path_fn,
    load_last_step_fn,
    logger,
    path_cls=Path,
) -> None:
    """
    Update dataframe-related session state after a selection change.
    """
    index_page_str = str(index_page)
    select_df_key = index_page_str + "df"

    if (
        select_df_key not in session_state
        and df_file is not None
        and (str(df_file) + "df") in session_state
    ):
        df_file, index_page_str = index_page, str(df_file)
        select_df_key = index_page_str + "df"

    selected_df = session_state.get(select_df_key)
    env = session_state.get("env")
    export_root = path_cls(env.AGILAB_EXPORT_ABS) if env else None
    selected_path = resolve_selected_df_path_fn(
        selected_df,
        fallback_df_file=df_file,
        export_root=export_root,
    )

    if selected_path is not None:
        session_state[index_page_str + "df_file"] = selected_path
        session_state["df_file"] = selected_path
    else:
        session_state.pop(index_page_str + "df_file", None)

    if steps_file:
        logger.info(f"mkdir {steps_file.parent}")
        steps_file.parent.mkdir(parents=True, exist_ok=True)
        load_last_step_fn(module_dir, steps_file, index_page_str)
    session_state.pop(index_page_str, None)
    session_state.page_broken = True
