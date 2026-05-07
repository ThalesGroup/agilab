from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from agi_node.agi_dispatcher import BaseWorker
from agi_node.agi_dispatcher import base_worker as base_worker_mod
from agi_node.agi_dispatcher import base_worker_service_support as service_support

SERVICE_TASK_SCHEMA = "agi.service.task.v1"


def _write_task(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps({"schema": SERVICE_TASK_SCHEMA, **payload}, sort_keys=True),
        encoding="utf-8",
    )


class DummyWorker(BaseWorker):
    def __init__(self):
        super().__init__()
        worker_id = 0
        BaseWorker._worker_id = worker_id
        BaseWorker._insts = {worker_id: self}

    def works(self, *_args, **_kwargs):
        pass


def teardown_function(_fn):
    BaseWorker._worker_id = None
    BaseWorker._worker = None
    BaseWorker._insts = {}
    BaseWorker._env = None
    BaseWorker.env = None
    BaseWorker._service_stop_events = {}
    BaseWorker._service_active = {}


def test_resolve_service_queue_root_from_attribute_and_mapping(tmp_path):
    namespace_args = SimpleNamespace(_agi_service_queue_dir=str(tmp_path / "attr-queue"))
    assert service_support.resolve_service_queue_root(namespace_args) == (
        tmp_path / "attr-queue"
    ).resolve(strict=False)

    mapping_args = {"_agi_service_queue_dir": str(tmp_path / "mapping-queue")}
    assert service_support.resolve_service_queue_root(mapping_args) == (
        tmp_path / "mapping-queue"
    ).resolve(strict=False)

    assert service_support.resolve_service_queue_root(SimpleNamespace()) is None


def test_make_heartbeat_writer_persists_payload(tmp_path):
    queue_root = tmp_path / "queue"
    logger_obj = SimpleNamespace(debug=lambda *_args, **_kwargs: None)

    write_heartbeat = service_support.make_heartbeat_writer(
        queue_root,
        worker_id=2,
        worker_name="tcp://127.0.0.1:8787",
        logger_obj=logger_obj,
    )
    write_heartbeat("stopped")

    heartbeat_files = list((queue_root / "heartbeats").glob("*.json"))
    assert heartbeat_files
    heartbeat_payload = json.loads(heartbeat_files[0].read_text(encoding="utf-8"))
    assert heartbeat_payload["worker_id"] == 2
    assert heartbeat_payload["state"] == "stopped"


def test_service_loop_without_worker_override_stops_cleanly():
    worker = DummyWorker()
    result: dict[str, object] = {}

    def _run_loop():
        result["payload"] = BaseWorker.loop(poll_interval=0.05)

    thread = threading.Thread(target=_run_loop, daemon=True)
    thread.start()
    time.sleep(0.1)

    assert BaseWorker.break_loop() is True
    thread.join(timeout=2)
    assert not thread.is_alive(), "BaseWorker.loop did not stop after break_loop"

    payload = result.get("payload")
    assert isinstance(payload, dict)
    assert payload.get("status") == "stopped"


