"""Shared DAG artifact types and bounded receipt detection."""

from __future__ import annotations

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


class ArtifactOutputSnapshot:
    """Observe output generations around one new executor call, without wall-clock cutoffs."""

    def __init__(
        self, *, workspaces: Iterable[Path], declared_paths: Iterable[Path] = ()
    ) -> None:
        self._workspaces = tuple(
            Path(path).expanduser().resolve() for path in workspaces
        )
        self._declared_paths = {
            Path(path).expanduser().resolve() for path in declared_paths
        }
        self._before: dict[Path, tuple[int, ...]] = {}
        self._excluded: set[Path] = set()
        for path in (*self._workspaces, *self._declared_paths):
            observed, excluded = self._collect(path)
            self._before.update(observed)
            self._excluded.update(excluded)

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
                if name in _NON_OUTPUT_DIRECTORIES or child.is_symlink():
                    directories.remove(name)
                    excluded.add(child.absolute())
                else:
                    child_identity = cls._identity(child)
                    if child_identity is not None:
                        observed[child.resolve()] = child_identity
            for name in files:
                child = current_path / name
                if child.is_symlink():
                    continue
                child_identity = cls._identity(child)
                if child_identity is not None:
                    observed[child.resolve()] = child_identity
        return observed, excluded

    def require_fresh(self, path: Path, *, artifact_id: str) -> None:
        resolved = path.expanduser().resolve()
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
        artifact_id = str(output.get("artifact", "") or output.get("id", "")).strip()
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
