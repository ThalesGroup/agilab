from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from contextlib import contextmanager
import hashlib
import json
import os
import platform
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
from typing import Any, Callable, Mapping, Sequence, TypeVar
from uuid import uuid4

from agilab.evidence.evidence_graph import (
    EVIDENCE_GRAPH_KIND,
    build_evidence_graph_from_workflow_manifest,
    validate_evidence_graph,
)
from agilab.workflow.workflow_runtime_contract import (
    build_workflow_runtime_contract,
    validate_workflow_runtime_contract,
)


WORKFLOW_RUN_MANIFEST_SCHEMA_VERSION = 4
SUPPORTED_WORKFLOW_RUN_MANIFEST_SCHEMAS = {2, 3, WORKFLOW_RUN_MANIFEST_SCHEMA_VERSION}
WORKFLOW_RUN_MANIFEST_KIND = "agilab.workflow_run_manifest"
EVIDENCE_LEDGER_SCHEMA_VERSION = 1
EVIDENCE_LEDGER_KIND = "agilab.evidence_ledger"
WORKFLOW_EVIDENCE_DIRNAME = "workflow_evidence"
WORKFLOW_RUN_MANIFEST_FILENAME = "workflow_run_manifest.json"
EVIDENCE_LEDGER_FILENAME = "evidence_ledger.json"
EVIDENCE_GRAPH_FILENAME = "evidence_graph.json"
RUNNER_STATE_SNAPSHOT_FILENAME = "runner_state_snapshot.json"
LATEST_WORKFLOW_EVIDENCE_FILENAME = "latest_workflow_evidence.json"
WORKFLOW_EVIDENCE_COMPLETION_FILENAME = ".complete.json"
WORKFLOW_EVIDENCE_PUBLICATION_LOCK_FILENAME = ".publish.lock"
SUPPORTED_STATUSES = {"pass", "fail", "unknown"}
_PUBLICATION_LOCK_TIMEOUT_SECONDS = 5.0
_PUBLICATION_LOCK_RETRY_INTERVAL_SECONDS = 0.05
_WINDOWS_SHARING_RETRY_TIMEOUT_SECONDS = 0.5
_WINDOWS_SHARING_RETRY_INTERVAL_SECONDS = 0.01
_T = TypeVar("_T")


def _is_windows() -> bool:
    return os.name == "nt"


def _run_with_windows_sharing_retry(operation: Callable[[], _T]) -> _T:
    """Retry only transient Windows sharing denials for mutable evidence files."""

    deadline = time.monotonic() + _WINDOWS_SHARING_RETRY_TIMEOUT_SECONDS
    while True:
        try:
            return operation()
        except PermissionError:
            if not _is_windows():
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            time.sleep(min(_WINDOWS_SHARING_RETRY_INTERVAL_SECONDS, remaining))


