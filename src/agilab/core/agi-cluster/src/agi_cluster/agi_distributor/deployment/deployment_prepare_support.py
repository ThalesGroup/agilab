import asyncio
import logging
import os
import shlex
import shutil
from ipaddress import ip_address as is_ip
from pathlib import Path
from tempfile import mkdtemp
from typing import Any, Callable, Optional, Set, cast

from asyncssh.process import ProcessError

from agi_cluster.agi_distributor import cli as distributor_cli, deployment_remote_support
from agi_cluster.agi_distributor.api.worker_cli_support import resolve_worker_cli_path
from agi_cluster.agi_distributor.deployment.deployment_python_support import (
    _normalize_worker_requires_python_floor,
)
from agi_env import AgiEnv


logger = logging.getLogger(__name__)
UV_SELF_UPDATE_ENV = "AGILAB_UV_SELF_UPDATE"


def _is_local_ip(ip: str) -> bool:
    is_local = cast(Callable[[str], bool], AgiEnv.is_local)
    return is_local(ip)


async def _gather_with_cancel_on_failure(coros: list[Any]) -> list[Any]:
    """Run per-node coroutines concurrently, preserving input order in results.

    Mirrors ``deploy_application``'s cancel-on-failure semantics: if any task
    fails, the remaining sibling tasks are cancelled and awaited before the
    original error propagates, so a failing node cannot leave sibling install
    work running unobserved (which a retry would then race).
    ``asyncio.gather`` preserves the order of the input coroutines in its
    results, so callers can rely on stable IP ordering.
    """
    tasks = [asyncio.create_task(coro) for coro in coros]
    try:
        return await asyncio.gather(*tasks)
    except BaseException:
        # A failing node must not leave sibling tasks running unobserved
        # (a retry would then race half-finished installs).
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


def _uv_self_update_enabled(
    envars: dict[str, Any],
    envar_truthy_fn: Callable[[dict[str, Any], str], bool],
) -> bool:
    return envar_truthy_fn(envars, UV_SELF_UPDATE_ENV)


async def _local_uv_python_available(
    uv: str,
    pyvers: str,
    cwd: Path,
    *,
    run_fn: Callable[..., Any],
) -> bool:
    try:
        await run_fn(f"{uv} python find {shlex.quote(str(pyvers))}", cwd)
    except RuntimeError:
        return False
    return True


async def _remote_uv_python_available(
    ip: str,
    uv: str,
    pyvers: str,
    *,
    run_exec_ssh_fn: Callable[..., Any],
    remote_command_failures: tuple[type[BaseException], ...],
) -> bool:
    try:
        await run_exec_ssh_fn(
            ip,
            deployment_remote_support._remote_command(uv, "python", "find", pyvers),
        )
    except remote_command_failures:
        return False
    return True


def _exception_types(*exc_types: type[BaseException]) -> tuple[type[BaseException], ...]:
    return tuple(dict.fromkeys(exc_types))


def _staged_uv_install_command() -> str:
    return (
        "tmp=$(mktemp -t agilab-uv-install.XXXXXX.sh) && "
        "trap 'rm -f \"$tmp\"' EXIT && "
        "curl --proto '=https' --tlsv1.2 -LsSf https://astral.sh/uv/install.sh -o \"$tmp\" && "
        "chmod 700 \"$tmp\" && "
        "sh \"$tmp\""
    )


def _staged_uv_powershell_install_command() -> str:
    return (
        'powershell -ExecutionPolicy ByPass -c "'
        "$p=Join-Path $env:TEMP 'agilab-uv-install.ps1'; "
        "Invoke-WebRequest -UseBasicParsing https://astral.sh/uv/install.ps1 -OutFile $p; "
        "powershell -ExecutionPolicy ByPass -File $p; "
        "Remove-Item -Force $p"
        '"'
    )


def _remote_python_makedirs_command(uv: str, path: Path) -> str:
    remote_path = path.as_posix()
    script = f"import os; os.makedirs({remote_path!r}, exist_ok=True)"
    return deployment_remote_support._remote_command(uv, "run", "python", "-c", script)


