import hashlib
import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, cast

from agi_env import AgiEnv
from agi_env.share_runtime_support import python_supports_free_threading


logger = logging.getLogger(__name__)
BUILD_CACHE_SCHEMA = "agilab-worker-build-cache-v1"
DISABLE_BUILD_CACHE_ENV = "AGILAB_DISABLE_WORKER_BUILD_CACHE"
BUILD_CACHE_HASH_LIMIT = 8 * 1024 * 1024
GIT_FINGERPRINT_TIMEOUT_SECONDS = 2.0


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


def _envar_value(envars: Any, key: str) -> Any:
    raw = os.environ.get(key)
    if raw is None:
        try:
            raw = envars.get(key)
        except (AttributeError, RuntimeError, TypeError):
            raw = None
    return raw


def _envar_nonempty(envars: Any, key: str) -> bool:
    raw = _envar_value(envars, key)
    if raw is None:
        return False
    return bool(str(raw).strip().strip("\"'").strip())


def _uv_offline_flag(env: Any) -> str:
    envars = getattr(env, "envars", {})
    raw = _envar_value(envars, "AGI_INTERNET_ON")
    if raw is None:
        return ""
    if _envar_nonempty(envars, "UV_INDEX_URL"):
        return ""
    if isinstance(raw, bool):
        return "" if raw else "--offline "
    if isinstance(raw, (int, float)):
        try:
            return "" if int(raw) == 1 else "--offline "
        except (TypeError, ValueError):
            return "--offline "
    return "" if str(raw).strip().lower() in {"1", "true", "yes", "on"} else "--offline "


def _project_uv(env: Any) -> str:
    if not env.is_free_threading_available or not python_supports_free_threading():
        return str(env.uv)
    cmd_prefix = str(env.envars.get("127.0.0.1_CMD_PREFIX", "")).strip()
    return " ".join(part for part in (cmd_prefix, "PYTHON_GIL=0", env.uv) if part)


def _env_truthy(envars: Any, key: str) -> bool:
    try:
        raw = envars.get(key)
    except (AttributeError, RuntimeError, TypeError):
        raw = None
    if raw is None:
        raw = os.environ.get(key)
    if raw is None:
        return False
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        try:
            return int(raw) == 1
        except (TypeError, ValueError):
            return False
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _build_cache_enabled(env: Any) -> bool:
    return not _env_truthy(getattr(env, "envars", {}), DISABLE_BUILD_CACHE_ENV)


def _file_fingerprint(path: Path) -> dict[str, Any] | None:
    try:
        stat_result = path.stat()
    except FileNotFoundError:
        return None
    if not path.is_file():
        return None
    payload: dict[str, Any] = {
        "path": str(path.resolve(strict=False)),
        "size": stat_result.st_size,
        "mtime_ns": stat_result.st_mtime_ns,
    }
    if stat_result.st_size <= BUILD_CACHE_HASH_LIMIT:
        digest = hashlib.sha256()
        try:
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            payload["sha256"] = digest.hexdigest()
        except OSError:
            pass
    return payload


def _optional_file_fingerprint(value: Any) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        return _file_fingerprint(Path(value))
    except (TypeError, ValueError):
        return None


