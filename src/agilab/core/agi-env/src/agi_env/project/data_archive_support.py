"""Dataset archive extraction helpers for ``AgiEnv``."""

from __future__ import annotations

import importlib
import os
import shutil
import tempfile
import traceback
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable, Mapping

import py7zr

from agi_env.shares.share_runtime_support import resolve_share_path

STAMP_WRITE_EXCEPTIONS = (OSError,)
SIZE_PROBE_EXCEPTIONS = (OSError,)

ARCHIVE_MAX_MEMBERS = 10_000
ARCHIVE_MAX_MEMBER_BYTES = 2 * 1024**3
ARCHIVE_MAX_TOTAL_BYTES = 8 * 1024**3
ARCHIVE_MAX_COMPRESSION_RATIO = 200.0
ARCHIVE_MIN_FREE_BYTES = 256 * 1024**2


def _load_py7zr_exceptions_module() -> Any | None:
    """Return ``py7zr.exceptions`` even when the package omits the attribute."""
    try:
        return importlib.import_module("py7zr.exceptions")
    except (AttributeError, ImportError):
        return getattr(py7zr, "exceptions", None)


def _exception_class(container: Any | None, name: str) -> type[BaseException] | None:
    candidate = getattr(container, name, None)
    if isinstance(candidate, type) and issubclass(candidate, BaseException):
        return candidate
    return None


def _plain_class(container: Any | None, name: str) -> type[Any] | None:
    candidate = getattr(container, name, None)
    if isinstance(candidate, type):
        return candidate
    return None


def _restore_py7zr_exception_exports(
    py7zr_module: Any,
    exceptions_module: Any | None,
) -> None:
    for name in (
        "AbsolutePathError",
        "ArchiveError",
        "Bad7zFile",
        "CrcError",
        "DecompressionError",
        "InternalError",
        "PasswordRequired",
        "UnsupportedCompressionMethodError",
    ):
        candidate = _exception_class(exceptions_module, name)
        if candidate is not None and _exception_class(py7zr_module, name) is None:
            setattr(py7zr_module, name, candidate)


def _load_py7zr_implementation_module(
    py7zr_module: Any = py7zr,
    exceptions_module: Any | None = None,
) -> Any | None:
    """Return the implementation module that still owns ``SevenZipFile``."""
    _restore_py7zr_exception_exports(py7zr_module, exceptions_module)
    try:
        return importlib.import_module("py7zr.py7zr")
    except (AttributeError, ImportError):
        return None


def _py7zr_archive_error_classes(
    py7zr_module: Any = py7zr,
    exceptions_module: Any | None = None,
) -> tuple[type[BaseException], ...]:
    """Resolve py7zr archive errors across py7zr package layouts."""
    classes: list[type[BaseException]] = []
    for container in (exceptions_module, getattr(py7zr_module, "exceptions", None), py7zr_module):
        for name in ("ArchiveError", "Bad7zFile"):
            candidate = _exception_class(container, name)
            if candidate is not None and candidate not in classes:
                classes.append(candidate)
    return tuple(classes)


def _py7zr_sevenzip_file_class(
    py7zr_module: Any = py7zr,
    implementation_module: Any | None = None,
) -> type[Any]:
    """Resolve ``SevenZipFile`` across py7zr package layouts."""
    for container in (py7zr_module, implementation_module):
        candidate = _plain_class(container, "SevenZipFile")
        if candidate is not None:
            return candidate
    raise AttributeError("py7zr SevenZipFile class is unavailable")


def ensure_py7zr_package_compatibility(
    py7zr_module: Any = py7zr,
    *,
    implementation_module: Any | None = None,
    exceptions_module: Any | None = None,
) -> Any:
    """Populate py7zr compatibility attributes removed from newer package layouts."""
    implementation_module = (
        PY7ZR_IMPLEMENTATION_MODULE if implementation_module is None else implementation_module
    )
    exceptions_module = PY7ZR_EXCEPTIONS_MODULE if exceptions_module is None else exceptions_module

    _restore_py7zr_exception_exports(py7zr_module, exceptions_module)

    if _plain_class(py7zr_module, "SevenZipFile") is None:
        setattr(
            py7zr_module,
            "SevenZipFile",
            _py7zr_sevenzip_file_class(py7zr_module, implementation_module),
        )

    bad7z_file = (
        _exception_class(py7zr_module, "Bad7zFile")
        or _exception_class(exceptions_module, "Bad7zFile")
    )
    if bad7z_file is not None and _exception_class(py7zr_module, "Bad7zFile") is None:
        setattr(py7zr_module, "Bad7zFile", bad7z_file)

    archive_error = (
        _exception_class(py7zr_module, "ArchiveError")
        or _exception_class(exceptions_module, "ArchiveError")
    )
    if archive_error is not None and _exception_class(py7zr_module, "ArchiveError") is None:
        setattr(py7zr_module, "ArchiveError", archive_error)

    return py7zr_module


