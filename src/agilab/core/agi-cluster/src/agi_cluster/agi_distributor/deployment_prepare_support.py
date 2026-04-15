import logging
import os
import shlex
import shutil
import socket
from ipaddress import ip_address as is_ip
from pathlib import Path
from tempfile import mkdtemp
from typing import Any, Callable, Optional, Set

from asyncssh.process import ProcessError

from agi_cluster.agi_distributor import cli as distributor_cli
from agi_env import AgiEnv


logger = logging.getLogger(__name__)


async def uninstall_modules(agi_cls: Any, env: AgiEnv, *, run_fn: Callable[..., Any] = AgiEnv.run, log: Any = logger) -> None:
    for module in agi_cls._module_to_clean:
        cmd = f"{env.uv} pip uninstall {module} -y"
        log.info(f"Executing: {cmd}")
        await run_fn(cmd, agi_cls.env.agi_env)
    agi_cls._module_to_clean.clear()


def venv_todo(agi_cls: Any, list_ip: Set[str], *, log: Any = logger) -> None:
    agi_cls._local_ip, agi_cls._remote_ip = [], []
    for ip in list_ip:
        (agi_cls._local_ip.append(ip) if AgiEnv.is_local(ip) else agi_cls._remote_ip.append(ip))
    agi_cls._install_todo = 2 * len(agi_cls._remote_ip)
    if agi_cls.env.verbose > 0:
        log.info(f"remote worker to install: {agi_cls._install_todo} ")


async def prepare_local_env(
    agi_cls: Any,
    *,
    envar_truthy_fn: Callable[[dict, str], bool],
    detect_export_cmd_fn: Callable[[str], Any],
    set_env_var_fn: Callable[..., Any] = AgiEnv.set_env_var,
    run_fn: Callable[..., Any] = AgiEnv.run,
    python_version_fn: Callable[[], str] = distributor_cli.python_version,
    log: Any = logger,
) -> None:
    env = agi_cls.env
    wenv_abs = env.wenv_abs
    pyvers = env.python_version
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
        if os.name == "nt":
            standalone_uv = Path.home() / ".local" / "bin" / "uv.exe"
            if standalone_uv.exists():
                uv_parts = shlex.split(env.uv)
                if uv_parts:
                    uv_parts[0] = str(standalone_uv)
                    windows_uv = cmd_prefix + " ".join(shlex.quote(part) for part in uv_parts)
                else:
                    windows_uv = cmd_prefix + shlex.quote(str(standalone_uv))
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
        else:
            try:
                await run_fn(f"{uv} self update", wenv_abs.parent)
            except RuntimeError as exc:
                log.warning("Failed to update uv (skipping self update): %s", exc)

        try:
            await run_fn(f"{uv} python install {pyvers}", wenv_abs.parent)
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
        cmd = f"{uv} --project {wenv_abs} init --bare --no-workspace"
        await run_fn(cmd, wenv_abs)


