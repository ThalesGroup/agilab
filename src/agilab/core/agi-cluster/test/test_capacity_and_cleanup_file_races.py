"""Capacity deserialization and cleanup evidence remain safe across filesystem races."""
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agi_cluster.agi_distributor.runtime import runtime_misc_support as capacity
from agi_cluster.agi_distributor.runtime import cleanup_support as cleanup


@pytest.fixture(autouse=True)
def trusted_permission_boundary(monkeypatch):
    # These tests isolate filesystem identity/IO from platform ACL providers.
    # POSIX mode and Windows DACL decisions have their own contract suites.
    monkeypatch.setattr(capacity, "_capacity_entry_error", lambda *_args, **_kwargs: None)


@pytest.fixture
def model(tmp_path):
    root = tmp_path / "trusted"
    root.mkdir(mode=0o700)
    model = root / "model.pkl"
    model.write_bytes(b"not deserialized by trust tests")
    model.chmod(0o600)
    return root, model


@pytest.mark.parametrize("kind,expected", [
    ("missing_root", "cannot stat trusted ancestor"),
    ("ancestor_file", "not a directory"), ("ancestor_symlink", "ancestor is a symlink"),
    ("missing_model", "model file is missing"), ("model_directory", "not a regular file"),
    ("model_symlink", "model file is a symlink"), ("outside", "outside trusted resource root"),
])
def test_capacity_model_trust_rejects_unsafe_path_shape(tmp_path, kind, expected):
    root = tmp_path / "trusted"
    root.mkdir(mode=0o700)
    target = root / "model.pkl"
    if kind == "missing_root":
        root = tmp_path / "missing"
        target = root / "model.pkl"
    elif kind == "ancestor_file":
        ancestor = root / "nested"
        ancestor.write_text("not directory")
        target = ancestor / "model.pkl"
    elif kind == "ancestor_symlink":
        actual = tmp_path / "actual"
        actual.mkdir()
        (root / "nested").symlink_to(actual, target_is_directory=True)
        target = root / "nested" / "model.pkl"
    elif kind == "model_directory":
        target.mkdir()
    elif kind == "model_symlink":
        actual = tmp_path / "actual.pkl"
        actual.write_text("fixture")
        target.symlink_to(actual)
    elif kind == "outside":
        target = tmp_path / "outside.pkl"
    error = capacity._capacity_file_trust_error(target, root, label="model file")
    assert expected in error


def test_capacity_model_open_detects_replacement_between_validation_and_open(monkeypatch, model):
    root, path = model
    proxy = SimpleNamespace(**{key: getattr(os, key) for key in dir(os)})
    real_open = os.open
    def replace_before_open(filename, flags):
        fd = real_open(filename, flags)
        replacement = path.with_suffix(".replacement")
        replacement.write_bytes(b"replacement generation")
        replacement.chmod(0o600)
        try:
            replacement.replace(path)
        except OSError:
            os.close(fd)
            raise
        return fd
    proxy.open = replace_before_open
    monkeypatch.setattr(capacity, "os", proxy)
    stream, stat_result, error = capacity._open_trusted_capacity_file(path, root, label="model file")
    assert stream is stat_result is None
    if "changed while it was being opened" in error:
        assert path.read_bytes() == b"replacement generation"
    else:
        # Windows may deny replacing an open file before descriptor comparison.
        assert "cannot open model file safely" in error
        assert path.read_bytes() == b"not deserialized by trust tests"


def test_capacity_model_open_rechecks_permissions_on_open_descriptor(monkeypatch, model):
    root, path = model
    proxy = SimpleNamespace(**{key: getattr(os, key) for key in dir(os)})
    real_open = os.open
    def unsafe_after_open(filename, flags):
        fd = real_open(filename, flags)
        path.chmod(0o666)
        return fd
    proxy.open = unsafe_after_open
    monkeypatch.setattr(capacity, "_capacity_entry_error", Mock(side_effect=[
        None, None, "model file is world-writable",
    ]))
    monkeypatch.setattr(capacity, "os", proxy)
    stream, stat_result, error = capacity._open_trusted_capacity_file(path, root, label="model file")
    assert stream is stat_result is None
    assert error is not None
    assert "writable" in error


@pytest.mark.parametrize("phase", ["open", "fdopen", "fstat"])
def test_capacity_open_failures_close_allocated_descriptors(monkeypatch, model, phase):
    root, path = model
    proxy = SimpleNamespace(**{key: getattr(os, key) for key in dir(os)})
    opened = []
    streams = []
    real_open, real_fdopen = os.open, os.fdopen
    def observed_open(*args):
        fd = real_open(*args)
        opened.append(fd)
        return fd
    def observed_fdopen(*args):
        stream = real_fdopen(*args)
        streams.append(stream)
        return stream
    proxy.open = observed_open
    proxy.fdopen = observed_fdopen
    setattr(proxy, phase, Mock(side_effect=OSError("injected " + phase + " failure")))
    monkeypatch.setattr(capacity, "os", proxy)
    stream, stat_result, error = capacity._open_trusted_capacity_file(path, root, label="model file")
    assert stream is stat_result is None
    assert "cannot open model file safely" in error
    assert all(stream.closed for stream in streams)
    for fd in opened:
        with pytest.raises(OSError):
            os.fstat(fd)


def test_pid_snapshot_skips_gone_file_but_preserves_existing_bytes(tmp_path):
    path = tmp_path / "worker.pid"
    path.write_bytes(b'{"pid": 123, "created": 1}')
    assert cleanup._snapshot_pid_evidence([tmp_path / "gone.pid", path]) == {path: path.read_bytes()}


def test_pid_snapshot_read_failure_stops_cleanup(monkeypatch, tmp_path):
    path = tmp_path / "worker.pid"
    original = Path.read_bytes
    def denied(candidate):
        if candidate == path:
            raise PermissionError("denied")
        return original(candidate)
    monkeypatch.setattr(Path, "read_bytes", denied)
    with pytest.raises(RuntimeError, match="Cannot preserve PID ownership"):
        cleanup._snapshot_pid_evidence([path])


def test_pid_evidence_restore_never_overwrites_new_generation(tmp_path):
    existing = tmp_path / "existing.pid"
    existing.write_bytes(b"new generation")
    missing = tmp_path / "nested" / "missing.pid"
    cleanup._restore_pid_evidence({existing: b"old generation", missing: b"recoverable"})
    assert existing.read_bytes() == b"new generation"
    assert missing.read_bytes() == b"recoverable"
    assert not list(tmp_path.rglob("*.tmp"))


def test_pid_evidence_restore_attempts_every_file_and_reports_publication_failure(monkeypatch, tmp_path):
    failed, succeeds = tmp_path / "failed.pid", tmp_path / "succeeds.pid"
    proxy = SimpleNamespace(**{key: getattr(os, key) for key in dir(os)})
    original = os.replace
    def fail_selected(src, dst):
        if dst == failed:
            raise OSError("publication denied")
        return original(src, dst)
    proxy.replace = fail_selected
    monkeypatch.setattr(cleanup, "os", proxy)
    with pytest.raises(RuntimeError, match="could not be restored"):
        cleanup._restore_pid_evidence({failed: b"failed evidence", succeeds: b"retained evidence"})
    assert not failed.exists()
    assert succeeds.read_bytes() == b"retained evidence"
    assert not list(tmp_path.glob("*.tmp"))
