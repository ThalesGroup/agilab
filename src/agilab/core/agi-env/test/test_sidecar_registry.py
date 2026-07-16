from __future__ import annotations

import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

import agi_env.ui.sidecar_registry as sidecar_registry_module

from agi_env.ui.sidecar_registry import (
    ProcessSidecarRegistry,
    SidecarCollisionError,
    SidecarRegistryBusyError,
    SidecarStartError,
)


_SERVER_CODE = """
import socket
import sys
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("127.0.0.1", int(sys.argv[1])))
sock.listen()
while True:
    conn, _ = sock.accept()
    conn.close()
"""

_NON_LISTENING_TREE_CODE = """
import pathlib
import subprocess
import sys
import time
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
pathlib.Path(sys.argv[1]).write_text(str(child.pid), encoding="utf-8")
time.sleep(120)
"""

_CLOSABLE_SERVER_CODE = """
import pathlib
import socket
import sys
import time
marker = pathlib.Path(sys.argv[2])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("127.0.0.1", int(sys.argv[1])))
sock.listen()
while not marker.exists():
    time.sleep(0.02)
sock.close()
time.sleep(120)
"""


def test_hosted_import_lease_times_out_for_peer_session() -> None:
    outcomes: list[BaseException | str] = []

    def _contender() -> None:
        try:
            with sidecar_registry_module.isolated_import_process_state(timeout=0.01):
                outcomes.append("acquired")
        except BaseException as exc:
            outcomes.append(exc)

    sidecar_registry_module.HOSTED_INLINE_RENDER_LEASE.acquire()
    try:
        thread = threading.Thread(target=_contender)
        thread.start()
        thread.join(timeout=1)
    finally:
        sidecar_registry_module.HOSTED_INLINE_RENDER_LEASE.release()

    assert not thread.is_alive()
    assert len(outcomes) == 1
    assert isinstance(outcomes[0], SidecarRegistryBusyError)


def test_preparation_thread_guard_honors_timeout(tmp_path: Path) -> None:
    registry = ProcessSidecarRegistry(tmp_path / "registry")
    outcomes: list[BaseException | str] = []

    def _contender() -> None:
        try:
            with registry.preparation_guard(
                service_kind="analysis",
                project="demo",
                key="demo",
                timeout=0.01,
            ):
                outcomes.append("acquired")
        except BaseException as exc:
            outcomes.append(exc)

    with registry.preparation_guard(
        service_kind="analysis",
        project="demo",
        key="demo",
        timeout=1,
    ):
        thread = threading.Thread(target=_contender)
        thread.start()
        thread.join(timeout=1)

    assert not thread.is_alive()
    assert len(outcomes) == 1
    assert isinstance(outcomes[0], SidecarRegistryBusyError)


