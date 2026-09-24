"""Ownership and failure boundaries for background process cleanup (no real signals)."""
from types import SimpleNamespace
from unittest.mock import Mock

import psutil
import pytest

from agi_cluster.agi_distributor.runtime import runtime_distribution_support as runtime


def process(pid, *, username="operator", created=100, environ=None):
    return SimpleNamespace(
        pid=pid, info={"status": "running"}, username=Mock(return_value=username),
        create_time=Mock(return_value=created), environ=Mock(return_value=environ or {}),
        terminate=Mock(), kill=Mock(), poll=Mock(return_value=None),
    )


@pytest.fixture
def fake_os(monkeypatch):
    os = SimpleNamespace(getpid=lambda: 1, getpgid=Mock(return_value=42),
                         getpgrp=lambda: 999, killpg=Mock())
    monkeypatch.setattr(runtime, "os", os)
    return os


@pytest.fixture
def fake_psutil(monkeypatch):
    proxy = SimpleNamespace(
        Process=Mock(return_value=process(1)), process_iter=Mock(return_value=[]),
        wait_procs=Mock(return_value=([], [])), STATUS_ZOMBIE=psutil.STATUS_ZOMBIE,
        AccessDenied=psutil.AccessDenied, NoSuchProcess=psutil.NoSuchProcess,
        ZombieProcess=psutil.ZombieProcess,
    )
    monkeypatch.setattr(runtime, "psutil", proxy)
    return proxy


def test_token_scan_rejects_old_other_user_and_unreadable_identity(fake_os, fake_psutil):
    token_key = runtime.background_jobs_support.BACKGROUND_JOB_TOKEN_ENV
    own = process(2, environ={token_key: "owned"})
    old = process(3, created=98, environ={token_key: "owned"})
    other = process(4, username="other", environ={token_key: "owned"})
    identity_denied = process(5)
    identity_denied.username.side_effect = psutil.AccessDenied(5)
    uncertain = process(6)
    uncertain.environ.side_effect = psutil.AccessDenied(6)
    gone = process(7)
    gone.environ.side_effect = psutil.NoSuchProcess(7)
    unrelated = process(8)
    fake_psutil.process_iter.return_value = [process(1), own, old, other, identity_denied, uncertain, gone, unrelated]
    assert runtime._owned_token_processes(SimpleNamespace(
        ownership_token="owned", ownership_started_at=100)) == ([own], [6])


def test_token_scan_handles_inaccessible_current_user(fake_os, fake_psutil):
    fake_psutil.Process.side_effect = psutil.AccessDenied(1)
    candidate = process(2, environ={runtime.background_jobs_support.BACKGROUND_JOB_TOKEN_ENV: "owned"})
    fake_psutil.process_iter.return_value = [candidate]
    assert runtime._owned_token_processes(SimpleNamespace(ownership_token="owned")) == ([candidate], [])


@pytest.mark.parametrize("token", [None, "", 42])
def test_missing_token_never_scans_processes(token, fake_psutil):
    assert runtime._owned_token_processes(SimpleNamespace(ownership_token=token)) == ([], [])
    fake_psutil.process_iter.assert_not_called()
    with pytest.raises(RuntimeError, match="no ownership token"):
        runtime._terminate_token_process_tree(SimpleNamespace(ownership_token=token), timeout=0)


def test_known_tree_preserves_children_before_parent(fake_psutil):
    root, child = process(2), process(3)
    root.children = Mock(return_value=[child])
    fake_psutil.Process.return_value = root
    assert runtime._known_process_tree(root) == [child, root]
    root.children.assert_called_once_with(recursive=True)
    root.poll.return_value = 0
    assert runtime._known_process_tree(root) == []


@pytest.mark.parametrize("failure", [psutil.AccessDenied(2), psutil.NoSuchProcess(2), ValueError("bad pid")])
def test_known_tree_disappeared_or_inaccessible(fake_psutil, failure):
    fake_psutil.Process.side_effect = failure
    assert runtime._known_process_tree(process(2)) == []


def test_token_cleanup_deduplicates_and_escalates(monkeypatch, fake_psutil):
    root, child = process(2), process(3)
    monkeypatch.setattr(runtime, "_owned_token_processes", Mock(side_effect=[([child], []), ([], [])]))
    monkeypatch.setattr(runtime, "_known_process_tree", lambda _: [child, root])
    fake_psutil.wait_procs.side_effect = [([root], [child]), ([child], [])]
    runtime._terminate_token_process_tree(SimpleNamespace(ownership_token="owned"), timeout=2)
    child.terminate.assert_called_once_with()
    root.terminate.assert_called_once_with()
    child.kill.assert_called_once_with()
    root.kill.assert_not_called()
    assert fake_psutil.wait_procs.call_args_list[0].args[0] == [child, root]


