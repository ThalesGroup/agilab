"""Worker-side CLI helpers for AGILAB node runtimes."""

import os
import sys
import contextlib
import importlib
import signal
import logging
import json
import hashlib
import shlex
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath
from tempfile import gettempdir
import shutil
import subprocess
import zipfile
import platform
import threading
import time
import faulthandler

faulthandler.enable()

USAGE = """
Usage: python cli.py <cmd> [arg]

Commands:
  kill <wenv_path> [exclude_pids]
                           Kill Dask processes proven to own this worker runtime
  kill-force [exclude_pids] Broad operator recovery for all matching Dask processes
  clean <wenv_path>        Clean the given wenv directory
  clean-force <wenv_path>  Also remove the host-wide Dask scratch directory
  target-lease-acquire <wenv_path> <token> [operation]
                           Acquire the exact remote-target lifecycle lease
  target-lease-release <wenv_path> <token>
                           Release only the matching lease generation
  target-lease-recover <wenv_path> <token> <recovered_tokens> [operation]
                           Replace only an identity-proven stale generation
  unzip <wenv_path>        Unzip resources into the given wenv directory
  threaded                 Run the Python threads test
  platform                 Show Python platform/version info
  rapids-probe             Probe NVIDIA/RAPIDS hardware capability as JSON

Examples:
  python cli.py kill /path/to/wenv
  python cli.py kill-force
  python cli.py kill /path/to/wenv 1234,5678
  python cli.py clean /path/to/wenv
  python cli.py unzip /path/to/wenv
  python cli.py threaded
  python cli.py platform
  python cli.py rapids-probe
"""

# --- Tunables for speed ---
PS_TIMEOUT = float(os.environ.get("CLI_PS_TIMEOUT", "0.35"))
TASKLIST_TIMEOUT = float(os.environ.get("CLI_TASKLIST_TIMEOUT", "0.6"))
POLL_INTERVAL = float(os.environ.get("CLI_POLL_INTERVAL", "0.02"))
GRACE_TOTAL = float(os.environ.get("CLI_GRACE_TOTAL", "0.30"))
FREETHREADED_THRESHOLD = float(os.environ.get("CLI_FREETHREADED_THRESHOLD", "0.80"))
BASELINE_TARGET_S = float(os.environ.get("CLI_BASELINE_TARGET_S", "0.15"))  # target single-thread work
RAPIDS_PROBE_TIMEOUT = float(os.environ.get("CLI_RAPIDS_PROBE_TIMEOUT", "3.0"))

logger = logging.getLogger(__name__)

_PROCESS_LIST_EXCEPTIONS = (OSError, subprocess.SubprocessError)
_CLEAN_EXCEPTIONS = (OSError, ValueError)
_UNZIP_EXCEPTIONS = (OSError, zipfile.BadZipFile)
_RAPIDS_PROBE_EXCEPTIONS = (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired)
_NVIDIA_SMI_CANDIDATES = (
    "nvidia-smi",
    "/usr/bin/nvidia-smi",
    "/usr/local/bin/nvidia-smi",
    "/usr/local/cuda/bin/nvidia-smi",
)
_PID_RECORD_SCHEMA = "agilab-dask-pid-owner-v1"
_PID_START_TOLERANCE_SECONDS = 1.0
_REMOTE_TARGET_LEASE_SCHEMA = "agilab-remote-target-lease-v1"


class _LazyPsutil:
    """Load psutil only for process-management commands.

    This module is copied to ``~/wenv/cli.py`` and lease commands execute it
    before the worker environment, including optional third-party packages,
    exists.
    """

    def __init__(self) -> None:
        object.__setattr__(self, "_module", None)

    def _load(self):
        module = object.__getattribute__(self, "_module")
        if module is None:
            try:
                module = importlib.import_module("psutil")
            except ImportError as exc:
                raise RuntimeError(
                    "psutil is required for AGILAB process-management commands."
                ) from exc
            object.__setattr__(self, "_module", module)
        return module

    def __getattr__(self, name):
        return getattr(self._load(), name)

    def __setattr__(self, name, value) -> None:
        if name == "_module":
            object.__setattr__(self, name, value)
            return
        setattr(self._load(), name, value)

    def __delattr__(self, name) -> None:
        delattr(self._load(), name)


psutil = _LazyPsutil()

# ---------------- helpers ----------------
def validate_archive_members_stay_within_dest(archive, dest: Path) -> None:
    """Reject ZIP entries that escape ``dest`` without importing ``agi_env``."""

    member_names = None
    for method_name in ("getnames", "namelist"):
        getnames = getattr(archive, method_name, None)
        if callable(getnames):
            member_names = [str(name) for name in getnames()]
            break
    if member_names is None:
        return

    resolved_dest = dest.resolve()
    for member_name in member_names:
        normalized = member_name.replace("\\", "/")
        posix_member = PurePosixPath(normalized)
        windows_member = PureWindowsPath(member_name)
        if posix_member.is_absolute() or windows_member.is_absolute() or windows_member.drive:
            raise RuntimeError(f"Unsafe archive member path in '{member_name}'")
        target = (resolved_dest / Path(*posix_member.parts)).resolve()
        if not target.is_relative_to(resolved_dest):
            raise RuntimeError(f"Unsafe archive member path in '{member_name}'")


