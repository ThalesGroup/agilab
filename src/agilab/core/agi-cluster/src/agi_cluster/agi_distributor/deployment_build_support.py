import logging
import os
import shutil
from pathlib import Path
from typing import Any, Callable

from agi_env import AgiEnv, normalize_path


logger = logging.getLogger(__name__)


def _worker_packages(baseworker: str) -> str:
    packages = "agi_dispatcher, "
    if baseworker.startswith("Agent"):
        packages += "agent_worker"
    elif baseworker.startswith("Dag"):
        packages += "dag_worker"
    elif baseworker.startswith("Pandas"):
        packages += "pandas_worker"
    elif baseworker.startswith("Polars"):
        packages += "polars_worker"
    elif baseworker.startswith("Fireducks"):
        packages += "fireducks_worker"
    return packages


def _python_site_version(pyvers_worker: str) -> str:
    python_dirs = pyvers_worker.split(".")
    if python_dirs[-1][-1] == "t":
        return python_dirs[0] + "." + python_dirs[1] + "t"
    return python_dirs[0] + "." + python_dirs[1]


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
    _wenv = normalize_path(str(env.wenv_abs))
    is_cy = agi_cls._mode & agi_cls.CYTHON_MODE
    packages = _worker_packages(env.base_worker_cls)

    app_path = env.active_app
    wenv_abs = env.wenv_abs
    module = env.setup_app_module

    uv = env.uv
    cmd_prefix = env.envars.get("127.0.0.1_CMD_PREFIX", "")
    if env.is_free_threading_available:
        uv = cmd_prefix + " PYTHON_GIL=0 " + env.uv
    module_cmd = f"python -m {module}"
    app_path_arg = f"\"{app_path}\""
    wenv_arg = f"\"{wenv_abs}\""

    worker_pyproject_dest = env.wenv_abs / env.worker_pyproject.name
    worker_pyproject_src = env.worker_pyproject if env.worker_pyproject.exists() else env.manager_pyproject
    if not worker_pyproject_src.exists():
        raise FileNotFoundError(f"Missing pyproject.toml for worker environment: {worker_pyproject_src}")
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

    cmd = f"{env.uv} --project {app_path_arg} pip install agi-env "
    await run_fn(cmd, app_path)

    cmd = f"{env.uv} --project {app_path_arg} pip install agi-node "
    await run_fn(cmd, app_path)

    if env.verbose > 1:
        cmd = (
            f"{env.uv} --project {app_path_arg} run --no-sync "
            f"{module_cmd} --app-path {app_path_arg} bdist_egg --packages \"{packages}\" -d {wenv_arg}"
        )
    else:
        cmd = (
            f"{env.uv} --project {app_path_arg} run --no-sync "
            f"{module_cmd} --app-path {app_path_arg} -q bdist_egg --packages \"{packages}\" -d {wenv_arg}"
        )

    await run_fn(cmd, app_path)

    dask_client = agi_cls._dask_client
    if dask_client:
        egg_files = list((wenv_abs / "dist").glob("*.egg"))
        for egg_file in egg_files:
            dask_client.upload_file(str(egg_file))

    if is_cy:
        if env.verbose > 1:
            cmd = (
                f"{env.uv} --project {app_path_arg} run --no-sync "
                f"{module_cmd} --app-path {wenv_arg} build_ext -b {wenv_arg}"
            )
        else:
            cmd = (
                f"{env.uv} --project {app_path_arg} run --no-sync "
                f"{module_cmd} --app-path {wenv_arg} -q build_ext -b {wenv_arg}"
            )

        res = await run_fn(cmd, app_path)
        worker_lib = next(iter((wenv_abs / "dist").glob("*_cy.*")), None)
        if worker_lib is None:
            raise RuntimeError(cmd)

        python_version = _python_site_version(env.pyvers_worker)
        destination_dir = wenv_abs / f".venv/lib/python{python_version}/site-packages"

        os.makedirs(destination_dir, exist_ok=True)
        shutil.copy2(worker_lib, destination_dir / os.path.basename(worker_lib))
        if res != "":
            log.info(res)


async def build_lib_remote(agi_cls: Any, *, log: Any = logger) -> None:
    if (agi_cls._dask_client.scheduler.pool.open == 0) and agi_cls.verbose:
        _runners = list(agi_cls._dask_client.scheduler_info()["workers"].keys())
        log.info("warning: no scheduler found but requested mode is dask=1 => switch to dask")
