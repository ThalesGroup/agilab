from __future__ import annotations

import argparse
import errno
import hashlib
import importlib.util
import json
import os
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import unicodedata
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT.parent / "thales_agilab" / "docs" / "source"
DEFAULT_TARGET = REPO_ROOT / "docs" / "source"
DOCS_SOURCE_ENV = "AGILAB_DOCS_SOURCE"
DOCS_REPOSITORY_ENV = "DOCS_REPOSITORY"
STAMP_FILE_NAME = ".docs_source_mirror_stamp.json"
STAMP_FORMAT_VERSION = 3
LEGACY_FULL_TREE_STAMP_FORMAT_VERSION = 1
UNSAFE_PARTIAL_STAMP_FORMAT_VERSION = 2
STAMP_MANAGED_TARGET = "docs/source"
STAMP_SOURCE_HINT = "../thales_agilab/docs/source"
STAMP_SYNC_TOOL = "tools/sync_docs_source.py"
IGNORED_FILE_NAMES = {".DS_Store"}
IGNORED_DIR_NAMES = {"__pycache__", ".ipynb_checkpoints"}
PUBLIC_OWNED_EXCLUSIONS = frozenset(
    {
        "data/release_proof.toml",
        "data/ui_robot_evidence.json",
        "release-proof.rst",
    }
)
UI_ROBOT_EVIDENCE_PUBLIC_OWNED = "data/ui_robot_evidence.json"
RELEASE_REFRESHABLE_PUBLIC_OWNED = frozenset(
    {
        "data/release_proof.toml",
        "release-proof.rst",
    }
)
UI_ROBOT_REFRESHABLE_PUBLIC_OWNED = frozenset(
    {UI_ROBOT_EVIDENCE_PUBLIC_OWNED}
)
CANONICAL_DRIFT_NOT_CHECKED = (
    "canonical docs source unavailable; target integrity only; "
    "canonical drift NOT CHECKED"
)


@dataclass(frozen=True)
class SyncPlan:
    created: list[str]
    updated: list[str]
    deleted: list[str]
    target_root_identity: tuple[int, int] | None = None
    target_parent_identity: tuple[int, int] | None = None

    def has_changes(self) -> bool:
        return bool(self.created or self.updated or self.deleted)


@dataclass(frozen=True)
class CanonicalSourceConfiguration:
    path: Path
    origin: str
    required: bool


@dataclass(frozen=True)
class CanonicalMirrorAlignmentResult:
    status: str
    message: str
    checked: bool


@dataclass
class AppliedSyncJournal:
    created: dict[str, CreatedMutationIntent]
    updated: dict[str, UpdatedMutationIntent]
    deleted: dict[str, DeletedMutationIntent]
    staged: list[OwnedStagedArtifact] = field(default_factory=list)
    created_directories: dict[str, OwnedCreatedDirectory] = field(default_factory=dict)


@dataclass(frozen=True)
class CreatedMutationIntent:
    destination: Path
    installed_fingerprint: tuple[int, int, int, int, str]


@dataclass(frozen=True)
class UpdatedMutationIntent:
    destination: Path
    installed_fingerprint: tuple[int, int, int, int, str]
    prior_state: tuple[int, int, int, int]


@dataclass(frozen=True)
class DeletedMutationIntent:
    destination: Path
    prior_state: tuple[int, int, int, int]


@dataclass(frozen=True)
class OwnedStagedArtifact:
    destination: Path
    entry: str | Path
    fingerprint: tuple[int, int, int, int, str]


@dataclass(frozen=True)
class OwnedCreatedDirectory:
    destination: Path
    identity: tuple[int, int]


@dataclass(frozen=True)
class StampSnapshot:
    existed: bool
    content: bytes | None
    fingerprint: tuple[int, int, int, int, str] | None


@dataclass(frozen=True)
class PinnedMutationBoundary:
    target: Path
    target_fd: int
    stamp_parent_fd: int
    target_root_identity: tuple[int, int]
    target_parent_identity: tuple[int, int]


@dataclass(frozen=True)
class PinnedDestinationParent:
    directory_fd: int | None
    destination: Path
    leaf_name: str


def _should_include(rel_path: Path) -> bool:
    if _normalized_rel_path(rel_path) in PUBLIC_OWNED_EXCLUSIONS:
        return False
    return not any(
        part in IGNORED_DIR_NAMES or part in IGNORED_FILE_NAMES
        for part in rel_path.parts
    )


def _should_include_public_owned(rel_path: Path) -> bool:
    return _normalized_rel_path(rel_path) in PUBLIC_OWNED_EXCLUSIONS


def _should_include_legacy(rel_path: Path) -> bool:
    return not any(
        part in IGNORED_DIR_NAMES or part in IGNORED_FILE_NAMES
        for part in rel_path.parts
    )


def _normalized_rel_path(rel_path: Path) -> str:
    return unicodedata.normalize("NFC", rel_path.as_posix())


def _is_link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def _validate_tree_root(root: Path) -> Path:
    if not root.is_dir():
        raise ValueError(f"docs mirror tree is not a directory: {root}")
    if _is_link_like(root):
        raise ValueError(
            f"docs mirror tree root cannot be a symlink or junction: {root}"
        )
    return root.resolve()


def _build_manifest(
    root: Path,
    *,
    include: Callable[[Path], bool],
    portable_keys: bool = True,
) -> dict[str, Path]:
    root_resolved = _validate_tree_root(root)
    manifest: dict[str, Path] = {}
    portable_paths: dict[str, Path] = {}
    for path in sorted(root.rglob("*")):
        rel_path = path.relative_to(root)
        if not _should_include_legacy(rel_path):
            continue
        if _is_link_like(path):
            raise ValueError(
                f"docs mirror manifests do not allow symlinks or junctions: {path}"
            )
        metadata = path.lstat()
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(
                f"docs mirror manifests do not allow special filesystem entries: {path}"
            )
        if not path.resolve().is_relative_to(root_resolved):
            raise ValueError(f"docs mirror path escapes its declared root: {path}")
        if not include(rel_path):
            continue
        normalized = _normalized_rel_path(rel_path)
        key = normalized
        portable_key = normalized.casefold()
        previous = portable_paths.get(portable_key) if portable_keys else None
        if previous is not None and previous != path:
            raise ValueError(
                "docs mirror contains colliding portable case/Unicode paths: "
                f"{previous} and {path}"
            )
        if portable_keys:
            portable_paths[portable_key] = path
        manifest[key] = path
    return manifest


def build_manifest(root: Path) -> dict[str, Path]:
    return _build_manifest(root, include=_should_include)


def build_public_owned_manifest(root: Path) -> dict[str, Path]:
    return _build_manifest(root, include=_should_include_public_owned)


def _build_legacy_manifest(root: Path) -> dict[str, Path]:
    return _build_manifest(
        root,
        include=_should_include_legacy,
        portable_keys=False,
    )


def _build_full_manifest(root: Path) -> dict[str, Path]:
    return _build_manifest(root, include=_should_include_legacy)


def _same_file_content(left: Path, right: Path) -> bool:
    if left.stat().st_size != right.stat().st_size:
        return False
    return left.read_bytes() == right.read_bytes()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest_state_from_manifest(manifest: dict[str, Path]) -> dict[str, int | str]:
    digest = hashlib.sha256()
    for rel_path, path in sorted(manifest.items()):
        file_hash = _file_sha256(path)
        digest.update(rel_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
    return {
        "file_count": len(manifest),
        "digest_sha256": digest.hexdigest(),
    }


def _manifest_state(root: Path) -> dict[str, int | str]:
    return _manifest_state_from_manifest(build_manifest(root))


def _stable_manifest_state(
    root: Path,
    *,
    legacy: bool = False,
) -> dict[str, int | str]:
    capture = _legacy_manifest_state if legacy else _manifest_state
    before = capture(root)
    after = capture(root)
    if before != after:
        raise ValueError(f"docs tree changed while evidence was captured: {root}")
    return after


def _public_owned_state(root: Path) -> dict[str, int | str]:
    return _manifest_state_from_manifest(build_public_owned_manifest(root))


def _manifest_file_digests(manifest: dict[str, Path]) -> dict[str, str]:
    return {rel_path: _file_sha256(path) for rel_path, path in sorted(manifest.items())}


def _target_evidence_states(
    root: Path,
) -> tuple[dict[str, int | str], dict[str, int | str], dict[str, str]]:
    full_manifest = _build_full_manifest(root)
    public_manifest = {
        rel_path: path
        for rel_path, path in full_manifest.items()
        if rel_path in PUBLIC_OWNED_EXCLUSIONS
    }
    managed_manifest = {
        rel_path: path
        for rel_path, path in full_manifest.items()
        if rel_path not in PUBLIC_OWNED_EXCLUSIONS
    }
    return (
        _manifest_state_from_manifest(managed_manifest),
        _manifest_state_from_manifest(public_manifest),
        _manifest_file_digests(public_manifest),
    )


def _stable_target_evidence_states(
    root: Path,
) -> tuple[dict[str, int | str], dict[str, int | str], dict[str, str]]:
    before = _target_evidence_states(root)
    after = _target_evidence_states(root)
    if before != after:
        raise ValueError(
            f"docs mirror target changed while evidence was captured: {root}"
        )
    return after


def _legacy_manifest_state(root: Path) -> dict[str, int | str]:
    return _manifest_state_from_manifest(_build_legacy_manifest(root))


def stamp_path_for_target(target: Path) -> Path:
    return target.parent / STAMP_FILE_NAME


def _logical_target_identity(target: Path) -> str:
    return f"{target.parent.name}/{target.name}"


def _absolute_path(path: Path, *, base: Path) -> Path:
    expanded = path.expanduser()
    candidate = expanded if expanded.is_absolute() else base / expanded
    return Path(os.path.abspath(candidate))


def _resolve_configured_path(raw_value: str, *, repo_root: Path, key: str) -> Path:
    value = raw_value.strip()
    if not value:
        raise ValueError(f"{key} is configured but empty")
    return _absolute_path(Path(value), base=repo_root)


def _primary_git_checkout_root(repo_root: Path) -> Path | None:
    """Return the primary checkout that owns a linked worktree's common dir."""

    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--git-common-dir"],
            check=True,
            text=True,
            capture_output=True,
        )
    except (FileNotFoundError, NotADirectoryError, subprocess.CalledProcessError):
        return None
    raw_common_dir = completed.stdout.strip()
    if not raw_common_dir:
        return None
    common_dir = _absolute_path(Path(raw_common_dir), base=repo_root).resolve()
    if common_dir.name != ".git" or not common_dir.is_dir():
        return None
    checkout_root = common_dir.parent
    return checkout_root if checkout_root.is_dir() else None


def canonical_source_configuration(
    repo_root: Path = REPO_ROOT,
) -> CanonicalSourceConfiguration:
    repo_root = _absolute_path(repo_root, base=Path.cwd()).resolve()
    configured_source = os.environ.get(DOCS_SOURCE_ENV)
    if configured_source is not None:
        return CanonicalSourceConfiguration(
            path=_resolve_configured_path(
                configured_source,
                repo_root=repo_root,
                key=DOCS_SOURCE_ENV,
            ),
            origin=f"env:{DOCS_SOURCE_ENV}",
            required=True,
        )

    configured_repo = os.environ.get(DOCS_REPOSITORY_ENV)
    if configured_repo is not None:
        docs_repo = _resolve_configured_path(
            configured_repo,
            repo_root=repo_root,
            key=DOCS_REPOSITORY_ENV,
        )
        return CanonicalSourceConfiguration(
            path=_absolute_path(docs_repo / "docs" / "source", base=repo_root),
            origin=f"env:{DOCS_REPOSITORY_ENV}",
            required=True,
        )

    primary_checkout = _primary_git_checkout_root(repo_root)
    conventional_public_root = primary_checkout or repo_root
    return CanonicalSourceConfiguration(
        path=_absolute_path(
            conventional_public_root.parent / "thales_agilab" / "docs" / "source",
            base=repo_root,
        ),
        origin="default",
        required=False,
    )


def configured_canonical_source(repo_root: Path = REPO_ROOT) -> Path:
    return canonical_source_configuration(repo_root).path


def _stamp_payload(
    *,
    managed_target: str,
    target_state: dict[str, int | str],
    public_owned_state: dict[str, int | str],
    public_owned_files_sha256: dict[str, str],
    source_status: str,
    source_digest_sha256: str | None,
) -> dict[str, object]:
    return {
        "format_version": STAMP_FORMAT_VERSION,
        "managed_target": managed_target,
        "public_owned_exclusions": sorted(PUBLIC_OWNED_EXCLUSIONS),
        "source_hint": STAMP_SOURCE_HINT,
        "source_status": source_status,
        "source_digest_sha256": source_digest_sha256,
        "target_digest_sha256": target_state["digest_sha256"],
        "file_count": target_state["file_count"],
        "public_owned_digest_sha256": public_owned_state["digest_sha256"],
        "public_owned_file_count": public_owned_state["file_count"],
        "public_owned_files_sha256": public_owned_files_sha256,
        "sync_tool": STAMP_SYNC_TOOL,
    }


