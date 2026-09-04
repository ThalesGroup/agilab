from __future__ import annotations

import pytest

from agilab.pipeline.pipeline_run_state import PipelineRunState


def test_pipeline_run_state_tracks_counts_completion_and_duration() -> None:
    state = PipelineRunState("run-1", "2026-09-04T12:00:00Z", 10.0)

    state.record_executed(2)
    state.record_skipped()
    state.complete()

    assert state.executed == 2
    assert state.skipped == 1
    assert state.status == "completed"
    assert state.error == ""
    assert state.duration_seconds(13.5) == 3.5
    assert state.duration_seconds(9.0) == 0.0


def test_pipeline_run_state_failure_closes_latest_running_record() -> None:
    state = PipelineRunState(
        "run-2",
        "2026-09-04T12:00:00Z",
        10.0,
        stage_records=[
            {"stage_index": 1, "status": "running", "error": ""},
            {"stage_index": 2, "status": "completed", "error": ""},
            {"stage_index": 3, "status": "running", "error": ""},
        ],
    )

    state.fail("stage failed", finished_at="2026-09-04T12:01:00Z")

    assert state.status == "failed"
    assert state.error == "stage failed"
    assert state.stage_records[0]["status"] == "running"
    assert state.stage_records[2] == {
        "stage_index": 3,
        "status": "failed",
        "error": "stage failed",
        "finished_at": "2026-09-04T12:01:00Z",
    }


@pytest.mark.parametrize("method_name", ["record_executed", "record_skipped"])
def test_pipeline_run_state_rejects_negative_counter_updates(method_name: str) -> None:
    state = PipelineRunState("run-3", "2026-09-04T12:00:00Z", 10.0)

    with pytest.raises(ValueError, match="cannot be negative"):
        getattr(state, method_name)(-1)