def test_service_loop_consumes_queued_tasks(tmp_path):
    worker = DummyWorker()
    BaseWorker._worker_id = 0
    BaseWorker._worker = "127.0.0.1:8787"
    worker.args = SimpleNamespace(_agi_service_queue_dir=str(tmp_path / "service_queue"))
    calls: list[tuple[object, object]] = []

    def _works(plan, metadata):
        calls.append((plan, metadata))

    worker.works = _works

    queue_root = Path(worker.args._agi_service_queue_dir)
    pending = queue_root / "pending"
    pending.mkdir(parents=True, exist_ok=True)

    payload = {
        "task_id": "batch-1",
        "worker_idx": 0,
        "worker": "127.0.0.1:8787",
        "plan": {
            "__agi_worker_chunk__": True,
            "chunk": ["step-1"],
            "total_workers": 1,
            "worker_idx": 0,
        },
        "metadata": {
            "__agi_worker_chunk__": True,
            "chunk": [{"meta": 1}],
            "total_workers": 1,
            "worker_idx": 0,
        },
    }
    task_file = pending / "000001-batch-1-000-worker.task.json"
    _write_task(task_file, payload)

    result: dict[str, object] = {}

    def _run_loop():
        result["payload"] = BaseWorker.loop(poll_interval=0.05)

    thread = threading.Thread(target=_run_loop, daemon=True)
    thread.start()

    deadline = time.time() + 2.0
    done_file = queue_root / "done" / task_file.name
    while time.time() < deadline and not done_file.exists():
        time.sleep(0.05)

    assert done_file.exists(), "Service queue task was not moved to done"
    assert len(calls) == 1

    assert BaseWorker.break_loop() is True
    thread.join(timeout=2)
    assert not thread.is_alive(), "Service loop did not stop after break_loop"

    payload_out = result.get("payload")
    assert isinstance(payload_out, dict)
    assert payload_out.get("processed") == 1


def test_service_loop_moves_unreadable_task_to_failed(tmp_path):
    worker = DummyWorker()
    BaseWorker._worker_id = 0
    BaseWorker._worker = "127.0.0.1:8787"
    worker.args = SimpleNamespace(_agi_service_queue_dir=str(tmp_path / "service_queue"))

    queue_root = Path(worker.args._agi_service_queue_dir)
    pending = queue_root / "pending"
    pending.mkdir(parents=True, exist_ok=True)

    task_file = pending / "000002-bad.task.json"
    task_file.write_text("not-json", encoding="utf-8")

    result: dict[str, object] = {}

    def _run_loop():
        result["payload"] = BaseWorker.loop(poll_interval=0.05)

    thread = threading.Thread(target=_run_loop, daemon=True)
    thread.start()

    deadline = time.time() + 2.0
    failed_file = queue_root / "failed" / task_file.name
    while time.time() < deadline and not failed_file.exists():
        time.sleep(0.05)

    assert failed_file.exists(), "Unreadable task was not moved to failed"

    assert BaseWorker.break_loop() is True
    thread.join(timeout=2)
    assert not thread.is_alive(), "Service loop did not stop after break_loop"

    payload_out = result.get("payload")
    assert isinstance(payload_out, dict)
    assert payload_out.get("failed") == 0


def test_service_loop_rejects_legacy_pickle_task_without_loading(tmp_path):
    worker = DummyWorker()
    BaseWorker._worker_id = 0
    BaseWorker._worker = "127.0.0.1:8787"
    worker.args = SimpleNamespace(_agi_service_queue_dir=str(tmp_path / "service_queue"))
    calls: list[object] = []
    worker.works = lambda *args, **_kwargs: calls.append(args)

    queue_root = Path(worker.args._agi_service_queue_dir)
    pending = queue_root / "pending"
    pending.mkdir(parents=True, exist_ok=True)

    legacy_task = pending / "000002-legacy.task.pkl"
    legacy_task.write_bytes(b"\x80\x04legacy-pickle-payload")

    result: dict[str, object] = {}

    def _run_loop():
        result["payload"] = BaseWorker.loop(poll_interval=0.05)

    thread = threading.Thread(target=_run_loop, daemon=True)
    thread.start()

    deadline = time.time() + 2.0
    failed_file = queue_root / "failed" / legacy_task.name
    while time.time() < deadline and not failed_file.exists():
        time.sleep(0.05)

    assert failed_file.exists(), "Legacy pickle task was not quarantined"
    assert calls == []

    assert BaseWorker.break_loop() is True
    thread.join(timeout=2)
    assert not thread.is_alive(), "Service loop did not stop after break_loop"


