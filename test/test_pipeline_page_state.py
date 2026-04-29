from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any


def _load_module(module_name: str, relative_path: str):
    module_path = Path(relative_path)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


pipeline_page_state = _load_module("agilab.pipeline_page_state", "src/agilab/pipeline_page_state.py")


def _deps(**overrides: Any):
    defaults = dict(
        is_displayable_step=lambda entry: bool(entry.get("Q") or entry.get("C")),
        is_runnable_step=lambda entry: bool(str(entry.get("C") or "").strip()),
        step_summary=lambda entry: str(entry.get("Q") or entry.get("C") or ""),
        step_label=lambda idx, entry: f"Step {idx + 1}: {entry.get('Q') or 'code'}",
        find_legacy_agi_run_steps=lambda _steps, _sequence: [],
        inspect_pipeline_run_lock=None,
    )
    defaults.update(overrides)
    return pipeline_page_state.PipelinePageStateDeps(**defaults)


def test_pipeline_page_state_keeps_visible_steps_when_logs_are_missing_or_cleared(tmp_path):
    steps = [{"Q": "generate trajectories", "C": "print('run')"}]
    session_state: dict[str, Any] = {}

    state_without_logs = pipeline_page_state.build_pipeline_page_state(
        index_page="demo",
        steps_file=tmp_path / "lab_steps.toml",
        steps=steps,
        sequence=[0],
        session_state=session_state,
        selected_lab=tmp_path / "mission_lab",
        deps=_deps(),
    )

    session_state["demo__run_logs"] = ["old log"]
    result = pipeline_page_state.clear_pipeline_run_logs(session_state, "demo")
    state_after_clear = pipeline_page_state.build_pipeline_page_state(
        index_page="demo",
        steps_file=tmp_path / "lab_steps.toml",
        steps=steps,
        sequence=[0],
        session_state=session_state,
        deps=_deps(),
    )

    assert result.status is pipeline_page_state.PipelineCommandStatus.SUCCESS
    assert state_without_logs.selected_lab == "mission_lab"
    assert state_without_logs.visible_steps[0].label == "Step 1: generate trajectories"
    assert state_after_clear.visible_steps == state_without_logs.visible_steps
    assert state_after_clear.run_logs == ()
    assert state_after_clear.can_run is True
    assert pipeline_page_state.PipelineAction.RUN_PIPELINE in state_after_clear.available_actions
    assert pipeline_page_state.PipelineAction.CLEAR_LOGS in state_after_clear.available_actions
    assert state_after_clear.blocked_actions[pipeline_page_state.PipelineAction.FORCE_RUN] == (
        "No pipeline lock is present."
    )


def test_pipeline_page_state_derives_blocked_actions_for_empty_and_stale_labs(tmp_path):
    empty_state = pipeline_page_state.build_pipeline_page_state(
        index_page="demo",
        steps_file=tmp_path / "empty_lab" / "lab_steps.toml",
        steps=[],
        sequence=[],
        session_state={},
        deps=_deps(),
    )
    assert empty_state.selected_lab == "empty_lab"
    assert pipeline_page_state.PipelineAction.RUN_PIPELINE not in empty_state.available_actions
    assert "No visible pipeline steps" in empty_state.blocked_actions[pipeline_page_state.PipelineAction.RUN_PIPELINE]

    stale_state = pipeline_page_state.build_pipeline_page_state(
        index_page="demo",
        steps_file=tmp_path / "lab_steps.toml",
        steps=[{"Q": "legacy run", "C": "await AGI.run(app_env, mode=0)"}],
        sequence=[0],
        session_state={},
        deps=_deps(
            find_legacy_agi_run_steps=lambda _steps, _sequence: [
                {"step": 1, "line": 4, "summary": "legacy run"}
            ]
        ),
    )
    assert pipeline_page_state.PipelineAction.ADD_STEP in stale_state.available_actions
    assert pipeline_page_state.PipelineAction.RUN_PIPELINE not in stale_state.available_actions
    assert pipeline_page_state.PipelineAction.FORCE_RUN not in stale_state.available_actions
    assert "stale AGI.run snippets" in stale_state.blocked_actions[pipeline_page_state.PipelineAction.RUN_PIPELINE]


