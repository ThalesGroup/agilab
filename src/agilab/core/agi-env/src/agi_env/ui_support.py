from __future__ import annotations

import base64
import subprocess
import sys
import tomllib
import webbrowser
from pathlib import Path
from typing import Optional

try:  # pragma: no cover - standard-library availability differs by Python version
    from importlib import metadata as _importlib_metadata  # type: ignore
except Exception:  # pragma: no cover
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

    except Exception as _toml_exc:  # pragma: no cover - defensive

        def _dump_toml_payload(data: dict, handle, _import_error=_toml_exc) -> None:
            raise RuntimeError(
                "Writing settings requires the 'tomli-w' or 'tomlkit' package."
            ) from _import_error


_GLOBAL_STATE_FILE = Path.home() / ".local" / "share" / "agilab" / "app_state.toml"
_LEGACY_LAST_APP_FILE = Path.home() / ".local" / "share" / "agilab" / ".last-active-app"
_DOCS_ALREADY_OPENED = False
_LAST_DOCS_URL: Optional[str] = None


def load_global_state() -> dict[str, str]:
    try:
        if _GLOBAL_STATE_FILE.exists():
            with _GLOBAL_STATE_FILE.open("rb") as fh:
                data = tomllib.load(fh)
                return data if isinstance(data, dict) else {}
    except Exception:
        pass

    try:
        if _LEGACY_LAST_APP_FILE.exists():
            raw = _LEGACY_LAST_APP_FILE.read_text(encoding="utf-8").strip()
            if raw:
                return {"last_active_app": raw}
    except Exception:
        pass
    return {}


def persist_global_state(data: dict[str, str]) -> None:
    try:
        _GLOBAL_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _GLOBAL_STATE_FILE.open("wb") as fh:
            _dump_toml_payload(data, fh)
    except Exception:
        pass


def load_last_active_app() -> Path | None:
    state = load_global_state()
    raw = state.get("last_active_app")
    if not raw:
        return None
    try:
        candidate = Path(raw).expanduser()
    except Exception:
        return None
    return candidate if candidate.exists() else None


def store_last_active_app(path: Path) -> None:
    try:
        normalized = str(path.expanduser())
    except Exception:
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
    if sys.platform != "darwin":
        return False

    escaped = target_url.replace("\\", "\\\\").replace("\"", "\\\"")
    script = f'''
on chrome_activate(targetUrl)
    tell application "Google Chrome"
        repeat with w in windows
            set tabIndex to 0
            repeat with t in tabs of w
                set tabIndex to tabIndex + 1
                if (URL of t is targetUrl) then
                    set active tab index of w to tabIndex
                    set index of w to 1
                    activate
                    return true
                end if
            end repeat
        end repeat
    end tell
    return false
end chrome_activate

on safari_activate(targetUrl)
    tell application "Safari"
        repeat with w in windows
            repeat with t in tabs of w
                if (URL of t is targetUrl) then
                    set current tab of w to t
                    set index of w to 1
                    activate
                    return true
                end if
            end repeat
        end repeat
    end tell
    return false
end safari_activate

tell application "System Events"
    set chromeRunning to (exists process "Google Chrome")
    set safariRunning to (exists process "Safari")
end tell

if chromeRunning then
    if chrome_activate("{escaped}") then return true
end if

if safariRunning then
    if safari_activate("{escaped}") then return true
end if

return false
'''

    try:
        result = subprocess.run(
            ["osascript", "-"],
            input=script,
            text=True,
            capture_output=True,
            timeout=2,
        )
        if result.returncode == 0:
            return result.stdout.strip().lower().endswith("true")
    except Exception:
        pass
    return False


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
    candidates = [
        env.agilab_pck.parent / "docs" / "build",
        env.agilab_pck.parent / "docs" / "html",
        env.agilab_pck / "docs" / "build",
        env.agilab_pck / "docs" / "html",
    ]

    for base in candidates:
        candidate = base / html_file
        if candidate.exists():
            return candidate

    docs_root = env.agilab_pck.parent / "docs"
    if docs_root.exists():
        matches = sorted(docs_root.rglob(html_file))
        if matches:
            return matches[0]
    return None


def open_docs(env, html_file: str = "index.html", anchor: str = "") -> None:
    docs_path = resolve_docs_path(env, html_file)
    if docs_path is None:
        print("Documentation file not found locally. Opening online docs instead.")
        target_url = with_anchor("https://thalesgroup.github.io/agilab/index.html", anchor)
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
    if base_path is None:
        base_path = Path(module_file).resolve().parents[1] / "resources"
    css_path = Path(base_path) / "theme.css"
    if not css_path.exists():
        return None
    try:
        return css_path.read_text(encoding="utf-8")
    except Exception:
        try:
            with css_path.open("rb") as fh:
                return fh.read().decode("utf-8", errors="replace")
        except Exception:
            return None


def read_version_from_pyproject(env) -> str | None:
    try:
        root = env.agilab_pck if env else None
        py_paths: list[Path] = []
        if root:
            py_paths.append(Path(root) / "pyproject.toml")
        try:
            here = Path.cwd().resolve()
            for _ in range(4):
                py = here / "pyproject.toml"
                if py.exists():
                    py_paths.append(py)
                    break
                if here.parent == here:
                    break
                here = here.parent
        except Exception:
            pass
        for py in py_paths:
            try:
                if not py.exists():
                    continue
                with py.open("rb") as handle:
                    data = tomllib.load(handle)
                project = data.get("project") or {}
                name = str(project.get("name") or "").strip().lower()
                if name and name != "agilab":
                    continue
                version = str(project.get("version") or "").strip()
                if version:
                    return version
            except Exception:
                continue
        return None
    except Exception:
        return None


def detect_agilab_version(env) -> str:
    if env and env.is_source_env:
        version = read_version_from_pyproject(env)
        if version:
            suffix = ""
            try:
                repo = Path(env.agilab_pck or ".")
                sha = subprocess.run(
                    ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                ).stdout.strip()
                dirty = subprocess.run(
                    ["git", "-C", str(repo), "status", "--porcelain"],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                ).stdout
                dirty_mark = "*" if dirty.strip() else ""
                suffix = f"+dev.{sha}{dirty_mark}" if sha else "+dev"
            except Exception:
                suffix = "+dev"
            return f"{version}{suffix}"
    if _importlib_metadata is not None:
        try:
            return _importlib_metadata.version("agilab")
        except Exception:
            pass
    return ""
