from __future__ import annotations

import pickle
from pathlib import Path
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agi_node.agi_dispatcher import BaseWorker

from agi_env.agi_logger import AgiLogger

logger = AgiLogger.get_logger(__name__)

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
    BaseWorker._insts = {}
    BaseWorker._env = None
    BaseWorker.env = None


def test_baseworker_do_works_executes_tasks():
    dummy = DummyWorker()
    with patch.object(dummy, "works", return_value=None) as mocked:
        BaseWorker._do_works({}, {})
    mocked.assert_called_once()


def test_prepare_output_dir_creates_directory(tmp_path):
    worker = DummyWorker()
    target = worker.prepare_output_dir(tmp_path, subdir="payload", attribute="custom_attr", clean=True)

    assert target.exists()
    assert target.name == "payload"
    assert worker.custom_attr == target


def test_setup_args_requires_args():
    worker = DummyWorker()
    with pytest.raises(ValueError):
        worker.setup_args(None)


def test_setup_args_applies_defaults_and_creates_output(tmp_path):
    class ConfigWorker(BaseWorker):
        args_ensure_defaults = staticmethod(lambda args, env=None: SimpleNamespace(**{**vars(args), "extra": "value"}))
        managed_pc_path_fields = ("data_path",)

    worker = ConfigWorker()
    args = SimpleNamespace(data_path=tmp_path / "data")

    processed = worker.setup_args(
        args,
        output_field="data_path",
        output_subdir="frames",
        output_attr="output_dir",
    )

    assert processed.extra == "value"
    assert worker.output_dir.exists()
    assert worker.output_dir.name == "frames"


def test_remap_managed_pc_path_when_managed():
    home = Path.home()
    sample = home / "dataset" / "file.csv"
    env = SimpleNamespace(
        _is_managed_pc=True,
        agi_share_path=Path("clustershare"),
        agi_share_path_abs=Path.home() / "clustershare",
    )

    remapped = BaseWorker._remap_managed_pc_path(sample, env=env)

    expected_root = home / BaseWorker.managed_pc_home_suffix
    assert str(remapped).startswith(str(expected_root))


def test_apply_managed_pc_path_overrides():
    class OverrideWorker(BaseWorker):
        managed_pc_path_fields = ("payload",)

    env = SimpleNamespace(
        _is_managed_pc=True,
        agi_share_path=Path("clustershare"),
        agi_share_path_abs=Path.home() / "clustershare",
    )
    path = Path.home() / "payload"
    args = SimpleNamespace(payload=path)

    result = OverrideWorker._apply_managed_pc_path_overrides(args, env=env)

    assert isinstance(result.payload, Path)
    assert str(result.payload).startswith(str(Path.home() / OverrideWorker.managed_pc_home_suffix))


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
    task_file = pending / "000001-batch-1-000-worker.task.pkl"
    with open(task_file, "wb") as stream:
        pickle.dump(payload, stream, protocol=pickle.HIGHEST_PROTOCOL)

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
