import asyncio
import getpass
import hashlib
import humanize
import importlib
import inspect
import json
import os
import pickle
import re
import stat
import subprocess
import sys
import traceback
import urllib.error
import urllib.request
import warnings
from datetime import timedelta
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, BinaryIO, Callable, List, Optional, cast

# NOTE: The capacity-model manifest is an *integrity* control, not an
# authenticity/signing control. It is an unsigned sha256 co-located with the
# model file, so it only detects accidental corruption or truncation of a
# pickle the operator already trusts on disk. It cannot prove *who* produced
# the model. Loading is additionally constrained to a trusted root, rejects
# unsafe owners or writable paths from the trusted root down on POSIX, and
# verifies Windows owner SID identity plus broad-principal DACL grants. The
# model is hashed and deserialized from one no-follow descriptor. These controls
# reduce the pickle-planting surface but do not prove who produced the model. Do
# not treat manifest verification alone as a defense against a tampered model.
CAPACITY_MODEL_MANIFEST_SCHEMA = "agilab.capacity_model_manifest.v1"
CAPACITY_MODEL_HASH_ALGORITHM = "sha256"
_WINDOWS_PRIVILEGED_TRUSTED_SIDS = frozenset(
    {
        "s-1-5-18",  # LocalSystem, the Windows equivalent of trusted uid 0
        "s-1-5-32-544",  # BUILTIN\\Administrators, privileged local root group
    }
)
# File/directory write rights, DELETE, WRITE_DAC, WRITE_OWNER, MAXIMUM_ALLOWED,
# GENERIC_ALL, and GENERIC_WRITE. These values are stable Win32 ACCESS_MASK bits
# and intentionally avoid importing pywin32 on non-Windows platforms.
_WINDOWS_UNSAFE_CAPACITY_ACCESS_MASK = (
    0x00000002
    | 0x00000004
    | 0x00000010
    | 0x00000040
    | 0x00000100
    | 0x00010000
    | 0x00040000
    | 0x00080000
    | 0x02000000
    | 0x10000000
    | 0x40000000
)
_WINDOWS_ACCESS_ALLOWED_ACE_TYPE = 0
_WINDOWS_ACCESS_ALLOWED_OBJECT_ACE_TYPE = 5
_WINDOWS_UNSUPPORTED_ACCESS_ALLOWED_ACE_TYPES = frozenset({4, 9, 11})
_CAPACITY_LOAD_EXCEPTIONS = (
    AttributeError,
    EOFError,
    ImportError,
    OSError,
    pickle.PickleError,
)
_SUPPORTED_INSTALL_WORKERS = {
    "AgiDataWorker": "pandas-worker",
    "PolarsWorker": "polars-worker",
    "PandasWorker": "pandas-worker",
    "FireducksWorker": "fireducks-worker",
    "DagWorker": "dag-worker",
}
_DERIVED_WORKER_BASES = {
    "Sb3TrainerWorker": "DagWorker",
}
_WORKER_RESOLUTION_EXCEPTIONS = (
    AttributeError,
    ImportError,
    ModuleNotFoundError,
)


def _sklearn_inconsistent_version_warning() -> type[Warning] | None:
    try:
        from sklearn.exceptions import InconsistentVersionWarning
    except Exception:
        # third-party optional dependency probe; absence keeps normal load behavior.
        return None
    return InconsistentVersionWarning
_RUN_TYPES = ["run --no-sync", "sync --dev", "sync --upgrade --dev", "simulate"]


def ensure_asyncio_run_signature(
    *,
    asyncio_module: Any = asyncio,
    inspect_signature_fn: Callable[..., Any] = inspect.signature,
) -> None:
    """Ensure ``asyncio.run`` accepts ``loop_factory`` when patched by pydevd."""
    current = asyncio_module.run
    try:
        params = inspect_signature_fn(current).parameters
    except (TypeError, ValueError):  # pragma: no cover - unable to introspect
        return
    if "loop_factory" in params:
        return
    if "pydevd" not in getattr(current, "__module__", ""):
        return

    original = current

    def _patched_run(
        main: Any,
        *,
        debug: Any = None,
        loop_factory: Callable[[], Any] | None = None,
    ) -> Any:
        if loop_factory is None:
            return original(main, debug=debug)

        loop = loop_factory()
        try:
            try:
                asyncio_module.set_event_loop(loop)
            except RuntimeError:
                pass
            if debug is not None:
                loop.set_debug(debug)
            return loop.run_until_complete(main)
        finally:
            try:
                loop.close()
            finally:
                try:
                    asyncio_module.set_event_loop(None)
                except RuntimeError:
                    pass

    asyncio_module.run = _patched_run


