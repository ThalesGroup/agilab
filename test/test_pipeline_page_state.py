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
        is_displayable_stage=lambda entry: bool(entry.get("Q") or entry.get("C")),
        is_runnable_stage=lambda entry: bool(str(entry.get("C") or "").strip()),
        stage_summary=lambda entry: str(entry.get("Q") or entry.get("C") or ""),
        stage_label=lambda idx, entry: f"Stage {idx + 1}: {entry.get('Q') or 'code'}",
        find_legacy_agi_run_stages=lambda _stages, _sequence: [],
        inspect_pipeline_run_lock=None,
    )
    defaults.update(overrides)
    return pipeline_page_state.PipelinePageStateDeps(**defaults)


def test_pipeline_page_state_keeps_visible_stages_when_logs_are_missing_or_cleared(tmp_path):
    stages = [{"Q": "generate trajectories", "C": "print('run')"}]
    session_state: dict[str, Any] = {}

    state_without_logs = pipeline_page_state.build_pipeline_page_state(
        index_page="demo",
        stages_file=tmp_path / "lab_stages.toml",
        stages=stages,
        sequence=[0],
        session_state=session_state,
        selected_lab=tmp_path / "mission_lab",
        deps=_deps(),
    )

    session_state["demo__run_logs"] = ["old log"]
    result = pipeline_page_state.clear_pipeline_run_logs(session_state, "demo")
    state_after_clear = pipeline_page_state.build_pipeline_page_state(
        index_page="demo",
        stages_file=tmp_path / "lab_stages.toml",
        stages=stages,
        sequence=[0],
        session_state=session_state,
        deps=_deps(),
    )

    assert result.status is pipeline_page_state.PipelineCommandStatus.SUCCESS
    assert state_without_logs.selected_lab == "mission_lab"
    assert state_without_logs.visible_stages[0].label == "Stage 1: generate trajectories"
    assert state_after_clear.visible_stages == state_without_logs.visible_stages
    assert state_after_clear.run_logs == ()
    assert state_after_clear.can_run is True
    assert pipeline_page_state.PipelineAction.DELETE_STAGE in state_after_clear.available_actions
    assert pipeline_page_state.PipelineAction.DELETE_ALL_STAGES in state_after_clear.available_actions
    assert pipeline_page_state.PipelineAction.RUN_PIPELINE in state_after_clear.available_actions
    assert pipeline_page_state.PipelineAction.CLEAR_LOGS in state_after_clear.available_actions
    assert state_after_clear.blocked_actions[pipeline_page_state.PipelineAction.FORCE_RUN] == (
        "No workflow lock is present."
    )


def test_pipeline_page_state_derives_blocked_actions_for_empty_and_stale_labs(tmp_path):
    empty_state = pipeline_page_state.build_pipeline_page_state(
        index_page="demo",
        stages_file=tmp_path / "empty_lab" / "lab_stages.toml",
        stages=[],
        sequence=[],
        session_state={},
        deps=_deps(),
    )
    assert empty_state.selected_lab == "empty_lab"
    assert pipeline_page_state.PipelineAction.RUN_PIPELINE not in empty_state.available_actions
    assert pipeline_page_state.PipelineAction.DELETE_STAGE not in empty_state.available_actions
    assert pipeline_page_state.PipelineAction.DELETE_ALL_STAGES not in empty_state.available_actions
    assert "No visible workflow stages" in empty_state.blocked_actions[pipeline_page_state.PipelineAction.RUN_PIPELINE]
    assert "No workflow stage" in empty_state.blocked_actions[pipeline_page_state.PipelineAction.DELETE_STAGE]

    stale_state = pipeline_page_state.build_pipeline_page_state(
        index_page="demo",
        stages_file=tmp_path / "lab_stages.toml",
        stages=[{"Q": "legacy run", "C": "await AGI.run(app_env, mode=0)"}],
        sequence=[0],
        session_state={},
        deps=_deps(
            find_legacy_agi_run_stages=lambda _stages, _sequence: [
                {"stage": 1, "line": 4, "summary": "legacy run"}
            ]
        ),
    )
    assert pipeline_page_state.PipelineAction.ADD_STAGE in stale_state.available_actions
    assert pipeline_page_state.PipelineAction.RUN_PIPELINE not in stale_state.available_actions
    assert pipeline_page_state.PipelineAction.FORCE_RUN not in stale_state.available_actions
    assert "stale AGI.run snippets" in stale_state.blocked_actions[pipeline_page_state.PipelineAction.RUN_PIPELINE]


