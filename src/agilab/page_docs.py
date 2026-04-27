from __future__ import annotations

import webbrowser
from pathlib import Path

import streamlit as st
from agi_gui.ui_support import open_docs_url, open_local_docs, with_anchor

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


def _resolve_local_page_docs_path(env, html_file: str) -> Path | None:
    roots: list[Path] = []
    raw_root = getattr(env, "agilab_pck", None)
    if not raw_root:
        return None
    try:
        package_root = Path(raw_root).expanduser().resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        package_root = None
    if package_root is None:
        return None
    roots.extend([package_root, package_root.parent, package_root.parent.parent])

    module_file = Path(__file__).resolve()
    roots.extend([module_file.parent, module_file.parents[1], module_file.parents[2]])

    seen: set[Path] = set()
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        for base in (root / "docs" / "build", root / "docs" / "html"):
            candidate = base / html_file
            if candidate.exists():
                return candidate
        docs_root = root / "docs"
        if docs_root.exists():
            matches = sorted(docs_root.rglob(html_file))
            if matches:
                return matches[0]
    return None


def _open_local_page_docs(env, html_file: str, anchor: str = "") -> str:
    last_error: FileNotFoundError | None = None
    for candidate in _docs_candidates(html_file):
        try:
            open_local_docs(env, candidate, anchor)
            return candidate
        except FileNotFoundError as exc:
            last_error = exc
            docs_path = _resolve_local_page_docs_path(env, candidate)
            if docs_path is not None:
                open_docs_url(with_anchor(docs_path.as_uri(), anchor))
                return candidate

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
    divider: bool = True,
) -> None:
    container = st.sidebar if sidebar else st
    if divider:
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