def agi_version_missing_on_pypi(project_path: Path) -> bool:
    """Return True when a pinned ``agi*``/``agilab`` dependency is missing on PyPI."""
    try:
        pyproject = project_path / "pyproject.toml"
        if not pyproject.exists():
            return False
        text = pyproject.read_text(encoding="utf-8", errors="ignore")
        deps = re.findall(
            r"^(?:\s*)(ag(?:i[-_].+|ilab))\s*=\s*[\"']([^\"']+)[\"']",
            text,
            flags=re.MULTILINE,
        )
        if not deps:
            return False
        pairs = []
        for name, spec in deps:
            match = re.match(r"^(?:==\s*)?(\d+(?:\.\d+){1,2})$", spec.strip())
            if match:
                pairs.append((name.replace("_", "-"), match.group(1)))
        if not pairs:
            return False
        pkg, ver = pairs[0]
        try:
            with urllib.request.urlopen(
                f"https://pypi.org/pypi/{pkg}/json", timeout=5
            ) as response:
                data = json.load(response)
            return ver not in data.get("releases", {})
        except (urllib.error.URLError, OSError, TimeoutError, ValueError):
            return False
    except (OSError, UnicodeError, ValueError):
        return False


def format_exception_chain(exc: BaseException) -> str:
    """Return a compact representation of an exception chain."""
    messages: List[str] = []
    norms: List[str] = []
    visited = set()
    current: Optional[BaseException] = exc

    def _normalize(text: str) -> str:
        text = text.strip()
        lowered = text.lower()
        for token in (
            "error:",
            "exception:",
            "warning:",
            "runtimeerror:",
            "valueerror:",
            "typeerror:",
        ):
            if lowered.startswith(token):
                return text[len(token) :].strip()
        if ": " in text:
            head, tail = text.split(": ", 1)
            if head.endswith(("Error", "Exception", "Warning")):
                return tail.strip()
        return text

    while current and id(current) not in visited:
        visited.add(id(current))
        tb_exc = traceback.TracebackException.from_exception(current)
        text = "".join(tb_exc.format_exception_only()).strip()
        if not text:
            text = f"{current.__class__.__name__}: {current}"
        if text:
            norm = _normalize(text)
            if messages:
                last_norm = norms[-1]
                norm = norm or text
                if norm == last_norm:
                    pass
                elif last_norm.endswith(norm):
                    messages[-1] = text
                    norms[-1] = norm
                elif not norm.endswith(last_norm):
                    messages.append(text)
                    norms.append(norm)
            else:
                messages.append(text)
                norms.append(norm if norm else text)

        if current.__cause__ is not None:
            current = current.__cause__
        elif current.__context__ is not None and not getattr(
            current, "__suppress_context__", False
        ):
            current = current.__context__
        else:
            break

    return " -> ".join(messages)


def load_capacity_predictor(
    model_path: Path,
    *,
    load_fn: Callable[[Any], Any] = pickle.load,
    retrain_fn: Optional[Callable[[], Any]] = None,
    log: Any = None,
    trusted_root: Path | None = None,
) -> Any:
    path = Path(model_path)
    if not path.is_file():
        if retrain_fn is not None:
            retrain_fn()
        return None

    if trusted_root is None:
        if log is not None:
            log.warning(
                "Refusing to load capacity model from %s without a trusted resource root",
                path,
            )
        if retrain_fn is not None:
            retrain_fn()
        return None

    path, root = _capacity_path_and_root(path, trusted_root)
    trust_error = _capacity_file_trust_error(
        path,
        root,
        label="model file",
    )
    if trust_error is not None:
        if log is not None:
            log.warning(
                "Refusing to load untrusted capacity model from %s: %s",
                path,
                trust_error,
            )
        if retrain_fn is not None:
            retrain_fn()
        return None
    model_stream, model_stat, open_error = _open_trusted_capacity_file(
        path,
        root,
        label="model file",
    )
    if open_error is not None or model_stream is None or model_stat is None:
        if log is not None:
            log.warning(
                "Refusing to load untrusted capacity model from %s: %s",
                path,
                open_error or "cannot open model file safely",
            )
        if retrain_fn is not None:
            retrain_fn()
        return None

    manifest_path = capacity_model_manifest_path(path)
    with model_stream:
        manifest_stream, _manifest_stat, manifest_open_error = (
            _open_trusted_capacity_file(
                manifest_path,
                root,
                label="model manifest",
            )
        )
        if manifest_open_error is not None or manifest_stream is None:
            manifest_error = manifest_open_error or "cannot open model manifest safely"
        else:
            with manifest_stream:
                manifest_error = _capacity_model_manifest_stream_error(
                    path,
                    model_stream,
                    model_stat,
                    manifest_stream,
                )

        if manifest_error is not None:
            if log is not None:
                log.warning(
                    "Refusing to load unverified capacity model from %s: %s",
                    path,
                    manifest_error,
                )
            if retrain_fn is not None:
                retrain_fn()
            return None

        try:
            inconsistent_version_warning = _sklearn_inconsistent_version_warning()
            with warnings.catch_warnings():
                if inconsistent_version_warning is not None:
                    warnings.filterwarnings(
                        "ignore",
                        category=inconsistent_version_warning,
                    )
                return load_fn(model_stream)
        except _CAPACITY_LOAD_EXCEPTIONS as exc:
            if log is not None:
                log.warning("Failed to load capacity model from %s: %s", path, exc)
            if retrain_fn is not None:
                retrain_fn()
            return None


