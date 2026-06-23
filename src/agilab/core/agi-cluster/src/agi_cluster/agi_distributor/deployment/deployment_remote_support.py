import json
import logging
import os
import re
import shlex
import subprocess
import uuid
from pathlib import Path, PurePosixPath
from shlex import quote
from tempfile import gettempdir
from typing import Any, Callable, Union

from asyncssh.process import ProcessError

from agi_cluster.agi_distributor import deployment_dask_support
from agi_cluster.agi_distributor.deployment.deployment_build_support import (
    _latest_glob_match as _latest_artifact_match,
    _resolved_cython_directives_spec,
)
from agi_env import AgiEnv
from agi_env.cython_build_config import cython_build_overlay_specs


logger = logging.getLogger(__name__)

_REMOTE_RAPIDS_CHECK_EXCEPTIONS = (ConnectionError, OSError, RuntimeError)
_REMOTE_PLATFORM_PROBE_EXCEPTIONS = (OSError, RuntimeError, ValueError)
_REMOTE_COMMAND_EXCEPTIONS = (OSError, RuntimeError)
_REMOTE_PIP_PROBE_EXCEPTIONS = _REMOTE_COMMAND_EXCEPTIONS + (ProcessError,)
_LEGACY_INTEL_MACOS_DEPENDENCY_SPECS = ("numba==0.62.1", "pyarrow==17.0.0")
_SSHFS_INSTALL_HINT = (
    "sshfs is required to mount AGI_CLUSTER_SHARE on this worker. "
    "Install sshfs first: Debian/Ubuntu: sudo apt-get install -y sshfs; "
    "macOS: install macFUSE/FUSE-T SSHFS and ensure sshfs is visible to non-interactive SSH."
)
_SCHEDULER_SSH_HINT = (
    "Scheduler SSH is not reachable from the worker. Enable SSH on the scheduler/manager, "
    "install the worker public key on the scheduler, and verify ssh <scheduler> from the worker "
    "before mounting AGI_CLUSTER_SHARE with SSHFS."
)
_SSHFS_OPTIONS = (
    "reconnect",
    "ServerAliveInterval=15",
    "ServerAliveCountMax=3",
    "BatchMode=yes",
    "StrictHostKeyChecking=yes",
    "noexec",
)
_SSHFS_SHARE_BACKEND = "sshfs"
_PREMOUNTED_SHARE_BACKENDS = {"nfs", "ntfs"}
_SUPPORTED_SHARE_BACKENDS = {_SSHFS_SHARE_BACKEND, *_PREMOUNTED_SHARE_BACKENDS}
_REMOTE_PATH_PREFIX = (
    'export PATH="$HOME/.local/bin:$HOME/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"; '
)
_REVERSE_SSHFS_LOOP_HINT = (
    "Unmount the local reverse SSHFS viewer mount or use a non-overlapping viewer "
    "path such as ~/worker_clustershare before running cluster INSTALL/RUN."
)


def _resolve_local_share_path(value: str, env: Any) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve(strict=False)
    home = getattr(env, "home_abs", None)
    base = Path(home).expanduser() if home else Path.home()
    return (base / path).resolve(strict=False)


def _remote_share_assignment(value: str) -> str:
    cleaned = value.strip() or "clustershare"
    if cleaned.startswith("~/"):
        return '"$HOME"/' + quote(cleaned[2:])
    if cleaned == "~":
        return '"$HOME"'
    if PurePosixPath(cleaned).is_absolute():
        return quote(cleaned)
    return '"$HOME"/' + quote(cleaned)


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


def _truthy_env(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _cython_mode_enabled(agi_cls: Any) -> bool:
    """Return whether this deploy carries the cython mode bit (AGI._mode & 2)."""

    mode = int(getattr(agi_cls, "_mode", 0) or 0)
    cython_mode = int(getattr(agi_cls, "CYTHON_MODE", 2) or 2)
    return bool(mode & cython_mode)


def _scheduler_ssh_port(env: Any) -> int:
    raw = _env_lookup(env, "AGILAB_SCHEDULER_SSH_PORT", "SCHEDULER_SSH_PORT", "scheduler_ssh_port")
    if raw in (None, ""):
        return 22
    try:
        port = int(str(raw).strip())
    except ValueError as exc:
        raise ValueError(f"Invalid scheduler SSH port: {raw!r}") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"Invalid scheduler SSH port: {port!r}")
    return port