async def uninstall_modules(agi_cls: Any, env: AgiEnv, *, run_fn: Callable[..., Any] = AgiEnv.run, log: Any = logger) -> None:
    for module in agi_cls._module_to_clean:
        cmd = f"{env.uv} pip uninstall {shlex.quote(str(module))} -y"
        log.info(f"Executing: {cmd}")
        await run_fn(cmd, agi_cls.env.agi_env)
    agi_cls._module_to_clean.clear()


def venv_todo(agi_cls: Any, list_ip: Set[str], *, log: Any = logger) -> None:
    agi_cls._local_ip, agi_cls._remote_ip = [], []
    for ip in list_ip:
        (agi_cls._local_ip.append(ip) if _is_local_ip(ip) else agi_cls._remote_ip.append(ip))
    agi_cls._install_todo = 2 * len(agi_cls._remote_ip)
    if agi_cls.env.verbose > 0:
        log.info(f"remote worker to install: {agi_cls._install_todo} ")


async def prepare_local_env(
    agi_cls: Any,
    *,
    envar_truthy_fn: Callable[[dict[str, Any], str], bool],
    detect_export_cmd_fn: Callable[[str], Any],
    set_env_var_fn: Callable[..., Any] = AgiEnv.set_env_var,
    run_fn: Callable[..., Any] = AgiEnv.run,
    python_version_fn: Callable[[], str] = distributor_cli.python_version,
    log: Any = logger,
) -> None:
    env = agi_cls.env
    wenv_abs = env.wenv_abs
    pyvers = env.python_version
    pyvers_uv_spec = getattr(env, "python_uv_spec", None) or pyvers
    ip = "127.0.0.1"
    hw_rapids_capable = agi_cls._hardware_supports_rapids() and agi_cls._rapids_enabled
    env.hw_rapids_capable = hw_rapids_capable

    if hw_rapids_capable:
        set_env_var_fn(ip, "hw_rapids_capable")
    else:
        set_env_var_fn(ip, "no_rapids_hw")

    if env.verbose > 0:
        log.info(f"Rapids-capable GPU[{ip}]: {hw_rapids_capable}")

    cmd_prefix = await detect_export_cmd_fn(ip)
    set_env_var_fn(f"{ip}_CMD_PREFIX", cmd_prefix)
    uv = cmd_prefix + env.uv

    log.info(f"mkdir {wenv_abs}")
    wenv_abs.mkdir(parents=True, exist_ok=True)

    if envar_truthy_fn(env.envars, "AGI_INTERNET_ON"):
        if _uv_self_update_enabled(env.envars, envar_truthy_fn) and os.name == "nt":
            standalone_uv = Path.home() / ".local" / "bin" / "uv.exe"
            if standalone_uv.exists():
                # ``shlex.quote`` produces POSIX-style single quotes that
                # cmd.exe does not interpret, so build a cmd-friendly string
                # instead: keep the path bare when it has no spaces, otherwise
                # wrap in double quotes.
                def _windows_quote(part: str) -> str:
                    return f'"{part}"' if " " in part else part

                uv_parts = shlex.split(env.uv)
                if uv_parts:
                    uv_parts[0] = str(standalone_uv)
                    windows_uv = cmd_prefix + " ".join(
                        _windows_quote(part) for part in uv_parts
                    )
                else:
                    windows_uv = cmd_prefix + _windows_quote(str(standalone_uv))
                try:
                    await run_fn(f"{windows_uv} self update", wenv_abs.parent)
                except RuntimeError as exc:
                    log.warning(
                        "Failed to update standalone uv at %s (skipping self update): %s",
                        standalone_uv,
                        exc,
                    )
            else:
                log.warning(
                    "Standalone uv not found at %s; skipping 'uv self update' on Windows",
                    standalone_uv,
                )
        elif _uv_self_update_enabled(env.envars, envar_truthy_fn):
            try:
                await run_fn(f"{uv} self update", wenv_abs.parent)
            except RuntimeError as exc:
                log.warning("Failed to update uv (skipping self update): %s", exc)

        if await _local_uv_python_available(uv, pyvers_uv_spec, wenv_abs.parent, run_fn=run_fn):
            log.info("Python interpreter '%s' is already available to uv; skipping install.", pyvers)
        else:
            try:
                await run_fn(f"{uv} python install {shlex.quote(str(pyvers_uv_spec))}", wenv_abs.parent)
            except RuntimeError as exc:
                if "No download found for request" in str(exc):
                    log.warning(
                        "uv could not download interpreter '%s'; assuming a system interpreter is available",
                        pyvers,
                    )
                else:
                    raise
    else:
        log.warning("No internet connection detected; skipping uv update and assuming a system interpreter is available")

    res = python_version_fn() or ""
    pyvers = res.strip()
    set_env_var_fn(f"{ip}_PYTHON_VERSION", pyvers)

    if env.is_worker_env:
        cmd = f'{uv} --project "{wenv_abs}" init --bare --no-workspace'
        await run_fn(cmd, wenv_abs)