def _posix_group_is_user_private(stat_result: os.stat_result) -> bool:
    """Return True when the file's group is the current user's private group.

    A "user-private group" (the common Linux default where each user has a
    same-named group with only that user as a member) is not a meaningful
    escalation surface, so group-write on such a group is tolerated. Any other
    (shared) group with write permission is rejected.
    """
    try:
        import grp
        import pwd

        euid = os.geteuid()
        user_record = pwd.getpwuid(euid)
        group_record = grp.getgrgid(stat_result.st_gid)
        primary_members = {
            record.pw_name
            for record in pwd.getpwall()
            if record.pw_gid == stat_result.st_gid
        }
        members = primary_members | set(group_record.gr_mem)
        # A private group must be provably usable by this user and nobody else.
        # ``gr_mem`` omits primary-group memberships, so both NSS views matter.
        return members == {user_record.pw_name}
    except (ImportError, KeyError, OSError, AttributeError):
        # Cannot verify group membership; treat as shared (not private).
        return False


def _windows_capacity_model_identities(
    model_path: Path,
) -> tuple[str, tuple[str, ...], str | None]:
    """Return the file SID, trusted process-token SIDs, and an owner label."""

    try:
        import win32api
        import win32con
        import win32security
    except ImportError as exc:
        raise RuntimeError(
            "pywin32 is required to verify capacity model ownership on Windows"
        ) from exc

    security_descriptor = win32security.GetFileSecurity(
        str(model_path),
        win32security.OWNER_SECURITY_INFORMATION,
    )
    owner_sid = security_descriptor.GetSecurityDescriptorOwner()
    if owner_sid is None:
        raise OSError("model file has no owner SID")

    token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(),
        win32con.TOKEN_QUERY,
    )
    try:
        current_sid, _attributes = win32security.GetTokenInformation(
            token,
            win32security.TokenUser,
        )
        token_owner = win32security.GetTokenInformation(
            token,
            win32security.TokenOwner,
        )
        default_owner_sid = (
            token_owner[0] if isinstance(token_owner, tuple) else token_owner
        )
        owner_sid_text = win32security.ConvertSidToStringSid(owner_sid)
        current_sid_text = win32security.ConvertSidToStringSid(current_sid)
        default_owner_sid_text = win32security.ConvertSidToStringSid(
            default_owner_sid
        )
    finally:
        token.Close()

    owner_label: str | None = None
    try:
        owner_name, owner_domain, _account_type = win32security.LookupAccountSid(
            None,
            owner_sid,
        )
        owner_label = (
            f"{owner_domain}\\{owner_name}" if owner_domain else owner_name
        )
    except Exception:
        # Best-effort diagnostic only; SID equality remains the trust decision.
        pass
    trusted_sids = tuple(dict.fromkeys((current_sid_text, default_owner_sid_text)))
    return owner_sid_text, trusted_sids, owner_label