def _remote_cluster_share_premounted(env: Any) -> bool:
    return _cluster_share_backend(env) in _PREMOUNTED_SHARE_BACKENDS or _truthy_env(
        _env_lookup(
            env,
            "AGILAB_REMOTE_CLUSTER_SHARE_PREMOUNTED",
            "AGILAB_PREMOUNTED_REMOTE_CLUSTER_SHARE",
            "AGILAB_CLUSTER_SHARE_PREMOUNTED",
            "remote_cluster_share_premounted",
        )
    )


def _cluster_share_backend(env: Any) -> str:
    raw = _env_lookup(
        env,
        "AGILAB_CLUSTER_SHARE_BACKEND",
        "AGI_CLUSTER_SHARE_BACKEND",
        "cluster_share_backend",
    )
    backend = str(raw or _SSHFS_SHARE_BACKEND).strip().lower() or _SSHFS_SHARE_BACKEND
    if backend not in _SUPPORTED_SHARE_BACKENDS:
        raise ValueError(f"Unsupported AGILAB cluster-share backend: {backend!r}")
    return backend


def _sshfs_options_args() -> str:
    return " ".join(f"-o {quote(option)}" for option in _SSHFS_OPTIONS)


def _operator_command_prefix(value: Any) -> str:
    prefix = str(value or "").strip()
    return f"{prefix} " if prefix else ""


