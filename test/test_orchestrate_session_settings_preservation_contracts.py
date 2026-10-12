"""Session-owned settings survive writes without sharing mutable objects."""

from copy import deepcopy
import tomllib

import pytest

from agilab.orchestrate.orchestrate_support import _preserve_app_settings_paths
from agilab.orchestrate import orchestrate_support as support


@pytest.mark.parametrize("path", [(), ("",), ("args", 1), ("args", "")])
def test_invalid_preservation_paths_reject_without_mutating_inputs(path):
    latest = {"args": {"values": ["disk"]}}
    session = {"args": {"values": ["session"]}}
    before = deepcopy((latest, session))
    with pytest.raises(ValueError, match="non-empty strings"):
        _preserve_app_settings_paths(latest, session, (path,))
    assert (latest, session) == before


def test_only_present_session_owned_paths_override_persisted_values():
    latest = {"args": "obsolete scalar", "cluster": {"scheduler": "disk", "workers": ["disk-worker"]}}
    session = {"args": {"samples": [1, 2], "enabled": False}, "cluster": {"scheduler": None}, "secret": "not owned"}
    before = deepcopy((latest, session))
    result = _preserve_app_settings_paths(latest, session, (
        ("args", "samples"), ("args", "enabled"), ("cluster", "scheduler"), ("missing",), ("cluster", "unknown"),
    ))
    assert result == {"args": {"samples": [1, 2], "enabled": False}, "cluster": {"scheduler": None, "workers": ["disk-worker"]}}
    assert "secret" not in result
    assert (latest, session) == before
    result["args"]["samples"].append(3)
    result["cluster"]["workers"].append("another-worker")
    assert (latest, session) == before


@pytest.mark.parametrize("source", [{}, {"cluster": None}, {"cluster": {"scheduler": 42}}])
def test_missing_or_non_mapping_session_parent_preserves_persisted_settings(source):
    latest = {"cluster": {"scheduler": {"host": "persisted"}}, "args": [1]}
    result = _preserve_app_settings_paths(latest, source, (("cluster", "scheduler", "host"),))
    assert result == latest
    assert result is not latest
    result["args"].append(2)
    assert latest["args"] == [1]


def test_a_settings_writer_must_declare_ownership_or_defaults_before_a_transaction(tmp_path):
    destination = tmp_path / "app_settings.toml"
    payload = {"args": {"seed": 7}}
    with pytest.raises(ValueError, match="ownership or default path"):
        support.owned_app_settings_payload(payload)
    assert not destination.exists() and payload == {"args": {"seed": 7}}
    defaults = support.owned_app_settings_payload(payload, default_paths=(("args", "seed"),))
    support.write_app_settings_toml(destination, defaults)
    assert tomllib.loads(destination.read_text())["args"]["seed"] == 7


@pytest.mark.parametrize("key", ["", 1])
def test_changed_leaf_ownership_rejects_unaddressable_mapping_keys(key):
    before = {"args": {key: 1}}
    after = {"args": {key: 2}}
    snapshots = deepcopy((before, after))
    with pytest.raises(ValueError, match="non-empty string keys"):
        support.changed_app_settings_paths(before, after)
    assert (before, after) == snapshots
    assert support.changed_app_settings_paths({"args": {"seed": 1}}, {"args": {"seed": 2}}) == (("args", "seed"),)


def test_changed_leaf_ownership_refuses_a_root_replacement_without_an_owned_path():
    with pytest.raises(ValueError, match="paths cannot be empty"):
        support.changed_app_settings_paths({"args": {}}, ["corrupt replacement"])
    assert support.changed_app_settings_paths({"args": 1}, {"args": 2}) == (("args",),)


def test_non_table_write_and_future_persisted_metadata_never_replace_the_existing_source(tmp_path):
    destination = tmp_path / "app_settings.toml"
    original = '[__meta__]\nschema = "agilab.app_settings.v2"\nversion = 2\n\n[args]\nseed = 7\n'
    destination.write_text(original)
    with pytest.raises(ValueError, match="TOML table"):
        support.write_app_settings_toml(destination, ["not a table"])
    assert destination.read_text() == original
    update = support.owned_app_settings_payload({"args": {"seed": 42}}, ("args", "seed"))
    with pytest.raises(ValueError, match="Unsupported app_settings.toml schema version 2"):
        support.write_app_settings_toml(destination, update)
    assert destination.read_text() == original
