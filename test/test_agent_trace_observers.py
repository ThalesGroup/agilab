"""Post-durability trace observation must never change execution outcomes."""

import json
import threading
import time

import pytest

from agilab.agent_runtime import agent_trace as trace


def test_observer_runs_after_durable_append_outside_trace_lock(tmp_path, monkeypatch):
    seen = []
    fsynced = []
    original_fsync = trace.os.fsync

    def fsync(fd):
        original_fsync(fd)
        fsynced.append(fd)

    monkeypatch.setattr(trace.os, "fsync", fsync)

    def observer(event):
        assert fsynced
        assert trace.load_trace_events(tmp_path)[-1] == event
        with trace._event_file_lock(tmp_path / trace.EVENTS_FILENAME):
            seen.append(event)

    with trace.observe_trace_events(observer):
        store = trace.AgentTraceStore(tmp_path, run_id="post-durable")
        event = store.append("session_start", message="password=secret-example")
    assert seen == [event]
    assert "secret-example" not in event.message


def test_observer_failure_is_visible_but_durable_event_is_successful(tmp_path):
    def failed(_event):
        raise ValueError("secret-example")

    store = trace.AgentTraceStore(tmp_path, run_id="no-rollback", observers=(failed,))
    with pytest.warns(RuntimeWarning, match="durable event") as warning:
        result = store.append("session_end", status="pass")
    assert "secret-example" not in str(warning[0].message)
    assert result.status == "pass"
    assert trace.load_trace_events(tmp_path) == [result]
    assert store.observer_errors[-1]["sequence"] == 1
    assert store.observer_errors[-1]["error_type"] == "ValueError"


def test_observer_recursion_is_bounded_and_scope_is_reset(tmp_path):
    seen = []
    store = None

    def observer(event):
        seen.append(event.sequence)
        store.append("tool_output", message="nested observer diagnostic")

    with trace.observe_trace_events(observer):
        store = trace.AgentTraceStore(tmp_path / "observed", run_id="observed")
        store.append("session_start")
    trace.AgentTraceStore(tmp_path / "ordinary", run_id="ordinary").append(
        "session_start"
    )
    assert seen == [1]
    assert len(trace.load_trace_events(tmp_path / "observed")) == 2


@pytest.mark.parametrize(
    "events", [("session_start", "command_start"), ("tool_start", "tool_done")]
)
@pytest.mark.parametrize("handle_kind", ["same", "second", "alias"])
def test_obs_regression_concurrent_dispatch_follows_durable_sequence(
    tmp_path, events, handle_kind, request
):
    import threading

    entered = threading.Event()
    release = threading.Event()
    seen = []
    failures = []

    def observer(event):
        if event.sequence == 1:
            entered.set()
            assert release.wait(3)
        with trace._event_file_lock(store.events_path):
            seen.append(event.sequence)

    store = trace.AgentTraceStore(tmp_path, run_id="ordered", observers=(observer,))

    peer_root = tmp_path
    if handle_kind == "alias":
        peer_root = tmp_path / "trace-alias"
        peer_root.symlink_to(tmp_path, target_is_directory=True)
    peer = (
        store
        if handle_kind == "same"
        else trace.AgentTraceStore(peer_root, run_id="ordered", observers=(observer,))
    )
    assert peer.initialize()["run_id"] == store.initialize()["run_id"]

    def append(handle, event):
        try:
            handle.append(event)
        except BaseException as exc:
            failures.append(exc)

    first = threading.Thread(target=append, args=(store, events[0]))
    second = threading.Thread(target=append, args=(peer, events[1]))
    first.start()
    try:
        assert entered.wait(2)
        second.start()
        second.join(timeout=2)
        assert not second.is_alive()
        assert [e.sequence for e in trace.load_trace_events(tmp_path)] == [1, 2]
    finally:
        release.set()
        first.join(timeout=3)
        if second.ident is not None:
            second.join(timeout=3)
    assert not first.is_alive() and not second.is_alive()
    assert not failures
    durable = [e.sequence for e in trace.load_trace_events(tmp_path)]
    request.node.user_properties.extend(
        [("durable_sequence", str(durable)), ("observed_sequence", str(seen))]
    )
    assert store.close_observers(timeout=0.2)
    assert peer.close_observers(timeout=0.2)
    assert seen == durable == [1, 2]