@pytest.mark.parametrize("phase", ["terminate", "kill"])
@pytest.mark.parametrize("failure_type", [psutil.NoSuchProcess, psutil.AccessDenied])
def test_token_cleanup_signal_failures_are_reported(monkeypatch, fake_psutil, phase, failure_type):
    child = process(3)
    getattr(child, phase).side_effect = failure_type(3)
    monkeypatch.setattr(runtime, "_owned_token_processes", Mock(side_effect=[([child], []), ([], [])]))
    monkeypatch.setattr(runtime, "_known_process_tree", lambda _: [])
    fake_psutil.wait_procs.side_effect = [([], [child] if phase == "kill" else []), ([], [])]
    if failure_type is psutil.AccessDenied:
        with pytest.raises(RuntimeError, match="termination remains unproven"):
            runtime._terminate_token_process_tree(SimpleNamespace(ownership_token="owned"), timeout=0)
    else:
        runtime._terminate_token_process_tree(SimpleNamespace(ownership_token="owned"), timeout=0)


@pytest.mark.parametrize("remaining,uncertain,match", [([process(7)], [], "still alive: 7"), ([], [8], "candidate pid.s.: 8")])
def test_cleanup_requires_post_signal_proof(monkeypatch, fake_psutil, remaining, uncertain, match):
    monkeypatch.setattr(runtime, "_owned_token_processes", Mock(side_effect=[([], []), (remaining, uncertain)]))
    monkeypatch.setattr(runtime, "_known_process_tree", lambda _: [])
    with pytest.raises(RuntimeError, match=match):
        runtime._terminate_token_process_tree(SimpleNamespace(ownership_token="owned"), timeout=0)


@pytest.mark.parametrize("status,group,result", [("running", 42, True), (psutil.STATUS_ZOMBIE, 42, False), ("running", 9, False)])
def test_live_group_ignores_zombies_and_other_groups(fake_os, fake_psutil, status, group, result):
    candidate = process(2)
    candidate.info["status"] = status
    fake_psutil.process_iter.return_value = [candidate]
    fake_os.getpgid.return_value = group
    assert runtime._posix_process_group_has_live_member(42) is result


@pytest.mark.parametrize("failure,result", [(ProcessLookupError(), False), (PermissionError(), True)])
def test_live_group_uncertainty_is_conservative(fake_os, fake_psutil, failure, result):
    fake_psutil.process_iter.return_value = [process(2)]
    fake_os.getpgid.side_effect = failure
    assert runtime._posix_process_group_has_live_member(42) is result


@pytest.mark.parametrize("failure,live,expected", [(ProcessLookupError(), True, False), (PermissionError(), False, False), (PermissionError(), True, None), (OSError("io"), True, None)])
def test_group_probe_distinguishes_dead_zombies_and_inspection_failure(monkeypatch, fake_os, failure, live, expected):
    fake_os.killpg.side_effect = failure
    monkeypatch.setattr(runtime, "_posix_process_group_has_live_member", lambda _: live)
    if expected is None:
        with pytest.raises(RuntimeError, match="cannot inspect"):
            runtime._posix_process_group_exists(42)
    else:
        assert runtime._posix_process_group_exists(42) is expected


@pytest.mark.parametrize("state,group,expected", [(None, 42, True), (None, 7, False), (0, 42, False)])
def test_leader_authority_requires_live_matching_group(fake_os, state, group, expected):
    leader = process(2)
    leader.poll.return_value = state
    fake_os.getpgid.return_value = group
    assert runtime._posix_leader_owns_group(leader, 42) is expected


@pytest.mark.parametrize("failure", [ProcessLookupError(), ValueError("bad"), OSError("io")])
def test_leader_inspection_failure_is_not_authority(fake_os, failure):
    fake_os.getpgid.side_effect = failure
    assert runtime._posix_leader_owns_group(process(2), 42) is False


@pytest.mark.parametrize("token,expected", [("owned", True), ("unrelated", False)])
def test_group_token_is_exact(fake_os, fake_psutil, token, expected):
    fake_psutil.process_iter.return_value = [process(2, environ={runtime.background_jobs_support.BACKGROUND_JOB_TOKEN_ENV: token})]
    assert runtime._posix_group_has_ownership_token(42, "owned") is expected


@pytest.mark.parametrize("phase,failure,expected", [
    ("getpgid", ProcessLookupError(), False), ("getpgid", PermissionError(), None),
    ("environ", psutil.NoSuchProcess(2), False), ("environ", psutil.AccessDenied(2), None),
])
def test_group_token_unavailable_refuses_authority(fake_os, fake_psutil, phase, failure, expected):
    candidate = process(2)
    fake_psutil.process_iter.return_value = [candidate]
    (fake_os.getpgid if phase == "getpgid" else candidate.environ).side_effect = failure
    if expected is None:
        with pytest.raises(RuntimeError, match="cannot"):
            runtime._posix_group_has_ownership_token(42, "owned")
    else:
        assert runtime._posix_group_has_ownership_token(42, "owned") is expected