PY7ZR_EXCEPTIONS_MODULE = _load_py7zr_exceptions_module()
PY7ZR_IMPLEMENTATION_MODULE = _load_py7zr_implementation_module(py7zr, PY7ZR_EXCEPTIONS_MODULE)
PY7ZR_ARCHIVE_ERROR_CLASSES = _py7zr_archive_error_classes(py7zr, PY7ZR_EXCEPTIONS_MODULE)
PY7ZR_BAD7Z_FILE = (
    _exception_class(PY7ZR_EXCEPTIONS_MODULE, "Bad7zFile")
    or _exception_class(py7zr, "Bad7zFile")
)
PY7ZR_SEVENZIP_FILE = _py7zr_sevenzip_file_class(py7zr, PY7ZR_IMPLEMENTATION_MODULE)
ensure_py7zr_package_compatibility()
EXTRACTION_FAILURE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    OSError,
    *PY7ZR_ARCHIVE_ERROR_CLASSES,
)


def _archive_size_mb(archive_path: Path) -> float | None:
    try:
        return archive_path.stat().st_size / 1_000_000
    except SIZE_PROBE_EXCEPTIONS:
        return None


def _archive_member_names(archive: Any) -> list[str] | None:
    for method_name in ("getnames", "namelist"):
        getnames = getattr(archive, method_name, None)
        if callable(getnames):
            return [str(name) for name in getnames()]
    return None


def _archive_member_target(dest: Path, member_name: str) -> Path:
    normalized = member_name.replace("\\", "/")
    member_path = PurePosixPath(normalized)
    return (dest / Path(*member_path.parts)).resolve()


def _validate_archive_members_stay_within_dest(archive: Any, dest: Path) -> None:
    """Reject archive entries that would escape ``dest`` before extraction."""

    member_names = _archive_member_names(archive)
    if member_names is None:
        # Production py7zr exposes getnames(); this compatibility branch keeps
        # lightweight test doubles working while real archives are preflighted.
        return

    resolved_dest = dest.resolve()
    for member_name in member_names:
        posix_member = PurePosixPath(member_name.replace("\\", "/"))
        windows_member = PureWindowsPath(member_name)
        if posix_member.is_absolute() or windows_member.is_absolute() or windows_member.drive:
            raise RuntimeError(f"Unsafe archive member path in '{member_name}'")
        target = _archive_member_target(resolved_dest, member_name)
        if not target.is_relative_to(resolved_dest):
            raise RuntimeError(f"Unsafe archive member path in '{member_name}'")


def validate_archive_members_stay_within_dest(archive: Any, dest: Path) -> None:
    """Public wrapper for archive preflight before ``extractall``."""

    _validate_archive_members_stay_within_dest(archive, dest)


def _archive_member_metadata(archive: Any) -> list[Any]:
    for method_name in ("infolist", "list"):
        list_members = getattr(archive, method_name, None)
        if callable(list_members):
            return list(list_members())
    raise ValueError(
        "Archive extraction refused because member size metadata is unavailable."
    )


def _archive_member_size(member: Any, *names: str) -> int | None:
    for name in names:
        value = getattr(member, name, None)
        if value is None:
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Archive member has invalid {name} metadata.") from exc
        if parsed < 0:
            raise ValueError(f"Archive member has negative {name} metadata.")
        return parsed
    return None


def _archive_member_is_directory(member: Any) -> bool:
    is_dir = getattr(member, "is_dir", None)
    if callable(is_dir):
        return bool(is_dir())
    return bool(getattr(member, "is_directory", False))


def _archive_member_display_name(member: Any) -> str:
    return str(getattr(member, "filename", getattr(member, "name", "<unknown>")))


def _existing_disk_usage_path(dest: Path) -> Path:
    probe = dest.resolve(strict=False)
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    return probe


