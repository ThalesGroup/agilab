"""Confinement contracts for worker cleanup; these tests never delete files."""
from pathlib import Path
import pytest
from agi_env.runtime.destructive_path_support import (
    safe_destructive_path, safe_worker_runtime_cleanup_path,
)


@pytest.mark.parametrize("target", [None, 42, b"dir", "", " ", "bad\x00path", ".", "..", "child/../other", r"child\..\other", "C:relative"])
def test_cleanup_rejects_malformed_or_ambiguous_targets(tmp_path, target):
    with pytest.raises(ValueError):
        safe_destructive_path(target, roots=(tmp_path,))


def test_cleanup_requires_strict_descendant_of_explicit_root(tmp_path):
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    child = trusted / "new" / "environment"
    assert safe_destructive_path(child, roots=(trusted,)) == child
    for target, roots in (
        (trusted, (trusted,)),
        (tmp_path / "trusted-sibling", (trusted,)),
        (child, ()),
        (Path(tmp_path.anchor), (trusted,)),
    ):
        with pytest.raises(ValueError):
            safe_destructive_path(target, roots=roots)
    assert not child.exists()


def test_cleanup_resolves_symlinks_before_authorizing(tmp_path):
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    inside = trusted / "environment"
    inside.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (trusted / "escape").symlink_to(outside, target_is_directory=True)
    (trusted / "alias").symlink_to(inside, target_is_directory=True)
    with pytest.raises(ValueError, match="trusted root"):
        safe_destructive_path(trusted / "escape" / "data", roots=(trusted,))
    assert safe_destructive_path(trusted / "alias", roots=(trusted,)) == inside
    assert outside.is_dir() and inside.is_dir()


@pytest.mark.parametrize("protected", ["home_path", "cwd_path"])
def test_worker_cleanup_never_accepts_protected_session_directory(tmp_path, protected):
    directory = tmp_path / "session"
    directory.mkdir()
    alias = tmp_path / "session-alias"
    alias.symlink_to(directory, target_is_directory=True)
    with pytest.raises(ValueError, match="worker runtime cleanup.*protected path"):
        safe_worker_runtime_cleanup_path(alias, roots=(tmp_path,), **{protected: directory})
    assert safe_worker_runtime_cleanup_path(directory / "worker", roots=(tmp_path,),
                                            **{protected: directory}) == directory / "worker"


def test_cleanup_accepts_any_trusted_root_but_rejects_a_root_itself(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    assert safe_destructive_path(second / "worker", roots=(first, second)) == second / "worker"
    with pytest.raises(ValueError, match="confinement root"):
        safe_destructive_path(second, roots=(tmp_path, second))


def test_cleanup_resolution_failure_is_an_explicit_validation_error(tmp_path, monkeypatch):
    original = Path.resolve
    def denied(path, *args, **kwargs):
        if path == tmp_path / "denied":
            raise OSError("resolution denied")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "resolve", denied)
    with pytest.raises(ValueError, match="invalid filesystem path.*resolution denied"):
        safe_destructive_path(tmp_path / "denied", roots=(tmp_path,))