def test_start_pipeline_run_command_refuses_blocked_actions_without_side_effects(tmp_path):
    session_state: dict[str, Any] = {}
    state = pipeline_page_state.build_pipeline_page_state(
        index_page="demo",
        steps_file=tmp_path / "lab_steps.toml",
        steps=[],
        sequence=[],
        session_state=session_state,
        deps=_deps(),
    )
    calls: list[str] = []

    result = pipeline_page_state.start_pipeline_run_command(
        page_state=state,
        requested_action=pipeline_page_state.PipelineAction.RUN_PIPELINE,
        session_state=session_state,
        env=object(),
        prepare_run_log_file=lambda *_args, **_kwargs: calls.append("prepare"),
        get_run_placeholder=lambda *_args, **_kwargs: calls.append("placeholder"),
        push_run_log=lambda *_args, **_kwargs: calls.append("push"),
        force_confirm_key="demo_confirm_force_run",
    )

    assert result.status is pipeline_page_state.PipelineCommandStatus.REFUSED
    assert "No visible pipeline steps" in result.message
    assert session_state == {}
    assert calls == []


def test_start_pipeline_run_command_sets_running_status_and_logs_path(tmp_path):
    session_state: dict[str, Any] = {"demo_confirm_force_run": True}
    pushed: list[tuple[str, str, object]] = []
    placeholder = object()
    state = pipeline_page_state.build_pipeline_page_state(
        index_page="demo",
        steps_file=tmp_path / "lab_steps.toml",
        steps=[{"Q": "run", "C": "print('run')"}],
        sequence=[0],
        session_state=session_state,
        deps=_deps(),
    )

    result = pipeline_page_state.start_pipeline_run_command(
        page_state=state,
        requested_action=pipeline_page_state.PipelineAction.RUN_PIPELINE,
        session_state=session_state,
        env=object(),
        prepare_run_log_file=lambda *_args, **_kwargs: (tmp_path / "pipeline.log", None),
        get_run_placeholder=lambda *_args, **_kwargs: placeholder,
        push_run_log=lambda index_page, message, log_placeholder: pushed.append(
            (index_page, message, log_placeholder)
        ),
        force_confirm_key="demo_confirm_force_run",
    )

    assert result.status is pipeline_page_state.PipelineCommandStatus.SUCCESS
    assert result.details["force_lock_clear"] is False
    assert result.details["log_file_path"] == str(tmp_path / "pipeline.log")
    assert result.details["log_placeholder"] is placeholder
    assert session_state["demo__last_run_status"] == "running"
    assert "demo_confirm_force_run" not in session_state
    assert pushed == [
        (
            "demo",
            f"Run pipeline started... logs will be saved to {tmp_path / 'pipeline.log'}",
            placeholder,
        )
    ]


def test_start_pipeline_run_command_force_run_continues_without_log_file(tmp_path):
    session_state: dict[str, Any] = {}
    pushed: list[str] = []
    state = pipeline_page_state.build_pipeline_page_state(
        index_page="demo",
        steps_file=tmp_path / "lab_steps.toml",
        steps=[{"Q": "run", "C": "print('run')"}],
        sequence=[0],
        session_state=session_state,
        env=object(),
        deps=_deps(
            inspect_pipeline_run_lock=lambda _env: {
                "owner_text": "pid 123",
                "is_stale": True,
            }
        ),
    )

    result = pipeline_page_state.start_pipeline_run_command(
        page_state=state,
        requested_action=pipeline_page_state.PipelineAction.FORCE_RUN,
        session_state=session_state,
        env=object(),
        prepare_run_log_file=lambda *_args, **_kwargs: (None, "no log"),
        get_run_placeholder=lambda *_args, **_kwargs: None,
        push_run_log=lambda _index_page, message, _placeholder: pushed.append(message),
    )

    assert result.status is pipeline_page_state.PipelineCommandStatus.SUCCESS
    assert result.details["force_lock_clear"] is True
    assert result.details["log_error"] == "no log"
    assert pushed == ["Run pipeline started... (unable to prepare log file: no log)"]


def test_start_pipeline_run_command_marks_failed_when_logging_raises(tmp_path):
    session_state: dict[str, Any] = {}
    state = pipeline_page_state.build_pipeline_page_state(
        index_page="demo",
        steps_file=tmp_path / "lab_steps.toml",
        steps=[{"Q": "run", "C": "print('run')"}],
        sequence=[0],
        session_state=session_state,
        deps=_deps(),
    )

    def _raise_push(*_args, **_kwargs):
        raise RuntimeError("push blocked")

    result = pipeline_page_state.start_pipeline_run_command(
        page_state=state,
        requested_action=pipeline_page_state.PipelineAction.RUN_PIPELINE,
        session_state=session_state,
        env=object(),
        prepare_run_log_file=lambda *_args, **_kwargs: (tmp_path / "pipeline.log", None),
        get_run_placeholder=lambda *_args, **_kwargs: None,
        push_run_log=_raise_push,
    )

    assert result.status is pipeline_page_state.PipelineCommandStatus.FAILED
    assert "push blocked" in result.message
    assert session_state["demo__last_run_status"] == "failed"


