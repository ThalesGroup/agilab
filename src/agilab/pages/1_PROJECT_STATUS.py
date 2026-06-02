"""Visible PROJECT status menu page."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import streamlit as st

from agilab.page_bootstrap import ensure_page_env, render_page_chrome
from agilab.page_project_selector import render_project_selector
from agilab.workflow_ui import render_project_status_page

_PROJECT_EDIT_PAGE_MODULE = "agilab_project_edit_page_shared"


def _load_project_edit_page_module() -> ModuleType:
    """Load the edit page so PROJECT_STATUS can reuse its sidebar handlers."""
    cached = sys.modules.get(_PROJECT_EDIT_PAGE_MODULE)
    if isinstance(cached, ModuleType):
        return cached
    module_path = Path(__file__).with_name("1_PROJECT.py")
    spec = importlib.util.spec_from_file_location(_PROJECT_EDIT_PAGE_MODULE, module_path)
    if spec is None or spec.loader is None:
        raise ModuleNotFoundError(f"Unable to load PROJECT edit page from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_PROJECT_EDIT_PAGE_MODULE] = module
    spec.loader.exec_module(module)
    return module


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
        show_edit_button=True,
    )
    project_edit_page = _load_project_edit_page_module()
    project_edit_page.render_project_sidebar(
        env,
        actions=project_edit_page.PROJECT_STATUS_ACTIONS,
        render_edit_body=False,
    )
    render_project_status_page(st, env=env)


if __name__ == "__main__":
    main()
