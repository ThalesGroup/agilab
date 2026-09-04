"""Typed lifecycle state for one dependency-aware pipeline execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


PipelineRunStatus = Literal["running", "completed", "failed"]


@dataclass(slots=True)
class PipelineRunState:
    """Own mutable counters and manifest state independently of Streamlit rendering."""

    run_id: str
    started_at: str
    started_monotonic: float
    stage_records: list[dict[str, Any]] = field(default_factory=list)
    executed: int = 0
    skipped: int = 0
    status: PipelineRunStatus = "running"
    error: str = ""

    def record_executed(self, count: int = 1) -> None:
        if count < 0:
            raise ValueError("executed stage count cannot be negative")
        self.executed += count

    def record_skipped(self, count: int = 1) -> None:
        if count < 0:
            raise ValueError("skipped stage count cannot be negative")
        self.skipped += count

    def complete(self) -> None:
        self.status = "completed"
        self.error = ""

    def fail(self, error: str, *, finished_at: str) -> None:
        """Fail the run and close the most recent in-flight stage record."""

        self.status = "failed"
        self.error = error
        for stage_record in reversed(self.stage_records):
            if stage_record.get("status") == "running":
                stage_record["status"] = "failed"
                stage_record["finished_at"] = finished_at
                stage_record["error"] = error
                break

    def duration_seconds(self, finished_monotonic: float) -> float:
        return max(finished_monotonic - self.started_monotonic, 0.0)
