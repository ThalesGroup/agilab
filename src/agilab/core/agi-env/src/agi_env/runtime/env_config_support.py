"""Pure dotenv and environment-file helpers for AGILAB."""

from __future__ import annotations

from contextlib import contextmanager
import os
import os as _stdlib_os
import re
from collections.abc import Mapping
from pathlib import Path
import shutil
import stat
import tempfile
from typing import Callable, Iterable

from dotenv import dotenv_values, set_key, unset_key

from agi_env.runtime.atomic_write_support import (
    FILE_LOCK_TIMEOUT_SECONDS,
    acquire_bounded_file_lock,
    release_file_lock,
    run_with_windows_file_sharing_retry,
)

ENV_MAPPING_EXCEPTIONS = (AttributeError, TypeError)
_ENV_VAR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ENV_FILE_LOCK_TIMEOUT_SECONDS = FILE_LOCK_TIMEOUT_SECONDS


@contextmanager
def _env_file_lock(env_file: Path):
    """Hold a stable cross-process lock for one dotenv transaction."""

    lock_path = env_file.with_name(env_file.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    locked = False
    try:
        acquire_bounded_file_lock(
            handle,
            lock_path,
            timeout_seconds=_ENV_FILE_LOCK_TIMEOUT_SECONDS,
        )
        locked = True
        yield
    finally:
        try:
            if locked:
                release_file_lock(handle)
        finally:
            handle.close()


def _fsync_directory(path: Path) -> None:
    try:
        fd = _stdlib_os.open(path, _stdlib_os.O_RDONLY)
    except OSError:
        return
    try:
        _stdlib_os.fsync(fd)
    except OSError:
        pass
    finally:
        _stdlib_os.close(fd)


def _transaction_temp_copy(env_file: Path) -> Path:
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{env_file.name}.", suffix=".tmp", dir=env_file.parent
    )
    _stdlib_os.close(fd)
    tmp_path = Path(tmp_name)
    if env_file.exists():
        shutil.copyfile(env_file, tmp_path)
    return tmp_path


def _publish_env_temp(tmp_path: Path, env_file: Path) -> None:
    # Windows' fsync/_commit requires a writable descriptor.
    with tmp_path.open("r+b") as stream:
        _stdlib_os.fsync(stream.fileno())
    run_with_windows_file_sharing_retry(lambda: _stdlib_os.replace(tmp_path, env_file))
    _fsync_directory(env_file.parent)


def update_env_file_text(
    env_file: Path,
    update: Callable[[str | None], str | None],
    *,
    encoding: str = "utf-8",
    file_mode: int | None = None,
    refuse_symlink_message: str | None = None,
) -> bool:
    """Apply one read/modify/write dotenv transaction and publish atomically.

    ``update`` receives ``None`` when the file is missing. Returning ``None``
    leaves an existing file untouched; returning text publishes it. Existing
    permissions are preserved unless ``file_mode`` is provided, while newly
    created files default to owner-only permissions.
    """

    env_file.parent.mkdir(parents=True, exist_ok=True)
    with _env_file_lock(env_file):
        if refuse_symlink_message and env_file.is_symlink():
            raise OSError(refuse_symlink_message)

        exists = env_file.exists()
        current_text = (
            run_with_windows_file_sharing_retry(
                lambda: env_file.read_text(encoding=encoding)
            )
            if exists
            else None
        )
        updated_text = update(current_text)
        if updated_text is None:
            return False

        mode = file_mode
        if mode is None:
            mode = stat.S_IMODE(env_file.stat().st_mode) if exists else 0o600

        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{env_file.name}.", suffix=".tmp", dir=env_file.parent
        )
        tmp_path = Path(tmp_name)
        try:
            with _stdlib_os.fdopen(fd, "w", encoding=encoding) as stream:
                stream.write(updated_text)
                stream.flush()
                _stdlib_os.fsync(stream.fileno())
            tmp_path.chmod(mode)
            _publish_env_temp(tmp_path, env_file)
            return True
        except BaseException:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass
            raise