@pytest.mark.parametrize("exists,leader,token,expected", [
    ([False], False, False, False), ([True], True, False, True),
    ([True], False, True, True), ([True, False], False, False, False),
    ([True, True], False, False, None),
])
def test_ownership_proof_rechecks_disappearing_group(monkeypatch, exists, leader, token, expected):
    monkeypatch.setattr(runtime, "_posix_process_group_exists", Mock(side_effect=exists))
    monkeypatch.setattr(runtime, "_posix_leader_owns_group", lambda *_: leader)
    monkeypatch.setattr(runtime, "_posix_group_has_ownership_token", lambda *_: token)
    job = SimpleNamespace(ownership_token="owned")
    if expected is None:
        with pytest.raises(RuntimeError, match="refusing to signal"):
            runtime._prove_posix_process_group_ownership(job, 42)
    else:
        assert runtime._prove_posix_process_group_ownership(job, 42) is expected


@pytest.mark.parametrize("failure", [None, ProcessLookupError(), PermissionError(), OSError("io")])
def test_signal_handles_post_proof_races(monkeypatch, fake_os, failure):
    monkeypatch.setattr(runtime, "_prove_posix_process_group_ownership", lambda *_: True)
    fake_os.killpg.side_effect = failure
    if isinstance(failure, (PermissionError, OSError)) and not isinstance(failure, ProcessLookupError):
        with pytest.raises(RuntimeError, match="cannot signal"):
            runtime._signal_posix_process_group(object(), 42, 15)
    else:
        assert runtime._signal_posix_process_group(object(), 42, 15) is (failure is None)


def test_missing_platform_primitives_fail_closed(fake_os):
    fake_os.getpgid = None
    fake_os.killpg = None
    assert runtime._posix_process_group_has_live_member(42)
    assert not runtime._posix_leader_owns_group(process(2), 42)
    assert not runtime._posix_group_has_ownership_token(42, "owned")
    with pytest.raises(RuntimeError, match="unavailable"):
        runtime._posix_process_group_exists(42)


def test_own_group_is_never_signalled(monkeypatch, fake_os):
    fake_os.getpgrp = lambda: 42
    with pytest.raises(RuntimeError, match="AGILAB process group"):
        runtime._terminate_posix_owned_process_tree(SimpleNamespace(process_group_id=42), timeout=0)
    fake_os.killpg.assert_not_called()


@pytest.mark.parametrize("wait_results,raises", [([True], False), ([False, True], False), ([False, False], True)])
def test_group_cleanup_escalates_with_bounded_wait_and_token_sweep(monkeypatch, fake_os, wait_results, raises):
    signals = Mock(return_value=True)
    sweep = Mock()
    monkeypatch.setattr(runtime, "_signal_posix_process_group", signals)
    monkeypatch.setattr(runtime, "_wait_for_posix_process_group", Mock(side_effect=wait_results))
    monkeypatch.setattr(runtime, "_terminate_token_process_tree", sweep)
    job = SimpleNamespace(process_group_id=42, process=process(2))
    if raises:
        with pytest.raises(runtime.subprocess.TimeoutExpired):
            runtime._terminate_posix_owned_process_tree(job, timeout=2)
        sweep.assert_not_called()
    else:
        runtime._terminate_posix_owned_process_tree(job, timeout=2)
        sweep.assert_called_once_with(job, timeout=2)
    assert [call.args[2] for call in signals.call_args_list] == (
        [runtime.signal.SIGTERM] if len(wait_results) == 1 else [runtime.signal.SIGTERM, runtime.signal.SIGKILL])


@pytest.mark.parametrize("group", [None, 0, -1, "42"])
def test_missing_group_uses_token_owned_tree_only(monkeypatch, fake_os, group):
    sweep = Mock()
    monkeypatch.setattr(runtime, "_terminate_token_process_tree", sweep)
    job = SimpleNamespace(process_group_id=group)
    runtime._terminate_posix_owned_process_tree(job, timeout=2)
    sweep.assert_called_once_with(job, timeout=2)
    fake_os.killpg.assert_not_called()


def test_group_signal_refuses_without_proof(monkeypatch, fake_os):
    monkeypatch.setattr(runtime, "_prove_posix_process_group_ownership", lambda *_: False)
    assert not runtime._signal_posix_process_group(object(), 42, 15)
    fake_os.killpg.assert_not_called()


@pytest.mark.parametrize("exists,result", [([False], True), ([True, True], False)])
def test_group_wait_uses_deadline_and_tolerates_disappeared_leader(monkeypatch, exists, result):
    monkeypatch.setattr(runtime, "_posix_process_group_exists", Mock(side_effect=exists))
    clock = SimpleNamespace(monotonic=Mock(side_effect=[0, 0.01, 2]), sleep=Mock())
    monkeypatch.setattr(runtime, "time", clock)
    leader = process(2)
    leader.poll.side_effect = ProcessLookupError()
    assert runtime._wait_for_posix_process_group(leader, 42, timeout=1) is result
    if result:
        clock.sleep.assert_not_called()
    else:
        clock.sleep.assert_called_once_with(0.05)
