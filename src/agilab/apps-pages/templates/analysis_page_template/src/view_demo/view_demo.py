"""Minimal AGILAB analysis page template entrypoint."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import streamlit as st

try:
    from agi_env import AgiEnv
except (ImportError, ModuleNotFoundError, OSError) as exc:  # pragma: no cover - dependency hint
    AgiEnv = None
    _AGI_ENV_IMPORT_ERROR = exc
else:  # pragma: no cover
    _AGI_ENV_IMPORT_ERROR = None

try:
    from agilab.page_docs import get_docs_menu_items
except (ImportError, ModuleNotFoundError, OSError):  # pragma: no cover - packaged page fallback

    def get_docs_menu_items(*, html_file: str | None = None) -> dict[str, str]:
        suffix = html_file or "index.html"
        return {"Get help": f"https://thalesgroup.github.io/agilab/{suffix}"}


PAGE_TITLE = "view_demo"
PAGE_LAYOUT = "wide"
PAGE_HELP_HTML = "explore-help.html"


def _query_param_value(value: object) -> str:
    if isinstance(value, (list, tuple)):
        return str(value[0]) if value else ""
    return str(value) if value is not None else ""


def _parse_active_app() -> str:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--active-app")
    args, _ = parser.parse_known_args()
    if args.active_app:
        return str(args.active_app)

    for key in ("active_app", "active-app", "project"):
        value = _query_param_value(st.query_params.get(key, ""))
        if value:
            return value
    return ""


def _load_project_env(active_app: str) -> Any:
    if AgiEnv is None:
        st.error("This page requires the agi-env package in its page environment.")
        st.error(f"Import error: {_AGI_ENV_IMPORT_ERROR}")
        st.stop()

    active_app_path = Path(active_app).expanduser().resolve()
    if not active_app_path.exists():
        st.error(f"Provided active project path does not exist: {active_app_path}")
        st.stop()

    return getattr(AgiEnv, "for_app", AgiEnv)(apps_path=active_app_path.parent, app=active_app_path.name, verbose=0)


def _dataset_root(env: Any) -> Path | None:
    for attr_name in ("app_data_rel", "app_data_abs"):
        value = getattr(env, attr_name, None)
        if value:
            return Path(value) / "dataset"
    return None


def _render_page_chrome() -> None:
    st.set_page_config(
        page_title=PAGE_TITLE,
        layout=PAGE_LAYOUT,
        menu_items=get_docs_menu_items(html_file=PAGE_HELP_HTML),
    )
    st.title(PAGE_TITLE)


def main() -> None:
    _render_page_chrome()

    active_app = _parse_active_app().strip()
    if not active_app:
        st.info("Open this page from AGILAB Analysis so the active project is passed in.")
        return

    env = _load_project_env(active_app)
    st.subheader(str(getattr(env, "app", active_app)))
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
