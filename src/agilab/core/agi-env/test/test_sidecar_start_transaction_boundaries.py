"""Sidecar startup errors never publish unverifiable ownership."""
from contextlib import nullcontext
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import psutil
import pytest

from agi_env.ui import sidecar_registry as sidecar


@pytest.fixture
def registry(tmp_path, monkeypatch):
    registry = sidecar.ProcessSidecarRegistry(tmp_path)
    monkeypatch.setattr(registry, "_reserved_loopback_port", lambda **_: nullcontext(43123))
    monkeypatch.setattr(registry, "_terminate_process", Mock())
    monkeypatch.setattr(registry, "_process_tree_identities", Mock(return_value={123: 20.0}))
    monkeypatch.setattr(registry, "_process_owns_endpoint", Mock(return_value=True))
    monkeypatch.setattr(registry, "_command_digest", Mock(return_value="owned-command"))
    proxy = SimpleNamespace(Process=Mock(return_value=SimpleNamespace(create_time=lambda: 20)),
                            Error=psutil.Error)
    monkeypatch.setattr(sidecar, "psutil", proxy)
    return registry


def _ensure(registry, launcher, **kwargs):
    return registry.ensure(service_kind="notebook", project="demo", key="config",
                           launcher=launcher, timeout=0.1, **kwargs)


@pytest.mark.parametrize("pid", [None, 0, -1, "123"])
def test_invalid_launcher_handle_is_cleaned_without_publishing_lease(registry, pid):
    process = SimpleNamespace(pid=pid)
    with pytest.raises(sidecar.SidecarStartError, match="owned process handle"):
        _ensure(registry, lambda *_: process)
    assert registry._load_entries() == {}
    registry._terminate_process.assert_called_once_with(
        process, root_pid=None, root_started_at=None, observed_processes={}
    )


@pytest.mark.parametrize("error", [psutil.AccessDenied(123), OSError("identity unavailable"), ValueError("invalid time")])
def test_unverifiable_start_time_never_publishes_lease(registry, monkeypatch, error):
    def inspect(pid):
        if pid == 123:
            raise error
        return SimpleNamespace(create_time=lambda: 20.0)
    monkeypatch.setattr(sidecar.psutil, "Process", inspect)
    process = SimpleNamespace(pid=123)
    with pytest.raises(sidecar.SidecarStartError, match="Could not verify"):
        _ensure(registry, lambda *_: process)
    registry._terminate_process.assert_called_once_with(
        process, root_pid=123, root_started_at=None, observed_processes={}
    )
    assert registry._load_entries() == {}


def test_cleanup_failure_does_not_mask_original_invalid_handle(registry):
    registry._terminate_process.side_effect = RuntimeError("cleanup failed")
    with pytest.raises(sidecar.SidecarStartError, match="owned process handle"):
        _ensure(registry, lambda *_: object())
    assert registry._load_entries() == {}


def test_launcher_exception_reports_failure_without_inventing_process_ownership(registry):
    error = OSError("spawn failed")
    with pytest.raises(sidecar.SidecarStartError, match="Failed to launch") as caught:
        _ensure(registry, Mock(side_effect=error))
    assert caught.value.__cause__ is error
    registry._terminate_process.assert_not_called()
    assert registry._load_entries() == {}


@pytest.mark.parametrize("endpoint", ["http://example.com:43123", "http://127.0.0.1:43124"])
def test_endpoint_builder_cannot_move_reserved_listener(registry, endpoint):
    launcher = Mock()
    with pytest.raises(sidecar.SidecarRegistryError, match="allocated loopback port"):
        _ensure(registry, launcher, endpoint_builder=lambda _: endpoint)
    launcher.assert_not_called()


def test_mutually_exclusive_replacement_policies_reject_before_launch(registry):
    launcher = Mock()
    with pytest.raises(ValueError, match="both replace and reject"):
        _ensure(registry, launcher, replace_existing_for_project=True, exclusive_for_project=True)
    launcher.assert_not_called()


def test_malformed_existing_entry_never_gets_overwritten(registry):
    entry_id = registry._entry_id("notebook", "demo", "config")
    registry._write_entries({entry_id: "invalid"})
    launcher = Mock()
    with pytest.raises(sidecar.SidecarRegistryError, match="Invalid sidecar registry entry"):
        _ensure(registry, launcher)
    assert registry._load_entries() == {entry_id: "invalid"}
    launcher.assert_not_called()