def test_finish_pipeline_run_command_records_success_and_failure_status() -> None:
    session_state: dict[str, Any] = {}

    success = pipeline_page_state.finish_pipeline_run_command(
        session_state=session_state,
        index_page="demo",
        succeeded=True,
        message="finished",
    )
    failure = pipeline_page_state.finish_pipeline_run_command(
        session_state=session_state,
        index_page="demo",
        succeeded=False,
    )

    assert success.status is pipeline_page_state.PipelineCommandStatus.SUCCESS
    assert success.message == "finished"
    assert success.details == {"index_page": "demo", "status": "complete"}
    assert failure.status is pipeline_page_state.PipelineCommandStatus.FAILED
    assert failure.message == "Pipeline run failed. Inspect Run logs."
    assert failure.details == {"index_page": "demo", "status": "failed"}
    assert session_state["demo__last_run_status"] == "failed"


def test_finish_pipeline_run_command_reports_session_state_write_errors() -> None:
    class BrokenSessionState(dict):
        def __setitem__(self, key, value):
            raise RuntimeError("state locked")

    result = pipeline_page_state.finish_pipeline_run_command(
        session_state=BrokenSessionState(),
        index_page="demo",
        succeeded=True,
    )

    assert result.status is pipeline_page_state.PipelineCommandStatus.FAILED
    assert "state locked" in result.message
    assert result.details == {
        "index_page": "demo",
        "status": "complete",
        "error": "state locked",
    }


def test_pipeline_page_state_refuses_stale_legacy_snippets_before_runtime(tmp_path):
    stale_ref = {"step": 1, "line": 4, "summary": "legacy run", "project": "flight_project"}

    state = pipeline_page_state.build_pipeline_page_state(
        index_page="demo",
        steps_file=tmp_path / "lab_steps.toml",
        steps=[{"Q": "legacy run", "C": "await AGI.run(app_env, mode=0)"}],
        sequence=[0],
        session_state={},
        deps=_deps(find_legacy_agi_run_steps=lambda _steps, _sequence: [stale_ref]),
    )

    assert state.status is pipeline_page_state.PipelineWorkflowStatus.STALE
    assert state.can_run is False
    assert state.can_force_run is False
    assert state.stale_step_refs == (stale_ref,)
    assert "stale AGI.run snippets" in state.run_disabled_reason
    assert "step 1, line 4" in state.run_disabled_reason


def test_pipeline_page_state_active_lock_disables_normal_run_but_allows_force_recovery(tmp_path):
    state = pipeline_page_state.build_pipeline_page_state(
        index_page="demo",
        steps_file=tmp_path / "lab_steps.toml",
        steps=[{"Q": "run", "C": "print('run')"}],
        sequence=[0],
        session_state={},
        env=object(),
        deps=_deps(
            inspect_pipeline_run_lock=lambda _env: {
                "owner_text": "pid 123",
                "is_stale": False,
            }
        ),
    )

    assert state.status is pipeline_page_state.PipelineWorkflowStatus.RUNNING
    assert state.can_run is False
    assert state.can_force_run is True
    assert "pid 123" in state.run_disabled_reason


def test_pipeline_page_state_stale_lock_is_explicit_and_forceable(tmp_path):
    state = pipeline_page_state.build_pipeline_page_state(
        index_page="demo",
        steps_file=tmp_path / "lab_steps.toml",
        steps=[{"Q": "run", "C": "print('run')"}],
        sequence=[0],
        session_state={},
        env=object(),
        deps=_deps(
            inspect_pipeline_run_lock=lambda _env: {
                "owner_text": "pid 123",
                "is_stale": True,
                "stale_reason": "heartbeat expired",
            }
        ),
    )

    assert state.status is pipeline_page_state.PipelineWorkflowStatus.STALE
    assert state.can_run is True
    assert state.can_force_run is True
    assert state.lock_state["stale_reason"] == "heartbeat expired"


def test_clear_pipeline_run_logs_returns_noop_and_failure_results():
    empty_state: dict[str, Any] = {}
    noop = pipeline_page_state.clear_pipeline_run_logs(empty_state, "demo")
    assert noop.status is pipeline_page_state.PipelineCommandStatus.NO_OP
    assert empty_state["demo__run_logs"] == []

    class BrokenState(dict):
        def __setitem__(self, key, value):
            raise RuntimeError("blocked")

    failed = pipeline_page_state.clear_pipeline_run_logs(
        BrokenState({"demo__run_logs": ["line"]}),
        "demo",
    )
    assert failed.status is pipeline_page_state.PipelineCommandStatus.FAILED
    assert "blocked" in failed.message
