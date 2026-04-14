"""Execution helpers extracted from pagelib."""

from __future__ import annotations

import os
import re
import runpy
import sys
from io import StringIO
from pathlib import Path


def _coerce_code_text(code) -> str:
    if isinstance(code, (list, tuple)):
        if len(code) >= 3:
            return str(code[2])
        if code:
            return str(code[-1])
        return ""
    if code is None:
        return ""
    return str(code)


def _resolve_target_path(path, *, env_agi_env, path_cls=Path) -> Path:
    try:
        target_path = path_cls(path) if path else path_cls(env_agi_env)
    except TypeError:
        target_path = path_cls(env_agi_env)
    target_path = target_path.expanduser()
    if target_path.name == ".venv":
        target_path = target_path.parent
    return target_path


def _build_snippet_file(code_str: str, *, env, logger, re_module=re, path_cls=Path) -> Path:
    pattern = r"await\s+(?:Agi\.)?([^\(]+)\("
    matches = re_module.findall(pattern, code_str)
    snippet_name = matches[0] if matches else "AGI_command"
    snippet_prefix = re_module.sub(r"[^0-9A-Za-z_]+", "_", str(snippet_name)).strip("_") or "AGI_unknown_command"
    target_slug = re_module.sub(r"[^0-9A-Za-z_]+", "_", str(env.target)).strip("_") or "unknown_app_name"

    runenv_path = path_cls(env.runenv)
    logger.info(f"mkdir {runenv_path}")
    runenv_path.mkdir(parents=True, exist_ok=True)

    snippet_file = runenv_path / f"{snippet_prefix}_{target_slug}.py"
    snippet_file.write_text(code_str, encoding="utf-8")
    return snippet_file


def run_agi(
    code,
    *,
    env,
    path=".",
    streamlit,
    logger,
    run_with_output_fn,
    diagnose_data_directory_fn,
    path_cls=Path,
    re_module=re,
):
    """Prepare a snippet file, validate the target path, and execute it."""
    code_str = _coerce_code_text(code).strip("\n")
    if not code_str:
        streamlit.warning("No code supplied for execution.")
        return None

    target_path = _resolve_target_path(path, env_agi_env=env.agi_env, path_cls=path_cls)
    snippet_file = _build_snippet_file(code_str, env=env, logger=logger, re_module=re_module, path_cls=path_cls)

    try:
        path_exists = target_path.exists()
    except PermissionError as exc:
        hint = diagnose_data_directory_fn(target_path)
        message = f"Permission denied while accessing '{target_path}': {exc}"
        if hint:
            message = f"{message}\n{hint}"
        streamlit.error(message)
        streamlit.stop()
    except OSError as exc:
        streamlit.error(f"Unable to access '{target_path}': {exc}")
        streamlit.stop()

    if path_exists:
        return run_with_output_fn(env, f"uv -q run python {snippet_file}", str(target_path))

    streamlit.info(
        "Please do an install first, ensure pyproject.toml lists required dependencies and rerun the project installation."
    )
    streamlit.stop()


def run_lab(
    query,
    snippet,
    codex,
    *,
    env_overrides=None,
    warning_fn=None,
    os_module=os,
    sys_module=sys,
    runpy_module=runpy,
    path_cls=Path,
):
    """Execute a generated snippet while temporarily overriding environment variables."""
    if not query:
        return None

    path_cls(snippet).write_text(query[2], encoding="utf-8")
    output = StringIO()
    sentinel = object()
    previous_env = {
        key: os_module.environ.get(key, sentinel)
        for key in (env_overrides or {})
    }
    try:
        for key, value in (env_overrides or {}).items():
            if value is None:
                os_module.environ.pop(key, None)
            else:
                os_module.environ[str(key)] = str(value)

        stdout, stderr = sys_module.stdout, sys_module.stderr
        sys_module.stdout = output
        sys_module.stderr = output
        try:
            runpy_module.run_path(codex)
        finally:
            sys_module.stdout = stdout
            sys_module.stderr = stderr
    except (ImportError, OSError, RuntimeError, SyntaxError, NameError, ValueError, TypeError, AttributeError, KeyError, IndexError) as exc:
        if warning_fn is not None:
            warning_fn(f"Error: {exc}")
        print(f"Error: {exc}", file=output)
    finally:
        for key, value in previous_env.items():
            if value is sentinel:
                os_module.environ.pop(key, None)
            else:
                os_module.environ[key] = str(value)

    return output.getvalue().strip()
