"""Queue recovery never discards a competing task generation or executes pickle."""
import json
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agi_cluster.agi_distributor.service import service_state_support as state


@pytest.fixture
def queue(tmp_path):
    paths = {name: tmp_path / name for name in ("running", "failed", "done")}
    for path in paths.values():
        path.mkdir()
    return SimpleNamespace(
        _service_queue_running=paths["running"], _service_queue_failed=paths["failed"],
        _service_queue_done=paths["done"], _service_read_heartbeat_payloads=Mock(return_value={}),
        _service_heartbeat_timeout_value=lambda: 10,
    )


def write_claim(queue, *, filename="job.task.json", payload=None, age=100):
    path = queue._service_queue_running / filename
    data = payload if payload is not None else {
        "schema": state.SERVICE_TASK_SCHEMA, "task_id": "job", "worker": "worker-a", "status": "running",
        "claim": {"worker_incarnation": "generation-a", "task_filename": "job.task.json"},
    }
    path.write_text(json.dumps(data))
    os.utime(path, (1000 - age, 1000 - age))
    return path, data


@pytest.mark.parametrize("field,value", [
    ("schema", "unsupported"), ("status", "running"), ("task_id", "different"),
    ("worker", "other-worker"), ("claim", {"worker_incarnation": "generation-b"}),
    ("claim", None),
])
def test_terminal_filename_alone_cannot_authorize_discarding_claim(queue, field, value):
    path, data = write_claim(queue)
    terminal = dict(data, status="done")
    terminal[field] = value
    done = queue._service_queue_done / path.name
    done.write_text(json.dumps(terminal))
    before = done.read_bytes()
    result = state.recover_orphaned_service_tasks(queue, now=1000)
    assert result == {"recovered": 1, "preserved": 0}
    assert not path.exists()
    failed = json.loads((queue._service_queue_failed / path.name).read_text())
    assert failed["status"] == "failed"
    assert failed["task_id"] == "job"
    assert done.read_bytes() == before


@pytest.mark.parametrize("terminal_content", ["[]", "{incomplete"])
def test_invalid_terminal_evidence_is_not_completion_proof(queue, terminal_content):
    path, _ = write_claim(queue)
    (queue._service_queue_done / path.name).write_text(terminal_content)
    assert state.recover_orphaned_service_tasks(queue, now=1000)["recovered"] == 1
    assert (queue._service_queue_failed / path.name).exists()


@pytest.mark.parametrize("terminal_status", ["done", "failed"])
def test_matching_terminal_generation_removes_duplicate_running_evidence(queue, terminal_status):
    path, data = write_claim(queue)
    directory = getattr(queue, "_service_queue_" + terminal_status)
    target = directory / path.name
    target.write_text(json.dumps(dict(data, status=terminal_status)))
    before = target.read_bytes()
    assert state.recover_orphaned_service_tasks(queue, now=1000) == {"recovered": 1, "preserved": 0}
    assert not path.exists()
    assert target.read_bytes() == before


def test_identityless_terminal_record_does_not_prove_same_task(queue):
    path, data = write_claim(queue, payload={"worker": "worker-a", "status": "running"})
    (queue._service_queue_done / path.name).write_text(json.dumps(dict(data, schema=state.SERVICE_TASK_SCHEMA, status="done")))
    state.recover_orphaned_service_tasks(queue, now=1000)
    assert (queue._service_queue_failed / path.name).exists()


@pytest.mark.parametrize("heartbeat,expected", [
    ({"timestamp": 999, "worker_incarnation": "generation-a", "state": "running"}, "preserved"),
    ({"timestamp": 999, "worker_incarnation": "generation-b", "state": "running"}, "recovered"),
    ({"timestamp": 999, "worker_incarnation": "generation-a", "state": "stopped"}, "recovered"),
    ({"timestamp": 999, "worker_incarnation": "generation-a", "state": "failed"}, "recovered"),
    ({"timestamp": "bad", "worker_incarnation": "generation-a"}, "recovered"),
    ({"timestamp": 800, "worker_incarnation": "generation-a"}, "recovered"),
])
def test_recovery_heartbeat_requires_live_matching_incarnation(queue, heartbeat, expected):
    path, _ = write_claim(queue)
    queue._service_read_heartbeat_payloads.return_value = {"worker-a": heartbeat}
    result = state.recover_orphaned_service_tasks(queue, now=1000)
    assert result[expected] == 1
    assert path.exists() is (expected == "preserved")


