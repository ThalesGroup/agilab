"""Host-level network and link helpers used by ``AgiEnv`` wrappers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


def create_symlink(
    src: Path,
    dest: Path,
    *,
    logger=None,
    os_name: str,
    create_junction_windows_fn: Callable[[Path, Path], bool],
) -> bool:
    """Create a symlink, using a Windows junction fallback for directories."""

    try:
        if dest.exists() or dest.is_symlink():
            if dest.is_symlink() and dest.resolve() == src.resolve():
                if logger:
                    logger.info(f"Symlink already exists and is correct: {dest} -> {src}")
                return True
            if logger:
                logger.warning(f"Warning: Destination already exists and is not a symlink: {dest}")
            if dest.is_dir():
                return False
            dest.unlink()
        dest.symlink_to(src, target_is_directory=src.is_dir())
        if logger:
            logger.info(f"Symlink created: @{dest.name} -> {src}")
        return True
    except OSError as exc:
        if os_name == "nt" and src.is_dir() and create_junction_windows_fn(src, dest):
            return True
        if logger:
            logger.error(f"Failed to create symlink @{dest} -> {src}: {exc}")
        return False


def is_local_ip(
    ip,
    *,
    cache: set,
    net_if_addrs_fn: Callable[[], dict[str, Any]],
    inet_family,
) -> bool:
    """Return whether ``ip`` matches a local interface address."""

    if not ip or ip in cache:
        return True

    for _, addrs in net_if_addrs_fn().items():
        for addr in addrs:
            if addr.family == inet_family and ip == addr.address:
                cache.add(ip)
                return True

    return False


def check_internet_connectivity(
    *,
    logger,
    request_factory,
    urlopen_fn,
    url: str = "https://www.google.com",
    timeout: int = 3,
) -> bool:
    """Check basic outbound connectivity with a HEAD request."""

    logger.info("Checking internet connectivity...")
    try:
        req = request_factory(url, method="HEAD")
        with urlopen_fn(req, timeout=timeout):
            pass
    except OSError:
        logger.error("No internet connection detected. Aborting.")
        return False
    logger.info("Internet connection is OK.")
    return True