async def prepare_cluster_env(
    agi_cls: Any,
    scheduler_addr: Optional[str],
    *,
    envar_truthy_fn: Callable[[dict, str], bool],
    detect_export_cmd_fn: Callable[[str], Any],
    ensure_optional_extras_fn: Callable[..., Any],
    stage_uv_sources_fn: Callable[..., list[Path]],
    run_exec_ssh_fn: Callable[..., Any],
    send_files_fn: Callable[..., Any],
    kill_fn: Callable[..., Any],
    clean_dirs_fn: Callable[..., Any],
    mkdtemp_fn: Callable[..., str] = mkdtemp,
    process_error_type: type[BaseException] = ProcessError,
    set_env_var_fn: Callable[..., Any] = AgiEnv.set_env_var,
    log: Any = logger,
) -> None:
    list_ip = set(list(agi_cls._workers) + [agi_cls._get_scheduler(scheduler_addr)[0]])
    localhost_ip = socket.gethostbyname("localhost")
    env = agi_cls.env
    dist_rel = env.dist_rel
    wenv_rel = env.wenv_rel
    pyvers_worker = env.pyvers_worker

    if not list_ip:
        list_ip.add(localhost_ip)

    remote_command_failures = tuple(dict.fromkeys((process_error_type, RuntimeError, OSError)))
    staged_pyproject_fallback_errors = tuple(dict.fromkeys((process_error_type, OSError, RuntimeError, ValueError)))

    for ip in list_ip:
        if not env.is_local(ip) and not is_ip(ip):
            raise ValueError(f"Invalid IP address: {ip}")

    agi_cls.list_ip = list_ip
    for ip in list_ip:
        if env.is_local(ip):
            continue

        cmd_prefix = await detect_export_cmd_fn(ip)
        set_env_var_fn(f"{ip}_CMD_PREFIX", cmd_prefix)
        uv_is_installed = True

        agi_internet_on = 1 if envar_truthy_fn(env.envars, "AGI_INTERNET_ON") else 0
        try:
            await run_exec_ssh_fn(ip, f"{cmd_prefix}{env.uv} --version")
        except ConnectionError:
            raise
        except remote_command_failures:
            uv_is_installed = False
            if agi_internet_on == 0:
                log.error("Uv binary is not installed, please install it manually on the workers.")
                raise EnvironmentError("Uv binary is not installed, please install it manually on the workers.")

            try:
                await run_exec_ssh_fn(
                    ip,
                    'powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"',
                )
                uv_is_installed = True
            except ConnectionError:
                raise
            except remote_command_failures:
                uv_is_installed = False
                await run_exec_ssh_fn(ip, 'curl -LsSf https://astral.sh/uv/install.sh | sh')
                uv_is_installed = True

        if not uv_is_installed:
            log.error("Failed to install uv")
            raise EnvironmentError("Failed to install uv")

        if agi_internet_on == 1:
            try:
                await run_exec_ssh_fn(ip, f"{cmd_prefix}{env.uv} self update")
            except ConnectionError:
                raise
            except remote_command_failures as exc:
                log.warning("Failed to update uv on %s (skipping self update): %s", ip, exc)
        else:
            log.warning("You appears to be on a local network. Please be sure to have uv latest release.")

        cmd_prefix = env.envars.get(f"{ip}_CMD_PREFIX", "")
        uv = cmd_prefix + env.uv

        cmd = f"{uv} run python -c \"import os; os.makedirs('{dist_rel.parents[1]}', exist_ok=True)\""
        await run_exec_ssh_fn(ip, cmd)

        try:
            await run_exec_ssh_fn(ip, f"{uv} python install {pyvers_worker}")
        except process_error_type as exc:
            if "No download found for request" in str(exc):
                log.warning(
                    "[%s] uv could not download interpreter '%s'; assuming a system interpreter is available",
                    ip,
                    pyvers_worker,
                )
            else:
                raise

        await send_files_fn(env, ip, [env.cluster_pck / "agi_distributor/cli.py"], wenv_rel.parent)

        await kill_fn(ip, force=True)
        await clean_dirs_fn(ip)

        cmd = f"{uv} run python -c \"import os; os.makedirs('{dist_rel}', exist_ok=True)\""
        await run_exec_ssh_fn(ip, cmd)

        files_to_send: list[Path] = []
        staged_tmp_dir: Path | None = None
        try:
            pyproject_src = env.worker_pyproject if env.worker_pyproject.exists() else env.manager_pyproject
            if pyproject_src.exists():
                extras_to_seed = set(getattr(agi_cls, "agi_workers", {}).values())
                try:
                    staged_tmp_dir = Path(mkdtemp_fn(prefix=f"agilab_{env.target_worker}_pyproject_"))
                    tmp_pyproject = staged_tmp_dir / "pyproject.toml"
                    shutil.copy(pyproject_src, tmp_pyproject)
                    ensure_optional_extras_fn(tmp_pyproject, extras_to_seed)
                    staged_entries = stage_uv_sources_fn(
                        src_pyproject=pyproject_src,
                        dest_pyproject=tmp_pyproject,
                        stage_root=staged_tmp_dir,
                        log_rewrites=bool(getattr(env, "verbose", 0)),
                    )
                    files_to_send.append(tmp_pyproject)
                    files_to_send.extend(staged_entries)
                except staged_pyproject_fallback_errors:
                    if staged_tmp_dir is not None:
                        shutil.rmtree(staged_tmp_dir, ignore_errors=True)
                        staged_tmp_dir = None
                    files_to_send.append(pyproject_src)
            if env.uvproject.exists():
                files_to_send.append(env.uvproject)
            await send_files_fn(env, ip, files_to_send, wenv_rel)
        finally:
            if staged_tmp_dir is not None:
                shutil.rmtree(staged_tmp_dir, ignore_errors=True)
