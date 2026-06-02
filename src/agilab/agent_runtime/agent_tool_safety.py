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
from typing import Any, Callable, Mapping

from agilab.security.secret_uri import redact_mapping, redact_text


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
_PERMISSION_LEVELS = ("readonly", "safe", "standard", "operator")
_PERMISSION_RANK = {level: index for index, level in enumerate(_PERMISSION_LEVELS)}
_READONLY_WORDS = frozenset({"check", "find", "inspect", "list", "read", "search", "show", "status", "validate", "verify"})
_STANDARD_WORDS = frozenset({"build", "execute", "install", "run", "smoke", "sync", "test"})
_SAFE_WRITE_WORDS = frozenset({"add", "create", "edit", "export", "generate", "patch", "record", "update", "write"})


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
class ToolPermissionDecision:
    """Tiered permission decision for an agent tool invocation."""

    action: str
    allowed: bool
    tier: str
    level: str
    reason: str
    confirmation_token: str | None = None


@dataclass(frozen=True)
class ToolHookContext:
    """Immutable context passed to AGILAB agent tool hooks."""

    action: str
    arguments: dict[str, Any]
    metadata: dict[str, Any]
    run_id: str = ""


@dataclass(frozen=True)
class ToolHookResult:
    """Result passed between before/after AGILAB tool hooks."""

    output: str
    status: str = "pass"
    metadata: dict[str, Any] | None = None
    is_error: bool = False


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


def normalize_permission_level(level: str | None) -> str:
    """Normalize a user-facing permission level."""

    raw = str(level or "safe").strip().lower().replace("_", "-")
    if raw == "yolo":
        return "operator"
    return raw if raw in _PERMISSION_RANK else "safe"


def classify_tool_permission(action: str, metadata: Mapping[str, Any] | None = None) -> str:
    """Classify an agent tool action into a permission tier.

    Tiers intentionally stay conservative:

    - ``readonly``: inspection-only actions
    - ``safe``: local write/export actions
    - ``standard``: execution/build/test actions
    - ``operator``: destructive or explicitly operator-gated actions
    """

    meta = metadata or {}
    explicit = str(meta.get("permission_tier") or meta.get("permission_level") or "").strip().lower()
    explicit = "operator" if explicit == "yolo" else explicit
    if explicit in _PERMISSION_RANK:
        return explicit
    if classify_tool_action(action, meta) == "destructive":
        return "operator"
    terms = _action_terms(action)
    if terms & _STANDARD_WORDS:
        return "standard"
    if terms & _SAFE_WRITE_WORDS:
        return "safe"
    if terms & _READONLY_WORDS:
        return "readonly"
    return "safe"


def evaluate_tool_permission(
    action: str,
    arguments: Mapping[str, Any] | None = None,
    *,
    level: str | None = None,
    confirmation: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ToolPermissionDecision:
    """Evaluate an invocation against a tiered permission level."""

    normalized_level = normalize_permission_level(level)
    tier = classify_tool_permission(action, metadata)
    if _PERMISSION_RANK[tier] <= _PERMISSION_RANK[normalized_level]:
        return ToolPermissionDecision(
            action=action,
            allowed=True,
            tier=tier,
            level=normalized_level,
            reason=f"{tier} action allowed by {normalized_level} permission level",
        )
    token = confirmation_token(action, arguments)
    if tier == "operator" and confirmation == token:
        return ToolPermissionDecision(
            action=action,
            allowed=True,
            tier=tier,
            level=normalized_level,
            reason="operator action confirmed by explicit token",
            confirmation_token=token,
        )
    return ToolPermissionDecision(
        action=action,
        allowed=False,
        tier=tier,
        level=normalized_level,
        reason=f"{tier} action exceeds {normalized_level} permission level",
        confirmation_token=token if tier == "operator" else None,
    )


BeforeToolHook = Callable[[ToolHookContext], ToolHookResult | None]
AfterToolHook = Callable[[ToolHookContext, ToolHookResult], ToolHookResult | None]
ToolRunner = Callable[[ToolHookContext], ToolHookResult]


class ToolHookSet:
    """Ordered before/after hooks for AGILAB agent-exposed tools."""

    def __init__(self) -> None:
        self._before: list[BeforeToolHook] = []
        self._after: list[AfterToolHook] = []

    def before_tool(self, hook: BeforeToolHook) -> BeforeToolHook:
        self._before.append(hook)
        return hook

    def after_tool(self, hook: AfterToolHook) -> AfterToolHook:
        self._after.append(hook)
        return hook

    def run_before(self, context: ToolHookContext) -> ToolHookResult | None:
        for hook in self._before:
            result = hook(context)
            if result is not None:
                return result
        return None

    def run_after(self, context: ToolHookContext, result: ToolHookResult) -> ToolHookResult:
        current = result
        for hook in self._after:
            replacement = hook(context, current)
            if replacement is not None:
                current = replacement
        return current

    def execute(self, context: ToolHookContext, runner: ToolRunner) -> ToolHookResult:
        skipped = self.run_before(context)
        result = skipped if skipped is not None else runner(context)
        return self.run_after(context, result)


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