def validate_archive_extraction_quota(
    archive: Any,
    dest: Path,
    *,
    archive_size_bytes: int | None = None,
    max_members: int = ARCHIVE_MAX_MEMBERS,
    max_member_bytes: int = ARCHIVE_MAX_MEMBER_BYTES,
    max_total_bytes: int = ARCHIVE_MAX_TOTAL_BYTES,
    max_compression_ratio: float = ARCHIVE_MAX_COMPRESSION_RATIO,
    min_free_bytes: int = ARCHIVE_MIN_FREE_BYTES,
) -> None:
    """Reject archives that exceed bounded extraction and disk quotas."""

    members = _archive_member_metadata(archive)
    if len(members) > max_members:
        raise ValueError(
            f"Archive contains {len(members)} members; limit is {max_members}."
        )

    total_uncompressed = 0
    total_compressed = 0
    has_compressed_metadata = False
    for member in members:
        if _archive_member_is_directory(member):
            continue
        member_name = _archive_member_display_name(member)
        uncompressed = _archive_member_size(member, "file_size", "uncompressed")
        if uncompressed is None:
            raise ValueError(
                f"Archive member {member_name!r} has no uncompressed-size metadata."
            )
        if uncompressed > max_member_bytes:
            raise ValueError(
                f"Archive member {member_name!r} expands to {uncompressed} bytes; "
                f"per-member limit is {max_member_bytes}."
            )
        total_uncompressed += uncompressed
        if total_uncompressed > max_total_bytes:
            raise ValueError(
                f"Archive expands to more than {max_total_bytes} bytes in total."
            )

        compressed = _archive_member_size(member, "compress_size", "compressed")
        if compressed is not None:
            has_compressed_metadata = True
            total_compressed += compressed
            if hasattr(member, "compress_size") and uncompressed:
                if compressed == 0 or uncompressed / compressed > max_compression_ratio:
                    raise ValueError(
                        f"Archive member {member_name!r} exceeds the allowed "
                        f"compression ratio of {max_compression_ratio:g}:1."
                    )

    compressed_basis = archive_size_bytes
    if compressed_basis is None and has_compressed_metadata:
        compressed_basis = total_compressed
    if total_uncompressed:
        if compressed_basis is None:
            raise ValueError(
                "Archive extraction refused because compressed-size metadata is unavailable."
            )
        if compressed_basis <= 0 or total_uncompressed / compressed_basis > max_compression_ratio:
            raise ValueError(
                "Archive exceeds the allowed overall compression ratio of "
                f"{max_compression_ratio:g}:1."
            )

    free_bytes = shutil.disk_usage(_existing_disk_usage_path(dest)).free
    required_bytes = total_uncompressed + min_free_bytes
    if required_bytes > free_bytes:
        raise ValueError(
            "Archive extraction requires "
            f"{required_bytes} free bytes including reserve; only {free_bytes} are available."
        )


def _write_dataset_stamp(archive_path: Path, stamp_path: Path) -> None:
    try:
        stamp_path.write_text(str(archive_path), encoding="utf-8")
        archive_mtime = archive_path.stat().st_mtime
        os.utime(stamp_path, (archive_mtime, archive_mtime))
    except STAMP_WRITE_EXCEPTIONS:
        pass


