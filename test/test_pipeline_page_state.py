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
    assert state_without_logs.visible_steps[0].label == "Step 1: generate trajectories"
    assert state_after_clear.visible_steps == state_without_logs.visible_steps
    assert state_after_clear.run_logs == ()
    assert state_after_clear.can_run is True


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
