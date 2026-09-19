"""Typed workflow execution and cleanup, independent of Streamlit and workers.

The adapter owns effects. This owner guarantees terminal publication, view
restoration and lock release are attempted, including cancellation and failures
while publishing evidence. The original failure remains the primary exception.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from agilab.pipeline.pipeline_run_state import PipelineRunState, PipelineRunStatus


@dataclass(frozen=True)
class PipelineExecutionPlan:
    stages: Sequence[Mapping[str, Any]]
    sequence: Sequence[int]
    waves: Sequence[Sequence[int]]
    profile: str
    max_workers: int
    stage_ids: Mapping[int, str]
    stage_deps: Mapping[int, Sequence[str]]


@dataclass(frozen=True)
class PipelineExecutionResult:
    run_id: str
    status: PipelineRunStatus
    executed: int
    skipped: int
    manifest_path: Path | None


class PipelineExecutor(Protocol):
    def execute(self, run_state: PipelineRunState) -> None: ...
    def record_failure(self, run_state: PipelineRunState) -> None: ...


class PipelineEvidencePublisher(Protocol):
    def publish(self, run_state: PipelineRunState) -> Path | None: ...


class PipelineViewRestorer(Protocol):
    def restore(self, run_state: PipelineRunState) -> None: ...


class PipelineLockReleaser(Protocol):
    def release(self, run_state: PipelineRunState) -> None: ...


class PipelineExecutionEffects(
    PipelineExecutor,
    PipelineEvidencePublisher,
    PipelineViewRestorer,
    PipelineLockReleaser,
    Protocol,
):
    """Capabilities supplied by the UI/runtime adapter."""


def execute_pipeline_lifecycle(
    state: PipelineRunState,
    effects: PipelineExecutionEffects,
    *,
    describe_error: Callable[[BaseException], str],
    timestamp: Callable[[], str],
) -> PipelineExecutionResult:
    """Execute once, finalize every owned resource, and preserve causal errors."""
    failure: BaseException | None = None
    manifest_path = None

    def error_text(exc: BaseException) -> str:
        try:
            return describe_error(exc)
        except BaseException:
            # Diagnostics must not defeat cleanup or reveal unredacted input.
            return type(exc).__name__

    try:
        effects.execute(state)
        state.complete()
    except BaseException as exc:
        failure = exc
        try:
            state.fail(error_text(exc), finished_at=timestamp())
            effects.record_failure(state)
        except BaseException as secondary:
            failure.add_note(
                f"Recording pending stages failed: {error_text(secondary)}"
            )
    finally:
        # Finalizers are independent: publication and view failures must not
        # leave a stale workflow lock. Keep cancellation as the primary error.
        for label, finalize in (
            ("Publishing terminal evidence", effects.publish),
            ("Restoring workflow view", effects.restore),
            ("Releasing workflow lock", effects.release),
        ):
            try:
                value = finalize(state)
                if label == "Publishing terminal evidence":
                    manifest_path = value
            except BaseException as exc:
                if failure is None:
                    failure = exc
                else:
                    failure.add_note(f"{label} failed: {error_text(exc)}")
    if failure is not None:
        raise failure
    return PipelineExecutionResult(
        state.run_id,
        state.status,
        state.executed,
        state.skipped,
        manifest_path,
    )