@dataclass(frozen=True)
class WorkflowEvidenceBundle:
    manifest_path: Path
    ledger_path: Path
    graph_path: Path
    state_snapshot_path: Path
    latest_path: Path
    manifest: dict[str, Any]
    ledger: dict[str, Any]
    graph: dict[str, Any]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def canonical_json_bytes(payload: Mapping[str, Any] | Sequence[Any]) -> bytes:
    return json.dumps(
        _json_safe(payload),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_payload(payload: Mapping[str, Any] | Sequence[Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def workflow_state_digest(state: Mapping[str, Any]) -> str:
    return sha256_payload(dict(state))


def workflow_evidence_root(lab_dir: Path) -> Path:
    return lab_dir.expanduser() / ".agilab" / WORKFLOW_EVIDENCE_DIRNAME


def workflow_evidence_paths(lab_dir: Path, manifest_id: str) -> tuple[Path, Path, Path]:
    root = workflow_evidence_root(lab_dir)
    evidence_dir = root / _safe_id(manifest_id)
    return (
        evidence_dir / WORKFLOW_RUN_MANIFEST_FILENAME,
        evidence_dir / EVIDENCE_LEDGER_FILENAME,
        root / LATEST_WORKFLOW_EVIDENCE_FILENAME,
    )


def workflow_evidence_graph_path(lab_dir: Path, manifest_id: str) -> Path:
    return workflow_evidence_root(lab_dir) / _safe_id(manifest_id) / EVIDENCE_GRAPH_FILENAME


def build_workflow_run_manifest(
    *,
    state: Mapping[str, Any],
    state_path: Path,
    repo_root: Path,
    lab_dir: Path,
    dag_path: Path | None = None,
    trigger: Mapping[str, Any] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build a stable workflow/DAG run manifest from persisted runner state."""
    persisted_state = _read_matching_runner_state(state=state, state_path=state_path)
    return _build_workflow_run_manifest(
        state=persisted_state,
        state_path=state_path,
        repo_root=repo_root,
        lab_dir=lab_dir,
        dag_path=dag_path,
        trigger=trigger,
        created_at=created_at,
    )


def _build_workflow_run_manifest(
    *,
    state: Mapping[str, Any],
    state_path: Path,
    repo_root: Path,
    lab_dir: Path,
    dag_path: Path | None = None,
    trigger: Mapping[str, Any] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    state_snapshot = _json_safe(dict(state))
    state_sha256 = workflow_state_digest(state)
    run_id = _safe_id(str(state.get("run_id", "") or "workflow-run"))
    units = _unit_rows(state)
    produced_artifacts, consumed_artifacts = _artifact_contracts(units)
    status = _manifest_status(state, units)
    runtime_contract = build_workflow_runtime_contract(state)
    source = state.get("source", {})
    source = source if isinstance(source, Mapping) else {}
    summary = state.get("summary", {})
    summary = summary if isinstance(summary, Mapping) else {}
    timestamp = created_at or _state_timestamp(state)
    workflow_source_path = _workflow_source_path(source, dag_path, repo_root)
    runtime = {
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "repo_root": str(repo_root.expanduser().resolve(strict=False)),
        "lab_dir": str(lab_dir.expanduser().resolve(strict=False)),
    }
    trigger_payload = _json_safe(dict(trigger or {}))
    identity_sha256 = sha256_payload(
        {
            "schema_version": WORKFLOW_RUN_MANIFEST_SCHEMA_VERSION,
            "state": state_snapshot,
            "state_path": str(state_path.expanduser()),
            "created_at": timestamp,
            "workflow_source_path": workflow_source_path,
            "runtime": runtime,
            "trigger": trigger_payload,
        }
    )
    manifest_id = (
        f"{run_id}-v{WORKFLOW_RUN_MANIFEST_SCHEMA_VERSION}-"
        f"{state_sha256[:12]}-{identity_sha256[:12]}"
    )
    manifest_path, ledger_path, _latest_path = workflow_evidence_paths(lab_dir, manifest_id)
    graph_path = workflow_evidence_graph_path(lab_dir, manifest_id)
    state_snapshot_path = manifest_path.parent / RUNNER_STATE_SNAPSHOT_FILENAME
    state_snapshot_bytes = _json_document_text(state_snapshot).encode("utf-8")
    state_snapshot_file_sha256 = hashlib.sha256(state_snapshot_bytes).hexdigest()

    validations = _manifest_validations(
        state=state,
        units=units,
        produced_artifacts=produced_artifacts,
        consumed_artifacts=consumed_artifacts,
    )
    return {
        "schema_version": WORKFLOW_RUN_MANIFEST_SCHEMA_VERSION,
        "kind": WORKFLOW_RUN_MANIFEST_KIND,
        "manifest_id": manifest_id,
        "identity_sha256": identity_sha256,
        "run_id": str(state.get("run_id", "") or ""),
        "status": status,
        "created_at": timestamp,
        "workflow": {
            "source_type": str(source.get("source_type", "") or "multi_app_dag"),
            "dag_path": workflow_source_path,
            "stages_file": str(source.get("stages_file", "") or ""),
            "plan_schema": str(source.get("plan_schema", "") or ""),
            "plan_runner_status": str(source.get("plan_runner_status", "") or ""),
            "execution_order": [str(item) for item in source.get("execution_order", [])]
            if isinstance(source.get("execution_order"), list)
            else [str(unit.get("id", "")) for unit in units if str(unit.get("id", ""))],
            "unit_count": len(units),
        },
        "runtime": runtime,
        "trigger": trigger_payload,
        "runner_state": {
            "path": str(state_path.expanduser()),
            "source_path": str(state_path.expanduser()),
            "snapshot_path": str(state_snapshot_path),
            "exists": True,
            "sha256": state_snapshot_file_sha256,
            "snapshot_sha256": state_sha256,
            "schema": str(state.get("schema", "") or ""),
            "run_status": str(state.get("run_status", "") or ""),
            "summary": _json_safe(dict(summary)),
        },
        "artifact_contracts": {
            "produced_count": len(produced_artifacts),
            "consumed_count": len(consumed_artifacts),
            "produced": produced_artifacts,
            "consumed": consumed_artifacts,
        },
        "stages": [_stage_record(unit) for unit in units],
        "artifacts": [
            {
                "name": RUNNER_STATE_SNAPSHOT_FILENAME,
                "path": str(state_snapshot_path),
                "source_path": str(state_path.expanduser()),
                "kind": "runner_state_snapshot",
                "exists": True,
                "size_bytes": len(state_snapshot_bytes),
                "sha256": state_snapshot_file_sha256,
            }
        ],
        "validations": validations,
        "runtime_contract": runtime_contract,
        "evidence_ledger": {
            "path": str(ledger_path),
            "kind": EVIDENCE_LEDGER_KIND,
        },
        "evidence_graph": {
            "path": str(graph_path),
            "kind": EVIDENCE_GRAPH_KIND,
        },
        "state_snapshot": {
            "path": str(state_snapshot_path),
            "sha256": state_sha256,
            "event_count": len(state_snapshot.get("events", []))
            if isinstance(state_snapshot.get("events"), list)
            else 0,
        },
    }


def build_evidence_ledger(
    manifest: Mapping[str, Any],
    *,
    manifest_path: Path,
    ledger_path: Path,
    extra_artifacts: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    manifest_digest = sha256_payload(dict(manifest))
    manifest_id = str(manifest.get("manifest_id", "") or "")
    claims = []
    for validation in manifest.get("validations", []):
        if not isinstance(validation, Mapping):
            continue
        claim_id = str(validation.get("id", "") or validation.get("label", "") or "validation")
        claims.append(
            {
                "id": claim_id,
                "status": str(validation.get("status", "unknown") or "unknown"),
                "summary": str(validation.get("summary", "") or ""),
                "evidence": [
                    {
                        "kind": WORKFLOW_RUN_MANIFEST_KIND,
                        "manifest_id": manifest_id,
                        "path": str(manifest_path),
                        "sha256": manifest_digest,
                    }
                ],
            }
        )
    artifacts = [
        {
            "name": WORKFLOW_RUN_MANIFEST_FILENAME,
            "kind": WORKFLOW_RUN_MANIFEST_KIND,
            "path": str(manifest_path),
            "sha256": manifest_digest,
        },
        {
            "name": EVIDENCE_LEDGER_FILENAME,
            "kind": EVIDENCE_LEDGER_KIND,
            "path": str(ledger_path),
        },
    ]
    artifacts.extend(_json_safe(dict(artifact)) for artifact in extra_artifacts or [])
    return {
        "schema_version": EVIDENCE_LEDGER_SCHEMA_VERSION,
        "kind": EVIDENCE_LEDGER_KIND,
        "ledger_id": f"ledger-{manifest_id}",
        "manifest_id": manifest_id,
        "run_id": str(manifest.get("run_id", "") or ""),
        "status": str(manifest.get("status", "unknown") or "unknown"),
        "created_at": str(manifest.get("created_at", "") or utc_now()),
        "claims": claims,
        "artifacts": artifacts,
    }


def write_workflow_run_evidence(
    *,
    state: Mapping[str, Any],
    state_path: Path,
    repo_root: Path,
    lab_dir: Path,
    dag_path: Path | None = None,
    trigger: Mapping[str, Any] | None = None,
    created_at: str | None = None,
) -> WorkflowEvidenceBundle:
    persisted_state = _read_matching_runner_state(state=state, state_path=state_path)
    manifest = _build_workflow_run_manifest(
        state=persisted_state,
        state_path=state_path,
        repo_root=repo_root,
        lab_dir=lab_dir,
        dag_path=dag_path,
        trigger=trigger,
        created_at=created_at,
    )
    manifest_path, ledger_path, latest_path = workflow_evidence_paths(
        lab_dir,
        str(manifest["manifest_id"]),
    )
    graph_path = workflow_evidence_graph_path(lab_dir, str(manifest["manifest_id"]))
    state_snapshot_path = manifest_path.parent / RUNNER_STATE_SNAPSHOT_FILENAME
    graph = build_evidence_graph_from_workflow_manifest(manifest)
    graph_issues = validate_evidence_graph(graph)
    if graph_issues:
        raise ValueError(f"Invalid workflow evidence graph: {'; '.join(graph_issues)}")
    ledger = build_evidence_ledger(
        manifest,
        manifest_path=manifest_path,
        ledger_path=ledger_path,
        extra_artifacts=[
            {
                "name": EVIDENCE_GRAPH_FILENAME,
                "kind": EVIDENCE_GRAPH_KIND,
                "path": str(graph_path),
                "sha256": sha256_payload(graph),
            },
            {
                "name": RUNNER_STATE_SNAPSHOT_FILENAME,
                "kind": "runner_state_snapshot",
                "path": str(state_snapshot_path),
                "sha256": _json_document_sha256(persisted_state),
            }
        ],
    )
    root = workflow_evidence_root(lab_dir)
    root.mkdir(parents=True, exist_ok=True)
    latest_payload = {
        "schema_version": 1,
        "kind": "agilab.latest_workflow_evidence",
        "manifest_id": manifest["manifest_id"],
        "status": manifest["status"],
        "manifest_path": str(manifest_path),
        "ledger_path": str(ledger_path),
        "graph_path": str(graph_path),
        "updated_at": manifest["created_at"],
        "revision": {
            "run_created_at": str(
                persisted_state.get("created_at", "") or manifest["created_at"]
            ),
            "updated_at": manifest["created_at"],
            "event_count": manifest["state_snapshot"]["event_count"],
            "tie_breaker": manifest["manifest_id"],
        },
    }
    final_dir = manifest_path.parent
    stage_dir = root / f".{final_dir.name}.{uuid4().hex}.staging"
    with _exclusive_publication_lock(root / WORKFLOW_EVIDENCE_PUBLICATION_LOCK_FILENAME):
        _cleanup_stale_staging_dirs(root)
        if final_dir.exists():
            _verify_existing_bundle(
                manifest_path=manifest_path,
                manifest=manifest,
                graph_path=graph_path,
                graph=graph,
                ledger_path=ledger_path,
                ledger=ledger,
                state_snapshot_path=state_snapshot_path,
                state_snapshot=persisted_state,
            )
        else:
            stage_dir.mkdir(mode=0o700)
            try:
                _write_json_fsync(stage_dir / RUNNER_STATE_SNAPSHOT_FILENAME, persisted_state)
                _write_json_fsync(stage_dir / WORKFLOW_RUN_MANIFEST_FILENAME, manifest)
                _write_json_fsync(stage_dir / EVIDENCE_GRAPH_FILENAME, graph)
                _write_json_fsync(stage_dir / EVIDENCE_LEDGER_FILENAME, ledger)
                _write_json_fsync(
                    stage_dir / WORKFLOW_EVIDENCE_COMPLETION_FILENAME,
                    {
                        "schema_version": 1,
                        "kind": "agilab.workflow_evidence.complete",
                        "manifest_id": manifest["manifest_id"],
                        "files": {
                            WORKFLOW_RUN_MANIFEST_FILENAME: _sha256_file_or_empty(
                                stage_dir / WORKFLOW_RUN_MANIFEST_FILENAME
                            ),
                            EVIDENCE_GRAPH_FILENAME: _sha256_file_or_empty(
                                stage_dir / EVIDENCE_GRAPH_FILENAME
                            ),
                            EVIDENCE_LEDGER_FILENAME: _sha256_file_or_empty(
                                stage_dir / EVIDENCE_LEDGER_FILENAME
                            ),
                            RUNNER_STATE_SNAPSHOT_FILENAME: _sha256_file_or_empty(
                                stage_dir / RUNNER_STATE_SNAPSHOT_FILENAME
                            ),
                        },
                    },
                )
                _validate_completion_marker(stage_dir, str(manifest["manifest_id"]))
                _fsync_directory(stage_dir)
                os.rename(stage_dir, final_dir)
                _fsync_directory(root)
            finally:
                if stage_dir.exists():
                    shutil.rmtree(stage_dir, ignore_errors=True)
        _write_latest_if_newer(latest_path, latest_payload)
    return WorkflowEvidenceBundle(
        manifest_path=manifest_path,
        ledger_path=ledger_path,
        graph_path=graph_path,
        state_snapshot_path=state_snapshot_path,
        latest_path=latest_path,
        manifest=manifest,
        ledger=ledger,
        graph=graph,
    )


def load_workflow_run_manifest(path: Path) -> dict[str, Any]:
    expanded_path = path.expanduser()
    manifest_bytes = expanded_path.read_bytes()
    payload = json.loads(manifest_bytes)
    if not isinstance(payload, dict):
        raise ValueError(f"workflow run manifest must be a JSON object: {path}")
    schema_version = int(payload.get("schema_version", 0))
    if schema_version not in SUPPORTED_WORKFLOW_RUN_MANIFEST_SCHEMAS:
        raise ValueError(f"Unsupported workflow run manifest schema: {payload.get('schema_version')!r}")
    if str(payload.get("kind", "")) != WORKFLOW_RUN_MANIFEST_KIND:
        raise ValueError(f"Unsupported workflow run manifest kind: {payload.get('kind')!r}")
    status = str(payload.get("status", "unknown"))
    if status not in SUPPORTED_STATUSES:
        raise ValueError(f"Unsupported workflow run manifest status: {status!r}")
    runtime_contract = payload.get("runtime_contract")
    if runtime_contract is not None:
        if not isinstance(runtime_contract, Mapping):
            raise ValueError("workflow run manifest runtime_contract must be a JSON object")
        issues = validate_workflow_runtime_contract(runtime_contract)
        if issues:
            raise ValueError(f"Invalid workflow runtime contract: {'; '.join(issues)}")
    evidence_graph = payload.get("evidence_graph")
    if evidence_graph is not None and not isinstance(evidence_graph, Mapping):
        raise ValueError("workflow run manifest evidence_graph must be a JSON object")
    completion_path = expanded_path.parent / WORKFLOW_EVIDENCE_COMPLETION_FILENAME
    requires_completion = (
        schema_version >= 4
        or completion_path.exists()
        or bool(payload.get("identity_sha256"))
        or (expanded_path.parent / RUNNER_STATE_SNAPSHOT_FILENAME).exists()
    )
    if requires_completion:
        manifest_id = str(payload.get("manifest_id", "") or "")
        if not manifest_id:
            raise ValueError("workflow run manifest manifest_id is required for completed evidence")
        _validate_completion_marker(
            expanded_path.parent,
            manifest_id,
            captured_files={WORKFLOW_RUN_MANIFEST_FILENAME: manifest_bytes},
            manifest_payload=payload,
        )
    return payload


def load_evidence_ledger(path: Path) -> dict[str, Any]:
    payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"evidence ledger must be a JSON object: {path}")
    if int(payload.get("schema_version", 0)) != EVIDENCE_LEDGER_SCHEMA_VERSION:
        raise ValueError(f"Unsupported evidence ledger schema: {payload.get('schema_version')!r}")
    if str(payload.get("kind", "")) != EVIDENCE_LEDGER_KIND:
        raise ValueError(f"Unsupported evidence ledger kind: {payload.get('kind')!r}")
    return payload


def workflow_manifest_summary(manifest: Mapping[str, Any]) -> dict[str, Any]:
    workflow = manifest.get("workflow", {})
    workflow = workflow if isinstance(workflow, Mapping) else {}
    contracts = manifest.get("artifact_contracts", {})
    contracts = contracts if isinstance(contracts, Mapping) else {}
    runtime_contract = manifest.get("runtime_contract", {})
    runtime_contract = runtime_contract if isinstance(runtime_contract, Mapping) else {}
    return {
        "manifest_id": str(manifest.get("manifest_id", "") or ""),
        "run_id": str(manifest.get("run_id", "") or ""),
        "status": str(manifest.get("status", "unknown") or "unknown"),
        "phase": str(runtime_contract.get("phase", "unknown") or "unknown"),
        "dag_path": str(workflow.get("dag_path", "") or ""),
        "unit_count": int(workflow.get("unit_count", 0) or 0),
        "produced_count": int(contracts.get("produced_count", 0) or 0),
        "consumed_count": int(contracts.get("consumed_count", 0) or 0),
        "event_count": int(runtime_contract.get("event_count", 0) or 0),
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _read_matching_runner_state(
    *,
    state: Mapping[str, Any],
    state_path: Path,
) -> dict[str, Any]:
    """Read persisted runner state once and reject stale caller snapshots."""

    expanded = state_path.expanduser()
    try:
        raw_payload = _run_with_windows_sharing_retry(expanded.read_bytes)
    except OSError as exc:
        raise ValueError(f"Runner state could not be read for evidence: {expanded}") from exc
    try:
        persisted = json.loads(raw_payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Runner state is not valid JSON: {expanded}") from exc
    if not isinstance(persisted, Mapping):
        raise ValueError(f"Runner state must be a JSON object: {expanded}")

    persisted_snapshot = _json_safe(dict(persisted))
    caller_snapshot = _json_safe(dict(state))
    if canonical_json_bytes(persisted_snapshot) != canonical_json_bytes(caller_snapshot):
        raise ValueError(
            f"Runner state changed before evidence publication: {expanded}; "
            "reload the persisted state and retry"
        )
    return dict(persisted_snapshot)


def _json_document_text(payload: Mapping[str, Any]) -> str:
    return json.dumps(_json_safe(payload), indent=2, sort_keys=True) + "\n"


def _json_document_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_json_document_text(payload).encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = _json_document_text(payload)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        _run_with_windows_sharing_retry(lambda: os.replace(tmp_path, path))
        _fsync_directory(path.parent)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
    return path


def _write_immutable_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path = path.expanduser()
    text = _json_document_text(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing != text:
            raise FileExistsError(f"Refusing to overwrite immutable workflow evidence: {path}")
        return path

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        # Actual callers hold the stable publication lock. ``os.replace`` keeps
        # backfill portable to Windows, FAT/exFAT, and shared filesystems which
        # do not support hard links, while never exposing a partial marker.
        if path.exists():
            existing = path.read_text(encoding="utf-8")
            if existing != text:
                raise FileExistsError(f"Refusing to overwrite immutable workflow evidence: {path}")
        else:
            os.replace(tmp_path, path)
        _fsync_directory(path.parent)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
    return path


def _write_json_fsync(path: Path, payload: Mapping[str, Any]) -> None:
    text = _json_document_text(payload)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())


def _write_latest_if_newer(path: Path, payload: Mapping[str, Any]) -> bool:
    """Advance the mutable latest pointer without allowing an older run to win."""

    try:
        _run_with_windows_sharing_retry(path.stat)
    except FileNotFoundError:
        current_exists = False
    else:
        current_exists = True
    if current_exists:
        try:
            current = json.loads(
                _run_with_windows_sharing_retry(
                    lambda: path.read_text(encoding="utf-8")
                )
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid latest workflow evidence pointer: {path}") from exc
        if not isinstance(current, Mapping):
            raise ValueError(f"Invalid latest workflow evidence pointer: {path}")
        if str(current.get("kind", "")) != "agilab.latest_workflow_evidence":
            raise ValueError(f"Invalid latest workflow evidence pointer kind: {path}")
        if _latest_revision(payload) <= _latest_revision(current):
            return False
    _write_json(path, payload)
    return True


def _latest_revision(
    payload: Mapping[str, Any],
) -> tuple[tuple[int, str], int, tuple[int, str], str]:
    revision = payload.get("revision", {})
    revision = revision if isinstance(revision, Mapping) else {}
    updated_at = str(
        revision.get("updated_at", "")
        or revision.get("created_at", "")
        or payload.get("updated_at", "")
        or ""
    )
    run_created_at = str(
        revision.get("run_created_at", "")
        or revision.get("created_at", "")
        or payload.get("updated_at", "")
        or ""
    )
    try:
        event_count = int(revision.get("event_count", 0) or 0)
    except (TypeError, ValueError):
        event_count = 0
    tie_breaker = str(
        revision.get("tie_breaker", "") or payload.get("manifest_id", "") or ""
    )
    return (
        _comparable_timestamp(run_created_at),
        event_count,
        _comparable_timestamp(updated_at),
        tie_breaker,
    )


def _comparable_timestamp(value: str) -> tuple[int, str]:
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return 0, text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    normalized = parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")
    return 1, normalized


def _cleanup_stale_staging_dirs(root: Path) -> None:
    for candidate in sorted(root.glob(".*.staging"), key=lambda path: path.name):
        if candidate.is_dir() and not candidate.is_symlink():
            shutil.rmtree(candidate, ignore_errors=True)


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


def _verify_existing_bundle(
    *,
    manifest_path: Path,
    manifest: Mapping[str, Any],
    graph_path: Path,
    graph: Mapping[str, Any],
    ledger_path: Path,
    ledger: Mapping[str, Any],
    state_snapshot_path: Path,
    state_snapshot: Mapping[str, Any],
) -> None:
    expected = (
        (state_snapshot_path, state_snapshot),
        (manifest_path, manifest),
        (graph_path, graph),
        (ledger_path, ledger),
    )
    for path, payload in expected:
        text = _json_document_text(payload)
        try:
            existing = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise FileExistsError(f"Incomplete immutable workflow evidence bundle: {path.parent}") from exc
        if existing != text:
            raise FileExistsError(f"Refusing to overwrite immutable workflow evidence: {path}")
    completion_path = manifest_path.parent / WORKFLOW_EVIDENCE_COMPLETION_FILENAME
    manifest_id = str(manifest.get("manifest_id", ""))
    if completion_path.exists():
        try:
            _validate_completion_marker(manifest_path.parent, manifest_id)
        except ValueError:
            # The immutable payloads were byte-verified above, so an
            # invalid marker can only describe an incomplete/failed publish.
            completion_path.unlink()
            _fsync_directory(completion_path.parent)
    if not completion_path.exists():
        _backfill_completion_marker(manifest_path.parent, manifest_id)
    _validate_completion_marker(manifest_path.parent, manifest_id)


def _backfill_completion_marker(bundle_dir: Path, manifest_id: str) -> Path:
    completion_path = bundle_dir / WORKFLOW_EVIDENCE_COMPLETION_FILENAME
    payload = {
        "schema_version": 1,
        "kind": "agilab.workflow_evidence.complete",
        "manifest_id": manifest_id,
        "files": {
            filename: _sha256_file_or_empty(bundle_dir / filename)
            for filename in _completion_filenames(bundle_dir)
        },
    }
    return _write_immutable_json(completion_path, payload)


def _completion_filenames(
    bundle_dir: Path,
    *,
    manifest_payload: Mapping[str, Any] | None = None,
) -> tuple[str, ...]:
    filenames = [
        WORKFLOW_RUN_MANIFEST_FILENAME,
        EVIDENCE_GRAPH_FILENAME,
        EVIDENCE_LEDGER_FILENAME,
    ]
    manifest_path = bundle_dir / WORKFLOW_RUN_MANIFEST_FILENAME
    if manifest_payload is None:
        try:
            loaded_manifest = json.loads(manifest_path.read_bytes())
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid workflow evidence manifest: {manifest_path}") from exc
        manifest_payload = loaded_manifest if isinstance(loaded_manifest, Mapping) else {}
    state_snapshot = (
        manifest_payload.get("state_snapshot", {})
        if isinstance(manifest_payload, Mapping)
        else {}
    )
    if isinstance(manifest_payload, Mapping) and (
        int(manifest_payload.get("schema_version", 0) or 0) >= 4
        or isinstance(state_snapshot, Mapping) and bool(state_snapshot.get("path"))
    ):
        filenames.append(RUNNER_STATE_SNAPSHOT_FILENAME)
    return tuple(filenames)


def _validate_completion_marker(
    bundle_dir: Path,
    manifest_id: str,
    *,
    captured_files: Mapping[str, bytes] | None = None,
    manifest_payload: Mapping[str, Any] | None = None,
) -> None:
    completion_path = bundle_dir / WORKFLOW_EVIDENCE_COMPLETION_FILENAME
    try:
        payload = json.loads(completion_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Invalid workflow evidence completion marker: {completion_path}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError(f"Invalid workflow evidence completion marker: {completion_path}")
    if int(payload.get("schema_version", 0) or 0) != 1:
        raise ValueError(f"Invalid workflow evidence completion marker schema: {completion_path}")
    if str(payload.get("kind", "")) != "agilab.workflow_evidence.complete":
        raise ValueError(f"Invalid workflow evidence completion marker kind: {completion_path}")
    if str(payload.get("manifest_id", "")) != manifest_id:
        raise ValueError(f"Workflow evidence completion marker manifest mismatch: {completion_path}")
    files = payload.get("files")
    if not isinstance(files, Mapping):
        raise ValueError(f"Workflow evidence completion marker files are missing: {completion_path}")
    captured = dict(captured_files or {})
    for filename in _completion_filenames(
        bundle_dir,
        manifest_payload=manifest_payload,
    ):
        expected = str(files.get(filename, ""))
        if filename in captured:
            actual = hashlib.sha256(captured[filename]).hexdigest()
        else:
            actual = _sha256_file_or_empty(bundle_dir / filename)
        if not expected or actual != expected:
            raise ValueError(
                f"Workflow evidence completion hash mismatch for {bundle_dir / filename}"
            )


@contextmanager
def _exclusive_publication_lock(path: Path):
    """Hold a stable cross-process file lock for workflow evidence publication."""

    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    locked = False
    try:
        if os.name == "nt":  # pragma: no cover - exercised on Windows CI
            import msvcrt

            if path.stat().st_size == 0:
                handle.write(b"\n")
                handle.flush()
                os.fsync(handle.fileno())
            def _try_lock() -> None:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            def _try_lock() -> None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        deadline = time.monotonic() + _PUBLICATION_LOCK_TIMEOUT_SECONDS
        while True:
            try:
                _try_lock()
                locked = True
                break
            except OSError as exc:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"Timed out waiting for workflow-evidence publication lock {path}. "
                        "Another session may still be publishing evidence; retry after it finishes."
                    ) from exc
                time.sleep(min(_PUBLICATION_LOCK_RETRY_INTERVAL_SECONDS, remaining))
        yield
    finally:
        try:
            if locked and os.name == "nt":  # pragma: no cover - exercised on Windows CI
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            elif locked:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _safe_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    return safe or "workflow-run"


def _sha256_file_or_empty(path: Path) -> str:
    path = path.expanduser()
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repo_relative_text(path: Path, repo_root: Path) -> str:
    try:
        return path.expanduser().resolve(strict=False).relative_to(
            repo_root.expanduser().resolve(strict=False)
        ).as_posix()
    except ValueError:
        return str(path.expanduser())


def _workflow_source_path(
    source: Mapping[str, Any],
    dag_path: Path | None,
    repo_root: Path,
) -> str:
    source_dag = str(source.get("dag_path", "") or source.get("source_dag", "") or "").strip()
    if source_dag:
        return source_dag
    if dag_path is None:
        return ""
    return _repo_relative_text(dag_path, repo_root)


def _state_timestamp(state: Mapping[str, Any]) -> str:
    for key in ("updated_at", "created_at"):
        value = str(state.get(key, "") or "").strip()
        if value:
            return value
    events = state.get("events", [])
    if isinstance(events, Sequence) and not isinstance(events, (str, bytes)):
        for event in reversed(events):
            if isinstance(event, Mapping):
                timestamp = str(event.get("timestamp", "") or "").strip()
                if timestamp:
                    return timestamp
    return utc_now()


def _unit_rows(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = state.get("units", [])
    if not isinstance(rows, list):
        return []
    units = [dict(row) for row in rows if isinstance(row, Mapping)]
    units.sort(key=_unit_sort_key)
    return units


def _unit_sort_key(unit: Mapping[str, Any]) -> tuple[int, str]:
    try:
        index = int(unit.get("order_index", 999_999))
    except (TypeError, ValueError):
        index = 999_999
    return index, str(unit.get("id", ""))


def _artifact_contracts(units: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    produced: list[dict[str, str]] = []
    consumed: list[dict[str, str]] = []
    for unit in units:
        unit_id = str(unit.get("id", "") or "")
        app = str(unit.get("app", "") or "")
        for artifact in unit.get("produces", []):
            if not isinstance(artifact, Mapping):
                continue
            artifact_id = str(artifact.get("artifact", "") or artifact.get("id", "") or "").strip()
            if not artifact_id:
                continue
            produced.append(
                {
                    "artifact": artifact_id,
                    "producer": unit_id,
                    "app": app,
                    "kind": str(artifact.get("kind", "") or ""),
                    "path": str(artifact.get("path", "") or ""),
                    "status": str(artifact.get("status", "") or ""),
                }
            )
        for dependency in unit.get("artifact_dependencies", []):
            if not isinstance(dependency, Mapping):
                continue
            artifact_id = str(dependency.get("artifact", "") or "").strip()
            if not artifact_id:
                continue
            consumed.append(
                {
                    "artifact": artifact_id,
                    "consumer": unit_id,
                    "app": app,
                    "from": str(dependency.get("from", "") or ""),
                    "from_app": str(dependency.get("from_app", "") or ""),
                    "source_path": str(dependency.get("source_path", "") or ""),
                }
            )
    return produced, consumed


def _stage_record(unit: Mapping[str, Any]) -> dict[str, Any]:
    contract = unit.get("execution_contract", {})
    contract_payload = dict(contract) if isinstance(contract, Mapping) else {}
    return {
        "id": str(unit.get("id", "") or ""),
        "app": str(unit.get("app", "") or ""),
        "status": str(unit.get("dispatch_status", "") or ""),
        "order_index": unit.get("order_index"),
        "depends_on": [str(item) for item in unit.get("depends_on", [])]
        if isinstance(unit.get("depends_on"), list)
        else [],
        "produces": [
            str(item.get("artifact", "") or item.get("id", ""))
            for item in unit.get("produces", [])
            if isinstance(item, Mapping) and str(item.get("artifact", "") or item.get("id", ""))
        ],
        "execution_contract_sha256": sha256_payload(contract_payload) if contract_payload else "",
    }


def _manifest_status(state: Mapping[str, Any], units: Sequence[Mapping[str, Any]]) -> str:
    run_status = str(state.get("run_status", "") or "").strip().lower()
    statuses = {str(unit.get("dispatch_status", "") or "").strip().lower() for unit in units}
    if run_status == "failed" or "failed" in statuses:
        return "fail"
    if run_status == "completed" or (units and statuses == {"completed"}):
        return "pass"
    return "unknown"


def _manifest_validations(
    *,
    state: Mapping[str, Any],
    units: Sequence[Mapping[str, Any]],
    produced_artifacts: Sequence[Mapping[str, str]],
    consumed_artifacts: Sequence[Mapping[str, str]],
) -> list[dict[str, Any]]:
    run_status = str(state.get("run_status", "") or "").strip().lower()
    runner_schema = str(state.get("schema", "") or "").strip()
    failed_units = [
        str(unit.get("id", "") or "")
        for unit in units
        if str(unit.get("dispatch_status", "") or "").strip().lower() == "failed"
    ]
    completed_units = [
        str(unit.get("id", "") or "")
        for unit in units
        if str(unit.get("dispatch_status", "") or "").strip().lower() == "completed"
    ]
    return [
        {
            "id": "runner_state_schema",
            "status": "pass" if runner_schema else "fail",
            "summary": "runner state declares a schema" if runner_schema else "runner state schema is missing",
            "details": {"schema": runner_schema},
        },
        {
            "id": "artifact_contracts",
            "status": "pass" if produced_artifacts else "unknown",
            "summary": (
                f"{len(produced_artifacts)} produced and {len(consumed_artifacts)} consumed artifact contract(s)"
            ),
            "details": {
                "produced_count": len(produced_artifacts),
                "consumed_count": len(consumed_artifacts),
            },
        },
        {
            "id": "run_outcome",
            "status": "fail" if failed_units or run_status == "failed" else "pass"
            if units and len(completed_units) == len(units)
            else "unknown",
            "summary": _run_outcome_summary(run_status, len(units), len(completed_units), failed_units),
            "details": {
                "run_status": run_status,
                "unit_count": len(units),
                "completed_unit_count": len(completed_units),
                "failed_unit_ids": failed_units,
            },
        },
    ]


def _run_outcome_summary(
    run_status: str,
    unit_count: int,
    completed_count: int,
    failed_units: Sequence[str],
) -> str:
    if failed_units or run_status == "failed":
        return f"workflow failed; failed units: {', '.join(failed_units) or 'unknown'}"
    if unit_count and completed_count == unit_count:
        return f"workflow completed all {unit_count} unit(s)"
    return f"workflow status is {run_status or 'unknown'}; {completed_count}/{unit_count} unit(s) completed"


def _file_record(path: Path, *, name: str, kind: str) -> dict[str, Any]:
    expanded = path.expanduser()
    exists = expanded.exists()
    return {
        "name": name,
        "path": str(expanded),
        "kind": kind,
        "exists": exists,
        "size_bytes": expanded.stat().st_size if exists and expanded.is_file() else None,
        "sha256": _sha256_file_or_empty(expanded),
    }