def _windows_capacity_model_dacl_grants(
    model_path: Path,
) -> tuple[tuple[str, int], ...]:
    """Return access-allowed DACL grants as normalized SID/mask pairs."""

    try:
        import win32security
    except ImportError as exc:
        raise RuntimeError(
            "pywin32 is required to verify capacity model ACLs on Windows"
        ) from exc

    security_descriptor = win32security.GetFileSecurity(
        str(model_path),
        win32security.DACL_SECURITY_INFORMATION,
    )
    dacl = security_descriptor.GetSecurityDescriptorDacl()
    if dacl is None:
        raise OSError("security descriptor has a null DACL")
    if not dacl.IsValid():
        raise OSError("security descriptor has an invalid DACL")

    grants: list[tuple[str, int]] = []
    for index in range(dacl.GetAceCount()):
        ace = dacl.GetAce(index)
        if not isinstance(ace, tuple) or len(ace) < 3:
            raise OSError(f"DACL ACE {index} has an unsupported shape")
        header = ace[0]
        if not isinstance(header, tuple) or not header:
            raise OSError(f"DACL ACE {index} has an unsupported header")
        ace_type = int(header[0])
        if ace_type == _WINDOWS_ACCESS_ALLOWED_ACE_TYPE:
            sid_index = 2
        elif ace_type == _WINDOWS_ACCESS_ALLOWED_OBJECT_ACE_TYPE:
            if len(ace) < 5:
                raise OSError(f"DACL object ACE {index} has an unsupported shape")
            sid_index = 4
        elif ace_type in _WINDOWS_UNSUPPORTED_ACCESS_ALLOWED_ACE_TYPES:
            raise OSError(f"DACL access-allowed ACE type {ace_type} is unsupported")
        else:
            continue
        grants.append(
            (
                win32security.ConvertSidToStringSid(ace[sid_index]),
                int(ace[1]),
            )
        )
    return tuple(grants)


def _windows_capacity_model_dacl_error(
    model_path: Path,
    *,
    trusted_sids: tuple[str, ...],
    grants_fn: Callable[[Path], tuple[tuple[str, int], ...]] | None = None,
    label: str = "model file",
) -> str | None:
    """Reject unsafe grants outside the token and root-equivalent principals."""

    grant_provider = grants_fn or _windows_capacity_model_dacl_grants
    try:
        normalized_trusted_sids = _WINDOWS_PRIVILEGED_TRUSTED_SIDS | {
            sid.casefold() for sid in trusted_sids if sid
        }
        grants = grant_provider(model_path)
        for trustee_sid, access_mask in grants:
            if not isinstance(trustee_sid, str) or not isinstance(access_mask, int):
                raise ValueError("DACL grant has an invalid SID or access mask")
            if (
                trustee_sid.casefold() not in normalized_trusted_sids
                and access_mask & _WINDOWS_UNSAFE_CAPACITY_ACCESS_MASK
            ):
                return (
                    f"{label} grants unsafe write/delete access to untrusted Windows "
                    f"principal {trustee_sid}"
                )
    except Exception as exc:
        # Defensive third-party boundary: pywin32 and injected providers can
        # raise different exception types. Any incomplete ACL evaluation must
        # refuse pickle deserialization.
        return f"cannot verify {label} ACL on Windows: {exc}"
    return None


def _windows_capacity_model_owner_error(
    model_path: Path,
    *,
    identities_fn: Callable[[Path], tuple[str, tuple[str, ...], str | None]]
    | None = None,
    acl_grants_fn: Callable[[Path], tuple[tuple[str, int], ...]] | None = None,
    label: str = "model file",
) -> str | None:
    """Return a fail-closed error unless owner and DACL are trusted."""

    identity_provider = identities_fn or _windows_capacity_model_identities
    try:
        owner_sid, trusted_sids, owner_label = identity_provider(model_path)
    except Exception as exc:
        # pywin32 raises several exception types across versions. This boundary
        # must turn every lookup failure into refusal to deserialize the pickle.
        return f"cannot verify {label} ownership on Windows: {exc}"

    normalized_trusted_sids = {sid.casefold() for sid in trusted_sids if sid}
    if not owner_sid or not normalized_trusted_sids:
        return f"cannot verify {label} ownership on Windows: an owner SID is missing"
    if owner_sid.casefold() not in normalized_trusted_sids:
        owner = owner_label or owner_sid
        return f"{label} is owned by {owner}, not the current Windows token"
    return _windows_capacity_model_dacl_error(
        model_path,
        trusted_sids=tuple(normalized_trusted_sids),
        grants_fn=acl_grants_fn,
        label=label,
    )


def _is_windows() -> bool:
    return os.name == "nt"


def _capacity_path_and_root(model_path: Path, trusted_root: Path) -> tuple[Path, Path]:
    requested_root = Path(
        os.path.abspath(os.fspath(Path(trusted_root).expanduser()))
    )
    root = requested_root.resolve(strict=False)
    requested_path = Path(
        os.path.abspath(os.fspath(Path(model_path).expanduser()))
    )
    if requested_path.is_relative_to(requested_root):
        requested_path = root / requested_path.relative_to(requested_root)
    return requested_path, root