def test_pipeline_page_state_exposes_undo_action_when_delete_snapshot_exists(tmp_path):
    session_state: dict[str, Any] = {"demo__undo_delete_snapshot": {"stages": [{"Q": "old"}]}}

    state = pipeline_page_state.build_pipeline_page_state(
        index_page="demo",
        stages_file=tmp_path / "lab_stages.toml",
        stages=[{"Q": "run", "C": "print('run')"}],
        sequence=[0],
        session_state=session_state,
        deps=_deps(),
    )

    assert pipeline_page_state.PipelineAction.UNDO_DELETE_STAGES in state.available_actions


def test_start_pipeline_run_command_refuses_blocked_actions_without_side_effects(tmp_path):
    session_state: dict[str, Any] = {}
    state = pipeline_page_state.build_pipeline_page_state(
        index_page="demo",
        stages_file=tmp_path / "lab_stages.toml",
        stages=[],
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
    assert "No visible workflow stages" in result.message
    assert session_state == {}
    assert calls == []


def test_start_pipeline_run_command_sets_running_status_and_logs_path(tmp_path):
    session_state: dict[str, Any] = {"demo_confirm_force_run": True}
    pushed: list[tuple[str, str, object]] = []
    placeholder = object()
    state = pipeline_page_state.build_pipeline_page_state(
        index_page="demo",
        stages_file=tmp_path / "lab_stages.toml",
        stages=[{"Q": "run", "C": "print('run')"}],
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
            f"Run workflow started... logs will be saved to {tmp_path / 'pipeline.log'}",
            placeholder,
        )
    ]


