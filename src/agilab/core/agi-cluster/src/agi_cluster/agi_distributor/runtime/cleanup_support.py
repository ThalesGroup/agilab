import asyncio
import contextlib
import getpass
import json
import logging
import os
import runpy
import shlex
import shutil
import socket
import stat
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from tempfile import gettempdir
from typing import Any, Awaitable, Callable, Optional

import psutil
from asyncssh.process import ProcessError

from agi_cluster.agi_distributor.api.worker_cli_support import resolve_worker_cli_path
from agi_env import AgiEnv
from agi_env.runtime.destructive_path_support import (
    safe_destructive_path,
    safe_worker_runtime_cleanup_path,
)


logger = logging.getLogger(__name__)
REMOVE_DIR_RETRY_EXCEPTIONS = (OSError, shutil.Error)
CMD_PREFIX_LOOKUP_EXCEPTIONS = (ConnectionError, OSError, RuntimeError, TimeoutError)
_BOOTSTRAP_PSUTIL_SPEC = "psutil>=7,<8"
_DASK_CMD_MARKERS = (
    "dask-scheduler",
    "dask-worker",
    "dask scheduler",
    "dask worker",
    "dask_scheduler",
    "dask_worker",
    "distributed.cli",
    "distributed.nanny",
    "distributed.worker",
)


@dataclass(frozen=True)
class RemoteTargetLease:
    ip: str
    target: Path
    token: str
    operation: str
    cmd_prefix: str
    recovery_tokens: tuple[str, ...] = ()


def _remote_arg(value: Any) -> str:
    if isinstance(value, Path):
        return shlex.quote(value.as_posix())
    return shlex.quote(str(value))


def _remote_words(value: Any) -> str:
    return " ".join(shlex.quote(part) for part in shlex.split(str(value), posix=True))


def _remote_target_key(value: Any) -> str:
    return os.path.normcase(os.path.normpath(str(value))).replace("\\", "/")


def _current_remote_lifecycle_token(agi_cls: Any) -> str:
    return str(
        getattr(agi_cls, "_lifecycle_remote_token", "")
        or getattr(agi_cls, "_lifecycle_call_token", "")
        or ""
    )


def _validate_cached_remote_lease(
    agi_cls: Any,
    ip: str,
    lease: RemoteTargetLease,
) -> None:
    expected_token = _current_remote_lifecycle_token(agi_cls)
    expected_target = Path(agi_cls.env.wenv_rel)
    if (
        not expected_token
        or lease.ip != ip
        or lease.token != expected_token
        or _remote_target_key(lease.target) != _remote_target_key(expected_target)
    ):
        raise RuntimeError(
            f"Cached remote target lease for {ip} does not match the active "
            "lifecycle token and target"
        )


async def _remote_cmd_prefix(
    env: Any,
    ip: str,
    *,
    detect_export_cmd_fn: Optional[Callable[[str], Awaitable[str]]] = None,
) -> str:
    cmd_prefix = str(env.envars.get(f"{ip}_CMD_PREFIX", "") or "")
    if cmd_prefix or env.is_local(ip) or detect_export_cmd_fn is None:
        return cmd_prefix

    try:
        cmd_prefix = str(await detect_export_cmd_fn(ip) or "")
    except CMD_PREFIX_LOOKUP_EXCEPTIONS:
        return ""

    if cmd_prefix:
        env.envars[f"{ip}_CMD_PREFIX"] = cmd_prefix
    return cmd_prefix