def _trusted_posix_owner_ids() -> set[int]:
    return {0, os.geteuid()}


def _posix_capacity_entry_error(
    stat_result: os.stat_result,
    *,
    label: str,
) -> str | None:
    if stat_result.st_uid not in _trusted_posix_owner_ids():
        return (
            f"{label} is owned by uid {stat_result.st_uid}, "
            "not the current user or root"
        )
    mode = stat_result.st_mode
    if mode & stat.S_IWOTH:
        return f"{label} is world-writable"
    if mode & stat.S_IWGRP and not _posix_group_is_user_private(stat_result):
        return f"{label} is group-writable by a shared group"
    return None


def _capacity_entry_error(
    path: Path,
    stat_result: os.stat_result,
    *,
    label: str,
) -> str | None:
    if _is_windows():
        return _windows_capacity_model_owner_error(path, label=label)
    return _posix_capacity_entry_error(stat_result, label=label)


def _capacity_file_trust_error(
    model_path: Path,
    trusted_root: Path,
    *,
    label: str,
) -> str | None:
    path = Path(model_path)
    root = Path(trusted_root)
    if not path.is_relative_to(root):
        return f"path is outside trusted resource root {root}"

    relative_path = path.relative_to(root)
    current = root
    ancestor_paths = [root]
    for part in relative_path.parts[:-1]:
        current /= part
        ancestor_paths.append(current)

    for ancestor in ancestor_paths:
        try:
            ancestor_stat = ancestor.stat(follow_symlinks=False)
        except OSError as exc:
            return f"cannot stat trusted ancestor {ancestor}: {exc}"
        if stat.S_ISLNK(ancestor_stat.st_mode):
            return f"trusted ancestor is a symlink: {ancestor}"
        if not stat.S_ISDIR(ancestor_stat.st_mode):
            return f"trusted ancestor is not a directory: {ancestor}"
        ancestor_error = _capacity_entry_error(
            ancestor,
            ancestor_stat,
            label=f"trusted ancestor {ancestor}",
        )
        if ancestor_error is not None:
            return ancestor_error

    try:
        stat_result = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        if label == "model manifest":
            return f"model manifest is missing: {path}"
        return f"{label} is missing: {path}"
    except OSError as exc:
        return f"cannot stat {label}: {exc}"
    if stat.S_ISLNK(stat_result.st_mode):
        return f"{label} is a symlink"
    if not stat.S_ISREG(stat_result.st_mode):
        return f"{label} is not a regular file"
    return _capacity_entry_error(path, stat_result, label=label)


def _capacity_model_trust_error(model_path: Path, trusted_root: Path) -> str | None:
    path, root = _capacity_path_and_root(model_path, trusted_root)
    return _capacity_file_trust_error(path, root, label="model file")


def _open_trusted_capacity_file(
    path: Path,
    trusted_root: Path,
    *,
    label: str,
) -> tuple[BinaryIO | None, os.stat_result | None, str | None]:
    trust_error = _capacity_file_trust_error(
        path,
        trusted_root,
        label=label,
    )
    if trust_error is not None:
        return None, None, trust_error

    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_BINARY", 0)
    fd: int | None = None
    stream: BinaryIO | None = None
    try:
        fd = os.open(path, flags)
        stream = os.fdopen(fd, "rb")
        fd = None
        descriptor_stat = os.fstat(stream.fileno())
        path_stat = path.stat(follow_symlinks=False)
        if not os.path.samestat(descriptor_stat, path_stat):
            stream.close()
            return None, None, f"{label} changed while it was being opened"
        if not stat.S_ISREG(descriptor_stat.st_mode):
            stream.close()
            return None, None, f"{label} is not a regular file"
        descriptor_error = _capacity_entry_error(
            path,
            descriptor_stat,
            label=label,
        )
        if descriptor_error is not None:
            stream.close()
            return None, None, descriptor_error
        return stream, descriptor_stat, None
    except (OSError, ValueError) as exc:
        if stream is not None:
            stream.close()
        elif fd is not None:
            os.close(fd)
        return None, None, f"cannot open {label} safely: {exc}"


def capacity_model_manifest_path(model_path: Path) -> Path:
    path = Path(model_path)
    return path.with_name(f"{path.name}.sha256.json")


def _capacity_model_sha256(model_path: Path) -> str:
    with open(Path(model_path).resolve(strict=False), "rb") as stream:
        return _capacity_model_sha256_stream(stream)


