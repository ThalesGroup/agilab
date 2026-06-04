from __future__ import annotations

import re
from typing import Any

TERMINAL_LOG_WIDTH = 360
LOG_PATH_LIMIT = 120
LOG_DETAIL_LIMIT = 220
COMPACT_LOG_SIGNAL_LIMIT = 8
COMPACT_LOG_TAIL_LIMIT = 4
COMPACT_LOG_CONTEXT_RADIUS = 1
COMPACT_LOG_DEBUG_MAX_LINES = 120
_ELLIPSIS = "..."
_SECRET_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"(?i)\b(api[_-]?key|token|password|secret|authorization)\s*=\s*([^\s;]+)"
        ),
        r"\1=<redacted>",
    ),
    (re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{16,}\b"), "<redacted-token>"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"), "<redacted-token>"),
    (re.compile(r"\bpypi-[A-Za-z0-9_-]{20,}\b"), "<redacted-token>"),
)
_HIGH_VALUE_LOG_PATTERNS: tuple[str, ...] = (
    "traceback",
    "error",
    "exception",
    "failed",
    "failure",
    "fatal",
    "denied",
    "missing",
    "not found",
    "no module named",
    "modulenotfounderror",
    "importerror",
    "permission denied",
    "connection refused",
    "no route to host",
    "timed out",
    "timeout",
    "unsatisfiable",
    "non-zero exit status",
    "exit code",
)


def bound_log_value(value: Any, limit: int = TERMINAL_LOG_WIDTH) -> str:
    """Return a single-line string bounded for compact terminal logging."""
    try:
        text = str(value)
    except Exception as exc:  # pragma: no cover - defensive formatting boundary
        text = f"<unprintable {type(value).__name__}: {exc}>"

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\n", "\\n").replace("\t", "\\t")
    if limit <= 0:
        return ""
    if len(normalized) <= limit:
        return normalized
    if limit <= len(_ELLIPSIS):
        return _ELLIPSIS[:limit]
    return normalized[: limit - len(_ELLIPSIS)] + _ELLIPSIS


def redact_log_value(value: Any) -> str:
    """Redact common secret-like values before rendering prompt-facing logs."""
    try:
        text = str(value)
    except Exception as exc:  # pragma: no cover - defensive formatting boundary
        text = f"<unprintable {type(value).__name__}: {exc}>"
    for pattern, replacement in _SECRET_REPLACEMENTS:
        text = pattern.sub(replacement, text)
    return text


def is_high_value_log_line(line: str) -> bool:
    """Return whether a line is likely worth surfacing in a compact diagnostic."""
    normalized = str(line or "").strip().lower()
    return bool(normalized) and any(pattern in normalized for pattern in _HIGH_VALUE_LOG_PATTERNS)


def _bounded_render_line(line_number: int, line: str, *, max_line_chars: int) -> str:
    return f"{line_number}: {bound_log_value(redact_log_value(line), max_line_chars)}"


def _unique_ordered(values: list[int]) -> list[int]:
    seen: set[int] = set()
    ordered: list[int] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def compact_log_view(
    payload: Any,
    *,
    verbose: int = 1,
    signal_limit: int = COMPACT_LOG_SIGNAL_LIMIT,
    tail_limit: int = COMPACT_LOG_TAIL_LIMIT,
    context_radius: int = COMPACT_LOG_CONTEXT_RADIUS,
    max_line_chars: int = LOG_DETAIL_LIMIT,
    debug_max_lines: int = COMPACT_LOG_DEBUG_MAX_LINES,
) -> dict[str, Any]:
    """Return a token-budgeted, signal-first view of a log payload.

    Verbosity levels match AGILAB runtime diagnostics:
    0 only reports counts and the newest signal, 1 adds bounded signal/tail
    lines, 2 adds context windows around signals, and 3 includes the full log
    only when it is already small enough for prompt-facing use.
    """
    text = "" if payload is None else str(payload)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    verbose = max(0, min(int(verbose or 0), 3))
    signal_indexes = [index for index, line in enumerate(lines) if is_high_value_log_line(line)]

    if verbose <= 0:
        selected_signal_indexes = signal_indexes[-1:]
        selected_tail_indexes: list[int] = []
    else:
        selected_signal_indexes = signal_indexes[: max(signal_limit, 0)]
        selected_tail_indexes = list(range(max(len(lines) - max(tail_limit, 0), 0), len(lines)))

    context_indexes: list[int] = []
    if verbose >= 2:
        for index in selected_signal_indexes:
            start = max(index - max(context_radius, 0), 0)
            stop = min(index + max(context_radius, 0) + 1, len(lines))
            context_indexes.extend(range(start, stop))
        context_indexes = _unique_ordered(context_indexes)

    debug_indexes: list[int] = []
    debug_note = ""
    if verbose >= 3:
        if len(lines) <= debug_max_lines:
            debug_indexes = list(range(len(lines)))
        else:
            debug_note = (
                f"debug log has {len(lines)} lines; full prompt-facing output is capped "
                f"at {debug_max_lines} lines, so use the raw log artifact for exhaustive debugging"
            )

    included_indexes = set(selected_signal_indexes) | set(selected_tail_indexes) | set(context_indexes) | set(debug_indexes)
    omitted_line_count = max(len(lines) - len(included_indexes), 0)
    signals = [
        {
            "line": index + 1,
            "text": bound_log_value(redact_log_value(lines[index]), max_line_chars),
        }
        for index in selected_signal_indexes
    ]
    tail = [_bounded_render_line(index + 1, lines[index], max_line_chars=max_line_chars) for index in selected_tail_indexes]
    context = [
        _bounded_render_line(index + 1, lines[index], max_line_chars=max_line_chars)
        for index in context_indexes
        if index not in selected_signal_indexes
    ]
    debug_lines = [
        _bounded_render_line(index + 1, lines[index], max_line_chars=max_line_chars)
        for index in debug_indexes
    ]
    note = (
        debug_note
        or "compact view keeps raw logs out of prompt context; increase diagnostics only when the signal is useful"
    )
    return {
        "strategy": "signal-first-token-budget",
        "verbose": verbose,
        "line_count": len(lines),
        "char_count": len(text),
        "signal_count": len(signal_indexes),
        "omitted_line_count": omitted_line_count,
        "signals": signals,
        "context": context,
        "tail": tail,
        "debug_lines": debug_lines,
        "note": note,
    }


def render_compact_log_view(view: dict[str, Any]) -> str:
    """Render ``compact_log_view`` output as compact text for Streamlit or Codex."""
    lines = [
        "AGILAB compact log",
        f"strategy: {view.get('strategy', 'signal-first-token-budget')}",
        (
            f"lines: {view.get('line_count', 0)} "
            f"signals: {view.get('signal_count', 0)} "
            f"omitted: {view.get('omitted_line_count', 0)} "
            f"verbose: {view.get('verbose', 1)}"
        ),
    ]
    signals = view.get("signals") or []
    if signals:
        lines.append("signals:")
        for signal in signals:
            lines.append(f"- {signal.get('line')}: {signal.get('text')}")
    context = view.get("context") or []
    if context:
        lines.append("context:")
        lines.extend(f"- {item}" for item in context)
    tail = view.get("tail") or []
    if tail:
        lines.append("tail:")
        lines.extend(f"- {item}" for item in tail)
    debug_lines = view.get("debug_lines") or []
    if debug_lines:
        lines.append("debug_lines:")
        lines.extend(f"- {item}" for item in debug_lines)
    note = str(view.get("note") or "").strip()
    if note:
        lines.append(f"note: {note}")
    return "\n".join(lines)