def remove_dir_forcefully(
    path: str,
    *,
    rmtree_fn: Callable[..., Any] = shutil.rmtree,
    sleep_fn: Callable[[float], Any] = time.sleep,
    access_fn: Callable[[Any, int], bool] = os.access,
    chmod_fn: Callable[[Any, int], Any] = os.chmod,
    log: Any = logger,
) -> None:
    def onerror(func: Callable[..., Any], failed_path: Any, exc_info: Any) -> None:
        if not access_fn(failed_path, os.W_OK):
            chmod_fn(failed_path, stat.S_IWUSR)
            func(failed_path)
        else:
            log.info("%s not removed due to %s", failed_path, exc_info[1])

    try:
        rmtree_fn(path, onerror=onerror)
    except REMOVE_DIR_RETRY_EXCEPTIONS as exc:
        log.error("Exception while deleting %s: %s", path, exc)
        sleep_fn(1)
        try:
            rmtree_fn(path, onerror=onerror)
        except REMOVE_DIR_RETRY_EXCEPTIONS as second_exc:
            log.error("Second failure deleting %s: %s", path, second_exc)
            raise


def _snapshot_pid_evidence(pid_files: list[Path]) -> dict[Path, bytes]:
    evidence: dict[Path, bytes] = {}
    for pid_file in pid_files:
        try:
            evidence[pid_file] = pid_file.read_bytes()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise RuntimeError(
                f"Cannot preserve PID ownership evidence before cleanup: {pid_file}: {exc}"
            ) from exc
    return evidence


def _restore_pid_evidence(evidence: dict[Path, bytes]) -> None:
    restore_errors: list[str] = []
    for pid_file, payload in evidence.items():
        if pid_file.exists():
            continue
        tmp_path = pid_file.with_name(
            f".{pid_file.name}.restore-{os.getpid()}-{time.time_ns()}.tmp"
        )
        try:
            pid_file.parent.mkdir(parents=True, exist_ok=True)
            with tmp_path.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp_path, pid_file)
        except OSError as exc:
            restore_errors.append(f"{pid_file}: {exc}")
        finally:
            with contextlib.suppress(OSError):
                tmp_path.unlink()
    if restore_errors:
        raise RuntimeError(
            "Worker cleanup failed and PID ownership evidence could not be restored: "
            + "; ".join(restore_errors)
        )


async def kill_processes(
    agi_cls: Any,
    ip: Optional[str] = None,
    current_pid: Optional[int] = None,
    force: bool = True,
    force_scan: bool = False,
    *,
    gethostbyname_fn: Callable[[str], str] = socket.gethostbyname,
    run_fn: Callable[[str, str], Awaitable[Any]] = AgiEnv.run,
    copy_fn: Callable[[Any, Any], Any] = shutil.copy,
    run_path_fn: Callable[..., Any] = runpy.run_path,
    sys_module: Any = sys,
    path_cls: type[Path] = Path,
    detect_export_cmd_fn: Optional[Callable[[str], Awaitable[str]]] = None,
    log: Any = logger,
) -> Optional[Any]:
    env = agi_cls.env
    uv = env.uv
    localhost = gethostbyname_fn("localhost")
    ip = ip or localhost
    current_pid = current_pid or os.getpid()

    cmds: list[str] = []
    cli_rel = env.wenv_rel.parent / "cli.py"
    cli_abs = env.wenv_abs.parent / cli_rel.name
    cmd_prefix = await _remote_cmd_prefix(
        env,
        ip,
        detect_export_cmd_fn=detect_export_cmd_fn,
    )
    # This copied bootstrap CLI runs before the worker environment exists.
    # Process ownership discovery needs psutil, unlike lease and archive commands.
    kill_prefix = (
        f"{cmd_prefix}{_remote_words(uv)} run --no-sync "
        f"--with {_remote_arg(_BOOTSTRAP_PSUTIL_SPEC)} python"
    )
    if env.is_local(ip):
        if not cli_abs.exists():
            copy_fn(resolve_worker_cli_path(env), cli_abs)
        if force:
            exclude_arg = f" {_remote_arg(current_pid)}" if current_pid else ""
            kill_command = "kill-force" if force_scan else "kill"
            target_arg = "" if force_scan else f" {_remote_arg(env.wenv_abs)}"
            cmds.append(
                f"{kill_prefix} {_remote_arg(cli_abs)} {kill_command}"
                f"{target_arg}{exclude_arg}"
            )
    elif force:
        kill_command = "kill-force" if force_scan else "kill"
        target_arg = "" if force_scan else f" {_remote_arg(env.wenv_rel)}"
        cmds.append(
            f"{kill_prefix} {_remote_arg(cli_rel)} {kill_command}{target_arg}"
        )

    last_res = None
    for cmd in cmds:
        cwd = str(env.wenv_abs)
        if env.is_local(ip):
            if env.debug:
                sys_module.argv = shlex.split(cmd.split("python ", 1)[1], posix=True)
                run_path_fn(sys_module.argv[0], run_name="__main__")
            else:
                await run_fn(cmd, cwd)
        else:
            last_res = await agi_cls.exec_ssh(ip, cmd)

        if isinstance(last_res, dict):
            out = last_res.get("stdout", "")
            err = last_res.get("stderr", "")
            log.info(out)
            if err:
                log.error(err)

    return last_res


