from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional

import streamlit as st

from agi_env import AgiEnv
from agi_env.app_provider_registry import aliased_app_runtime_target, app_name_aliases
from agi_gui.pagelib import scan_dir
from agi_gui.ui_support import load_last_active_app, store_last_active_app


JUPYTER_URL = "http://localhost:8888"


def load_last_active_app_name(modules: List[str]) -> Optional[str]:
    """Return the last active app name if it maps to a known module directory."""
    last_path = load_last_active_app()
    if not last_path:
        return None
    candidates = [last_path.name, str(last_path)]

    def _normalize(candidate: str) -> Optional[str]:
        for alias in app_name_aliases(candidate):
            if alias in modules:
                return alias
        return None

    for name in candidates:
        if not name:
            continue
        normalized = _normalize(name)
        if normalized:
            return normalized
    return None


def on_lab_change(new_index_page: str) -> None:
    """Handle lab directory change event."""
    st.session_state.pop("stages_file", None)
    st.session_state.pop("df_file", None)
    key = str(st.session_state.get("index_page", "")) + "df"
    st.session_state.pop(key, None)
    st.session_state["_requested_lab_dir"] = new_index_page
    st.session_state["lab_dir"] = new_index_page
    st.session_state["project_changed"] = True
    st.session_state["_experiment_reload_required"] = True
    st.session_state.page_broken = True
    env = st.session_state.get("env")
    try:
        base = Path(env.apps_path)  # type: ignore[attr-defined]
        builtin_base = base / "builtin"
        for alias in app_name_aliases(new_index_page):
            for cand in (
                base / alias,
                builtin_base / alias,
            ):
                if not cand.exists():
                    continue
                store_last_active_app(cand)
                return
    except (AttributeError, TypeError, OSError):
        pass


def available_lab_modules(env: AgiEnv, export_root: Path) -> List[str]:
    """Return lab choices from project directories, not from the home export tree."""
    modules: List[str] = []
    try:
        projects = env.get_projects(  # type: ignore[attr-defined]
            getattr(env, "apps_path", None),
            getattr(env, "builtin_apps_path", None),
            getattr(env, "apps_repository_root", None),
        )
        modules.extend(str(project).strip() for project in projects if str(project).strip())
    except (AttributeError, OSError, RuntimeError, TypeError):
        pass
    if not modules:
        modules = [str(module).strip() for module in scan_dir(export_root) if str(module).strip()]
    seen: set[str] = set()
    ordered: List[str] = []
    for module in modules:
        if module not in seen:
            ordered.append(module)
            seen.add(module)
    return sorted(ordered, key=lambda name: (name.casefold(), name))


def normalize_lab_choice(raw_value: Any, modules: List[str]) -> str:
    """Map persisted/query lab names to the canonical project-directory choice."""
    if not modules:
        return ""
    text = str(raw_value or "").strip()
    if not text:
        return ""
    candidates = list(app_name_aliases(text)) or [text]
    path_name = Path(text).name
    if path_name not in candidates:
        candidates.append(path_name)
    for alias in app_name_aliases(path_name):
        if alias not in candidates:
            candidates.append(alias)
    if text.endswith("_project"):
        stem = text.removesuffix("_project")
        candidates.append(stem)
        path_stem = Path(stem).name
        if path_stem not in candidates:
            candidates.append(path_stem)
    else:
        candidates.append(f"{text}_project")
        if path_name:
            candidates.append(f"{path_name}_project")
    for candidate in candidates:
        if candidate in modules:
            return candidate
    candidate_stems = {candidate.removesuffix("_project") for candidate in candidates if candidate}
    return next((module for module in modules if module.removesuffix("_project") in candidate_stems), "")


def resolve_lab_export_dir(export_root: Path, lab_choice: str) -> Path:
    """Resolve the export directory that matches a selected project directory."""
    choice = str(lab_choice or "").strip()
    if not choice:
        return export_root.resolve()
    target = aliased_app_runtime_target(Path(choice).name)
    candidates = [target]
    for alias in app_name_aliases(choice):
        if alias not in candidates:
            candidates.append(alias)
    for candidate in candidates:
        resolved = (export_root / candidate).resolve()
        if resolved.exists():
            return resolved
    return (export_root / target).resolve()


def open_notebook_in_browser() -> None:
    """Inject JS to open the Jupyter Notebook URL in a new tab."""
    js_code = f"""
    <script>
    window.open("{JUPYTER_URL}", "_blank");
    </script>
    """
    st.components.v1.html(js_code, height=0, width=0)