def test_service_loop_records_worker_failures(tmp_path):
    worker = DummyWorker()
    BaseWorker._worker_id = 0
    BaseWorker._worker = "127.0.0.1:8787"
    worker.args = SimpleNamespace(_agi_service_queue_dir=str(tmp_path / "service_queue"))

    def _raise(*_args, **_kwargs):
        raise RuntimeError("boom")

    worker.works = _raise

    queue_root = Path(worker.args._agi_service_queue_dir)
    pending = queue_root / "pending"
    pending.mkdir(parents=True, exist_ok=True)

    payload = {
        "task_id": "batch-fail",
        "worker_idx": 0,
        "worker": "127.0.0.1:8787",
        "plan": {
            "__agi_worker_chunk__": True,
            "chunk": ["step-1"],
            "total_workers": 1,
            "worker_idx": 0,
        },
        "metadata": {
            "__agi_worker_chunk__": True,
            "chunk": [{"meta": 1}],
            "total_workers": 1,
            "worker_idx": 0,
        },
    }
    task_file = pending / "000003-batch-fail-000-worker.task.json"
    _write_task(task_file, payload)

    result: dict[str, object] = {}

    def _run_loop():
        result["payload"] = BaseWorker.loop(poll_interval=0.05)

    thread = threading.Thread(target=_run_loop, daemon=True)
    thread.start()

    deadline = time.time() + 2.0
    failed_file = queue_root / "failed" / task_file.name
    while time.time() < deadline and not failed_file.exists():
        time.sleep(0.05)

    assert failed_file.exists(), "Failed task was not moved to failed"

    failed_payload = json.loads(failed_file.read_text(encoding="utf-8"))
    assert failed_payload["status"] == "failed"
    assert failed_payload["error"] == "boom"
    assert "RuntimeError: boom" in failed_payload["traceback"]

    assert BaseWorker.break_loop() is True
    thread.join(timeout=2)
    assert not thread.is_alive(), "Service loop did not stop after break_loop"

    payload_out = result.get("payload")
    assert isinstance(payload_out, dict)
    assert payload_out.get("failed") == 1


def test_service_loop_skips_tasks_for_other_workers(tmp_path):
    worker = DummyWorker()
    BaseWorker._worker_id = 0
    BaseWorker._worker = "127.0.0.1:8787"
    worker.args = SimpleNamespace(_agi_service_queue_dir=str(tmp_path / "service_queue"))

    queue_root = Path(worker.args._agi_service_queue_dir)
    pending = queue_root / "pending"
    pending.mkdir(parents=True, exist_ok=True)

    mismatched_idx = pending / "000004-idx.task.json"
    _write_task(mismatched_idx, {"worker_idx": 99, "plan": [], "metadata": []})

    mismatched_worker = pending / "000005-worker.task.json"
    _write_task(mismatched_worker, {"worker": "tcp://other:8787", "plan": [], "metadata": []})

    result: dict[str, object] = {}

    def _run_loop():
        result["payload"] = BaseWorker.loop(poll_interval=0.05)

    thread = threading.Thread(target=_run_loop, daemon=True)
    thread.start()
    time.sleep(0.2)

    assert mismatched_idx.exists()
    assert mismatched_worker.exists()

    assert BaseWorker.break_loop() is True
    thread.join(timeout=2)
    assert not thread.is_alive(), "Service loop did not stop after break_loop"

    payload_out = result.get("payload")
    assert isinstance(payload_out, dict)
    assert payload_out.get("processed") == 0


def test_service_loop_swallow_heartbeat_write_failure(monkeypatch, tmp_path):
    class LoopWorker(BaseWorker):
        def __init__(self):
            self.args = SimpleNamespace(_agi_service_queue_dir=str(tmp_path / "queue"))

        def loop(self, stop_event):
            stop_event.set()
            return False

    worker = LoopWorker()
    BaseWorker._worker_id = 0
    BaseWorker._worker = "tcp://127.0.0.1:8787"
    BaseWorker._insts = {0: worker}

    monkeypatch.setattr(base_worker_mod.os, "replace", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("replace denied")))

    payload = BaseWorker.loop(poll_interval=0.0)

    assert payload["status"] == "stopped"
    assert list((tmp_path / "queue" / "heartbeats").glob("*.tmp")) == []


