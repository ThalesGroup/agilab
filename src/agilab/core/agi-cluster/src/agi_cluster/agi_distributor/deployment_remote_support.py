import logging
import uuid
from pathlib import Path, PurePosixPath
from shlex import quote
from tempfile import gettempdir
from typing import Any, Callable, Union

from agi_cluster.agi_distributor import deployment_dask_support
from agi_env import AgiEnv


logger = logging.getLogger(__name__)

_REMOTE_RAPIDS_CHECK_EXCEPTIONS = (ConnectionError, OSError, RuntimeError)
_REMOTE_PLATFORM_PROBE_EXCEPTIONS = (OSError, RuntimeError, ValueError)
_LEGACY_INTEL_MACOS_DEPENDENCY_SPECS = ("numba==0.62.1", "pyarrow==17.0.0")


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


async def _legacy_intel_macos_dependency_specs(agi_cls: Any, ip: str, *, log: Any = logger) -> tuple[str, ...]:
    try:
        probe = await agi_cls.exec_ssh(ip, _remote_platform_probe_command())
    except ConnectionError:
        raise
    except _REMOTE_PLATFORM_PROBE_EXCEPTIONS as exc:
        log.warning("Could not probe remote worker platform on %s; skipping legacy macOS pins: %s", ip, exc)
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


def _latest_artifact_match(root: Path, pattern: str) -> Path | None:
    matches = sorted(root.glob(pattern), key=lambda candidate: candidate.name)
    if not matches:
        return None
    return max(matches, key=lambda candidate: (candidate.stat().st_mtime_ns, candidate.name))