@pytest.mark.parametrize("separate_handle", [False, True])
def test_obs_regression_dispatch_queue_close_and_recursion_are_bounded(
    tmp_path, separate_handle
):
    import threading
    import time

    entered, release = threading.Event(), threading.Event()
    failures = []

    class Observer:
        def __call__(self, event):
            if event.sequence == 1:
                entered.set()
                assert release.wait(4)

        def observation_failed(self, *, sequence, error_type):
            with trace._event_file_lock(store.events_path):
                failures.append((sequence, error_type))

    observer = Observer()
    store = trace.AgentTraceStore(tmp_path, run_id="bounded", observers=(observer,))
    peer = (
        trace.AgentTraceStore(tmp_path, run_id="bounded", observers=(observer,))
        if separate_handle
        else store
    )
    first = threading.Thread(target=lambda: store.append("session_start"))
    first.start()
    try:
        assert entered.wait(2)
        with pytest.warns(RuntimeWarning, match="ObserverQueueFull"):
            for _ in range(trace.MAX_OBSERVER_QUEUE + 2):
                peer.append("tool_output")
        assert len(store._observer_queue) == trace.MAX_OBSERVER_QUEUE
        started = time.monotonic()
        with pytest.warns(RuntimeWarning, match="ObserverDrainTimeout"):
            assert not store.close_observers(timeout=0.02)
        assert time.monotonic() - started < 0.2
    finally:
        release.set()
        first.join(timeout=4)
    assert not first.is_alive()
    assert store._observer_idle.is_set()
    assert not store._observer_queue
    assert any(kind == "ObserverQueueFull" for _, kind in failures)
    with pytest.warns(RuntimeWarning, match="ObserverDispatchClosed"):
        final = store.append("session_end", status="pass")
    assert final.status == "pass"
    assert trace.load_trace_events(tmp_path)[-1] == final
    assert not peer.close_observers(timeout=0.2)


@pytest.mark.parametrize("separate_handle", [False, True])
def test_obs_regression_direct_recursive_observer_cannot_wait_for_itself(
    tmp_path, separate_handle
):
    seen = []
    store = None

    def observer(event):
        seen.append(event.sequence)
        peer.append("tool_output")
        assert not peer.flush_observers(timeout=0.01)

    store = trace.AgentTraceStore(tmp_path, run_id="recursive", observers=(observer,))
    peer = (
        trace.AgentTraceStore(tmp_path, run_id="recursive", observers=(observer,))
        if separate_handle
        else store
    )
    store.append("session_start")
    assert seen == [1]
    assert [e.sequence for e in trace.load_trace_events(tmp_path)] == [1, 2]
    assert store.close_observers(timeout=0.01)
    assert peer.close_observers(timeout=0.01)


def test_obs_regression_close_one_handle_then_reopen_and_repair(tmp_path):
    seen = []

    def observer(event):
        seen.append(event.sequence)

    first = trace.AgentTraceStore(tmp_path, run_id="reopen", observers=(observer,))
    peer = trace.AgentTraceStore(tmp_path, run_id="reopen", observers=(observer,))
    first.append("session_start")
    dispatch = first._observer_dispatch
    assert first.close_observers(timeout=0.2)
    peer.append("command_start")
    assert peer._observer_dispatch is dispatch
    assert peer.close_observers(timeout=0.2)
    assert dispatch.key not in trace._OBSERVER_DISPATCHES
    with first.events_path.open("ab") as handle:
        handle.write(b'{"interrupted":')
    reopened = trace.AgentTraceStore(tmp_path, run_id="reopen", observers=(observer,))
    assert reopened._observer_dispatch is not dispatch
    assert reopened.initialize()["run_id"] == "reopen"
    reopened.append("command_done", status="pass")
    terminal = reopened.append("session_end", status="pass")
    assert reopened.close_observers(timeout=0.2)
    assert (
        seen == [e.sequence for e in trace.load_trace_events(tmp_path)] == [1, 2, 3, 4]
    )
    assert terminal.status == "pass"
    assert not reopened.observer_errors
    assert dispatch.key not in trace._OBSERVER_DISPATCHES


