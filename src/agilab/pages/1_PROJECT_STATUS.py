"""Visible PROJECT status menu page."""

from __future__ import annotations

import streamlit as st

from agilab.page_bootstrap import ensure_page_env, render_page_chrome
from agilab.page_project_selector import render_project_selector
from agilab.workflow_ui import render_project_status_page


def _on_project_change(project: str) -> None:
    env = st.session_state.get("env")
    if env is None:
        return
    env.change_app(project)
    st.session_state["env"] = env
    st.query_params["active_app"] = project
    st.rerun()


def main() -> None:
    """Render the selected project's compact status before execution pages."""
    env = ensure_page_env(st, __file__)
    if env is None:
        return
    render_page_chrome(
        st,
        env=env,
        page_label="PROJECT",
        docs_html_file="edit-help.html",
    )
    projects = list(getattr(env, "projects", []) or [])
    current_project = env.app if getattr(env, "app", None) in projects else (projects[0] if projects else None)
    render_project_selector(
        st,
        projects,
        current_project,
        on_change=_on_project_change,
        container=st,
    )
    render_project_status_page(st, env=env)


if __name__ == "__main__":
    main()
