"""Boundary contracts for worker payloads and lease durability failures."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from agi_node.agi_dispatcher import cli
from agi_node.agi_dispatcher import base_worker as worker_runtime


@pytest.mark.parametrize("token", ["", "a" * 31, "not-hexadecimal-token-at-all-12345"])
def test_invalid_lease_token_cannot_create_ownership_state(tmp_path, token):
    target = tmp_path / "worker"
    assert cli.acquire_remote_target_lease(target, token, "install") is False
    assert cli.remote_target_lease_owned(target, token) is False
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("failure", ["open", "fsync"])
def test_directory_sync_failure_is_best_effort_and_closes_opened_descriptor(
    tmp_path, monkeypatch, failure
):
    opened = []
    closed = []
    synced = []
    descriptor = 8721

    def open_directory(path, flags):
        assert Path(path) == tmp_path
        assert flags == cli.os.O_RDONLY
        if failure == "open":
            raise PermissionError("filesystem denies directory sync")
        opened.append(descriptor)
        return descriptor

    def sync(fd):
        synced.append(fd)
        raise OSError("filesystem does not support directory fsync")

    # Windows cannot open a directory with os.open. Model that boundary locally
    # so both failure stages are exercised without mutating the shared os module.
    monkeypatch.setattr(cli, "os", SimpleNamespace(
        O_RDONLY=cli.os.O_RDONLY, open=open_directory, fsync=sync, close=closed.append,
    ))
    cli._fsync_directory(tmp_path)
    assert closed == synced == opened
    assert opened == ([] if failure == "open" else [descriptor])


@pytest.mark.parametrize("running_loop", [False, True])
def test_worker_blocking_awaitable_propagates_original_exception(running_loop):
    error = ValueError("worker initialization failed")

    async def fail():
        await asyncio.sleep(0)
        raise error

    async def inside_running_loop():
        return worker_runtime._run_awaitable_blocking(fail())

    with pytest.raises(ValueError) as raised:
        if running_loop:
            asyncio.run(inside_running_loop())
        else:
            worker_runtime._run_awaitable_blocking(fail())
    assert raised.value is error


@pytest.mark.parametrize("worker_idx", [-1, "1", None, 2])
def test_worker_chunk_rejects_invalid_sender_slot(worker_idx):
    payload = {
        "__agi_worker_chunk__": True,
        "chunk": ["task"],
        "worker_idx": worker_idx,
        "total_workers": 2,
    }
    with pytest.raises(ValueError, match="Invalid worker_idx"):
        worker_runtime.BaseWorker._expand_chunk(payload, worker_id=0)


@pytest.mark.parametrize("receiver", [-1, "1"])
def test_worker_chunk_rejects_invalid_initialized_receiver(receiver):
    payload = {
        "__agi_worker_chunk__": True,
        "chunk": ["task"],
        "worker_idx": 0,
        "total_workers": 2,
    }
    with pytest.raises(ValueError, match="Invalid initialized worker_id"):
        worker_runtime.BaseWorker._expand_chunk(payload, worker_id=receiver)


@pytest.mark.parametrize(
    "root,subdir,message",
    [
        ("C:output", "data", "drive-relative"),
        ("root/../elsewhere", "data", "parent traversal"),
        ("root", "C:relative", "must be relative"),
        ("root", "C:/absolute", "must be relative"),
        ("root", "../escape", "parent traversal"),
    ],
)
def test_worker_output_path_rejects_ambiguous_or_escaping_inputs_before_creation(
    tmp_path, root, subdir, message
):
    worker = SimpleNamespace(env=SimpleNamespace(workflow_data_root=tmp_path))
    with pytest.raises(ValueError, match=message):
        worker_runtime.BaseWorker.prepare_output_dir(worker, root, subdir=subdir)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("raw_cap", [0, -2, "invalid", [], None])
def test_pool_capacity_falls_back_to_environment_after_invalid_app_override(
    monkeypatch, raw_cap
):
    from agi_node.agi_dispatcher import worker_pool_support as pool

    monkeypatch.setenv(pool.POOL_MAX_WORKERS_ENV, "3")
    assert pool._resolve_pool_cap({pool.POOL_MAX_WORKERS_ARG: raw_cap}) == 3


def test_pool_batch_reports_all_failed_items_after_running_siblings(
    monkeypatch, caplog
):
    from concurrent.futures import ThreadPoolExecutor
    from agi_node.agi_dispatcher import worker_pool_support as pool

    seen = []

    def work(item):
        seen.append(item)
        if item != "good":
            raise ValueError("invalid item " + item)
        return "completed"

    worker = SimpleNamespace(work_pool=work)
    monkeypatch.setattr(pool, "_POOL_RUNTIME_WORKER", worker)
    hooks = SimpleNamespace(family="ContractWorker", executor_kind="thread")
    items = ["bad-1", "bad-2", "good", "bad-3", "bad-4"]
    with ThreadPoolExecutor(max_workers=2) as executor:
        with pytest.raises(RuntimeError, match="failed for 4 of 5") as raised:
            pool._run_chunk(executor, worker, hooks, 7, items, width=2)
    assert sorted(seen) == sorted(items)
    assert "chunk #7" in str(raised.value)
    assert "..." in str(raised.value)
    for item in ("bad-1", "bad-2", "bad-3", "bad-4"):
        assert "invalid item " + item in caplog.text


def test_empty_pool_chunk_submits_no_work():
    from agi_node.agi_dispatcher import worker_pool_support as pool

    executor = SimpleNamespace(submit=lambda *a: pytest.fail("empty batch submitted"))
    assert pool._run_chunk(executor, object(), object(), 0, [], width=1) == []


def test_broken_pool_reports_chunk_and_preserves_original_cause():
    from concurrent.futures import BrokenExecutor, Future
    from agi_node.agi_dispatcher import worker_pool_support as pool

    error = BrokenExecutor("worker initialization failed")

    def submit(*args):
        future = Future()
        future.set_exception(error)
        return future

    with pytest.raises(
        RuntimeError, match="pool broke while running chunk #9"
    ) as raised:
        pool._run_chunk(
            SimpleNamespace(submit=submit),
            object(),
            SimpleNamespace(family="ContractWorker", executor_kind="process"),
            9,
            ["one", "two", "three", "four"],
            width=2,
        )
    assert raised.value.__cause__ is error
    assert "items:" in str(raised.value)


def test_abandon_pool_attempts_every_owned_process_even_when_cleanup_fails():
    from agi_node.agi_dispatcher import worker_pool_support as pool

    events = []

    def fail_terminate():
        events.append("first")
        raise OSError("process already exited")

    def fail_shutdown(**kwargs):
        events.append(kwargs)
        raise RuntimeError("executor broken")

    executor = SimpleNamespace(
        _processes={
            1: SimpleNamespace(terminate=fail_terminate),
            2: SimpleNamespace(terminate=lambda: events.append("second")),
        },
        shutdown=fail_shutdown,
    )
    pool._abandon_stuck_pool(executor)
    assert events == [{"wait": False, "cancel_futures": True}, "first", "second"]
