"""Reusable action execution primitives for Streamlit workflow pages."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

ActionStatus = Literal["success", "warning", "error", "info"]


@dataclass(frozen=True)
class ActionResult:
    """Structured outcome for a user-triggered workflow action."""

    status: ActionStatus
    title: str
    detail: str | None = None
    next_action: str | None = None
    data: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def success(
        cls,
        title: str,
        *,
        detail: str | None = None,
        next_action: str | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> "ActionResult":
        return cls("success", title, detail=detail, next_action=next_action, data=data or {})

    @classmethod
    def warning(
        cls,
        title: str,
        *,
        detail: str | None = None,
        next_action: str | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> "ActionResult":
        return cls("warning", title, detail=detail, next_action=next_action, data=data or {})

    @classmethod
    def error(
        cls,
        title: str,
        *,
        detail: str | None = None,
        next_action: str | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> "ActionResult":
        return cls("error", title, detail=detail, next_action=next_action, data=data or {})

    @classmethod
    def info(
        cls,
        title: str,
        *,
        detail: str | None = None,
        next_action: str | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> "ActionResult":
        return cls("info", title, detail=detail, next_action=next_action, data=data or {})


@dataclass(frozen=True)
class ActionSpec:
    """User-facing metadata for a long-running page action."""

    name: str
    start_message: str
    failure_title: str | None = None
    failure_next_action: str | None = None


def render_action_result(streamlit: Any, result: ActionResult) -> None:
    """Render a structured action result through a Streamlit-compatible object."""

    renderer = getattr(streamlit, result.status)
    renderer(result.title)
    if result.detail:
        streamlit.info(result.detail)
    if result.next_action:
        streamlit.info(f"Next: {result.next_action}")


def run_streamlit_action(
    streamlit: Any,
    spec: ActionSpec,
    action: Callable[[], ActionResult],
    *,
    on_success: Callable[[ActionResult], Any] | None = None,
) -> ActionResult:
    """Run a Streamlit page action with consistent progress and result handling."""

    try:
        with streamlit.spinner(spec.start_message):
            result = action()
    except Exception as exc:
        result = ActionResult.error(
            spec.failure_title or f"{spec.name} failed.",
            detail=str(exc),
            next_action=spec.failure_next_action,
        )

    render_action_result(streamlit, result)
    if result.status == "success" and on_success is not None:
        on_success(result)
    return result