def test_obs_regression_shared_dispatch_errors_belong_to_appending_handle(tmp_path):
    import threading

    entered, release = threading.Event(), threading.Event()
    errors = []

    def observer(event):
        if event.sequence == 1:
            entered.set()
            assert release.wait(3)
        else:
            raise ValueError("private callback failure")

    first = trace.AgentTraceStore(tmp_path, run_id="origin", observers=(observer,))
    peer = trace.AgentTraceStore(tmp_path, run_id="origin", observers=(observer,))

    def append():
        try:
            first.append("session_start")
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=append)
    with pytest.warns(RuntimeWarning, match="ValueError"):
        worker.start()
        try:
            assert entered.wait(2)
            durable = peer.append("command_start", status="pass")
            assert durable.sequence == 2
        finally:
            release.set()
            worker.join(timeout=3)
    assert not worker.is_alive() and not errors
    assert not first.observer_errors
    assert list(peer.observer_errors) == [{"sequence": 2, "error_type": "ValueError"}]
    assert first.close_observers(timeout=0.2)
    assert not peer.close_observers(timeout=0.2)
    assert trace.load_trace_events(tmp_path)[-1].status == "pass"
    recovered = trace.AgentTraceStore(
        tmp_path, run_id="origin", observers=(lambda e: None,)
    )
    recovered.append("session_end", status="pass")
    assert recovered.close_observers(timeout=0.2)


def test_obs_regression_reopen_while_closed_handle_still_drains(tmp_path):
    import threading

    entered, release = threading.Event(), threading.Event()
    seen, errors = [], []

    def observer(event):
        if event.sequence == 1:
            entered.set()
            assert release.wait(3)
        seen.append(event.sequence)

    first = trace.AgentTraceStore(tmp_path, run_id="closing", observers=(observer,))

    def append():
        try:
            first.append("session_start")
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=append)
    worker.start()
    try:
        assert entered.wait(2)
        with pytest.warns(RuntimeWarning, match="ObserverDrainTimeout"):
            assert not first.close_observers(timeout=0.01)
        reopened = trace.AgentTraceStore(
            tmp_path, run_id="closing", observers=(observer,)
        )
        assert reopened._observer_dispatch is first._observer_dispatch
        reopened.append("command_start")
        assert seen == []
    finally:
        release.set()
        worker.join(timeout=3)
    assert not worker.is_alive() and not errors
    assert seen == [1, 2]
    assert reopened.close_observers(timeout=0.2)
    assert first._observer_dispatch.key not in trace._OBSERVER_DISPATCHES


def test_obs_regression_unrelated_trace_does_not_wait_for_shared_dispatch(tmp_path):
    import threading

    entered, release = threading.Event(), threading.Event()
    seen, errors = [], []

    def observer(event):
        if event.run_id == "blocked":
            entered.set()
            assert release.wait(3)
        seen.append(event.run_id)

    first = trace.AgentTraceStore(
        tmp_path / "first", run_id="blocked", observers=(observer,)
    )
    other = trace.AgentTraceStore(
        tmp_path / "other", run_id="independent", observers=(observer,)
    )

    def append():
        try:
            first.append("session_start")
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=append)
    worker.start()
    try:
        assert entered.wait(2)
        other.append("session_start", status="pass")
        assert seen == ["independent"]
        assert other.close_observers(timeout=0.2)
    finally:
        release.set()
        worker.join(timeout=3)
    assert not worker.is_alive() and not errors
    assert first.close_observers(timeout=0.2)
    assert seen == ["independent", "blocked"]


def test_obs_regression_dispatch_registry_releases_abandoned_handles(tmp_path):
    import gc
    import weakref

    store = trace.AgentTraceStore(
        tmp_path, run_id="abandoned", observers=(lambda e: None,)
    )
    store.append("session_start")
    key = store._observer_dispatch.key
    handle_ref, dispatch_ref = weakref.ref(store), weakref.ref(store._observer_dispatch)
    del store
    gc.collect()
    assert handle_ref() is None and dispatch_ref() is None
    assert key not in trace._OBSERVER_DISPATCHES
    reopened = trace.AgentTraceStore(
        tmp_path, run_id="abandoned", observers=(lambda e: None,)
    )
    reopened.append("session_end", status="pass")
    assert reopened.close_observers(timeout=0.2)


