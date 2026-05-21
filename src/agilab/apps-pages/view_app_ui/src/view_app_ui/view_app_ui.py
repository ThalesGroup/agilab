# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import sys
import tomllib
from types import ModuleType
from typing import Any

import streamlit as st


PAGE_KEY = "view_app_ui"


def _safe_page_config() -> None:
    try:
        st.set_page_config(page_title="App UI", layout="wide")
    except Exception:
        pass


def _ensure_repo_on_path() -> None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "agilab"
        if candidate.is_dir():
            src_root = candidate.parent
            repo_root = src_root.parent
            for entry in (str(src_root), str(repo_root)):
                if entry not in sys.path:
                    sys.path.insert(0, entry)
            break


_ensure_repo_on_path()


def _resolve_active_app(argv: list[str] | None = None) -> Path:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--active-app", dest="active_app", type=str, required=True)
    args, _ = parser.parse_known_args(argv)
    active_app_path = Path(args.active_app).expanduser().resolve()
    if not active_app_path.exists():
        raise FileNotFoundError(f"Provided --active-app path not found: {active_app_path}")
    return active_app_path


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


def _prepend_sys_path(path: Path) -> None:
    entry = str(path)
    sys.path[:] = [existing for existing in sys.path if existing != entry]
    sys.path.insert(0, entry)


def _load_module(path: Path) -> ModuleType:
    module_name = f"_agilab_view_app_ui_{abs(hash(str(path.resolve())))}"
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


def _run_app_ui(entrypoint: Path, active_app: Path) -> None:
    _prepend_sys_path(entrypoint.parent)
    _prepend_sys_path(active_app / "src")
    previous_argv = list(sys.argv)
    sys.argv = [str(entrypoint), "--active-app", str(active_app)]
    try:
        module = _load_module(entrypoint)
        main_fn = getattr(module, "main", None)
        if not callable(main_fn):
            raise AttributeError(f"Configured app UI {entrypoint} does not expose main()")
        main_fn()
    finally:
        sys.argv = previous_argv


def main() -> None:
    try:
        active_app = _resolve_active_app()
        config = _configured_app_ui(active_app)
        entrypoint = _resolve_entrypoint(active_app, config.get("entrypoint"))
        if entrypoint is None:
            _safe_page_config()
            st.info("This project does not declare an app UI entrypoint for ANALYSIS.")
            st.caption("Configure [pages.view_app_ui].entrypoint in the active app settings.")
            return
        _run_app_ui(entrypoint, active_app)
    except Exception as exc:
        _safe_page_config()
        st.error(f"Failed to render app UI: {exc}")


if __name__ == "__main__":
    main()
