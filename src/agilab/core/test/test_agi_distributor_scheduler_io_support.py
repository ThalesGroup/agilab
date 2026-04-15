from __future__ import annotations

import socket
from types import SimpleNamespace

import pytest

from agi_cluster.agi_distributor import scheduler_io_support


def test_find_free_port():
    port = scheduler_io_support.find_free_port(start=5000, end=6000, attempts=10)
    assert isinstance(port, int)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as stream:
        try:
            stream.bind(("localhost", port))
        except OSError as exc:
            pytest.fail(f"find_free_port returned a port that is not free: {exc}")


def test_find_free_port_raises_when_no_candidate_is_bindable(monkeypatch):
    class _FailingSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def setsockopt(self, *_args, **_kwargs):
            return None

        def bind(self, *_args, **_kwargs):
            raise OSError("busy")

    with pytest.raises(RuntimeError, match="No free port found"):
        scheduler_io_support.find_free_port(
            start=5000,
            end=5002,
            attempts=3,
            randint_fn=lambda *_a, **_k: 5001,
            socket_factory=lambda *_a, **_k: _FailingSocket(),
        )


def test_get_default_local_ip():
    ip = scheduler_io_support.get_default_local_ip()
    assert ip != "Unable to determine local IP"
    parts = ip.split(".")
    assert len(parts) == 4
    for part in parts:
        assert part.isdigit()


def test_get_default_local_ip_returns_fallback_on_failure():
    class _BrokenSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def connect(self, *_args, **_kwargs):
            raise OSError("no route")

    assert (
        scheduler_io_support.get_default_local_ip(
            socket_factory=lambda *_a, **_k: _BrokenSocket(),
        )
        == "Unable to determine local IP"
    )


def test_get_scheduler_uses_workers_first_ip_and_random_port():
    agi_cls = SimpleNamespace(_workers={"10.0.0.2": 2}, _scheduler=None)
    ip, port = scheduler_io_support.get_scheduler(
        agi_cls,
        None,
        find_free_port_fn=lambda: 6123,
        gethostbyname_fn=lambda _host: "127.0.0.1",
    )
    assert (ip, port) == ("10.0.0.2", 6123)
    assert agi_cls._scheduler == "10.0.0.2:6123"


def test_get_scheduler_uses_localhost_when_no_workers_are_defined():
    agi_cls = SimpleNamespace(_workers=None, _scheduler=None)
    ip, port = scheduler_io_support.get_scheduler(
        agi_cls,
        None,
        find_free_port_fn=lambda: 6123,
        gethostbyname_fn=lambda _host: "127.0.0.1",
    )
    assert (ip, port) == ("127.0.0.1", 6123)
    assert agi_cls._scheduler == "127.0.0.1:6123"


def test_get_scheduler_accepts_dict_with_explicit_port():
    agi_cls = SimpleNamespace(_workers=None, _scheduler=None)
    ip, port = scheduler_io_support.get_scheduler(
        agi_cls,
        {"10.1.1.1": 7788},
        find_free_port_fn=lambda: 6000,
        gethostbyname_fn=lambda _host: "127.0.0.1",
    )
    assert (ip, port) == ("10.1.1.1", 7788)
    assert agi_cls._scheduler == "10.1.1.1:7788"


def test_get_scheduler_accepts_explicit_string_ip():
    agi_cls = SimpleNamespace(_workers={"10.0.0.2": 2}, _scheduler=None)
    ip, port = scheduler_io_support.get_scheduler(
        agi_cls,
        "192.168.0.10",
        find_free_port_fn=lambda: 7001,
        gethostbyname_fn=lambda _host: "127.0.0.1",
    )
    assert (ip, port) == ("192.168.0.10", 7001)
    assert agi_cls._scheduler == "192.168.0.10:7001"


def test_get_scheduler_rejects_invalid_type():
    agi_cls = SimpleNamespace(_workers=None, _scheduler=None)
    with pytest.raises(ValueError, match="Scheduler ip address is not valid"):
        scheduler_io_support.get_scheduler(
            agi_cls,
            42,
            find_free_port_fn=lambda: 6000,
            gethostbyname_fn=lambda _host: "127.0.0.1",
        )


def test_get_stdout_captures_printed_output():
    def _fn(x, y=0):
        print(f"sum={x + y}")
        return x + y

    out, result = scheduler_io_support.get_stdout(_fn, 2, y=3)
    assert "sum=5" in out
    assert result == 5