async def prepare_cluster_env(
    agi_cls: Any,
    scheduler_addr: Optional[str],
    *,
    envar_truthy_fn: Callable[[dict[str, Any], str], bool],
    detect_export_cmd_fn: Callable[[str], Any],
    ensure_optional_extras_fn: Callable[..., Any],
    stage_uv_sources_fn: Callable[..., list[Path]],
    run_exec_ssh_fn: Callable[..., Any],
    send_files_fn: Callable[..., Any],
    kill_fn: Callable[..., Any],
    clean_dirs_fn: Callable[..., Any],
    acquire_remote_target_lease_fn: Optional[Callable[..., Any]] = None,
    mkdtemp_fn: Callable[..., str] = mkdtemp,
    process_error_type: type[BaseException] = ProcessError,
    set_env_var_fn: Callable[..., Any] = AgiEnv.set_env_var,
    log: Any = logger,
) -> None:
    list_ip = set(list(agi_cls._workers) + [agi_cls._get_scheduler(scheduler_addr)[0]])
    env = agi_cls.env
    dist_rel = env.dist_rel
    wenv_rel = env.wenv_rel
    pyvers_worker = env.pyvers_worker
    pyvers_worker_uv_spec = (
        getattr(env, "pyvers_worker_uv_spec", None) or pyvers_worker
    )

    remote_command_failures = _exception_types(process_error_type, RuntimeError, OSError)
    staged_pyproject_fallback_errors = _exception_types(
        process_error_type,
        OSError,
        RuntimeError,
        ValueError,
    )

    for ip in list_ip:
        if not env.is_local(ip):
            try:
                is_ip(ip)
            except ValueError as exc:
                raise ValueError(f"Invalid IP address: {ip}") from exc

    agi_cls.list_ip = list_ip
    # Stable IP order for deterministic set_env_var writes and legacy detection.
    remote_ips = [ip for ip in sorted(list_ip) if not env.is_local(ip)]

    async def _probe_remote_platform(ip: str) -> dict[str, Any]:
        # Loop-1 body: detect the shell prefix and run the platform probe.
        # Env writes and legacy-set updates are deferred to the caller so they
        # happen deterministically in stable IP order after every probe
        # completes (the cross-node legacy-Intel-macOS decision below MUST see
        # all loop-1 probes before loop-2 begins). ConnectionError propagates
        # (mirroring the original inline ``except ConnectionError: raise``);
        # other remote command failures are recorded as a warning to emit
        # later without aborting sibling probes.
        cmd_prefix = await detect_export_cmd_fn(ip)
        result: dict[str, Any] = {"ip": ip, "cmd_prefix": cmd_prefix, "is_legacy": False, "warning": None}
        try:
            platform_probe = await run_exec_ssh_fn(ip, deployment_remote_support._remote_platform_probe_command())
        except ConnectionError:
            raise
        except remote_command_failures as exc:
            result["warning"] = exc
        else:
            system, machine, product_version = deployment_remote_support._parse_remote_platform_probe(platform_probe)
            result["is_legacy"] = deployment_remote_support._is_legacy_intel_macos(system, machine, product_version)
        return result

    probe_results = await _gather_with_cancel_on_failure(
        [_probe_remote_platform(ip) for ip in remote_ips]
    )

    legacy_intel_macos_ips: set[str] = set()
    for result in probe_results:
        ip = result["ip"]
        set_env_var_fn(f"{ip}_CMD_PREFIX", result["cmd_prefix"])
        if result["warning"] is not None:
            log.warning(
                "Could not probe remote worker platform on %s; skipping legacy macOS runtime selection: %s",
                ip,
                result["warning"],
            )
        elif result["is_legacy"]:
            legacy_intel_macos_ips.add(ip)

    # Persist the probe result so deploy_remote_worker can reuse it instead of
    # re-running the platform probe over SSH once per worker in the same flow.
    agi_cls._legacy_intel_macos_ips = set(legacy_intel_macos_ips)

    if legacy_intel_macos_ips and (
        pyvers_worker != "3.12" or pyvers_worker_uv_spec != "3.12"
    ):
        log.warning(
            "Detected legacy Intel macOS worker(s) %s; selecting Python 3.12 for all worker environments instead of %s",
            ", ".join(sorted(legacy_intel_macos_ips)),
            pyvers_worker,
        )
        pyvers_worker = "3.12"
        env.pyvers_worker = "3.12"
        env.python_version = "3.12"
        pyvers_worker_uv_spec = "3.12"
        env.pyvers_worker_uv_spec = pyvers_worker_uv_spec
        env.uv_worker = env.uv

    async def _prepare_remote_worker(ip: str) -> list[tuple[str, Any]]:
        # Loop-2 body for a single worker IP. Runs as one task per IP so per-node
        # install work overlaps (mirroring deploy_application). The order of
        # steps WITHIN a node is preserved exactly, as are all error paths.
        # Any set_env_var write is collected and returned so the caller can apply
        # it deterministically in stable IP order after the gather, keeping env
        # state from interleaving across concurrent tasks.
        pending_env_writes: list[tuple[str, Any]] = []

        cmd_prefix = env.envars.get(f"{ip}_CMD_PREFIX")
        if cmd_prefix is None:
            cmd_prefix = await detect_export_cmd_fn(ip)
            pending_env_writes.append((f"{ip}_CMD_PREFIX", cmd_prefix))
        agi_internet_on = 1 if envar_truthy_fn(env.envars, "AGI_INTERNET_ON") else 0
        uv_probe = deployment_remote_support._remote_tool(cmd_prefix, env.uv)
        try:
            await run_exec_ssh_fn(
                ip,
                deployment_remote_support._remote_command(uv_probe, "--version"),
            )
        except ConnectionError:
            raise
        except remote_command_failures:
            if agi_internet_on == 0:
                log.error("Uv binary is not installed, please install it manually on the workers.")
                raise EnvironmentError("Uv binary is not installed, please install it manually on the workers.")

            try:
                await run_exec_ssh_fn(
                    ip,
                    _staged_uv_powershell_install_command(),
                )
            except ConnectionError:
                raise
            except remote_command_failures:
                await run_exec_ssh_fn(ip, _staged_uv_install_command())

        if agi_internet_on == 1 and _uv_self_update_enabled(env.envars, envar_truthy_fn):
            try:
                await run_exec_ssh_fn(
                    ip,
                    deployment_remote_support._remote_command(uv_probe, "self", "update"),
                )
            except remote_command_failures as exc:
                log.warning("Failed to update uv on %s (skipping self update): %s", ip, exc)
        elif agi_internet_on != 1:
            log.warning("You appears to be on a local network. Please be sure to have uv latest release.")

        # Re-read the shell prefix from env state as before, falling back to the
        # value this task computed above (whose write is still pending) so a
        # concurrent sibling cannot observe a partial write.
        cmd_prefix = env.envars.get(f"{ip}_CMD_PREFIX")
        if cmd_prefix is None:
            cmd_prefix = pending_env_writes[-1][1] if pending_env_writes else ""
        uv = deployment_remote_support._remote_tool(cmd_prefix, env.uv)

        cmd = _remote_python_makedirs_command(uv, dist_rel.parents[1])
        await run_exec_ssh_fn(ip, cmd)

        if await _remote_uv_python_available(
            ip,
            uv,
            pyvers_worker_uv_spec,
            run_exec_ssh_fn=run_exec_ssh_fn,
            remote_command_failures=remote_command_failures,
        ):
            log.info("[%s] Python interpreter '%s' is already available to uv; skipping install.", ip, pyvers_worker_uv_spec)
        else:
            try:
                await run_exec_ssh_fn(
                    ip,
                    deployment_remote_support._remote_command(
                        uv,
                        "python",
                        "install",
                        pyvers_worker_uv_spec,
                    ),
                )
            except process_error_type as exc:
                if "No download found for request" in str(exc):
                    log.warning(
                        "[%s] uv could not download interpreter '%s'; assuming a system interpreter is available",
                        ip,
                        pyvers_worker_uv_spec,
                    )
                else:
                    raise

        await send_files_fn(env, ip, [resolve_worker_cli_path(env)], wenv_rel.parent)

        if acquire_remote_target_lease_fn is not None:
            await acquire_remote_target_lease_fn(ip, cmd_prefix=cmd_prefix)
        await kill_fn(ip, force=True)
        await clean_dirs_fn(ip)

        cmd = _remote_python_makedirs_command(uv, dist_rel)
        await run_exec_ssh_fn(ip, cmd)

        files_to_send: list[Path] = []
        staged_tmp_dir: Path | None = None
        try:
            pyproject_src = env.worker_pyproject if env.worker_pyproject.exists() else env.manager_pyproject
            if pyproject_src.exists():
                staged_tmp_dir = Path(mkdtemp_fn(prefix=f"agilab_{env.target_worker}_pyproject_"))
                tmp_pyproject = staged_tmp_dir / "pyproject.toml"
                shutil.copy(pyproject_src, tmp_pyproject)
                _normalize_worker_requires_python_floor(
                    tmp_pyproject,
                    raise_on_parse_error=True,
                )
                normalized_pyproject = tmp_pyproject.read_text(encoding="utf-8")
                extras_to_seed = set(getattr(agi_cls, "agi_workers", {}).values())
                staged_entries: list[Path] = []
                try:
                    ensure_optional_extras_fn(tmp_pyproject, extras_to_seed)
                    staged_entries = stage_uv_sources_fn(
                        src_pyproject=pyproject_src,
                        dest_pyproject=tmp_pyproject,
                        stage_root=staged_tmp_dir,
                        log_rewrites=bool(getattr(env, "verbose", 0)),
                    )
                except staged_pyproject_fallback_errors:
                    # Optional staging may have partially rewritten the temp
                    # manifest before failing.  Keep the fallback payload at
                    # the normalized baseline; never send a half-staged file.
                    tmp_pyproject.write_text(normalized_pyproject, encoding="utf-8")
                    staged_entries = []
                files_to_send.append(tmp_pyproject)
                files_to_send.extend(staged_entries)
            if env.uvproject.exists():
                files_to_send.append(env.uvproject)
            await send_files_fn(env, ip, files_to_send, wenv_rel)
        finally:
            if staged_tmp_dir is not None:
                shutil.rmtree(staged_tmp_dir, ignore_errors=True)

        return pending_env_writes

    worker_env_writes = await _gather_with_cancel_on_failure(
        [_prepare_remote_worker(ip) for ip in remote_ips]
    )
    # Apply deferred env writes deterministically in stable IP order so env
    # state cannot interleave between concurrently running per-IP tasks.
    for pending_env_writes in worker_env_writes:
        for key, value in pending_env_writes:
            set_env_var_fn(key, value)