@pytest.mark.parametrize("boundary", ["before_accounting", "failure_sink"])
@pytest.mark.parametrize("failure_kind", ["budget", "callback"])
def test_metadata_completion_waits_for_rejected_failure_delivery(
    tmp_path, monkeypatch, boundary, failure_kind, request
):
    import threading
    import time

    entered, release = threading.Event(), threading.Event()
    failing, finish_failure = threading.Event(), threading.Event()
    seen, failures, driver_errors = [], [], []
    pending_count = trace.MAX_OBSERVER_QUEUE if failure_kind == "budget" else 1
    rejected_sequence = pending_count + 1
    expected_error = (
        "ObserverDrainBudgetExceeded" if failure_kind == "budget" else "ValueError"
    )

    class Observer:
        def __call__(self, event):
            if event.sequence == 1:
                entered.set()
                assert release.wait(5)
            if failure_kind == "callback" and event.sequence == rejected_sequence:
                raise ValueError("bounded callback failure")
            seen.append(event.sequence)

        def observation_failed(self, *, sequence, error_type):
            if error_type == expected_error:
                if boundary == "failure_sink":
                    failing.set()
                    assert finish_failure.wait(5)
                failures.append((sequence, error_type))

    observer = Observer()
    first = trace.AgentTraceStore(tmp_path, run_id="completion", observers=(observer,))
    peer = trace.AgentTraceStore(tmp_path, run_id="completion", observers=(observer,))
    original_failure = peer._observer_failure

    def failure(record, error_type, observer=None):
        if boundary == "before_accounting" and error_type == expected_error:
            failing.set()
            assert finish_failure.wait(5)
        original_failure(record, error_type, observer)

    monkeypatch.setattr(peer, "_observer_failure", failure)

    def append():
        try:
            first.append("session_start")
        except BaseException as exc:
            driver_errors.append(exc)

    worker = threading.Thread(target=append)
    worker.start()
    with pytest.warns(RuntimeWarning, match=expected_error):
        try:
            assert entered.wait(2)
            for _ in range(pending_count):
                peer.append("tool_output")
            release.set()
            assert failing.wait(2)
            started = time.monotonic()
            completion = [
                peer.flush_observers(0.02),
                peer.close_observers(0.02),
                first.close_observers(0.02),
            ]
            reopened = trace.AgentTraceStore(
                tmp_path, run_id="completion", observers=(observer,)
            )
            same_dispatch = reopened._observer_dispatch is first._observer_dispatch
            completion.extend(
                [reopened.flush_observers(0.02), reopened.close_observers(0.02)]
            )
            elapsed = time.monotonic() - started
            ownership_released = first._observer_dispatch_lock.acquire(blocking=False)
            if ownership_released:
                first._observer_dispatch_lock.release()
            failure_count_while_pending = len(failures)
        finally:
            release.set()
            finish_failure.set()
            worker.join(timeout=5)
    assert not worker.is_alive() and not driver_errors
    assert completion == [False] * 5
    assert same_dispatch and not ownership_released
    assert elapsed < 0.5
    assert failure_count_while_pending == 0
    assert failures == [(rejected_sequence, expected_error)]
    assert list(peer.observer_errors) == [
        {"sequence": rejected_sequence, "error_type": expected_error}
    ]
    assert not first.observer_errors
    assert first.flush_observers(0.2) and not peer.close_observers(0.2)
    assert seen == list(range(1, rejected_sequence))
    assert [e.sequence for e in trace.load_trace_events(tmp_path)] == list(
        range(1, rejected_sequence + 1)
    )
    recovered = trace.AgentTraceStore(
        tmp_path, run_id="completion", observers=(observer,)
    )
    terminal = recovered.append("session_end", status="pass")
    assert recovered.close_observers(0.2) and not recovered.observer_errors
    assert terminal.status == trace.load_trace_events(tmp_path)[-1].status == "pass"
    request.node.user_properties.extend(
        [
            ("production_queue_limit", trace.MAX_OBSERVER_QUEUE),
            ("rejected_sequence", rejected_sequence),
            ("pending_completion_results", str(completion)),
            ("failure_notifications", len(failures)),
            ("threads_remaining", int(worker.is_alive())),
        ]
    )


