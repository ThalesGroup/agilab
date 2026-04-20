import logging
import shutil
from pathlib import Path
from typing import Any, Callable, cast

from agi_env import AgiEnv
from agi_env.share_runtime_support import python_supports_free_threading


logger = logging.getLogger(__name__)


def _sorted_glob_matches(root: Path, pattern: str) -> list[Path]:
    return sorted(root.glob(pattern), key=lambda candidate: candidate.name)


def _latest_glob_match(root: Path, pattern: str) -> Path | None:
    matches = _sorted_glob_matches(root, pattern)
    if not matches:
        return None
    return max(matches, key=lambda candidate: (candidate.stat().st_mtime_ns, candidate.name))


def _worker_packages(baseworker: str | None, *, worker_group: str | None = None) -> str:
    packages = "agi_dispatcher, "
    if worker_group == "dag-worker":
        return packages + "dag_worker"
    if worker_group == "pandas-worker":
        return packages + "pandas_worker"
    if worker_group == "polars-worker":
        return packages + "polars_worker"
    if worker_group == "fireducks-worker":
        return packages + "fireducks_worker"
    if isinstance(baseworker, str) and baseworker.startswith("Agent"):
        packages += "agent_worker"
    elif isinstance(baseworker, str) and baseworker.startswith("Dag"):
        packages += "dag_worker"
    elif isinstance(baseworker, str) and baseworker.startswith("Pandas"):
        packages += "pandas_worker"
    elif isinstance(baseworker, str) and baseworker.startswith("Polars"):
        packages += "polars_worker"
    elif isinstance(baseworker, str) and baseworker.startswith("Fireducks"):
        packages += "fireducks_worker"
    return packages


def _python_site_version(pyvers_worker: str) -> str:
    python_dirs = pyvers_worker.split(".")
    if python_dirs[-1][-1] == "t":
        return python_dirs[0] + "." + python_dirs[1]
    return python_dirs[0] + "." + python_dirs[1]


def _project_uv(env: Any) -> str:
    if not env.is_free_threading_available or not python_supports_free_threading():
        return str(env.uv)
    cmd_prefix = str(env.envars.get("127.0.0.1_CMD_PREFIX", "")).strip()
    return " ".join(part for part in (cmd_prefix, "PYTHON_GIL=0", env.uv) if part)


def _worker_pyproject_source(env: Any) -> Path:
    worker_pyproject_src = cast(
        Path,
        env.worker_pyproject if env.worker_pyproject.exists() else env.manager_pyproject,
    )
    if not worker_pyproject_src.exists():
        raise FileNotFoundError(f"Missing pyproject.toml for worker environment: {worker_pyproject_src}")
    return worker_pyproject_src


def _core_install_commands(*, env: Any, uv: str, app_path_arg: str) -> list[str]:
    commands: list[str] = []
    core_packages = (
        ("agi-env", getattr(env, "agi_env", None)),
        ("agi-node", getattr(env, "agi_node", None)),
    )
    for package_name, source_path in core_packages:
        if getattr(env, "is_source_env", False) and source_path:
            commands.append(f"{uv} --project {app_path_arg} pip install --no-deps -e '{source_path}'")
        else:
            commands.append(f"{uv} --project {app_path_arg} pip install {package_name} ")
    return commands


def _build_module_command(env: Any) -> str:
    if getattr(env, "is_source_env", False):
        agi_node_root = getattr(env, "agi_node", None)
        if agi_node_root:
            candidates = [
                Path(agi_node_root) / "agi_dispatcher" / "build.py",
                Path(agi_node_root) / "src" / "agi_node" / "agi_dispatcher" / "build.py",
            ]
            for build_script in candidates:
                if build_script.exists():
                    return f"python \"{build_script}\""
    return f"python -m {env.setup_app_module}"


def _stage_worker_build_project(
    agi_cls: Any,
    env: Any,
    *,
    ensure_optional_extras_fn: Callable[..., Any],
    stage_uv_sources_fn: Callable[..., Any],
    validate_worker_uv_sources_fn: Callable[..., Any],
) -> None:
    worker_pyproject_dest = env.wenv_abs / env.worker_pyproject.name
    worker_pyproject_src = _worker_pyproject_source(env)
    shutil.copy(worker_pyproject_src, worker_pyproject_dest)
    ensure_optional_extras_fn(worker_pyproject_dest, set(getattr(agi_cls, "agi_workers", {}).values()))
    if env.uvproject.exists():
        shutil.copy(env.uvproject, env.wenv_abs)
    stage_uv_sources_fn(
        src_pyproject=worker_pyproject_src,
        dest_pyproject=worker_pyproject_dest,
        stage_root=env.wenv_abs,
        log_rewrites=bool(getattr(env, "verbose", 0)),
    )
    validate_worker_uv_sources_fn(worker_pyproject_dest)


