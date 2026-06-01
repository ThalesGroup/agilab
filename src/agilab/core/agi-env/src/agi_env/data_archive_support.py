"""Dataset archive extraction helpers for ``AgiEnv``."""

from __future__ import annotations

import importlib
import os
import traceback
from pathlib import Path
from typing import Any, Callable

import py7zr

STAMP_WRITE_EXCEPTIONS = (OSError,)
SIZE_PROBE_EXCEPTIONS = (OSError,)


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
EXTRACTION_FAILURE_EXCEPTIONS = (OSError, *PY7ZR_ARCHIVE_ERROR_CLASSES)


def _archive_size_mb(archive_path: Path) -> float | None:
    try:
        return archive_path.stat().st_size / 1_000_000
    except SIZE_PROBE_EXCEPTIONS:
        return None


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
    environ: dict[str, str] = os.environ,  # ty: ignore[invalid-parameter-default]
) -> None:
    """Extract a `.7z` dataset archive into the app share directory."""

    archive_path = Path(archive_path)
    if not archive_path.exists():
        logger.warning(f"Warning: Archive '{archive_path}' does not exist. Skipping extraction.")
        return

    extract_rel = Path(extract_to) if extract_to is not None else Path(app_data_rel)

    def _resolve_destination(base: Path, candidate: Path) -> Path:
        return candidate if candidate.is_absolute() else (base / candidate)

    def _prepare_parent(path: Path) -> Path | None:
        parent = path.parent
        try:
            ensure_dir_fn(parent)
        except OSError as exc:
            logger.warning("Unable to prepare dataset parent '%s': %s.", parent, exc)
            return None
        return parent

    dest = _resolve_destination(Path(agi_share_path_abs), extract_rel)
    dest_parent = _prepare_parent(dest)
    if dest_parent is None:
        logger.warning(
            "Skipping dataset extraction; unable to prepare dataset parent '%s'.",
            dest.parent,
        )
        return

    dataset = dest / "dataset"
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

    if dataset.exists() and force_refresh:
        try:
            def _ignore_missing(func, path, excinfo):
                exc = excinfo[1]
                if isinstance(exc, FileNotFoundError):
                    return
                raise exc

            rmtree_fn(dataset, onerror=_ignore_missing)
        except FileNotFoundError:
            pass
        except PermissionError as exc:
            if verbose > 0:
                logger.info(f"Unable to refresh dataset '{dataset}': {exc}. Skipping extraction.")
            return

    try:
        ensure_dir_fn(dataset)
    except OSError as exc:
        logger.warning("Unable to create dataset directory '%s': %s. Skipping extraction.", dataset, exc)
        return

    try:
        with sevenzip_file_cls(archive_path, mode="r") as archive:
            size_mb = _archive_size_mb(archive_path)
            size_hint = f" (~{size_mb:.1f} MB)" if size_mb else ""
            if verbose > 1:
                logger.info(
                    f"Starting dataset extraction: {archive_path}{size_hint} -> {dataset} "
                    "(this can take a moment; please wait)."
                )
            archive.extractall(path=dest)
        if verbose > 1:
            logger.info(f"Extracted '{archive_path}' to '{dest}'.")

        stamp_path = dataset / ".agilab_dataset_stamp"
        _write_dataset_stamp(archive_path, stamp_path)
    except EXTRACTION_FAILURE_EXCEPTIONS as exc:
        # Extraction is an operational boundary: surface archive/read/write failures
        # to callers through one stable RuntimeError contract.
        logger.error(f"Failed to extract '{archive_path}': {exc}")
        traceback.print_exc()
        raise RuntimeError(f"Extraction failed for '{archive_path}'") from exc