def test_read_stderr_iterable_stream_sets_project_error_flag():
    agi_cls = SimpleNamespace(_worker_init_error=False)
    stream = [b"plain line\n", "boom [ProjectError]\n"]

    scheduler_io_support.read_stderr(agi_cls, stream, sleep_fn=lambda *_a, **_k: None)

    assert agi_cls._worker_init_error is True


def test_read_stderr_channel_stream_sets_project_error_flag():
    class _Chan:
        def __init__(self):
            self._chunks = [b"line-a\n", b"line-b [ProjectError]\n"]

        def recv_stderr_ready(self):
            return bool(self._chunks)

        def recv_stderr(self, _size):
            return self._chunks.pop(0) if self._chunks else b""

        def exit_status_ready(self):
            return not self._chunks

    agi_cls = SimpleNamespace(_worker_init_error=False)
    stream = SimpleNamespace(channel=_Chan())

    scheduler_io_support.read_stderr(agi_cls, stream, sleep_fn=lambda *_a, **_k: None)

    assert agi_cls._worker_init_error is True


def test_read_stderr_channel_handles_recv_exception():
    class _Chan:
        def __init__(self):
            self._calls = 0

        def recv_stderr_ready(self):
            return self._calls < 2

        def recv_stderr(self, _size):
            self._calls += 1
            if self._calls == 1:
                raise RuntimeError("transient read failure")
            return b"ok line\n"

        def exit_status_ready(self):
            return self._calls >= 2

    agi_cls = SimpleNamespace(_worker_init_error=False)
    scheduler_io_support.read_stderr(
        agi_cls,
        SimpleNamespace(channel=_Chan()),
        sleep_fn=lambda *_a, **_k: None,
    )

    assert agi_cls._worker_init_error is False


def test_read_stderr_channel_breaks_cleanly_on_empty_chunk():
    class _Chan:
        def recv_stderr_ready(self):
            return True

        def recv_stderr(self, _size):
            return b""

        def exit_status_ready(self):
            return False

    agi_cls = SimpleNamespace(_worker_init_error=False)

    scheduler_io_support.read_stderr(
        agi_cls,
        SimpleNamespace(channel=_Chan()),
        sleep_fn=lambda *_a, **_k: None,
    )

    assert agi_cls._worker_init_error is False


def test_read_stderr_channel_uses_decode_fallback_and_sleep_branch():
    sleeps: list[float] = []

    class _Payload:
        def __init__(self):
            self.calls: list[tuple[str, str]] = []

        def decode(self, encoding, errors="strict"):
            self.calls.append((encoding, errors))
            if encoding == "cp850" and errors == "replace":
                return "fallback line [ProjectError]\n"
            raise UnicodeDecodeError(encoding, b"\xff", 0, 1, "boom")

    payload = _Payload()

    class _Chan:
        def __init__(self):
            self._step = 0

        def recv_stderr_ready(self):
            return self._step == 1

        def recv_stderr(self, _size):
            self._step += 1
            return payload

        def exit_status_ready(self):
            return self._step >= 2

    agi_cls = SimpleNamespace(_worker_init_error=False)
    channel = _Chan()

    def _sleep(delay):
        sleeps.append(delay)
        channel._step = 1

    scheduler_io_support.read_stderr(
        agi_cls,
        SimpleNamespace(channel=channel),
        sleep_fn=_sleep,
    )

    assert sleeps == [0.1]
    assert agi_cls._worker_init_error is True
    assert payload.calls == [
        ("utf-8", "strict"),
        ("cp850", "strict"),
        ("cp1252", "strict"),
        ("cp850", "replace"),
    ]


def test_read_stderr_channel_propagates_unexpected_value_error():
    class _Chan:
        def recv_stderr_ready(self):
            return True

        def recv_stderr(self, _size):
            raise ValueError("unexpected recv bug")

        def exit_status_ready(self):
            return False

    agi_cls = SimpleNamespace(_worker_init_error=False)

    with pytest.raises(ValueError, match="unexpected recv bug"):
        scheduler_io_support.read_stderr(
            agi_cls,
            SimpleNamespace(channel=_Chan()),
            sleep_fn=lambda *_a, **_k: None,
        )
