"""Pending ORCHESTRATE actions queued before the page renders."""

from __future__ import annotations

from typing import MutableMapping, Optional


PENDING_INSTALL_ACTION_KEY = "_orchestrate_pending_install_action"
PENDING_EXECUTE_ACTION_KEY = "_orchestrate_pending_action"


def queue_pending_install_action(session_state: MutableMapping[str, object]) -> None:
    """Request that ORCHESTRATE runs INSTALL on the next page render."""
    session_state[PENDING_INSTALL_ACTION_KEY] = "install"


def consume_pending_install_action(session_state: MutableMapping[str, object]) -> bool:
    """Return whether a queued INSTALL request was present."""
    return session_state.pop(PENDING_INSTALL_ACTION_KEY, None) == "install"


def queue_pending_execute_action(session_state: MutableMapping[str, object], action: str) -> None:
    """Request that ORCHESTRATE runs an execute-section action on the next render."""
    session_state[PENDING_EXECUTE_ACTION_KEY] = action


def consume_pending_execute_action(session_state: MutableMapping[str, object]) -> Optional[str]:
    """Return and clear the queued execute-section action, if any."""
    value = session_state.pop(PENDING_EXECUTE_ACTION_KEY, None)
    return str(value) if value is not None else None
