"""Small UI performance helpers for Streamlit rerun paths."""

from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable


UI_DISCOVERY_CACHE_DISABLE_ENV = "AGILAB_DISABLE_UI_DISCOVERY_CACHE"
UI_TIMING_TRACE_ENV_KEY = "AGILAB_UI_TIMING_TRACE"
UI_TIMING_SESSION_KEY = "agilab_ui_timing_spans"
DEFAULT_TIMING_LIMIT = 40


@dataclass(frozen=True, slots=True)
class UiTimingSpan:
    """One opt-in timing sample from the Streamlit UI rerun path."""

    label: str
    category: str
    elapsed_ms: float

    def as_row(self) -> dict[str, str]:
        row = asdict(self)
        row["elapsed_ms"] = f"{self.elapsed_ms:.1f}"
        return {key: str(value) for key, value in row.items()}


def flag_enabled(value: object) -> bool:
    """Return True for common environment-style truthy values."""

    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "debug"}


def ui_discovery_cache_enabled(environ: Any = os.environ) -> bool:
    """Return whether in-process UI discovery caches should be used."""

    return not flag_enabled(environ.get(UI_DISCOVERY_CACHE_DISABLE_ENV, ""))


def ui_timing_trace_enabled(environ: Any = os.environ) -> bool:
    """Return whether detailed UI timing spans should be recorded."""

    return flag_enabled(environ.get(UI_TIMING_TRACE_ENV_KEY, ""))


def path_stat_signature(path: Path, *, label: str | None = None) -> tuple[str, bool, int, int] | None:
    """Return a stable stat signature for one path, or None when unavailable."""

    try:
        stat = path.stat()
    except OSError:
        return None
    name = label if label is not None else path.name
    return (name, path.is_dir(), stat.st_mtime_ns, stat.st_size)


def child_path_signatures(
    root: Path,
    *,
    child_suffix: str,
    extra_relative_paths: Iterable[str] = (),
    include_root: bool = True,
) -> tuple[tuple[str, bool, int, int], ...]:
    """Return a cheap invalidation signature for top-level UI registry folders."""

    signatures: list[tuple[str, bool, int, int]] = []
    if include_root:
        root_signature = path_stat_signature(root, label=".")
        if root_signature is not None:
            signatures.append(root_signature)
    try:
        children = sorted(root.iterdir(), key=lambda path: path.name.casefold())
    except OSError:
        return tuple(signatures)

    relative_paths = tuple(Path(raw_path) for raw_path in extra_relative_paths)
    for child in children:
        if child.name.startswith(".") or not child.is_dir() or not child.name.endswith(child_suffix):
            continue
        child_signature = path_stat_signature(child)
        if child_signature is not None:
            signatures.append(child_signature)
        for relative_path in relative_paths:
            candidate = child / relative_path
            signature = path_stat_signature(
                candidate,
                label=f"{child.name}/{relative_path.as_posix()}",
            )
            if signature is not None:
                signatures.append(signature)
    return tuple(signatures)


def record_ui_timing_span(
    session_state: Any,
    *,
    label: str,
    started_at: float,
    category: str = "page",
    perf_counter: Callable[[], float] = time.perf_counter,
    limit: int = DEFAULT_TIMING_LIMIT,
) -> UiTimingSpan:
    """Append one timing span to Streamlit session state and return it."""

    elapsed_ms = max(0.0, (perf_counter() - started_at) * 1000.0)
    span = UiTimingSpan(label=str(label), category=str(category), elapsed_ms=elapsed_ms)
    try:
        spans = list(session_state.get(UI_TIMING_SESSION_KEY, ()))
        spans.append(span.as_row())
        session_state[UI_TIMING_SESSION_KEY] = spans[-max(1, int(limit)) :]
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    return span
