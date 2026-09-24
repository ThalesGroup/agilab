"""Lease identity and remote transport failures retain exact ownership evidence."""
import json
import shlex
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import psutil
import pytest

from agi_cluster.agi_distributor.runtime import cleanup_support as cleanup
from agi_cluster.agi_distributor.runtime import lifecycle_guard_support as lifecycle
from agi_cluster.agi_distributor.runtime import transport_support as transport


@pytest.mark.parametrize("field,value,expected", [
    ("pid", None, True), ("pid", "bad", True), ("pid", 0, True), ("pid", -1, True),
    ("hostname", "a-different-host", True), ("process_start_time", "bad", True),
    ("process_start_time", None, True), ("process_start_time", 100, True),
    ("process_start_time", 101, True), ("process_start_time", 102, False),
])
def test_owner_liveness_treats_uncertainty_as_live(field, value, expected):
    payload = {"pid": 42, "process_start_time": 100}
    payload[field] = value
    process = SimpleNamespace(is_running=lambda: True, create_time=lambda: 100)
    assert lifecycle._owner_is_live(payload, process_factory=lambda _: process) is expected


@pytest.mark.parametrize("phase", ["construct", "is_running", "create_time"])
@pytest.mark.parametrize("error_type,expected", [(psutil.NoSuchProcess, False), (psutil.AccessDenied, True), (OSError, True)])
def test_owner_identity_lookup_failure_is_not_staleness(phase, error_type, expected):
    error = error_type(42)
    process = SimpleNamespace(is_running=Mock(return_value=True), create_time=Mock(return_value=100))
    factory = Mock(return_value=process)
    (factory if phase == "construct" else getattr(process, phase)).side_effect = error
    assert lifecycle._owner_is_live({"pid": 42, "process_start_time": 100}, process_factory=factory) is expected


@pytest.mark.parametrize("value", [None, "bad"])
def test_process_start_time_invalid_values_are_unavailable(value):
    assert lifecycle._process_start_time(42, process_factory=lambda _: SimpleNamespace(create_time=lambda: value)) is None


@pytest.mark.parametrize("content", ["not-json", "[]", "null", "{}"])
def test_unreadable_owner_record_does_not_invent_identity(tmp_path, content):
    (tmp_path / "owner.json").write_text(content)
    assert lifecycle._read_owner(tmp_path) == {}
    (tmp_path / "owner.json").unlink()
    assert lifecycle._read_owner(tmp_path) == {}


def test_recovery_capabilities_are_validated_deduplicated_and_ordered():
    a, b = "a" * 32, "b" * 32
    assert lifecycle._owner_remote_tokens({"remote_token": a, "recovered_remote_tokens": [
        a, "", "x" * 32, None, b]}) == (a, b)
    assert lifecycle._owner_remote_tokens({"remote_token": a, "recovered_remote_tokens": b}) == (a,)


@pytest.fixture
def remote_owner():
    return SimpleNamespace(env=SimpleNamespace(wenv_rel=Path("work/demo"), uv="uv", python_version="3.13"),
                           _lifecycle_call_token="current", _lifecycle_call_operation="deploy",
                           exec_ssh=AsyncMock())


@pytest.mark.asyncio
async def test_remote_lease_is_published_before_uncertain_transport(remote_owner):
    remote_owner._lifecycle_remote_recovery_tokens = ["old", "old", "", None]
    remote_owner.exec_ssh.side_effect = OSError("connection lost after remote claim")
    with pytest.raises(OSError):
        await cleanup.acquire_remote_target_lease(remote_owner, "worker", cmd_prefix="")
    lease = remote_owner._remote_target_leases["worker"]
    assert lease.token == "current"
    assert lease.recovery_tokens == ("old",)
    command = remote_owner.exec_ssh.call_args.args[1]
    assert "target-lease-recover" in command
    assert shlex.split(command)[-4:] == ["work/demo", "current", "old", "deploy"]


@pytest.mark.asyncio
async def test_remote_lease_reuses_only_matching_generation(remote_owner):
    first = await cleanup.acquire_remote_target_lease(remote_owner, "worker", cmd_prefix="")
    assert await cleanup.acquire_remote_target_lease(remote_owner, "worker") is first
    remote_owner.exec_ssh.assert_awaited_once()
    remote_owner._lifecycle_call_token = "new"
    with pytest.raises(RuntimeError, match="does not match"):
        await cleanup.acquire_remote_target_lease(remote_owner, "worker")


@pytest.mark.asyncio
async def test_remote_lease_requires_active_lifecycle(remote_owner):
    remote_owner._lifecycle_call_token = ""
    with pytest.raises(RuntimeError, match="active lifecycle token"):
        await cleanup.acquire_remote_target_lease(remote_owner, "worker")
    remote_owner.exec_ssh.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_cached_remote_lease_blocks_acquisition_and_cleanup(remote_owner):
    remote_owner._remote_target_leases = {"worker": object()}
    remote_owner.env.envars = {}
    with pytest.raises(RuntimeError, match="invalid"):
        await cleanup.acquire_remote_target_lease(remote_owner, "worker")
    with pytest.raises(RuntimeError, match="invalid"):
        await cleanup.clean_dirs(remote_owner, "worker")
    remote_owner.exec_ssh.assert_not_awaited()