def _same_directory(left: Path, right: Path) -> bool:
    try:
        return left.samefile(right)
    except OSError as exc:
        raise ValueError(
            "unable to verify that canonical source and mirror target are distinct: "
            f"{left} vs {right}: {exc}"
        ) from exc


def _same_or_ancestor_directory(parent: Path, candidate: Path) -> bool:
    if not parent.exists() or not parent.is_dir():
        return False
    for path in (candidate, *candidate.parents):
        if not path.exists() or not path.is_dir():
            continue
        if _same_directory(parent, path):
            return True
    return False


def _ensure_disjoint_directories(source: Path, target: Path) -> None:
    source_resolved = source.resolve()
    target_resolved = target.resolve(strict=False)
    lexical_overlap = (
        source_resolved == target_resolved
        or source_resolved.is_relative_to(target_resolved)
        or target_resolved.is_relative_to(source_resolved)
    )
    identity_overlap = _same_or_ancestor_directory(
        source,
        target,
    ) or _same_or_ancestor_directory(target, source)
    if lexical_overlap or identity_overlap:
        raise ValueError(
            "canonical source and mirror target are the same directory or overlap; "
            f"got source={source} target={target}"
        )


def build_mirror_stamp(source: Path, target: Path) -> dict[str, object]:
    if not source.is_dir():
        raise ValueError(f"canonical source is not a directory: {source}")
    if not target.is_dir():
        raise ValueError(f"mirror target is not a directory: {target}")
    _ensure_disjoint_directories(source, target)

    source_state = _manifest_state(source)
    target_state, public_owned_state, public_owned_files = (
        _stable_target_evidence_states(target)
    )
    if _manifest_state(source) != source_state:
        raise ValueError(
            f"canonical docs source changed while evidence was captured: {source}"
        )
    if source_state != target_state:
        raise ValueError(
            "canonical source and managed mirror target differ; apply the complete "
            "sync plan before writing verified mirror evidence"
        )
    payload = _stamp_payload(
        managed_target=_logical_target_identity(target),
        target_state=target_state,
        public_owned_state=public_owned_state,
        public_owned_files_sha256=public_owned_files,
        source_status="verified",
        source_digest_sha256=str(source_state["digest_sha256"]),
    )
    return payload


def build_target_only_mirror_stamp(target: Path) -> dict[str, object]:
    if not target.is_dir():
        raise ValueError(f"mirror target is not a directory: {target}")
    target_state, public_owned_state, public_owned_files = (
        _stable_target_evidence_states(target)
    )
    payload = _stamp_payload(
        managed_target=_logical_target_identity(target),
        target_state=target_state,
        public_owned_state=public_owned_state,
        public_owned_files_sha256=public_owned_files,
        source_status="unavailable",
        source_digest_sha256=None,
    )
    return payload


def _read_regular_path_snapshot(
    path: Path,
    *,
    label: str,
) -> tuple[bytes, tuple[int, int, int, int, str]]:
    metadata_before = path.lstat()
    if _is_link_like(path) or not stat.S_ISREG(metadata_before.st_mode):
        raise ValueError(f"{label} path is not a regular file: {path}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        file_fd = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"unable to open regular {label} path {path}: {exc}") from exc
    try:
        opened = os.fstat(file_fd)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
            metadata_before.st_dev,
            metadata_before.st_ino,
        ):
            raise ValueError(f"{label} path changed while opened: {path}")
        chunks: list[bytes] = []
        while chunk := os.read(file_fd, 1024 * 1024):
            chunks.append(chunk)
        finished = os.fstat(file_fd)
    finally:
        os.close(file_fd)
    try:
        metadata_after = path.lstat()
    except FileNotFoundError as exc:
        raise ValueError(f"{label} path changed while read: {path}") from exc
    identity_before = (
        metadata_before.st_dev,
        metadata_before.st_ino,
        metadata_before.st_size,
        metadata_before.st_mtime_ns,
    )
    identity_after = (
        metadata_after.st_dev,
        metadata_after.st_ino,
        metadata_after.st_size,
        metadata_after.st_mtime_ns,
    )
    identity_finished = (
        finished.st_dev,
        finished.st_ino,
        finished.st_size,
        finished.st_mtime_ns,
    )
    if identity_after != identity_before or identity_finished != identity_before:
        raise ValueError(f"{label} path changed while read: {path}")
    content = b"".join(chunks)
    return content, (*identity_after, hashlib.sha256(content).hexdigest())


def _read_regular_path_bytes(path: Path, *, label: str) -> bytes:
    return _read_regular_path_snapshot(path, label=label)[0]


