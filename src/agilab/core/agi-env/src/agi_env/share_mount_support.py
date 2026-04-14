"""Cluster share settings and mount-selection helpers for ``AgiEnv``."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Mapping


def _parse_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", ""}:
            return False
    return None


def _read_cluster_setting(path: Path) -> bool | None:
    """Read ``[cluster].cluster_enabled`` from a TOML settings file."""
    try:
        if not path.is_file() or path.stat().st_size <= 0:
            return None
        import tomllib

        with path.open("rb") as handle:
            doc = tomllib.load(handle)
        cluster_section = doc.get("cluster")
        if isinstance(cluster_section, dict) and "cluster_enabled" in cluster_section:
            return _parse_bool(cluster_section.get("cluster_enabled"))
        return None
    except Exception:
        return None


def cluster_enabled_from_settings(
    *,
    is_worker_env: bool,
    resolve_workspace_settings_fn: Callable[[], Path | None],
    find_source_settings_fn: Callable[[], Path | None],
    envars: Mapping[str, object],
    environ: Mapping[str, str] = os.environ,
) -> bool:
    """Resolve whether cluster mode is enabled for the active app."""

    if is_worker_env:
        return True

    parsed: bool | None = None
    try:
        settings_candidates = [
            resolve_workspace_settings_fn(),
            find_source_settings_fn(),
        ]
        for settings_path in settings_candidates:
            if settings_path is None:
                continue
            parsed = _read_cluster_setting(settings_path)
            if parsed is not None:
                break
    except Exception:
        parsed = None

    if parsed is not None:
        return parsed

    parsed = _parse_bool(envars.get("AGI_CLUSTER_ENABLED"))
    if parsed is None:
        parsed = _parse_bool(environ.get("AGI_CLUSTER_ENABLED"))
    return bool(parsed) if parsed is not None else False


def _abs_path(path_str: str, *, home_path: Path) -> str:
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = home_path / path
    return os.path.normpath(os.path.abspath(str(path)))


def _is_usable_dir(path: str) -> bool:
    if not os.path.isdir(path):
        return False
    try:
        os.listdir(path)
        testfile = os.path.join(path, ".agi_mount_test")
        with open(testfile, "w") as handle:
            handle.write("ok")
        os.remove(testfile)
        return True
    except Exception:
        return False


def _same_storage(left: str, right: str) -> bool:
    try:
        left_stat = os.stat(os.path.realpath(left))
        right_stat = os.stat(os.path.realpath(right))
        return (left_stat.st_dev, left_stat.st_ino) == (right_stat.st_dev, right_stat.st_ino)
    except FileNotFoundError:
        return False


def _fstab_bind_source_for_target(target: str) -> str | None:
    try:
        with open("/etc/fstab", "r") as handle:
            for raw in handle:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) < 4:
                    continue
                src, tgt, _fstype, opts = parts[:4]
                if os.path.normpath(tgt) == target and "bind" in opts.split(","):
                    return os.path.normpath(src)
    except FileNotFoundError:
        pass
    return None


def is_mounted(path: str, *, home_path: Path) -> bool:
    """Return whether ``path`` is usable as a mounted share location."""

    if not _is_usable_dir(path):
        return False

    try:
        with open("/proc/self/mountinfo", "r") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) > 4 and os.path.normpath(parts[4]) == path:
                    return True
    except FileNotFoundError:
        return True

    bind_src = _fstab_bind_source_for_target(path)
    if bind_src:
        bind_src_abs = _abs_path(bind_src, home_path=home_path) if not os.path.isabs(bind_src) else bind_src
        return _same_storage(path, bind_src_abs)
    return True


def resolve_share_path(
    *,
    cluster_share: str,
    local_share: str,
    cluster_enabled: bool,
    env_path: Path,
    home_path: Path,
) -> str:
    """Choose the active AGILAB share path or raise with a fail-fast message."""

    cluster_candidate = _abs_path(cluster_share, home_path=home_path)
    local_candidate = _abs_path(local_share, home_path=home_path)

    if cluster_enabled and os.path.normpath(cluster_candidate) == os.path.normpath(local_candidate):
        raise RuntimeError(
            "Cluster mode requires AGI_CLUSTER_SHARE to be distinct from AGI_LOCAL_SHARE. "
            f"Both resolve to {cluster_candidate!r}; env={env_path}"
        )

    mounted = is_mounted(cluster_candidate, home_path=home_path)
    if mounted and cluster_enabled:
        return cluster_share

    if cluster_enabled and not mounted:
        raise RuntimeError(
            "Cluster mode requires AGI_CLUSTER_SHARE to be mounted and writable. "
            f"Configured AGI_CLUSTER_SHARE={cluster_candidate!r} is not usable; env={env_path}"
        )
    return local_share