def test_heartbeat_arriving_after_claim_restores_original_running_bytes(queue):
    path, _ = write_claim(queue)
    before = path.read_bytes()
    queue._service_read_heartbeat_payloads.side_effect = [{}, {"worker-a": {
        "timestamp": 999, "worker_incarnation": "generation-a", "state": "running"}}]
    assert state.recover_orphaned_service_tasks(queue, now=1000) == {"recovered": 0, "preserved": 1}
    assert path.read_bytes() == before
    assert not list(queue._service_queue_running.glob(".*.tmp"))
    assert not list(queue._service_queue_failed.iterdir())


def test_hidden_recovery_claim_never_overwrites_competing_canonical(queue):
    path, _ = write_claim(queue, age=1)
    hidden, _ = write_claim(queue, filename=".job.task.json.recovery-interrupted.tmp")
    before = path.read_bytes(), hidden.read_bytes()
    assert state.recover_orphaned_service_tasks(queue, now=1000) == {"recovered": 0, "preserved": 2}
    assert (path.read_bytes(), hidden.read_bytes()) == before


def test_failed_terminal_publication_restores_only_task_evidence(monkeypatch, queue):
    path, _ = write_claim(queue)
    before = path.read_bytes()
    monkeypatch.setattr(state, "_atomic_write", Mock(side_effect=OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        state.recover_orphaned_service_tasks(queue, now=1000)
    assert path.read_bytes() == before
    assert not list(queue._service_queue_running.glob(".*.tmp"))


def test_existing_failed_record_is_not_overwritten_by_new_orphan(queue):
    path, data = write_claim(queue)
    destination = queue._service_queue_failed / path.name
    destination.write_text(json.dumps(dict(data, status="failed", task_id="different")))
    before = destination.read_bytes()
    assert state.recover_orphaned_service_tasks(queue, now=1000)["recovered"] == 1
    assert destination.read_bytes() == before
    recovered = list(queue._service_queue_failed.glob("job.orphaned-*.task.json"))
    assert len(recovered) == 1
    assert json.loads(recovered[0].read_text())["task_id"] == "job"


@pytest.mark.parametrize("fresh,collision", [(True, False), (False, False), (False, True)])
def test_legacy_pickle_is_moved_opaquely_and_collision_preserves_prior_bytes(queue, fresh, collision):
    path = queue._service_queue_running / "legacy.task.pkl"
    payload = b"not a valid pickle; recovery must not deserialize it"
    path.write_bytes(payload)
    os.utime(path, (999 if fresh else 800,) * 2)
    target = queue._service_queue_failed / path.name
    if collision:
        target.write_bytes(b"prior terminal evidence")
    result = state.recover_orphaned_service_tasks(queue, now=1000)
    if fresh:
        assert result == {"recovered": 0, "preserved": 1}
        assert path.read_bytes() == payload
    else:
        assert result == {"recovered": 1, "preserved": 0}
        assert not path.exists()
        candidates = list(queue._service_queue_failed.glob("legacy.orphaned-*.task.pkl")) if collision else [target]
        assert len(candidates) == 1
        assert candidates[0].read_bytes() == payload
        if collision:
            assert target.read_bytes() == b"prior terminal evidence"


@pytest.mark.parametrize("payload", [[], None, "{incomplete"])
def test_unreadable_running_claim_is_preserved_for_diagnosis(queue, payload):
    path = queue._service_queue_running / "job.task.json"
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload))
    before = path.read_bytes()
    assert state.recover_orphaned_service_tasks(queue, now=1000) == {"recovered": 0, "preserved": 0}
    assert path.read_bytes() == before


def test_uninitialized_queue_does_no_recovery():
    assert state.recover_orphaned_service_tasks(SimpleNamespace(
        _service_queue_running=None, _service_queue_failed=None)) == {"recovered": 0, "preserved": 0}
