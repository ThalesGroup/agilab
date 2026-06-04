import asyncio
import errno
import getpass
import logging
import os
import shutil
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Iterable, List, Optional, cast

import asyncssh
from asyncssh.process import ProcessError

from agi_env import AgiEnv


logger = logging.getLogger(__name__)

_KNOWN_HOSTS_ENV_NAMES = (
    "AGILAB_CLUSTER_SSH_KNOWN_HOSTS",
    "AGILAB_CLUSTER_KNOWN_HOSTS",
    "AGI_CLUSTER_SSH_KNOWN_HOSTS",
    "AGI_CLUSTER_KNOWN_HOSTS",
    "cluster_ssh_known_hosts",
    "cluster_known_hosts",
)
_HOST_KEY_POLICY_ENV_NAMES = (
    "AGILAB_CLUSTER_SSH_HOST_KEY_POLICY",
    "AGILAB_CLUSTER_HOST_KEY_POLICY",
    "AGI_CLUSTER_SSH_HOST_KEY_POLICY",
    "AGI_CLUSTER_HOST_KEY_POLICY",
    "AGILAB_CLUSTER_SSH_STRICT_HOST_KEY_CHECKING",
    "cluster_ssh_host_key_policy",
    "cluster_host_key_policy",
)
_STRICT_HOST_KEY_VALUES = {"1", "on", "strict", "true", "yes"}
_TOFU_HOST_KEY_VALUES = {
    "0",
    "accept-new",
    "false",
    "learn",
    "learn-and-pin",
    "off",
    "tofu",
}


def _is_local_ip(ip: str) -> bool:
    is_local = cast(Callable[[str], bool], AgiEnv.is_local)
    return is_local(ip)


def _env_lookup(env: Any, *names: str) -> str | None:
    for name in names:
        value = getattr(env, name, None)
        if value not in (None, ""):
            return str(value)
    envars = getattr(env, "envars", None)
    if isinstance(envars, dict):
        for name in names:
            value = envars.get(name)
            if value not in (None, ""):
                return str(value)
    for name in names:
        value = os.environ.get(name)
        if value not in (None, ""):
            return str(value)
    return None


def _cluster_ssh_known_hosts_path(env: Any) -> Path:
    configured = _env_lookup(env, *_KNOWN_HOSTS_ENV_NAMES)
    if configured:
        return Path(configured).expanduser()
    return Path("~/.ssh/known_hosts").expanduser()


def _cluster_ssh_host_key_policy(env: Any) -> str:
    configured = _env_lookup(env, *_HOST_KEY_POLICY_ENV_NAMES)
    if configured in (None, ""):
        return "strict"

    normalized = str(configured).strip().lower()
    if normalized in _STRICT_HOST_KEY_VALUES:
        return "strict"
    if normalized in _TOFU_HOST_KEY_VALUES:
        return "accept-new"
    raise ValueError(
        "Invalid cluster SSH host-key policy. Use 'strict' or 'accept-new'."
    )


def _scp_host_key_options(env: Any) -> list[str]:
    policy = _cluster_ssh_host_key_policy(env)
    strict_check = "accept-new" if policy == "accept-new" else "yes"
    known_hosts = _cluster_ssh_known_hosts_path(env)
    return [
        "-o",
        f"StrictHostKeyChecking={strict_check}",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
    ]


def _known_hosts_query_host(host: str, port: int) -> str:
    return f"[{host}]:{port}" if port != 22 else host


