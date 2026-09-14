"""Bounded observations of one terminal Codex JSONL usage report."""

import json
from collections.abc import Mapping

from agilab.security.secret_uri import redact_text


def nonnegative_integer(value):
    return value if type(value) is int and value >= 0 else None


def _normalize_usage(raw):
    input_tokens = nonnegative_integer(raw.get("input_tokens"))
    output_tokens = nonnegative_integer(raw.get("output_tokens"))
    if input_tokens is None or output_tokens is None:
        return None
    details = raw.get("input_tokens_details")
    cached = raw.get("cached_input_tokens")
    if cached is None and isinstance(details, Mapping):
        cached = details.get("cached_tokens")
    if cached is not None and (
        nonnegative_integer(cached) is None or cached > input_tokens
    ):
        return None
    total = raw.get("total_tokens", input_tokens + output_tokens)
    if nonnegative_integer(total) != input_tokens + output_tokens:
        return None
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_input_tokens": cached,
        "uncached_input_tokens": input_tokens - cached if cached is not None else None,
        "total_tokens": total,
    }


def parse_codex_jsonl(value: str) -> dict[str, object]:
    """Observe one terminal report. Missing/ambiguous usage is never zero usage.

    These are provider-reported counts in a local artifact, not billing or
    producer attestation. Nested tool-output JSON is not a usage authority.
    """
    if len(value.encode("utf-8")) > 8 * 1024 * 1024:
        raise ValueError("Usage evidence exceeds 8 MiB")
    count = invalid = terminal_count = started = failed = 0
    usage = None
    types, models = set(), []

    def unique_pairs(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("Duplicate usage JSON key")
            result[key] = item
        return result

    def invalid_constant(value):
        raise ValueError("Nonfinite usage JSON")

    for line in value.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(
                line, object_pairs_hook=unique_pairs, parse_constant=invalid_constant
            )
            if not isinstance(event, dict):
                raise ValueError("not an event")
        except (ValueError, RecursionError):
            invalid += 1
            continue
        count += 1
        kind = event.get("type")
        if kind == "turn.started":
            started += 1
            if terminal_count:
                failed += 1
        if kind in ("turn.failed", "error"):
            failed += 1
        if isinstance(kind, str) and len(types) < 64:
            types.add(redact_text(kind)[:128])
        model = event.get("model")
        if isinstance(model, str) and len(models) < 16:
            model = redact_text(model)[:128]
            if model not in models:
                models.append(model)
        if kind == "turn.completed":
            terminal_count += 1
            raw = event.get("usage")
            usage = _normalize_usage(raw) if isinstance(raw, dict) else None
    status = (
        "available"
        if usage is not None
        and terminal_count == 1
        and not invalid
        and not failed
        and started <= 1
        else "missing"
    )
    if terminal_count > 1 or started > 1:
        status = "ambiguous"
    return {
        "status": status,
        "usage": usage if status == "available" else None,
        "event_count": count,
        "invalid_line_count": invalid,
        "event_types": sorted(types),
        "reported_models": models,
    }