async def wait_for_port_release(
    ip: str,
    port: int,
    timeout: float = 5.0,
    interval: float = 0.2,
    *,
    gethostbyname_fn: Callable[[str], str] = socket.gethostbyname,
    socket_factory: Callable[..., Any] = socket.socket,
    sleep_fn: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    monotonic_fn: Callable[[], float] = time.monotonic,
) -> bool:
    ip = ip or gethostbyname_fn("localhost")
    deadline = monotonic_fn() + timeout
    while monotonic_fn() < deadline:
        sock = socket_factory(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind((ip, port))
        except OSError:
            await sleep_fn(interval)
        else:
            sock.close()
            return True
        finally:
            try:
                sock.close()
            except OSError:
                pass
    return False


def _normalized_process_username(username: Any) -> str:
    """Strip a Windows ``DOMAIN\\user`` prefix so usernames compare exactly."""
    text = str(username or "")
    return text.rsplit("\\", 1)[-1]


def _is_dask_command(cmdline: Any) -> bool:
    text = " ".join(str(part) for part in (cmdline or [])).lower()
    return any(marker in text for marker in _DASK_CMD_MARKERS)


def _owned_pid_files(env: Any, *, path_cls: type[Path] = Path) -> list[Path]:
    wenv_abs = path_cls(env.wenv_abs).expanduser().resolve(strict=False)
    candidates: set[Path] = set()
    for root in (wenv_abs.parent, wenv_abs):
        candidates.update(root.glob("dask_scheduler.pid"))
        candidates.update(root.glob("dask_worker*.pid"))
    return sorted(candidates, key=lambda candidate: candidate.as_posix())


def _pid_file_is_inside_target(pid_file: Path, wenv_abs: Path) -> bool:
    try:
        pid_file.resolve(strict=False).relative_to(wenv_abs)
    except (OSError, ValueError):
        return False
    return True


def _validated_local_worker_runtime_target(
    env: Any,
    *,
    path_cls: type[Path] = Path,
) -> Path:
    home_value = getattr(env, "home_abs", None)
    if home_value is None:
        raise RuntimeError(
            "Cannot clean AGILAB worker environment without its trusted home root"
        )
    home_path = path_cls(home_value).expanduser().resolve(strict=False)
    try:
        return safe_worker_runtime_cleanup_path(
            env.wenv_abs,
            roots=(home_path / "wenv",),
            home_path=home_path,
            cwd_path=path_cls.cwd(),
        )
    except (OSError, TypeError, ValueError) as exc:
        raise RuntimeError(
            f"Refusing unsafe AGILAB worker environment cleanup target: {exc}"
        ) from exc


def _read_pid_record(pid_file: Path) -> tuple[int, float | None]:
    text = pid_file.read_text(encoding="utf-8").strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return int(text), None
    if isinstance(payload, int):
        return int(payload), None
    if not isinstance(payload, dict):
        raise ValueError("PID ownership record must be an integer or JSON object")
    pid = int(payload["pid"])
    process_start_time = payload.get("process_start_time")
    return pid, float(process_start_time) if process_start_time not in (None, "") else None


def _command_belongs_to_target(
    cmdline: Any,
    *,
    pid_file: Path | None,
    wenv_abs: Path,
    wenv_display: Path | None = None,
) -> bool:
    """Check parsed path arguments without unsafe prefix/substring matches."""

    if isinstance(cmdline, str):
        try:
            parts = shlex.split(cmdline, posix=os.name != "nt")
        except ValueError:
            parts = [cmdline]
    else:
        parts = [str(part) for part in (cmdline or [])]

    owned_pid = (
        os.path.normcase(os.path.normpath(str(pid_file.expanduser().resolve(strict=False))))
        if pid_file is not None
        else None
    )
    owned_roots = {
        os.path.normcase(os.path.normpath(str(wenv_abs.expanduser().resolve(strict=False))))
    }
    if wenv_display is not None:
        displayed = wenv_display.expanduser()
        if displayed.is_absolute():
            owned_roots.add(os.path.normcase(os.path.normpath(str(displayed))))

    candidates: list[str] = []
    for part in parts:
        candidates.append(part)
        if "=" in part:
            option, value = part.split("=", 1)
            if option.startswith("-") and value:
                candidates.append(value)

    for value in candidates:
        value = value.strip().strip("\"'")
        if not value or "://" in value:
            continue
        candidate_path = Path(value).expanduser()
        if not candidate_path.is_absolute():
            continue
        candidate = os.path.normcase(
            os.path.normpath(str(candidate_path.resolve(strict=False)))
        )
        if owned_pid is not None and candidate == owned_pid:
            return True
        for root in owned_roots:
            try:
                if os.path.commonpath((candidate, root)) == root:
                    return True
            except ValueError:
                # Paths on different Windows drives cannot establish ownership.
                continue
    return False


def _process_snapshot(process_iter_fn: Callable[..., Any]) -> dict[int, Any]:
    processes: dict[int, Any] = {}
    for proc in process_iter_fn(["pid", "username", "cmdline", "create_time"]):
        try:
            processes[int(proc.info["pid"])] = proc
        except (KeyError, TypeError, ValueError, psutil.NoSuchProcess):
            continue
    return processes


def _target_dask_pids(
    processes: dict[int, Any],
    *,
    self_pid: int,
    wenv_abs: Path,
    wenv_display: Path,
) -> list[int]:
    active: list[int] = []
    for pid, proc in processes.items():
        if pid == self_pid:
            continue
        try:
            cmdline = proc.info.get("cmdline")
            if _is_dask_command(cmdline) and _command_belongs_to_target(
                cmdline,
                pid_file=None,
                wenv_abs=wenv_abs,
                wenv_display=wenv_display,
            ):
                active.append(pid)
        except (AttributeError, psutil.NoSuchProcess):
            continue
    return sorted(active)


def clean_dirs_local(
    agi_cls: Any,
    *,
    process_iter_fn: Callable[..., Any] = psutil.process_iter,
    getuser_fn: Callable[[], str] = getpass.getuser,
    getpid_fn: Callable[[], int] = os.getpid,
    rmtree_fn: Callable[..., Any] = shutil.rmtree,
    sleep_fn: Callable[[float], Any] = time.sleep,
    path_cls: type[Path] = Path,
    process_wait_timeout: float = 3.0,
) -> None:
    """Stop only Dask processes proven to belong to this target, then clean it.

    The lifecycle lease serializes every target sharing this runtime parent.
    PID files narrow process ownership further and command/start-time
    validation protects against stale PID reuse.  Ordinary cleanup
    intentionally leaves the shared Dask scratch root and unrelated Dask
    processes untouched.
    """

    me = getuser_fn()
    self_pid = getpid_fn()
    wenv_display = path_cls(agi_cls.env.wenv_abs).expanduser()
    wenv_abs = _validated_local_worker_runtime_target(
        agi_cls.env,
        path_cls=path_cls,
    )
    processes = _process_snapshot(process_iter_fn)

    blocked_pids: list[int] = []
    killed_processes: list[tuple[int, Any]] = []
    pid_files = _owned_pid_files(agi_cls.env, path_cls=path_cls)
    removable_pid_files: set[Path] = set()
    for pid_file in pid_files:
        target_local_evidence = _pid_file_is_inside_target(pid_file, wenv_abs)
        try:
            pid, expected_start = _read_pid_record(pid_file)
        except (OSError, KeyError, TypeError, ValueError):
            if target_local_evidence:
                removable_pid_files.add(pid_file)
            continue
        if pid == self_pid:
            continue
        proc = processes.get(pid)
        if proc is None:
            # No live incarnation owns this record, so shared-parent legacy
            # evidence is stale and safe to remove after target deletion.
            removable_pid_files.add(pid_file)
            continue
        info = proc.info
        try:
            actual_start = info.get("create_time")
            same_start = expected_start is None or (
                actual_start not in (None, "")
                and abs(float(actual_start) - expected_start) <= 1.0
            )
        except (TypeError, ValueError):
            same_start = False
        if expected_start is not None and not same_start:
            # The PID was reused by another process generation.  The record is
            # stale even when the newer process remains live.
            removable_pid_files.add(pid_file)
        owned = (
            bool(info.get("username"))
            and _normalized_process_username(info.get("username")) == me
            and _is_dask_command(info.get("cmdline"))
            and _command_belongs_to_target(
                info.get("cmdline"),
                # A legacy PID file in the shared parent is not itself target
                # identity: a live sibling can reference the same parent.
                pid_file=pid_file if target_local_evidence else None,
                wenv_abs=wenv_abs,
                wenv_display=wenv_display,
            )
            and same_start
        )
        if owned:
            removable_pid_files.add(pid_file)
            try:
                proc.kill()
                killed_processes.append((pid, proc))
            except psutil.NoSuchProcess:
                pass
            except (psutil.AccessDenied, OSError):
                blocked_pids.append(pid)
                continue

    # A killed process can retain files briefly, especially on Windows. Wait a
    # bounded amount, then refresh the process table before deleting evidence.
    for pid, proc in killed_processes:
        wait = getattr(proc, "wait", None)
        if not callable(wait):
            continue
        try:
            wait(timeout=process_wait_timeout)
        except psutil.NoSuchProcess:
            pass
        except (psutil.TimeoutExpired, psutil.AccessDenied, OSError):
            blocked_pids.append(pid)

    if blocked_pids:
        raise RuntimeError(
            "Cannot clean AGILAB worker environment while owned Dask process(es) "
            f"remain active: {sorted(blocked_pids)}"
        )

    # PID files are kill authorization, not permission to erase a live target.
    # Fail closed when any Dask process still references this exact environment,
    # including a process whose PID file was lost or stale.
    residual_pids = _target_dask_pids(
        _process_snapshot(process_iter_fn),
        self_pid=self_pid,
        wenv_abs=wenv_abs,
        wenv_display=wenv_display,
    )
    if residual_pids:
        raise RuntimeError(
            "Cannot clean AGILAB worker environment while Dask process(es) "
            f"still reference the target: {residual_pids}"
        )

    # Only a failed recursive deletion can remove target-local evidence. Shared
    # parent records belong to independent sibling sessions and may disappear
    # legitimately while this cleanup is in flight; restoring those records
    # would resurrect stale ownership evidence.
    target_local_pid_files = [
        pid_file
        for pid_file in pid_files
        if _pid_file_is_inside_target(pid_file, wenv_abs)
    ]
    pid_evidence = _snapshot_pid_evidence(target_local_pid_files)
    try:
        if wenv_abs.exists():
            remove_dir_forcefully(
                str(wenv_abs),
                rmtree_fn=rmtree_fn,
                sleep_fn=sleep_fn,
            )
        if wenv_abs.exists():
            raise OSError(f"worker environment still exists after deletion: {wenv_abs}")
    except (OSError, shutil.Error, TypeError) as exc:
        try:
            _restore_pid_evidence(pid_evidence)
        except RuntimeError as restore_exc:
            raise RuntimeError(str(restore_exc)) from exc
        raise RuntimeError(
            f"Could not completely delete AGILAB worker environment {wenv_abs}; "
            "PID ownership evidence was retained"
        ) from exc

    # Shared-parent legacy evidence is outside ``wenv_abs`` and is removed only
    # after the exact target directory has been deleted and verified absent.
    for pid_file in removable_pid_files:
        with contextlib.suppress(FileNotFoundError):
            pid_file.unlink()


def force_clean_dirs_local(
    agi_cls: Any,
    *,
    process_iter_fn: Callable[..., Any] = psutil.process_iter,
    getuser_fn: Callable[[], str] = getpass.getuser,
    getpid_fn: Callable[[], int] = os.getpid,
    rmtree_fn: Callable[..., Any] = shutil.rmtree,
    gettempdir_fn: Callable[[], str] = gettempdir,
) -> None:
    """Operator-only broad cleanup for recovering an abandoned Dask host."""

    me = getuser_fn()
    self_pid = getpid_fn()
    wenv_abs = _validated_local_worker_runtime_target(agi_cls.env)
    for proc in process_iter_fn(["pid", "username", "cmdline"]):
        try:
            if (
                proc.info.get("username")
                and _normalized_process_username(proc.info.get("username")) == me
                and proc.info.get("pid") != self_pid
                and _is_dask_command(proc.info.get("cmdline"))
            ):
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    temp_root = Path(gettempdir_fn()).expanduser().resolve(strict=False)
    try:
        scratch = safe_destructive_path(
            temp_root / "dask-scratch-space",
            roots=(temp_root,),
            label="Dask scratch cleanup",
        )
    except (OSError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Refusing unsafe Dask scratch cleanup target: {exc}") from exc
    for directory in (str(scratch), str(wenv_abs)):
        try:
            rmtree_fn(directory, ignore_errors=True)
        except (OSError, TypeError):
            pass


def _remote_lease_command(
    env: Any,
    lease: RemoteTargetLease,
    action: str,
) -> str:
    cli = env.wenv_rel.parent / "cli.py"
    if action == "acquire" and lease.recovery_tokens:
        command = "target-lease-recover"
        suffix = (
            f" {_remote_arg(','.join(lease.recovery_tokens))}"
            f" {_remote_arg(lease.operation)}"
        )
    else:
        command = f"target-lease-{action}"
        suffix = (
            f" {_remote_arg(lease.operation)}" if action == "acquire" else ""
        )
    return (
        f"{lease.cmd_prefix}{_remote_words(env.uv)} run --no-sync "
        f"-p {_remote_arg(env.python_version)} python {_remote_arg(cli)} "
        f"{command} {_remote_arg(lease.target)} {_remote_arg(lease.token)}{suffix}"
    )


async def acquire_remote_target_lease(
    agi_cls: Any,
    ip: str,
    *,
    cmd_prefix: str | None = None,
    detect_export_cmd_fn: Optional[Callable[[str], Awaitable[str]]] = None,
) -> RemoteTargetLease:
    """Hold a worker-host lease until the surrounding lifecycle operation exits."""

    env = agi_cls.env
    token = _current_remote_lifecycle_token(agi_cls)
    raw_recovery_tokens = getattr(
        agi_cls,
        "_lifecycle_remote_recovery_tokens",
        (),
    )
    recovery_tokens = tuple(
        dict.fromkeys(
            str(item)
            for item in raw_recovery_tokens
            if isinstance(item, str) and item
        )
    )
    operation = str(
        getattr(agi_cls, "_lifecycle_call_operation", "unknown") or "unknown"
    )
    if not token:
        raise RuntimeError("Remote target cleanup/start requires an active lifecycle token")

    leases = getattr(agi_cls, "_remote_target_leases", None)
    if not isinstance(leases, dict):
        leases = {}
        setattr(agi_cls, "_remote_target_leases", leases)
    existing = leases.get(ip)
    if existing is not None:
        if not isinstance(existing, RemoteTargetLease):
            raise RuntimeError(f"Cached remote target lease evidence for {ip} is invalid")
        _validate_cached_remote_lease(agi_cls, ip, existing)
        return existing

    if cmd_prefix is None:
        cmd_prefix = await _remote_cmd_prefix(
            env,
            ip,
            detect_export_cmd_fn=detect_export_cmd_fn,
        )
    lease = RemoteTargetLease(
        ip=ip,
        target=Path(env.wenv_rel),
        token=token,
        operation=operation,
        cmd_prefix=str(cmd_prefix or ""),
        recovery_tokens=recovery_tokens,
    )
    # Publish local evidence before the SSH command. If transport or worker
    # publication fails after claiming the remote directory, lifecycle exit can
    # still issue exact-token release and retain the local lease on uncertainty.
    leases[ip] = lease
    await agi_cls.exec_ssh(ip, _remote_lease_command(env, lease, "acquire"))
    return lease


async def release_remote_target_leases(agi_cls: Any) -> None:
    """Release verified remote lease generations, retaining failed evidence."""

    leases = getattr(agi_cls, "_remote_target_leases", None)
    if not isinstance(leases, dict) or not leases:
        return
    env = agi_cls.env
    failures: list[str] = []
    for ip, lease in sorted(list(leases.items())):
        if not isinstance(lease, RemoteTargetLease):
            failures.append(f"{ip}: invalid local lease evidence")
            continue
        try:
            await agi_cls.exec_ssh(
                ip,
                _remote_lease_command(env, lease, "release"),
            )
        except (
            ConnectionError,
            OSError,
            ProcessError,
            RuntimeError,
            TimeoutError,
        ) as exc:
            failures.append(f"{ip}: {exc}")
        else:
            leases.pop(ip, None)
    if failures:
        raise RuntimeError(
            "Could not prove remote target lease release: " + "; ".join(failures)
        )


async def clean_dirs(
    agi_cls: Any,
    ip: str,
    *,
    makedirs_fn: Callable[..., Any] = os.makedirs,
    remove_dir_forcefully_fn: Optional[Callable[[str], None]] = None,
) -> None:
    env = agi_cls.env
    uv = env.uv
    # This helper is invoked once per remote node, often concurrently.  It
    # must never delete/recreate the manager's local wenv from each remote
    # task; local cleanup is owned by the single lifecycle operation.
    cmd_prefix = env.envars.get(f"{ip}_CMD_PREFIX", "")
    wenv = env.wenv_rel
    cli = wenv.parent / "cli.py"
    leases = getattr(agi_cls, "_remote_target_leases", {})
    lease = leases.get(ip) if isinstance(leases, dict) else None
    if lease is not None:
        if not isinstance(lease, RemoteTargetLease):
            raise RuntimeError(f"Cached remote target lease evidence for {ip} is invalid")
        _validate_cached_remote_lease(agi_cls, ip, lease)
    acquire_remote_lease = getattr(agi_cls, "_acquire_remote_target_lease", None)
    if (
        not isinstance(lease, RemoteTargetLease)
        and callable(acquire_remote_lease)
        and getattr(agi_cls, "_lifecycle_call_token", None)
    ):
        lease = await acquire_remote_lease(ip, cmd_prefix=cmd_prefix)
    token_arg = (
        f" {_remote_arg(lease.token)}"
        if isinstance(lease, RemoteTargetLease)
        else ""
    )
    cmd = (
        f"{cmd_prefix}{_remote_words(uv)} run --no-sync "
        f"--with {_remote_arg(_BOOTSTRAP_PSUTIL_SPEC)} "
        f"-p {_remote_arg(env.python_version)} python "
        f"{_remote_arg(cli)} clean {_remote_arg(wenv)}{token_arg}"
    )
    await agi_cls.exec_ssh(ip, cmd)