def test_service_loop_skips_claim_races(tmp_path, monkeypatch):
    worker = DummyWorker()
    BaseWorker._worker_id = 0
    BaseWorker._worker = "127.0.0.1:8787"
    worker.args = SimpleNamespace(_agi_service_queue_dir=str(tmp_path / "service_queue"))

    queue_root = Path(worker.args._agi_service_queue_dir)
    pending = queue_root / "pending"
    pending.mkdir(parents=True, exist_ok=True)

    task_file = pending / "000006-claim-race.task.json"
    _write_task(task_file, {"worker_idx": 0, "plan": [], "metadata": []})

    original_replace = Path.replace

    def _patched_replace(self, target):
        if self == task_file:
            raise FileNotFoundError("claimed elsewhere")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", _patched_replace, raising=False)

    result: dict[str, object] = {}

    def _run_loop():
        result["payload"] = BaseWorker.loop(poll_interval=0.05)

    thread = threading.Thread(target=_run_loop, daemon=True)
    thread.start()
    time.sleep(0.2)

    assert task_file.exists()

    assert BaseWorker.break_loop() is True
    thread.join(timeout=2)
    assert not thread.is_alive(), "Service loop did not stop after break_loop"

    payload_out = result.get("payload")
    assert isinstance(payload_out, dict)
    assert payload_out.get("processed") == 0


def test_service_loop_handles_disappearing_task_files(tmp_path, monkeypatch):
    worker = DummyWorker()
    BaseWorker._worker_id = 0
    BaseWorker._worker = "127.0.0.1:8787"
    worker.args = SimpleNamespace(_agi_service_queue_dir=str(tmp_path / "service_queue"))

    queue_root = Path(worker.args._agi_service_queue_dir)
    pending = queue_root / "pending"
    pending.mkdir(parents=True, exist_ok=True)

    task_file = pending / "000007-disappearing.task.json"
    _write_task(task_file, {"worker_idx": 0, "plan": [], "metadata": []})

    original_open = open

    def _patched_open(path, *args, **kwargs):
        if Path(path) == task_file and "r" in kwargs.get("mode", args[0] if args else ""):
            raise FileNotFoundError("gone")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(base_worker_mod, "open", _patched_open, raising=False)

    result: dict[str, object] = {}

    def _run_loop():
        result["payload"] = BaseWorker.loop(poll_interval=0.05)

    thread = threading.Thread(target=_run_loop, daemon=True)
    thread.start()
    time.sleep(0.2)

    assert task_file.exists()

    assert BaseWorker.break_loop() is True
    thread.join(timeout=2)
    assert not thread.is_alive(), "Service loop did not stop after break_loop"

    payload_out = result.get("payload")
    assert isinstance(payload_out, dict)
    assert payload_out.get("processed") == 0


def test_service_loop_custom_worker_writes_heartbeat_and_calls_stop(tmp_path):
    class LoopWorker(BaseWorker):
        def __init__(self):
            self.args = SimpleNamespace(_agi_service_queue_dir=str(tmp_path / "queue"))
            self.stop_called = False

        def loop(self, stop_event):
            stop_event.set()
            return False

        def stop(self):
            self.stop_called = True

    worker = LoopWorker()
    BaseWorker._worker_id = 0
    BaseWorker._worker = "tcp://127.0.0.1:8787"
    BaseWorker._insts = {0: worker}

    payload = BaseWorker.loop(poll_interval=0.0)

    heartbeat_files = list((tmp_path / "queue" / "heartbeats").glob("*.json"))
    assert payload["status"] == "stopped"
    assert worker.stop_called is True
    assert heartbeat_files
    heartbeat_payload = json.loads(heartbeat_files[0].read_text(encoding="utf-8"))
    assert heartbeat_payload["state"] == "stopped"