def test_lease_publication_collision_preserves_concurrent_entry_and_cleans_started_process(registry):
    entry_id = registry._entry_id("notebook", "demo", "config")
    def launcher(*_):
        registry._write_entries({entry_id: {"other": "concurrent registration"}})
        return SimpleNamespace(pid=123, poll=lambda: None)
    with pytest.raises(sidecar.SidecarCollisionError, match="changed while"):
        _ensure(registry, launcher)
    assert registry._load_entries() == {entry_id: {"other": "concurrent registration"}}
    assert registry._terminate_process.call_args.kwargs["observed_processes"] == {123: 20.0}


def test_stale_registered_identity_with_foreign_listener_is_not_replaced(registry, monkeypatch):
    payload = dict(service_kind="notebook", project="demo", key="config",
                   endpoint="http://127.0.0.1:43123", token="fixture-token", pid=321,
                   process_started_at=10.0, command_digest="old-command", registered_at=1.0)
    lease = sidecar.SidecarLease(**payload, health_signature=registry._sign(payload))
    entry_id = registry._entry_id("notebook", "demo", "config")
    registry._write_entries({entry_id: asdict(lease)})
    monkeypatch.setattr(registry, "_lease_is_healthy", lambda _: False)
    monkeypatch.setattr(registry, "_process_identity_status", lambda *_: False)
    monkeypatch.setattr(registry, "_port_is_open", lambda _: True)
    launcher = Mock()
    with pytest.raises(sidecar.SidecarCollisionError, match="unrelated process"):
        _ensure(registry, launcher)
    launcher.assert_not_called()
    assert registry._load_entries()[entry_id]["pid"] == 321


@pytest.mark.parametrize("payload", ['{"entries":[]}', "not json"])
def test_invalid_registry_document_reports_read_error(registry, payload):
    registry.registry_path.write_text(payload)
    with pytest.raises(sidecar.SidecarRegistryError, match="Invalid sidecar registry structure|Could not read"):
        registry._load_entries()


def test_unreadable_existing_secret_does_not_get_replaced(registry, monkeypatch):
    registry.secret_path.write_bytes(b"x" * 32)
    read = Path.read_bytes
    def fail(path):
        if path == registry.secret_path:
            raise OSError("secret access denied")
        return read(path)
    monkeypatch.setattr(Path, "read_bytes", fail)
    with pytest.raises(sidecar.SidecarRegistryError, match="Could not read registry secret"):
        registry._load_secret()
    assert registry.secret_path.stat().st_size == 32


@pytest.mark.parametrize("phase", ["write", "fsync"])
def test_secret_write_failure_closes_descriptor_and_removes_partial_file(tmp_path, monkeypatch, phase):
    import os
    registry = sidecar.ProcessSidecarRegistry(tmp_path)
    proxy = SimpleNamespace(**{name: getattr(os, name) for name in dir(os)})
    proxy.close = Mock(wraps=os.close)
    setattr(proxy, phase, Mock(side_effect=OSError("secret write failed")))
    monkeypatch.setattr(sidecar, "os", proxy)
    with pytest.raises(OSError, match="secret write failed"):
        registry._load_secret()
    assert not registry.secret_path.exists()
    assert not list(tmp_path.glob("*.tmp"))
    assert proxy.close.call_count == 1
    with pytest.raises(OSError):
        os.fstat(proxy.close.call_args.args[0])


@pytest.mark.parametrize("phase", ["open", "fsync"])
def test_sidecar_directory_sync_failure_closes_open_descriptor(tmp_path, monkeypatch, phase):
    fake = SimpleNamespace(O_RDONLY=0, open=Mock(return_value=59), fsync=Mock(), close=Mock())
    getattr(fake, phase).side_effect = OSError("directory sync unavailable")
    monkeypatch.setattr(sidecar, "os", fake)
    sidecar.ProcessSidecarRegistry._fsync_directory(tmp_path)
    if phase == "open":
        fake.close.assert_not_called()
    else:
        fake.close.assert_called_once_with(59)


def test_too_short_existing_secret_is_not_silently_regenerated(registry):
    registry.secret_path.write_bytes(b"short")
    with pytest.raises(sidecar.SidecarRegistryError, match="secret is invalid"):
        registry._load_secret()
    assert registry.secret_path.read_bytes() == b"short"


@pytest.mark.parametrize("field", ["service_kind", "project", "key"])
def test_empty_sidecar_identity_rejects_before_launch(registry, field):
    params = dict(service_kind="notebook", project="demo", key="config", launcher=Mock())
    params[field] = " "
    with pytest.raises(ValueError, match="must be non-empty"):
        registry.ensure(**params)
    params["launcher"].assert_not_called()