def test_metadata_origin_readiness_timeout_releases_and_recovers(tmp_path, monkeypatch):
    import threading

    monkeypatch.setattr(trace, "LOCK_TIMEOUT_SECONDS", 0.05)
    entered, release = threading.Event(), threading.Event()
    queued, exit_writer = threading.Event(), threading.Event()
    seen, driver_errors = [], []

    def observer(event):
        if event.sequence == 1:
            entered.set()
            assert release.wait(2)
        seen.append(event.sequence)

    first = trace.AgentTraceStore(
        tmp_path, run_id="readiness-recovery", observers=(observer,)
    )
    peer = trace.AgentTraceStore(tmp_path, run_id=first.run_id, observers=(observer,))
    first.initialize()
    original_queue = peer._queue_observer

    def queue(record):
        result = original_queue(record)
        queued.set()
        assert exit_writer.wait(2)
        return result

    monkeypatch.setattr(peer, "_queue_observer", queue)

    def append(store, event):
        try:
            store.append(event)
        except BaseException as exc:
            driver_errors.append(exc)

    drainer = threading.Thread(target=append, args=(first, "session_start"))
    writer = threading.Thread(target=append, args=(peer, "command_start"))
    drainer.start()
    try:
        assert entered.wait(1)
        writer.start()
        assert queued.wait(1)
        release.set()
        drainer.join(timeout=1)
        assert not drainer.is_alive() and writer.is_alive()
        assert seen == [1]
        assert not first.flush_observers(0.01)
        assert not peer.close_observers(0.01)
        assert not first.close_observers(0.01)
        reopened = trace.AgentTraceStore(
            tmp_path, run_id=first.run_id, observers=(observer,)
        )
        assert reopened._observer_dispatch is first._observer_dispatch
        assert not reopened.flush_observers(0.01)
    finally:
        release.set()
        exit_writer.set()
        drainer.join(timeout=2)
        if writer.ident is not None:
            writer.join(timeout=2)
    assert not drainer.is_alive() and not writer.is_alive() and not driver_errors
    assert seen == [1, 2]
    terminal = reopened.append("session_end", status="pass")
    assert reopened.close_observers(0.05)
    assert seen == [1, 2, 3] and terminal.status == "pass"
    assert (
        not first.observer_errors
        and not peer.observer_errors
        and not reopened.observer_errors
    )


@pytest.mark.parametrize("handle_kind", ["same", "second", "alias"])
def test_metadata_callback_waits_for_origin_file_lock_exit(
    tmp_path, monkeypatch, handle_kind, request
):
    import threading

    entered, release = threading.Event(), threading.Event()
    queued, exit_writer = threading.Event(), threading.Event()
    second_started = threading.Event()
    seen, lock_available, driver_errors = [], [], []

    def observer(event):
        if event.sequence == 1:
            entered.set()
            assert release.wait(5)
        if event.sequence == 2:
            second_started.set()
            with first.events_path.with_name(first.events_path.name + ".lock").open(
                "a+b"
            ) as handle:
                available = trace._try_lock_handle(handle)
                lock_available.append(available)
                if available:
                    trace._unlock_handle(handle)
            with trace._event_file_lock(first.events_path):
                assert trace.load_trace_events(tmp_path)[-1].sequence == 2
            peer.append("tool_output", message="callback re-entry")
        seen.append(event.sequence)

    first = trace.AgentTraceStore(tmp_path, run_id="origin-lock", observers=(observer,))
    peer_root = tmp_path
    if handle_kind == "alias":
        peer_root = tmp_path / "trace-alias"
        peer_root.symlink_to(tmp_path, target_is_directory=True)
    peer = (
        first
        if handle_kind == "same"
        else trace.AgentTraceStore(
            peer_root, run_id="origin-lock", observers=(observer,)
        )
    )
    first.initialize()
    original_queue = peer._queue_observer

    def queue(record):
        result = original_queue(record)
        if record.sequence == 2:
            queued.set()
            assert exit_writer.wait(5)
        return result

    monkeypatch.setattr(peer, "_queue_observer", queue)

    def append(store, event):
        try:
            store.append(event)
        except BaseException as exc:
            driver_errors.append(exc)

    writer = threading.Thread(target=append, args=(peer, "command_start"))
    drainer = threading.Thread(target=append, args=(first, "session_start"))
    drainer.start()
    try:
        assert entered.wait(2)
        writer.start()
        assert queued.wait(2)
        release.set()
        callback_started_before_origin_exit = second_started.wait(0.1)
    finally:
        exit_writer.set()
        release.set()
        drainer.join(timeout=5)
        if writer.ident is not None:
            writer.join(timeout=5)
    assert not writer.is_alive() and not drainer.is_alive() and not driver_errors
    assert not callback_started_before_origin_exit
    assert lock_available == [True]
    assert seen == [1, 2]
    assert [e.sequence for e in trace.load_trace_events(tmp_path)] == [1, 2, 3]
    terminal = peer.append("session_end", status="pass")
    assert first.close_observers(0.2) and peer.close_observers(0.2)
    assert terminal.status == "pass"
    assert not first.observer_errors and not peer.observer_errors
    request.node.user_properties.extend(
        [
            (
                "callback_started_before_origin_exit",
                callback_started_before_origin_exit,
            ),
            ("origin_file_lock_available", str(lock_available)),
            ("durable_sequence", "[1, 2, 3, 4]"),
            ("callback_sequence", str(seen)),
            ("threads_remaining", int(writer.is_alive()) + int(drainer.is_alive())),
        ]
    )


