"""Shared DAG artifact types and bounded receipt detection."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from stat import S_ISDIR
from typing import Any, Iterable, Mapping


_RECEIPT_SCHEMAS = frozenset(
    {
        "agilab.dag_contract_stage_result.v1",
        "agilab.distributed_dag_stage_submission.v1",
    }
)
_RECEIPT_JSON_READ_LIMIT = 1024 * 1024
_NON_OUTPUT_DIRECTORIES = frozenset(
    {".venv", ".venv-dev", "__pycache__", ".git", ".cache", "node_modules"}
)


def _is_linked_artifact_path(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def artifact_file_identity(path: Path) -> dict[str, Any]:
    """Capture the bytes bound to one produced file, without loading it at once."""
    if _is_linked_artifact_path(path) or not path.is_file():
        raise ValueError(f"Produced artifact must be a regular file: {path}")
    digest = hashlib.sha256()
    size_bytes = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            size_bytes += len(chunk)
            digest.update(chunk)
    return {"size_bytes": size_bytes, "sha256": digest.hexdigest()}


def artifact_identity(path: Path, *, run_root: Path) -> dict[str, Any]:
    """Hash one declared artifact; never traverse linked or runtime metadata trees."""
    if _is_linked_artifact_path(path):
        raise ValueError(f"Produced artifact contains a symlink or junction: {path}")
    path = path.resolve()
    if path.is_file():
        return artifact_file_identity(path)
    if not path.is_dir():
        raise ValueError(f"Produced artifact is missing or unsupported: {path}")
    digest = hashlib.sha256()
    size_bytes = 0
    entry_count = 0
    # These are the same non-output directories the freshness contract excludes.
    # Private runtime metadata is excluded only at its defined stage-root paths.
    metadata = {
        run_root.resolve() / ".agilab-idempotency",
        run_root.resolve() / "distributed_submission_evidence",
    }

    def walk_error(error: OSError) -> None:
        raise error

    for current, directories, files in os.walk(
        path, followlinks=False, onerror=walk_error
    ):
        current_path = Path(current)
        directories[:] = sorted(
            name
            for name in directories
            if name not in _NON_OUTPUT_DIRECTORIES
            and (current_path / name).absolute() not in metadata
        )
        for name in directories:
            if _is_linked_artifact_path(current_path / name):
                raise ValueError(
                    f"Produced artifact contains a symlink or junction: {current_path / name}"
                )
        entries = [
            {
                "path": current_path.relative_to(path).as_posix(),
                "kind": "directory",
            }
        ]
        for name in sorted(files):
            child = current_path / name
            identity = artifact_file_identity(child)
            size_bytes += identity["size_bytes"]
            entries.append(
                {
                    "path": child.relative_to(path).as_posix(),
                    "kind": "file",
                    **identity,
                }
            )
        for entry in entries:
            digest.update(
                json.dumps(entry, sort_keys=True, separators=(",", ":")).encode("ascii")
            )
            digest.update(b"\n")
            entry_count += 1
    return {
        "identity_kind": "directory",
        "entry_count": entry_count,
        "size_bytes": size_bytes,
        "sha256": digest.hexdigest(),
    }


def require_artifact_location(
    path: Path,
    *,
    artifact_id: str,
    expected: Mapping[str, Any],
    bind_new: bool = False,
) -> str:
    """Check the frozen target before any receipt probe or artifact-content read."""
    if _is_linked_artifact_path(path):
        raise ValueError(
            f"Cached produced artifact `{artifact_id}` contains a symlink or junction: {path}"
        )
    try:
        resolved = str(path.resolve())
    except (OSError, RuntimeError) as exc:
        raise ValueError(
            f"Cached produced artifact `{artifact_id}` has an invalid location: {path}"
        ) from exc
    original = expected.get("resolved_path")
    if original is None and bind_new:
        return resolved
    # Do not resolve the stored canonical spelling again: a changed ancestor may
    # now redirect that exact spelling to a different target.
    if not isinstance(original, str) or original != resolved:
        raise ValueError(
            f"Cached produced artifact `{artifact_id}` resolves to a different original location; "
            "a parent symlink or missing original location requires a fresh explicit attempt."
        )
    return resolved


def require_artifact_identity(
    path: Path,
    *,
    artifact_id: str,
    expected: Mapping[str, Any],
    run_root: Path,
    bind_location: bool = False,
) -> dict[str, Any]:
    """Reject changed files and legacy cache entries lacking an original binding."""
    require_artifact_location(
        path, artifact_id=artifact_id, expected=expected, bind_new=bind_location
    )
    size_bytes = expected.get("size_bytes")
    sha256 = expected.get("sha256")
    if (
        isinstance(size_bytes, bool)
        or not isinstance(size_bytes, int)
        or size_bytes < 0
        or not isinstance(sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", sha256) is None
    ):
        raise ValueError(
            f"Cached produced artifact `{artifact_id}` has no valid original byte identity. "
            "Run a fresh explicit attempt."
        )
    try:
        actual = artifact_identity(path, run_root=run_root)
    except (OSError, ValueError) as exc:
        raise ValueError(
            f"Cached produced artifact `{artifact_id}` cannot be verified: {exc}"
        ) from exc
    expected_identity = {"size_bytes": size_bytes, "sha256": sha256}
    if expected.get("identity_kind") == "directory":
        count = expected.get("entry_count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ValueError(
                f"Cached produced artifact `{artifact_id}` has no valid original directory identity."
            )
        expected_identity.update(identity_kind="directory", entry_count=count)
    if actual != expected_identity:
        raise ValueError(
            f"Cached produced artifact `{artifact_id}` differs from its completed producer bytes."
        )
    return actual


def bind_artifact_identities(
    outputs: list[dict[str, Any]], *, run_root: Path, bind_new: bool
) -> list[dict[str, Any]]:
    """Bind only fresh executor outputs; never establish a baseline from a cache."""
    for output in outputs:
        path = Path(output["path"])
        path = path if path.is_absolute() else run_root / path
        location = require_artifact_location(
            path, artifact_id=output["artifact"], expected=output, bind_new=bind_new
        )
        if bind_new and not any(key in output for key in ("size_bytes", "sha256")):
            identity = artifact_identity(path, run_root=run_root)
        else:
            identity = require_artifact_identity(
                path,
                artifact_id=output["artifact"],
                expected=output,
                run_root=run_root,
                bind_location=bind_new,
            )
        output.update(identity, resolved_path=location)
    return outputs


class ArtifactOutputSnapshot:
    """Observe output generations around one new executor call, without wall-clock cutoffs."""

    def __init__(
        self, *, workspaces: Iterable[Path], declared_paths: Iterable[Path] = ()
    ) -> None:
        workspace_paths = tuple(Path(path).expanduser() for path in workspaces)
        self._workspace_anchors = tuple(
            (path.absolute(), path.resolve()) for path in workspace_paths
        )
        self._workspaces = tuple(target for _, target in self._workspace_anchors)
        self._declared_paths = {
            self._canonical_output_path(path) for path in declared_paths
        }
        self._before: dict[Path, tuple[int, ...]] = {}
        self._excluded: set[Path] = set()
        for path in (*self._workspaces, *self._declared_paths):
            observed, excluded = self._collect(path)
            self._before.update(observed)
            self._excluded.update(excluded)

    def _canonical_output_path(self, path: Path) -> Path:
        path = Path(path).expanduser()
        anchor = next(
            (
                target
                for original, target in self._workspace_anchors
                if path.absolute() == original
            ),
            None,
        )
        if _is_linked_artifact_path(path) and anchor is None:
            raise ValueError(
                f"Artifact freshness output contains a symlink or junction: {path}"
            )
        resolved = path.resolve()
        if anchor is not None and resolved != anchor:
            raise ValueError(
                f"Artifact freshness workspace anchor changed location: {path}"
            )
        return resolved

    @staticmethod
    def _identity(path: Path) -> tuple[int, ...] | None:
        try:
            stat = path.stat()
        except (FileNotFoundError, NotADirectoryError):
            return None
        if S_ISDIR(stat.st_mode):
            # Child-file generations and directory replacement establish
            # freshness; cache/receipt writes must not qualify via parent mtime.
            return (stat.st_dev, stat.st_ino)
        return (
            stat.st_dev,
            stat.st_ino,
            stat.st_size,
            stat.st_mtime_ns,
            stat.st_ctime_ns,
        )

    @classmethod
    def _collect(cls, path: Path) -> tuple[dict[Path, tuple[int, ...]], set[Path]]:
        if _is_linked_artifact_path(path):
            return {}, {path.absolute()}
        identity = cls._identity(path)
        if identity is None:
            return {}, set()
        observed = {path: identity}
        excluded: set[Path] = set()
        if not path.is_dir():
            return observed, excluded

        def walk_error(error: OSError) -> None:
            raise error

        for current, directories, files in os.walk(
            path, followlinks=False, onerror=walk_error
        ):
            current_path = Path(current)
            for name in list(directories):
                child = current_path / name
                if name in _NON_OUTPUT_DIRECTORIES or _is_linked_artifact_path(child):
                    directories.remove(name)
                    excluded.add(child.absolute())
                else:
                    child_identity = cls._identity(child)
                    if child_identity is not None:
                        observed[child.resolve()] = child_identity
            for name in files:
                child = current_path / name
                if _is_linked_artifact_path(child):
                    continue
                child_identity = cls._identity(child)
                if child_identity is not None:
                    observed[child.resolve()] = child_identity
        return observed, excluded

    def require_fresh(self, path: Path, *, artifact_id: str) -> None:
        resolved = self._canonical_output_path(path)
        declared = resolved in self._declared_paths
        covered = declared or any(
            resolved.is_relative_to(root) for root in self._workspaces
        )
        if not covered or (
            not declared
            and any(resolved.is_relative_to(root) for root in self._excluded)
        ):
            raise RuntimeError(
                f"Cannot establish attempt freshness for artifact `{artifact_id}` outside its output workspace. "
                "Declare its output path before execution."
            )
        before = {
            key: value
            for key, value in self._before.items()
            if key == resolved or key.is_relative_to(resolved)
        }
        after, _ = self._collect(resolved)
        if not after or before == after:
            raise RuntimeError(
                f"DAG executor did not freshly produce declared artifact `{artifact_id}` for this attempt."
            )


def artifact_result_path_key(kind: str) -> str:
    if kind == "reduce_summary":
        return "reduce_artifact_path"
    if kind == "summary_metrics":
        return "summary_metrics_path"
    return "contract_artifact_path"


def reported_artifact_paths(result: Mapping[str, Any]) -> dict[str, str]:
    """Read explicit output identities without accepting empty or malformed paths."""
    if "produced_artifacts" not in result:
        return {}
    outputs = result["produced_artifacts"]
    if not isinstance(outputs, list):
        raise RuntimeError("DAG executor produced_artifacts must be a list.")
    paths: dict[str, str] = {}
    for output in outputs:
        if not isinstance(output, Mapping):
            raise RuntimeError(
                "DAG executor produced_artifacts entries must be mappings."
            )
        artifact_id = output.get("artifact") or output.get("id")
        path = output.get("path")
        if not isinstance(artifact_id, str) or not artifact_id.strip():
            raise RuntimeError(
                "DAG executor produced_artifacts entries require an artifact identity."
            )
        if not isinstance(path, (str, Path)) or not str(path).strip():
            raise RuntimeError(
                f"DAG executor artifact `{artifact_id}` requires a nonempty path."
            )
        artifact_id = artifact_id.strip()
        if artifact_id in paths:
            raise RuntimeError(
                f"DAG executor reported artifact `{artifact_id}` more than once."
            )
        paths[artifact_id] = str(path).strip()
    return paths


def verified_submission_artifacts(
    result: Mapping[str, Any], *, run_root: Path, unit_id: str, idempotency_token: str
) -> set[tuple[str, str, Path]]:
    """Read the submitter's completed output checks for this exact unit/token."""
    value = result.get("submission_evidence_path")
    if not isinstance(value, (str, Path)) or not str(value).strip():
        return set()
    path = Path(value)
    if not path.is_absolute():
        path = run_root / path
    if not path.resolve().is_relative_to(run_root.resolve()):
        return set()
    try:
        with path.open("rb") as stream:
            data = stream.read(_RECEIPT_JSON_READ_LIMIT + 1)
        if len(data) > _RECEIPT_JSON_READ_LIMIT:
            return set()
        receipt = json.loads(data)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return set()
    if not isinstance(receipt, Mapping) or (
        receipt.get("schema") != "agilab.distributed_dag_stage_submission.v1"
        or receipt.get("unit_id") != unit_id
        or receipt.get("idempotency_token") != idempotency_token
    ):
        return set()
    validation = receipt.get("artifact_validation")
    if not isinstance(validation, Mapping) or validation.get("status") != "passed":
        return set()
    paths = reported_artifact_paths(validation)
    verified: set[tuple[str, str, Path]] = set()
    for output in validation.get("produced_artifacts", []):
        if output.get("kind") == "contract_artifact":
            continue
        artifact_id = str(output.get("artifact", "") or output.get("id", "")).strip()
        output_path = Path(paths[artifact_id])
        output_path = (
            output_path if output_path.is_absolute() else run_root / output_path
        )
        require_artifact_identity(
            output_path, artifact_id=artifact_id, expected=output, run_root=run_root
        )
        verified.add(
            (
                artifact_id,
                str(output.get("kind", "")),
                Path(paths[artifact_id]).resolve(),
            )
        )
    return verified


def is_contract_receipt_artifact(path: Path) -> bool:
    """Recognize AGILAB receipts without loading large scientific artifacts."""
    try:
        if not path.is_file():
            return False
        with path.open("rb") as stream:
            prefix = stream.read(256)
            if not prefix.lstrip().startswith(b"{"):
                return False
            stream.seek(0)
            data = stream.read(_RECEIPT_JSON_READ_LIMIT + 1)
            if len(data) <= _RECEIPT_JSON_READ_LIMIT:
                payload = json.loads(data)
                return (
                    isinstance(payload, dict)
                    and isinstance(payload.get("schema"), str)
                    and payload["schema"] in _RECEIPT_SCHEMAS
                )
            # AGILAB's atomic JSON writer uses sorted keys and two-space
            # indentation. Its schema is near the end even when logs are large.
            stream.seek(-65536, 2)
            tail = stream.read(65536)
            if not tail.rstrip().endswith(b"}"):
                return False
            return any(
                re.search(
                    rb'^  "schema": "' + re.escape(schema.encode()) + rb'",?\r?$',
                    tail,
                    re.MULTILINE,
                )
                is not None
                for schema in _RECEIPT_SCHEMAS
            )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
