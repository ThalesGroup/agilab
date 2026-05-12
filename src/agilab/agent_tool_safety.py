# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Safety primitives for agent-exposed AGILAB tools."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from agilab.secret_uri import redact_mapping, redact_text


SCHEMA = "agilab.agent_tool_safety.v1"
_DESTRUCTIVE_WORDS = frozenset(
    {
        "clean",
        "clear",
        "delete",
        "destroy",
        "drop",
        "kill",
        "overwrite",
        "purge",
        "remove",
        "reset",
        "restart",
        "rm",
        "stop",
        "terminate",
        "uninstall",
        "wipe",
    }
)
_ACTION_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


class ToolConfirmationRequired(PermissionError):
    """Raised when an agent tool invocation needs explicit confirmation."""


@dataclass(frozen=True)
class ToolSafetyDecision:
    """Result of checking whether an agent tool invocation may proceed."""

    action: str
    allowed: bool
    risk: str
    reason: str
    confirmation_token: str | None = None


@dataclass(frozen=True)
class ProgressEvent:
    """One append-only progress record for agent or MCP-style tool execution."""

    schema: str
    event: str
    run_id: str
    status: str
    message: str
    created_at: str
    metadata: dict[str, Any]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical_payload(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _action_terms(action: str) -> set[str]:
    return {term.lower() for term in _ACTION_TOKEN_RE.findall(action)}


def classify_tool_action(action: str, metadata: Mapping[str, Any] | None = None) -> str:
    """Classify an agent tool action as ``safe`` or ``destructive``."""
    meta = metadata or {}
    if bool(meta.get("destructive")):
        return "destructive"
    kind = str(meta.get("kind", "") or "").lower()
    if kind == "destructive":
        return "destructive"
    return "destructive" if _action_terms(action) & _DESTRUCTIVE_WORDS else "safe"


def confirmation_token(action: str, arguments: Mapping[str, Any] | None = None) -> str:
    """Return the stable operator token required for a destructive action."""
    payload = {
        "schema": SCHEMA,
        "action": action,
        "arguments": arguments or {},
    }
    digest = hashlib.sha256(_canonical_payload(payload).encode("utf-8")).hexdigest()
    return f"confirm:{digest[:16]}"


def evaluate_tool_invocation(
    action: str,
    arguments: Mapping[str, Any] | None = None,
    *,
    confirmation: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ToolSafetyDecision:
    """Return whether an agent tool invocation is allowed to execute."""
    risk = classify_tool_action(action, metadata)
    if risk != "destructive":
        return ToolSafetyDecision(
            action=action,
            allowed=True,
            risk=risk,
            reason="action does not match destructive tool semantics",
        )
    expected = confirmation_token(action, arguments)
    if confirmation == expected:
        return ToolSafetyDecision(
            action=action,
            allowed=True,
            risk=risk,
            reason="destructive action confirmed by operator token",
            confirmation_token=expected,
        )
    return ToolSafetyDecision(
        action=action,
        allowed=False,
        risk=risk,
        reason="destructive action requires explicit operator confirmation",
        confirmation_token=expected,
    )


def require_tool_invocation_allowed(
    action: str,
    arguments: Mapping[str, Any] | None = None,
    *,
    confirmation: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ToolSafetyDecision:
    """Return the decision or raise when confirmation is missing."""
    decision = evaluate_tool_invocation(
        action,
        arguments,
        confirmation=confirmation,
        metadata=metadata,
    )
    if not decision.allowed:
        raise ToolConfirmationRequired(decision.reason)
    return decision


class ProgressRecorder:
    """Append-only NDJSON progress writer for long-running agent tools."""

    def __init__(self, path: Path | str, *, run_id: str) -> None:
        self.path = Path(path).expanduser()
        self.run_id = run_id

    def emit(
        self,
        event: str,
        *,
        status: str = "running",
        message: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> ProgressEvent:
        record = ProgressEvent(
            schema=SCHEMA,
            event=event,
            run_id=self.run_id,
            status=status,
            message=redact_text(message),
            created_at=_utc_now(),
            metadata=redact_mapping(metadata or {}),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(record), sort_keys=True) + "\n")
        return record


def load_progress_events(path: Path | str) -> list[dict[str, Any]]:
    """Load progress events previously written by :class:`ProgressRecorder`."""
    progress_path = Path(path).expanduser()
    if not progress_path.exists():
        return []
    return [
        json.loads(line)
        for line in progress_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
