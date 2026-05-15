from __future__ import annotations

import webbrowser
from pathlib import Path
from typing import Mapping

import streamlit as st
from agi_gui.ui_support import open_docs_url, open_local_docs, with_anchor

DOCS_BASE_URL = "https://thalesgroup.github.io/agilab"
DOCS_MENU_LABEL = "Get help"
SETTINGS_MENU_URL = "/SETTINGS"
SETTINGS_MENU_TEXT = (
    f"**Settings:** [Open AGILAB Settings]({SETTINGS_MENU_URL}) for environment variables "
    "and runtime diagnostics."
)
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


def docs_menu_url(html_file: str = "agilab-help.html", anchor: str = "") -> str:
    """Return the public documentation URL used by Streamlit's page menu."""
    return _remote_docs_url(html_file, anchor)


def docs_menu_items(
    *,
    html_file: str = "agilab-help.html",
    anchor: str = "",
    base_items: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Merge AGILAB menu content with the page-specific documentation entry."""
    items = dict(base_items or {})
    about_text = items.get("About")
    if about_text and "Open AGILAB Settings" not in about_text:
        items["About"] = f"{SETTINGS_MENU_TEXT}\n\n{about_text}"
    items[DOCS_MENU_LABEL] = docs_menu_url(html_file, anchor)
    return items


def get_docs_menu_items(*, html_file: str = "agilab-help.html", anchor: str = "") -> dict[str, str]:
    """Return Streamlit menu items with About text and a page-specific docs link."""
    from agi_env.pagelib_resource_support import about_content_payload

    return docs_menu_items(
        html_file=html_file,
        anchor=anchor,
        base_items=about_content_payload(),
    )


def _open_remote_docs(html_file: str, anchor: str = "") -> bool:
    try:
        return bool(webbrowser.open_new_tab(_remote_docs_url(html_file, anchor)))
    except (OSError, RuntimeError, webbrowser.Error):
        return False


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


def _open_preferred_page_docs(env, html_file: str, anchor: str = "") -> str:
    if _open_remote_docs(html_file, anchor):
        return "remote"
    return f"local:{_open_local_page_docs(env, html_file, anchor)}"


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
    if not sidebar:
        container.subheader(title)
    if caption:
        container.caption(caption)

    if container.button(
        "Read Documentation",
        key=f"{key_prefix}_docs_read",
        type="primary",
        width="stretch",
    ):
        try:
            _open_preferred_page_docs(env, html_file, anchor)
        except FileNotFoundError:
            container.error("Documentation not found online or locally. Regenerate via docs/gen-docs.sh.")
