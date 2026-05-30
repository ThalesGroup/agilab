from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from agi_env.host_runtime_support import (
    check_internet_connectivity,
    create_symlink,
    is_local_ip,
)


def test_create_symlink_uses_windows_junction_fallback(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    dest = tmp_path / "dest"
    calls = []

    monkeypatch.setattr(
        type(dest),
        "symlink_to",
        lambda self, *_args, **_kwargs: (_ for _ in ()).throw(OSError("denied")),
        raising=False,
    )

    assert create_symlink(
        src,
        dest,
        logger=mock.Mock(),
        os_name="nt",
        create_junction_windows_fn=lambda source, target: calls.append((source, target)) or True,
    )
    assert calls == [(src, dest)]


def test_is_local_ip_caches_matched_interface():
    cache = set()
    addrs = {"en0": [SimpleNamespace(family="inet", address="192.168.1.10")]}

    assert is_local_ip(
        "192.168.1.10",
        cache=cache,
        net_if_addrs_fn=lambda: addrs,
        inet_family="inet",
    )
    assert "192.168.1.10" in cache
    assert is_local_ip(
        "",
        cache=cache,
        net_if_addrs_fn=lambda: {},
        inet_family="inet",
    )


def test_check_internet_connectivity_reports_success_and_failure():
    logger = mock.Mock()

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    assert check_internet_connectivity(
        logger=logger,
        request_factory=lambda url, method: (url, method),
        urlopen_fn=lambda *_args, **_kwargs: _Response(),
    )

    def _raise(*_args, **_kwargs):
        raise OSError("offline")

    assert not check_internet_connectivity(
        logger=logger,
        request_factory=lambda url, method: (url, method),
        urlopen_fn=_raise,
    )
    assert logger.error.called
