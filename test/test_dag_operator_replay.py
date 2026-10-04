from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import threading

import pytest

from agilab.dag.dag_run_engine import DagRunEngine
from agilab.dag.dag_idempotency import DagExternalExecutionUncertainError
from agilab.dag.dag_operator_replay import prepare_operator_replay, replay_unit_ids
from agilab.global_pipeline.global_pipeline_runner_state import RunnerStateConflictError, RunnerStateRecoveryRequiredError, runner_state_revision


def _engine(tmp_path, *, queue=None, relay=None):
    return DagRunEngine(
        repo_root=Path.cwd(), lab_dir=tmp_path,
        dag_path=Path("docs/source/data/multi_app_dag_sample.json").resolve(),
        run_queue_fn=queue or _result, run_relay_fn=relay or _result,
    )


def _result(**kwargs):
    return {
        "workspace": str(kwargs["run_root"]),
        "summary_metrics_path": "summary.json", "reduce_artifact_path": "reduce.json",
        "summary_metrics": {"packets_generated": 8, "packets_delivered": 7},
    }


def _complete(engine):
    state, _, _ = engine.load_or_create_state()
    state = engine.run_next_controlled_stage_transaction(state).state
    return engine.run_next_controlled_stage_transaction(state).state


def test_partial_rerun_preserves_upstream_and_invalidates_selected_outputs(tmp_path):
    calls = []

    def queue(**kwargs):
        calls.append(("queue", kwargs["idempotency_token"]))
        return _result(**kwargs)

    def relay(**kwargs):
        calls.append(("relay", kwargs["idempotency_token"]))
        return _result(**kwargs)

    engine = _engine(tmp_path, queue=queue, relay=relay)
    completed = _complete(engine)
    upstream = deepcopy(completed["units"][0])
    prepared = engine.prepare_operator_replay_transaction(
        completed, unit_id="relay_followup", action="partial_rerun",
    ).state
    assert prepared["units"][0] == upstream
    assert prepared["units"][1]["dispatch_status"] == "runnable"
    assert {row["artifact"] for row in prepared["artifacts"]} == {"queue_metrics", "queue_reduce_summary"}
    assert all(row["producer"] == "queue_baseline" for row in prepared["artifacts"])
    reloaded, _, _ = _engine(tmp_path).load_or_create_state()
    assert reloaded == prepared
    rerun = engine.run_next_controlled_stage_transaction(reloaded)
    assert rerun.ok and rerun.state["run_status"] == "completed"
    assert [app for app, _ in calls] == ["queue", "relay", "relay"]
    assert calls[1][1] != calls[2][1]


def test_upstream_partial_rerun_invalidates_downstream_and_preserves_history(tmp_path):
    engine = _engine(tmp_path)
    completed = _complete(engine)
    assert replay_unit_ids(completed, "queue_baseline") == ("queue_baseline", "relay_followup")
    prepared = engine.prepare_operator_replay_transaction(
        completed, unit_id="queue_baseline", action="partial_rerun",
    ).state
    assert [unit["dispatch_status"] for unit in prepared["units"]] == ["runnable", "blocked"]
    assert prepared["artifacts"] == []
    assert prepared["events"][:len(completed["events"])] == completed["events"]
    assert prepared["summary"]["completed_count"] == 0
    assert completed["run_status"] == "completed"  # Input remains unchanged.


def test_failed_stage_retry_runs_with_new_token_and_unblocks_dependent(tmp_path):
    tokens = []

    def fail_once(**kwargs):
        tokens.append(kwargs["idempotency_token"])
        if len(tokens) == 1:
            raise RuntimeError("Injected local failure before producing output")
        return _result(**kwargs)

    engine = _engine(tmp_path, queue=fail_once)
    state, _, _ = engine.load_or_create_state()
    with pytest.raises(DagExternalExecutionUncertainError):
        engine.run_next_controlled_stage_transaction(state)
    uncertain = engine.load_or_create_state()[0]
    token = uncertain["active_execution"]["unit_tokens"]["queue_baseline"]
    failed = engine.recover_execution_attempt_transaction(
        uncertain, unit_id="queue_baseline", idempotency_token=token,
    )
    assert failed["units"][0]["dispatch_status"] == "failed"
    prepared = engine.prepare_operator_replay_transaction(
        failed, unit_id="queue_baseline", action="retry",
    ).state
    assert prepared["units"][0]["retry"]["attempt"] == 1
    retried = engine.run_next_controlled_stage_transaction(prepared)
    assert retried.ok and retried.state["units"][1]["dispatch_status"] == "runnable"
    assert tokens[0] != tokens[1]
    assert engine.run_next_controlled_stage_transaction(retried.state).state["run_status"] == "completed"


def test_stale_and_duplicate_replay_requests_cannot_mutate_state(tmp_path):
    engine = _engine(tmp_path)
    completed = _complete(engine)
    prepared = engine.prepare_operator_replay_transaction(
        completed, unit_id="relay_followup", action="partial_rerun",
    ).state
    with pytest.raises(RunnerStateConflictError):
        engine.prepare_operator_replay_transaction(
            completed, unit_id="relay_followup", action="partial_rerun",
        )
    with pytest.raises(ValueError, match="requires a completed"):
        engine.prepare_operator_replay_transaction(
            prepared, unit_id="relay_followup", action="partial_rerun",
        )
    assert engine.load_or_create_state()[0] == prepared


