import io
import logging
import random
import socket
import time
from contextlib import redirect_stdout
from typing import Any, Callable, Dict, Optional, Tuple, Union


logger = logging.getLogger(__name__)


def get_default_local_ip(
    *,
    socket_factory: Callable[..., Any] = socket.socket,
) -> str:
    try:
        with socket_factory(socket.AF_INET, socket.SOCK_DGRAM) as stream:
            stream.connect(("8.8.8.8", 80))
            return stream.getsockname()[0]
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


def get_scheduler(
    agi_cls: Any,
    ip_sched: Optional[Union[str, Dict[str, int]]] = None,
    *,
    find_free_port_fn: Callable[[], int],
    gethostbyname_fn: Callable[[str], str] = socket.gethostbyname,
) -> Tuple[str, int]:
    port = find_free_port_fn()
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
        ip = ip_sched
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
            except Exception:
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
            agi_cls._worker_init_error = line.endswith("[ProjectError]")
        return

    while True:
        if channel.recv_stderr_ready():
            try:
                raw = channel.recv_stderr(1024)
            except Exception:
                continue
            if not raw:
                break
            decoded = decode_bytes(raw)
            for part in decoded.splitlines():
                line = part.strip()
                log.info(line)
                agi_cls._worker_init_error = line.endswith("[ProjectError]")
        elif channel.exit_status_ready():
            break
        else:
            sleep_fn(0.1)