def _bdist_egg_command(*, uv: str, module_cmd: str, app_path_arg: str, packages: str, wenv_arg: str, verbose: int) -> str:
    quiet_flag = "" if verbose > 1 else "-q "
    return (
        f"{uv} --project {app_path_arg} run --no-sync "
        f"{module_cmd} --app-path {app_path_arg} {quiet_flag}"
        f"bdist_egg --packages \"{packages}\" -d {wenv_arg}"
    )


def _build_ext_command(*, uv: str, module_cmd: str, app_path_arg: str, wenv_arg: str, verbose: int) -> str:
    quiet_flag = "" if verbose > 1 else "-q "
    return (
        f"{uv} --project {app_path_arg} run --no-sync "
        f"{module_cmd} --app-path {wenv_arg} {quiet_flag}build_ext -b {wenv_arg}"
    )


def _upload_built_eggs(dask_client: Any, dist_dir: Path) -> None:
    if not dask_client:
        return
    for egg_file in _sorted_glob_matches(dist_dir, "*.egg"):
        dask_client.upload_file(str(egg_file))


def _copy_cython_worker_lib(
    *,
    wenv_abs: Path,
    pyvers_worker: str,
    build_output: str,
    failure_message: str,
    log: Any = logger,
) -> None:
    worker_lib = _latest_glob_match(wenv_abs / "dist", "*_cy.*")
    if worker_lib is None:
        raise RuntimeError(failure_message)

    python_version = _python_site_version(pyvers_worker)
    destination_dir = wenv_abs / f".venv/lib/python{python_version}/site-packages"
    destination_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(worker_lib, destination_dir / worker_lib.name)
    if build_output:
        log.info(build_output)


async def build_lib_local(
    agi_cls: Any,
    *,
    ensure_optional_extras_fn: Callable[..., Any],
    stage_uv_sources_fn: Callable[..., Any],
    validate_worker_uv_sources_fn: Callable[..., Any],
    run_fn: Callable[..., Any] = AgiEnv.run,
    log: Any = logger,
) -> None:
    env = agi_cls.env
    is_cy = agi_cls._mode & agi_cls.CYTHON_MODE
    install_worker_group = getattr(agi_cls, "install_worker_group", None)
    worker_group = install_worker_group[0] if install_worker_group else None
    packages = _worker_packages(env.base_worker_cls, worker_group=worker_group)

    app_path = env.active_app
    wenv_abs = env.wenv_abs
    uv = _project_uv(env)
    module_cmd = _build_module_command(env)
    app_path_arg = f"\"{app_path}\""
    wenv_arg = f"\"{wenv_abs}\""

    _stage_worker_build_project(
        agi_cls,
        env,
        ensure_optional_extras_fn=ensure_optional_extras_fn,
        stage_uv_sources_fn=stage_uv_sources_fn,
        validate_worker_uv_sources_fn=validate_worker_uv_sources_fn,
    )

    for cmd in _core_install_commands(env=env, uv=uv, app_path_arg=app_path_arg):
        await run_fn(cmd, app_path)

    cmd = _bdist_egg_command(
        uv=uv,
        module_cmd=module_cmd,
        app_path_arg=app_path_arg,
        packages=packages,
        wenv_arg=wenv_arg,
        verbose=env.verbose,
    )
    await run_fn(cmd, app_path)

    _upload_built_eggs(agi_cls._dask_client, wenv_abs / "dist")

    if is_cy:
        cmd = _build_ext_command(
            uv=uv,
            module_cmd=module_cmd,
            app_path_arg=app_path_arg,
            wenv_arg=wenv_arg,
            verbose=env.verbose,
        )
        res = await run_fn(cmd, app_path)
        _copy_cython_worker_lib(
            wenv_abs=wenv_abs,
            pyvers_worker=env.pyvers_worker,
            build_output=res,
            failure_message=cmd,
            log=log,
        )


async def build_lib_remote(agi_cls: Any, *, log: Any = logger) -> None:
    if (agi_cls._dask_client.scheduler.pool.open == 0) and agi_cls.verbose:
        _runners = list(agi_cls._dask_client.scheduler_info()["workers"].keys())
        log.info("warning: no scheduler found but requested mode is dask=1 => switch to dask")