@pytest.mark.parametrize("operation", ["flush", "close"])
@pytest.mark.parametrize("sink_action", ["blocked", "recursive", "raises"])
def test_metadata_timeout_notification_is_bounded_coalesced_and_tracked(
    tmp_path, request, operation, sink_action
):
    callback_entered = threading.Event()
    callback_finished = threading.Event()
    callback_release = threading.Event()
    sink_entered = threading.Event()
    sink_release = threading.Event()
    first_done = threading.Event()
    repeats_done = threading.Event()
    errors, seen, notifications, sink_threads, returns = [], [], [], [], []
    callers = []
    repeat_count = 0
    count_lock = threading.Lock()

    class Observer:
        def __call__(self, event):
            if event.sequence == 1:
                callback_entered.set()
                if not callback_release.wait(5):
                    errors.append("ordinary callback was not released")
            seen.append(event.sequence)
            callback_finished.set()

        def observation_failed(self, *, sequence, error_type):
            sink_threads.append(threading.current_thread())
            notifications.append((sequence, error_type))
            try:
                acquired = store._observer_queue_lock.acquire(blocking=False)
                if acquired:
                    store._observer_queue_lock.release()
                assert acquired, "failure sink holds queue lock"
                assert trace._OBSERVER_ACTIVE.get()
                with trace._event_file_lock(store.events_path):
                    assert trace.load_trace_events(tmp_path)[0].status == "pass"
                sink_entered.set()
                assert sink_release.wait(5), "failure sink was not released"
                if sink_action == "recursive":
                    store.append("tool_output", status="pass")
                    assert not peer.flush_observers(0.01)
                    assert not store.close_observers(0.01)
            except BaseException as exc:
                errors.append(repr(exc))
            if sink_action == "raises":
                raise ValueError("private failure sink detail")

    observer = Observer()
    store = trace.AgentTraceStore(
        tmp_path, run_id="timeout-owned", observers=(observer,)
    )
    peer = trace.AgentTraceStore(
        tmp_path, run_id="timeout-owned", observers=(observer,)
    )
    dispatch = store._observer_dispatch
    reopened = None

    def append():
        try:
            store.append("session_start", status="pass")
        except BaseException as exc:
            errors.append(repr(exc))

    def invoke(handle, action, *, first=False):
        nonlocal repeat_count
        try:
            started = time.monotonic()
            result = getattr(handle, action + "_observers")(0.01 if first else 0.005)
            returns.append((result, time.monotonic() - started))
        except BaseException as exc:
            errors.append(repr(exc))
        finally:
            if first:
                first_done.set()
            else:
                with count_lock:
                    repeat_count += 1
                    if repeat_count == 4:
                        repeats_done.set()

    appender = threading.Thread(target=append, name="timeout-test-append")
    first = threading.Thread(
        target=invoke,
        args=(store, operation),
        kwargs={"first": True},
        name="timeout-test-first-caller",
    )
    appender.start()
    snapshot = {}
    try:
        assert callback_entered.wait(2)
        first.start()
        assert sink_entered.wait(2)
        snapshot["first_returned_within_120ms"] = first_done.wait(0.12)
        for index in range(4):
            caller = threading.Thread(
                target=invoke,
                args=(
                    store if index % 2 == 0 else peer,
                    "flush" if index % 2 == 0 else "close",
                ),
                name=f"timeout-test-repeat-{index}",
            )
            callers.append(caller)
            caller.start()
        snapshot["repeated_callers_returned_within_120ms"] = repeats_done.wait(0.12)
        snapshot["notifications_while_held"] = list(notifications)
        snapshot["sink_on_timeout_caller"] = any(
            thread in [first, *callers] for thread in sink_threads
        )
        callback_release.set()
        assert callback_finished.wait(2)
        snapshot["idle_before_sink_release"] = dispatch.idle.is_set()
        snapshot["unfinished_before_sink_release"] = len(dispatch.unfinished)
        snapshot["notification_tracked"] = (
            dispatch.timeout_notification in dispatch.unfinished
        )
        snapshot["peer_flush_before_sink_release"] = peer.flush_observers(0)
        snapshot["peer_close_before_sink_release"] = peer.close_observers(0)
        snapshot["origin_close_before_sink_release"] = store.close_observers(0)
        reopened = trace.AgentTraceStore(
            tmp_path, run_id="timeout-owned", observers=(observer,)
        )
        snapshot["reopened_same_dispatch"] = reopened._observer_dispatch is dispatch
        snapshot["reopened_flush_before_sink_release"] = reopened.flush_observers(0)
    finally:
        callback_release.set()
        sink_release.set()
        for worker in dict.fromkeys([appender, first, *callers, *sink_threads]):
            if worker.ident is not None:
                worker.join(timeout=3)
        snapshot["threads_remaining"] = [
            worker.name
            for worker in [appender, first, *callers, *sink_threads]
            if worker.is_alive()
        ]
        store.close_observers(0.2)
        peer.close_observers(0.2)
        if reopened is not None:
            reopened.close_observers(0.2)
        request.node.user_properties.append(
            ("timeout_lifetime", json.dumps(snapshot, sort_keys=True))
        )

    assert not errors, errors
    assert not snapshot["threads_remaining"]
    assert snapshot["first_returned_within_120ms"], snapshot
    assert snapshot["repeated_callers_returned_within_120ms"], snapshot
    assert not snapshot["sink_on_timeout_caller"], snapshot
    assert snapshot["notifications_while_held"] == [(1, "ObserverDrainTimeout")]
    assert not snapshot["idle_before_sink_release"]
    assert snapshot["unfinished_before_sink_release"] >= 1
    assert snapshot["notification_tracked"]
    assert not snapshot["peer_flush_before_sink_release"]
    assert not snapshot["peer_close_before_sink_release"]
    assert not snapshot["origin_close_before_sink_release"]
    assert snapshot["reopened_same_dispatch"]
    assert not snapshot["reopened_flush_before_sink_release"]
    assert len(returns) == 5 and all(
        result is False and elapsed < 0.12 for result, elapsed in returns
    )
    assert list(store.observer_errors) == [
        {"sequence": 1, "error_type": "ObserverDrainTimeout"}
    ]
    assert not peer.observer_errors
    assert seen == [1]
    assert all(event.status == "pass" for event in trace.load_trace_events(tmp_path))
    assert dispatch.idle.is_set() and not dispatch.unfinished
    assert dispatch.key not in trace._OBSERVER_DISPATCHES
    recovered = trace.AgentTraceStore(
        tmp_path, run_id="timeout-owned", observers=(observer,)
    )
    assert recovered._observer_dispatch is not dispatch
    terminal = recovered.append("session_end", status="pass")
    assert recovered.close_observers(0.2)
    assert seen == [1, terminal.sequence]
    assert not store.flush_observers(0)