@pytest.mark.asyncio
async def test_release_retains_only_unproven_leases_and_attempts_all_hosts(remote_owner):
    def lease(host):
        return cleanup.RemoteTargetLease(host, Path("work/demo"), "current", "deploy", "")
    leases = {"a": lease("a"), "b": lease("b"), "c": object()}
    remote_owner._remote_target_leases = leases
    remote_owner.exec_ssh.side_effect = [OSError("lost"), None]
    with pytest.raises(RuntimeError, match="a: lost; c: invalid"):
        await cleanup.release_remote_target_leases(remote_owner)
    assert set(leases) == {"a", "c"}
    assert [call.args[0] for call in remote_owner.exec_ssh.call_args_list] == ["a", "b"]


@pytest.mark.asyncio
@pytest.mark.parametrize("leases", [None, {}, []])
async def test_release_without_remote_evidence_does_no_network(remote_owner, leases):
    remote_owner._remote_target_leases = leases
    await cleanup.release_remote_target_leases(remote_owner)
    remote_owner.exec_ssh.assert_not_awaited()


@pytest.mark.parametrize("result", [SimpleNamespace(returncode=1, stdout=""), SimpleNamespace(returncode=0, stdout=""), SimpleNamespace(returncode=0, stdout="key")])
def test_known_host_lookup_requires_success_and_output(monkeypatch, tmp_path, result):
    hosts = tmp_path / "known_hosts"
    hosts.write_text("existing\n")
    run = Mock(return_value=result)
    monkeypatch.setattr(transport, "subprocess", SimpleNamespace(run=run, TimeoutExpired=__import__("subprocess").TimeoutExpired))
    assert transport._known_host_entry_exists("host", hosts, port=2222) is (result.returncode == 0 and bool(result.stdout))
    assert run.call_args.args[0][2] == "[host]:2222"
    assert run.call_args.kwargs["timeout"] == 5


@pytest.mark.parametrize("failure", [OSError("missing executable"), __import__("subprocess").TimeoutExpired("ssh-keygen", 5)])
def test_known_host_lookup_failure_never_claims_existing_pin(monkeypatch, tmp_path, failure):
    hosts = tmp_path / "known_hosts"
    hosts.touch()
    monkeypatch.setattr(transport, "subprocess", SimpleNamespace(run=Mock(side_effect=failure),
                        TimeoutExpired=__import__("subprocess").TimeoutExpired))
    assert not transport._known_host_entry_exists("host", hosts)


@pytest.mark.parametrize("returncode,output", [(1, "key"), (0, "# comment\n\n"), (0, "")])
def test_failed_scan_cannot_append_host_pin(monkeypatch, tmp_path, returncode, output):
    hosts = tmp_path / "ssh" / "known_hosts"
    result = SimpleNamespace(returncode=returncode, stdout=output, stderr="")
    monkeypatch.setattr(transport, "subprocess", SimpleNamespace(run=Mock(return_value=result),
                        TimeoutExpired=__import__("subprocess").TimeoutExpired))
    assert not transport._append_known_host_from_scan("host", hosts, log=Mock())
    assert not hosts.exists()


def test_successful_scan_preserves_existing_pins_and_filters_comments(monkeypatch, tmp_path):
    hosts = tmp_path / "ssh" / "known_hosts"
    hosts.parent.mkdir()
    hosts.write_text("existing\n")
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout="# scan\n\n|hashed| ssh-ed25519 key\n", stderr=""))
    monkeypatch.setattr(transport, "subprocess", SimpleNamespace(run=run,
                        TimeoutExpired=__import__("subprocess").TimeoutExpired))
    assert transport._append_known_host_from_scan("host", hosts, port=2222, log=Mock())
    assert hosts.read_text() == "existing\n|hashed| ssh-ed25519 key\n"
    assert run.call_args.args[0][-1] == "host"
    assert run.call_args.kwargs["timeout"] == 10


@pytest.mark.parametrize("policy,exists,learned,scans", [("strict", False, False, 0), ("accept-new", True, False, 0), ("accept-new", False, False, 1), ("accept-new", False, True, 1)])
def test_only_explicit_tofu_policy_learns_absent_pin(monkeypatch, tmp_path, policy, exists, learned, scans):
    scan = Mock(return_value=learned)
    monkeypatch.setattr(transport, "_known_host_entry_exists", lambda *_: exists)
    monkeypatch.setattr(transport, "_append_known_host_from_scan", scan)
    log = Mock()
    transport._prepare_known_hosts_for_policy("host", tmp_path / "known_hosts", policy, log=log)
    assert scan.call_count == scans
    assert log.info.call_count == int(bool(scans and learned))


def make_generation(path, token, **extra):
    path.mkdir(parents=True)
    (path / ("token-" + token)).mkdir()
    payload = {"schema": lifecycle.LEASE_SCHEMA, "token": token, **extra}
    (path / "owner.json").write_text(json.dumps(payload))


@pytest.mark.parametrize("token", ["", "bad", "x" * 32])
def test_invalid_stale_generation_token_cannot_remove_lock(tmp_path, token):
    lock = tmp_path / "runtime.lock"
    make_generation(lock, "a" * 32)
    before = (lock / "owner.json").read_bytes()
    assert not lifecycle._remove_stale_lock(lock, token)
    assert (lock / "owner.json").read_bytes() == before


def test_stale_recovery_resumes_claim_after_marker_move(tmp_path):
    token = "a" * 32
    lock = tmp_path / "runtime.lock"
    make_generation(lock, token)
    claim = tmp_path / (".runtime.lock.reclaim-" + token + "-interrupted")
    (lock / ("token-" + token)).rename(claim)
    assert lifecycle._remove_stale_lock(lock, token)
    tombstone = lifecycle._target_release_tombstone(lock, token)
    assert not lock.exists()
    assert not claim.exists()
    assert lifecycle._read_owner(tombstone)["token"] == token
    assert lifecycle._remove_stale_lock(lock, token)


def test_conflicting_tombstone_preserves_owner_and_claim(tmp_path):
    token = "a" * 32
    lock = tmp_path / "runtime.lock"
    make_generation(lock, token)
    tombstone = lifecycle._target_release_tombstone(lock, token)
    make_generation(tombstone, "b" * 32)
    claim = tmp_path / "claim"
    claim.mkdir()
    assert not lifecycle._retire_claimed_target_generation(lock, token, claim)
    assert lifecycle._read_owner(lock)["token"] == token
    assert lifecycle._read_owner(tombstone)["token"] == "b" * 32
    assert claim.exists()


@pytest.mark.parametrize("successor_schema,successor_token,released", [
    (lifecycle.LEASE_SCHEMA, "b" * 32, True),
    (lifecycle.LEASE_SCHEMA, "a" * 32, False),
    ("other", "b" * 32, False),
    (lifecycle.LEASE_SCHEMA, "invalid", False),
])
def test_release_proof_requires_valid_distinct_successor(tmp_path, successor_schema, successor_token, released):
    lock = tmp_path / "runtime.lock"
    make_generation(lock, successor_token)
    (lock / "owner.json").write_text(json.dumps({"schema": successor_schema, "token": successor_token}))
    assert lifecycle._target_generation_released(lock, "a" * 32) is released


def test_retirement_rename_failure_preserves_recoverable_claim(monkeypatch, tmp_path):
    token = "a" * 32
    lock = tmp_path / "runtime.lock"
    make_generation(lock, token)
    claim = tmp_path / "claim"
    claim.mkdir()
    rename = Path.rename
    def fail_target(path, destination):
        if path == lock:
            raise PermissionError("read-only parent")
        return rename(path, destination)
    monkeypatch.setattr(Path, "rename", fail_target)
    assert not lifecycle._retire_claimed_target_generation(lock, token, claim)
    assert lock.exists()
    assert claim.exists()


def test_stale_recovery_inherits_only_old_owner_remote_capabilities(tmp_path):
    env = SimpleNamespace(wenv_abs=tmp_path / "runtime" / "demo")
    lock = lifecycle.target_lease_path(env)
    token, remote, inherited = "a" * 32, "b" * 32, "c" * 32
    make_generation(lock, token, pid=42, remote_token=remote, recovered_remote_tokens=[remote, inherited])
    def factory(pid):
        if pid == 42:
            raise psutil.NoSuchProcess(pid)
        return SimpleNamespace(create_time=lambda: 100)
    lease = lifecycle.acquire_target_lease(env, "install", process_factory=factory,
                                          getpid_fn=lambda: 99, time_fn=lambda: 123)
    assert lease.recovered_remote_tokens == (remote, inherited)
    assert lease.remote_token == lease.token
    assert lifecycle.release_target_lease(lease)
    assert lifecycle.release_target_lease(lease)


def test_stale_acquisition_refuses_corrupt_owner_even_when_pid_unknown(tmp_path):
    env = SimpleNamespace(wenv_abs=tmp_path / "runtime" / "demo")
    lock = lifecycle.target_lease_path(env)
    lock.mkdir(parents=True)
    (lock / "owner.json").write_text("corrupt")
    with pytest.raises(lifecycle.LifecycleBusyError):
        lifecycle.acquire_target_lease(env, "install", process_factory=lambda _: SimpleNamespace(create_time=lambda: 100))
    assert (lock / "owner.json").read_text() == "corrupt"
    assert not list(lock.parent.glob("*.claim-*"))