def _render_stamp_payload(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _stamp_parent(boundary: PinnedMutationBoundary) -> PinnedDestinationParent:
    stamp_path = stamp_path_for_target(boundary.target)
    return PinnedDestinationParent(
        directory_fd=boundary.stamp_parent_fd,
        destination=stamp_path,
        leaf_name=STAMP_FILE_NAME,
    )


def _read_regular_at(
    parent: PinnedDestinationParent,
    name: str | Path,
    *,
    label: str,
) -> tuple[bytes, tuple[int, int, int, int, str]]:
    if parent.directory_fd is None:
        raise ValueError(f"safe {label} access requires a pinned directory")
    metadata_before = os.stat(
        name,
        dir_fd=parent.directory_fd,
        follow_symlinks=False,
    )
    if not stat.S_ISREG(metadata_before.st_mode):
        raise ValueError(
            f"{label} path is not a regular file: "
            f"{parent.destination.parent / str(name)}"
        )
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    file_fd = os.open(name, flags, dir_fd=parent.directory_fd)
    try:
        opened = os.fstat(file_fd)
        before = (
            metadata_before.st_dev,
            metadata_before.st_ino,
            metadata_before.st_size,
            metadata_before.st_mtime_ns,
        )
        if (
            not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
            != before
        ):
            raise ValueError(f"{label} path changed while opened: {parent.destination}")
        chunks: list[bytes] = []
        while chunk := os.read(file_fd, 1024 * 1024):
            chunks.append(chunk)
        finished = os.fstat(file_fd)
    finally:
        os.close(file_fd)
    metadata_after = os.stat(
        name,
        dir_fd=parent.directory_fd,
        follow_symlinks=False,
    )
    after = (
        metadata_after.st_dev,
        metadata_after.st_ino,
        metadata_after.st_size,
        metadata_after.st_mtime_ns,
    )
    final = (
        finished.st_dev,
        finished.st_ino,
        finished.st_size,
        finished.st_mtime_ns,
    )
    if after != before or final != before:
        raise ValueError(f"{label} path changed while read: {parent.destination}")
    content = b"".join(chunks)
    return content, (*after, hashlib.sha256(content).hexdigest())


def _capture_regular_stamp(
    stamp_path: Path,
    *,
    boundary: PinnedMutationBoundary,
) -> StampSnapshot:
    parent = _stamp_parent(boundary)
    try:
        content, fingerprint = _read_regular_at(
            parent,
            parent.leaf_name,
            label="mirror stamp",
        )
    except FileNotFoundError:
        return StampSnapshot(False, None, None)
    return StampSnapshot(True, content, fingerprint)


def _write_bytes_atomically_at(
    parent: PinnedDestinationParent,
    content: bytes,
) -> None:
    if parent.directory_fd is None:
        raise ValueError("safe mirror stamp publication requires a pinned directory")
    # Reject an existing symlink, junction analogue, directory, or special file.
    try:
        _read_regular_at(parent, parent.leaf_name, label="mirror stamp")
    except FileNotFoundError:
        pass
    temporary_name: str | None = None
    temporary_fd: int | None = None
    for _attempt in range(32):
        candidate = f".{parent.leaf_name}.{secrets.token_hex(8)}.tmp"
        try:
            temporary_fd = os.open(
                candidate,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                0o644,
                dir_fd=parent.directory_fd,
            )
        except FileExistsError:
            continue
        temporary_name = candidate
        break
    if temporary_name is None or temporary_fd is None:
        raise OSError(errno.EEXIST, "unable to allocate mirror stamp temporary file")
    try:
        with os.fdopen(temporary_fd, "wb", closefd=True) as handle:
            temporary_fd = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(
            temporary_name,
            parent.leaf_name,
            src_dir_fd=parent.directory_fd,
            dst_dir_fd=parent.directory_fd,
        )
        temporary_name = None
    finally:
        if temporary_fd is not None:
            os.close(temporary_fd)
        if temporary_name is not None:
            try:
                os.unlink(temporary_name, dir_fd=parent.directory_fd)
            except FileNotFoundError:
                pass


def _write_stamp_payload(
    stamp_path: Path,
    payload: dict[str, object],
    *,
    boundary: PinnedMutationBoundary,
) -> None:
    if stamp_path != stamp_path_for_target(boundary.target):
        raise ValueError("mirror stamp path does not belong to the pinned target")
    _write_bytes_atomically_at(_stamp_parent(boundary), _render_stamp_payload(payload))


def _restore_stamp(
    boundary: PinnedMutationBoundary,
    baseline: StampSnapshot,
    *,
    owned_fingerprint: tuple[int, int, int, int, str] | None,
) -> None:
    stamp_path = stamp_path_for_target(boundary.target)
    current = _capture_regular_stamp(stamp_path, boundary=boundary)
    if current.fingerprint == baseline.fingerprint:
        return
    if owned_fingerprint is None or current.fingerprint != owned_fingerprint:
        raise ValueError(
            "mirror stamp changed concurrently; preserved the concurrent stamp"
        )
    parent = _stamp_parent(boundary)
    if baseline.existed:
        if baseline.content is None:
            raise ValueError(f"missing rollback content for stamp: {stamp_path}")
        _write_bytes_atomically_at(parent, baseline.content)
    else:
        os.unlink(parent.leaf_name, dir_fd=parent.directory_fd)
    restored = _capture_regular_stamp(stamp_path, boundary=boundary)
    if restored.existed != baseline.existed or restored.content != baseline.content:
        raise ValueError("mirror stamp rollback did not restore the exact prior bytes")


def _publish_verified_stamp(
    boundary: PinnedMutationBoundary,
    payload: dict[str, object],
    verify: Callable[[], tuple[bool, str]],
) -> tuple[int, int, int, int, str]:
    stamp_path = stamp_path_for_target(boundary.target)
    baseline = _capture_regular_stamp(stamp_path, boundary=boundary)
    expected = _render_stamp_payload(payload)
    owned_fingerprint: tuple[int, int, int, int, str] | None = None
    try:
        _assert_boundary_still_named(boundary)
        _write_stamp_payload(stamp_path, payload, boundary=boundary)
        published = _capture_regular_stamp(stamp_path, boundary=boundary)
        if published.content != expected or published.fingerprint is None:
            raise ValueError(
                "mirror stamp publication was substituted before ownership could be "
                "established"
            )
        owned_fingerprint = published.fingerprint
        ok, message = verify()
        if not ok:
            raise ValueError(f"published mirror stamp failed verification: {message}")
        _assert_boundary_still_named(boundary)
        final = _capture_regular_stamp(stamp_path, boundary=boundary)
        if final.content != expected or final.fingerprint != owned_fingerprint:
            raise ValueError("published mirror stamp changed during final verification")
        return owned_fingerprint
    except BaseException as exc:
        if owned_fingerprint is None:
            try:
                current = _capture_regular_stamp(stamp_path, boundary=boundary)
            except (OSError, ValueError):
                current = StampSnapshot(False, None, None)
            if current.content == expected and current.fingerprint is not None:
                owned_fingerprint = current.fingerprint
            elif current.fingerprint != baseline.fingerprint:
                raise RuntimeError(
                    "mirror stamp publication failed after a concurrent or substituted "
                    "stamp appeared; the unowned stamp was preserved"
                ) from exc
        if owned_fingerprint is not None:
            try:
                _restore_stamp(
                    boundary,
                    baseline,
                    owned_fingerprint=owned_fingerprint,
                )
            except (OSError, ValueError) as rollback_exc:
                raise RuntimeError(
                    "mirror stamp publication failed and rollback was incomplete: "
                    f"{rollback_exc}"
                ) from exc
        raise


def _build_mirror_stamp_at_boundary(
    source: Path,
    boundary: PinnedMutationBoundary,
    *,
    expected_public_owned_files: dict[str, str] | None = None,
) -> dict[str, object]:
    # Keep this invariant at the mutation boundary too.  Public callers normally
    # check it before opening the target, but an internal or future caller must
    # never be able to stamp a tree as its own canonical source.
    _ensure_disjoint_directories(source, boundary.target)
    source_state = _manifest_state(source)
    target_state, public_owned_state, public_owned_files = (
        _stable_target_evidence_states_at_boundary(boundary)
    )
    if _manifest_state(source) != source_state:
        raise ValueError(
            f"canonical docs source changed while evidence was captured: {source}"
        )
    if (
        expected_public_owned_files is not None
        and public_owned_files != expected_public_owned_files
    ):
        raise ValueError(
            "public-owned evidence changed during managed docs apply; refusing to "
            "publish a new mirror stamp"
        )
    if source_state != target_state:
        raise ValueError(
            "canonical source and managed mirror target differ; apply the complete "
            "sync plan before writing verified mirror evidence"
        )
    return _stamp_payload(
        managed_target=_logical_target_identity(boundary.target),
        target_state=target_state,
        public_owned_state=public_owned_state,
        public_owned_files_sha256=public_owned_files,
        source_status="verified",
        source_digest_sha256=str(source_state["digest_sha256"]),
    )


def _build_target_only_stamp_at_boundary(
    boundary: PinnedMutationBoundary,
) -> dict[str, object]:
    target_state, public_owned_state, public_owned_files = (
        _stable_target_evidence_states_at_boundary(boundary)
    )
    return _stamp_payload(
        managed_target=_logical_target_identity(boundary.target),
        target_state=target_state,
        public_owned_state=public_owned_state,
        public_owned_files_sha256=public_owned_files,
        source_status="unavailable",
        source_digest_sha256=None,
    )


def _verify_payload_at_boundary(
    boundary: PinnedMutationBoundary,
    payload: dict[str, object],
    *,
    source: Path | None,
    expected_public_owned_files: dict[str, str] | None = None,
) -> tuple[bool, str]:
    stamp = _capture_regular_stamp(
        stamp_path_for_target(boundary.target),
        boundary=boundary,
    )
    if stamp.content != _render_stamp_payload(payload):
        return False, "published stamp bytes do not match the intended payload"
    target_state, public_state, public_files = (
        _stable_target_evidence_states_at_boundary(boundary)
    )
    if (
        expected_public_owned_files is not None
        and public_files != expected_public_owned_files
    ):
        return False, "public-owned evidence changed during mirror stamp publication"
    expected = {
        "target_digest_sha256": target_state["digest_sha256"],
        "file_count": target_state["file_count"],
        "public_owned_digest_sha256": public_state["digest_sha256"],
        "public_owned_file_count": public_state["file_count"],
        "public_owned_files_sha256": public_files,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            return False, f"published mirror stamp has stale {key}"
    if source is not None:
        source_state = _manifest_state(source)
        if (
            payload.get("source_status") != "verified"
            or payload.get("source_digest_sha256") != source_state["digest_sha256"]
            or _manifest_state(source) != source_state
        ):
            return False, "published mirror stamp has stale verified source evidence"
    else:
        source_status = payload.get("source_status")
        source_digest = payload.get("source_digest_sha256")
        if source_status == "unavailable" and source_digest is not None:
            return False, "target-only mirror stamp has unexpected source provenance"
        if source_status == "verified" and not isinstance(source_digest, str):
            return False, "verified mirror stamp has incomplete source provenance"
        if source_status not in {"verified", "unavailable"}:
            return False, "mirror stamp has invalid source provenance"
    return True, "mirror stamp payload verified through the pinned mutation boundary"


def _write_mirror_stamp_at_boundary(
    source: Path,
    boundary: PinnedMutationBoundary,
    *,
    expected_public_owned_files: dict[str, str] | None = None,
) -> tuple[Path, tuple[int, int, int, int, str]]:
    payload = _build_mirror_stamp_at_boundary(
        source,
        boundary,
        expected_public_owned_files=expected_public_owned_files,
    )
    fingerprint = _publish_verified_stamp(
        boundary,
        payload,
        lambda: _verify_payload_at_boundary(
            boundary,
            payload,
            source=source,
            expected_public_owned_files=expected_public_owned_files,
        ),
    )
    return stamp_path_for_target(boundary.target), fingerprint


def write_mirror_stamp(source: Path, target: Path) -> Path:
    _ensure_disjoint_directories(source, target)
    with _pinned_mutation_boundary(target) as boundary:
        stamp_path, _fingerprint = _write_mirror_stamp_at_boundary(source, boundary)
    return stamp_path


def write_target_only_mirror_stamp(target: Path) -> Path:
    with _pinned_mutation_boundary(target) as boundary:
        payload = _build_target_only_stamp_at_boundary(boundary)
        _publish_verified_stamp(
            boundary,
            payload,
            lambda: _verify_payload_at_boundary(boundary, payload, source=None),
        )
    return stamp_path_for_target(target)


def _read_stamp(target: Path) -> tuple[dict[str, object] | None, str | None]:
    stamp_path = stamp_path_for_target(target)
    if not os.path.lexists(stamp_path):
        return None, f"missing mirror stamp: {stamp_path}"
    try:
        content = _read_regular_path_bytes(stamp_path, label="mirror stamp")
        stamp = json.loads(content.decode("utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeError, ValueError) as exc:
        return None, f"invalid mirror stamp {stamp_path}: {exc}"
    if not isinstance(stamp, dict):
        return None, f"invalid mirror stamp {stamp_path}: expected a JSON object"
    return stamp, None


def _validate_stamp_identity(
    stamp: dict[str, object],
    stamp_path: Path,
    target: Path,
) -> tuple[bool, str]:
    version = stamp.get("format_version")
    if version not in {
        LEGACY_FULL_TREE_STAMP_FORMAT_VERSION,
        UNSAFE_PARTIAL_STAMP_FORMAT_VERSION,
        STAMP_FORMAT_VERSION,
    }:
        return False, (
            f"unsupported mirror stamp format in {stamp_path}: {version!r}; "
            "regenerate with `python tools/sync_docs_source.py --apply --delete` "
            "when the canonical source is available, or "
            "`python tools/sync_docs_source.py --write-target-only-stamp` for "
            "explicit target-only evidence"
        )

    expected_managed_target = (
        STAMP_MANAGED_TARGET
        if version
        in {
            LEGACY_FULL_TREE_STAMP_FORMAT_VERSION,
            UNSAFE_PARTIAL_STAMP_FORMAT_VERSION,
        }
        else _logical_target_identity(target)
    )
    expected_identity = {
        "managed_target": expected_managed_target,
        "source_hint": STAMP_SOURCE_HINT,
        "sync_tool": STAMP_SYNC_TOOL,
    }
    for identity_field, expected in expected_identity.items():
        if stamp.get(identity_field) != expected:
            return False, (
                f"mirror stamp {identity_field} mismatch in {stamp_path}: expected "
                f"{expected!r}, got {stamp.get(identity_field)!r}"
            )

    if version != LEGACY_FULL_TREE_STAMP_FORMAT_VERSION:
        expected_exclusions = sorted(PUBLIC_OWNED_EXCLUSIONS)
        if stamp.get("public_owned_exclusions") != expected_exclusions:
            return False, (
                f"mirror stamp exclusions mismatch in {stamp_path}: expected "
                f"{expected_exclusions!r}, got {stamp.get('public_owned_exclusions')!r}"
            )
    return True, ""


def _validate_source_provenance(
    stamp: dict[str, object],
    stamp_path: Path,
) -> tuple[bool, str]:
    source_status = stamp.get("source_status")
    source_digest = stamp.get("source_digest_sha256")
    if source_status not in {"verified", "unavailable"}:
        return False, f"invalid source_status in {stamp_path}: {source_status!r}"
    if source_status == "verified":
        if not isinstance(source_digest, str) or not source_digest:
            return False, f"verified mirror stamp has no source digest: {stamp_path}"
        if source_digest != stamp.get("target_digest_sha256"):
            return False, (
                "verified mirror stamp records unequal source and managed-target "
                f"digests: {stamp_path}"
            )
    elif source_digest is not None:
        return False, (
            f"unavailable-source mirror stamp must use a null source digest: {stamp_path}"
        )
    return True, ""


def _validate_managed_target_state(
    stamp: dict[str, object],
    target: Path,
    state: dict[str, int | str],
) -> tuple[bool, str]:
    if stamp.get("file_count") != state["file_count"]:
        return False, (
            f"mirror stamp mismatch for {target}: expected managed file_count "
            f"{stamp.get('file_count')}, got {state['file_count']}"
        )
    if stamp.get("target_digest_sha256") != state["digest_sha256"]:
        return False, (
            f"mirror stamp mismatch for {target}: expected managed digest "
            f"{stamp.get('target_digest_sha256')}, got {state['digest_sha256']}"
        )
    return True, ""


def _stamp_object_from_snapshot(
    snapshot: StampSnapshot,
    stamp_path: Path,
) -> dict[str, object]:
    if not snapshot.existed or snapshot.content is None:
        raise ValueError(f"missing mirror stamp: {stamp_path}")
    try:
        stamp = json.loads(snapshot.content.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError(f"invalid mirror stamp {stamp_path}: {exc}") from exc
    if not isinstance(stamp, dict):
        raise ValueError(  # noqa: TRY004 - malformed evidence is a value error
            f"invalid mirror stamp {stamp_path}: expected a JSON object"
        )
    return stamp


def _validate_public_owned_rebaseline(
    stamp: dict[str, object],
    current_files: dict[str, str],
    *,
    stamp_path: Path,
    allowed_changes: frozenset[str],
) -> set[str]:
    previous_files = stamp.get("public_owned_files_sha256")
    if not isinstance(previous_files, dict) or not all(
        isinstance(path, str) and isinstance(digest, str)
        for path, digest in previous_files.items()
    ):
        raise ValueError(
            f"mirror stamp has no valid per-file public evidence: {stamp_path}"
        )
    changed_public_files = {
        path
        for path in set(previous_files) | set(current_files)
        if previous_files.get(path) != current_files.get(path)
    }
    forbidden_changes = sorted(changed_public_files - allowed_changes)
    if forbidden_changes:
        raise ValueError(
            "refusing to re-baseline public-owned evidence not allowed by this "
            "operation: " + ", ".join(forbidden_changes)
        )
    return changed_public_files


def _validate_ui_robot_evidence_at_boundary(
    boundary: PinnedMutationBoundary,
    *,
    expected_digest: str,
) -> None:
    evidence_path = boundary.target / UI_ROBOT_EVIDENCE_PUBLIC_OWNED
    with _pinned_destination_parent(
        boundary,
        evidence_path,
        create=False,
    ) as parent:
        content, fingerprint = _read_regular_at(
            parent,
            parent.leaf_name,
            label="UI robot evidence",
        )
    if fingerprint[-1] != expected_digest:
        raise ValueError(
            "UI robot evidence changed between target-state capture and validation"
        )
    validator_path = Path(__file__).with_name("ui_robot_evidence.py")
    validator_spec = importlib.util.spec_from_file_location(
        "agilab_ui_robot_evidence_validator",
        validator_path,
    )
    if validator_spec is None or validator_spec.loader is None:
        raise RuntimeError(
            f"unable to load UI robot evidence validator: {validator_path}"
        )
    validator = importlib.util.module_from_spec(validator_spec)
    validator_spec.loader.exec_module(validator)
    with tempfile.TemporaryDirectory(prefix="agilab-ui-robot-validation-") as temp:
        validation_path = Path(temp) / "ui_robot_evidence.json"
        validation_path.write_bytes(content)
        try:
            evidence = validator.load_evidence(validation_path)
        except (OSError, UnicodeError, ValueError) as exc:
            raise ValueError(f"invalid UI robot evidence: {exc}") from exc
    checks = validator.validate_evidence(evidence)
    failed_checks = [
        str(check.get("id") or "unknown")
        for check in checks
        if check.get("status") != "pass"
    ]
    if not checks or failed_checks:
        details = ", ".join(failed_checks) if failed_checks else "no checks returned"
        raise ValueError(f"UI robot evidence validation failed: {details}")


def _validate_existing_public_evidence_before_full_sync(
    boundary: PinnedMutationBoundary,
    stamp_snapshot: StampSnapshot,
) -> dict[str, str]:
    """Do not let a managed-tree sync bless unrelated public evidence drift."""

    _target_state, _public_state, public_files = (
        _stable_target_evidence_states_at_boundary(boundary)
    )
    if not stamp_snapshot.existed:
        return public_files
    stamp_path = stamp_path_for_target(boundary.target)
    stamp = _stamp_object_from_snapshot(stamp_snapshot, stamp_path)
    version = stamp.get("format_version")
    if version in {
        LEGACY_FULL_TREE_STAMP_FORMAT_VERSION,
        UNSAFE_PARTIAL_STAMP_FORMAT_VERSION,
    }:
        # A complete canonical sync is the documented migration path for legacy
        # stamps that did not carry safe per-file public evidence.
        return public_files
    if version != STAMP_FORMAT_VERSION:
        raise ValueError(
            f"unsupported mirror stamp format in {stamp_path}: {version!r}"
        )
    identity_ok, message = _validate_stamp_identity(
        stamp,
        stamp_path,
        boundary.target,
    )
    if not identity_ok:
        raise ValueError(message)
    provenance_ok, message = _validate_source_provenance(stamp, stamp_path)
    if not provenance_ok:
        raise ValueError(message)
    _validate_public_owned_rebaseline(
        stamp,
        public_files,
        stamp_path=stamp_path,
        allowed_changes=frozenset(),
    )
    return public_files


def _refresh_target_integrity_stamp(
    target: Path,
    *,
    allowed_changes: frozenset[str],
    operation_description: str,
    source: Path | None = None,
    required_existing_path: str | None = None,
    require_passing_ui_robot_evidence: bool = False,
) -> tuple[Path, bool]:
    with _pinned_mutation_boundary(target) as boundary:
        if source is not None:
            if not source.is_dir():
                raise ValueError(f"canonical docs source is not a directory: {source}")
            _ensure_disjoint_directories(source, boundary.target)
        stamp_path = stamp_path_for_target(boundary.target)
        previous = _capture_regular_stamp(stamp_path, boundary=boundary)
        stamp = _stamp_object_from_snapshot(previous, stamp_path)
        target_state, public_owned_state, public_owned_files = (
            _stable_target_evidence_states_at_boundary(boundary)
        )
        identity_ok, message = _validate_stamp_identity(
            stamp,
            stamp_path,
            boundary.target,
        )
        if not identity_ok or stamp.get("format_version") != STAMP_FORMAT_VERSION:
            raise ValueError(
                message
                or "mirror stamp has no complete per-file public evidence and cannot "
                "be refreshed safely; use a complete canonical sync or explicitly "
                "write target-only evidence"
            )
        provenance_ok, message = _validate_source_provenance(stamp, stamp_path)
        if not provenance_ok:
            raise ValueError(message)
        managed_ok, message = _validate_managed_target_state(
            stamp,
            boundary.target,
            target_state,
        )
        if not managed_ok:
            raise ValueError(
                message
                + "; refusing to re-baseline changed managed docs during "
                + operation_description
            )
        if source is not None:
            if stamp.get("source_status") != "verified":
                raise ValueError(
                    f"{operation_description} requires verified canonical-source "
                    f"provenance in {stamp_path}"
                )
            source_state = _stable_manifest_state(source)
            if (
                source_state["digest_sha256"] != stamp.get("source_digest_sha256")
                or source_state["file_count"] != stamp.get("file_count")
            ):
                raise ValueError(
                    f"canonical source drift for {source}: stamp expected digest "
                    f"{stamp.get('source_digest_sha256')} and file_count "
                    f"{stamp.get('file_count')}, got {source_state['digest_sha256']} "
                    f"and {source_state['file_count']}"
                )
            if source_state != target_state:
                raise ValueError(
                    "canonical source and managed mirror target differ; refusing "
                    f"{operation_description}"
                )
        changed_public_files = _validate_public_owned_rebaseline(
            stamp,
            public_owned_files,
            stamp_path=stamp_path,
            allowed_changes=allowed_changes,
        )
        if required_existing_path is not None:
            previous_files = stamp.get("public_owned_files_sha256")
            if (
                not isinstance(previous_files, dict)
                or required_existing_path not in previous_files
                or required_existing_path not in public_owned_files
            ):
                raise ValueError(
                    f"{operation_description} requires an existing stamped "
                    f"{required_existing_path} file; creation or deletion cannot be "
                    "re-baselined"
                )
            if changed_public_files not in (
                set(),
                {required_existing_path},
            ):
                raise ValueError(
                    f"{operation_description} may refresh only "
                    f"{required_existing_path}"
                )
        if require_passing_ui_robot_evidence:
            evidence_digest = public_owned_files.get(
                UI_ROBOT_EVIDENCE_PUBLIC_OWNED
            )
            if not isinstance(evidence_digest, str):
                raise ValueError(
                    "UI robot evidence refresh requires a captured evidence digest"
                )
            _validate_ui_robot_evidence_at_boundary(
                boundary,
                expected_digest=evidence_digest,
            )
        source_status = str(stamp["source_status"])
        raw_source_digest = stamp.get("source_digest_sha256")
        source_digest = (
            raw_source_digest if isinstance(raw_source_digest, str) else None
        )
        payload = _stamp_payload(
            managed_target=_logical_target_identity(boundary.target),
            target_state=target_state,
            public_owned_state=public_owned_state,
            public_owned_files_sha256=public_owned_files,
            source_status=source_status,
            source_digest_sha256=source_digest,
        )
        if previous.content == _render_stamp_payload(payload):
            ok, verification_message = _verify_payload_at_boundary(
                boundary,
                payload,
                source=source,
            )
            if not ok:
                raise ValueError(
                    "existing mirror stamp changed or became stale during refresh: "
                    + verification_message
                )
            _assert_boundary_still_named(boundary)
            final = _capture_regular_stamp(stamp_path, boundary=boundary)
            if (
                final.content != previous.content
                or final.fingerprint != previous.fingerprint
            ):
                raise ValueError("existing mirror stamp changed during no-op refresh")
            return stamp_path, False
        _publish_verified_stamp(
            boundary,
            payload,
            lambda: _verify_payload_at_boundary(
                boundary,
                payload,
                source=source,
            ),
        )
        # Verified provenance is intentionally preserved without re-reading the
        # canonical checkout; exact payload binding above prevents a downgrade.
        final = _capture_regular_stamp(stamp_path, boundary=boundary)
        if final.content != _render_stamp_payload(payload):
            raise ValueError("refreshed mirror stamp changed after publication")
        return stamp_path, True


def refresh_target_integrity_stamp(target: Path) -> tuple[Path, bool]:
    """Refresh release-proof integrity while preserving managed provenance.

    Only release-proof files may change during this refresh. Other public-owned
    evidence, including UI robot evidence, must still match its previous v3
    per-file digest. Missing, malformed, legacy-v1, or stale managed evidence
    fails closed and requires an explicit recovery operation.
    """

    return _refresh_target_integrity_stamp(
        target,
        allowed_changes=RELEASE_REFRESHABLE_PUBLIC_OWNED,
        operation_description="a release refresh",
    )


def refresh_ui_robot_evidence_stamp(
    source: Path,
    target: Path,
) -> tuple[Path, bool]:
    """Refresh only an existing UI-robot evidence digest.

    This operation requires live canonical-source alignment and verified v3
    provenance. It cannot create or delete the UI evidence file, bless managed
    docs drift, or re-baseline any other public-owned artifact.
    """

    return _refresh_target_integrity_stamp(
        target,
        allowed_changes=UI_ROBOT_REFRESHABLE_PUBLIC_OWNED,
        operation_description="a UI robot evidence refresh",
        source=source,
        required_existing_path=UI_ROBOT_EVIDENCE_PUBLIC_OWNED,
        require_passing_ui_robot_evidence=True,
    )


def _verify_target_stamp_once(
    target: Path,
) -> tuple[bool, str, dict[str, object] | None]:
    if not target.is_dir():
        return False, f"mirror target is not a directory: {target}", None
    if _is_link_like(target):
        return False, f"mirror target cannot be a symlink or junction: {target}", None
    stamp_path = stamp_path_for_target(target)
    stamp, error = _read_stamp(target)
    if stamp is None:
        return False, str(error), None
    identity_ok, identity_message = _validate_stamp_identity(stamp, stamp_path, target)
    if not identity_ok:
        return False, identity_message, stamp

    version = stamp.get("format_version")
    if version == LEGACY_FULL_TREE_STAMP_FORMAT_VERSION:
        try:
            state = _legacy_manifest_state(target)
        except (OSError, ValueError) as exc:
            return False, f"unable to verify mirror target {target}: {exc}", stamp
        if stamp.get("file_count") != state["file_count"]:
            return (
                False,
                (
                    f"legacy mirror stamp mismatch for {target}: expected file_count "
                    f"{stamp.get('file_count')}, got {state['file_count']}"
                ),
                stamp,
            )
        if stamp.get("target_digest_sha256") != state["digest_sha256"]:
            return (
                False,
                (
                    f"legacy mirror stamp mismatch for {target}: expected digest "
                    f"{stamp.get('target_digest_sha256')}, got {state['digest_sha256']}"
                ),
                stamp,
            )
        return True, f"legacy v1 mirror stamp integrity verified: {stamp_path}", stamp

    provenance_ok, provenance_message = _validate_source_provenance(stamp, stamp_path)
    if not provenance_ok:
        return False, provenance_message, stamp
    try:
        target_state, public_owned_state, public_owned_files = (
            _stable_target_evidence_states(target)
        )
    except (OSError, ValueError) as exc:
        return False, f"unable to verify mirror target {target}: {exc}", stamp
    managed_ok, managed_message = _validate_managed_target_state(
        stamp,
        target,
        target_state,
    )
    if not managed_ok:
        return False, managed_message, stamp
    if version == UNSAFE_PARTIAL_STAMP_FORMAT_VERSION:
        return (
            False,
            (
                f"legacy v2 mirror stamp does not cover public-owned evidence: {stamp_path}; "
                "run `python tools/sync_docs_source.py --apply --delete` with the "
                "canonical source, or explicitly recover target-only evidence with "
                "`python tools/sync_docs_source.py --write-target-only-stamp`"
            ),
            stamp,
        )

    if stamp.get("public_owned_file_count") != public_owned_state["file_count"]:
        return (
            False,
            (
                f"mirror stamp mismatch for {target}: expected public-owned file_count "
                f"{stamp.get('public_owned_file_count')}, got {public_owned_state['file_count']}"
            ),
            stamp,
        )
    if stamp.get("public_owned_digest_sha256") != public_owned_state["digest_sha256"]:
        return (
            False,
            (
                f"mirror stamp mismatch for {target}: expected public-owned digest "
                f"{stamp.get('public_owned_digest_sha256')}, got "
                f"{public_owned_state['digest_sha256']}"
            ),
            stamp,
        )
    if stamp.get("public_owned_files_sha256") != public_owned_files:
        return (
            False,
            (
                f"mirror stamp mismatch for {target}: expected per-file public-owned "
                f"digests {stamp.get('public_owned_files_sha256')!r}, got "
                f"{public_owned_files!r}"
            ),
            stamp,
        )
    return True, f"mirror stamp ok: {stamp_path}; target integrity verified", stamp


def _verify_target_stamp(
    target: Path,
) -> tuple[bool, str, dict[str, object] | None, StampSnapshot | None]:
    if not target.is_dir():
        return False, f"mirror target is not a directory: {target}", None, None
    if _is_link_like(target):
        return (
            False,
            f"mirror target cannot be a symlink or junction: {target}",
            None,
            None,
        )
    stamp_path = stamp_path_for_target(target)
    try:
        content_before, fingerprint_before = _read_regular_path_snapshot(
            stamp_path,
            label="mirror stamp",
        )
    except FileNotFoundError:
        return False, f"missing mirror stamp: {stamp_path}", None, None
    except (OSError, ValueError) as exc:
        return False, f"invalid mirror stamp {stamp_path}: {exc}", None, None
    baseline = StampSnapshot(True, content_before, fingerprint_before)
    ok, message, stamp = _verify_target_stamp_once(target)
    try:
        content_after, fingerprint_after = _read_regular_path_snapshot(
            stamp_path,
            label="mirror stamp",
        )
    except (FileNotFoundError, OSError, ValueError) as exc:
        return (
            False,
            f"mirror stamp changed while target evidence was verified: {exc}",
            stamp,
            baseline,
        )
    if content_after != content_before or fingerprint_after != fingerprint_before:
        return (
            False,
            "mirror stamp changed while target evidence was verified",
            stamp,
            baseline,
        )
    return ok, message, stamp, baseline


def _finish_stable_target_verification(
    target: Path,
    baseline: StampSnapshot,
    success_message: str,
    *,
    source: Path | None = None,
    source_baseline: dict[str, int | str] | None = None,
    legacy_source: bool = False,
) -> tuple[bool, str]:
    target_ok, target_message, _stamp, final = _verify_target_stamp(target)
    if not target_ok or final is None:
        return False, target_message
    if final.content != baseline.content or final.fingerprint != baseline.fingerprint:
        return False, "mirror stamp changed during read-only verification"
    if source is not None and source_baseline is not None:
        try:
            final_source = _stable_manifest_state(source, legacy=legacy_source)
        except (OSError, ValueError) as exc:
            return False, f"unable to verify canonical docs source {source}: {exc}"
        if final_source != source_baseline:
            return (
                False,
                f"canonical docs source changed during stamp verification: {source}",
            )
    return True, success_message


def verify_mirror_stamp(
    target: Path,
    source: Path | None = None,
    *,
    skip_missing_source: bool = False,
) -> tuple[bool, str]:
    target_ok, target_message, stamp, target_baseline = _verify_target_stamp(target)
    if not target_ok or stamp is None or target_baseline is None:
        return False, target_message

    if source is None:
        if not skip_missing_source:
            return False, (
                "canonical docs source was not supplied; rerun with a canonical "
                "--source or explicitly allow --skip-missing-source"
            )
        return _finish_stable_target_verification(
            target,
            target_baseline,
            f"{target_message}; {CANONICAL_DRIFT_NOT_CHECKED}: source path not supplied",
        )

    if not source.exists():
        if not skip_missing_source:
            return False, (
                f"canonical docs source not found: {source}; rerun with "
                "--skip-missing-source only when target-only integrity is intended"
            )
        return _finish_stable_target_verification(
            target,
            target_baseline,
            f"{target_message}; {CANONICAL_DRIFT_NOT_CHECKED}: {source}",
        )
    if not source.is_dir():
        return False, f"canonical docs source is not a directory: {source}"
    try:
        _ensure_disjoint_directories(source, target)
    except ValueError as exc:
        return False, str(exc)

    version = stamp.get("format_version")
    if version == LEGACY_FULL_TREE_STAMP_FORMAT_VERSION:
        if stamp.get("source_digest_sha256") != stamp.get("target_digest_sha256"):
            return False, (
                "legacy v1 mirror stamp recorded different canonical-source and "
                "target digests; it is valid only as target-integrity evidence"
            )
        try:
            source_state = _stable_manifest_state(source, legacy=True)
        except (OSError, ValueError) as exc:
            return False, f"unable to verify canonical docs source {source}: {exc}"
        expected_source_digest = stamp.get("source_digest_sha256")
        if expected_source_digest != source_state["digest_sha256"]:
            return False, (
                f"canonical source drift for {source}: legacy stamp expected digest "
                f"{expected_source_digest}, got {source_state['digest_sha256']}"
            )
        return _finish_stable_target_verification(
            target,
            target_baseline,
            f"{target_message}; canonical source matches legacy v1 evidence",
            source=source,
            source_baseline=source_state,
            legacy_source=True,
        )

    source_status = stamp.get("source_status")
    if source_status == "unavailable":
        return _finish_stable_target_verification(
            target,
            target_baseline,
            f"{target_message}; stamp source_status=unavailable; "
            f"{CANONICAL_DRIFT_NOT_CHECKED}",
        )

    try:
        source_state = _stable_manifest_state(source)
    except (OSError, ValueError) as exc:
        return False, f"unable to verify canonical docs source {source}: {exc}"
    source_digest = stamp.get("source_digest_sha256")
    if source_state["digest_sha256"] != source_digest:
        return False, (
            f"canonical source drift for {source}: stamp expected digest "
            f"{source_digest}, got {source_state['digest_sha256']}"
        )
    if source_state["file_count"] != stamp.get("file_count"):
        return False, (
            f"canonical source drift for {source}: stamp expected file_count "
            f"{stamp.get('file_count')}, got {source_state['file_count']}"
        )

    return _finish_stable_target_verification(
        target,
        target_baseline,
        f"{target_message}; canonical source verified: {source}",
        source=source,
        source_baseline=source_state,
    )


def verify_target_mirror_integrity(target: Path) -> tuple[bool, str]:
    """Verify only the checked-in public mirror and its stamped identity."""
    ok, message = verify_mirror_stamp(
        target,
        source=None,
        skip_missing_source=True,
    )
    if ok:
        return True, f"checked-in docs mirror target integrity verified: {target}"
    return False, message


def canonical_mirror_alignment_result(
    target: Path,
    source: Path,
    *,
    source_required: bool = False,
) -> CanonicalMirrorAlignmentResult:
    """Return alignment status plus whether a tree comparison completed."""
    if not source.exists():
        if source_required:
            return CanonicalMirrorAlignmentResult(
                "fail",
                f"configured canonical docs source not found: {source}",
                False,
            )
        return CanonicalMirrorAlignmentResult(
            "skipped",
            f"{CANONICAL_DRIFT_NOT_CHECKED}: {source}",
            False,
        )
    if not source.is_dir():
        return CanonicalMirrorAlignmentResult(
            "fail", f"canonical docs source is not a directory: {source}", False
        )
    if not target.is_dir():
        return CanonicalMirrorAlignmentResult(
            "fail", f"mirror target is not a directory: {target}", False
        )
    try:
        _ensure_disjoint_directories(source, target)
        source_state_before = _stable_manifest_state(source)
        target_state_before = _stable_manifest_state(target)
        plan = make_sync_plan(source, target, delete_extra=True)
        source_state_after_plan = _stable_manifest_state(source)
        target_state_after_plan = _stable_manifest_state(target)
    except (OSError, ValueError) as exc:
        return CanonicalMirrorAlignmentResult("fail", str(exc), False)
    if source_state_after_plan != source_state_before:
        return CanonicalMirrorAlignmentResult(
            "fail",
            f"canonical docs source changed during alignment verification: {source}",
            False,
        )
    if target_state_after_plan != target_state_before:
        return CanonicalMirrorAlignmentResult(
            "fail",
            f"docs mirror target changed during alignment verification: {target}",
            False,
        )
    if plan.has_changes():
        return CanonicalMirrorAlignmentResult(
            "fail",
            f"canonical source drift for {source}: create={len(plan.created)} "
            f"update={len(plan.updated)} delete={len(plan.deleted)}",
            True,
        )
    target_ok, target_message = verify_target_mirror_integrity(target)
    if not target_ok:
        return CanonicalMirrorAlignmentResult("fail", target_message, True)
    try:
        source_state_after_target = _stable_manifest_state(source)
        target_state_after_target = _stable_manifest_state(target)
    except (OSError, ValueError) as exc:
        return CanonicalMirrorAlignmentResult("fail", str(exc), False)
    if source_state_after_target != source_state_before:
        return CanonicalMirrorAlignmentResult(
            "fail",
            f"canonical docs source changed during alignment verification: {source}",
            False,
        )
    if target_state_after_target != target_state_before:
        return CanonicalMirrorAlignmentResult(
            "fail",
            f"docs mirror target changed during alignment verification: {target}",
            False,
        )
    return CanonicalMirrorAlignmentResult(
        "pass",
        f"canonical source and managed public mirror are aligned: {source}; "
        f"{target_message}",
        True,
    )


def verify_canonical_mirror_alignment(
    target: Path,
    source: Path,
    *,
    source_required: bool = False,
) -> tuple[str, str]:
    """Compatibility tuple for callers that do not need the checked signal."""
    result = canonical_mirror_alignment_result(
        target,
        source,
        source_required=source_required,
    )
    return result.status, result.message


def make_sync_plan(source: Path, target: Path, *, delete_extra: bool) -> SyncPlan:
    _ensure_disjoint_directories(source, target)
    source_manifest = build_manifest(source)
    target_manifest = build_manifest(target) if target.exists() else {}
    source_portable = {path.casefold(): path for path in source_manifest}
    target_portable = {path.casefold(): path for path in target_manifest}
    spelling_drift = sorted(
        (source_portable[key], target_portable[key])
        for key in source_portable.keys() & target_portable.keys()
        if source_portable[key] != target_portable[key]
    )
    if spelling_drift:
        details = ", ".join(
            f"source={source_path!r} target={target_path!r}"
            for source_path, target_path in spelling_drift
        )
        raise ValueError(
            "portable path spelling drift between canonical source and mirror target: "
            f"{details}; use a manual two-step rename through a temporary filename"
        )

    created = sorted(path for path in source_manifest if path not in target_manifest)
    updated = sorted(
        path
        for path in source_manifest
        if path in target_manifest
        and not _same_file_content(source_manifest[path], target_manifest[path])
    )
    deleted = (
        sorted(path for path in target_manifest if path not in source_manifest)
        if delete_extra
        else []
    )
    return SyncPlan(
        created=created,
        updated=updated,
        deleted=deleted,
        target_root_identity=_directory_identity(target) if target.exists() else None,
        target_parent_identity=(
            _directory_identity(target.parent) if target.exists() else None
        ),
    )


def make_stable_sync_plan(
    source: Path,
    target: Path,
    *,
    delete_extra: bool,
) -> SyncPlan:
    """Build a read-only plan bracketed by stable source and target evidence."""

    source_before = _stable_manifest_state(source)
    target_before = _stable_manifest_state(target) if target.exists() else None
    plan = make_sync_plan(source, target, delete_extra=delete_extra)
    source_after = _stable_manifest_state(source)
    target_after = _stable_manifest_state(target) if target.exists() else None
    if source_after != source_before:
        raise ValueError(f"canonical docs source changed while planning: {source}")
    if target_after != target_before:
        raise ValueError(f"docs mirror target changed while planning: {target}")
    return plan


def _regular_file_state(path: Path) -> tuple[int, int, int, int]:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"managed docs path is not a regular file: {path}")
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def _supports_pinned_directory_operations() -> bool:
    return os.name != "nt" and hasattr(os, "O_DIRECTORY")


def _directory_open_flags() -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    return flags


def _directory_identity_from_stat(metadata: os.stat_result) -> tuple[int, int]:
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("docs mirror boundary path is not a directory")
    return metadata.st_dev, metadata.st_ino


def _directory_identity(path: Path) -> tuple[int, int]:
    metadata = path.lstat()
    if _is_link_like(path) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"docs mirror boundary path is not a real directory: {path}")
    return _directory_identity_from_stat(metadata)


def _open_absolute_directory_no_follow(path: Path) -> int:
    """Open every component without following links and return the final fd."""

    absolute = _absolute_path(path, base=Path.cwd())
    if not absolute.is_absolute():  # pragma: no cover - _absolute_path guarantees it
        raise ValueError(f"docs mirror boundary path is not absolute: {absolute}")
    flags = _directory_open_flags()
    root = Path(absolute.anchor)
    current_fd = os.open(root, flags)
    try:
        for component in absolute.parts[1:]:
            next_fd = os.open(component, flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


@contextmanager
def _pinned_mutation_boundary(
    target: Path,
    *,
    expected_root_identity: tuple[int, int] | None = None,
    expected_parent_identity: tuple[int, int] | None = None,
) -> Iterator[PinnedMutationBoundary]:
    """Pin the target root and stamp parent for one complete mutation."""

    if not _supports_pinned_directory_operations():
        raise ValueError(
            "docs mirror mutation is unavailable on this platform: safe apply and "
            "stamp publication require POSIX handle-relative no-follow directory "
            "operations; check and verification remain available"
        )
    target_absolute = _absolute_path(target, base=Path.cwd())
    parent_fd: int | None = None
    target_fd: int | None = None
    try:
        parent_fd = _open_absolute_directory_no_follow(target_absolute.parent)
        parent_identity = _directory_identity_from_stat(os.fstat(parent_fd))
        target_fd = os.open(
            target_absolute.name,
            _directory_open_flags(),
            dir_fd=parent_fd,
        )
        root_identity = _directory_identity_from_stat(os.fstat(target_fd))
        if (
            expected_root_identity is not None
            and root_identity != expected_root_identity
        ):
            raise ValueError(
                "managed docs target root changed after planning; no changes were applied"
            )
        if (
            expected_parent_identity is not None
            and parent_identity != expected_parent_identity
        ):
            raise ValueError(
                "managed docs stamp parent changed after planning; no changes were applied"
            )
    except OSError as exc:
        if target_fd is not None:
            os.close(target_fd)
        if parent_fd is not None:
            os.close(parent_fd)
        raise ValueError(
            f"unable to pin docs mirror mutation boundary for {target_absolute}: {exc}"
        ) from exc
    except BaseException:
        if target_fd is not None:
            os.close(target_fd)
        if parent_fd is not None:
            os.close(parent_fd)
        raise

    try:
        yield PinnedMutationBoundary(
            target=target_absolute,
            target_fd=target_fd,
            stamp_parent_fd=parent_fd,
            target_root_identity=root_identity,
            target_parent_identity=parent_identity,
        )
    finally:
        os.close(target_fd)
        os.close(parent_fd)


def _assert_boundary_still_named(boundary: PinnedMutationBoundary) -> None:
    """Reject ancestor replacement while continuing to use pinned safe handles."""

    parent_fd: int | None = None
    target_fd: int | None = None
    try:
        parent_fd = _open_absolute_directory_no_follow(boundary.target.parent)
        if (
            _directory_identity_from_stat(os.fstat(parent_fd))
            != boundary.target_parent_identity
        ):
            raise ValueError(
                "managed docs stamp parent changed during the mutation; refusing "
                "to publish through a detached boundary"
            )
        target_fd = os.open(
            boundary.target.name,
            _directory_open_flags(),
            dir_fd=parent_fd,
        )
        if (
            _directory_identity_from_stat(os.fstat(target_fd))
            != boundary.target_root_identity
        ):
            raise ValueError(
                "managed docs target root changed during the mutation; refusing "
                "to publish through a detached boundary"
            )
    except OSError as exc:
        raise ValueError(
            "managed docs target ancestry changed during the mutation; refusing "
            f"to publish through a detached boundary: {exc}"
        ) from exc
    finally:
        if target_fd is not None:
            os.close(target_fd)
        if parent_fd is not None:
            os.close(parent_fd)


def _mkdir_owned_at(
    parent_fd: int,
    component: str,
    *,
    destination: Path,
    relative_path: Path,
    journal: AppliedSyncJournal | None,
) -> tuple[int, int] | None:
    """Create and journal a directory only after the mkdir syscall succeeds."""

    created_identity: tuple[int, int] | None = None

    def capture_created_identity() -> None:
        nonlocal created_identity
        created = os.stat(component, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISDIR(created.st_mode):
            raise ValueError(
                "managed docs destination parent was substituted after creation: "
                f"{destination.parent}"
            )
        created_identity = _directory_identity_from_stat(created)
        if journal is not None:
            journal.created_directories[_normalized_rel_path(relative_path)] = (
                OwnedCreatedDirectory(
                    destination=destination,
                    identity=created_identity,
                )
            )

    try:
        _mkdir_at(
            parent_fd,
            component,
            on_success=capture_created_identity,
        )
    except FileExistsError:
        return None
    return created_identity


def _mkdir_at(
    parent_fd: int,
    component: str,
    *,
    on_success: Callable[[], None],
) -> None:
    os.mkdir(component, mode=0o755, dir_fd=parent_fd)
    on_success()


@contextmanager
def _pinned_destination_parent(
    boundary: PinnedMutationBoundary,
    destination: Path,
    *,
    create: bool,
    journal: AppliedSyncJournal | None = None,
) -> Iterator[PinnedDestinationParent]:
    target_absolute = boundary.target
    destination_absolute = _absolute_path(destination, base=Path.cwd())
    try:
        relative = destination_absolute.relative_to(target_absolute)
    except ValueError as exc:
        raise ValueError(
            f"managed docs destination escapes target: {destination}"
        ) from exc
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError(f"invalid managed docs destination: {destination}")

    flags = _directory_open_flags()
    open_fds: list[int] = []
    try:
        current_fd = os.dup(boundary.target_fd)
        open_fds.append(current_fd)
        if not stat.S_ISDIR(os.fstat(current_fd).st_mode):
            raise ValueError(
                f"managed docs target is not a real directory: {target_absolute}"
            )

        traversed: list[str] = []
        for component in relative.parts[:-1]:
            traversed.append(component)
            created_identity: tuple[int, int] | None = None
            try:
                next_fd = os.open(component, flags, dir_fd=current_fd)
            except FileNotFoundError:
                if not create:
                    raise ValueError(
                        f"managed docs destination parent disappeared: {destination.parent}"
                    )
                created_path = boundary.target.joinpath(*traversed)
                created_identity = _mkdir_owned_at(
                    current_fd,
                    component,
                    destination=created_path,
                    relative_path=Path(*traversed),
                    journal=journal,
                )
                try:
                    next_fd = os.open(component, flags, dir_fd=current_fd)
                except OSError as exc:
                    raise ValueError(
                        "managed docs destination parent is not a real directory: "
                        f"{destination.parent}"
                    ) from exc
                if (
                    created_identity is not None
                    and _directory_identity_from_stat(os.fstat(next_fd))
                    != created_identity
                ):
                    os.close(next_fd)
                    raise ValueError(
                        "managed docs destination parent changed after creation: "
                        f"{destination.parent}"
                    )
            except OSError as exc:
                raise ValueError(
                    "managed docs destination parent is not a real directory: "
                    f"{destination.parent}"
                ) from exc
            open_fds.append(next_fd)
            current_fd = next_fd

        yield PinnedDestinationParent(
            directory_fd=current_fd,
            destination=destination_absolute,
            leaf_name=relative.parts[-1],
        )
    finally:
        for directory_fd in reversed(open_fds):
            try:
                os.close(directory_fd)
            except OSError:
                pass


def _build_manifest_at_boundary(
    boundary: PinnedMutationBoundary,
    *,
    include: Callable[[Path], bool] = _should_include,
) -> dict[str, Path]:
    manifest: dict[str, Path] = {}
    portable_paths: dict[str, Path] = {}

    def visit(directory_fd: int, relative_parent: Path) -> None:
        for name in sorted(os.listdir(directory_fd)):
            rel_path = relative_parent / name
            if not _should_include_legacy(rel_path):
                continue
            metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            mode = metadata.st_mode
            logical_path = boundary.target / rel_path
            if stat.S_ISLNK(mode):
                raise ValueError(
                    "docs mirror manifests do not allow symlinks or junctions: "
                    f"{logical_path}"
                )
            if stat.S_ISDIR(mode):
                child_fd = os.open(name, _directory_open_flags(), dir_fd=directory_fd)
                try:
                    visit(child_fd, rel_path)
                finally:
                    os.close(child_fd)
                continue
            if not stat.S_ISREG(mode):
                raise ValueError(
                    "docs mirror manifests do not allow special filesystem entries: "
                    f"{logical_path}"
                )
            if not include(rel_path):
                continue
            normalized = _normalized_rel_path(rel_path)
            portable_key = normalized.casefold()
            previous = portable_paths.get(portable_key)
            if previous is not None and previous != logical_path:
                raise ValueError(
                    "docs mirror contains colliding portable case/Unicode paths: "
                    f"{previous} and {logical_path}"
                )
            portable_paths[portable_key] = logical_path
            manifest[normalized] = logical_path

    visit(boundary.target_fd, Path())
    return manifest


def _manifest_state_at_boundary(
    boundary: PinnedMutationBoundary,
    manifest: dict[str, Path],
) -> dict[str, int | str]:
    digest = hashlib.sha256()
    for rel_path, destination in sorted(manifest.items()):
        with _pinned_destination_parent(
            boundary,
            destination,
            create=False,
        ) as parent:
            file_hash = _regular_file_fingerprint_at(parent, parent.leaf_name)[-1]
        digest.update(rel_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
    return {
        "file_count": len(manifest),
        "digest_sha256": digest.hexdigest(),
    }


def _target_evidence_states_at_boundary(
    boundary: PinnedMutationBoundary,
) -> tuple[dict[str, int | str], dict[str, int | str], dict[str, str]]:
    full_manifest = _build_manifest_at_boundary(
        boundary,
        include=_should_include_legacy,
    )
    public_manifest = {
        rel_path: path
        for rel_path, path in full_manifest.items()
        if rel_path in PUBLIC_OWNED_EXCLUSIONS
    }
    managed_manifest = {
        rel_path: path
        for rel_path, path in full_manifest.items()
        if rel_path not in PUBLIC_OWNED_EXCLUSIONS
    }
    public_files: dict[str, str] = {}
    for rel_path, destination in sorted(public_manifest.items()):
        with _pinned_destination_parent(
            boundary,
            destination,
            create=False,
        ) as parent:
            public_files[rel_path] = _regular_file_fingerprint_at(
                parent,
                parent.leaf_name,
            )[-1]
    return (
        _manifest_state_at_boundary(boundary, managed_manifest),
        _manifest_state_at_boundary(boundary, public_manifest),
        public_files,
    )


def _stable_target_evidence_states_at_boundary(
    boundary: PinnedMutationBoundary,
) -> tuple[dict[str, int | str], dict[str, int | str], dict[str, str]]:
    before = _target_evidence_states_at_boundary(boundary)
    after = _target_evidence_states_at_boundary(boundary)
    if before != after:
        raise ValueError(
            f"docs mirror target changed while evidence was captured: {boundary.target}"
        )
    return after


def _regular_file_state_at(
    parent: PinnedDestinationParent,
    name: str | Path,
) -> tuple[int, int, int, int]:
    if parent.directory_fd is None:
        raise ValueError(
            "safe docs mirror mutation requires a pinned destination directory"
        )
    metadata = os.stat(name, dir_fd=parent.directory_fd, follow_symlinks=False)
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(
            f"managed docs path is not a regular file: {parent.destination.parent / str(name)}"
        )
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def _regular_file_fingerprint_at(
    parent: PinnedDestinationParent,
    name: str | Path,
) -> tuple[int, int, int, int, str]:
    if parent.directory_fd is None:
        raise ValueError(
            "safe docs mirror mutation requires a pinned destination directory"
        )
    state_before = _regular_file_state_at(parent, name)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    file_fd = os.open(name, flags, dir_fd=parent.directory_fd)
    digest = hashlib.sha256()
    try:
        opened = os.fstat(file_fd)
        opened_state = (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
        )
        if opened_state != state_before or not stat.S_ISREG(opened.st_mode):
            raise ValueError(
                f"managed docs file changed while fingerprinted: {parent.destination}"
            )
        while chunk := os.read(file_fd, 1024 * 1024):
            digest.update(chunk)
        finished = os.fstat(file_fd)
        finished_state = (
            finished.st_dev,
            finished.st_ino,
            finished.st_size,
            finished.st_mtime_ns,
        )
    finally:
        os.close(file_fd)
    state_after = _regular_file_state_at(parent, name)
    if state_before != finished_state or state_after != state_before:
        raise ValueError(
            f"managed docs file changed while fingerprinted: {parent.destination}"
        )
    return (*state_after, digest.hexdigest())


def _stage_copy_at(
    source: Path,
    parent: PinnedDestinationParent,
    *,
    journal: AppliedSyncJournal,
    destination: Path,
) -> OwnedStagedArtifact:
    if parent.directory_fd is None:
        raise ValueError(
            "safe docs mirror mutation requires a pinned destination directory"
        )

    source_metadata = source.lstat()
    if not stat.S_ISREG(source_metadata.st_mode):
        raise ValueError(f"managed docs source is not a regular file: {source}")
    temporary_name: str | None = None
    temporary_fd: int | None = None
    for _attempt in range(32):
        candidate = f".{parent.leaf_name}.{secrets.token_hex(8)}.sync"
        try:
            temporary_fd = os.open(
                candidate,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                0o600,
                dir_fd=parent.directory_fd,
            )
        except FileExistsError:
            continue
        temporary_name = candidate
        break
    if temporary_name is None or temporary_fd is None:
        raise OSError(
            errno.EEXIST, "unable to allocate a unique docs sync staging file"
        )

    try:
        source_state_before = _regular_file_state(source)
        with (
            source.open("rb") as source_handle,
            os.fdopen(temporary_fd, "wb", closefd=True) as destination_handle,
        ):
            temporary_fd = None
            shutil.copyfileobj(source_handle, destination_handle)
            destination_handle.flush()
            os.fchmod(
                destination_handle.fileno(), stat.S_IMODE(source_metadata.st_mode)
            )
            os.fsync(destination_handle.fileno())
        source_state_after = _regular_file_state(source)
        if source_state_after != source_state_before:
            raise ValueError(f"managed docs source changed while staged: {source}")
        os.utime(
            temporary_name,
            ns=(source_metadata.st_atime_ns, source_metadata.st_mtime_ns),
            dir_fd=parent.directory_fd,
            follow_symlinks=False,
        )
        fingerprint = _regular_file_fingerprint_at(parent, temporary_name)
        # Ownership is recorded inside this helper so an injected exception
        # immediately after the helper returns cannot strand an unjournalled file.
        return _register_owned_staged_artifact(
            journal,
            destination=destination,
            entry=temporary_name,
            fingerprint=fingerprint,
        )
    except BaseException:
        if temporary_fd is not None:
            os.close(temporary_fd)
        try:
            os.unlink(temporary_name, dir_fd=parent.directory_fd)
        except FileNotFoundError:
            pass
        raise


def _unlink_at(
    parent: PinnedDestinationParent,
    name: str | Path,
    *,
    missing_ok: bool = False,
    on_success: Callable[[], None] | None = None,
) -> None:
    try:
        if parent.directory_fd is None:
            raise ValueError(
                "safe docs mirror mutation requires a pinned destination directory"
            )
        os.unlink(name, dir_fd=parent.directory_fd)
        if on_success is not None:
            on_success()
    except FileNotFoundError:
        if not missing_ok:
            raise


def _replace_at(
    parent: PinnedDestinationParent,
    source: str | Path,
    destination_name: str,
    *,
    on_success: Callable[[], None] | None = None,
) -> None:
    if parent.directory_fd is None:
        raise ValueError(
            "safe docs mirror mutation requires a pinned destination directory"
        )
    os.replace(
        source,
        destination_name,
        src_dir_fd=parent.directory_fd,
        dst_dir_fd=parent.directory_fd,
    )
    if on_success is not None:
        on_success()


def _link_no_replace_at(
    parent: PinnedDestinationParent,
    source: str | Path,
    destination_name: str,
    *,
    on_success: Callable[[], None] | None = None,
) -> None:
    if parent.directory_fd is None:
        raise ValueError(
            "safe docs mirror mutation requires a pinned destination directory"
        )
    os.link(
        source,
        destination_name,
        src_dir_fd=parent.directory_fd,
        dst_dir_fd=parent.directory_fd,
        follow_symlinks=False,
    )
    if on_success is not None:
        on_success()


def _fingerprint_or_none_at(
    parent: PinnedDestinationParent,
    name: str | Path,
) -> tuple[int, int, int, int, str] | None:
    try:
        return _regular_file_fingerprint_at(parent, name)
    except FileNotFoundError:
        return None


def _matches_prior_file_at(
    parent: PinnedDestinationParent,
    *,
    prior_state: tuple[int, int, int, int],
    backup: Path,
) -> bool:
    current = _fingerprint_or_none_at(parent, parent.leaf_name)
    return (
        current is not None
        and current[:4] == prior_state
        and current[-1] == _file_sha256(backup)
    )


def _register_owned_staged_artifact(
    journal: AppliedSyncJournal,
    *,
    destination: Path,
    entry: str | Path,
    fingerprint: tuple[int, int, int, int, str],
) -> OwnedStagedArtifact:
    artifact = OwnedStagedArtifact(destination, entry, fingerprint)
    journal.staged.append(artifact)
    return artifact


def _forget_owned_staged_artifact(
    journal: AppliedSyncJournal,
    artifact: OwnedStagedArtifact,
) -> None:
    if artifact in journal.staged:
        journal.staged.remove(artifact)


def _cleanup_owned_staged_artifact_at(
    parent: PinnedDestinationParent,
    artifact: OwnedStagedArtifact,
    journal: AppliedSyncJournal,
) -> None:
    current = _fingerprint_or_none_at(parent, artifact.entry)
    if current is None:
        _forget_owned_staged_artifact(journal, artifact)
        return
    if current != artifact.fingerprint:
        raise ValueError(
            "docs sync staging path changed concurrently; preserved: "
            f"{artifact.destination.parent / str(artifact.entry)}"
        )
    try:
        _unlink_at(parent, artifact.entry)
    except BaseException:
        if _fingerprint_or_none_at(parent, artifact.entry) is None:
            _forget_owned_staged_artifact(journal, artifact)
        raise
    _forget_owned_staged_artifact(journal, artifact)


def _assert_file_precondition_at(
    parent: PinnedDestinationParent,
    expected_state: tuple[int, int, int, int],
    backup: Path | None,
) -> None:
    current_state = _regular_file_state_at(parent, parent.leaf_name)
    if current_state != expected_state:
        raise ValueError(
            f"managed mirror changed after planning: {parent.destination}; refusing "
            "to overwrite concurrent state"
        )
    if backup is not None:
        current_fingerprint = _regular_file_fingerprint_at(parent, parent.leaf_name)
        if current_fingerprint[-1] != _file_sha256(backup):
            raise ValueError(
                f"managed mirror content changed after planning: {parent.destination}; "
                "refusing to overwrite concurrent state"
            )


def _apply_sync_plan_safely(
    source: Path,
    boundary: PinnedMutationBoundary,
    plan: SyncPlan,
    *,
    preconditions: dict[str, tuple[Path, tuple[int, int, int, int], Path | None]],
    journal: AppliedSyncJournal,
) -> None:
    source_manifest = build_manifest(source)
    target = boundary.target
    target_manifest = _build_manifest_at_boundary(boundary)
    _assert_boundary_still_named(boundary)

    for rel_path in plan.created:
        _assert_boundary_still_named(boundary)
        source_path = source_manifest.get(rel_path)
        if source_path is None:
            raise ValueError(f"planned canonical source file disappeared: {rel_path}")
        destination = target / source_path.relative_to(source)
        with _pinned_destination_parent(
            boundary,
            destination,
            create=True,
            journal=journal,
        ) as parent:
            artifact = _stage_copy_at(
                source_path,
                parent,
                journal=journal,
                destination=destination,
            )
            temporary = artifact.entry
            fingerprint = artifact.fingerprint
            try:
                try:
                    _link_no_replace_at(
                        parent,
                        temporary,
                        parent.leaf_name,
                        on_success=lambda rel_path=rel_path, destination=destination, fingerprint=fingerprint: (
                            journal.created.__setitem__(
                                rel_path,
                                CreatedMutationIntent(destination, fingerprint),
                            )
                        ),
                    )
                except FileExistsError as exc:
                    raise ValueError(
                        f"managed mirror path appeared after planning: {destination}; "
                        "refusing to overwrite concurrent state"
                    ) from exc
            finally:
                _cleanup_owned_staged_artifact_at(parent, artifact, journal)

    for rel_path in plan.updated:
        _assert_boundary_still_named(boundary)
        source_path = source_manifest.get(rel_path)
        destination = target_manifest.get(rel_path)
        if source_path is None or destination is None or rel_path not in preconditions:
            raise ValueError(f"managed mirror changed after planning: {rel_path}")
        expected_path, expected_state, backup = preconditions[rel_path]
        if destination != expected_path:
            raise ValueError(f"managed mirror path identity changed: {rel_path}")
        with _pinned_destination_parent(boundary, destination, create=False) as parent:
            artifact = _stage_copy_at(
                source_path,
                parent,
                journal=journal,
                destination=destination,
            )
            temporary = artifact.entry
            fingerprint = artifact.fingerprint
            try:
                _assert_file_precondition_at(parent, expected_state, backup)
                _replace_at(
                    parent,
                    temporary,
                    parent.leaf_name,
                    on_success=lambda rel_path=rel_path, destination=destination, fingerprint=fingerprint, expected_state=expected_state: (
                        journal.updated.__setitem__(
                            rel_path,
                            UpdatedMutationIntent(
                                destination,
                                fingerprint,
                                expected_state,
                            ),
                        )
                    ),
                )
            finally:
                _cleanup_owned_staged_artifact_at(parent, artifact, journal)

    for rel_path in plan.deleted:
        _assert_boundary_still_named(boundary)
        destination = target_manifest.get(rel_path)
        if destination is None or rel_path not in preconditions:
            raise ValueError(f"managed mirror changed after planning: {rel_path}")
        expected_path, expected_state, backup = preconditions[rel_path]
        if destination != expected_path:
            raise ValueError(f"managed mirror path identity changed: {rel_path}")
        with _pinned_destination_parent(boundary, destination, create=False) as parent:
            _assert_file_precondition_at(parent, expected_state, backup)
            _unlink_at(
                parent,
                parent.leaf_name,
                on_success=lambda rel_path=rel_path, destination=destination, expected_state=expected_state: (
                    journal.deleted.__setitem__(
                        rel_path,
                        DeletedMutationIntent(destination, expected_state),
                    )
                ),
            )


def apply_sync_plan(source: Path, target: Path, plan: SyncPlan) -> None:
    with _pinned_mutation_boundary(
        target,
        expected_root_identity=plan.target_root_identity,
        expected_parent_identity=plan.target_parent_identity,
    ) as boundary:
        target_manifest = _build_manifest_at_boundary(boundary)
        preconditions: dict[
            str,
            tuple[Path, tuple[int, int, int, int], Path | None],
        ] = {}
        for rel_path in plan.updated + plan.deleted:
            destination = target_manifest.get(rel_path)
            if destination is None:
                continue
            with _pinned_destination_parent(
                boundary,
                destination,
                create=False,
            ) as parent:
                state = _regular_file_state_at(parent, parent.leaf_name)
            preconditions[rel_path] = (destination, state, None)
        journal = AppliedSyncJournal(created={}, updated={}, deleted={})
        _apply_sync_plan_safely(
            source,
            boundary,
            plan,
            preconditions=preconditions,
            journal=journal,
        )


@contextmanager
def managed_source_snapshot(source: Path) -> Iterator[Path]:
    """Yield an immutable, normalized snapshot of the managed canonical tree.

    The state is hashed before and after copying. A concurrent source mutation
    therefore fails before the public mirror is touched instead of producing a
    stamp assembled from different source moments.
    """

    source_manifest = build_manifest(source)
    source_state_before = _manifest_state_from_manifest(source_manifest)
    with tempfile.TemporaryDirectory(prefix="agilab-docs-source-") as temporary:
        snapshot = Path(temporary) / "source"
        snapshot.mkdir()
        for _normalized_path, source_path in sorted(source_manifest.items()):
            # Keep the canonical case-preserving path spelling in the snapshot.
            # Case-folded identities are used only to reject portability collisions.
            destination = snapshot / source_path.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination)

        snapshot_state = _manifest_state(snapshot)
        source_state_after = _manifest_state(source)
        if (
            snapshot_state != source_state_before
            or source_state_after != source_state_before
        ):
            raise ValueError(
                "canonical docs source changed while its sync snapshot was being "
                "captured; no mirror changes were applied"
            )
        yield snapshot


def _backup_regular_file_at(
    parent: PinnedDestinationParent,
    backup_path: Path,
) -> tuple[int, int, int, int]:
    if parent.directory_fd is None:
        raise ValueError("rollback backup requires a pinned destination directory")
    metadata_before = os.stat(
        parent.leaf_name,
        dir_fd=parent.directory_fd,
        follow_symlinks=False,
    )
    if not stat.S_ISREG(metadata_before.st_mode):
        raise ValueError(
            f"managed docs path is not a regular file: {parent.destination}"
        )
    content, fingerprint = _read_regular_at(
        parent,
        parent.leaf_name,
        label="managed docs file",
    )
    metadata_after = os.stat(
        parent.leaf_name,
        dir_fd=parent.directory_fd,
        follow_symlinks=False,
    )
    if fingerprint[:4] != (
        metadata_after.st_dev,
        metadata_after.st_ino,
        metadata_after.st_size,
        metadata_after.st_mtime_ns,
    ) or stat.S_IMODE(metadata_before.st_mode) != stat.S_IMODE(metadata_after.st_mode):
        raise ValueError(
            f"managed docs file metadata changed while backed up: {parent.destination}"
        )
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path.write_bytes(content)
    backup_path.chmod(stat.S_IMODE(metadata_before.st_mode))
    os.utime(
        backup_path,
        ns=(metadata_before.st_atime_ns, metadata_before.st_mtime_ns),
    )
    if hashlib.sha256(backup_path.read_bytes()).hexdigest() != fingerprint[-1]:
        raise ValueError(f"rollback backup verification failed: {backup_path}")
    return fingerprint[:4]


def _rollback_sync_plan(
    boundary: PinnedMutationBoundary,
    journal: AppliedSyncJournal,
    backup: Path,
    *,
    stamp_baseline: StampSnapshot,
    owned_stamp_fingerprint: tuple[int, int, int, int, str] | None,
) -> list[str]:
    errors: list[str] = []
    for _rel_path, intent in reversed(list(journal.created.items())):
        destination = intent.destination
        try:
            with _pinned_destination_parent(
                boundary, destination, create=False
            ) as parent:
                current = _fingerprint_or_none_at(parent, parent.leaf_name)
                if current is None:
                    continue
                if current != intent.installed_fingerprint:
                    errors.append(
                        f"created path changed concurrently; preserved: {destination}"
                    )
                    continue
                _unlink_at(parent, parent.leaf_name)
        except (OSError, ValueError) as exc:
            errors.append(f"remove {destination}: {exc}")

    for rel_path, intent in journal.updated.items():
        destination = intent.destination
        source = backup / rel_path
        try:
            if not source.is_file():
                errors.append(f"missing rollback backup: {source}")
                continue
            with _pinned_destination_parent(
                boundary, destination, create=False
            ) as parent:
                if _matches_prior_file_at(
                    parent,
                    prior_state=intent.prior_state,
                    backup=source,
                ):
                    continue
                current = _fingerprint_or_none_at(parent, parent.leaf_name)
                if current != intent.installed_fingerprint:
                    errors.append(
                        f"updated path changed concurrently; preserved: {destination}"
                    )
                    continue
                artifact = _stage_copy_at(
                    source,
                    parent,
                    journal=journal,
                    destination=destination,
                )
                temporary = artifact.entry
                try:
                    _replace_at(parent, temporary, parent.leaf_name)
                finally:
                    _cleanup_owned_staged_artifact_at(parent, artifact, journal)
        except (OSError, ValueError) as exc:
            errors.append(f"restore {destination}: {exc}")

    for rel_path, intent in journal.deleted.items():
        destination = intent.destination
        source = backup / rel_path
        try:
            if not source.is_file():
                errors.append(f"missing rollback backup: {source}")
                continue
            with _pinned_destination_parent(
                boundary,
                destination,
                create=True,
            ) as parent:
                if _matches_prior_file_at(
                    parent,
                    prior_state=intent.prior_state,
                    backup=source,
                ):
                    continue
                current = _fingerprint_or_none_at(parent, parent.leaf_name)
                if current is not None:
                    errors.append(
                        f"deleted path reappeared concurrently; preserved: {destination}"
                    )
                    continue
                artifact = _stage_copy_at(
                    source,
                    parent,
                    journal=journal,
                    destination=destination,
                )
                temporary = artifact.entry
                try:
                    try:
                        _link_no_replace_at(parent, temporary, parent.leaf_name)
                    except FileExistsError:
                        errors.append(
                            "deleted path reappeared concurrently; preserved: "
                            f"{destination}"
                        )
                finally:
                    _cleanup_owned_staged_artifact_at(parent, artifact, journal)
        except (OSError, ValueError) as exc:
            errors.append(f"restore {destination}: {exc}")

    for artifact in list(journal.staged):
        try:
            with _pinned_destination_parent(
                boundary,
                artifact.destination,
                create=False,
            ) as parent:
                _cleanup_owned_staged_artifact_at(parent, artifact, journal)
        except (OSError, ValueError) as exc:
            errors.append(
                "clean owned staging artifact "
                f"{artifact.destination.parent / str(artifact.entry)}: {exc}"
            )

    for _rel_path, intent in sorted(
        journal.created_directories.items(),
        key=lambda item: len(Path(item[0]).parts),
        reverse=True,
    ):
        try:
            with _pinned_destination_parent(
                boundary,
                intent.destination,
                create=False,
            ) as parent:
                try:
                    current = os.stat(
                        parent.leaf_name,
                        dir_fd=parent.directory_fd,
                        follow_symlinks=False,
                    )
                except FileNotFoundError:
                    continue
                if (
                    not stat.S_ISDIR(current.st_mode)
                    or _directory_identity_from_stat(current) != intent.identity
                ):
                    # A concurrent replacement is not transaction-owned, but it
                    # also means the transaction did not restore its exact start.
                    errors.append(
                        "created directory identity changed concurrently; preserved: "
                        f"{intent.destination}"
                    )
                    continue
                try:
                    os.rmdir(parent.leaf_name, dir_fd=parent.directory_fd)
                except OSError as exc:
                    if exc.errno in {errno.ENOTEMPTY, errno.EEXIST}:
                        errors.append(
                            "created directory became nonempty concurrently; "
                            f"preserved: {intent.destination}"
                        )
                    else:
                        raise
        except (OSError, ValueError) as exc:
            errors.append(f"remove created directory {intent.destination}: {exc}")

    stamp_path = stamp_path_for_target(boundary.target)
    try:
        _restore_stamp(
            boundary,
            stamp_baseline,
            owned_fingerprint=owned_stamp_fingerprint,
        )
    except (OSError, ValueError) as exc:
        errors.append(f"restore {stamp_path}: {exc}")
    return errors


def apply_sync_plan_transactionally(
    source: Path,
    target: Path,
    plan: SyncPlan,
    *,
    live_source: Path | None = None,
) -> None:
    """Apply a complete plan and stamp it, restoring the prior tree on failure."""
    expected_source_state = _manifest_state(source)

    def validate_live_source() -> None:
        if live_source is None:
            return
        live_state = _manifest_state(live_source)
        if live_state != expected_source_state:
            raise ValueError(
                "canonical docs source changed after its sync snapshot was captured; "
                "refusing to commit stale verified mirror evidence"
            )

    with _pinned_mutation_boundary(
        target,
        expected_root_identity=plan.target_root_identity,
        expected_parent_identity=plan.target_parent_identity,
    ) as boundary:
        stamp_path = stamp_path_for_target(boundary.target)
        stamp_baseline = _capture_regular_stamp(stamp_path, boundary=boundary)
        public_owned_baseline = _validate_existing_public_evidence_before_full_sync(
            boundary,
            stamp_baseline,
        )
        with tempfile.TemporaryDirectory(prefix="agilab-docs-rollback-") as temporary:
            backup = Path(temporary)
            target_manifest = _build_manifest_at_boundary(boundary)
            preconditions: dict[
                str,
                tuple[Path, tuple[int, int, int, int], Path | None],
            ] = {}
            for rel_path in plan.updated + plan.deleted:
                destination = target_manifest.get(rel_path)
                if destination is None:
                    raise ValueError(
                        "managed mirror changed after planning; expected a regular "
                        f"file for {rel_path}; no mirror changes were applied"
                    )
                backup_path = backup / rel_path
                with _pinned_destination_parent(
                    boundary,
                    destination,
                    create=False,
                ) as parent:
                    state = _backup_regular_file_at(parent, backup_path)
                preconditions[rel_path] = (destination, state, backup_path)

            journal = AppliedSyncJournal(created={}, updated={}, deleted={})
            owned_stamp_fingerprint: tuple[int, int, int, int, str] | None = None
            try:
                validate_live_source()
                _apply_sync_plan_safely(
                    source,
                    boundary,
                    plan,
                    preconditions=preconditions,
                    journal=journal,
                )
                validate_live_source()
                _stamp_path, owned_stamp_fingerprint = _write_mirror_stamp_at_boundary(
                    source,
                    boundary,
                    expected_public_owned_files=public_owned_baseline,
                )
                validate_live_source()
            except BaseException as exc:
                rollback_errors = _rollback_sync_plan(
                    boundary,
                    journal,
                    backup,
                    stamp_baseline=stamp_baseline,
                    owned_stamp_fingerprint=owned_stamp_fingerprint,
                )
                if rollback_errors:
                    details = "; ".join(rollback_errors)
                    raise RuntimeError(
                        "docs mirror sync failed and rollback was incomplete: "
                        + details
                    ) from exc
                raise


def render_plan(plan: SyncPlan, *, source: Path, target: Path) -> str:
    lines = [
        f"source: {source}",
        f"target: {target}",
        f"create: {len(plan.created)}",
        f"update: {len(plan.updated)}",
        f"delete: {len(plan.deleted)}",
    ]
    for label, items in (
        ("create", plan.created),
        ("update", plan.updated),
        ("delete", plan.deleted),
    ):
        for item in items:
            lines.append(f"{label}: {item}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Sync the public docs/source mirror in agilab from the canonical "
            "thales_agilab/docs/source tree."
        )
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help=(
            "Canonical docs/source directory. When omitted, AGILAB_DOCS_SOURCE, "
            "then DOCS_REPOSITORY/docs/source, then the conventional sibling "
            "checkout are used."
        ),
    )
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="Check for drift without applying changes. This is the default mode.",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Copy created/updated files into the target mirror. Mutation requires "
            "POSIX handle-relative directory operations; Windows supports check and "
            "verification modes only. The target directory must already exist; this "
            "command does not bootstrap it through an untrusted ancestor path."
        ),
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete files from the target mirror when they no longer exist in the source tree.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the sync summary output when nothing changes.",
    )
    mode.add_argument(
        "--verify-stamp",
        action="store_true",
        help=(
            "Verify target integrity and canonical-source drift. Use "
            "--skip-missing-source to explicitly accept target-only verification."
        ),
    )
    mode.add_argument(
        "--verify-target-integrity",
        action="store_true",
        help=(
            "Verify only the checked-in target and its stamp, without resolving "
            "or comparing a canonical source checkout."
        ),
    )
    mode.add_argument(
        "--write-target-only-stamp",
        action="store_true",
        help=(
            "Write target-integrity evidence with source_status=unavailable. "
            "This never claims that the canonical source was checked."
        ),
    )
    mode.add_argument(
        "--refresh-target-integrity-stamp",
        action="store_true",
        help=(
            "Refresh only the release-proof public-owned digests in an existing "
            "valid v3 stamp while preserving its managed-source provenance. "
            "Other evidence changes and older stamp formats fail closed."
        ),
    )
    mode.add_argument(
        "--refresh-ui-robot-evidence-stamp",
        action="store_true",
        help=(
            "Refresh only the digest for an existing public-owned "
            "data/ui_robot_evidence.json in a valid v3 stamp. The canonical "
            "source, managed target, and all other public-owned evidence must "
            "still match their stamped state."
        ),
    )
    parser.add_argument(
        "--skip-missing-source",
        action="store_true",
        help=(
            "When the canonical source checkout is absent, skip source-to-target "
            "drift checks instead of failing. This is intended for local hooks "
            "and public CI jobs that should enforce the comparison only when "
            "the sibling docs checkout is available."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    target = _absolute_path(args.target, base=Path.cwd())

    if args.verify_target_integrity:
        if not target.exists():
            parser.error(f"target directory not found: {target}")
        ok, message = verify_target_mirror_integrity(target)
        if not ok or not args.quiet:
            print(message)
        return 0 if ok else 1

    if args.refresh_target_integrity_stamp:
        if not target.exists():
            parser.error(f"target directory not found: {target}")
        if not target.is_dir():
            parser.error(f"target path is not a directory: {target}")
        try:
            stamp_path, written = refresh_target_integrity_stamp(target)
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"mirror stamp not refreshed: {exc}", file=sys.stderr)
            return 1
        if not args.quiet:
            if written:
                stamp, _error = _read_stamp(target)
                source_status = stamp.get("source_status") if stamp else "unavailable"
                print(
                    f"mirror stamp refreshed: {stamp_path}; source_status={source_status}"
                )
            else:
                print(f"existing mirror stamp preserved: {stamp_path}")
        return 0

    if args.refresh_ui_robot_evidence_stamp:
        if not target.exists():
            parser.error(f"target directory not found: {target}")
        if not target.is_dir():
            parser.error(f"target path is not a directory: {target}")
        if args.source is not None:
            source_configuration = CanonicalSourceConfiguration(
                path=_absolute_path(args.source, base=Path.cwd()),
                origin="cli:--source",
                required=True,
            )
        else:
            try:
                source_configuration = canonical_source_configuration()
            except ValueError as exc:
                parser.error(str(exc))
        source = source_configuration.path
        if not source.exists():
            print(
                "UI robot evidence mirror stamp not refreshed: canonical docs "
                f"source not found: {source} ({source_configuration.origin})",
                file=sys.stderr,
            )
            return 1
        try:
            stamp_path, written = refresh_ui_robot_evidence_stamp(source, target)
        except (OSError, RuntimeError, ValueError) as exc:
            print(
                f"UI robot evidence mirror stamp not refreshed: {exc}",
                file=sys.stderr,
            )
            return 1
        if not args.quiet:
            if written:
                print(f"UI robot evidence mirror stamp refreshed: {stamp_path}")
            else:
                print(f"existing mirror stamp preserved: {stamp_path}")
        return 0

    if args.write_target_only_stamp:
        if not target.exists():
            parser.error(f"target directory not found: {target}")
        if not target.is_dir():
            parser.error(f"target path is not a directory: {target}")
        try:
            stamp_path = write_target_only_mirror_stamp(target)
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"mirror stamp not written: {exc}", file=sys.stderr)
            return 1
        if not args.quiet:
            print(
                f"target-only mirror stamp written: {stamp_path}; "
                "canonical drift NOT CHECKED"
            )
        return 0

    if args.verify_stamp:
        if not target.exists():
            parser.error(f"target directory not found: {target}")
        target_ok, target_message = verify_target_mirror_integrity(target)
        if not target_ok:
            print(target_message)
            return 1
        if args.source is not None:
            source_configuration = CanonicalSourceConfiguration(
                path=_absolute_path(args.source, base=Path.cwd()),
                origin="cli:--source",
                required=True,
            )
        else:
            try:
                source_configuration = canonical_source_configuration()
            except ValueError as exc:
                parser.error(str(exc))
        source = source_configuration.path
        if not source.exists() and source_configuration.required:
            print(
                f"configured canonical docs source not found: {source} "
                f"({source_configuration.origin})"
            )
            return 1
        ok, message = verify_mirror_stamp(
            target,
            source,
            skip_missing_source=args.skip_missing_source,
        )
        if not ok or not args.quiet or "canonical drift NOT CHECKED" in message:
            print(message)
        return 0 if ok else 1

    if args.source is not None:
        source_configuration = CanonicalSourceConfiguration(
            path=_absolute_path(args.source, base=Path.cwd()),
            origin="cli:--source",
            required=True,
        )
    else:
        try:
            source_configuration = canonical_source_configuration()
        except ValueError as exc:
            parser.error(str(exc))
    source = source_configuration.path
    if not source.exists():
        if (
            args.skip_missing_source
            and not args.apply
            and not source_configuration.required
        ):
            if not target.exists():
                parser.error(f"target directory not found: {target}")
            ok, message = verify_target_mirror_integrity(target)
            if ok:
                message = f"{message}; {CANONICAL_DRIFT_NOT_CHECKED}: {source}"
            print(message)
            return 0 if ok else 1
        parser.error(
            f"source directory not found: {source} ({source_configuration.origin})"
        )
    if not source.is_dir():
        parser.error(f"source path is not a directory: {source}")

    try:
        _ensure_disjoint_directories(source, target)
    except ValueError as exc:
        print(f"sync not applied: {exc}", file=sys.stderr)
        return 1
    if target.exists() and not target.is_dir():
        parser.error(f"target path is not a directory: {target}")

    if args.apply:
        if not target.exists():
            print(
                "sync not applied: target directory not found; create the real target "
                "directory explicitly before --apply (automatic bootstrap is disabled "
                "to avoid following an untrusted ancestor path): "
                f"{target}",
                file=sys.stderr,
            )
            return 1
        try:
            with managed_source_snapshot(source) as snapshot:
                complete_plan = make_sync_plan(snapshot, target, delete_extra=True)
                plan = (
                    complete_plan
                    if args.delete
                    else SyncPlan(
                        created=complete_plan.created,
                        updated=complete_plan.updated,
                        deleted=[],
                        target_root_identity=complete_plan.target_root_identity,
                        target_parent_identity=complete_plan.target_parent_identity,
                    )
                )
                if plan.has_changes() or not args.quiet:
                    print(render_plan(plan, source=source, target=target))
                if complete_plan.deleted and not args.delete:
                    print(
                        "sync not applied: the managed mirror contains "
                        f"{len(complete_plan.deleted)} file(s) absent from the "
                        "canonical source. No changes were applied; rerun with "
                        "--apply --delete so the complete sync plan and verified "
                        "stamp stay aligned",
                        file=sys.stderr,
                    )
                    return 1
                apply_sync_plan_transactionally(
                    snapshot,
                    target,
                    plan,
                    live_source=source,
                )
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"sync not applied: {exc}", file=sys.stderr)
            return 1
        return 0

    try:
        complete_plan = make_stable_sync_plan(source, target, delete_extra=True)
    except (OSError, ValueError) as exc:
        print(f"sync check failed: {exc}", file=sys.stderr)
        return 1
    plan = (
        complete_plan
        if args.delete
        else SyncPlan(
            created=complete_plan.created,
            updated=complete_plan.updated,
            deleted=[],
        )
    )
    if plan.has_changes() or not args.quiet:
        print(render_plan(plan, source=source, target=target))
    return 1 if plan.has_changes() else 0


if __name__ == "__main__":
    sys.exit(main())