def unzip_data(
    archive_path: Path,
    *,
    extract_to: Path | str | None,
    app_data_rel: str | Path,
    agi_share_path_abs: Path,
    user: str,
    home_abs: Path,
    verbose: int,
    logger: Any,
    force_extract: bool = False,
    ensure_dir_fn: Callable[[str | Path], Path],
    sevenzip_file_cls: type[Any],
    rmtree_fn: Callable[..., Any],
    environ: Mapping[str, str] = os.environ,
) -> None:
    """Extract a `.7z` dataset archive into the app share directory."""

    archive_path = Path(archive_path)
    if not archive_path.exists():
        logger.warning(f"Warning: Archive '{archive_path}' does not exist. Skipping extraction.")
        return

    extract_rel = Path(extract_to) if extract_to is not None else Path(app_data_rel)
    share_root = Path(agi_share_path_abs).expanduser().resolve(strict=False)

    def _prepare_parent(path: Path) -> Path | None:
        parent = path.parent
        try:
            ensure_dir_fn(parent)
        except OSError as exc:
            logger.warning("Unable to prepare dataset parent '%s': %s.", parent, exc)
            return None
        return parent

    dest = resolve_share_path(extract_rel, share_root)
    dest_parent = _prepare_parent(dest)
    if dest_parent is None:
        logger.warning(
            "Skipping dataset extraction; unable to prepare dataset parent '%s'.",
            dest.parent,
        )
        return

    def _resolve_dataset_target() -> Path:
        target = resolve_share_path(dest / "dataset", share_root)
        if target == share_root:
            raise ValueError("Dataset reset target must not be the physical share root")
        return target

    dataset = _resolve_dataset_target()
    env_force = environ.get("AGILAB_FORCE_DATA_REFRESH", "0") not in {"0", "", "false", "False"}
    force_refresh = force_extract or env_force

    desired_user = user
    current_owner = Path(home_abs).name
    if desired_user and desired_user != current_owner and not force_refresh:
        try:
            ensure_dir_fn(dest)
        except OSError as exc:
            logger.warning("Unable to ensure target directory '%s': %s. Skipping extraction.", dest, exc)
            return
        if verbose > 0:
            logger.info(
                f"Skipping dataset extraction for '{dest}' (desired owner '{desired_user}' "
                f"differs from local owner '{current_owner}')."
            )
        return

    try:
        ensure_dir_fn(dest)
    except OSError as exc:
        logger.warning("Unable to ensure target directory '%s': %s. Skipping extraction.", dest, exc)
        return

    if dataset.exists() and not force_refresh:
        if verbose > 0:
            logger.info(
                f"Dataset already present at '{dataset}'. "
                "Skipping extraction (set AGILAB_FORCE_DATA_REFRESH=1 to rebuild)."
            )
        stamp_path = dataset / ".agilab_dataset_stamp"
        if not stamp_path.exists():
            _write_dataset_stamp(archive_path, stamp_path)
        return

    def _ignore_missing(
        _func: Callable[..., Any],
        _path: str,
        excinfo: tuple[type[BaseException], BaseException, Any],
    ) -> None:
        exc = excinfo[1]
        if isinstance(exc, FileNotFoundError):
            return
        raise exc

    def _cleanup_tree(path: Path, *, purpose: str) -> None:
        if not path.exists():
            return
        try:
            rmtree_fn(path, onerror=_ignore_missing)
        except FileNotFoundError:
            return
        except OSError as exc:
            logger.warning("Unable to remove %s '%s': %s.", purpose, path, exc)

    created_staging_root: Path | None = None
    try:
        created_staging_root = Path(
            tempfile.mkdtemp(prefix=".agilab-dataset-refresh-", dir=dest)
        )
        staging_root = resolve_share_path(created_staging_root, dest)
    except (OSError, ValueError) as exc:
        logger.warning(
            "Unable to create a staging directory below '%s': %s. Skipping extraction.",
            dest,
            exc,
        )
        return

    try:
        backup = resolve_share_path(
            staging_root.with_name(f"{staging_root.name}.rollback"),
            dest,
        )
    except ValueError:
        _cleanup_tree(staging_root, purpose="dataset refresh staging directory")
        raise

    try:
        with sevenzip_file_cls(archive_path, mode="r") as archive:
            size_mb = _archive_size_mb(archive_path)
            size_hint = f" (~{size_mb:.1f} MB)" if size_mb else ""
            if verbose > 1:
                logger.info(
                    f"Starting dataset extraction: {archive_path}{size_hint} -> {staging_root} "
                    "(this can take a moment; please wait)."
                )
            _validate_archive_members_stay_within_dest(archive, staging_root)
            validate_archive_extraction_quota(
                archive,
                staging_root,
                archive_size_bytes=archive_path.stat().st_size,
            )
            archive.extractall(path=staging_root)

        try:
            staged_dataset = resolve_share_path(staging_root / "dataset", staging_root)
        except ValueError as exc:
            raise RuntimeError("Extracted dataset escaped its staging directory") from exc
        if not staged_dataset.is_dir():
            raise RuntimeError(
                f"Archive '{archive_path}' did not produce a dataset directory"
            )

        _write_dataset_stamp(
            archive_path,
            staged_dataset / ".agilab_dataset_stamp",
        )

        dataset = _resolve_dataset_target()
        had_live_dataset = dataset.exists()
        if had_live_dataset:
            dataset.replace(backup)
        try:
            staged_dataset.replace(dataset)
        except BaseException:
            if had_live_dataset:
                try:
                    backup.replace(dataset)
                except OSError as rollback_exc:
                    raise RuntimeError(
                        f"Dataset refresh failed and rollback could not restore '{dataset}'"
                    ) from rollback_exc
            raise

        if had_live_dataset:
            _cleanup_tree(backup, purpose="dataset refresh rollback directory")
        if verbose > 1:
            logger.info(f"Extracted '{archive_path}' to '{dest}'.")
    except EXTRACTION_FAILURE_EXCEPTIONS as exc:
        # Extraction is an operational boundary: surface archive/read/write failures
        # to callers through one stable RuntimeError contract.
        logger.error(f"Failed to extract '{archive_path}': {exc}")
        traceback.print_exc()
        raise RuntimeError(f"Extraction failed for '{archive_path}'") from exc
    finally:
        _cleanup_tree(staging_root, purpose="dataset refresh staging directory")
