# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import streamlit as st
from agi_pages.queue_resilience import (
    load_queue_resilience_run,
    prepare_queue_resilience_page,
    render_queue_resilience_run,
)
from agi_pages.runtime import (
    ensure_repo_on_path as _page_ensure_repo_on_path,
)


def _ensure_repo_on_path() -> None:
    _page_ensure_repo_on_path(__file__)


_ensure_repo_on_path()

from agi_env import AgiEnv  # noqa: E402


DATA_DIR_KEY = "queue_resilience_datadir"
SUMMARY_GLOB_KEY = "queue_resilience_summary_glob"
APP_SCOPE_KEY = "queue_resilience_active_app_scope"
APP_SCOPED_SESSION_DEFAULT_KEYS = (
    DATA_DIR_KEY,
    SUMMARY_GLOB_KEY,
)


def _load_page_meta() -> tuple[str, str]:
    if __package__:
        from .page_meta import PAGE_LOGO, PAGE_TITLE

        return PAGE_LOGO, PAGE_TITLE

    _meta_path = Path(__file__).with_name("page_meta.py")
    _meta_spec = importlib.util.spec_from_file_location(
        "view_queue_resilience_page_meta", _meta_path
    )
    if (
        _meta_spec is None or _meta_spec.loader is None
    ):  # pragma: no cover - defensive fallback
        raise RuntimeError(f"Unable to load page metadata from {_meta_path}")
    _meta_module = importlib.util.module_from_spec(_meta_spec)
    _meta_spec.loader.exec_module(_meta_module)
    return _meta_module.PAGE_LOGO, _meta_module.PAGE_TITLE


PAGE_LOGO, PAGE_TITLE = _load_page_meta()


def _create_env(active_app_path: Path) -> AgiEnv:
    env = AgiEnv.session_for_app(
        apps_path=active_app_path.parent,
        app=active_app_path.name,
        verbose=0,
    )
    env.init_done = True
    return env


page_context = prepare_queue_resilience_page(
    st,
    env_factory=_create_env,
    title=PAGE_TITLE,
    logo_title=PAGE_LOGO,
    caption=(
        "Use exported queue telemetry to inspect backlog, routing pressure, and delivery outcomes "
        "without reopening the producer code."
    ),
    data_dir_key=DATA_DIR_KEY,
    summary_glob_key=SUMMARY_GLOB_KEY,
    app_scope_key=APP_SCOPE_KEY,
    app_scoped_keys=APP_SCOPED_SESSION_DEFAULT_KEYS,
)

summary_path = st.sidebar.selectbox(
    "Run summary",
    options=page_context.summary_files,
    format_func=lambda path: str(Path(path).relative_to(page_context.artifact_root)),
)
run = load_queue_resilience_run(
    st,
    Path(summary_path),
    csv_loader=pd.read_csv,
)
render_queue_resilience_run(st, run)