def build_remote_env_update_script(
    updates: Mapping[str, object],
    *,
    default_comments: Iterable[str] = (),
) -> str:
    """Build a dependency-free remote dotenv transaction script.

    The emitted script cooperates with local AGILAB writers through the same
    stable ``.env.lock`` file, merges against the latest content under that
    lock, and publishes through a uniquely named fsynced temporary file.
    """

    update_rows = [(str(key), str(value)) for key, value in updates.items()]
    invalid_keys = [key for key, _value in update_rows if not _ENV_VAR_NAME_RE.fullmatch(key)]
    if invalid_keys:
        raise ValueError(f"Invalid dotenv key for remote update: {invalid_keys[0]!r}")
    comment_rows = [str(line) for line in default_comments]
    managed_key_comments = "\n".join(
        f"# managed dotenv key: {key}=" for key, _value in update_rows
    )
    template = """\
import os
import stat
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

__MANAGED_KEYS__
updates = __UPDATES__
default_comments = __COMMENTS__
update_keys = {key for key, _value in updates}
env_path = Path.home() / ".agilab/.env"
env_path.parent.mkdir(parents=True, exist_ok=True)


def _sharing_retry(operation):
    deadline = time.monotonic() + 0.5
    while True:
        try:
            return operation()
        except PermissionError:
            if os.name != "nt":
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            time.sleep(min(0.01, remaining))


@contextmanager
def _env_lock():
    lock_path = env_path.with_name(env_path.name + ".lock")
    handle = lock_path.open("a+b")
    locked = False
    try:
        if os.name == "nt":
            import msvcrt

            if lock_path.stat().st_size == 0:
                handle.write(b"\\n")
                handle.flush()
                os.fsync(handle.fileno())
            def _try_lock():
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            def _try_lock():
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        deadline = time.monotonic() + 5.0
        while True:
            try:
                _try_lock()
                locked = True
                break
            except OSError as exc:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"Timed out waiting for AGILAB dotenv lock {lock_path}. "
                        "Another session may still be updating it; retry after it finishes."
                    ) from exc
                time.sleep(min(0.05, remaining))
        yield
    finally:
        if locked:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


with _env_lock():
    current = (
        _sharing_retry(lambda: env_path.read_text(encoding="utf-8"))
        if env_path.exists()
        else ""
    )
    lines = []
    existing_keys = set()
    for raw_line in current.splitlines():
        candidate = raw_line.strip()
        if candidate.startswith("#"):
            candidate = candidate[1:].strip()
        if "=" in candidate:
            existing_keys.add(candidate.split("=", 1)[0].strip())
        active_key = raw_line.split("=", 1)[0].strip()
        if active_key not in update_keys:
            lines.append(raw_line)

    missing_comments = []
    for comment_line in default_comments:
        key = comment_line.lstrip("#").split("=", 1)[0].strip()
        if key in update_keys or key in existing_keys:
            continue
        missing_comments.append(comment_line)
    if missing_comments:
        if lines and lines[-1] != "":
            lines.append("")
        lines.append("# Optional AGILAB cluster env defaults (commented)")
        lines.extend(missing_comments)
        lines.append("")
    for key, value in updates:
        lines.append(f"{key}={value!r}")
    content = "\\n".join(lines).rstrip() + "\\n"

    mode = stat.S_IMODE(env_path.stat().st_mode) if env_path.exists() else 0o600
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{env_path.name}.", suffix=".tmp", dir=env_path.parent
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        tmp_path.chmod(mode)
        _sharing_retry(lambda: os.replace(tmp_path, env_path))
    except BaseException:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise

print(str(env_path))
"""
    return (
        template.replace("__MANAGED_KEYS__", managed_key_comments)
        .replace("__UPDATES__", repr(update_rows))
        .replace("__COMMENTS__", repr(comment_rows))
    )


def _normalize_env_value(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def clean_envar_value(
    envars: Mapping[str, object] | None,
    key: str,
    *,
    fallback_to_process: bool = False,
) -> str | None:
    """Return a stripped env value or ``None`` when unset/blank."""

    raw = None
    try:
        raw = envars.get(key) if envars is not None else None
    except ENV_MAPPING_EXCEPTIONS:
        raw = None
    value = _normalize_env_value(raw)
    if value is not None:
        return value
    if fallback_to_process:
        return _normalize_env_value(os.environ.get(key))
    return None


def load_dotenv_values(dotenv_path: Path, *, verbose: bool = False) -> dict[str, str]:
    """Load dotenv values while treating blank assignments as unset."""

    loaded = run_with_windows_file_sharing_retry(
        lambda: dotenv_values(dotenv_path=dotenv_path, verbose=verbose)
    )
    normalized: dict[str, str] = {}
    for key, value in loaded.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        normalized[str(key)] = value
    return normalized


def write_env_updates(env_file: Path, updates: dict[str, object]) -> None:
    """Persist updates into a dotenv file without shell-style quoting."""

    if not updates:
        return
    env_file.parent.mkdir(parents=True, exist_ok=True)
    with _env_file_lock(env_file):
        tmp_path = _transaction_temp_copy(env_file)
        try:
            for key, value in updates.items():
                set_key(str(tmp_path), key, str(value), quote_mode="never")
            _publish_env_temp(tmp_path, env_file)
        finally:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass


def remove_env_keys(env_file: Path, keys) -> list[str]:
    """Remove ``keys`` from a dotenv file, returning the keys that were present.

    Counterpart to :func:`write_env_updates`, which only ever adds. Missing
    files and missing keys are treated as no-ops, so callers can prune stale
    entries idempotently without making python-dotenv emit missing-key warnings.
    """

    env_file.parent.mkdir(parents=True, exist_ok=True)
    with _env_file_lock(env_file):
        if not env_file.exists():
            return []
        present_keys = [str(key) for key in dotenv_values(dotenv_path=env_file)]
        case_insensitive = os.name == "nt"
        removed: list[str] = []
        tmp_path = _transaction_temp_copy(env_file)
        try:
            for requested_key in keys:
                requested = str(requested_key)
                matching_keys = [
                    present
                    for present in present_keys
                    if (
                        present.casefold() == requested.casefold()
                        if case_insensitive
                        else present == requested
                    )
                ]
                for actual_key in matching_keys:
                    result, _ = unset_key(str(tmp_path), actual_key, quote_mode="never")
                    if result:
                        removed.append(actual_key)
                    present_keys.remove(actual_key)
            if removed:
                _publish_env_temp(tmp_path, env_file)
            return removed
        finally:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass
