"""Sidecar ownership observations fail closed without signalling real processes."""
import hashlib
import socket
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import Mock

import psutil
import pytest

from agi_env.ui import sidecar_registry as sidecar


@pytest.fixture
def registry(tmp_path):
    return sidecar.ProcessSidecarRegistry(tmp_path)


@pytest.fixture
def lease(registry):
    raw = dict(service_kind="notebook", project="demo", key="old",
               endpoint="http://127.0.0.1:43210", token="test-token", pid=87654,
               process_started_at=12.0, command_digest="test-command", registered_at=20.0)
    raw["health_signature"] = registry._sign(raw)
    return sidecar.SidecarLease(**raw)


@pytest.fixture
def processes(monkeypatch):
    proxy = SimpleNamespace(
        Process=Mock(), Error=psutil.Error, NoSuchProcess=psutil.NoSuchProcess,
        AccessDenied=psutil.AccessDenied, STATUS_ZOMBIE=psutil.STATUS_ZOMBIE,
    )
    monkeypatch.setattr(sidecar, "psutil", proxy)
    return proxy


@pytest.mark.parametrize("running,status,created,expected", [
    (False, "running", 12, False), (True, psutil.STATUS_ZOMBIE, 12, False),
    (True, "running", 12, True), (True, "running", 13, False),
])
def test_identity_requires_live_process_and_same_birth_time(processes, running, status, created, expected):
    processes.Process.return_value = SimpleNamespace(is_running=lambda: running, status=lambda: status,
                                                    create_time=lambda: created)
    assert sidecar.ProcessSidecarRegistry._process_identity_status(42, 12) is expected


@pytest.mark.parametrize("failure,expected", [(psutil.NoSuchProcess(42), False), (psutil.AccessDenied(42), None),
                                             (OSError("denied"), None), (ValueError("invalid time"), None)])
def test_identity_inspection_failure_never_becomes_match(processes, failure, expected):
    processes.Process.side_effect = failure
    assert sidecar.ProcessSidecarRegistry._process_identity_status(42, 12) is expected
    assert not sidecar.ProcessSidecarRegistry._process_matches(42, 12)


def test_process_tree_refuses_reused_pid_before_enumerating_children(monkeypatch, processes):
    monkeypatch.setattr(sidecar.ProcessSidecarRegistry, "_process_matches", lambda *_: False)
    assert sidecar.ProcessSidecarRegistry._process_tree(42, 12) == []
    processes.Process.assert_not_called()


@pytest.mark.parametrize("failure", [psutil.AccessDenied(42), OSError("denied")])
def test_process_tree_inspection_failure_returns_no_owned_tree(monkeypatch, processes, failure):
    monkeypatch.setattr(sidecar.ProcessSidecarRegistry, "_process_matches", lambda *_: True)
    processes.Process.side_effect = failure
    assert sidecar.ProcessSidecarRegistry._process_tree(42, 12) == []


def test_tree_identities_skip_only_unreadable_children(monkeypatch):
    readable = SimpleNamespace(pid=42, create_time=Mock(return_value=12))
    denied = SimpleNamespace(pid=43, create_time=Mock(side_effect=psutil.AccessDenied(43)))
    invalid = SimpleNamespace(pid=44, create_time=Mock(return_value="bad"))
    monkeypatch.setattr(sidecar.ProcessSidecarRegistry, "_process_tree", lambda *_: [readable, denied, invalid])
    assert sidecar.ProcessSidecarRegistry._process_tree_identities(42, 12) == {42: 12.0}


@pytest.mark.parametrize("local,family,status,expected", [
    (("127.0.0.1", 43210), socket.AF_INET, "LISTEN", True),
    (SimpleNamespace(ip="127.0.0.1", port=43210), socket.AF_INET, "listen", True),
    (("127.0.0.1", 43211), socket.AF_INET, "LISTEN", False),
    (("0.0.0.0", 43210), socket.AF_INET, "LISTEN", False),
    (("127.0.0.1", 43210), socket.AF_INET6, "LISTEN", False),
    (("127.0.0.1", 43210), socket.AF_INET, "ESTABLISHED", False),
    ((), socket.AF_INET, "LISTEN", False),
    (("127.0.0.1",), socket.AF_INET, "LISTEN", False),
    (SimpleNamespace(other="value"), socket.AF_INET, "LISTEN", False),
    (("127.0.0.1", 43210), None, "LISTEN", False),
    (("127.0.0.1", None), socket.AF_INET, "LISTEN", False),
])
def test_endpoint_proof_requires_exact_ipv4_loopback_listener(monkeypatch, local, family, status, expected):
    connection = SimpleNamespace(laddr=local, family=family, status=status)
    process = SimpleNamespace(net_connections=Mock(return_value=[connection]))
    monkeypatch.setattr(sidecar.ProcessSidecarRegistry, "_process_tree", lambda *_: [process])
    assert sidecar.ProcessSidecarRegistry._process_owns_endpoint(42, 12, "127.0.0.1", 43210) is expected


def test_endpoint_scan_can_prove_child_after_inaccessible_parent(monkeypatch):
    parent = SimpleNamespace(net_connections=Mock(side_effect=psutil.AccessDenied(42)))
    child = SimpleNamespace(net_connections=Mock(return_value=[
        SimpleNamespace(laddr=("127.0.0.1", 43210), family=socket.AF_INET, status="LISTEN")]))
    tree = Mock(return_value=[parent, child])
    monkeypatch.setattr(sidecar.ProcessSidecarRegistry, "_process_tree", tree)
    assert sidecar.ProcessSidecarRegistry._process_owns_endpoint(42, 12, "127.0.0.1", 43210)
    assert not sidecar.ProcessSidecarRegistry._process_owns_endpoint(42, 12, "0.0.0.0", 43210)
    assert tree.call_count == 1


@pytest.mark.parametrize("failure", [None, psutil.AccessDenied(42), OSError("denied")])
def test_command_digest_binds_exact_argument_boundaries(monkeypatch, processes, failure):
    monkeypatch.setattr(sidecar.ProcessSidecarRegistry, "_process_matches", lambda *_: True)
    command = Mock(return_value=["python", "argument with spaces", ""])
    command.side_effect = failure
    processes.Process.return_value = SimpleNamespace(cmdline=command)
    expected = "" if failure else hashlib.sha256(b"python\0argument with spaces\0").hexdigest()
    assert sidecar.ProcessSidecarRegistry._command_digest(42, 12) == expected


@pytest.mark.parametrize("identity,digest,endpoint,expected", [
    (False, "test-command", True, False), (True, "different", True, False),
    (True, "test-command", False, False), (True, "test-command", True, True),
])
def test_healthy_lease_requires_signature_identity_command_and_endpoint(monkeypatch, registry, lease, identity, digest, endpoint, expected):
    monkeypatch.setattr(registry, "_process_matches", lambda *_: identity)
    monkeypatch.setattr(registry, "_command_digest", lambda *_: digest)
    monkeypatch.setattr(registry, "_process_owns_endpoint", lambda *_: endpoint)
    assert registry._lease_is_healthy(lease) is expected


@pytest.mark.parametrize("identity,port_open,error", [(None, False, "Cannot verify"), (False, True, "still listening"), (False, False, None)])
def test_retirement_preserves_uncertain_lease_evidence(monkeypatch, registry, lease, identity, port_open, error):
    raw = asdict(lease)
    entries = {"old": raw, "keep": {}, "foreign": dict(raw, project="other"), "malformed": None}
    monkeypatch.setattr(registry, "_process_identity_status", lambda *_: identity)
    monkeypatch.setattr(registry, "_port_is_open", lambda *_: port_open)
    write = Mock()
    monkeypatch.setattr(registry, "_write_entries", write)
    if error:
        with pytest.raises(sidecar.SidecarCollisionError, match=error):
            registry._retire_project_entries(entries, service_kind="notebook", project="demo", keep_entry_id="keep")
        assert entries["old"] == raw
        write.assert_not_called()
    else:
        registry._retire_project_entries(entries, service_kind="notebook", project="demo", keep_entry_id="keep")
        assert set(entries) == {"keep", "foreign", "malformed"}
        write.assert_called_once_with(entries)


@pytest.mark.parametrize("failure", [psutil.NoSuchProcess(87654), psutil.AccessDenied(87654)])
def test_retirement_handles_process_disappearing_or_inaccessible_after_identity_probe(monkeypatch, registry, lease, processes, failure):
    entries = {"old": asdict(lease)}
    monkeypatch.setattr(registry, "_process_identity_status", lambda *_: True)
    monkeypatch.setattr(registry, "_port_is_open", lambda *_: False)
    monkeypatch.setattr(registry, "_write_entries", Mock())
    processes.Process.side_effect = failure
    if isinstance(failure, psutil.AccessDenied):
        with pytest.raises(sidecar.SidecarCollisionError, match="Cannot inspect"):
            registry._retire_project_entries(entries, service_kind="notebook", project="demo", keep_entry_id="keep")
        assert "old" in entries
    else:
        registry._retire_project_entries(entries, service_kind="notebook", project="demo", keep_entry_id="keep")
        assert entries == {}


@pytest.mark.parametrize("after", [False, True, None])
def test_retirement_requires_post_termination_identity_absence(monkeypatch, registry, lease, processes, after):
    entries = {"old": asdict(lease)}
    process = SimpleNamespace(pid=lease.pid)
    processes.Process.return_value = process
    monkeypatch.setattr(registry, "_process_identity_status", Mock(side_effect=[True, after]))
    monkeypatch.setattr(registry, "_process_tree_identities", lambda *_: {lease.pid: lease.process_started_at})
    terminate = Mock()
    monkeypatch.setattr(registry, "_terminate_process", terminate)
    monkeypatch.setattr(registry, "_port_is_open", lambda *_: False)
    monkeypatch.setattr(registry, "_write_entries", Mock())
    if after is False:
        registry._retire_project_entries(entries, service_kind="notebook", project="demo", keep_entry_id="keep")
        assert entries == {}
    else:
        with pytest.raises(sidecar.SidecarCollisionError, match="Could not stop"):
            registry._retire_project_entries(entries, service_kind="notebook", project="demo", keep_entry_id="keep")
        assert "old" in entries
    terminate.assert_called_once_with(process, root_pid=lease.pid, root_started_at=lease.process_started_at,
                                     observed_processes={lease.pid: lease.process_started_at})


def test_reserved_port_retries_process_local_collision_and_cleans_claim(monkeypatch, registry):
    registry.root.mkdir(parents=True, exist_ok=True)
    occupied = str((registry.root / "port-43210.lock").resolve())
    reservations = {occupied}
    monkeypatch.setattr(sidecar, "_PORT_RESERVATIONS", reservations)
    monkeypatch.setattr(registry, "_allocate_loopback_port", Mock(side_effect=[43210, 43211]))
    sleeps = Mock()
    monkeypatch.setattr(sidecar, "time", SimpleNamespace(monotonic=lambda: 0, sleep=sleeps))
    monkeypatch.setattr(registry, "_try_advisory_lock", lambda _: True)
    unlock = Mock()
    monkeypatch.setattr(registry, "_unlock_advisory_lock", unlock)
    with registry._reserved_loopback_port(timeout=1) as port:
        assert port == 43211
        assert str((registry.root / "port-43211.lock").resolve()) in reservations
    assert reservations == {occupied}
    sleeps.assert_called_once_with(0.01)
    unlock.assert_called_once()


def test_reserved_port_retries_external_lock_without_leaking_claim(monkeypatch, registry):
    reservations = set()
    monkeypatch.setattr(sidecar, "_PORT_RESERVATIONS", reservations)
    monkeypatch.setattr(registry, "_allocate_loopback_port", Mock(side_effect=[43210, 43211]))
    monkeypatch.setattr(sidecar, "time", SimpleNamespace(monotonic=lambda: 0, sleep=Mock()))
    handles = []
    def lock(handle):
        handles.append(handle)
        return len(handles) == 2
    monkeypatch.setattr(registry, "_try_advisory_lock", lock)
    unlock = Mock()
    monkeypatch.setattr(registry, "_unlock_advisory_lock", unlock)
    with registry._reserved_loopback_port(timeout=1) as port:
        assert port == 43211
        assert handles[0].closed
        assert len(reservations) == 1
    assert not reservations
    assert all(handle.closed for handle in handles)
    unlock.assert_called_once_with(handles[1])


def test_reserved_port_deadline_never_allocates_when_expired(monkeypatch, registry):
    monkeypatch.setattr(sidecar, "time", SimpleNamespace(monotonic=Mock(side_effect=[0, 1])))
    allocate = Mock()
    monkeypatch.setattr(registry, "_allocate_loopback_port", allocate)
    with pytest.raises(sidecar.SidecarRegistryBusyError, match="reserving a loopback port"):
        with registry._reserved_loopback_port(timeout=1):
            pytest.fail("expired reservation must not yield")
    allocate.assert_not_called()


def test_reserved_port_body_failure_releases_both_locks(monkeypatch, registry):
    reservations = set()
    monkeypatch.setattr(sidecar, "_PORT_RESERVATIONS", reservations)
    monkeypatch.setattr(registry, "_allocate_loopback_port", lambda: 43210)
    monkeypatch.setattr(registry, "_try_advisory_lock", lambda _: True)
    unlock = Mock()
    monkeypatch.setattr(registry, "_unlock_advisory_lock", unlock)
    with pytest.raises(RuntimeError, match="launch failure"):
        with registry._reserved_loopback_port(timeout=1):
            raise RuntimeError("launch failure")
    assert not reservations
    unlock.assert_called_once()
    assert unlock.call_args.args[0].closed
