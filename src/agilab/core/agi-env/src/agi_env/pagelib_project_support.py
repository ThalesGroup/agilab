"""Project-switch and custom-form helpers extracted from pagelib."""

from __future__ import annotations

from pathlib import Path


def init_custom_ui(session_state) -> None:
    """Keep edit-mode toggles in sync and signal app-args forms to refresh."""
    toggle_ui = bool(session_state.get("toggle_edit_ui", False))
    session_state["toggle_edit"] = not toggle_ui
    for key in list(session_state.keys()):
        if ":app_args_form:" in key:
            del session_state[key]
    session_state["app_args_form_refresh_nonce"] = int(
        session_state.get("app_args_form_refresh_nonce", 0)
    ) + 1


def on_project_change(
    project,
    *,
    session_state,
    store_last_active_app_fn,
    clear_project_session_state_fn,
    reset_project_sections_fn,
    error_fn,
    switch_to_select: bool = False,
    path_cls=Path,
) -> None:
    """Reset project-scoped state and re-seed sidebar data for the selected app."""
    env = session_state["env"]
    clear_project_session_state_fn(session_state)

    try:
        env.change_app(env.apps_path / project)
        module = env.target
        try:
            store_last_active_app_fn(env.active_app)
        except (OSError, RuntimeError):
            pass

        session_state.module_rel = path_cls(module)
        session_state.datadir = env.AGILAB_EXPORT_ABS / module
        session_state.datadir_str = str(session_state.datadir)
        session_state.df_export_file = str(session_state.datadir / "export.csv")
        session_state.switch_to_select = switch_to_select
        session_state.project_changed = True
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
        error_fn(f"An error occurred while changing the project: {exc}")

    reset_project_sections_fn(session_state)