def _capacity_model_sha256_stream(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    stream.seek(0)
    try:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        return digest.hexdigest()
    finally:
        stream.seek(0)


def write_capacity_model_manifest(model_path: Path) -> Path:
    path = Path(model_path).resolve(strict=False)
    stat_result = path.stat()
    manifest_path = capacity_model_manifest_path(path)
    payload = {
        "schema": CAPACITY_MODEL_MANIFEST_SCHEMA,
        "model_file": path.name,
        "algorithm": CAPACITY_MODEL_HASH_ALGORITHM,
        "digest_sha256": _capacity_model_sha256(path),
        "size_bytes": stat_result.st_size,
    }
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def _capacity_model_manifest_stream_error(
    model_path: Path,
    model_stream: BinaryIO,
    model_stat: os.stat_result,
    manifest_stream: BinaryIO,
) -> str | None:
    path = Path(model_path)
    try:
        payload = json.loads(manifest_stream.read().decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return f"model manifest is unreadable: {exc}"

    if not isinstance(payload, dict):
        return "model manifest schema mismatch"
    if payload.get("schema") != CAPACITY_MODEL_MANIFEST_SCHEMA:
        return "model manifest schema mismatch"
    if payload.get("model_file") != path.name:
        return "model manifest file mismatch"
    if payload.get("algorithm") != CAPACITY_MODEL_HASH_ALGORITHM:
        return "model manifest algorithm mismatch"

    if payload.get("size_bytes") != model_stat.st_size:
        return "model manifest size mismatch"

    expected_digest = payload.get("digest_sha256")
    if not isinstance(expected_digest, str) or not expected_digest:
        return "model manifest digest missing"
    try:
        actual_digest = _capacity_model_sha256_stream(model_stream)
    except OSError as exc:
        return f"cannot hash model file for manifest verification: {exc}"
    if actual_digest != expected_digest:
        return "model manifest sha256 mismatch"
    return None


def _capacity_model_manifest_error(model_path: Path) -> str | None:
    requested_path = Path(model_path).expanduser()
    path, root = _capacity_path_and_root(requested_path, requested_path.parent)
    model_stream, model_stat, model_error = _open_trusted_capacity_file(
        path,
        root,
        label="model file",
    )
    if model_error is not None or model_stream is None or model_stat is None:
        return model_error or "cannot open model file safely"

    with model_stream:
        manifest_stream, _manifest_stat, manifest_error = (
            _open_trusted_capacity_file(
                capacity_model_manifest_path(path),
                root,
                label="model manifest",
            )
        )
        if manifest_error is not None or manifest_stream is None:
            return manifest_error or "cannot open model manifest safely"
        with manifest_stream:
            return _capacity_model_manifest_stream_error(
                path,
                model_stream,
                model_stat,
                manifest_stream,
            )


def bootstrap_capacity_predictor(
    agi_cls: Any,
    env: Any,
    *,
    retrain_fn: Optional[Callable[[], Any]] = None,
    load_fn: Callable[[Any], Any] = pickle.load,
    missing_log_message: str | None = None,
    log: Any = None,
) -> Any:
    agi_cls._capacity_data_file = env.resources_path / "balancer_df.csv"
    agi_cls._capacity_model_file = env.resources_path / "balancer_model.pkl"
    model_path = Path(agi_cls._capacity_model_file)
    predictor = load_capacity_predictor(
        model_path,
        load_fn=load_fn,
        retrain_fn=retrain_fn,
        log=log,
        trusted_root=env.resources_path,
    )
    agi_cls._capacity_predictor = predictor
    if (
        predictor is None
        and retrain_fn is None
        and missing_log_message
        and not model_path.is_file()
        and log is not None
    ):
        log.info(missing_log_message, model_path)
    return predictor


def _pure_path_from_text(value: str) -> PurePosixPath | PureWindowsPath:
    if "\\" in value or re.match(r"^[A-Za-z]:[\\/]", value):
        return PureWindowsPath(value)
    return PurePosixPath(value)


def _first_relative_data_path_segment(value: Any) -> str | None:
    if not isinstance(value, (str, os.PathLike)):
        return None
    raw = os.fspath(value)
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    path = _pure_path_from_text(text)
    if path.is_absolute():
        return None
    parts = tuple(part for part in path.parts if part not in {"", "."})
    if not parts or parts[0] == "..":
        return None
    return parts[0]


def _worker_data_path_module_candidates(
    *arg_maps: dict[str, Any] | None,
) -> set[str]:
    candidates: set[str] = set()
    for arg_map in arg_maps:
        if not isinstance(arg_map, dict):
            continue
        for key in ("data_in", "data_out"):
            segment = _first_relative_data_path_segment(arg_map.get(key))
            if segment:
                candidates.add(segment)
    return candidates


def normalize_workers_data_path(
    workers_data_path: str | None,
    *,
    args: dict[str, Any],
    worker_args: dict[str, Any] | None = None,
) -> str | None:
    """Return the workflow session root for module-scoped worker data paths."""
    if workers_data_path is None:
        return None
    text = str(workers_data_path).strip()
    if not text:
        return workers_data_path

    path = _pure_path_from_text(text)
    module_candidates = _worker_data_path_module_candidates(worker_args, args)
    if path.name not in module_candidates:
        return workers_data_path
    parent = path.parent
    if str(parent) in {"", "."}:
        return workers_data_path
    return str(parent)


def _absolute_workers_data_share_root(
    env: Any,
    workers_data_path: str,
) -> Path:
    share_root = Path(workers_data_path).expanduser()
    if not share_root.is_absolute():
        env_home = getattr(env, "home_abs", None)
        base = Path(env_home).expanduser() if env_home else Path.home()
        share_root = base / share_root
    try:
        return share_root.resolve(strict=False)
    except OSError:
        return Path(os.path.normpath(str(share_root)))


def _workers_data_path_can_rebind_env_share(
    env: Any,
    workers_data_path: str,
) -> bool:
    current_share = str(getattr(env, "AGI_CLUSTER_SHARE", "") or "").strip()
    if not current_share:
        return True
    workers_share_abs = _absolute_workers_data_share_root(env, workers_data_path)
    current_share_abs = _absolute_workers_data_share_root(env, current_share)
    try:
        workers_share_abs.relative_to(current_share_abs)
    except ValueError:
        return False
    return True


def _apply_workers_data_path_to_env(
    env: Any,
    workers_data_path: str | None,
) -> None:
    if env is None or workers_data_path is None:
        return
    share_text = str(workers_data_path).strip()
    if not share_text:
        return
    if not _workers_data_path_can_rebind_env_share(env, share_text):
        return

    workflow_data_root_abs = _absolute_workers_data_share_root(env, share_text)
    env.AGILAB_WORKFLOW_DATA_ROOT = share_text
    env.agi_workflow_data_root = share_text
    env.agi_workflow_data_root_abs = workflow_data_root_abs
    if isinstance(getattr(env, "envars", None), dict):
        env.envars["AGILAB_WORKFLOW_DATA_ROOT"] = share_text

    share_target_name_fn = getattr(env, "_share_target_name", None)
    if callable(share_target_name_fn):
        share_target_name = share_target_name_fn()
        env.share_target_name = share_target_name
        env.app_data_rel = workflow_data_root_abs / share_target_name
        env.dataframe_path = env.app_data_rel / "dataframe"


def initialize_runtime_state(
    agi_cls: Any,
    env: Any,
    *,
    workers: dict[str, int],
    verbose: int,
    rapids_enabled: bool,
    args: dict[str, Any],
    worker_args: dict[str, Any] | None = None,
    workers_data_path: str | None = None,
    args_transform_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    log: Any = None,
    log_message: str = "AGI instance created for target %s with verbosity %s",
) -> None:
    agi_cls.env = env
    agi_cls.target_path = env.manager_path
    agi_cls._target = env.target
    agi_cls._rapids_enabled = rapids_enabled
    if env.verbose > 0 and log is not None:
        log.info(log_message, env.target, env.verbose)

    agi_cls._args = args_transform_fn(args) if args_transform_fn is not None else args
    agi_cls._worker_args = worker_args if worker_args is not None else agi_cls._args
    agi_cls.verbose = verbose
    agi_cls._workers = workers
    agi_cls._workers_data_path = normalize_workers_data_path(
        workers_data_path,
        args=agi_cls._args,
        worker_args=agi_cls._worker_args,
    )
    _apply_workers_data_path_to_env(env, agi_cls._workers_data_path)
    agi_cls._run_time = {}


def configure_runtime_mode(
    agi_cls: Any,
    env: Any,
    mode: int | str | None,
    *,
    default_mode: int | None = None,
    invalid_type_message: str = "parameter <mode> must be an int or a string",
    require_dask: bool = False,
    dask_error_message: str = "AGI.serve requires Dask mode (include 'd' in mode)",
) -> int:
    if mode is None:
        if default_mode is None:
            raise ValueError(invalid_type_message)
        agi_cls._mode = default_mode
    elif isinstance(mode, str):
        pattern = r"^[dcrp]+$"
        if not re.fullmatch(pattern, mode.lower()):
            raise ValueError(
                "parameter <mode> must only contain the letters 'd', 'c', 'r', 'p'"
            )
        agi_cls._mode = env.mode2int(mode)
    elif isinstance(mode, int):
        agi_cls._mode = int(mode)
    else:
        raise ValueError(invalid_type_message)

    agi_cls._run_types = list(_RUN_TYPES)
    # Validate the whole mode against the supported bit space; masking first
    # (mode & _RUN_MASK) made the old check a tautology, letting e.g. mode=999
    # silently take the install/deploy path.
    supported_mode_bits = int(getattr(agi_cls, "_RAPIDS_SET", 0b111111))
    if agi_cls._mode < 0 or agi_cls._mode & ~supported_mode_bits:
        raise ValueError(f"mode {agi_cls._mode} not implemented")
    if require_dask and not (agi_cls._mode & agi_cls.DASK_MODE):
        raise ValueError(dask_error_message)
    return cast(int, agi_cls._mode)


def install_worker_groups() -> dict[str, str]:
    return dict(_SUPPORTED_INSTALL_WORKERS)


def resolve_install_worker_group(
    base_worker_cls: str | None,
    *,
    base_worker_module: str | None = None,
    agi_workers: dict[str, str] | None = None,
    import_module_fn: Callable[[str], Any] = importlib.import_module,
) -> str | None:
    if not base_worker_cls:
        return None

    worker_groups = dict(
        _SUPPORTED_INSTALL_WORKERS if agi_workers is None else agi_workers
    )
    resolved = worker_groups.get(base_worker_cls)
    if resolved is not None:
        return resolved

    alias = _DERIVED_WORKER_BASES.get(base_worker_cls)
    if alias is not None:
        return worker_groups.get(alias)

    if not base_worker_module:
        return None

    try:
        worker_module = import_module_fn(base_worker_module)
        worker_cls = getattr(worker_module, base_worker_cls)
    except _WORKER_RESOLUTION_EXCEPTIONS:
        return None

    for ancestor in getattr(worker_cls, "__mro__", ())[1:]:
        ancestor_name = getattr(ancestor, "__name__", "")
        if not ancestor_name:
            continue
        resolved = worker_groups.get(
            _DERIVED_WORKER_BASES.get(ancestor_name, ancestor_name)
        )
        if resolved is not None:
            return resolved

    return None


def configure_install_worker_group(
    agi_cls: Any,
    env: Any,
    *,
    agi_workers: dict[str, str] | None = None,
    import_module_fn: Callable[[str], Any] = importlib.import_module,
) -> str:
    worker_groups = dict(
        _SUPPORTED_INSTALL_WORKERS if agi_workers is None else agi_workers
    )
    agi_cls.agi_workers = worker_groups
    base_worker_cls = getattr(env, "base_worker_cls", None)
    if not base_worker_cls:
        target_worker_class = (
            getattr(env, "target_worker_class", None) or "<worker class>"
        )
        worker_path = getattr(env, "worker_path", None) or "<worker path>"
        supported = ", ".join(sorted(worker_groups.keys()))
        raise ValueError(
            f"Missing {target_worker_class} definition; expected {worker_path}. "
            f"Ensure the app worker exists and inherits from a supported base worker ({supported})."
        )
    worker_group = resolve_install_worker_group(
        base_worker_cls,
        base_worker_module=getattr(env, "_base_worker_module", None),
        agi_workers=worker_groups,
        import_module_fn=import_module_fn,
    )
    if worker_group is None:
        supported = ", ".join(sorted(worker_groups.keys()))
        raise ValueError(
            f"Unsupported base worker class '{base_worker_cls}'. Supported values: {supported}."
        )
    agi_cls.install_worker_group = [worker_group]
    return worker_group


def hardware_supports_rapids(
    *,
    run_fn: Callable[..., Any] | None = None,
    devnull: Any = subprocess.DEVNULL,
) -> bool:
    try:
        if run_fn is None:
            run_fn = subprocess.run
        run_fn(
            ["nvidia-smi"],
            stdout=devnull,
            stderr=devnull,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def should_install_pip(
    *,
    getuser_fn: Callable[[], str] = getpass.getuser,
    sys_prefix: str = sys.prefix,
) -> bool:
    return (
        str(getuser_fn()).startswith("T0")
        and not (Path(sys_prefix) / "Scripts/pip.exe").exists()
    )


def format_elapsed(
    seconds: float,
    *,
    precisedelta_fn: Callable[[timedelta], str] = humanize.precisedelta,
) -> str:
    return precisedelta_fn(timedelta(seconds=seconds))