def _known_host_entry_exists(host: str, known_hosts_path: Path, *, port: int = 22) -> bool:
    if not known_hosts_path.exists():
        return False
    try:
        result = subprocess.run(
            [
                "ssh-keygen",
                "-F",
                _known_hosts_query_host(host, port),
                "-f",
                str(known_hosts_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def _append_known_host_from_scan(
    host: str,
    known_hosts_path: Path,
    *,
    port: int = 22,
    log: Any = logger,
) -> bool:
    known_hosts_path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        try:
            known_hosts_path.parent.chmod(0o700)
        except OSError:
            pass
    try:
        result = subprocess.run(
            [
                "ssh-keyscan",
                "-H",
                "-T",
                "5",
                "-p",
                str(port),
                "-t",
                "ed25519,rsa,ecdsa",
                host,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("Could not learn SSH host key for %s: %s", host, exc)
        return False

    lines = [line for line in result.stdout.splitlines() if line.strip() and not line.startswith("#")]
    if result.returncode != 0 or not lines:
        detail = (result.stderr or "").strip() or "no host key returned"
        log.warning("Could not learn SSH host key for %s: %s", host, detail)
        return False

    with known_hosts_path.open("a", encoding="utf-8") as stream:
        for line in lines:
            stream.write(f"{line}\n")
    if os.name != "nt":
        try:
            known_hosts_path.chmod(0o600)
        except OSError:
            pass
    return True


def _prepare_known_hosts_for_policy(
    host: str,
    known_hosts_path: Path,
    policy: str,
    *,
    log: Any = logger,
) -> None:
    if policy != "accept-new":
        return
    if _known_host_entry_exists(host, known_hosts_path):
        return
    learned = _append_known_host_from_scan(host, known_hosts_path, log=log)
    if learned:
        log.info("Pinned SSH host key for %s in %s", host, known_hosts_path)


async def _run_scp_command(
    cmd: list[str],
    *,
    local_path: Path,
    remote: str,
    log: Any = logger,
    extra_env: dict[str, str] | None = None,
) -> None:
    import os as _os
    proc_env = {**_os.environ, **(extra_env or {})}
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=proc_env,
    )
    _stdout, stderr = await process.communicate()

    if process.returncode != 0:
        message = stderr.decode().strip()
        log.error(f"SCP failed sending {local_path} to {remote}: {message}")
        raise ConnectionError(f"SCP error: {message}")

    log.info(f"Sent file {local_path} to {remote}")


def _verbose_logging_enabled() -> bool:
    verbose = getattr(AgiEnv, "verbose", 0) or 0
    return verbose > 0 or bool(getattr(AgiEnv, "debug", False))


def is_private_ssh_key_file(path: Path) -> bool:
    """Return True when ``path`` looks like a usable private SSH key."""

    if not path.is_file():
        return False

    name = path.name.lower()
    if name == "config":
        return False
    if name.startswith("authorized_keys"):
        return False
    if name.startswith("known_hosts"):
        return False
    if name.endswith(".pub"):
        return False

    try:
        header = path.read_text(errors="ignore")[:256]
    except OSError:
        return False

    private_key_markers = (
        "BEGIN OPENSSH PRIVATE KEY",
        "BEGIN RSA PRIVATE KEY",
        "BEGIN DSA PRIVATE KEY",
        "BEGIN EC PRIVATE KEY",
        "BEGIN PRIVATE KEY",
        "BEGIN ENCRYPTED PRIVATE KEY",
    )
    if any(marker in header for marker in private_key_markers):
        return True

    return name.startswith("id_") and "." not in name


def discover_private_ssh_keys(ssh_dir: Path) -> List[str]:
    """Return likely private SSH keys from ``ssh_dir``."""

    if not ssh_dir.exists():
        return []

    keys = []
    for file in sorted(ssh_dir.iterdir(), key=lambda candidate: candidate.name):
        if is_private_ssh_key_file(file):
            keys.append(str(file))
    return keys


async def send_file(
    env: AgiEnv,
    ip: str,
    local_path: Path,
    remote_path: Path,
    *,
    user: Optional[str] = None,
    password: Optional[str] = None,
    log: Any = logger,
) -> None:
    if _is_local_ip(ip):
        destination = remote_path
        if not destination.is_absolute():
            destination = Path(env.home_abs) / destination
        log.info(f"mkdir {destination.parent}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if local_path.is_dir():
            shutil.copytree(local_path, destination, dirs_exist_ok=True)
        else:
            shutil.copyfile(local_path, destination)
        return

    if not user:
        user = getattr(env, "user", None) or getpass.getuser()
    if not password:
        password = getattr(env, "password", None)

    user_at_ip = f"{user}@{ip}" if user else ip
    remote = f"{user_at_ip}:{remote_path}"

    auth_prefix: list[str] = []
    scp_env: dict[str, str] = {}

    if password and os.name != "nt":
        auth_prefix = ["sshpass", "-e"]
        scp_env["SSHPASS"] = password

    scp_cmd = ["scp", *_scp_host_key_options(env)]
    if local_path.is_dir():
        scp_cmd.append("-r")
    ssh_key_path = getattr(env, "ssh_key_path", None)
    if ssh_key_path:
        scp_cmd.extend(["-i", str(Path(ssh_key_path).expanduser())])
    scp_cmd.append(str(local_path))
    scp_cmd.append(remote)
    cmd = auth_prefix + scp_cmd

    last_error: ConnectionError | OSError | None = None
    for _attempt in range(2):
        try:
            await _run_scp_command(cmd, local_path=local_path, remote=remote, log=log, extra_env=scp_env)
            return
        except (ConnectionError, OSError) as exc:
            last_error = exc

    if last_error is not None:
        raise last_error


async def send_files(
    agi_cls: Any,
    env: AgiEnv,
    ip: str,
    files: list[Path],
    remote_dir: Path,
    *,
    user: Optional[str] = None,
) -> None:
    tasks = []
    for file_path in files:
        remote_path = remote_dir / file_path.name
        tasks.append(agi_cls.send_file(env, ip, file_path, remote_path, user=user))
    await asyncio.gather(*tasks)


@asynccontextmanager
async def get_ssh_connection(
    agi_cls: Any,
    ip: str,
    *,
    timeout_sec: int = 5,
    discover_private_keys_fn: Callable[[Path], List[str]] = discover_private_ssh_keys,
    log: Any = logger,
) -> AsyncIterator[Any]:
    env = agi_cls.env
    if _is_local_ip(ip) and not env.user:
        env.user = getpass.getuser()

    if not env.user:
        raise ValueError("SSH username is not configured. Please set 'user' in your .env file.")

    conn = agi_cls._ssh_connections.get(ip)
    if conn and not conn.is_closed():
        yield conn
        return

    agent_path = None
    try:
        client_keys: Optional[Iterable[str]] = None
        ssh_key_override = env.ssh_key_path
        if ssh_key_override:
            client_keys = [str(Path(ssh_key_override).expanduser())]
        else:
            if env.password:
                client_keys = []
                agent_path = None
            else:
                ssh_dir = Path("~/.ssh").expanduser()
                keys = discover_private_keys_fn(ssh_dir)
                client_keys = keys if keys else None

        host_key_policy = _cluster_ssh_host_key_policy(env)
        known_hosts_path = _cluster_ssh_known_hosts_path(env)
        _prepare_known_hosts_for_policy(
            ip,
            known_hosts_path,
            host_key_policy,
            log=log,
        )

        conn = await asyncio.wait_for(
            asyncssh.connect(
                ip,
                username=env.user,
                password=env.password,
                known_hosts=str(known_hosts_path),
                client_keys=client_keys,
                agent_path=agent_path,
            ),
            timeout=timeout_sec,
        )

        agi_cls._ssh_connections[ip] = conn
        yield conn

    except asyncio.TimeoutError:
        err_msg = f"Connection to {ip} timed out after {timeout_sec} seconds."
        log.warning(err_msg)
        raise ConnectionError(err_msg) from None

    except asyncssh.PermissionDenied:
        err_msg = f"Authentication failed for SSH user '{env.user}' on host {ip}."
        log.error(err_msg)
        raise ConnectionError(err_msg) from None

    except OSError as exc:
        original = str(exc).strip() or repr(exc)
        if exc.errno in {
            errno.EHOSTUNREACH,
            errno.ENETUNREACH,
            getattr(errno, "EHOSTDOWN", None),
            getattr(errno, "ENETDOWN", None),
            getattr(errno, "ETIMEDOUT", None),
        }:
            err_msg = (
                f"Unable to connect to {ip} on SSH port 22. "
                "Please check that the device is powered on, network cable connected, and SSH service running."
            )
            if original:
                err_msg = f"{err_msg} (details: {original})"
            log.info(err_msg)
        else:
            err_msg = original
            log.error(err_msg)
        raise ConnectionError(err_msg) from None

    except asyncssh.Error as exc:
        base_msg = str(exc).strip() or repr(exc)
        cmd = getattr(exc, "command", None)
        if cmd:
            log.error(cmd)
        log.error(base_msg)
        raise ConnectionError(base_msg) from None


async def exec_ssh(
    agi_cls: Any,
    ip: str,
    cmd: str,
    *,
    process_error_cls: type[BaseException] = ProcessError,
    log: Any = logger,
) -> str:
    try:
        async with agi_cls.get_ssh_connection(ip) as conn:
            msg = f"[{ip}] {cmd}"
            if _verbose_logging_enabled():
                log.info(msg)
            result = await conn.run(cmd, check=True)
            stdout = result.stdout
            stderr = result.stderr
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            if stderr:
                log.info(f"[{ip}] {stderr.strip()}")
            if _verbose_logging_enabled():
                if stdout:
                    log.info(f"[{ip}] {stdout.strip()}")
            return (stdout or "").strip() + "\n" + (stderr or "").strip()

    except ConnectionError:
        raise

    except process_error_cls as exc:
        stdout = getattr(exc, "stdout", "")
        stderr = getattr(exc, "stderr", "")
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        log.error(f"Remote command stderr: {stderr.strip()}")
        raise

    except (asyncssh.Error, OSError) as exc:
        msg = str(exc).strip() or repr(exc)
        friendly = f"Connection to {ip} failed: {msg}"
        log.info(friendly)
        raise ConnectionError(friendly) from None


async def exec_ssh_async(agi_cls: Any, ip: str, cmd: str) -> str:
    """Execute a remote command via SSH and return the last non-empty stdout line."""

    async with agi_cls.get_ssh_connection(ip) as conn:
        process = await conn.create_process(cmd)
        stdout = await process.stdout.read()
        await process.wait()
        lines = [line.strip() for line in stdout.splitlines() if line.strip()]
        return lines[-1] if lines else ""


async def close_all_connections(agi_cls: Any) -> None:
    """Close and drop every cached SSH connection."""

    for conn in agi_cls._ssh_connections.values():
        conn.close()
        await conn.wait_closed()
    agi_cls._ssh_connections.clear()
