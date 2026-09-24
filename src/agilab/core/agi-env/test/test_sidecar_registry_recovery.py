"""Signed registry recovery contracts with simulated process observations."""
import json
import pytest
from agi_env.ui.sidecar_registry import ProcessSidecarRegistry, SidecarCollisionError, SidecarLease, SidecarRegistryError


def _entry(registry):
    raw = dict(service_kind="notebook", project="demo", key="old",
               endpoint="http://127.0.0.1:43210", token="test-token", pid=87654,
               process_started_at=12.0, command_digest="test-command", registered_at=20.0)
    raw["health_signature"] = registry._sign(raw)
    return raw


@pytest.mark.parametrize("identity,port_open,expected", [
    (True, False, "still live"), (None, False, "cannot be verified"),
    (False, True, "no longer matches"), (False, False, None),
])
def test_registry_get_preserves_uncertain_ownership_and_prunes_only_dead_entry(
    tmp_path, monkeypatch, identity, port_open, expected,
):
    registry = ProcessSidecarRegistry(tmp_path)
    raw = _entry(registry)
    key = registry._entry_id("notebook", "demo", "old")
    registry._write_entries({key: raw})
    before = registry.registry_path.read_bytes()
    monkeypatch.setattr(registry, "_lease_is_healthy", lambda lease: False)
    monkeypatch.setattr(registry, "_process_identity_status", lambda *args: identity)
    monkeypatch.setattr(registry, "_port_is_open", lambda port: port_open)
    if expected:
        with pytest.raises(SidecarCollisionError, match=expected):
            registry.get(service_kind="notebook", project="demo", key="old")
        assert registry.registry_path.read_bytes() == before
    else:
        assert registry.get(service_kind="notebook", project="demo", key="old") is None
        assert registry._load_entries() == {}


@pytest.mark.parametrize("field,value", [("token", "replacement"), ("pid", 111), ("project", "other"),
                                        ("process_started_at", 13.0), ("command_digest", "other")])
def test_registry_rejects_tampered_lease_before_any_process_probe(tmp_path, monkeypatch, field, value):
    registry = ProcessSidecarRegistry(tmp_path)
    raw = _entry(registry)
    raw[field] = value
    key = registry._entry_id("notebook", "demo", "old")
    registry._write_entries({key: raw})
    before = registry.registry_path.read_bytes()
    def unexpected(*args):
        pytest.fail("tampered lease must not reach process probes")
    monkeypatch.setattr(registry, "_process_identity_status", unexpected)
    with pytest.raises(SidecarRegistryError, match="signature"):
        registry.get(service_kind="notebook", project="demo", key="old")
    assert registry.registry_path.read_bytes() == before


@pytest.mark.parametrize("identity,port_open,healthy", [
    (None, False, False), (True, False, False), (False, True, False), (True, True, True),
])
def test_conflicting_project_configuration_is_never_retired_implicitly(
    tmp_path, monkeypatch, identity, port_open, healthy,
):
    registry = ProcessSidecarRegistry(tmp_path)
    entries = {"old": _entry(registry)}
    before = json.dumps(entries, sort_keys=True)
    monkeypatch.setattr(registry, "_lease_is_healthy", lambda lease: healthy)
    monkeypatch.setattr(registry, "_process_identity_status", lambda *args: identity)
    monkeypatch.setattr(registry, "_port_is_open", lambda port: port_open)
    with pytest.raises(SidecarCollisionError):
        registry._reject_project_entry_conflicts(entries, service_kind="notebook",
                                                 project="demo", keep_entry_id="new")
    assert json.dumps(entries, sort_keys=True) == before


def test_dead_conflict_pruning_preserves_other_projects_and_current_entry(tmp_path, monkeypatch):
    registry = ProcessSidecarRegistry(tmp_path)
    raw = _entry(registry)
    entries = {"dead": raw, "keep": raw, "other": {"project": "elsewhere"},
               "invalid": None, "other-kind": {"project": "demo", "service_kind": "other"}}
    monkeypatch.setattr(registry, "_lease_is_healthy", lambda lease: False)
    monkeypatch.setattr(registry, "_process_identity_status", lambda *args: False)
    monkeypatch.setattr(registry, "_port_is_open", lambda port: False)
    registry._reject_project_entry_conflicts(entries, service_kind="notebook",
                                             project="demo", keep_entry_id="keep")
    assert set(entries) == {"keep", "other", "invalid", "other-kind"}
    assert registry._load_entries() == entries


@pytest.mark.parametrize("raw", [None, 1, "entry", {}, {"pid": "invalid"}])
def test_registry_rejects_malformed_present_entry(tmp_path, raw):
    registry = ProcessSidecarRegistry(tmp_path)
    key = registry._entry_id("notebook", "demo", "old")
    registry._write_entries({key: raw})
    if raw is None:
        assert registry.get(service_kind="notebook", project="demo", key="old") is None
    else:
        with pytest.raises(SidecarRegistryError, match="Invalid"):
            registry.get(service_kind="notebook", project="demo", key="old")


@pytest.mark.parametrize("endpoint", ["http://example.invalid:43210", "http://0.0.0.0:43210",
                                     "http://[::1]:43210", "http://127.0.0.1"])
def test_lease_endpoint_requires_concrete_loopback_and_port(tmp_path, endpoint):
    raw = _entry(ProcessSidecarRegistry(tmp_path))
    raw["endpoint"] = endpoint
    lease = SidecarLease(**raw)
    with pytest.raises(SidecarRegistryError):
        _ = lease.port


@pytest.mark.parametrize("secret", [b"", b"short", b"x" * 31])
def test_registry_refuses_existing_truncated_secret_without_replacing_it(tmp_path, secret):
    registry = ProcessSidecarRegistry(tmp_path)
    registry.secret_path.write_bytes(secret)
    with pytest.raises(SidecarRegistryError, match="secret is invalid"):
        registry._load_secret()
    assert registry.secret_path.read_bytes() == secret