def test_service_loop_reraises_stop_hook_failure_without_primary_error(monkeypatch):
    class LoopWorker(BaseWorker):
        def loop(self):
            return False

        def stop(self):
            raise RuntimeError("stop boom")

    worker = LoopWorker()
    BaseWorker._worker_id = 0
    BaseWorker._worker = "tcp://127.0.0.1:8787"
    BaseWorker._insts = {0: worker}

    errors: list[str] = []
    monkeypatch.setattr(
        base_worker_mod.logger,
        "exception",
        lambda message, *args, **_kwargs: errors.append(
            str(message % args if args else message)
        ),
    )

    with pytest.raises(RuntimeError, match="stop boom"):
        BaseWorker.loop(poll_interval=0.0)

    assert errors == ["Worker stop hook raised inside service loop"]


def test_service_loop_preserves_primary_error_when_stop_hook_also_fails(monkeypatch):
    class LoopWorker(BaseWorker):
        def loop(self):
            raise ValueError("loop boom")

        def stop(self):
            raise RuntimeError("stop boom")

    worker = LoopWorker()
    BaseWorker._worker_id = 0
    BaseWorker._worker = "tcp://127.0.0.1:8787"
    BaseWorker._insts = {0: worker}

    errors: list[str] = []
    monkeypatch.setattr(
        base_worker_mod.logger,
        "exception",
        lambda message, *args, **_kwargs: errors.append(
            str(message % args if args else message)
        ),
    )

    with pytest.raises(ValueError, match="loop boom"):
        BaseWorker.loop(poll_interval=0.0)

    assert errors == [
        "Service loop failed: loop boom",
        "Worker stop hook raised inside service loop",
    ]


def test_service_loop_supports_async_worker_override():
    class AsyncLoopWorker(BaseWorker):
        async def loop(self):
            return False

    worker = AsyncLoopWorker()
    BaseWorker._worker_id = 0
    BaseWorker._worker = "tcp://127.0.0.1:8787"
    BaseWorker._insts = {0: worker}

    payload = BaseWorker.loop(poll_interval=0.0)

    assert payload["status"] == "stopped"


def test_baseworker_stop_swallows_break_loop_errors(monkeypatch):
    worker = DummyWorker()
    worker._worker_id = 5
    worker._worker = "tcp://127.0.0.1:8787"
    BaseWorker._service_active = {5: True}

    debug_calls: list[str] = []
    monkeypatch.setattr(BaseWorker, "break_loop", staticmethod(lambda: (_ for _ in ()).throw(RuntimeError("boom"))))
    monkeypatch.setattr(base_worker_mod.logger, "debug", lambda *_args, **_kwargs: debug_calls.append("debug"))

    worker.stop()

    assert debug_calls == ["debug"]


def test_service_loop_async_worker_uses_event_loop_fallback(monkeypatch):
    class FakeAwaitable:
        def __await__(self):
            if False:
                yield None
            return False

    class AsyncLoopWorker(BaseWorker):
        def loop(self):
            return FakeAwaitable()

    worker = AsyncLoopWorker()
    BaseWorker._worker_id = 0
    BaseWorker._worker = "tcp://127.0.0.1:8787"
    BaseWorker._insts = {0: worker}

    class FakeLoop:
        def __init__(self):
            self.closed = False
            self.awaited = []

        def run_until_complete(self, awaitable):
            self.awaited.append(awaitable)
            return False

        def close(self):
            self.closed = True

    fake_loop = FakeLoop()
    monkeypatch.setattr(base_worker_mod.asyncio, "run", lambda _awaitable: (_ for _ in ()).throw(RuntimeError("running loop")))
    monkeypatch.setattr(base_worker_mod.asyncio, "new_event_loop", lambda: fake_loop)

    payload = BaseWorker.loop(poll_interval=0.0)

    assert payload["status"] == "stopped"
    assert fake_loop.awaited
    assert fake_loop.closed is True
