import io
import logging
import random
import socket
import time
from contextlib import redirect_stdout
from typing import Any, Callable, Dict, Optional, Tuple, Union

from agi_cluster.agi_distributor.deployment import deployment_remote_support


logger = logging.getLogger(__name__)

# Dask's standard scheduler port. Kept fixed so firewall rules stay valid;
# override with AGI.run(..., scheduler="ip:port") or a scheduler port range.
DEFAULT_SCHEDULER_PORT = 8786

_DECODE_BYTES_EXCEPTIONS = (UnicodeDecodeError,)
_READ_STDERR_RETRY_EXCEPTIONS = (OSError, RuntimeError)


def _parse_scheduler_string(raw_scheduler: str) -> tuple[str, Optional[int]]:
    scheduler = raw_scheduler.strip()
    if "://" in scheduler:
        scheduler = scheduler.split("://", 1)[1]
    if "/" in scheduler:
        scheduler = scheduler.split("/", 1)[0]
    if "@" in scheduler:
        scheduler = scheduler.rsplit("@", 1)[1]

    if scheduler.startswith("["):
        host_end = scheduler.find("]")
        if host_end == -1:
            raise ValueError("Scheduler address is not valid")
        host = scheduler[1:host_end]
        remainder = scheduler[host_end + 1 :]
        if not remainder:
            return host, None
        if remainder.startswith(":") and remainder[1:].isdigit():
            return host, _validate_scheduler_port(remainder[1:])
        raise ValueError("Scheduler address is not valid")

    if scheduler.count(":") == 1:
        host, port_text = scheduler.rsplit(":", 1)
        if host and port_text.isdigit():
            return host, _validate_scheduler_port(port_text)
        if host and port_text:
            raise ValueError("Scheduler port is not valid")

    return scheduler, None


def _validate_scheduler_port(port_text: str) -> int:
    port = int(port_text)
    if not 0 < port < 65536:
        raise ValueError("Scheduler port is not valid")
    return port


def get_default_local_ip(
    *,
    socket_factory: Callable[..., Any] = socket.socket,
) -> str:
    try:
        with socket_factory(socket.AF_INET, socket.SOCK_DGRAM) as stream:
            stream.connect(("8.8.8.8", 80))
            return str(stream.getsockname()[0])
    except OSError:
        return "Unable to determine local IP"


def find_free_port(
    *,
    start: int = 5000,
    end: int = 10000,
    attempts: int = 100,
    randint_fn: Callable[[int, int], int] = random.randint,
    socket_factory: Callable[..., Any] = socket.socket,
) -> int:
    for _ in range(attempts):
        port = randint_fn(start, end)
        with socket_factory(socket.AF_INET, socket.SOCK_STREAM) as stream:
            stream.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                stream.bind(("localhost", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free port found in the specified range.")


def scheduler_port_range(env: Any) -> Optional[Tuple[int, int]]:
    """Optional fixed port range for the dask scheduler (firewall pinning).

    Accepts a single port ("8786") or an inclusive range ("8786:8790"). The
    range's first port becomes the default scheduler port; the remaining ports
    are fallbacks when it is busy. An explicit AGI.run(..., scheduler="ip:port")
    still wins.
    """
    raw = deployment_remote_support._env_lookup(
        env,
        "AGILAB_DASK_SCHEDULER_PORT_RANGE",
        "DASK_SCHEDULER_PORT_RANGE",
        "dask_scheduler_port_range",
    )
    if raw in (None, ""):
        return None
    text = str(raw).strip()
    parts = text.split(":")
    if len(parts) not in (1, 2):
        raise ValueError(f"Invalid dask scheduler port range: {raw!r}")
    try:
        ports = [int(part.strip()) for part in parts]
    except ValueError as exc:
        raise ValueError(f"Invalid dask scheduler port range: {raw!r}") from exc
    if any(not 1 <= port <= 65535 for port in ports):
        raise ValueError(f"Invalid dask scheduler port range: {raw!r}")
    if len(ports) == 1:
        return ports[0], ports[0]
    if ports[0] > ports[1]:
        raise ValueError(f"Invalid dask scheduler port range: {raw!r}")
    return ports[0], ports[1]


def get_scheduler(
    agi_cls: Any,
    ip_sched: Optional[Union[str, Dict[str, int]]] = None,
    *,
    gethostbyname_fn: Callable[[str], str] = socket.gethostbyname,
) -> Tuple[str, int]:
    port_range = scheduler_port_range(getattr(agi_cls, "env", None))
    port = port_range[0] if port_range else DEFAULT_SCHEDULER_PORT
    if not ip_sched:
        if agi_cls._workers:
            ip = list(agi_cls._workers)[0]
        else:
            ip = gethostbyname_fn("localhost")
    elif isinstance(ip_sched, dict):
        ip, port = list(ip_sched.items())[0]
    elif not isinstance(ip_sched, str):
        raise ValueError("Scheduler ip address is not valid")
    else:
        ip, explicit_port = _parse_scheduler_string(ip_sched)
        if explicit_port is not None:
            port = explicit_port
    agi_cls._scheduler = f"{ip}:{port}"
    return ip, port


def get_stdout(func: Any, *args: Any, **kwargs: Any) -> Tuple[str, Any]:
    stream = io.StringIO()
    with redirect_stdout(stream):
        result = func(*args, **kwargs)
    return stream.getvalue(), result


def read_stderr(
    agi_cls: Any,
    output_stream: Any,
    *,
    sleep_fn: Callable[[float], Any] = time.sleep,
    log: Any = logger,
) -> None:
    def decode_bytes(payload: bytes) -> str:
        for encoding in ("utf-8", "cp850", "cp1252"):
            try:
                return payload.decode(encoding)
            except _DECODE_BYTES_EXCEPTIONS:
                continue
        return payload.decode("cp850", errors="replace")

    channel = getattr(output_stream, "channel", None)
    if channel is None:
        for raw in output_stream:
            if isinstance(raw, bytes):
                decoded = decode_bytes(raw)
            else:
                decoded = decode_bytes(raw.encode("latin-1", errors="replace"))
            line = decoded.strip()
            log.info(line)
            # Sticky flag: stderr lines after the marker (tracebacks, blanks)
            # must not reset a detected worker init error.
            if line.endswith("[ProjectError]"):
                agi_cls._worker_init_error = True
        return

    while True:
        if channel.recv_stderr_ready():
            try:
                raw = channel.recv_stderr(1024)
            except _READ_STDERR_RETRY_EXCEPTIONS:
                continue
            if not raw:
                break
            decoded = decode_bytes(raw)
            for part in decoded.splitlines():
                line = part.strip()
                log.info(line)
                if line.endswith("[ProjectError]"):
                    agi_cls._worker_init_error = True
        elif channel.exit_status_ready():
            break
        else:
            sleep_fn(0.1)
