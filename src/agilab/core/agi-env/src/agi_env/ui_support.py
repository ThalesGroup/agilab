from __future__ import annotations

import base64
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Optional
from .ui_docs_support import (
    ONLINE_DOCS_INDEX,
    detect_dev_version_suffix,
    detect_installed_version,
    focus_existing_docs_tab as _focus_existing_docs_tab_impl,
    read_theme_css as _read_theme_css_impl,
    read_version_from_pyproject as _read_version_from_pyproject_impl,
    resolve_docs_path as _resolve_docs_path_impl,
)
from .ui_state_support import (
    load_global_state as _load_global_state_impl,
    normalize_existing_path as _normalize_existing_path,
    normalize_path_string as _normalize_path_string,
    persist_global_state as _persist_global_state_impl,
)

try:  # pragma: no cover - standard-library availability differs by Python version
    from importlib import metadata as _importlib_metadata  # type: ignore
except ImportError:  # pragma: no cover
    _importlib_metadata = None  # type: ignore

try:  # pragma: no cover - optional dependency
    import tomli_w as _tomli_writer  # type: ignore[import-not-found]

    def _dump_toml_payload(data: dict, handle) -> None:
        _tomli_writer.dump(data, handle)

except ModuleNotFoundError:
    try:
        from tomlkit import dumps as _tomlkit_dumps

        def _dump_toml_payload(data: dict, handle) -> None:
            handle.write(_tomlkit_dumps(data).encode("utf-8"))

    except (ImportError, ModuleNotFoundError) as _toml_exc:  # pragma: no cover - defensive

        def _dump_toml_payload(data: dict, handle, _import_error=_toml_exc) -> None:
            raise RuntimeError(
                "Writing settings requires the 'tomli-w' or 'tomlkit' package."
            ) from _import_error


_GLOBAL_STATE_FILE = Path.home() / ".local" / "share" / "agilab" / "app_state.toml"
_LEGACY_LAST_APP_FILE = Path.home() / ".local" / "share" / "agilab" / ".last-active-app"
_DOCS_ALREADY_OPENED = False
_LAST_DOCS_URL: Optional[str] = None


def load_global_state() -> dict[str, str]:
    return _load_global_state_impl(
        _GLOBAL_STATE_FILE,
        _LEGACY_LAST_APP_FILE,
    )


def persist_global_state(data: dict[str, str]) -> None:
    _persist_global_state_impl(
        _GLOBAL_STATE_FILE,
        data,
        dump_payload_fn=_dump_toml_payload,
    )


def load_last_active_app() -> Path | None:
    state = load_global_state()
    return _normalize_existing_path(state.get("last_active_app"), path_cls=Path)


def store_last_active_app(path: Path) -> None:
    normalized = _normalize_path_string(path, path_cls=Path)
    if normalized is None:
        return
    state = load_global_state()
    if state.get("last_active_app") == normalized:
        return
    state["last_active_app"] = normalized
    persist_global_state(state)


def with_anchor(url: str, anchor: str) -> str:
    if anchor:
        if not anchor.startswith("#"):
            anchor = "#" + anchor
        return url + anchor
    return url


def focus_existing_docs_tab(target_url: str) -> bool:
    return _focus_existing_docs_tab_impl(
        target_url,
        platform=sys.platform,
        run_cmd=subprocess.run,
    )


def open_docs_url(target_url: str) -> None:
    global _DOCS_ALREADY_OPENED, _LAST_DOCS_URL

    if _DOCS_ALREADY_OPENED and _LAST_DOCS_URL == target_url:
        if focus_existing_docs_tab(target_url):
            return
        webbrowser.open_new_tab(target_url)
        _DOCS_ALREADY_OPENED = True
        _LAST_DOCS_URL = target_url
        return

    webbrowser.open_new_tab(target_url)
    _DOCS_ALREADY_OPENED = True
    _LAST_DOCS_URL = target_url


def resolve_docs_path(env, html_file: str) -> Path | None:
    return _resolve_docs_path_impl(Path(env.agilab_pck), html_file, path_cls=Path)


def open_docs(env, html_file: str = "index.html", anchor: str = "") -> None:
    docs_path = resolve_docs_path(env, html_file)
    if docs_path is None:
        print("Documentation file not found locally. Opening online docs instead.")
        target_url = with_anchor(ONLINE_DOCS_INDEX, anchor)
    else:
        target_url = with_anchor(docs_path.as_uri(), anchor)
    open_docs_url(target_url)


def open_local_docs(env, html_file: str = "index.html", anchor: str = "") -> None:
    docs_path = resolve_docs_path(env, html_file)
    if docs_path is None:
        raise FileNotFoundError(f"Local documentation file '{html_file}' was not found.")
    open_docs_url(with_anchor(docs_path.as_uri(), anchor))


def read_base64_image(image_path) -> str:
    with open(image_path, "rb") as img_file:
        return base64.b64encode(img_file.read()).decode()


def read_css_text(resources_path: Path) -> str:
    with open(resources_path / "code_editor.scss") as file:
        return file.read()


def read_theme_css(base_path: Path | None = None, *, module_file: str) -> str | None:
    return _read_theme_css_impl(base_path, module_file=module_file, path_cls=Path)


def read_version_from_pyproject(env) -> str | None:
    return _read_version_from_pyproject_impl(env, path_cls=Path)


def detect_agilab_version(env) -> str:
    if env and env.is_source_env:
        version = read_version_from_pyproject(env)
        if version:
            suffix = detect_dev_version_suffix(Path(env.agilab_pck or "."), run_cmd=subprocess.run)
            return f"{version}{suffix}"
    return detect_installed_version(_importlib_metadata)