def test_start_pipeline_run_command_force_run_continues_without_log_file(tmp_path):
    session_state: dict[str, Any] = {}
    pushed: list[str] = []
    state = pipeline_page_state.build_pipeline_page_state(
        index_page="demo",
        stages_file=tmp_path / "lab_stages.toml",
        stages=[{"Q": "run", "C": "print('run')"}],
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
    assert pushed == ["Run workflow started... (unable to prepare log file: no log)"]


def test_start_pipeline_run_command_marks_failed_when_logging_raises(tmp_path):
    session_state: dict[str, Any] = {}
    state = pipeline_page_state.build_pipeline_page_state(
        index_page="demo",
        stages_file=tmp_path / "lab_stages.toml",
        stages=[{"Q": "run", "C": "print('run')"}],
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
    assert failure.message == "Workflow run failed. Inspect Run logs."
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
    stale_ref = {"stage": 1, "line": 4, "summary": "legacy run", "project": "flight_telemetry_project"}

    state = pipeline_page_state.build_pipeline_page_state(
        index_page="demo",
        stages_file=tmp_path / "lab_stages.toml",
        stages=[{"Q": "legacy run", "C": "await AGI.run(app_env, mode=0)"}],
        sequence=[0],
        session_state={},
        deps=_deps(find_legacy_agi_run_stages=lambda _stages, _sequence: [stale_ref]),
    )

    assert state.status is pipeline_page_state.PipelineWorkflowStatus.STALE
    assert state.can_run is False
    assert state.can_force_run is False
    assert state.stale_stage_refs == (stale_ref,)
    assert "stale AGI.run snippets" in state.run_disabled_reason
    assert "stage 1, line 4" in state.run_disabled_reason


def test_pipeline_page_state_active_lock_disables_normal_run_but_allows_force_recovery(tmp_path):
    state = pipeline_page_state.build_pipeline_page_state(
        index_page="demo",
        stages_file=tmp_path / "lab_stages.toml",
        stages=[{"Q": "run", "C": "print('run')"}],
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
        stages_file=tmp_path / "lab_stages.toml",
        stages=[{"Q": "run", "C": "print('run')"}],
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


def test_delete_pipeline_stage_command_preserves_snapshot_and_logs(tmp_path):
    session_state: dict[str, Any] = {"demo__run_logs": ["keep me"]}
    selected_map: dict[int, str] = {0: "runtime-a", 1: "runtime-b"}
    removed: list[tuple[Any, ...]] = []
    stages = [
        {"Q": "alpha", "C": "print('a')"},
        {"Q": "beta", "C": "print('b')"},
    ]

    result = pipeline_page_state.delete_pipeline_stage_command(
        session_state=session_state,
        index_page="demo",
        stage_index=0,
        lab_dir=tmp_path / "lab",
        stages_file=tmp_path / "lab_stages.toml",
        persisted_stages=stages,
        selected_map=selected_map,
        capture_pipeline_snapshot=lambda index_page, captured_stages: {
            "index_page": index_page,
            "stages": list(captured_stages),
        },
        remove_stage=lambda *args: removed.append(args),
        timestamp="2026-04-29T08:00:00",
    )

    assert result.status is pipeline_page_state.PipelineCommandStatus.SUCCESS
    assert selected_map == {1: "runtime-b"}
    assert removed == [(tmp_path / "lab", "0", tmp_path / "lab_stages.toml", "demo")]
    assert session_state["demo__run_logs"] == ["keep me"]
    undo_snapshot = session_state["demo__undo_delete_snapshot"]
    assert undo_snapshot["label"] == "remove stage 1"
    assert undo_snapshot["timestamp"] == "2026-04-29T08:00:00"
    assert undo_snapshot["stages"] == stages


def test_delete_pipeline_stage_command_refuses_missing_stage(tmp_path):
    selected_map: dict[int, str] = {0: "runtime-a"}
    removed: list[tuple[Any, ...]] = []

    result = pipeline_page_state.delete_pipeline_stage_command(
        session_state={},
        index_page="demo",
        stage_index=4,
        lab_dir=tmp_path / "lab",
        stages_file=tmp_path / "lab_stages.toml",
        persisted_stages=[{"Q": "alpha"}],
        selected_map=selected_map,
        capture_pipeline_snapshot=lambda *_args: {"stages": []},
        remove_stage=lambda *args: removed.append(args),
    )

    assert result.status is pipeline_page_state.PipelineCommandStatus.REFUSED
    assert selected_map == {0: "runtime-a"}
    assert removed == []


def test_delete_all_pipeline_stages_command_resets_editor_state_without_touching_logs(tmp_path):
    session_state: dict[str, Any] = {
        "demo": [1, "d", "q", "m", "c", "detail", 3],
        "demo__details": {0: "a"},
        "demo__venv_map": {0: "runtime-a"},
        "demo__run_sequence": [2, 0],
        "demo_run_sequence_widget": [2, 0],
        "demo__run_logs": ["existing"],
        "demo_confirm_delete_all": True,
        "demo__q_rev": 4,
        "lab_selected_venv": "runtime-a",
    }
    removed: list[str] = []
    bumps: list[str] = []
    persisted_sequences: list[list[int]] = []
    stages = [{"Q": "a"}, {"Q": "b"}, {"Q": "c"}]

    result = pipeline_page_state.delete_all_pipeline_stages_command(
        session_state=session_state,
        index_page="demo",
        lab_dir=tmp_path / "lab",
        module_path=tmp_path / "module",
        stages_file=tmp_path / "lab_stages.toml",
        persisted_stages=stages,
        sequence_widget_key="demo_run_sequence_widget",
        capture_pipeline_snapshot=lambda _index_page, captured_stages: {"stages": list(captured_stages)},
        remove_stage=lambda _lab_dir, stage, _stages_file, _index_page: removed.append(stage),
        bump_history_revision=lambda: bumps.append("bump"),
        persist_sequence_preferences=lambda _module, _stages_file, sequence: persisted_sequences.append(
            list(sequence)
        ),
        confirm_key="demo_confirm_delete_all",
        timestamp="2026-04-29T08:01:00",
    )

    assert result.status is pipeline_page_state.PipelineCommandStatus.SUCCESS
    assert removed == ["2", "1", "0"]
    assert bumps == ["bump"]
    assert persisted_sequences == [[]]
    assert "demo_confirm_delete_all" not in session_state
    assert "demo_run_sequence_widget" not in session_state
    assert session_state["demo"] == [0, "", "", "", "", "", 0]
    assert session_state["demo__details"] == {}
    assert session_state["demo__venv_map"] == {}
    assert session_state["demo__run_sequence"] == []
    assert session_state["demo__run_logs"] == ["existing"]
    assert session_state["lab_selected_venv"] == ""
    assert session_state["demo__clear_q"] is True
    assert session_state["demo__force_blank_q"] is True
    assert session_state["demo__q_rev"] == 5
    undo_snapshot = session_state["demo__undo_delete_snapshot"]
    assert undo_snapshot["label"] == "delete pipeline"
    assert undo_snapshot["timestamp"] == "2026-04-29T08:01:00"
    assert undo_snapshot["stages"] == stages


def test_delete_all_pipeline_stages_command_noops_without_stages(tmp_path):
    session_state: dict[str, Any] = {
        "demo": [0, "", "", "", "", "", 0],
        "demo_confirm_delete_all": True,
    }

    result = pipeline_page_state.delete_all_pipeline_stages_command(
        session_state=session_state,
        index_page="demo",
        lab_dir=tmp_path / "lab",
        module_path=tmp_path / "module",
        stages_file=tmp_path / "lab_stages.toml",
        persisted_stages=[],
        sequence_widget_key="demo_run_sequence_widget",
        capture_pipeline_snapshot=lambda *_args: {"stages": []},
        remove_stage=lambda *_args: None,
        bump_history_revision=lambda: None,
        persist_sequence_preferences=lambda *_args: None,
        confirm_key="demo_confirm_delete_all",
    )

    assert result.status is pipeline_page_state.PipelineCommandStatus.NO_OP
    assert "demo_confirm_delete_all" not in session_state


def test_undo_pipeline_delete_command_restores_and_clears_snapshot(tmp_path):
    session_state: dict[str, Any] = {
        "demo__undo_delete_snapshot": {"stages": [{"Q": "restored"}], "label": "delete pipeline"}
    }
    restored: list[tuple[Any, ...]] = []

    result = pipeline_page_state.undo_pipeline_delete_command(
        session_state=session_state,
        index_page="demo",
        module_path=tmp_path / "module",
        stages_file=tmp_path / "lab_stages.toml",
        sequence_widget_key="demo_run_sequence_widget",
        restore_pipeline_snapshot=lambda *args: restored.append(args) or None,
    )

    assert result.status is pipeline_page_state.PipelineCommandStatus.SUCCESS
    assert "demo__undo_delete_snapshot" not in session_state
    assert restored == [
        (
            tmp_path / "module",
            tmp_path / "lab_stages.toml",
            "demo",
            "demo_run_sequence_widget",
            {"stages": [{"Q": "restored"}], "label": "delete pipeline"},
        )
    ]


def test_undo_pipeline_delete_command_reports_restore_errors(tmp_path):
    session_state: dict[str, Any] = {
        "demo__undo_delete_snapshot": {"stages": [{"Q": "restored"}], "label": "delete pipeline"}
    }

    result = pipeline_page_state.undo_pipeline_delete_command(
        session_state=session_state,
        index_page="demo",
        module_path=tmp_path / "module",
        stages_file=tmp_path / "lab_stages.toml",
        sequence_widget_key="demo_run_sequence_widget",
        restore_pipeline_snapshot=lambda *_args: "restore boom",
    )

    assert result.status is pipeline_page_state.PipelineCommandStatus.FAILED
    assert result.message == "Undo failed: restore boom"
    assert "demo__undo_delete_snapshot" in session_state