async def deploy_remote_worker(
    agi_cls: Any,
    ip: str,
    env: Any,
    wenv_rel: Path,
    option: str,
    *,
    worker_site_packages_dir_fn: Callable[..., Path | PurePosixPath],
    staged_uv_sources_pth_content_fn: Callable[..., str],
    set_env_var_fn: Callable[..., Any] = AgiEnv.set_env_var,
    log: Any = logger,
) -> None:
    """Install packages and bootstrap a remote worker environment."""

    del option

    wenv_rel = env.wenv_rel
    dist_abs = env.dist_abs
    pyvers = env.pyvers_worker
    cmd_prefix = env.envars.get(f"{ip}_CMD_PREFIX", "")
    uv = cmd_prefix + env.uv_worker

    if agi_cls._workers_data_path:
        await agi_cls.exec_ssh(ip, "mkdir -p .agilab")
        await agi_cls.exec_ssh(
            ip,
            f"echo 'AGI_CLUSTER_SHARE=\"{Path(agi_cls._workers_data_path).expanduser().as_posix()}\"' > .agilab/.env",
        )

    if env.is_source_env:
        egg_file = _latest_artifact_match(dist_abs, f"{env.target_worker}*.egg")
        if egg_file is None:
            egg_file = _latest_artifact_match(dist_abs, f"{env.app}*.egg")
        if egg_file is None:
            log.error(f"searching for {dist_abs / env.target_worker}*.egg or {dist_abs / env.app}*.egg")
            raise FileNotFoundError(f"no existing egg file in {dist_abs / env.target_worker}* or {dist_abs / env.app}*")

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
        await agi_cls.exec_ssh(ip, f"mkdir -p '{dist_remote}'")
        await agi_cls.send_files(env, ip, [egg_file], wenv_rel)
        await agi_cls.send_files(env, ip, [node_whl, env_whl], dist_remote)
    else:
        egg_file = _latest_artifact_match(dist_abs, f"{env.target_worker}*.egg")
        if egg_file is None:
            egg_file = _latest_artifact_match(dist_abs, f"{env.app}*.egg")
        if egg_file is None:
            log.error(f"searching for {dist_abs / env.target_worker}*.egg or {dist_abs / env.app}*.egg")
            raise FileNotFoundError(f"no existing egg file in {dist_abs / env.target_worker}* or {dist_abs / env.app}*")

        await agi_cls.send_files(env, ip, [egg_file], wenv_rel)
        env_whl = None
        node_whl = None

    hw_rapids_capable = False
    if agi_cls._rapids_enabled:
        try:
            result = await agi_cls.exec_ssh(ip, "nvidia-smi")
        except _REMOTE_RAPIDS_CHECK_EXCEPTIONS:
            log.error(f"rapids is requested but not supported by node [{ip}]")
            raise

        hw_rapids_capable = (result != "") and agi_cls._rapids_enabled
        env.hw_rapids_capable = hw_rapids_capable
        if hw_rapids_capable:
            set_env_var_fn(ip, "hw_rapids_capable")
        log.info(f"Rapids-capable GPU[{ip}]: {hw_rapids_capable}")

    cli = env.wenv_rel.parent / "cli.py"
    cmd = f"{uv} run -p {pyvers} python  {cli.as_posix()} unzip {wenv_rel.as_posix()}"
    await agi_cls.exec_ssh(ip, cmd)

    cmd = f"{uv} --project {wenv_rel.as_posix()} run -p {pyvers} python -m ensurepip"
    await agi_cls.exec_ssh(ip, cmd)

    compatibility_specs = await _legacy_intel_macos_dependency_specs(agi_cls, ip, log=log)
    if compatibility_specs:
        quoted_specs = " ".join(quote(spec) for spec in compatibility_specs)
        cmd = f"{uv} --project {wenv_rel.as_posix()} add -p {pyvers} {quoted_specs}"
        await agi_cls.exec_ssh(ip, cmd)

    if env.is_source_env:
        if env_whl is None or node_whl is None:
            raise RuntimeError("source environment remote deployment requires local agi-env and agi-node wheels")
        env_pck: Union[str, Path] = wenv_rel / "dist" / env_whl.name
        node_pck: Union[str, Path] = wenv_rel / "dist" / node_whl.name
    else:
        env_pck = "agi-env"
        node_pck = "agi-node"

    def _pkg_ref(pkg: Union[str, Path]) -> str:
        return pkg.as_posix() if isinstance(pkg, Path) else str(pkg)

    cmd = f"{uv} --project {wenv_rel.as_posix()} add -p {pyvers} --upgrade {_pkg_ref(env_pck)}"
    await agi_cls.exec_ssh(ip, cmd)

    cmd = f"{uv} --project {wenv_rel.as_posix()} add -p {pyvers} --upgrade {_pkg_ref(node_pck)}"
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
    pth_content = staged_uv_sources_pth_content_fn(remote_site_packages, remote_uv_sources)
    tmp_pth = Path(gettempdir()) / f"agilab_uv_sources_{uuid.uuid4().hex}.pth"
    tmp_pth.write_text(pth_content, encoding="utf-8")
    try:
        await agi_cls.exec_ssh(ip, f"mkdir -p '{remote_site_packages.as_posix()}'")
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

    cmd = f"{uv} --project {wenv_rel.as_posix()}  run --no-sync -p {pyvers} python {cli.as_posix()} unzip {wenv_rel.as_posix()}"
    await agi_cls.exec_ssh(ip, cmd)

    cmd = (
        f"{uv} --project {wenv_rel.as_posix()} run --no-sync -p {pyvers} python -m "
        f"{env.post_install_rel} {wenv_rel.stem}"
    )
    await agi_cls.exec_ssh(ip, cmd)

    if env.verbose > 1:
        cmd = (
            f"{uv} --project '{wenv_rel.as_posix()}' run --no-sync -p {pyvers} python -m "
            f"agi_node.agi_dispatcher.build  --app-path  '{wenv_rel.as_posix()}' build_ext -b '{wenv_rel.as_posix()}'"
        )
    else:
        cmd = (
            f"{uv} --project '{wenv_rel.as_posix()}' run --no-sync -p {pyvers} python -m "
            f"agi_node.agi_dispatcher.build --app-path '{wenv_rel.as_posix()}' -q build_ext -b '{wenv_rel.as_posix()}'"
        )
    await agi_cls.exec_ssh(ip, cmd)