def _resolved_destructive_path(value):
    try:
        return Path(value).expanduser().resolve(strict=False)
    except (OSError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid filesystem path {value!r}: {exc}") from exc


def _destructive_path_is_relative_to(path, parent):
    try:
        path.relative_to(parent)
    except ValueError:
        pass
    else:
        return True

    try:
        if not parent.exists():
            return False
    except OSError:
        return False
    candidate = path
    while True:
        try:
            if candidate.exists() and candidate.samefile(parent):
                return True
        except (OSError, ValueError):
            pass
        next_candidate = candidate.parent
        if next_candidate == candidate:
            return False
        candidate = next_candidate


def safe_destructive_path(path, *, roots, label="destructive operation", protected_paths=()):
    """Self-contained confinement for the pre-install worker bootstrap CLI.

    This file is copied and executed before the new worker environment is
    installed, so it must not import helpers introduced by the incoming
    ``agi-env`` release.
    """

    try:
        raw_value = os.fspath(path)
    except TypeError as exc:
        raise ValueError(f"{label} target must be a filesystem path") from exc
    if not isinstance(raw_value, str) or not raw_value.strip() or "\x00" in raw_value:
        raise ValueError(f"{label} target is empty or malformed")

    raw_path = Path(raw_value).expanduser()
    windows_path = PureWindowsPath(raw_value)
    if raw_path in (Path("."), Path("..")) or ".." in (
        raw_path.parts + windows_path.parts
    ):
        raise ValueError(f"{label} target must not contain parent traversal")
    if windows_path.drive and not windows_path.root:
        raise ValueError(f"{label} target must not be drive-relative")

    target = _resolved_destructive_path(raw_path)
    if target == Path(target.anchor):
        raise ValueError(f"{label} target must not be the filesystem root")

    resolved_roots = [_resolved_destructive_path(root) for root in roots]
    if not resolved_roots:
        raise ValueError(f"{label} requires a trusted confinement root")
    for root in resolved_roots:
        if _destructive_path_is_relative_to(
            target,
            root,
        ) and _destructive_path_is_relative_to(root, target):
            raise ValueError(f"{label} target must not be the confinement root")
    if not any(
        _destructive_path_is_relative_to(target, root) for root in resolved_roots
    ):
        roots_text = ", ".join(str(root) for root in resolved_roots)
        raise ValueError(
            f"{label} target must stay under a trusted root ({roots_text}), got {target}"
        )

    for protected_path in protected_paths:
        protected = _resolved_destructive_path(protected_path)
        if target == protected:
            raise ValueError(f"{label} target must not be protected path {protected}")
    return target


def safe_worker_runtime_cleanup_path(
    path,
    *,
    roots,
    home_path=None,
    cwd_path=None,
):
    protected = tuple(item for item in (home_path, cwd_path) if item is not None)
    return safe_destructive_path(
        path,
        roots=roots,
        label="worker runtime cleanup",
        protected_paths=protected,
    )


def _remote_target_lease_path(target: Path) -> Path:
    target = _normalized_path(target)
    target_key = os.path.normcase(os.path.normpath(str(target))).replace("\\", "/")
    digest = hashlib.sha256(target_key.encode("utf-8")).hexdigest()[:20]
    return target.parent / ".agilab-target-leases" / f"target-{digest}.lock"


def _read_remote_target_lease(target: Path) -> dict:
    owner_path = _remote_target_lease_path(target) / "owner.json"
    try:
        payload = json.loads(owner_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _valid_remote_target_lease_token(token: str) -> bool:
    if len(token) != 32:
        return False
    try:
        int(token, 16)
    except ValueError:
        return False
    return True


def _remote_target_lease_marker(lock_path: Path, token: str) -> Path:
    return lock_path / f"token-{token}"


def _fsync_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _remote_release_tombstone(lock_path: Path, token: str) -> Path:
    return lock_path.with_name(f".{lock_path.name}.released-{token}")


def _read_json_file(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _valid_marker_claim(path: Path, token: str) -> bool:
    try:
        return path.is_file() and path.read_text(encoding="ascii").strip() == token
    except OSError:
        return False


def _release_marker_claims(lock_path: Path, token: str) -> list[Path]:
    return [
        candidate
        for candidate in sorted(
            lock_path.parent.glob(
                f".{lock_path.name}.release-claim-{token}-*"
            ),
            key=lambda path: path.name,
        )
        if _valid_marker_claim(candidate, token)
    ]


def _release_owner_claims(lock_path: Path, token: str) -> list[Path]:
    claims: list[Path] = []
    for candidate in sorted(
        lock_path.parent.glob(
            f".{lock_path.name}.release-owner-claim-{token}-*"
        ),
        key=lambda path: path.name,
    ):
        owner = _read_json_file(candidate)
        if (
            owner.get("schema") == _REMOTE_TARGET_LEASE_SCHEMA
            and str(owner.get("token") or "") == token
        ):
            claims.append(candidate)
    return claims


def _acquire_publication_claims(lock_path: Path, token: str) -> list[Path]:
    claims: list[Path] = []
    for candidate in sorted(
        lock_path.parent.glob(
            f".{lock_path.name}.acquire-claim-{token}-*"
        ),
        key=lambda path: path.name,
    ):
        owner = _read_json_file(candidate)
        if (
            owner.get("schema") == _REMOTE_TARGET_LEASE_SCHEMA
            and str(owner.get("token") or "") == token
        ):
            claims.append(candidate)
    return claims


def remote_target_lease_owned(target: Path, token: str) -> bool:
    if not _valid_remote_target_lease_token(token):
        return False
    lock_path = _remote_target_lease_path(target)
    owner = _read_remote_target_lease(target)
    return (
        owner.get("schema") == _REMOTE_TARGET_LEASE_SCHEMA
        and str(owner.get("token") or "") == str(token)
        and _remote_target_lease_marker(lock_path, token).is_file()
    )


def acquire_remote_target_lease(target: Path, token: str, operation: str = "unknown") -> bool:
    """Atomically claim a worker-host target for one manager lifecycle token."""

    if not _valid_remote_target_lease_token(token):
        logger.error("Remote target lease token must be exactly 32 hexadecimal characters")
        return False
    target = _normalized_path(target)
    lock_path = _remote_target_lease_path(target)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    owner = {
        "schema": _REMOTE_TARGET_LEASE_SCHEMA,
        "token": token,
        "operation": operation or "unknown",
        "created_at": time.time(),
    }
    publication_claim = lock_path.with_name(
        f".{lock_path.name}.acquire-claim-{token}-{uuid.uuid4().hex}"
    )
    claimed_destination = False
    published = False
    try:
        with publication_claim.open("x", encoding="utf-8") as stream:
            json.dump(owner, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        _fsync_directory(lock_path.parent)
        # mkdir is the no-replace destination CAS on every supported platform.
        # The external publication claim makes a crash after this point exactly
        # recoverable even before owner.json or the token marker is visible.
        lock_path.mkdir()
        claimed_destination = True
        owner_tmp = lock_path / f".owner.{token}.{uuid.uuid4().hex}.tmp"
        with owner_tmp.open("x", encoding="utf-8") as stream:
            json.dump(owner, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(owner_tmp, lock_path / "owner.json")
        marker = _remote_target_lease_marker(lock_path, token)
        with marker.open("x", encoding="ascii") as stream:
            stream.write(token + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        _fsync_directory(lock_path)
        _fsync_directory(lock_path.parent)
        published = True
    except FileExistsError:
        if remote_target_lease_owned(target, token):
            return True
        owner = _read_remote_target_lease(target)
        logger.error(
            "Worker runtime %s is already leased by operation %s (token=%s)",
            target,
            owner.get("operation", "unknown"),
            owner.get("token", "unknown"),
        )
        return False
    except OSError as exc:
        if lock_path.exists():
            owner = _read_remote_target_lease(target)
            logger.error(
                "Worker runtime %s is already leased by operation %s (token=%s)",
                target,
                owner.get("operation", "unknown"),
                owner.get("token", "unknown"),
            )
        else:
            logger.error("Could not persist worker runtime lease for %s: %s", target, exc)
        return False
    finally:
        # Preserve the exact publication capability only when this command won
        # the destination but failed before publishing a complete generation.
        if published or not claimed_destination:
            with contextlib.suppress(OSError):
                publication_claim.unlink()
    return True


def release_remote_target_lease(target: Path, token: str) -> bool:
    """Release only the exact lease generation named by ``token``."""

    target = _normalized_path(target)
    lock_path = _remote_target_lease_path(target)
    if not _valid_remote_target_lease_token(token):
        logger.error("Remote target lease token must be exactly 32 hexadecimal characters")
        return False
    if not lock_path.exists():
        return True

    marker = _remote_target_lease_marker(lock_path, token)
    claim = lock_path.parent / (
        f".{lock_path.name}.release-claim-{token}-{uuid.uuid4().hex}"
    )
    claim_kind = "marker"
    claimed_owner: dict = {}
    try:
        marker.rename(claim)
    except FileNotFoundError:
        owner = _read_remote_target_lease(target)
        owner_token = str(owner.get("token") or "")
        if not lock_path.exists() or (
            owner.get("schema") == _REMOTE_TARGET_LEASE_SCHEMA
            and owner_token != token
        ):
            # This generation was already released. A successor generation,
            # if present, must remain untouched.
            return True
        marker_claims = _release_marker_claims(lock_path, token)
        owner_claims = _release_owner_claims(lock_path, token)
        publication_claims = _acquire_publication_claims(lock_path, token)
        if owner.get("schema") == _REMOTE_TARGET_LEASE_SCHEMA and owner_token == token:
            if marker_claims:
                claim = marker_claims[0]
            elif owner_claims:
                logger.error(
                    "Refusing to release worker runtime %s: owner publication "
                    "claim conflicts with a visible owner",
                    target,
                )
                return False
            else:
                claim_kind = "owner"
                claim = lock_path.parent / (
                    f".{lock_path.name}.release-owner-claim-{token}-{uuid.uuid4().hex}"
                )
                try:
                    (lock_path / "owner.json").rename(claim)
                except OSError as exc:
                    logger.error(
                        "Could not claim partial worker lease publication %s: %s",
                        target,
                        exc,
                    )
                    return False
                claimed_owner = _read_json_file(claim)
        elif not owner and owner_claims:
            claim_kind = "owner"
            claim = owner_claims[0]
            claimed_owner = _read_json_file(claim)
        elif not owner and publication_claims:
            claim_kind = "publication"
            claim = publication_claims[0]
            claimed_owner = _read_json_file(claim)
        else:
            logger.error(
                "Refusing to release worker runtime %s: token generation "
                "evidence is missing",
                target,
            )
            return False
    except OSError as exc:
        logger.error("Could not claim worker runtime lease for release %s: %s", target, exc)
        return False

    owner = claimed_owner or _read_remote_target_lease(target)
    if (
        owner.get("schema") != _REMOTE_TARGET_LEASE_SCHEMA
        or str(owner.get("token") or "") != token
    ):
        # The marker claim is the authorization generation. If its owner
        # record disagrees, fail closed and leave the current lock untouched.
        if lock_path.exists() and str(owner.get("token") or "") == token:
            with contextlib.suppress(OSError):
                if claim_kind == "owner":
                    claim.rename(lock_path / "owner.json")
                elif claim_kind == "marker":
                    claim.rename(marker)
        else:
            with contextlib.suppress(OSError):
                claim.unlink()
        logger.error("Worker runtime lease generation changed before release: %s", target)
        return False

    # Make the moved generation non-empty even when recovering the historical
    # owner-before-marker publication window. The deterministic destination is
    # retained as a tombstone, so a delayed resumer cannot rename a successor
    # generation after another resumer has completed this token.
    release_generation = lock_path / f"release-generation-{token}"
    try:
        with release_generation.open("a", encoding="ascii") as stream:
            stream.write(token + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        if claim_kind == "owner":
            with contextlib.suppress(OSError):
                claim.rename(lock_path / "owner.json")
        elif claim_kind == "marker":
            with contextlib.suppress(OSError):
                claim.rename(marker)
        logger.error("Could not persist worker lease release claim %s: %s", target, exc)
        return False

    quarantine = _remote_release_tombstone(lock_path, token)
    if quarantine.exists():
        with contextlib.suppress(OSError):
            claim.unlink()
        current_owner = _read_remote_target_lease(target)
        if not lock_path.exists() or str(current_owner.get("token") or "") != token:
            return True
        logger.error("Worker runtime lease release is already claimed: %s", target)
        return False
    try:
        lock_path.rename(quarantine)
    except FileNotFoundError:
        with contextlib.suppress(OSError):
            claim.unlink()
        return True
    except OSError as exc:
        if quarantine.exists():
            with contextlib.suppress(OSError):
                claim.unlink()
            current_owner = _read_remote_target_lease(target)
            if not lock_path.exists() or str(current_owner.get("token") or "") != token:
                return True
        current_owner = _read_remote_target_lease(target)
        if str(current_owner.get("token") or "") == token:
            with contextlib.suppress(OSError):
                if claim_kind == "owner":
                    claim.rename(lock_path / "owner.json")
                elif claim_kind == "marker":
                    claim.rename(marker)
        logger.error("Could not release worker runtime lease for %s: %s", target, exc)
        return False
    # Keep the deterministic generation tombstone. It is the durable CAS that
    # makes an arbitrarily delayed release/resumer harmless to successors.
    with contextlib.suppress(OSError):
        claim.unlink()
    for publication_claim in _acquire_publication_claims(lock_path, token):
        with contextlib.suppress(OSError):
            publication_claim.unlink()
    _fsync_directory(lock_path.parent)
    return True


def recover_remote_target_lease(
    target: Path,
    token: str,
    recovered_tokens: list[str] | tuple[str, ...],
    operation: str = "unknown",
) -> bool:
    """Replace an exact stale generation without using lease age as authority.

    ``recovered_tokens`` are capabilities emitted by the manager-side lifecycle
    guard only after it proves the prior manager PID incarnation is gone. The
    worker still performs an exact token-marker CAS. A live or replacement owner
    with any other generation remains untouched.
    """

    if not _valid_remote_target_lease_token(token):
        logger.error("Remote target lease token must be exactly 32 hexadecimal characters")
        return False
    authorized_tokens = tuple(
        dict.fromkeys(
            str(candidate)
            for candidate in recovered_tokens
            if _valid_remote_target_lease_token(str(candidate))
        )
    )
    if not authorized_tokens or len(authorized_tokens) != len(recovered_tokens):
        logger.error("Remote target recovery requires valid exact generation tokens")
        return False
    if token in authorized_tokens:
        logger.error("Replacement lease token must differ from recovered generations")
        return False

    target = _normalized_path(target)
    lock_path = _remote_target_lease_path(target)
    if remote_target_lease_owned(target, token):
        return True
    if not lock_path.exists():
        return acquire_remote_target_lease(target, token, operation)

    owner = _read_remote_target_lease(target)
    owner_token = str(owner.get("token") or "")
    if not owner:
        for recovered_token in authorized_tokens:
            owner_claims = _release_owner_claims(lock_path, recovered_token)
            if owner_claims:
                owner = _read_json_file(owner_claims[0])
                owner_token = str(owner.get("token") or "")
                break
            publication_claims = _acquire_publication_claims(
                lock_path,
                recovered_token,
            )
            if publication_claims:
                owner = _read_json_file(publication_claims[0])
                owner_token = str(owner.get("token") or "")
                break
    if (
        owner.get("schema") != _REMOTE_TARGET_LEASE_SCHEMA
        or owner_token not in authorized_tokens
        or not (
            remote_target_lease_owned(target, owner_token)
            or bool(_release_marker_claims(lock_path, owner_token))
            or bool(_release_owner_claims(lock_path, owner_token))
            or bool(_acquire_publication_claims(lock_path, owner_token))
            or str(_read_remote_target_lease(target).get("token") or "")
            == owner_token
        )
    ):
        logger.error(
            "Refusing to recover worker runtime %s: current generation is not "
            "identity-proven stale",
            target,
        )
        return False

    # Exact-generation release is the recovery CAS. A competing manager may
    # acquire the now-empty path before us; ordinary acquire then fails closed
    # and never removes that successor.
    if not release_remote_target_lease(target, owner_token):
        return False
    return acquire_remote_target_lease(target, token, operation)


def clean(
    wenv=None,
    *,
    force_scratch=False,
    lease_token=None,
    home_path=None,
    cwd_path=None,
):
    try:
        home = Path(home_path).expanduser() if home_path is not None else Path.home()
        cwd = Path(cwd_path).expanduser() if cwd_path is not None else Path.cwd()
        target_path = None
        if wenv is not None:
            raw_target = Path(wenv).expanduser()
            if not raw_target.is_absolute():
                raw_target = cwd / raw_target
            target_path = safe_worker_runtime_cleanup_path(
                raw_target,
                roots=(home / "wenv", cwd / "wenv"),
                home_path=home,
                cwd_path=cwd,
            )

        scratch = None
        if force_scratch:
            temp_root = Path(gettempdir()).expanduser().resolve(strict=False)
            scratch = safe_destructive_path(
                temp_root / "dask-scratch-space",
                roots=(temp_root,),
                label="Dask scratch cleanup",
            )
            logger.info(f"Force cleaning {scratch}")
            shutil.rmtree(scratch, ignore_errors=True)
            logger.info(f"Removed {scratch}")
        if target_path is not None:
            if not force_scratch:
                lock_path = _remote_target_lease_path(target_path)
                if lock_path.exists() and not remote_target_lease_owned(
                    target_path, str(lease_token or "")
                ):
                    logger.error(
                        "Refusing to clean %s without its exact remote lifecycle token",
                        target_path,
                    )
                    return False
                active = _target_dask_processes(target_path)
                if active:
                    logger.error(
                        "Refusing to clean %s while target Dask process(es) remain: %s",
                        target_path,
                        sorted(active),
                    )
                    return False
            logger.info(f"Cleaning {target_path}")
            if not target_path.exists():
                logger.info("Worker environment is already absent: %s", target_path)
                return True
            shutil.rmtree(target_path)
            if target_path.exists():
                logger.error(
                    "Worker environment still exists after cleanup: %s", target_path
                )
                return False
            logger.info(f"Removed {target_path}")
    except _CLEAN_EXCEPTIONS as e:
        logger.error(f"Error during cleanup: {e}")
        return False
    return True

def get_processes_matching(match_fn):
    """Return PIDs whose command line (Unix) or image name (Windows) matches."""
    pids = set()
    if os.name != "nt":
        try:
            logger.debug("Running ps to find matching processes...")
            # Headerless, faster to parse
            output = subprocess.check_output(
                ["ps", "-A", "-o", "pid=", "-o", "command="],
                text=True, timeout=PS_TIMEOUT
            )
            for line in output.splitlines():
                try:
                    pid_str, cmd = line.strip().split(None, 1)
                    if match_fn(cmd):
                        pids.add(int(pid_str))
                except ValueError:
                    continue
        except _PROCESS_LIST_EXCEPTIONS as e:
            logger.warning(f"Unix ps failed: {e}")
    else:
        try:
            logger.debug("Running tasklist to find matching processes...")
            output = subprocess.check_output(
                ["tasklist", "/fo", "csv", "/nh"], text=True, timeout=TASKLIST_TIMEOUT
            )
            for line in output.strip().splitlines():
                parts = [p.strip('"') for p in line.split('","')]
                if len(parts) >= 2:
                    name, pid_str = parts[0], parts[1]
                    if match_fn(name):
                        try:
                            pids.add(int(pid_str))
                        except ValueError:
                            continue
        except _PROCESS_LIST_EXCEPTIONS as e:
            logger.warning(f"Windows tasklist failed: {e}")
    return pids


def get_processes_containing(substring: str):
    substring = substring.lower()
    return get_processes_matching(lambda cmd: substring in cmd.lower())


# Only match actual dask scheduler/worker entrypoints, never arbitrary
# processes whose command line merely contains the substring "dask"
# (e.g. an editor opened on dask_tuning.md or an unrelated project).
_DASK_CMD_MARKERS = (
    "dask-scheduler",
    "dask-worker",
    "dask scheduler",
    "dask worker",
    "dask_scheduler",
    "dask_worker",
    "distributed.cli",
    "distributed.nanny",
    "distributed.worker",
)


def _is_dask_command(cmd: str) -> bool:
    cmd = cmd.lower()
    return any(marker in cmd for marker in _DASK_CMD_MARKERS)


def _normalized_path(path: Path, *, cwd: Path | None = None) -> Path:
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = (cwd or Path.cwd()) / candidate
    return candidate.resolve(strict=False)


def _command_belongs_to_target(
    cmdline,
    target: Path,
    *,
    process_cwd: Path | None = None,
) -> bool:
    """Require an exact project/executable path, never a PID-file substring."""

    if isinstance(cmdline, str):
        try:
            parts = shlex.split(cmdline, posix=os.name != "nt")
        except ValueError:
            return False
    else:
        parts = [str(part) for part in (cmdline or [])]
    if not parts:
        return False

    candidates: list[tuple[str, bool]] = [(parts[0], False)]
    for index, part in enumerate(parts):
        if part == "--project" and index + 1 < len(parts):
            candidates.append((parts[index + 1], True))
        elif part.startswith("--project="):
            candidates.append((part.split("=", 1)[1], True))

    target = _normalized_path(target)
    cwd = process_cwd or Path.cwd()
    for raw_value, is_project_option in candidates:
        value = str(raw_value).strip().strip("\"'")
        if not value or "://" in value:
            continue
        value_path = Path(value)
        if (
            not is_project_option
            and not value_path.is_absolute()
            and "/" not in value
            and "\\" not in value
        ):
            # A bare argv[0] such as "dask" only says which PATH lookup won;
            # it is not proof that the executable came from this runtime.
            continue
        try:
            candidate = _normalized_path(value_path, cwd=cwd)
        except (OSError, RuntimeError, ValueError):
            continue
        try:
            if candidate == target or candidate.is_relative_to(target):
                return True
        except (OSError, ValueError):
            continue
    return False


def _read_pid_record(pid_file: Path) -> tuple[int, float | None, str | None]:
    text = pid_file.read_text(encoding="utf-8").strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return int(text), None, None
    if isinstance(payload, int):
        return int(payload), None, None
    if not isinstance(payload, dict):
        raise ValueError("PID ownership record must be an integer or JSON object")
    pid = int(payload["pid"])
    raw_start = payload.get("process_start_time")
    process_start = float(raw_start) if raw_start not in (None, "") else None
    raw_target = payload.get("target")
    record_target = str(raw_target) if raw_target not in (None, "") else None
    return pid, process_start, record_target


def _write_pid_record(
    pid_file: Path,
    *,
    pid: int,
    process_start_time: float,
    target: Path,
) -> None:
    payload = {
        "schema": _PID_RECORD_SCHEMA,
        "pid": int(pid),
        "process_start_time": float(process_start_time),
        "target": _normalized_path(target).as_posix(),
    }
    tmp_path = pid_file.with_name(f".{pid_file.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp_path.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_path, pid_file)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def _target_pid_files(target: Path) -> list[Path]:
    """Return namespaced PID files plus legacy shared-parent candidates."""

    target = _normalized_path(target)
    candidates: set[Path] = set()
    for root in (target, target.parent):
        candidates.update(root.glob("dask_scheduler.pid"))
        candidates.update(root.glob("dask_worker*.pid"))
    # Historical remote schedulers wrote this file in the worker account home,
    # one level above the shared worker-environment directory.
    candidates.update(target.parent.parent.glob("dask_scheduler.pid"))
    return sorted(candidates, key=lambda path: path.as_posix())


def _process_identity(pid: int) -> tuple[object, float, list[str], Path | None] | None:
    try:
        process = psutil.Process(pid)
        process_start = float(process.create_time())
        cmdline = [str(part) for part in process.cmdline()]
        try:
            process_cwd = Path(process.cwd())
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            process_cwd = None
        return process, process_start, cmdline, process_cwd
    except psutil.NoSuchProcess:
        return None
    except (psutil.AccessDenied, OSError, TypeError, ValueError):
        raise RuntimeError(f"Cannot prove process ownership for PID {pid}") from None


def _process_incarnation_state(pid: int, expected_start: float) -> bool | None:
    try:
        process = psutil.Process(pid)
        if abs(float(process.create_time()) - expected_start) > _PID_START_TOLERANCE_SECONDS:
            return False
        if not process.is_running():
            return False
        status = process.status()
        return status != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False
    except (psutil.AccessDenied, OSError, TypeError, ValueError):
        return None


def _same_process_incarnation(pid: int, expected_start: float) -> bool:
    return _process_incarnation_state(pid, expected_start) is True


def _poll_process_incarnations_until_dead(
    process_starts: dict[int, float],
    total: float = GRACE_TOTAL,
    interval: float = POLL_INTERVAL,
) -> set[int]:
    deadline = time.monotonic() + total
    remaining = dict(process_starts)
    while remaining and time.monotonic() < deadline:
        remaining = {
            pid: started
            for pid, started in remaining.items()
            if _process_incarnation_state(pid, started) is not False
        }
        if remaining:
            time.sleep(interval)
    return set(remaining)


def _target_dask_processes(target: Path) -> dict[int, float]:
    target = _normalized_path(target)
    processes: dict[int, float] = {}
    for process in psutil.process_iter(["pid", "cmdline", "create_time"]):
        try:
            info = process.info
            cmdline = info.get("cmdline") or []
            command_text = " ".join(str(part) for part in cmdline)
            if not _is_dask_command(command_text):
                continue
            try:
                process_cwd = Path(process.cwd())
            except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
                process_cwd = None
            if _command_belongs_to_target(cmdline, target, process_cwd=process_cwd):
                processes[int(info["pid"])] = float(info["create_time"])
        except (KeyError, TypeError, ValueError, psutil.NoSuchProcess):
            continue
        except (psutil.AccessDenied, OSError):
            continue
    return processes

def get_child_pids(parent_pids):
    children = set()
    if not parent_pids:
        return children
    if os.name != "nt":
        try:
            logger.debug("Finding child PIDs...")
            output = subprocess.check_output(
                ["ps", "-A", "-o", "pid=", "-o", "ppid="], text=True, timeout=PS_TIMEOUT
            )
            for line in output.strip().splitlines():
                try:
                    pid_str, ppid_str = line.strip().split(None, 1)
                    pid = int(pid_str)
                    ppid = int(ppid_str)
                    if ppid in parent_pids:
                        children.add(pid)
                except ValueError:
                    continue
        except _PROCESS_LIST_EXCEPTIONS as e:
            logger.warning(f"ps for child processes failed: {e}")
    return children

def _is_alive(pid: int) -> bool:
    try:
        # On Unix, signal 0 checks existence; on Windows raises if invalid.
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Probably alive but not permitted; assume alive so we attempt SIGKILL next.
        return True
    except OSError:
        # Unknown; be conservative.
        return True

def kill_pids(pids, sig, *, process_starts: dict[int, float] | None = None):
    survivors = set()
    for pid in pids:
        if process_starts is not None:
            expected_start = process_starts.get(pid)
            if expected_start is None or not _same_process_incarnation(
                pid, expected_start
            ):
                logger.info("PID %s no longer has the authorized incarnation", pid)
                continue
        try:
            os.kill(pid, sig)
            logger.info(f"Sent signal {sig} to PID {pid}")
        except ProcessLookupError:
            logger.info(f"Process {pid} not found (already stopped)")
        except PermissionError:
            logger.warning(f"No permission to kill process {pid}")
            survivors.add(pid)
        except OSError as e:
            logger.warning(f"Failed to kill PID {pid} with signal {sig}: {e}")
            survivors.add(pid)
    return survivors

def _poll_until_dead(pids, total=GRACE_TOTAL, interval=POLL_INTERVAL):
    deadline = time.monotonic() + total
    remaining = set(pids)
    while remaining and time.monotonic() < deadline:
        remaining = {pid for pid in remaining if _is_alive(pid)}
        if remaining:
            time.sleep(interval)
    return remaining


def _unlink_pid_files(pid_files: set[Path]) -> bool:
    removed = True
    for pid_file in sorted(pid_files, key=lambda path: path.as_posix()):
        try:
            pid_file.unlink()
        except FileNotFoundError:
            continue
        except OSError as exc:
            logger.warning("Could not remove pid file %s: %s", pid_file, exc)
            removed = False
    return removed


def _force_kill(exclude_pids: set[int]) -> bool:
    """Broad operator recovery, deliberately outside target ownership rules."""

    dask_pids = get_processes_matching(_is_dask_command) - exclude_pids
    child_pids = get_child_pids(dask_pids)
    target_pids = (dask_pids | child_pids) - exclude_pids
    module_dir = Path(__file__).parent
    pid_files = (
        set(Path("").glob("*.pid"))
        | set(module_dir.glob("*.pid"))
        | set(module_dir.parent.glob("*.pid"))
    )

    if target_pids:
        logger.info("Force-killing Dask PIDs/children: %s", sorted(target_pids))
        kill_pids(target_pids, signal.SIGTERM)
        survivors = _poll_until_dead(target_pids)
        if survivors and hasattr(signal, "SIGKILL"):
            kill_pids(survivors, signal.SIGKILL)
            survivors = _poll_until_dead(survivors)
        if survivors:
            logger.error("Dask process(es) survived force cleanup: %s", sorted(survivors))
            return False
    else:
        logger.info("No Dask process running.")

    return _unlink_pid_files(pid_files)


def _pid_file_is_target_namespaced(pid_file: Path, target: Path) -> bool:
    try:
        return pid_file.parent.resolve(strict=False) == target
    except (OSError, RuntimeError, ValueError):
        return False


def _record_targets_runtime(record_target: str | None, target: Path) -> bool:
    if not record_target:
        return False
    try:
        return _normalized_path(Path(record_target)) == target
    except (OSError, RuntimeError, ValueError):
        return False


def _plain_pid_record_can_name_process(pid_file: Path, process_start: float) -> bool:
    """Reject a plain PID record when the PID was created after the record."""

    try:
        record_time = pid_file.stat().st_mtime
    except OSError:
        return False
    return process_start <= record_time + _PID_START_TOLERANCE_SECONDS


def _add_child_incarnations(process_starts: dict[int, float]) -> bool:
    """Snapshot exact descendants without authorizing a reused child PID."""

    parents = set(process_starts)
    while parents:
        next_parents: set[int] = set()
        for parent_pid in parents:
            parent_start = process_starts[parent_pid]
            state = _process_incarnation_state(parent_pid, parent_start)
            if state is False:
                continue
            if state is None:
                logger.warning(
                    "Cannot prove parent process incarnation for PID %s", parent_pid
                )
                return False
            try:
                parent = psutil.Process(parent_pid)
                children = parent.children(recursive=False)
            except psutil.NoSuchProcess:
                continue
            except (psutil.AccessDenied, OSError, TypeError, ValueError):
                logger.warning("Cannot inspect child processes for PID %s", parent_pid)
                return False
            for child in children:
                try:
                    child_pid = int(child.pid)
                    child_start = float(child.create_time())
                    # Recheck the relationship after reading the incarnation;
                    # a PID recycled between children() and create_time() must
                    # not inherit kill authorization from the former child.
                    if int(child.ppid()) != parent_pid:
                        continue
                except psutil.NoSuchProcess:
                    continue
                except (psutil.AccessDenied, OSError, TypeError, ValueError):
                    logger.warning(
                        "Cannot prove child process incarnation under PID %s",
                        parent_pid,
                    )
                    return False
                if child_pid in process_starts:
                    continue
                process_starts[child_pid] = child_start
                next_parents.add(child_pid)
        parents = next_parents
    return True


def _scoped_kill(target: Path, exclude_pids: set[int]) -> bool:
    target = _normalized_path(target)
    process_starts: dict[int, float] = {}
    evidence_files: set[Path] = set()
    stale_evidence: set[Path] = set()
    ownership_uncertain = False

    for pid_file in _target_pid_files(target):
        target_namespaced = _pid_file_is_target_namespaced(pid_file, target)
        try:
            pid, expected_start, record_target = _read_pid_record(pid_file)
        except (OSError, KeyError, TypeError, ValueError) as exc:
            logger.warning("Could not read PID ownership record %s: %s", pid_file, exc)
            ownership_uncertain = ownership_uncertain or target_namespaced
            continue

        explicitly_targeted = _record_targets_runtime(record_target, target)
        if record_target and not explicitly_targeted:
            continue
        if pid in exclude_pids:
            logger.info("Skipping excluded PID %s from file %s", pid, pid_file)
            continue

        try:
            identity = _process_identity(pid)
        except RuntimeError as exc:
            if target_namespaced or explicitly_targeted:
                ownership_uncertain = True
            logger.warning("%s", exc)
            continue
        if identity is None:
            if target_namespaced or explicitly_targeted:
                stale_evidence.add(pid_file)
            continue

        _process, process_start, cmdline, process_cwd = identity
        command_owned = _is_dask_command(" ".join(cmdline)) and _command_belongs_to_target(
            cmdline,
            target,
            process_cwd=process_cwd,
        )
        same_incarnation = (
            abs(process_start - expected_start) <= _PID_START_TOLERANCE_SECONDS
            if expected_start is not None
            else _plain_pid_record_can_name_process(pid_file, process_start)
        )
        if not command_owned or not same_incarnation:
            if target_namespaced or explicitly_targeted:
                if expected_start is not None and not same_incarnation:
                    stale_evidence.add(pid_file)
                elif expected_start is None and not same_incarnation:
                    stale_evidence.add(pid_file)
                else:
                    ownership_uncertain = True
            continue

        process_starts[pid] = process_start
        evidence_files.add(pid_file)
        try:
            _write_pid_record(
                pid_file,
                pid=pid,
                process_start_time=process_start,
                target=target,
            )
        except OSError as exc:
            # The original PID evidence remains in place; do not erase it on a
            # failed stop merely because the incarnation upgrade was blocked.
            logger.warning("Could not upgrade PID ownership record %s: %s", pid_file, exc)

    residual_before = _target_dask_processes(target)
    unauthorized = set(residual_before) - set(process_starts) - exclude_pids
    excluded_active = set(residual_before) & exclude_pids
    if unauthorized or excluded_active:
        ownership_uncertain = True
        logger.error(
            "Cannot prove PID ownership for target Dask process(es): %s",
            sorted(unauthorized | excluded_active),
        )

    if not _add_child_incarnations(process_starts):
        ownership_uncertain = True
    if process_starts:
        logger.info("Target-owned Dask PIDs/children to kill: %s", sorted(process_starts))
        kill_pids(
            set(process_starts),
            signal.SIGTERM,
            process_starts=process_starts,
        )
        survivors = _poll_process_incarnations_until_dead(process_starts)
        if survivors and hasattr(signal, "SIGKILL"):
            kill_pids(
                survivors,
                signal.SIGKILL,
                process_starts=process_starts,
            )
            survivors = _poll_process_incarnations_until_dead(
                {pid: process_starts[pid] for pid in survivors}
            )
        if survivors:
            logger.error("Target Dask process(es) survived cleanup: %s", sorted(survivors))
            return False
    else:
        logger.info("No target-owned Dask process running.")

    residual_after = _target_dask_processes(target)
    if residual_after:
        logger.error(
            "Target Dask process(es) remain after cleanup: %s", sorted(residual_after)
        )
        return False
    if ownership_uncertain:
        return False
    return _unlink_pid_files(evidence_files | stale_evidence)


def kill(
    target=None,
    exclude_pids=None,
    *,
    force_scan=False,
    home_path=None,
    cwd_path=None,
) -> bool:
    """Stop exact target-owned Dask processes, or all Dask processes when forced."""

    exclusions = set(exclude_pids or ())
    exclusions.add(os.getpid())
    if force_scan:
        return _force_kill(exclusions)
    if target is None:
        logger.error("Ordinary cleanup requires an exact worker runtime path")
        return False
    home = Path(home_path).expanduser() if home_path is not None else Path.home()
    cwd = Path(cwd_path).expanduser() if cwd_path is not None else Path.cwd()
    try:
        raw_target = Path(target).expanduser()
        if not raw_target.is_absolute():
            raw_target = cwd / raw_target
        target_path = safe_worker_runtime_cleanup_path(
            raw_target,
            roots=(home / "wenv", cwd / "wenv"),
            home_path=home,
            # Ordinary ``kill`` only signals identity-proven processes; it
            # never deletes the runtime directory.  Local cleanup launches
            # this bootstrap CLI with cwd equal to the target worker runtime,
            # so protecting cwd here would reject every production-shaped
            # scoped kill before ownership discovery.  Recursive ``clean``
            # keeps the stricter cwd protection above.
            cwd_path=None,
        )
    except (OSError, TypeError, ValueError) as exc:
        logger.error("Refusing unsafe AGILAB worker kill target: %s", exc)
        return False
    return _scoped_kill(target_path, exclusions)

def unzip(wenv=None):
    try:
        root = Path(wenv)  # ty: ignore[invalid-argument-type]
        root_src = root / 'src'
        logger.info(f"Ensuring src directory exists at {root_src}")
        root_src.mkdir(parents=True, exist_ok=True)
        eggs = list(root.glob('*.egg'))
        for e in eggs:
            logger.info(f"Extracting {e}")
            with zipfile.ZipFile(e) as zf:
                validate_archive_members_stay_within_dest(zf, root_src)
                zf.extractall(root_src)
        logger.info(f"Unzipped: {eggs}")
    except _UNZIP_EXCEPTIONS as e:
        # Report failure to the caller: the manager invokes this command over
        # SSH with check=True and must see a nonzero exit code instead of a
        # silently truncated/partial extraction.
        logger.error(f"Error during unzip: {e}")
        return False
    return True

# ---------------- fast threaded test ----------------
def _busy_work(iters: int) -> int:
    # Pure Python arithmetic to keep the GIL busy.
    x = 0
    for _ in range(iters):
        x = (x * 1664525 + 1013904223) & 0xFFFFFFFF
    return x

def _time_busy(iters: int) -> float:
    start = time.perf_counter()
    _busy_work(iters)
    return time.perf_counter() - start

def _choose_iters(target_s: float = BASELINE_TARGET_S) -> int:
    # Quick single-shot calibration to hit ~target_s for 1 thread.
    iters = 200_000
    t = _time_busy(iters)
    if t <= 0:
        return 5_000_000
    scale = target_s / t
    # Keep within reasonable bounds
    return max(50_000, min(20_000_000, int(iters * scale)))

def threaded(nthreads=2, iters=None) -> float:
    """Run a CPU-bound workload across n threads; return wall time."""
    if iters is None:
        iters = _choose_iters()
    logger.debug(f"threaded: nthreads={nthreads}, iters={iters} per thread")

    def worker():
        _busy_work(iters)

    threads = [threading.Thread(target=worker, name=f"Worker-{i}") for i in range(nthreads)]
    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    dt = time.perf_counter() - start
    logger.info(f"Threads={nthreads} wall={dt:.3f}s")
    return dt

def test_python_threads():
    logger.info("Testing Python threads for true parallelism")
    t1 = threaded(nthreads=1)
    t2 = threaded(nthreads=2)

    logger.info(f"Time with 1 thread: {t1:.3f} s")
    logger.info(f"Time with 2 threads: {t2:.3f} s")

    # If free-threaded, CPU-bound threads should reduce wall time noticeably.
    if t2 <= t1 * FREETHREADED_THRESHOLD:
        logger.info("Likely freethreaded (true parallelism!)")
    else:
        logger.info("Likely normal Python (GIL active)")

def python_version():
    arch = platform.machine().lower().replace('arm64', 'aarch64').replace('amd64', 'x86_64')
    sys_name = platform.system().lower()
    if sys_name == 'darwin':
        os_tag = 'macos'
    elif sys_name == 'windows':
        os_tag = 'windows'
    elif sys_name == 'linux':
        os_tag = 'linux'
    else:
        os_tag = sys_name

    version = platform.python_version()
    cache_tag = getattr(sys.implementation, "cache_tag", "")
    freethreaded = "+freethreaded" if "freethreaded" in cache_tag else ""
    tag = f"{sys.implementation.name}-{version}{freethreaded}-{os_tag}-{arch}-none"
    logger.info(tag)
    return tag


def _nvidia_smi_candidates():
    resolved = shutil.which("nvidia-smi")
    seen = set()
    if resolved:
        seen.add(resolved)
        yield resolved

    for candidate in _NVIDIA_SMI_CANDIDATES:
        if candidate in seen:
            continue
        seen.add(candidate)
        yield candidate


def _gpu_names_from_nvidia_smi(output: str) -> list[str]:
    names = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("GPU ") and ":" in line:
            line = line.split(":", 1)[1].strip()
        if " (UUID:" in line:
            line = line.split(" (UUID:", 1)[0].strip()
        names.append(line)
    return names


def _run_nvidia_smi_probe(executable: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [executable, "-L"],
        capture_output=True,
        check=False,
        text=True,
        timeout=RAPIDS_PROBE_TIMEOUT,
    )


def rapids_probe() -> dict:
    """Return a JSON-serialisable RAPIDS hardware capability probe."""
    attempts = []
    for executable in _nvidia_smi_candidates():
        try:
            result = _run_nvidia_smi_probe(executable)
        except _RAPIDS_PROBE_EXCEPTIONS as exc:
            attempts.append({"command": executable, "ok": False, "error": str(exc)})
            continue

        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        if result.returncode == 0 and stdout:
            return {
                "rapids_capable": True,
                "probe": "nvidia-smi",
                "command": executable,
                "gpus": _gpu_names_from_nvidia_smi(stdout),
            }
        attempts.append(
            {
                "command": executable,
                "ok": False,
                "returncode": result.returncode,
                "stderr": stderr[-500:],
            }
        )

    return {
        "rapids_capable": False,
        "probe": "nvidia-smi",
        "command": None,
        "gpus": [],
        "attempts": attempts,
    }

# ---------------- main ----------------
if __name__ == "__main__":
    if len(sys.argv) == 1:
        print(USAGE)
        sys.exit(1)

    cmd = sys.argv[1]
    args = sys.argv[2:]
    arg = args[0] if args else None
    exclude_pids = set()

    if cmd == "kill":
        if not arg:
            print("Missing worker runtime path for 'kill'\n" + USAGE)
            sys.exit(1)
        exclude_arg = args[1] if len(args) > 1 else None
        if exclude_arg:
            for pid_str in exclude_arg.split(","):
                try:
                    exclude_pids.add(int(pid_str))
                except ValueError:
                    logger.warning(f"Invalid PID to exclude: {pid_str}")
        if not kill(target=arg, exclude_pids=exclude_pids):
            sys.exit(1)

    elif cmd == "kill-force":
        if arg:
            for pid_str in arg.split(","):
                try:
                    exclude_pids.add(int(pid_str))
                except ValueError:
                    logger.warning(f"Invalid PID to exclude: {pid_str}")
        if not kill(exclude_pids=exclude_pids, force_scan=True):
            sys.exit(1)

    elif cmd in {"clean", "clean-force"}:
        if not arg:
            print("Missing argument for 'clean'\n" + USAGE)
            sys.exit(1)
        lease_token = args[1] if len(args) > 1 else None
        if not clean(
            wenv=arg,
            force_scratch=cmd == "clean-force",
            lease_token=lease_token,
        ):
            sys.exit(1)

    elif cmd == "target-lease-acquire":
        if len(args) < 2:
            print("Missing target/token for 'target-lease-acquire'\n" + USAGE)
            sys.exit(1)
        operation = args[2] if len(args) > 2 else "unknown"
        if not acquire_remote_target_lease(Path(args[0]), args[1], operation):
            sys.exit(1)

    elif cmd == "target-lease-release":
        if len(args) < 2:
            print("Missing target/token for 'target-lease-release'\n" + USAGE)
            sys.exit(1)
        if not release_remote_target_lease(Path(args[0]), args[1]):
            sys.exit(1)

    elif cmd == "target-lease-recover":
        if len(args) < 3:
            print("Missing target/token/recovery proof for 'target-lease-recover'\n" + USAGE)
            sys.exit(1)
        operation = args[3] if len(args) > 3 else "unknown"
        recovered_tokens = [item for item in args[2].split(",") if item]
        if not recover_remote_target_lease(
            Path(args[0]),
            args[1],
            recovered_tokens,
            operation,
        ):
            sys.exit(1)

    elif cmd == "unzip":
        if not arg:
            print("Missing argument for 'unzip'\n" + USAGE)
            sys.exit(1)
        if not unzip(wenv=arg):
            sys.exit(1)

    elif cmd == "threaded":
        test_python_threads()

    elif cmd == "platform":
        python_version()

    elif cmd == "rapids-probe":
        print(json.dumps(rapids_probe(), sort_keys=True))

    else:
        print(f"Unknown command: {cmd}\n{USAGE}")
        sys.exit(1)