def test_file_guard_does_not_unlock_when_acquisition_times_out(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = ProcessSidecarRegistry(tmp_path / "registry")
    monkeypatch.setattr(registry, "_try_advisory_lock", lambda _handle: False)
    monkeypatch.setattr(
        registry,
        "_unlock_advisory_lock",
        lambda _handle: (_ for _ in ()).throw(
            AssertionError("unowned lock must not be released")
        ),
    )

    with pytest.raises(SidecarRegistryBusyError, match="Timed out"):
        with registry._locked_file_guard(
            registry.lock_path,
            timeout=0,
            purpose="test",
        ):
            raise AssertionError("unavailable lock unexpectedly acquired")


def _launcher(processes: list[subprocess.Popen[bytes]], calls: list[int]):
    def launch(port: int, _token: str) -> subprocess.Popen[bytes]:
        calls.append(port)
        process = subprocess.Popen(
            [sys.executable, "-c", _SERVER_CODE, str(port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        processes.append(process)
        return process

    return launch


def _stop(processes: list[subprocess.Popen[bytes]]) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)


def _process_is_live(pid: int) -> bool:
    try:
        process = psutil.Process(pid)
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except (psutil.Error, OSError):
        return False


@pytest.mark.parametrize(
    ("family", "bind_address", "expected"),
    [
        pytest.param(socket.AF_INET, "127.0.0.1", True, id="ipv4-loopback"),
        pytest.param(socket.AF_INET, "0.0.0.0", False, id="ipv4-wildcard"),
        pytest.param(socket.AF_INET, "192.0.2.10", False, id="ipv4-lan"),
        pytest.param(socket.AF_INET6, "::1", False, id="ipv6-loopback-mismatch"),
    ],
)
def test_process_endpoint_ownership_requires_exact_ipv4_loopback_bind(
    monkeypatch,
    family,
    bind_address,
    expected,
):
    port = 50123
    connection = SimpleNamespace(
        family=family,
        laddr=SimpleNamespace(ip=bind_address, port=port),
        status="LISTEN",
    )
    process = SimpleNamespace(net_connections=lambda *, kind: [connection])
    monkeypatch.setattr(
        ProcessSidecarRegistry,
        "_process_tree",
        classmethod(lambda _cls, _pid, _started_at: [process]),
    )

    assert ProcessSidecarRegistry._process_owns_endpoint(
        123,
        456.0,
        "127.0.0.1",
        port,
    ) is expected


def test_registry_reuses_one_verified_process_and_token(tmp_path):
    registry = ProcessSidecarRegistry(tmp_path / "registry")
    processes: list[subprocess.Popen[bytes]] = []
    calls: list[int] = []
    try:
        first = registry.ensure(
            service_kind="notebook",
            project="alpha_project",
            key="analysis.ipynb",
            launcher=_launcher(processes, calls),
            token="owned-token",
            timeout=5,
        )
        second = registry.ensure(
            service_kind="notebook",
            project="alpha_project",
            key="analysis.ipynb",
            launcher=lambda *_args: (_ for _ in ()).throw(AssertionError("must reuse")),
            token="different-session-token",
            timeout=5,
        )

        assert calls == [first.port]
        assert second == first
        assert second.token == "owned-token"
        assert registry.lock_path.exists()
    finally:
        _stop(processes)


def test_registry_secret_publication_failure_leaves_no_partial_secret(
    tmp_path,
    monkeypatch,
):
    registry = ProcessSidecarRegistry(tmp_path / "registry")
    real_replace = sidecar_registry_module.os.replace

    def fail_secret_replace(source, destination):
        if Path(destination) == registry.secret_path:
            raise OSError("simulated secret publication failure")
        return real_replace(source, destination)

    monkeypatch.setattr(sidecar_registry_module.os, "replace", fail_secret_replace)
    with pytest.raises(OSError, match="simulated secret publication failure"):
        registry._load_secret()

    assert not registry.secret_path.exists()
    assert list(registry.root.glob(f".{registry.secret_path.name}.*.tmp")) == []


def test_registry_serializes_concurrent_launchers_without_replacing_lock_file(tmp_path):
    registry = ProcessSidecarRegistry(tmp_path / "registry")
    processes: list[subprocess.Popen[bytes]] = []
    calls: list[int] = []
    barrier = threading.Barrier(3)
    results = []
    errors = []

    def worker() -> None:
        barrier.wait()
        try:
            results.append(
                registry.ensure(
                    service_kind="analysis-view",
                    project="alpha_project",
                    key="view_maps",
                    launcher=_launcher(processes, calls),
                    timeout=5,
                )
            )
        except BaseException as exc:  # pragma: no cover - surfaced by assertion
            errors.append(exc)

    threads = [threading.Thread(target=worker), threading.Thread(target=worker)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=10)

    try:
        assert errors == []
        assert len(results) == 2
        assert len(calls) == 1
        assert results[0] == results[1]
        assert registry.lock_path.exists()
    finally:
        _stop(processes)


def test_registry_does_not_block_disjoint_service_while_launcher_waits(tmp_path):
    registry = ProcessSidecarRegistry(tmp_path / "registry")
    processes: list[subprocess.Popen[bytes]] = []
    calls: list[int] = []
    slow_launcher_entered = threading.Event()
    release_slow_launcher = threading.Event()
    fast_service_finished = threading.Event()
    results = {}
    errors = []

    def slow_launcher(port: int, token: str) -> subprocess.Popen[bytes]:
        slow_launcher_entered.set()
        if not release_slow_launcher.wait(timeout=5):
            raise RuntimeError("timed out waiting to release slow launcher")
        return _launcher(processes, calls)(port, token)

    def ensure_slow_service() -> None:
        try:
            results["slow"] = registry.ensure(
                service_kind="notebook",
                project="alpha_project",
                key="analysis.ipynb",
                launcher=slow_launcher,
                timeout=5,
            )
        except BaseException as exc:  # pragma: no cover - surfaced by assertion
            errors.append(exc)

    def ensure_fast_service() -> None:
        try:
            results["fast"] = registry.ensure(
                service_kind="mlflow",
                project="alpha_project",
                key="tracking",
                launcher=_launcher(processes, calls),
                timeout=5,
            )
        except BaseException as exc:  # pragma: no cover - surfaced by assertion
            errors.append(exc)
        finally:
            fast_service_finished.set()

    slow_thread = threading.Thread(target=ensure_slow_service)
    fast_thread = threading.Thread(target=ensure_fast_service)
    slow_thread.start()
    assert slow_launcher_entered.wait(timeout=2)
    fast_thread.start()

    try:
        assert fast_service_finished.wait(timeout=3), (
            "an unrelated service launch was blocked by the slow launcher"
        )
        assert slow_thread.is_alive()
    finally:
        release_slow_launcher.set()
        slow_thread.join(timeout=10)
        fast_thread.join(timeout=10)

    try:
        assert not slow_thread.is_alive()
        assert not fast_thread.is_alive()
        assert errors == []
        assert registry.get(
            service_kind="notebook",
            project="alpha_project",
            key="analysis.ipynb",
        ) == results["slow"]
        assert registry.get(
            service_kind="mlflow",
            project="alpha_project",
            key="tracking",
        ) == results["fast"]
    finally:
        _stop(processes)


def test_registry_fails_closed_for_live_owned_process_without_listener(tmp_path):
    registry = ProcessSidecarRegistry(tmp_path / "registry")
    marker = tmp_path / "close-listener"
    processes: list[subprocess.Popen[bytes]] = []

    def launch(port: int, _token: str) -> subprocess.Popen[bytes]:
        process = subprocess.Popen(
            [sys.executable, "-c", _CLOSABLE_SERVER_CODE, str(port), str(marker)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        processes.append(process)
        return process

    try:
        lease = registry.ensure(
            service_kind="analysis-view",
            project="alpha_project",
            key="view",
            launcher=launch,
            timeout=5,
        )
        marker.touch()
        deadline = time.monotonic() + 3
        while registry._port_is_open(lease.port) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not registry._port_is_open(lease.port)
        assert processes[0].poll() is None

        with pytest.raises(SidecarCollisionError, match="still live"):
            registry.ensure(
                service_kind="analysis-view",
                project="alpha_project",
                key="view",
                launcher=lambda *_args: (_ for _ in ()).throw(
                    AssertionError("must not launch replacement")
                ),
                timeout=1,
            )
    finally:
        _stop(processes)


def test_registry_reaps_listener_when_registry_publication_fails(tmp_path, monkeypatch):
    registry = ProcessSidecarRegistry(tmp_path / "registry")
    processes: list[subprocess.Popen[bytes]] = []
    calls: list[int] = []
    monkeypatch.setattr(
        registry,
        "_write_entries",
        lambda _entries: (_ for _ in ()).throw(OSError("registry write failed")),
    )

    with pytest.raises(OSError, match="registry write failed"):
        registry.ensure(
            service_kind="analysis-view",
            project="alpha_project",
            key="view",
            launcher=_launcher(processes, calls),
            timeout=5,
        )

    assert len(processes) == 1
    assert processes[0].poll() is not None
    assert not registry._port_is_open(calls[0])
    assert not registry.registry_path.exists()


def test_registry_interrupt_during_endpoint_wait_reaps_process_and_reraises(
    tmp_path,
    monkeypatch,
):
    registry = ProcessSidecarRegistry(tmp_path / "registry")
    processes: list[subprocess.Popen[bytes]] = []
    calls: list[int] = []
    cleanup_calls = []
    real_terminate = registry._terminate_process

    def interrupt_endpoint_wait(*_args) -> bool:
        raise KeyboardInterrupt("operator interrupted sidecar wait")

    def record_termination(process, **kwargs) -> None:
        cleanup_calls.append((process, kwargs))
        real_terminate(process, **kwargs)

    monkeypatch.setattr(registry, "_process_owns_endpoint", interrupt_endpoint_wait)
    monkeypatch.setattr(registry, "_terminate_process", record_termination)

    try:
        with pytest.raises(KeyboardInterrupt, match="operator interrupted sidecar wait"):
            registry.ensure(
                service_kind="analysis-view",
                project="alpha_project",
                key="interrupted-view",
                launcher=_launcher(processes, calls),
                timeout=5,
            )

        assert len(processes) == 1
        assert len(cleanup_calls) == 1
        assert cleanup_calls[0][0] is processes[0]
        assert cleanup_calls[0][1]["root_pid"] == processes[0].pid
        assert processes[0].poll() is not None
        assert not registry._port_is_open(calls[0])
        assert not registry.registry_path.exists()
    finally:
        _stop(processes)


def test_registry_unexpected_identity_failure_reaps_process_and_reraises(
    tmp_path,
    monkeypatch,
):
    registry = ProcessSidecarRegistry(tmp_path / "registry")
    processes: list[subprocess.Popen[bytes]] = []
    calls: list[int] = []
    cleanup_calls = []
    real_terminate = registry._terminate_process
    real_psutil_process = sidecar_registry_module.psutil.Process

    def fail_identity(pid: int):
        if processes and pid == processes[0].pid:
            raise RuntimeError("unexpected process identity failure")
        return real_psutil_process(pid)

    def record_termination(process, **kwargs) -> None:
        cleanup_calls.append((process, kwargs))
        real_terminate(process, **kwargs)

    monkeypatch.setattr(sidecar_registry_module.psutil, "Process", fail_identity)
    monkeypatch.setattr(registry, "_terminate_process", record_termination)

    try:
        with pytest.raises(RuntimeError, match="unexpected process identity failure"):
            registry.ensure(
                service_kind="analysis-view",
                project="alpha_project",
                key="identity-failure-view",
                launcher=_launcher(processes, calls),
                timeout=5,
            )

        assert len(processes) == 1
        assert len(cleanup_calls) == 1
        assert cleanup_calls[0][0] is processes[0]
        processes[0].wait(timeout=3)
        assert not registry._port_is_open(calls[0])
        assert not registry.registry_path.exists()
    finally:
        _stop(processes)


def test_registry_replaces_verified_obsolete_project_configuration(tmp_path):
    registry = ProcessSidecarRegistry(tmp_path / "registry")
    processes: list[subprocess.Popen[bytes]] = []
    calls: list[int] = []
    try:
        first = registry.ensure(
            service_kind="gpt-oss",
            project="alpha_project",
            key="config-a",
            launcher=_launcher(processes, calls),
            timeout=5,
        )
        second = registry.ensure(
            service_kind="gpt-oss",
            project="alpha_project",
            key="config-b",
            launcher=_launcher(processes, calls),
            replace_existing_for_project=True,
            timeout=5,
        )

        assert first.token != second.token
        assert processes[0].poll() is not None
        assert processes[1].poll() is None
        assert registry.get(
            service_kind="gpt-oss",
            project="alpha_project",
            key="config-a",
        ) is None
        assert registry.get(
            service_kind="gpt-oss",
            project="alpha_project",
            key="config-b",
        ) == second
    finally:
        _stop(processes)


def test_registry_exclusive_configuration_does_not_kill_another_session(
    tmp_path,
):
    registry = ProcessSidecarRegistry(tmp_path / "registry")
    processes: list[subprocess.Popen[bytes]] = []
    calls: list[int] = []
    try:
        first = registry.ensure(
            service_kind="gpt-oss",
            project="alpha_project",
            key="config-a",
            launcher=_launcher(processes, calls),
            timeout=5,
        )

        with pytest.raises(
            SidecarCollisionError,
            match="refusing to replace another session's service",
        ):
            registry.ensure(
                service_kind="gpt-oss",
                project="alpha_project",
                key="config-b",
                launcher=_launcher(processes, calls),
                exclusive_for_project=True,
                timeout=5,
            )

        assert len(processes) == 1
        assert processes[0].poll() is None
        assert registry.get(
            service_kind="gpt-oss",
            project="alpha_project",
            key="config-a",
        ) == first
        assert registry.get(
            service_kind="gpt-oss",
            project="alpha_project",
            key="config-b",
        ) is None
    finally:
        _stop(processes)


def test_registry_fails_closed_when_live_listener_replaces_registered_pid(tmp_path):
    registry = ProcessSidecarRegistry(tmp_path / "registry")
    processes: list[subprocess.Popen[bytes]] = []
    calls: list[int] = []
    lease = registry.ensure(
        service_kind="analysis-view",
        project="alpha_project",
        key="view_maps",
        launcher=_launcher(processes, calls),
        timeout=5,
    )
    _stop(processes)

    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", lease.port))
            listener.listen()
            break
        except OSError:
            listener.close()
            time.sleep(0.05)
    else:  # pragma: no cover - platform refused timely port reuse
        pytest.skip("could not reuse released loopback port")

    try:
        with pytest.raises(SidecarCollisionError, match="no longer matches"):
            registry.get(
                service_kind="analysis-view",
                project="alpha_project",
                key="view_maps",
            )
    finally:
        listener.close()


def test_registry_start_failure_stops_only_observed_launcher_descendants(tmp_path):
    registry = ProcessSidecarRegistry(tmp_path / "registry")
    child_pid_path = tmp_path / "child.pid"
    launched: list[subprocess.Popen[bytes]] = []

    def launch(_port: int, _token: str) -> subprocess.Popen[bytes]:
        process = subprocess.Popen(
            [sys.executable, "-c", _NON_LISTENING_TREE_CODE, str(child_pid_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        launched.append(process)
        return process

    with pytest.raises(SidecarStartError, match="did not prove ownership"):
        registry.ensure(
            service_kind="analysis-view",
            project="alpha_project",
            key="broken-view",
            launcher=launch,
            timeout=0.8,
        )

    assert len(launched) == 1
    assert launched[0].poll() is not None
    assert child_pid_path.exists()
    child_pid = int(Path(child_pid_path).read_text(encoding="utf-8"))
    deadline = time.monotonic() + 3
    while _process_is_live(child_pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _process_is_live(child_pid)