def _git_directory_fingerprint(root: Path) -> list[dict[str, Any]] | None:
    """Return a cheap git tree fingerprint when ``root`` is clean and tracked."""

    if not root.exists():
        return []
    try:
        resolved = root.expanduser().resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return None

    try:
        top_result = subprocess.run(
            ["git", "-C", str(resolved), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
            timeout=GIT_FINGERPRINT_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None

    try:
        git_root = Path(top_result.stdout.strip()).resolve(strict=False)
        relative = resolved.relative_to(git_root).as_posix()
    except (OSError, RuntimeError, ValueError):
        return None

    try:
        status_result = subprocess.run(
            [
                "git",
                "-C",
                str(git_root),
                "status",
                "--porcelain",
                "--untracked-files=all",
                "--",
                relative,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=GIT_FINGERPRINT_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None

    if status_result.stdout.strip():
        return None

    tree_spec = f"HEAD:{relative}"
    try:
        tree_result = subprocess.run(
            ["git", "-C", str(git_root), "rev-parse", tree_spec],
            check=True,
            capture_output=True,
            text=True,
            timeout=GIT_FINGERPRINT_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None

    tree_hash = tree_result.stdout.strip()
    if not tree_hash:
        return None
    return [
        {
            "strategy": "git-tree",
            "path": resolved.as_posix(),
            "git_root": git_root.as_posix(),
            "rel": relative,
            "tree": tree_hash,
        }
    ]


def _directory_fingerprint(root: Path) -> list[dict[str, Any]]:
    git_fingerprint = _git_directory_fingerprint(root)
    if git_fingerprint is not None:
        return git_fingerprint

    if not root.exists():
        return []
    ignored_parts = {".venv", "__pycache__", ".pytest_cache", "build", "dist"}
    fingerprints: list[dict[str, Any]] = []
    for candidate in sorted(root.rglob("*"), key=lambda path: path.as_posix()):
        if not candidate.is_file():
            continue
        if any(part in ignored_parts for part in candidate.relative_to(root).parts):
            continue
        file_fp = _file_fingerprint(candidate)
        if file_fp is None:
            continue
        file_fp["rel"] = candidate.relative_to(root).as_posix()
        fingerprints.append(file_fp)
    return fingerprints


def _build_cache_path(wenv_abs: Path) -> Path:
    return wenv_abs / "dist" / ".agilab-worker-build-cache.json"


def _load_build_cache(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_build_cache(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _worker_build_cache_payload(
    *,
    env: Any,
    packages: str,
    worker_group: str | None,
    is_cy: bool,
    module_cmd: str,
    core_install_commands: list[str],
) -> dict[str, Any]:
    app_path = Path(env.active_app)
    worker_pyproject_src = _worker_pyproject_source(env)
    return {
        "schema": BUILD_CACHE_SCHEMA,
        "base_worker_cls": str(getattr(env, "base_worker_cls", "")),
        "worker_group": worker_group,
        "packages": packages,
        "is_cython": bool(is_cy),
        "pyvers_worker": str(getattr(env, "pyvers_worker", "")),
        "module_cmd": module_cmd,
        "core_install_commands": core_install_commands,
        "active_app": str(app_path.resolve(strict=False)),
        "app_src": _directory_fingerprint(app_path / "src"),
        "worker_pyproject": _file_fingerprint(worker_pyproject_src),
        "manager_pyproject": _optional_file_fingerprint(getattr(env, "manager_pyproject", None)),
        "uvproject": _optional_file_fingerprint(getattr(env, "uvproject", None)),
    }


def _worker_build_outputs_exist(wenv_abs: Path, *, is_cy: bool) -> bool:
    if not _sorted_glob_matches(wenv_abs / "dist", "*.egg"):
        return False
    if is_cy and _latest_glob_match(wenv_abs / "dist", "*_cy.*") is None:
        return False
    return True


def _worker_build_cache_hit(
    *,
    env: Any,
    packages: str,
    worker_group: str | None,
    is_cy: bool,
    module_cmd: str,
    core_install_commands: list[str],
) -> bool:
    if not _build_cache_enabled(env):
        return False
    payload = _worker_build_cache_payload(
        env=env,
        packages=packages,
        worker_group=worker_group,
        is_cy=is_cy,
        module_cmd=module_cmd,
        core_install_commands=core_install_commands,
    )
    cached = _load_build_cache(_build_cache_path(env.wenv_abs))
    return cached == payload and _worker_build_outputs_exist(env.wenv_abs, is_cy=is_cy)


def _record_worker_build_cache(
    *,
    env: Any,
    packages: str,
    worker_group: str | None,
    is_cy: bool,
    module_cmd: str,
    core_install_commands: list[str],
) -> None:
    if not _build_cache_enabled(env) or not _worker_build_outputs_exist(env.wenv_abs, is_cy=is_cy):
        return
    payload = _worker_build_cache_payload(
        env=env,
        packages=packages,
        worker_group=worker_group,
        is_cy=is_cy,
        module_cmd=module_cmd,
        core_install_commands=core_install_commands,
    )
    _write_build_cache(_build_cache_path(env.wenv_abs), payload)


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
    offline_flag = _uv_offline_flag(env)
    core_packages = (
        ("agi-env", getattr(env, "agi_env", None)),
        ("agi-node", getattr(env, "agi_node", None)),
    )
    if getattr(env, "is_source_env", False):
        editable_specs = [
            f"-e '{source_path}'"
            for _package_name, source_path in core_packages
            if source_path
        ]
        if editable_specs:
            commands.append(
                f"{uv} {offline_flag}--project {app_path_arg} pip install --upgrade --no-deps "
                + " ".join(editable_specs)
            )
    else:
        commands.append(
            f"{uv} --project {app_path_arg} pip install "
            + " ".join(package_name for package_name, _source_path in core_packages)
        )
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
        f"{module_cmd} --app-path {app_path_arg} {quiet_flag}build_ext -b {wenv_arg}"
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
    core_install_commands = _core_install_commands(env=env, uv=uv, app_path_arg=app_path_arg)

    _stage_worker_build_project(
        agi_cls,
        env,
        ensure_optional_extras_fn=ensure_optional_extras_fn,
        stage_uv_sources_fn=stage_uv_sources_fn,
        validate_worker_uv_sources_fn=validate_worker_uv_sources_fn,
    )

    cache_hit = _worker_build_cache_hit(
        env=env,
        packages=packages,
        worker_group=worker_group,
        is_cy=bool(is_cy),
        module_cmd=module_cmd,
        core_install_commands=core_install_commands,
    )
    if cache_hit:
        log.info(
            "Worker build cache hit for %s; reusing existing build artifacts.",
            getattr(env, "target_worker", "worker"),
        )
        _upload_built_eggs(agi_cls._dask_client, wenv_abs / "dist")
        if is_cy:
            _copy_cython_worker_lib(
                wenv_abs=wenv_abs,
                pyvers_worker=env.pyvers_worker,
                build_output="",
                failure_message="cached build_ext output is missing",
                log=log,
            )
        return

    for cmd in core_install_commands:
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

    _record_worker_build_cache(
        env=env,
        packages=packages,
        worker_group=worker_group,
        is_cy=bool(is_cy),
        module_cmd=module_cmd,
        core_install_commands=core_install_commands,
    )


async def build_lib_remote(agi_cls: Any, *, log: Any = logger) -> None:
    if (agi_cls._dask_client.scheduler.pool.open == 0) and agi_cls.verbose:
        _runners = list(agi_cls._dask_client.scheduler_info()["workers"].keys())
        log.info("warning: no scheduler found but requested mode is dask=1 => switch to dask")
