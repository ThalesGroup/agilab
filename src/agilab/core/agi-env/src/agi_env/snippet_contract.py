"""Versioned contract helpers for generated AGILAB snippets."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable


CURRENT_SNIPPET_API_VERSION = 1
CURRENT_SNIPPET_API = "agi.snippet.v1"
SUPPORTED_SNIPPET_APIS = frozenset({CURRENT_SNIPPET_API})
SNIPPET_API_NAME = "AGILAB_SNIPPET_API"
SNIPPET_API_VERSION_NAME = "AGILAB_SNIPPET_API_VERSION"
GENERATED_SNIPPET_HEADER = "# AGILAB generated snippet"
_SNIPPET_API_RE = re.compile(
    rf"^\s*{SNIPPET_API_NAME}\s*=\s*([\"'])(?P<api>[^\"']+)\1\s*(?:#.*)?$",
    re.MULTILINE,
)
_SNIPPET_API_COMMENT_RE = re.compile(r"^\s*#\s*snippet_api:\s*(?P<api>\S+)\s*$", re.MULTILINE)
_LEGACY_SNIPPET_API_VERSION_RE = re.compile(
    rf"^\s*{SNIPPET_API_VERSION_NAME}\s*=\s*([0-9]+)\s*(?:#.*)?$",
    re.MULTILINE,
)
_AGI_API_TOKENS = (
    "from agi_cluster.agi_distributor import AGI",
    "from agi_cluster.agi_distributor import AGI,",
    "import agi_cluster",
    "AGI.install(",
    "AGI.run(",
    "AGI.serve(",
    "AGI.get_distrib(",
    "RunRequest(",
    "StageRequest(",
)


def snippet_contract_lines(
    *,
    app: str | None = None,
    generator: str = "agilab",
) -> list[str]:
    """Return the guard lines embedded in generated AGILAB snippets."""

    lines = [
        GENERATED_SNIPPET_HEADER,
        f"# snippet_api: {CURRENT_SNIPPET_API}",
    ]
    if app:
        lines.append(f"# app: {app}")
    if generator:
        lines.append(f"# generator: {generator}")
    lines.extend(
        [
            "from agi_env.snippet_contract import require_supported_snippet_api",
            "",
            f'{SNIPPET_API_NAME} = "{CURRENT_SNIPPET_API}"',
            f"require_supported_snippet_api({SNIPPET_API_NAME})",
        ]
    )
    return lines


def snippet_contract_block(
    *,
    app: str | None = None,
    generator: str = "agilab",
) -> str:
    """Return the generated snippet guard as a Python source block."""

    return "\n".join(snippet_contract_lines(app=app, generator=generator))


def extract_snippet_api(code: str | None) -> str | None:
    """Extract the semantic snippet API marker from source text."""

    text = str(code or "")
    match = _SNIPPET_API_RE.search(text)
    if match:
        return match.group("api")
    comment_match = _SNIPPET_API_COMMENT_RE.search(text)
    if comment_match:
        return comment_match.group("api")
    legacy_match = _LEGACY_SNIPPET_API_VERSION_RE.search(text)
    if legacy_match:
        return f"legacy.version.{legacy_match.group(1)}"
    return None


def extract_snippet_api_version(code: str | None) -> str | None:
    """Compatibility wrapper for older callers; prefer ``extract_snippet_api``."""

    return extract_snippet_api(code)


def is_generated_agi_snippet(code: str | None) -> bool:
    """Return True when code appears to call AGILAB core AGI APIs."""

    text = str(code or "")
    return any(token in text for token in _AGI_API_TOKENS)


def is_supported_snippet_api(code: str | None) -> bool:
    """Return True when snippet source carries a supported semantic API marker."""

    return extract_snippet_api(code) in SUPPORTED_SNIPPET_APIS


def is_current_snippet_api(code: str | None) -> bool:
    """Compatibility wrapper for older callers; prefer ``is_supported_snippet_api``."""

    return is_supported_snippet_api(code)


def stale_snippet_cleanup_message(paths: Iterable[str | Path] | None = None) -> str:
    """Return an actionable cleanup message for stale generated snippets."""

    path_list = [str(path) for path in (paths or []) if str(path)]
    if path_list:
        preview = ", ".join(path_list[:5])
        extra = f" Affected snippet{'s' if len(path_list) != 1 else ''}: {preview}."
    else:
        extra = ""
    return (
        "AGILAB core snippet API changed. Clean up old generated AGI_*.py snippets "
        "and rerun ORCHESTRATE INSTALL -> DISTRIBUTE -> RUN to regenerate them."
        f"{extra}"
    )


def clean_stale_snippet_files(paths: Iterable[str | Path]) -> tuple[list[Path], list[Path]]:
    """Delete only generated AGI snippets that use an unsupported snippet API."""

    deleted: list[Path] = []
    failed: list[Path] = []
    for raw_path in paths:
        try:
            path = Path(raw_path).expanduser()
        except (TypeError, ValueError, RuntimeError, OSError):
            failed.append(Path(str(raw_path)))
            continue
        if not path.exists() or not path.is_file():
            continue
        try:
            code = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            failed.append(path)
            continue
        if not is_generated_agi_snippet(code) or is_supported_snippet_api(code):
            continue
        try:
            path.unlink()
            deleted.append(path)
        except OSError:
            failed.append(path)
    return deleted, failed


def require_supported_snippet_api(api: int | str | None) -> None:
    """Fail fast when a generated snippet targets an unsupported AGILAB core API."""

    if str(api or "") not in SUPPORTED_SNIPPET_APIS:
        raise RuntimeError(stale_snippet_cleanup_message())


def require_current_snippet_api(version: int | str | None) -> None:
    """Compatibility wrapper for older generated snippets."""

    if version == CURRENT_SNIPPET_API_VERSION:
        raise RuntimeError(stale_snippet_cleanup_message())
    require_supported_snippet_api(version)
