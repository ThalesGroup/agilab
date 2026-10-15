"""Reusable action execution primitives for native Python workflow pages."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from agilab.diagnostics.runtime_failure_diagnostics import classify_runtime_failure

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
    action: Callable[[], ActionResult] | None = None,
    *,
    on_success: Callable[[ActionResult], Any] | None = None,
    action_with_progress: Callable[[Callable[[str], None]], ActionResult] | None = None,
) -> ActionResult:
    """Run an action, optionally reporting real phases through a status block.

    Existing zero-argument actions retain their spinner. A phased action receives
    a synchronous reporter; its history remains available after completion.
    """

    if (action is None) == (action_with_progress is None):
        raise ValueError("Provide exactly one action or action_with_progress callable.")

    progress = None
    try:
        if action_with_progress is not None:
            with streamlit.status(spec.start_message, expanded=True) as progress:
                def report(phase: str) -> None:
                    progress.update(label=phase)
                    progress.write(phase)

                result = action_with_progress(report)
        else:
            assert action is not None
            with streamlit.spinner(spec.start_message):
                result = action()
    except Exception as exc:
        diagnostic = classify_runtime_failure(str(exc), phase=spec.name)
        result = ActionResult.error(
            spec.failure_title or (diagnostic.title if diagnostic else f"{spec.name} failed."),
            detail=diagnostic.detail if diagnostic else str(exc),
            next_action=spec.failure_next_action or (diagnostic.next_action if diagnostic else None),
            data={"failure_category": diagnostic.category} if diagnostic else {},
        )

    if progress is not None:
        progress.update(
            label=spec.name,
            state="error" if result.status == "error" else "complete",
            expanded=result.status == "error",
        )
    render_action_result(streamlit, result)
    if result.status == "success" and on_success is not None:
        on_success(result)
    return result
