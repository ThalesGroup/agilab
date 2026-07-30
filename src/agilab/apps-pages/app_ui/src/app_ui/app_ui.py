# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tomllib
from types import ModuleType
from typing import Any

import streamlit as st
from agi_env.ui.sidecar_registry import isolated_import_process_state
from agi_pages.runtime import (
    configure_streamlit_page,
    ensure_repo_on_path,
    resolve_active_app_path,
)


# The app UI sidecar imports an app-owned module and renders its initial screen
# while temporarily owning process-global import state.  Five seconds is
# sufficient for small pages but is too short for normal first renders of
# app-backed project pages, causing a concurrent Streamlit rerun to replace the
# app UI with a render error.  Keep the guard bounded so a real deadlock remains
# diagnosable, while allowing a normal interactive render to finish.
_APP_UI_INLINE_IMPORT_LEASE_TIMEOUT_SECONDS = 30.0

PAGE_KEY = "app_ui"


def _safe_page_config() -> None:
    configure_streamlit_page(st, title="App UI")


ensure_repo_on_path(__file__)


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _configured_app_ui(active_app: Path) -> dict[str, Any]:
    settings = _read_toml(active_app / "src" / "app_settings.toml")
    pages = settings.get("pages")
    if not isinstance(pages, dict):
        return {}
    config = pages.get(PAGE_KEY)
    return config if isinstance(config, dict) else {}


def _resolve_entrypoint(active_app: Path, entrypoint: object) -> Path | None:
    if not isinstance(entrypoint, str) or not entrypoint.strip():
        return None
    raw_path = Path(entrypoint.strip()).expanduser()
    candidates = [raw_path] if raw_path.is_absolute() else [active_app / "src" / raw_path, active_app / raw_path]
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if not resolved.is_file():
            continue
        try:
            resolved.relative_to(active_app.resolve())
        except ValueError:
            continue
        return resolved
    return None


def _load_module(path: Path) -> ModuleType:
    module_name = f"_agilab_app_ui_{abs(hash(str(path.resolve())))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ModuleNotFoundError(f"Unable to load app UI from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _manager_editable_import_roots(active_app: Path) -> tuple[Path, ...]:
    try:
        from agi_env.runtime import import_layout_support
    except (ImportError, ModuleNotFoundError) as exc:
        raise RuntimeError(
            "The installed AGILAB UI runtime cannot inspect manager editables. "
            "Upgrade the aligned AGILAB packages and restart Streamlit."
        ) from exc
    try:
        from agi_env.runtime.hot_source_support import aligned_module_callable

        resolver = aligned_module_callable(
            import_layout_support,
            "hosted_editable_source_import_roots",
        )
    except (ImportError, RuntimeError) as exc:
        raise RuntimeError(
            "The installed AGILAB UI runtime is stale: agi_env does not expose "
            "hosted editable import support. Upgrade the aligned AGILAB packages "
            "and restart Streamlit."
        ) from exc
    return resolver(active_app / ".venv")


def _run_app_ui(entrypoint: Path, active_app: Path) -> None:
    app_src = active_app / "src"
    import_roots = tuple(
        dict.fromkeys(
            (
                app_src,
                entrypoint.parent,
                *_manager_editable_import_roots(active_app),
            )
        )
    )
    with isolated_import_process_state(
        argv=[str(entrypoint), "--active-app", str(active_app)],
        prepend_paths=import_roots,
        module_roots=import_roots,
        timeout=_APP_UI_INLINE_IMPORT_LEASE_TIMEOUT_SECONDS,
    ):
        module = _load_module(entrypoint)
        main_fn = getattr(module, "main", None)
        if not callable(main_fn):
            raise AttributeError(f"Configured app UI {entrypoint} does not expose main()")
        main_fn()


def main() -> None:
    try:
        active_app = resolve_active_app_path()
        config = _configured_app_ui(active_app)
        entrypoint = _resolve_entrypoint(active_app, config.get("entrypoint"))
        if entrypoint is None:
            _safe_page_config()
            st.info("This project does not declare an app UI entrypoint for ANALYSIS.")
            st.caption("Configure [pages.app_ui].entrypoint in the active app settings.")
            return
        _run_app_ui(entrypoint, active_app)
    except Exception as exc:
        _safe_page_config()
        st.error(f"Failed to render app UI: {exc}")


if __name__ == "__main__":
    main()
