"""Pure shared-path and runtime flag helpers for AGILAB."""

from __future__ import annotations

import sys
import sysconfig
import re
from pathlib import Path, PurePosixPath, PureWindowsPath

FREE_THREADING_PROBE_EXCEPTIONS = (AttributeError, OSError, RuntimeError)
FREE_THREADING_CONFIG_EXCEPTIONS = (AttributeError, OSError, TypeError, ValueError)
_NON_DEDICATED_WORKER_ROOT_NAMES = frozenset(
    {
        "applications",
        "bin",
        "boot",
        "dev",
        "etc",
        "home",
        "lib",
        "lib32",
        "lib64",
        "library",
        "mnt",
        "nix",
        "opt",
        "private",
        "proc",
        "root",
        "run",
        "sbin",
        "snap",
        "srv",
        "sys",
        "system",
        "tmp",
        "usr",
        "users",
        "var",
        "volumes",
    }
)


def share_target_name(target: str | None, app: str | None, *, default: str = "app") -> str:
    """Return the logical app name for share paths."""

    name = target or app or default
    for suffix in ("_project", "_worker"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def resolve_share_path(path: str | Path | None, share_root: Path) -> Path:
    """Resolve ``path`` relative to ``share_root`` with share-root confinement."""

    if path in (None, "", "."):
        return share_root.resolve(strict=False)

    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        resolved = candidate.resolve(strict=False)
    else:
        resolved = (share_root / candidate).resolve(strict=False)

    share_root_resolved = share_root.resolve(strict=False)
    if not _path_is_within_share_root(resolved, share_root_resolved):
        raise ValueError(
            f"Path must stay inside the configured share root {share_root_resolved!r}, got {path!r}."
        )
    return resolved


def _path_is_within_share_root(path: Path, share_root: Path) -> bool:
    """Return whether ``path`` is confined by ``share_root`` on this filesystem.

    Component equality is authoritative.  When path spellings differ, accept
    the alias only if an existing ancestor has the same filesystem identity as
    the configured root.  This admits case aliases on case-insensitive volumes
    without treating case-distinct siblings as aliases on case-sensitive ones.
    """

    share_root_parts = share_root.parts
    if path.parts[: len(share_root_parts)] == share_root_parts:
        return True

    try:
        share_root_exists = share_root.exists()
    except OSError:
        share_root_exists = False
    if not share_root_exists:
        return False

    candidate = path
    while True:
        try:
            if candidate.samefile(share_root):
                return True
        except (OSError, ValueError):
            pass
        parent = candidate.parent
        if parent == candidate:
            return False
        candidate = parent


def resolve_share_input_path(
    path: str | Path | None,
    workflow_root: Path,
    physical_share_root: Path,
) -> Path:
    """Resolve an input path with a confined physical-share fallback.

    Workflow-local data wins when it exists.  Otherwise, a pre-existing input
    at the same relative path under the physical share may be reused.  Absolute
    inputs below the physical share are also accepted when they exist, while a
    path outside both roots remains rejected.
    """

    try:
        resolved = resolve_share_path(path, workflow_root)
    except ValueError:
        fallback = resolve_share_path(path, physical_share_root)
        if fallback.exists():
            return fallback
        raise
    if resolved.exists():
        return resolved
    fallback = resolve_share_path(path, physical_share_root)
    if fallback != resolved and fallback.exists():
        return fallback
    return resolved


def validate_worker_share_root(value: str | Path | None) -> str:
    """Validate a dedicated worker-side share root without rebasing it locally."""

    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError("Workers Data Path must name a dedicated directory")
    if "\x00" in cleaned:
        raise ValueError("Workers Data Path must not contain NUL bytes")

    normalized = cleaned.replace("\\", "/")
    posix_path = PurePosixPath(normalized)
    if posix_path.is_absolute() and posix_path.parent == posix_path:
        raise ValueError("Workers Data Path must not be the filesystem root")
    if not posix_path.is_absolute() and posix_path in {
        PurePosixPath("."),
        PurePosixPath("~"),
    }:
        raise ValueError("Workers Data Path must name a dedicated directory, not the worker home")
    posix_parts = tuple(
        part for part in posix_path.parts if part not in {posix_path.anchor, "."}
    )
    folded_posix_parts = tuple(part.casefold() for part in posix_parts)
    if posix_path.is_absolute() and (
        (
            len(folded_posix_parts) == 1
            and folded_posix_parts[0] in _NON_DEDICATED_WORKER_ROOT_NAMES
        )
        or (
            len(folded_posix_parts) == 2
            and folded_posix_parts[0] in {"home", "users"}
        )
        or folded_posix_parts == ("var", "root")
    ):
        raise ValueError(
            "Workers Data Path must name a dedicated directory, not a worker home or system root"
        )
    if ".." in posix_path.parts:
        raise ValueError("Workers Data Path must not contain '..' traversal")

    windows_path = PureWindowsPath(cleaned)
    if windows_path.drive:
        if not windows_path.is_absolute():
            raise ValueError("Workers Data Path must not be drive-relative")
        raise ValueError(
            "Workers Data Path must use a POSIX worker path, not a Windows drive or UNC path"
        )
    return cleaned


def validate_local_share_root(
    value: str | Path,
    *,
    home_roots: tuple[str | Path, ...] = (),
) -> Path:
    """Return a dedicated scheduler-side share root or raise ``ValueError``.

    Unlike a worker mount setting, this path uses the scheduler's native path
    flavour. Existing symlink/case aliases are resolved before exact filesystem,
    home, and operating-system roots are rejected.
    """

    cleaned = str(value or "").strip()
    if not cleaned or "\x00" in cleaned:
        raise ValueError("AGI_CLUSTER_SHARE must name a dedicated local directory")

    raw_candidate = Path(cleaned).expanduser()
    candidate = raw_candidate.resolve(strict=False)
    anchor = Path(candidate.anchor)
    if candidate == anchor:
        raise ValueError("AGI_CLUSTER_SHARE must not be the scheduler filesystem root")

    def _relative_parts(path: Path) -> tuple[str, ...]:
        return tuple(
            part.casefold()
            for part in path.parts
            if part not in {path.anchor, "."}
        )

    def _is_ambient_root(parts: tuple[str, ...]) -> bool:
        # macOS resolves /etc, /var, /tmp, and /home through /private or the
        # sealed Data volume. Strip those implementation prefixes before
        # applying the same native-root policy.
        if parts[:1] == ("private",):
            return _is_ambient_root(parts[1:])
        if parts[:3] == ("system", "volumes", "data"):
            return _is_ambient_root(parts[3:])
        return (
            (len(parts) == 1 and parts[0] in _NON_DEDICATED_WORKER_ROOT_NAMES)
            or (len(parts) == 2 and parts[0] in {"home", "users"})
            or parts == ("var", "root")
        )

    if _is_ambient_root(_relative_parts(raw_candidate)) or _is_ambient_root(
        _relative_parts(candidate)
    ):
        raise ValueError(
            "AGI_CLUSTER_SHARE must name a dedicated directory, not a scheduler home or system root"
        )

    for raw_home in home_roots:
        if not raw_home:
            continue
        home = Path(raw_home).expanduser().resolve(strict=False)
        if candidate.parts == home.parts:
            raise ValueError("AGI_CLUSTER_SHARE must not be the scheduler home directory")
        try:
            if candidate.exists() and home.exists() and candidate.samefile(home):
                raise ValueError("AGI_CLUSTER_SHARE must not be the scheduler home directory")
        except OSError:
            continue

    return candidate


def mode_to_str(mode: int, *, hw_rapids_capable: bool = False) -> str:
    """Encode a bitmask ``mode`` into readable ``pcdr`` flag form."""

    chars = ["p", "c", "d", "r"]
    reversed_chars = reversed(list(enumerate(chars)))
    # Bitwise OR so a rapids-capable host does not corrupt the label when bit 8
    # is already set on ``mode`` (arithmetic ``+ 8`` would carry into higher bits).
    normalized_mode = mode | 8 if hw_rapids_capable else mode
    return "".join(
        "_" if (normalized_mode & (1 << i)) == 0 else v for i, v in reversed_chars
    )


def mode_to_int(mode: str) -> int:
    """Convert iterable mode flags (``p``, ``c``, ``d``, ``r``) into the bitmask int."""

    mode_int = 0
    set_rm = set(mode)
    for i, value in enumerate(["p", "c", "d", "r"]):
        if value in set_rm:
            mode_int += 1 << i
    return mode_int


def is_valid_ip(ip: str) -> bool:
    """Return ``True`` when ``ip`` is a syntactically valid IPv4 address."""

    pattern = re.compile(r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$")
    if pattern.match(ip):
        parts = ip.split(".")
        return all(0 <= int(part) <= 255 for part in parts)
    return False


def python_supports_free_threading() -> bool:
    """Return ``True`` when the current interpreter can run with ``PYTHON_GIL=0``."""

    checker = getattr(sys, "_is_gil_enabled", None)
    if callable(checker):
        try:
            return not bool(checker())
        except FREE_THREADING_PROBE_EXCEPTIONS:
            pass

    try:
        return bool(sysconfig.get_config_var("Py_GIL_DISABLED"))
    except FREE_THREADING_CONFIG_EXCEPTIONS:
        return False