def _shell_words(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return " ".join(quote(part) for part in shlex.split(text, posix=True))


def _remote_tool(prefix: Any, executable: Any) -> str:
    return _operator_command_prefix(prefix) + _shell_words(executable)


def _remote_arg(value: Any) -> str:
    if isinstance(value, (Path, PurePosixPath)):
        return quote(value.as_posix())
    return quote(str(value))


def _remote_command(tool: str, *args: Any) -> str:
    return " ".join([tool, *(_remote_arg(arg) for arg in args)])


def _remote_share_unmount_snippet() -> str:
    return (
        "if command -v fusermount3 >/dev/null 2>&1; then "
        'fusermount3 -u "$REMOTE_CLUSTER_SHARE" || true; '
        "elif command -v fusermount >/dev/null 2>&1; then "
        'fusermount -u "$REMOTE_CLUSTER_SHARE" || true; '
        'else umount "$REMOTE_CLUSTER_SHARE" || true; fi'
    )


def _sshfs_source_host(source: str) -> str:
    cleaned = str(source or "").strip()
    if cleaned.startswith("sshfs#"):
        cleaned = cleaned.split("#", 1)[1]
    if not cleaned:
        return ""

    if cleaned.startswith("[") or "@[" in cleaned:
        prefix = cleaned.rsplit("]:", 1)[0] + "]" if "]:" in cleaned else cleaned
    elif ":" in cleaned:
        prefix = cleaned.split(":", 1)[0]
    else:
        prefix = cleaned

    host = prefix.rsplit("@", 1)[-1]
    if host.startswith("[") and host.endswith("]"):
        return host[1:-1]
    return host


def _local_mount_record_from_mount_output(path: Path) -> dict[str, str] | None:
    """Fallback mount probe parsing ``mount`` output (findmnt is Linux-only)."""
    try:
        completed = subprocess.run(
            ["mount"],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None

    try:
        resolved = path.expanduser().resolve(strict=False)
    except (OSError, RuntimeError):
        return None

    # BSD/macOS format: ``<source> on <target> (<fstype>, <options>...)``.
    line_re = re.compile(r"^(?P<source>.+?) on (?P<target>/.*?) \((?P<options>[^)]*)\)\s*$")
    best: dict[str, str] | None = None
    best_depth = -1
    for raw_line in completed.stdout.splitlines():
        match = line_re.match(raw_line.strip())
        if not match:
            continue
        target = Path(match.group("target"))
        try:
            if not resolved.is_relative_to(target):
                continue
        except (OSError, ValueError):
            continue
        depth = len(target.parts)
        if depth <= best_depth:
            continue
        fstype = match.group("options").split(",", 1)[0].strip()
        best = {
            "TARGET": match.group("target"),
            "SOURCE": match.group("source"),
            "FSTYPE": fstype,
        }
        best_depth = depth
    return best


def _local_mount_record_for_path(path: Path) -> dict[str, str] | None:
    try:
        completed = subprocess.run(
            [
                "findmnt",
                "-T",
                path.as_posix(),
                "-n",
                "-P",
                "-o",
                "TARGET,SOURCE,FSTYPE",
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except FileNotFoundError:
        # findmnt (util-linux) does not exist on macOS/BSD managers; fall back
        # to parsing ``mount`` output so the reverse-SSHFS guard stays active.
        logger.warning(
            "findmnt is unavailable; probing local mounts for %s via 'mount' output",
            path,
        )
        return _local_mount_record_from_mount_output(path)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None

    line = completed.stdout.strip().splitlines()[0] if completed.stdout.strip() else ""
    if not line:
        return None

    record: dict[str, str] = {}
    try:
        fields = shlex.split(line, posix=True)
    except ValueError:
        return None
    for field in fields:
        if "=" not in field:
            continue
        key, value = field.split("=", 1)
        record[key] = value
    return record or None


def _reverse_sshfs_mount_problem(local_share: Path, worker_ip: str) -> str | None:
    record = _local_mount_record_for_path(local_share)
    if not record:
        return None

    fstype = record.get("FSTYPE", "").lower()
    # macFUSE/FUSE-T SSHFS mounts can surface as "macfuse"/"fuse"/"nfs"
    # fstypes on macOS, so match beyond the Linux "fuse.sshfs" form.
    if not any(marker in fstype for marker in ("sshfs", "fuse", "nfs")):
        return None

    source = record.get("SOURCE", "")
    source_host = _sshfs_source_host(source)
    if source_host != str(worker_ip or "").strip():
        return None

    target = record.get("TARGET", "")
    return (
        f"Refusing to mount AGI_CLUSTER_SHARE on remote worker {worker_ip}: "
        f"scheduler share {local_share.as_posix()} is already inside SSHFS mount "
        f"{target or '<unknown target>'} from the same worker ({source}). "
        "Mounting the scheduler share back onto that worker would create an SSHFS loop. "
        f"{_REVERSE_SSHFS_LOOP_HINT}"
    )


def _home_relative_share_setting(value: str, env: Any) -> str:
    cleaned = str(value or "").strip() or "clustershare"
    normalized = cleaned.replace("\\", "/")

    for raw_home in (getattr(env, "home_abs", None), Path.home()):
        if not raw_home:
            continue
        try:
            home = Path(raw_home).expanduser().resolve(strict=False)
            candidate = Path(cleaned).expanduser()
            if candidate.is_absolute():
                relative = candidate.resolve(strict=False).relative_to(home)
                if relative.parts:
                    return relative.as_posix()
        except (OSError, RuntimeError, TypeError, ValueError):
            continue

    home_match = re.match(r"^(?:[A-Za-z]:)?/(?:Users|home)/[^/]+/(.+)$", normalized)
    if home_match:
        return home_match.group(1)
    return cleaned


def _remote_cluster_share_root_setting(
    remote_share: str,
    *,
    local_share_setting: str,
    env: Any,
) -> str:
    """Return the worker-side AGI_CLUSTER_SHARE root, not a per-run subpath."""

    remote_setting = _home_relative_share_setting(remote_share, env)
    requested = PurePosixPath(remote_setting.replace("\\", "/"))
    configured_text = _home_relative_share_setting(local_share_setting, env)
    configured = PurePosixPath(configured_text.replace("\\", "/"))

    if configured_text and not configured.is_absolute():
        try:
            requested.relative_to(configured)
        except ValueError:
            pass
        else:
            return configured.as_posix()

    user = str(getattr(env, "user", "") or "").strip()
    requested_parts = tuple(part for part in requested.parts if part not in {"", "."})
    if (
        user
        and not requested.is_absolute()
        and len(requested_parts) >= 4
        and requested_parts[0] in {"clustershare", "datashare"}
        and requested_parts[1] == user
    ):
        return PurePosixPath(*requested_parts[:2]).as_posix()

    return remote_setting


def _scheduler_host_from_state(agi_cls: Any) -> str:
    raw_host = (
        getattr(agi_cls, "_scheduler_ip", None)
        or getattr(agi_cls, "_scheduler", None)
        or ""
    )
    host = str(raw_host).strip()
    if host.startswith("tcp://"):
        host = host.removeprefix("tcp://")
    if "@" in host:
        host = host.rsplit("@", 1)[-1]
    if host.startswith("[") and "]" in host:
        return host[1:].split("]", 1)[0]
    if host.count(":") == 1:
        host = host.rsplit(":", 1)[0]
    return host


def _scheduler_ssh_target(agi_cls: Any, env: Any) -> str:
    host = _scheduler_host_from_state(agi_cls)
    if not host:
        return ""
    user = str(getattr(env, "user", "") or "").strip()
    return f"{user}@{host}" if user else host


def _remote_env_update_command(remote_share: str, workflow_data_root: str | None = None) -> str:
    # Update only worker cluster-mode lines: the remote ~/.agilab/.env holds other
    # operator-managed settings that must be preserved (merge semantics,
    # matching install.sh/write_env_updates).  Remote workers resolve relative
    # app outputs through the active share mode, so the share path and cluster
    # flag must be written together; Dask workers also need worker layout flags
    # because AgiEnv reads those from the persisted .env file during startup.
    source_line = "IS_SOURCE_ENV='0'"
    worker_line = "IS_WORKER_ENV='1'"
    enabled_line = "AGI_CLUSTER_ENABLED='1'"
    share_line = f"AGI_CLUSTER_SHARE={remote_share!r}"
    workflow_root_line = f"AGILAB_WORKFLOW_DATA_ROOT={(workflow_data_root or remote_share)!r}"
    return (
        'mkdir -p "$HOME/.agilab" && touch "$HOME/.agilab/.env" && '
        "{ grep -Ev '^(IS_SOURCE_ENV|IS_WORKER_ENV|AGI_CLUSTER_ENABLED|AGI_CLUSTER_SHARE|AGILAB_WORKFLOW_DATA_ROOT)=' "
        "\"$HOME/.agilab/.env\" || true; "
        f"printf '%s\\n' {quote(source_line)} {quote(worker_line)} "
        f"{quote(enabled_line)} {quote(share_line)} {quote(workflow_root_line)}; }} "
        "> \"$HOME/.agilab/.env.tmp\" && "
        'mv "$HOME/.agilab/.env.tmp" "$HOME/.agilab/.env"'
    )


def _remote_share_mount_command(
    *,
    scheduler_target: str,
    scheduler_ssh_port: int,
    local_share: Path,
    remote_share: str,
) -> str:
    source = f"{scheduler_target}:{local_share.as_posix()}"
    sshfs_options = _sshfs_options_args()
    unmount_snippet = _remote_share_unmount_snippet()
    return (
        _REMOTE_PATH_PREFIX + "set -e; "
        'mkdir -p "$HOME/.agilab"; '
        "if ! command -v sshfs >/dev/null 2>&1; then "
        f"printf '%s\\n' {quote(_SSHFS_INSTALL_HINT)} >&2; exit 70; "
        "fi; "
        f"SCHEDULER_SSH_TARGET={quote(scheduler_target)}; "
        f"SCHEDULER_SSH_PORT={quote(str(scheduler_ssh_port))}; "
        'if ! ssh -p "$SCHEDULER_SSH_PORT" -o BatchMode=yes -o ConnectTimeout=5 "$SCHEDULER_SSH_TARGET" true; then '
        f"printf '%s\\n' {quote(_SCHEDULER_SSH_HINT)} >&2; exit 71; "
        "fi; "
        "REMOTE_CLUSTER_SHARE=" + _remote_share_assignment(remote_share) + "; "
        f"SCHEDULER_CLUSTER_SHARE={quote(source)}; "
        'mkdir -p "$REMOTE_CLUSTER_SHARE"; '
        'MOUNT_LINE=$(mount | grep -F -- "$REMOTE_CLUSTER_SHARE" || true); '
        'if [ -n "$MOUNT_LINE" ]; then '
        'if printf \'%s\\n\' "$MOUNT_LINE" | grep -F -- "$SCHEDULER_CLUSTER_SHARE" >/dev/null 2>&1 '
        '&& test -d "$REMOTE_CLUSTER_SHARE" && test -w "$REMOTE_CLUSTER_SHARE"; then '
        'echo "already mounted: $REMOTE_CLUSTER_SHARE"; '
        "else "
        'echo "stale, unexpected, or unwritable SSHFS mount: $REMOTE_CLUSTER_SHARE; remounting" >&2; '
        + unmount_snippet
        + "; "
        f'sshfs -p "$SCHEDULER_SSH_PORT" "$SCHEDULER_CLUSTER_SHARE" "$REMOTE_CLUSTER_SHARE" {sshfs_options}; '
        "fi; "
        "else "
        f'sshfs -p "$SCHEDULER_SSH_PORT" "$SCHEDULER_CLUSTER_SHARE" "$REMOTE_CLUSTER_SHARE" {sshfs_options}; '
        "fi; "
        'test -d "$REMOTE_CLUSTER_SHARE" && test -w "$REMOTE_CLUSTER_SHARE"'
    )


def _remote_share_premounted_check_command(remote_share: str) -> str:
    return (
        _REMOTE_PATH_PREFIX
        + "set -e; "
        + "REMOTE_CLUSTER_SHARE=" + _remote_share_assignment(remote_share) + "; "
        + "if [ ! -d \"$REMOTE_CLUSTER_SHARE\" ] || [ ! -w \"$REMOTE_CLUSTER_SHARE\" ]; then "
        + "printf '%s\\n' 'Pre-mounted AGILAB cluster share is not visible or writable on the remote worker.' >&2; "
        + "exit 72; "
        + "fi; "
        + 'printf "%s\\n" "$REMOTE_CLUSTER_SHARE"'
    )


async def _prepare_remote_cluster_share(
    agi_cls: Any,
    ip: str,
    env: Any,
    remote_share: str,
    *,
    log: Any = logger,
) -> None:
    local_share_raw = (
        str(getattr(env, "AGI_CLUSTER_SHARE", "") or "")
        or str(
            getattr(env, "envars", {}).get("AGI_CLUSTER_SHARE", "")
            if isinstance(getattr(env, "envars", None), dict)
            else ""
        )
        or remote_share
    )
    local_share = _resolve_local_share_path(local_share_raw, env)
    share_backend = _cluster_share_backend(env)
    share_is_premounted = _remote_cluster_share_premounted(env)
    remote_share_setting = _remote_cluster_share_root_setting(
        remote_share,
        local_share_setting=local_share_raw,
        env=env,
    )
    if not share_is_premounted:
        reverse_mount_problem = _reverse_sshfs_mount_problem(local_share, ip)
        if reverse_mount_problem:
            raise RuntimeError(reverse_mount_problem)
    local_share.mkdir(parents=True, exist_ok=True)

    workflow_data_root_setting = _home_relative_share_setting(remote_share, env)
    await agi_cls.exec_ssh(
        ip,
        _remote_env_update_command(remote_share_setting, workflow_data_root_setting),
    )
    if share_is_premounted:
        if getattr(env, "verbose", 0) > 0:
            log.info(
                "Using pre-mounted AGILAB cluster share (%s) on remote worker %s at %s",
                share_backend,
                ip,
                remote_share_setting,
            )
        await agi_cls.exec_ssh(ip, _remote_share_premounted_check_command(remote_share_setting))
        return

    scheduler_target = _scheduler_ssh_target(agi_cls, env)
    if not scheduler_target:
        raise RuntimeError(
            "Cannot mount AGI_CLUSTER_SHARE on remote worker: scheduler host is unknown."
        )

    mount_cmd = _remote_share_mount_command(
        scheduler_target=scheduler_target,
        scheduler_ssh_port=_scheduler_ssh_port(env),
        local_share=local_share,
        remote_share=remote_share_setting,
    )
    if getattr(env, "verbose", 0) > 0:
        log.info(
            "Mounting scheduler AGI_CLUSTER_SHARE on remote worker %s with SSHFS", ip
        )
    await agi_cls.exec_ssh(ip, mount_cmd)


def _parse_version_prefix(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for raw_part in version.strip().split("."):
        digits = ""
        for char in raw_part:
            if not char.isdigit():
                break
            digits += char
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def _is_legacy_intel_macos(system: str, machine: str, product_version: str) -> bool:
    if system.strip().lower() != "darwin":
        return False
    if machine.strip().lower() not in {"x86_64", "amd64"}:
        return False

    version_parts = _parse_version_prefix(product_version)
    if len(version_parts) < 2:
        return False

    major, minor = version_parts[:2]
    return major == 10 and minor <= 15


def _remote_platform_probe_command() -> str:
    return (
        "printf '%s\\n' "
        '"$(uname -s 2>/dev/null || true)" '
        '"$(uname -m 2>/dev/null || true)" '
        '"$(sw_vers -productVersion 2>/dev/null || true)"'
    )


def _parse_remote_platform_probe(output: str) -> tuple[str, str, str]:
    lines = [line.strip() for line in output.splitlines()]
    padded = (lines + ["", "", ""])[:3]
    return padded[0], padded[1], padded[2]


def _remote_rapids_probe_command(
    uv: str, pyvers: str, cli: PurePosixPath | Path
) -> str:
    return _remote_command(
        uv,
        "run",
        "--no-sync",
        "-p",
        pyvers,
        "python",
        cli,
        "rapids-probe",
    )


def _parse_remote_rapids_probe(output: str) -> bool:
    for raw_line in reversed(output.splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        start = line.find("{")
        end = line.rfind("}")
        if start < 0 or end < start:
            continue
        try:
            payload = json.loads(line[start : end + 1])
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        return bool(payload.get("rapids_capable"))
    raise ValueError(f"Remote RAPIDS probe did not return JSON: {output!r}")


async def _remote_rapids_capability(
    agi_cls: Any,
    ip: str,
    *,
    uv: str,
    pyvers: str,
    cli: PurePosixPath | Path,
) -> bool:
    result = await agi_cls.exec_ssh(ip, _remote_rapids_probe_command(uv, pyvers, cli))
    return _parse_remote_rapids_probe(result)


async def _legacy_intel_macos_dependency_specs(
    agi_cls: Any, ip: str, *, log: Any = logger
) -> tuple[str, ...]:
    try:
        probe = await agi_cls.exec_ssh(ip, _remote_platform_probe_command())
    except ConnectionError:
        raise
    except _REMOTE_PLATFORM_PROBE_EXCEPTIONS as exc:
        log.warning(
            "Could not probe remote worker platform on %s; skipping legacy macOS pins: %s",
            ip,
            exc,
        )
        return ()

    system, machine, product_version = _parse_remote_platform_probe(probe)
    if not _is_legacy_intel_macos(system, machine, product_version):
        return ()

    log.warning(
        "Detected legacy Intel macOS worker %s (%s %s); pre-pinning worker dependencies: %s",
        ip,
        machine,
        product_version,
        ", ".join(_LEGACY_INTEL_MACOS_DEPENDENCY_SPECS),
    )
    return _LEGACY_INTEL_MACOS_DEPENDENCY_SPECS


async def _remote_project_has_pip(
    agi_cls: Any, ip: str, *, uv: str, wenv_rel: Path, pyvers: str
) -> bool:
    try:
        await agi_cls.exec_ssh(
            ip,
            _remote_command(
                uv,
                "--project",
                wenv_rel,
                "run",
                "-p",
                pyvers,
                "python",
                "-c",
                "import pip",
            ),
        )
    except ConnectionError:
        raise
    except _REMOTE_PIP_PROBE_EXCEPTIONS:
        return False
    return True


def _resolve_worker_egg(env: Any, dist_abs: Path, log: Any) -> Path:
    egg_file = _latest_artifact_match(dist_abs, f"{env.target_worker}*.egg")
    if egg_file is None:
        egg_file = _latest_artifact_match(dist_abs, f"{env.app}*.egg")
    if egg_file is None:
        log.error(
            f"searching for {dist_abs / env.target_worker}*.egg or {dist_abs / env.app}*.egg"
        )
        raise FileNotFoundError(
            f"no existing egg file in {dist_abs / env.target_worker}* or {dist_abs / env.app}*"
        )
    return egg_file


async def deploy_remote_worker(
    agi_cls: Any,
    ip: str,
    env: Any,
    *,
    worker_site_packages_dir_fn: Callable[..., Path | PurePosixPath],
    staged_uv_sources_pth_content_fn: Callable[..., str],
    set_env_var_fn: Callable[..., Any] = AgiEnv.set_env_var,
    log: Any = logger,
) -> None:
    """Install packages and bootstrap a remote worker environment."""

    wenv_rel = env.wenv_rel
    dist_abs = env.dist_abs
    pyvers = env.pyvers_worker
    # Operator-managed shell prefix; trusted input prepended verbatim.
    cmd_prefix = env.envars.get(f"{ip}_CMD_PREFIX", "")
    uv = _remote_tool(cmd_prefix, env.uv_worker)

    if agi_cls._workers_data_path:
        await _prepare_remote_cluster_share(
            agi_cls,
            ip,
            env,
            str(agi_cls._workers_data_path),
            log=log,
        )

    egg_file = _resolve_worker_egg(env, dist_abs, log)
    if env.is_source_env:
        wenv = env.agi_env / "dist"
        env_whl = _latest_artifact_match(wenv, "agi_env*.whl")
        if env_whl is None:
            raise FileNotFoundError(f"no existing whl file in {wenv / 'agi_env*'}")

        wenv = env.agi_node / "dist"
        node_whl = _latest_artifact_match(wenv, "agi_node*.whl")
        if node_whl is None:
            raise FileNotFoundError(f"no existing whl file in {wenv / 'agi_node*'}")

        dist_remote = wenv_rel / "dist"
        log.info(f"mkdir {dist_remote}")
        await agi_cls.exec_ssh(ip, f"mkdir -p {_remote_arg(dist_remote)}")
        await agi_cls.send_files(env, ip, [egg_file], wenv_rel)
        await agi_cls.send_files(env, ip, [node_whl, env_whl], dist_remote)
    else:
        await agi_cls.send_files(env, ip, [egg_file], wenv_rel)
        env_whl = None
        node_whl = None

    hw_rapids_capable = False
    cli = env.wenv_rel.parent / "cli.py"
    if agi_cls._rapids_enabled:
        try:
            hw_rapids_capable = await _remote_rapids_capability(
                agi_cls,
                ip,
                uv=uv,
                pyvers=pyvers,
                cli=cli,
            )
        except _REMOTE_RAPIDS_CHECK_EXCEPTIONS:
            log.error(f"rapids is requested but not supported by node [{ip}]")
            raise

        env.hw_rapids_capable = hw_rapids_capable
        if hw_rapids_capable:
            set_env_var_fn(ip, "hw_rapids_capable")
        else:
            set_env_var_fn(ip, "no_rapids_hw")
        log.info(f"Rapids-capable GPU[{ip}]: {hw_rapids_capable}")

    cmd = _remote_command(uv, "run", "-p", pyvers, "python", cli, "unzip", wenv_rel)
    await agi_cls.exec_ssh(ip, cmd)

    if await _remote_project_has_pip(
        agi_cls, ip, uv=uv, wenv_rel=wenv_rel, pyvers=pyvers
    ):
        log.info(
            "[%s] pip is already available in %s; skipping ensurepip.",
            ip,
            wenv_rel.as_posix(),
        )
    else:
        cmd = _remote_command(
            uv, "--project", wenv_rel, "run", "-p", pyvers, "python", "-m", "ensurepip"
        )
        await agi_cls.exec_ssh(ip, cmd)

    compatibility_specs = await _legacy_intel_macos_dependency_specs(
        agi_cls, ip, log=log
    )
    if compatibility_specs:
        cmd = _remote_command(
            uv, "--project", wenv_rel, "add", "-p", pyvers, *compatibility_specs
        )
        await agi_cls.exec_ssh(ip, cmd)

    if env.is_source_env:
        if env_whl is None or node_whl is None:
            raise RuntimeError(
                "source environment remote deployment requires local agi-env and agi-node wheels"
            )
        env_pck: Union[str, Path] = wenv_rel / "dist" / env_whl.name
        node_pck: Union[str, Path] = wenv_rel / "dist" / node_whl.name
    else:
        env_pck = "agi-env"
        node_pck = "agi-node"

    def _pkg_ref(pkg: Union[str, Path]) -> str:
        return pkg.as_posix() if isinstance(pkg, Path) else str(pkg)

    core_package_refs = [_pkg_ref(pkg) for pkg in (env_pck, node_pck)]
    cmd = _remote_command(
        uv, "--project", wenv_rel, "add", "-p", pyvers, "--upgrade", *core_package_refs
    )
    await agi_cls.exec_ssh(ip, cmd)

    if deployment_dask_support.dask_mode_enabled(agi_cls):
        cmd = deployment_dask_support.dask_runtime_install_command(
            uv,
            PurePosixPath(wenv_rel.as_posix()),
            pyvers=pyvers,
        )
        await agi_cls.exec_ssh(ip, cmd)

    remote_site_packages = worker_site_packages_dir_fn(
        PurePosixPath(wenv_rel.as_posix()),
        pyvers,
        windows=False,
    )
    remote_uv_sources = PurePosixPath(wenv_rel.as_posix()) / "_uv_sources"
    pth_content = staged_uv_sources_pth_content_fn(
        remote_site_packages, remote_uv_sources
    )
    tmp_pth = Path(gettempdir()) / f"agilab_uv_sources_{uuid.uuid4().hex}.pth"
    tmp_pth.write_text(pth_content, encoding="utf-8")
    try:
        await agi_cls.exec_ssh(ip, f"mkdir -p {_remote_arg(remote_site_packages)}")
        await agi_cls.send_file(
            env,
            ip,
            tmp_pth,
            remote_site_packages / "agilab_uv_sources.pth",
        )
    finally:
        try:
            tmp_pth.unlink()
        except FileNotFoundError:
            pass

    cmd = _remote_command(
        uv,
        "--project",
        wenv_rel,
        "run",
        "--no-sync",
        "-p",
        pyvers,
        "python",
        cli,
        "unzip",
        wenv_rel,
    )
    await agi_cls.exec_ssh(ip, cmd)

    cmd = _remote_command(
        uv,
        "--project",
        wenv_rel,
        "run",
        "--no-sync",
        "-p",
        pyvers,
        "python",
        "-m",
        env.post_install_rel,
        wenv_rel.stem,
    )
    await agi_cls.exec_ssh(ip, cmd)

    if _cython_mode_enabled(agi_cls):
        quiet_args = () if env.verbose > 1 else ("-q",)
        # Manager-resolved directives travel as an explicit argv because env
        # vars do not survive the SSH command; local and remote builds must
        # resolve the exact same spec.
        directives_spec = _resolved_cython_directives_spec(env)
        directives_args = (
            ("--compiler-directives", directives_spec) if directives_spec else ()
        )
        cmd = _remote_command(
            uv,
            "--project",
            wenv_rel,
            "run",
            "--no-sync",
            *(
                item
                for spec in cython_build_overlay_specs()
                for item in ("--with", spec)
            ),
            "-p",
            pyvers,
            "python",
            "-m",
            "agi_node.agi_dispatcher.build",
            "--app-path",
            wenv_rel,
            *directives_args,
            *quiet_args,
            "build_ext",
            "-b",
            wenv_rel,
        )
        await agi_cls.exec_ssh(ip, cmd)
    else:
        log.info(
            "[%s] Skipping remote Cython build_ext: the cython mode bit is not "
            "set for this deploy (re-install with cython enabled to compile "
            "the worker).",
            ip,
        )

    # Fail fast on a runtime smoke test so a deployment does not report success
    # when the worker environment cannot actually start its threaded entrypoint.
    cmd = _remote_command(
        uv,
        "--project",
        wenv_rel,
        "run",
        "--no-sync",
        "-p",
        pyvers,
        "python",
        cli,
        "threaded",
    )
    await agi_cls.exec_ssh(ip, cmd)