def test_metadata_timeout_coalesces_delivered_record_and_keeps_origin_errors(tmp_path):
    release = [threading.Event(), threading.Event()]
    entered = [threading.Event(), threading.Event()]
    notified = [threading.Event(), threading.Event()]
    notifications, sink_threads, seen, errors = [], [], [], []

    class Observer:
        def __call__(self, event):
            entered[event.sequence - 1].set()
            if not release[event.sequence - 1].wait(5):
                errors.append("callback was not released")
            seen.append(event.sequence)

        def observation_failed(self, *, sequence, error_type):
            sink_threads.append(threading.current_thread())
            notifications.append((sequence, error_type))
            notified[sequence - 1].set()

    observer = Observer()
    store = trace.AgentTraceStore(
        tmp_path, run_id="timeout-origins", observers=(observer,)
    )
    peer = trace.AgentTraceStore(
        tmp_path, run_id="timeout-origins", observers=(observer,)
    )

    def append():
        try:
            store.append("session_start", status="pass")
        except BaseException as exc:
            errors.append(repr(exc))

    worker = threading.Thread(target=append)
    worker.start()
    try:
        assert entered[0].wait(2)
        peer.append("command_start", status="pass")
        with pytest.warns(RuntimeWarning, match="ObserverDrainTimeout"):
            assert not peer.flush_observers(0.01)
        assert notified[0].wait(2)
        for thread in list(sink_threads):
            thread.join(timeout=2)
        for _ in range(8):
            assert not peer.flush_observers(0)
        assert notifications == [(1, "ObserverDrainTimeout")]
        assert len(store._observer_dispatch.unfinished) == 2
        release[0].set()
        assert entered[1].wait(2)
        with pytest.warns(RuntimeWarning, match="ObserverDrainTimeout"):
            assert not store.flush_observers(0.01)
        assert notified[1].wait(2)
        for thread in list(sink_threads):
            thread.join(timeout=2)
        assert notifications == [
            (1, "ObserverDrainTimeout"),
            (2, "ObserverDrainTimeout"),
        ]
    finally:
        for barrier in release:
            barrier.set()
        worker.join(timeout=3)
        for thread in sink_threads:
            thread.join(timeout=3)
        store.close_observers(0.2)
        peer.close_observers(0.2)
    assert not errors and not worker.is_alive()
    assert all(not thread.is_alive() for thread in sink_threads)
    assert seen == [1, 2]
    assert list(store.observer_errors) == [
        {"sequence": 1, "error_type": "ObserverDrainTimeout"}
    ]
    assert list(peer.observer_errors) == [
        {"sequence": 2, "error_type": "ObserverDrainTimeout"}
    ]
    assert not store._observer_dispatch.unfinished


