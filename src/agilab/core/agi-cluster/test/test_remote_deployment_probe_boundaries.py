"""Remote deployment probes tolerate malformed output without inventing mount state."""
from pathlib import PurePosixPath
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agi_cluster.agi_distributor.deployment import deployment_remote_support as deployment


@pytest.mark.parametrize("source,host", [
    ("sshfs#alice@worker:/share", "worker"), ("", ""),
    ("alice@[2001:db8::1]:/share", "2001:db8::1"),
    ("[2001:db8::1]", "2001:db8::1"), ("worker", "worker"),
])
def test_sshfs_source_normalization(source, host):
    assert deployment._sshfs_source_host(source) == host


@pytest.mark.parametrize("error", [OSError("probe failed"), deployment.subprocess.TimeoutExpired("mount", 5)])
def test_mount_probe_failure_is_unknown(tmp_path, monkeypatch, error):
    monkeypatch.setattr(deployment.subprocess, "run", Mock(side_effect=error))
    assert deployment._local_mount_record_from_mount_output(tmp_path) is None


def test_bsd_mount_parser_selects_deepest_matching_mount(monkeypatch):
    # Parse BSD mount syntax independently of the manager's host path flavour.
    monkeypatch.setattr(deployment, "Path", PurePosixPath)
    source = SimpleNamespace(expanduser=lambda: SimpleNamespace(resolve=lambda **_: PurePosixPath("/share/nested/data")))
    text = (
        "malformed line\n"
        "alice@remote:/nested on /share/nested (fuse, rw)\n"
        "alice@other:/wrong on /elsewhere (fuse, rw)\n"
        "alice@root:/share on /share (fuse, rw)\n"
        "alice@duplicate:/nested on /share/nested (fuse, rw)\n"
    )
    monkeypatch.setattr(deployment.subprocess, "run", Mock(return_value=SimpleNamespace(returncode=0, stdout=text)))
    assert deployment._local_mount_record_from_mount_output(source) == {
        "TARGET": "/share/nested", "SOURCE": "alice@remote:/nested", "FSTYPE": "fuse"
    }


@pytest.mark.parametrize("phase", ["returncode", "resolve"])
def test_bsd_mount_probe_does_not_report_record_after_failed_probe(monkeypatch, phase):
    monkeypatch.setattr(deployment.subprocess, "run", Mock(return_value=SimpleNamespace(
        returncode=1 if phase == "returncode" else 0, stdout="source on /share (fuse, rw)"
    )))
    resolve = Mock(side_effect=OSError("unresolvable"))
    path = SimpleNamespace(expanduser=lambda: SimpleNamespace(resolve=resolve))
    assert deployment._local_mount_record_from_mount_output(path) is None
    if phase == "returncode":
        resolve.assert_not_called()


@pytest.mark.parametrize("output,expected", [
    ("", None), ('TARGET="unterminated', None), ("garbage", None),
    ('garbage TARGET="/share" SOURCE="alice@worker:/remote" FSTYPE="fuse.sshfs"',
     {"TARGET": "/share", "SOURCE": "alice@worker:/remote", "FSTYPE": "fuse.sshfs"}),
])
def test_findmnt_parser_rejects_invalid_fields_and_preserves_valid_record(tmp_path, monkeypatch, output, expected):
    monkeypatch.setattr(deployment.subprocess, "run", Mock(return_value=SimpleNamespace(returncode=0, stdout=output)))
    assert deployment._local_mount_record_for_path(tmp_path) == expected


@pytest.mark.parametrize("error", [OSError("findmnt failed"), deployment.subprocess.TimeoutExpired("findmnt", 5)])
def test_findmnt_runtime_failure_does_not_fall_back_to_unrelated_mounts(tmp_path, monkeypatch, error):
    monkeypatch.setattr(deployment.subprocess, "run", Mock(side_effect=error))
    fallback = Mock()
    monkeypatch.setattr(deployment, "_local_mount_record_from_mount_output", fallback)
    assert deployment._local_mount_record_for_path(tmp_path) is None
    fallback.assert_not_called()


def test_findmnt_unsuccessful_exit_does_not_parse_stale_output(tmp_path, monkeypatch):
    monkeypatch.setattr(deployment.subprocess, "run", Mock(return_value=SimpleNamespace(
        returncode=1, stdout='TARGET="/share" SOURCE="worker:/data" FSTYPE="fuse.sshfs"'
    )))
    assert deployment._local_mount_record_for_path(tmp_path) is None


@pytest.mark.parametrize("output,expected", [
    ('noise\n{bad}\n\n{"rapids_capable": true}\n', True),
    ('{"rapids_capable": true}\n{"rapids_capable": false}\n', False),
    ('prefix {"rapids_capable": true} suffix\nnoise', True),
])
def test_rapids_probe_uses_last_valid_json_record(output, expected):
    assert deployment._parse_remote_rapids_probe(output) is expected


def test_rapids_probe_without_valid_json_refuses_capability():
    with pytest.raises(ValueError, match="did not return JSON"):
        deployment._parse_remote_rapids_probe("noise\n{bad}\n\n")
