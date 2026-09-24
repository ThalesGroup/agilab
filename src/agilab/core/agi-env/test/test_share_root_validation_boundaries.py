"""Share-root validation rejects ambiguous roots and handles filesystem probe errors."""
from pathlib import Path
from unittest.mock import Mock

import pytest

from agi_env.shares import share_runtime_support as share


@pytest.mark.parametrize("value", [
    "", " ", "bad\x00path", "/", ".", "~", "/home", "/home/alice",
    "/users/alice", "/var/root", "/usr", "data/../escape", "C:relative", "C:\\share",
    "\\\\server\\share",
])
def test_worker_share_root_requires_dedicated_posix_directory(value):
    with pytest.raises(ValueError, match="Workers Data Path"):
        share.validate_worker_share_root(value)


@pytest.mark.parametrize("value", ["data/session", "/mnt/team/session", "~/clustershare", "/home/alice/experiment"])
def test_dedicated_worker_share_root_is_preserved_without_local_rebasing(value):
    assert share.validate_worker_share_root(value) == value


def test_share_root_probe_failure_does_not_authorize_outside_path(tmp_path, monkeypatch):
    root = tmp_path / "share"
    outside = tmp_path / "outside"
    root.mkdir()
    real_exists = Path.exists
    def exists(path):
        if path == root:
            raise OSError("share inaccessible")
        return real_exists(path)
    monkeypatch.setattr(Path, "exists", exists)
    assert share._path_is_within_share_root(outside, root) is False


def test_alias_identity_probe_failure_does_not_authorize_sibling_path(tmp_path, monkeypatch):
    root = tmp_path / "share"
    root.mkdir()
    monkeypatch.setattr(Path, "samefile", Mock(side_effect=OSError("identity unavailable")))
    assert share._path_is_within_share_root(tmp_path / "sibling", root) is False


@pytest.mark.parametrize("value", ["", "bad\x00path"])
def test_local_share_root_requires_nonempty_text(value):
    with pytest.raises(ValueError, match="dedicated local directory"):
        share.validate_local_share_root(value)


def test_local_share_home_probe_error_preserves_distinct_dedicated_root(tmp_path, monkeypatch):
    candidate, home = tmp_path / "share", tmp_path / "home"
    candidate.mkdir()
    home.mkdir()
    monkeypatch.setattr(Path, "samefile", Mock(side_effect=OSError("identity inaccessible")))
    assert share.validate_local_share_root(candidate, home_roots=("", home)) == candidate.resolve()


def test_physical_share_fallback_must_exist_for_absolute_input(tmp_path):
    workflow, physical = tmp_path / "workflow", tmp_path / "physical"
    workflow.mkdir()
    physical.mkdir()
    with pytest.raises(ValueError, match="inside"):
        share.resolve_share_input_path(physical / "missing.csv", workflow, physical)