def test_replay_refuses_running_or_changed_source_contract(tmp_path):
    engine = _engine(tmp_path)
    baseline = engine.load_or_create_state()[0]
    completed = _complete(engine)
    changed = deepcopy(baseline)
    changed["units"][1]["artifact_dependencies"][0]["source_path"] = "changed.json"
    with pytest.raises(ValueError, match="contract changed"):
        prepare_operator_replay(
            completed, baseline=changed, unit_id="relay_followup", action="partial_rerun", timestamp="now",
        )
    running = deepcopy(completed)
    running["units"][0]["dispatch_status"] = "running"
    with pytest.raises(ValueError, match="must finish"):
        prepare_operator_replay(
            running, baseline=baseline, unit_id="relay_followup", action="partial_rerun", timestamp="now",
        )


def test_retry_does_not_unlock_stage_with_incomplete_explicit_dependency(tmp_path):
    engine = _engine(tmp_path)
    baseline = engine.load_or_create_state()[0]
    baseline["units"][1]["artifact_dependencies"] = []
    baseline["units"][1]["dispatch_status"] = "blocked"
    failed = deepcopy(baseline)
    failed["units"][1]["dispatch_status"] = "failed"
    prepared = prepare_operator_replay(
        failed, baseline=baseline, unit_id="relay_followup", action="retry", timestamp="now",
    )
    assert prepared["units"][1]["dispatch_status"] == "blocked"


def test_replay_refuses_saved_source_without_current_fingerprint(tmp_path):
    engine = _engine(tmp_path)
    completed = _complete(engine)
    observed_revision = runner_state_revision(completed)
    completed["source"].pop("dag_sha256")
    engine.write_state(completed, expected_revision=observed_revision)
    with pytest.raises(ValueError, match="fingerprint is missing or changed"):
        engine.prepare_operator_replay_transaction(
            completed, unit_id="relay_followup", action="partial_rerun",
        )


def test_replay_cannot_invalidate_a_live_execution_owner(tmp_path):
    started, release = threading.Event(), threading.Event()
    relay_calls = []

    def relay(**kwargs):
        relay_calls.append(kwargs["idempotency_token"])
        if len(relay_calls) == 2:
            started.set()
            assert release.wait(10)
        return _result(**kwargs)

    engine = _engine(tmp_path, relay=relay)
    completed = _complete(engine)
    prepared = engine.prepare_operator_replay_transaction(
        completed, unit_id="relay_followup", action="partial_rerun",
    ).state
    outcomes = []
    thread = threading.Thread(target=lambda: outcomes.append(engine.run_next_controlled_stage_transaction(prepared)))
    thread.start()
    try:
        assert started.wait(10)
        active = engine.load_or_create_state()[0]
        with pytest.raises(RunnerStateRecoveryRequiredError):
            engine.prepare_operator_replay_transaction(
                active, unit_id="queue_baseline", action="partial_rerun",
            )
        assert engine.load_or_create_state()[0] == active
    finally:
        release.set()
        thread.join(10)
    assert not thread.is_alive()
    assert len(outcomes) == 1 and outcomes[0].ok
    assert len(relay_calls) == 2


def test_native_workflow_panel_prepares_selected_branch_and_reloads_persisted_state(tmp_path):
    from agi_web.testing import AppTest

    calls = []

    def callback(**kwargs):
        calls.append(kwargs["idempotency_token"])
        return _result(**kwargs)

    engine = _engine(tmp_path, queue=callback, relay=callback)
    _complete(engine)

    def workflow_view():
        from agilab.pipeline.pipeline_lab import _render_global_runner_state_view

        state, state_path, dag_path = engine.load_or_create_state()
        _render_global_runner_state_view(
            state=state, state_path=state_path, dag_path=dag_path, dag_engine=engine,
            repo_root=engine.repo_root, index_page_str="operator-widget-proof",
        )

    app = AppTest.from_function(workflow_view).run()
    assert not app.exception
    key_prefix = "operator-widget-proof_global_runner"
    assert app.button(key=f"{key_prefix}_prepare_partial_rerun").label == "Prepare partial rerun"
    app.selectbox(key=f"{key_prefix}_replay_stage").select("relay_followup").run()
    app.button(key=f"{key_prefix}_prepare_partial_rerun").click().run()
    assert not app.exception
    persisted = engine.load_or_create_state()[0]
    assert [unit["dispatch_status"] for unit in persisted["units"]] == ["completed", "runnable"]
    assert len(calls) == 2  # Preparation never executes an app callback.
    reloaded = AppTest.from_function(workflow_view).run()
    assert not reloaded.exception
    assert engine.load_or_create_state()[0] == persisted
    reloaded.button(key=f"{key_prefix}_run_next_stage").click().run()
    assert not reloaded.exception
    assert engine.load_or_create_state()[0]["run_status"] == "completed"
    assert len(calls) == 3 and calls[1] != calls[2]


def test_source_change_during_plan_read_is_rejected_before_state_publication(tmp_path, monkeypatch):
    import agilab.dag.dag_run_engine as engine_module

    source = tmp_path / "agilab_operator_source_consistency_dag.json"
    source.write_bytes(Path("docs/source/data/multi_app_dag_sample.json").read_bytes())
    engine = DagRunEngine(repo_root=Path.cwd(), lab_dir=tmp_path / "lab", dag_path=source)
    original = engine_module.build_persisted_runner_state

    def change_after_read(**kwargs):
        result = original(**kwargs)
        source.write_bytes(source.read_bytes() + b"\n")
        return result

    monkeypatch.setattr(engine_module, "build_persisted_runner_state", change_after_read)
    with pytest.raises(ValueError, match="changed while its plan was being read"):
        engine.load_or_create_state()
    assert not engine.state_path.exists()
