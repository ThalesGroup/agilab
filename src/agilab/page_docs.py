from __future__ import annotations

import webbrowser

import streamlit as st
from agi_env.pagelib import open_local_docs

DOCS_BASE_URL = "https://thalesgroup.github.io/agilab"
_DOCS_LOCAL_ALIASES: dict[str, tuple[str, ...]] = {
    "agilab-help.html": ("index.html",),
    "edit-help.html": ("edit_help.html",),
    "execute-help.html": ("execute_help.html",),
    "experiment-help.html": ("experiment_help.html",),
    "explore-help.html": ("views_help.html",),
}


def _docs_candidates(html_file: str) -> tuple[str, ...]:
    aliases = _DOCS_LOCAL_ALIASES.get(html_file, ())
    return (html_file, *aliases)


def _remote_docs_url(html_file: str, anchor: str = "") -> str:
    base = f"{DOCS_BASE_URL.rstrip('/')}/{html_file}"
    if not anchor:
        return base
    clean_anchor = anchor[1:] if anchor.startswith("#") else anchor
    return f"{base}#{clean_anchor}"


def _open_remote_docs(html_file: str, anchor: str = "") -> None:
    webbrowser.open_new_tab(_remote_docs_url(html_file, anchor))


def _open_local_page_docs(env, html_file: str, anchor: str = "") -> str:
    last_error: FileNotFoundError | None = None
    for candidate in _docs_candidates(html_file):
        try:
            open_local_docs(env, candidate, anchor)
            return candidate
        except FileNotFoundError as exc:
            last_error = exc

    if last_error is not None:
        raise last_error
    raise FileNotFoundError(f"Local documentation file '{html_file}' was not found.")


def render_page_docs_access(
    env,
    *,
    html_file: str,
    anchor: str = "",
    key_prefix: str,
    title: str = "Documentation",
    caption: str | None = None,
    sidebar: bool = True,
) -> None:
    container = st.sidebar if sidebar else st
    container.divider()
    container.subheader(title)
    if caption:
        container.caption(caption)

    if container.button(
        "Read Documentation",
        key=f"{key_prefix}_docs_remote",
        type="primary",
        width="stretch",
    ):
        _open_remote_docs(html_file, anchor)

    if container.button(
        "Open Local Documentation",
        key=f"{key_prefix}_docs_local",
        width="stretch",
    ):
        try:
            _open_local_page_docs(env, html_file, anchor)
        except FileNotFoundError:
            container.error("Local documentation not found. Regenerate via docs/gen-docs.sh.")
