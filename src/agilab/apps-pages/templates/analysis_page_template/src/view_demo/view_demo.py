"""Minimal AGILAB analysis page template entrypoint."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st
from agi_pages.runtime import configure_streamlit_page, resolve_active_app_path

try:
    from agi_env import AgiEnv
except (ImportError, ModuleNotFoundError, OSError) as exc:  # pragma: no cover - dependency hint
    AgiEnv = None
    _AGI_ENV_IMPORT_ERROR = exc
else:  # pragma: no cover
    _AGI_ENV_IMPORT_ERROR = None

try:
    from agilab.ui.page_docs import get_docs_menu_items
except (ImportError, ModuleNotFoundError, OSError):  # pragma: no cover - packaged page fallback

    def get_docs_menu_items(*, html_file: str | None = None) -> dict[str, str]:
        suffix = html_file or "index.html"
        return {"Get help": f"https://thalesgroup.github.io/agilab/{suffix}"}


PAGE_TITLE = "view_demo"
PAGE_LAYOUT = "wide"
PAGE_HELP_HTML = "explore-help.html"


def _load_project_env(active_app_path: Path) -> Any:
    if AgiEnv is None:
        st.error("This page requires the agi-env package in its page environment.")
        st.error(f"Import error: {_AGI_ENV_IMPORT_ERROR}")
        st.stop()

    return AgiEnv.session_for_app(
        apps_path=active_app_path.parent,
        app=active_app_path.name,
        verbose=0,
    )


def _dataset_root(env: Any) -> Path | None:
    for attr_name in ("app_data_rel", "app_data_abs"):
        value = getattr(env, attr_name, None)
        if value:
            return Path(value) / "dataset"
    return None


def _render_page_chrome() -> None:
    configure_streamlit_page(
        st,
        title=PAGE_TITLE,
        page_title=PAGE_TITLE,
        layout=PAGE_LAYOUT,
        menu_items=get_docs_menu_items(html_file=PAGE_HELP_HTML),
    )
    st.title(PAGE_TITLE)


def main() -> None:
    _render_page_chrome()

    try:
        # The shared resolver accepts the standard ``--active-app`` launch
        # argument and the equivalent ANALYSIS query parameters.
        active_app = resolve_active_app_path(
            use_environment=False,
            query_params=st.query_params,
            query_param_keys=("active_app", "active-app", "project"),
            missing_message="Open this page from AGILAB Analysis so the active project is passed in.",
            error_fn=st.error,
            missing_fn=st.info,
        )
    except (FileNotFoundError, ValueError):
        # A generated page should render the actionable resolver message and
        # return cleanly when it is opened outside an active project context.
        return

    env = _load_project_env(active_app)
    st.subheader(str(getattr(env, "app", active_app.name)))
    st.caption(f"Project path: {getattr(env, 'active_app', active_app)}")

    dataset_root = _dataset_root(env)
    if dataset_root is None or not dataset_root.exists():
        st.info("No dataset folder yet. Run the project workflow before exploring outputs here.")
        return

    csv_files = sorted(dataset_root.glob("*.csv"))
    if not csv_files:
        st.warning("No CSV file found in the dataset folder yet.")
        return

    st.success(f"{len(csv_files)} CSV file(s) available.")
    with st.expander("Dataset files", expanded=False):
        for file in csv_files:
            st.write(file.name)


if __name__ == "__main__":
    main()