def test_metadata_timeout_retries_owned_notification_after_thread_start_failure(
    tmp_path, monkeypatch
):
    entered, release = threading.Event(), threading.Event()
    delivered = threading.Event()
    import gc
    import weakref

    notifications, errors, sink_threads, attempts = [], [], [], []

    class Observer:
        def __call__(self, _event):
            entered.set()
            if not release.wait(5):
                errors.append("callback was not released")

        def observation_failed(self, *, sequence, error_type):
            sink_threads.append(threading.current_thread())
            notifications.append((sequence, error_type))
            delivered.set()

    observer = Observer()
    store = trace.AgentTraceStore(
        tmp_path, run_id="timeout-start-retry", observers=(observer,)
    )
    peer = trace.AgentTraceStore(tmp_path, run_id=store.run_id, observers=(observer,))

    def append():
        try:
            store.append("session_start", status="pass")
        except BaseException as exc:
            errors.append(repr(exc))

    worker = threading.Thread(target=append)
    worker.start()
    original_start = threading.Thread.start

    def start(thread):
        if thread.name == "agilab-trace-timeout":
            attempts.append(thread.name)
            if len(attempts) == 1:
                raise RuntimeError("controlled thread allocation failure")
        return original_start(thread)

    try:
        assert entered.wait(2)
        monkeypatch.setattr(threading.Thread, "start", start)
        with pytest.warns(RuntimeWarning, match="ObserverDrainTimeout"):
            assert not store.flush_observers(0.01)
        assert not delivered.is_set()
        release.set()
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert not store._observer_idle.is_set()
        assert len(store._observer_dispatch.unfinished) == 1
        store_ref = weakref.ref(store)
        dispatch_ref = weakref.ref(store._observer_dispatch)
        del store, peer
        gc.collect()
        assert dispatch_ref() is not None
        store = store_ref()
        peer = trace.AgentTraceStore(
            tmp_path, run_id="timeout-start-retry", observers=(observer,)
        )
        assert peer._observer_dispatch is dispatch_ref()
        assert not peer.flush_observers(0)
        assert delivered.wait(2)
    finally:
        release.set()
        worker.join(timeout=3)
        for thread in sink_threads:
            thread.join(timeout=3)
        store.close_observers(0.2)
        peer.close_observers(0.2)
    assert len(attempts) == 2
    assert notifications == [(1, "ObserverDrainTimeout")]
    assert not errors and all(not thread.is_alive() for thread in sink_threads)
    assert store._observer_idle.is_set() and not store._observer_dispatch.unfinished
    assert not store.flush_observers(0)
    assert peer.flush_observers(0)
