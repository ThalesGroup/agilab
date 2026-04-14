"""Documentation and version helpers extracted from ui_support."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path


ONLINE_DOCS_INDEX = "https://thalesgroup.github.io/agilab/index.html"


def focus_existing_docs_tab(
    target_url: str,
    *,
    platform: str = sys.platform,
    run_cmd=subprocess.run,
) -> bool:
    """Try to focus an already-open docs tab on macOS browsers."""
    if platform != "darwin":
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
        result = run_cmd(
            ["osascript", "-"],
            input=script,
            text=True,
            capture_output=True,
            timeout=2,
        )
    except (OSError, RuntimeError, subprocess.TimeoutExpired, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and result.stdout.strip().lower().endswith("true")


def resolve_docs_path(agilab_pck: Path, html_file: str, *, path_cls=Path) -> Path | None:
    """Resolve a local documentation file from common build/html roots."""
    candidates = [
        agilab_pck.parent / "docs" / "build",
        agilab_pck.parent / "docs" / "html",
        agilab_pck / "docs" / "build",
        agilab_pck / "docs" / "html",
    ]
    for base in candidates:
        candidate = base / html_file
        if candidate.exists():
            return candidate

    docs_root = agilab_pck.parent / "docs"
    if docs_root.exists():
        matches = sorted(docs_root.rglob(html_file))
        if matches:
            return matches[0]
    return None


def read_theme_css(base_path: Path | None = None, *, module_file: str, path_cls=Path) -> str | None:
    """Read theme.css as UTF-8, falling back to lossy binary decode when needed."""
    if base_path is None:
        base_path = path_cls(module_file).resolve().parents[1] / "resources"
    css_path = path_cls(base_path) / "theme.css"
    if not css_path.exists():
        return None
    try:
        return css_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        try:
            with css_path.open("rb") as handle:
                return handle.read().decode("utf-8", errors="replace")
        except OSError:
            return None


def read_version_from_pyproject(env, *, toml_module=tomllib, path_cls=Path) -> str | None:
    """Read the AGILAB version from the nearest relevant pyproject.toml."""
    root = getattr(env, "agilab_pck", None) if env else None
    py_paths: list[Path] = []
    if root:
        py_paths.append(path_cls(root) / "pyproject.toml")
    try:
        here = path_cls.cwd().resolve()
        for _ in range(4):
            pyproject = here / "pyproject.toml"
            if pyproject.exists():
                py_paths.append(pyproject)
                break
            if here.parent == here:
                break
            here = here.parent
    except OSError:
        pass

    for pyproject in py_paths:
        try:
            if not pyproject.exists():
                continue
            with pyproject.open("rb") as handle:
                data = toml_module.load(handle)
            project = data.get("project") or {}
            name = str(project.get("name") or "").strip().lower()
            if name and name != "agilab":
                continue
            version = str(project.get("version") or "").strip()
            if version:
                return version
        except (OSError, toml_module.TOMLDecodeError, TypeError, ValueError):
            continue
    return None


def detect_dev_version_suffix(repo: Path, *, run_cmd=subprocess.run) -> str:
    """Return ``+dev`` metadata derived from git, or a plain ``+dev`` fallback."""
    try:
        sha = run_cmd(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        ).stdout.strip()
        dirty = run_cmd(
            ["git", "-C", str(repo), "status", "--porcelain"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        ).stdout
    except (OSError, RuntimeError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return "+dev"
    dirty_mark = "*" if dirty.strip() else ""
    return f"+dev.{sha}{dirty_mark}" if sha else "+dev"


def detect_installed_version(importlib_metadata_module) -> str:
    """Read the installed package version, tolerating missing metadata."""
    if importlib_metadata_module is None:
        return ""
    package_not_found = getattr(importlib_metadata_module, "PackageNotFoundError", ModuleNotFoundError)
    try:
        return importlib_metadata_module.version("agilab")
    except (package_not_found, RuntimeError):
        return ""
