from __future__ import annotations

import importlib.util
import multiprocessing
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


REPORT_PATH = Path("tools/global_pipeline_runner_state_report.py").resolve()
CORE_PATH = Path("src/agilab/global_pipeline_runner_state.py").resolve()


def _load_report_module():
    spec = importlib.util.spec_from_file_location("global_pipeline_runner_state_report_test_module", REPORT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_core_module():
    spec = importlib.util.spec_from_file_location("global_pipeline_runner_state_test_module", CORE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _read_runner_state_until_stopped(
    state_path: str,
    stop_event,
    result_queue,
) -> None:
    module = _load_core_module()
    reads = 0
    try:
        while not stop_event.is_set() or reads < 25:
            state = module.load_runner_state(Path(state_path))
            generation = int(state["generation"])
            values = state["values"]
            if len(values) != 4096 or any(value != generation for value in values):
                raise AssertionError(f"partial runner-state generation observed: {generation}")
            reads += 1
    except BaseException as exc:
        result_queue.put((False, reads, repr(exc)))
        return
    result_queue.put((True, reads, ""))


def _attempt_runner_state_transaction(
    state_path: str,
    expected_revision: str,
    start_event,
    execution_count,
    result_queue,
) -> None:
    module = _load_core_module()
    start_event.wait(timeout=5)
    try:
        with module.runner_state_transaction(
            Path(state_path),
            expected_revision=expected_revision,
        ) as transaction:
            with execution_count.get_lock():
                execution_count.value += 1
            next_state = dict(transaction.state)
            next_state["events"] = [*transaction.state.get("events", []), {"kind": "completed"}]
            transaction.commit(next_state)
    except module.RunnerStateConflictError:
        result_queue.put("conflict")
        return
    result_queue.put("committed")


def test_runner_state_report_builds_dispatch_projection() -> None:
    module = _load_report_module()

    report = module.build_report(repo_root=Path.cwd())

    assert report["report"] == "Global pipeline runner state report"
    assert report["status"] == "pass"
    assert report["dag_path"] == "docs/source/data/multi_app_dag_sample.json"
    assert report["summary"]["schema"] == "agilab.global_pipeline_runner_state.v1"
    assert report["summary"]["runner_mode"] == "read_only_preview"
    assert report["summary"]["run_status"] == "not_started"
    assert report["summary"]["unit_count"] == 2
    assert report["summary"]["runnable_count"] == 1
    assert report["summary"]["blocked_count"] == 1
    assert report["summary"]["completed_count"] == 0
    assert report["summary"]["failed_count"] == 0
    assert report["summary"]["runnable_unit_ids"] == ["queue_baseline"]
    assert report["summary"]["blocked_unit_ids"] == ["relay_followup"]
    assert report["summary"]["retry_policy_count"] == 2
    assert report["summary"]["partial_rerun_record_count"] == 2
    assert report["summary"]["operator_state_count"] == 2
    assert {check["id"] for check in report["checks"]} == {
        "global_pipeline_runner_state_schema",
        "global_pipeline_runner_state_dispatch_queue",
        "global_pipeline_runner_state_transitions",
        "global_pipeline_runner_state_retry_partial_rerun",
        "global_pipeline_runner_state_operator_ui",
        "global_pipeline_runner_state_provenance",
        "global_pipeline_runner_state_docs_reference",
    }


def test_runner_state_units_keep_transitions_and_operator_metadata() -> None:
    module = _load_core_module()

    state = module.build_runner_state(repo_root=Path.cwd())

    assert state.ok is True
    first, second = state.state_units
    assert first["id"] == "queue_baseline"
    assert first["dispatch_status"] == "runnable"
    assert first["operator_ui"]["state"] == "ready_to_dispatch"
    assert first["produces"] == [
        {
            "artifact": "queue_metrics",
            "kind": "summary_metrics",
            "path": "queue_analysis/uav_queue_summary_metrics.json",
        }
    ]
    assert first["retry"] == {
        "attempt": 0,
        "last_error": "",
        "max_attempts": 0,
        "next_action": "configure retry policy before dispatching queue_baseline",
        "policy": "metadata_only",
        "status": "not_scheduled",
    }
    assert first["partial_rerun"] == {
        "artifact_scope": ["queue_metrics"],
        "eligible_after_completion": True,
        "policy": "metadata_only",
        "requested": False,
        "requires_completed_dependencies": [],
    }

    assert second["id"] == "relay_followup"
    assert second["dispatch_status"] == "blocked"
    assert second["operator_ui"] == {
        "blocked_by_artifacts": ["queue_metrics"],
        "message": "relay_followup is blocked until queue_metrics is available.",
        "severity": "info",
        "state": "waiting_for_artifacts",
    }
    assert second["partial_rerun"]["artifact_scope"] == ["relay_metrics"]
    assert second["produces"] == [
        {
            "artifact": "relay_metrics",
            "kind": "summary_metrics",
            "path": "queue_analysis/uav_relay_queue_summary_metrics.json",
        }
    ]
    assert second["partial_rerun"]["requires_completed_dependencies"] == ["queue_baseline"]
    assert second["provenance"] == {
        "pipeline_view": "src/agilab/apps/builtin/uav_relay_queue_project/pipeline_view.dot",
        "planning_mode": "read_only",
        "runner_state_mode": "read_only_preview",
        "source_app": "uav_relay_queue_project",
        "source_dag": "docs/source/data/multi_app_dag_sample.json",
        "source_plan_runner_status": "not_executed",
        "source_plan_schema": "agilab.global_pipeline_execution_plan.v1",
        "source_unit_id": "relay_followup",
    }
    transition_pairs = {
        (transition["from"], transition["to"])
        for unit in state.state_units
        for transition in unit["transitions"]
    }
    assert {
        ("pending", "runnable"),
        ("pending", "blocked"),
        ("blocked", "runnable"),
        ("runnable", "completed"),
        ("runnable", "failed"),
        ("failed", "runnable"),
        ("completed", "runnable"),
    }.issubset(transition_pairs)


def test_persisted_runner_state_dispatches_next_runnable_without_app_execution(tmp_path: Path) -> None:
    module = _load_core_module()
    output_path = tmp_path / "runner_state.json"

    proof = module.persist_runner_state(
        repo_root=Path.cwd(),
        output_path=output_path,
        now="2026-04-29T00:00:00Z",
    )

    assert proof.ok is True
    assert proof.round_trip_ok is True
    state = proof.runner_state
    assert state["schema"] == "agilab.global_pipeline_runner_state.v1"
    assert state["persistence_format"] == "json"
    assert state["run_status"] == "planned"
    assert state["summary"]["planned_count"] == 2
    assert state["summary"]["running_count"] == 0
    assert state["summary"]["runnable_unit_ids"] == ["queue_baseline"]
    assert state["provenance"]["real_app_execution"] is False

    result = module.dispatch_next_runnable(state, now="2026-04-29T00:00:01Z")

    assert result.ok is True
    assert result.dispatched_unit_id == "queue_baseline"
    assert result.state["run_status"] == "running"
    assert result.state["summary"]["planned_count"] == 1
    assert result.state["summary"]["running_count"] == 1
    assert result.state["summary"]["running_unit_ids"] == ["queue_baseline"]
    assert result.state["summary"]["blocked_unit_ids"] == ["relay_followup"]
    assert result.state["events"][-1] == {
        "detail": "operator dispatched the next runnable unit without executing the app",
        "from_status": "runnable",
        "kind": "unit_dispatched",
        "timestamp": "2026-04-29T00:00:01Z",
        "to_status": "running",
        "unit_id": "queue_baseline",
    }
    assert result.state["provenance"]["real_app_execution"] is False


def test_persisted_runner_state_validates_flight_plus_meteo_dag(tmp_path: Path) -> None:
    module = _load_core_module()
    dag_path = Path("docs/source/data/multi_app_dag_flight_sample.json")

    proof = module.persist_runner_state(
        repo_root=Path.cwd(),
        output_path=tmp_path / "runner_state.json",
        dag_path=dag_path,
        now="2026-04-29T00:00:00Z",
    )

    assert proof.ok is True
    state = proof.runner_state
    assert state["source"]["dag_path"] == str(dag_path)
    assert state["source"]["execution_order"] == ["flight_context", "weather_forecast_review"]
    assert state["summary"]["unit_count"] == 2
    assert state["summary"]["runnable_unit_ids"] == ["flight_context"]
    assert state["summary"]["blocked_unit_ids"] == ["weather_forecast_review"]
    assert [unit["app"] for unit in state["units"]] == [
        "flight_telemetry_project",
        "weather_forecast_project",
    ]
    assert all(unit["provenance"]["pipeline_view"] for unit in state["units"])


def test_runner_state_report_handles_load_failure(tmp_path: Path) -> None:
    module = _load_report_module()
    missing = tmp_path / "missing.json"

    report = module.build_report(repo_root=Path.cwd(), dag_path=missing)

    assert report["status"] == "fail"
    assert report["checks"] == [
        {
            "details": {
                "error": f"[Errno 2] No such file or directory: '{missing}'",
            },
            "evidence": [str(missing)],
            "id": "global_pipeline_runner_state_load",
            "label": "Global pipeline runner state load",
            "status": "fail",
            "summary": "global pipeline runner state could not be assembled",
        }
    ]


def test_runner_state_helper_and_failure_edges(tmp_path: Path, monkeypatch) -> None:
    module = _load_core_module()

    issue = module._issue("schema", "bad")
    assert issue.as_dict() == {"level": "error", "location": "schema", "message": "bad"}
    assert module._as_str_list("bad") == []
    assert module._dependency_summary([]) == "all artifact dependencies satisfied"
    assert module._unit_rows({"units": "bad"}) == []
    assert module._run_status_for_units([{"dispatch_status": "failed"}]) == "failed"
    assert module._run_status_for_units([{"dispatch_status": "completed"}]) == "completed"
    assert module._run_status_for_units(
        [{"dispatch_status": "completed"}, {"dispatch_status": "blocked"}]
    ) == "running"

    non_object = tmp_path / "state.json"
    non_object.write_text("[]", encoding="utf-8")
    try:
        module.load_runner_state(non_object)
    except ValueError as exc:
        assert "must be a JSON object" in str(exc)
    else:
        raise AssertionError("load_runner_state should reject non-object JSON")

    proof = module.RunnerStatePersistenceProof(
        ok=False,
        issues=(issue,),
        path="state.json",
        runner_state={"a": 1},
        reloaded_state={"a": 2},
    )
    assert proof.round_trip_ok is False
    assert proof.as_dict()["issues"] == [issue.as_dict()]

    dispatch = module.RunnerDispatchResult(
        ok=False,
        message="none",
        dispatched_unit_id="",
        state={},
    )
    assert dispatch.as_dict()["message"] == "none"

    result = module.dispatch_next_runnable(
        {
            "state_units": [
                {"id": "blocked", "dispatch_status": "blocked"},
                {"id": "done", "dispatch_status": "completed"},
            ],
            "events": "bad",
        },
        now="2026-05-17T00:00:00Z",
    )
    assert result.ok is False
    assert result.message == "No runnable multi-app DAG unit is available to dispatch."
    assert result.state["units"] == [
        {"id": "blocked", "dispatch_status": "blocked"},
        {"id": "done", "dispatch_status": "completed"},
    ]
    assert result.state["events"] == []

    monkeypatch.setattr(
        module,
        "build_persisted_runner_state",
        lambda **_kwargs: {"ok": True, "schema": module.SCHEMA},
    )
    monkeypatch.setattr(module, "write_runner_state", lambda output_path, state: output_path)
    monkeypatch.setattr(module, "load_runner_state", lambda _path: {"ok": True, "schema": "changed"})
    proof = module.persist_runner_state(repo_root=tmp_path, output_path=tmp_path / "state.json")
    assert proof.ok is False
    assert proof.issues[0].location == "persistence.round_trip"


def test_runner_state_atomic_replace_prevents_multiprocess_partial_reads(tmp_path: Path) -> None:
    module = _load_core_module()
    state_path = tmp_path / "runner_state.json"
    module.write_runner_state(state_path, {"generation": 0, "values": [0] * 4096})
    context = multiprocessing.get_context("spawn")
    stop_event = context.Event()
    result_queue = context.Queue()
    reader = context.Process(
        target=_read_runner_state_until_stopped,
        args=(str(state_path), stop_event, result_queue),
    )
    reader.start()
    try:
        for generation in range(1, 41):
            module.write_runner_state(
                state_path,
                {"generation": generation, "values": [generation] * 4096},
            )
    finally:
        stop_event.set()
        reader.join(timeout=15)
        if reader.is_alive():
            reader.terminate()
            reader.join(timeout=5)

    assert reader.exitcode == 0
    ok, reads, error = result_queue.get(timeout=2)
    assert ok, error
    assert reads >= 25


def test_runner_state_read_retries_windows_sharing_violation(monkeypatch, tmp_path: Path) -> None:
    module = _load_core_module()
    state_path = tmp_path / "runner_state.json"
    state_path.write_text('{"generation": 1}\n', encoding="utf-8")
    real_read_text = Path.read_text
    attempts = 0

    def _transient_read_text(path: Path, *args, **kwargs):
        nonlocal attempts
        if path == state_path:
            attempts += 1
            if attempts == 1:
                raise PermissionError("sharing violation")
        return real_read_text(path, *args, **kwargs)

    monkeypatch.setattr(module, "_is_windows", lambda: True)
    monkeypatch.setattr(module.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(Path, "read_text", _transient_read_text)

    assert module.load_runner_state(state_path) == {"generation": 1}
    assert attempts == 2


def test_runner_state_replace_retries_windows_sharing_violation(monkeypatch, tmp_path: Path) -> None:
    module = _load_core_module()
    state_path = tmp_path / "runner_state.json"
    real_replace = module.os.replace
    attempts = 0

    def _transient_replace(source, destination):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("sharing violation")
        return real_replace(source, destination)

    monkeypatch.setattr(module, "_is_windows", lambda: True)
    monkeypatch.setattr(module.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(module.os, "replace", _transient_replace)

    module.write_runner_state(state_path, {"generation": 1})

    assert module.load_runner_state(state_path) == {"generation": 1}
    assert attempts == 2


def test_runner_state_lock_times_out_instead_of_freezing_session(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_core_module()
    state_path = tmp_path / "runner_state.json"
    monkeypatch.setattr(module, "_RUNNER_STATE_LOCK_TIMEOUT_SECONDS", 0.01)

    with module._exclusive_runner_state_lock(state_path):
        with pytest.raises(TimeoutError, match="Another session"):
            with module._exclusive_runner_state_lock(state_path):
                raise AssertionError("nested lock unexpectedly acquired")


def test_runner_state_write_refuses_stale_revision(tmp_path: Path) -> None:
    module = _load_core_module()
    state_path = tmp_path / "runner_state.json"
    initial = {"generation": 1, "events": [{"kind": "created"}]}
    module.write_runner_state(state_path, initial)
    stale_revision = module.runner_state_revision(initial)
    current = {"generation": 2, "events": [{"kind": "created"}, {"kind": "completed"}]}
    module.write_runner_state(
        state_path,
        current,
        expected_revision=stale_revision,
    )

    with pytest.raises(module.RunnerStateConflictError, match="another session"):
        module.write_runner_state(
            state_path,
            {"generation": 3, "events": [{"kind": "stale overwrite"}]},
            expected_revision=stale_revision,
        )

    assert module.load_runner_state(state_path) == current


def test_runner_state_directory_fsync_failure_keeps_committed_write_successful(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_core_module()
    state_path = tmp_path / "runner_state.json"
    state = {"generation": 1, "events": [{"kind": "created"}]}
    real_fsync = module.os.fsync

    def _fail_directory_fsync(fd):
        if stat.S_ISDIR(module.os.fstat(fd).st_mode):
            raise OSError("directory fsync unavailable")
        return real_fsync(fd)

    monkeypatch.setattr(module.os, "fsync", _fail_directory_fsync)
    evidence_published = False
    with module.runner_state_write_transaction(
        state_path,
        state,
        expected_revision=module.MISSING_RUNNER_STATE_REVISION,
    ) as written_path:
        assert written_path == state_path
        evidence_published = True

    assert evidence_published
    assert module.load_runner_state(state_path) == state


def test_windows_directory_flush_fails_closed_when_durability_is_unproven(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_core_module()
    observed_paths: list[Path] = []
    monkeypatch.setattr(module, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        module,
        "_flush_windows_directory",
        lambda path: observed_paths.append(path) or False,
    )

    assert module._fsync_runner_state_directory(tmp_path) is False
    assert observed_paths == [tmp_path]


def test_new_directory_hierarchy_flushes_each_parent_entry(monkeypatch, tmp_path: Path) -> None:
    module = _load_core_module()
    flushed: list[Path] = []
    monkeypatch.setattr(
        module,
        "_fsync_runner_state_directory",
        lambda path: flushed.append(path) or True,
    )
    target = tmp_path / "new-lab" / ".agilab"

    assert module._ensure_directory_hierarchy_durable(target) is True
    assert target.is_dir()
    assert target in flushed
    assert target.parent in flushed
    assert tmp_path in flushed


@pytest.mark.skipif(os.name != "nt", reason="real Windows directory handle required")
def test_windows_directory_flush_real_helper_succeeds(tmp_path: Path) -> None:
    module = _load_core_module()

    assert module._flush_windows_directory(tmp_path) is True


def test_runner_state_transaction_serializes_stale_multiprocess_sessions(tmp_path: Path) -> None:
    module = _load_core_module()
    state_path = tmp_path / "runner_state.json"
    initial = {"events": [{"kind": "created"}]}
    module.write_runner_state(state_path, initial)
    expected_revision = module.runner_state_revision(initial)
    context = multiprocessing.get_context("spawn")
    start_event = context.Event()
    execution_count = context.Value("i", 0)
    result_queue = context.Queue()
    sessions = [
        context.Process(
            target=_attempt_runner_state_transaction,
            args=(
                str(state_path),
                expected_revision,
                start_event,
                execution_count,
                result_queue,
            ),
        )
        for _index in range(2)
    ]
    for session in sessions:
        session.start()
    start_event.set()
    for session in sessions:
        session.join(timeout=15)
        if session.is_alive():
            session.terminate()
            session.join(timeout=5)

    assert [session.exitcode for session in sessions] == [0, 0]
    assert sorted(result_queue.get(timeout=2) for _index in sessions) == ["committed", "conflict"]
    assert execution_count.value == 1
    assert module.load_runner_state(state_path)["events"] == [
        {"kind": "created"},
        {"kind": "completed"},
    ]
