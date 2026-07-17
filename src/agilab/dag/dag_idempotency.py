"""Crash-durable idempotency guards for DAG side-effect boundaries."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Callable, Mapping

from agilab.global_pipeline.global_pipeline_runner_state import (
    _ensure_directory_hierarchy_durable,
    _fsync_runner_state_directory,
)


class DagExternalExecutionUncertainError(RuntimeError):
    """Raised when a callback may have produced a side effect before failing."""

    def __init__(
        self,
        *,
        unit_id: str,
        idempotency_token: str,
        detail: str,
    ) -> None:
        self.unit_id = unit_id
        self.idempotency_token = idempotency_token
        self.detail = detail
        super().__init__(
            f"DAG stage `{unit_id}` may have produced a side effect for token "
            f"`{idempotency_token}`: {detail}. Exact-token recovery is required."
        )


def fsync_directory(path: Path) -> None:
    """Flush one directory or fail before a guarded callback may start."""

    if not _fsync_runner_state_directory(path):
        raise OSError(f"Could not durably flush directory metadata: {path}")


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> Path:
    """Atomically replace JSON and durably flush its parent directory."""

    if not _ensure_directory_hierarchy_durable(path.parent):
        raise OSError(f"Could not durably create directory hierarchy: {path.parent}")
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        stream = os.fdopen(fd, "w", encoding="utf-8")
        fd = -1
        with stream:
            json.dump(payload, stream, indent=2, sort_keys=True, default=str)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_path, path)
        fsync_directory(path.parent)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
    return path


def execute_idempotently(
    *,
    run_root: Path,
    unit_id: str,
    idempotency_token: str,
    callback: Callable[[], Mapping[str, Any]],
    scope: str = "adapter",
) -> dict[str, Any]:
    """Execute a callback once per durable scope/token ledger claim."""

    token = str(idempotency_token).strip()
    guard_scope = str(scope).strip()
    if not token:
        raise RuntimeError(f"DAG stage `{unit_id}` requires an idempotency token.")
    if not guard_scope:
        raise RuntimeError(f"DAG stage `{unit_id}` requires an idempotency guard scope.")
    ledger_path, cached_result = _begin_execution(
        run_root=run_root,
        unit_id=unit_id,
        idempotency_token=token,
        scope=guard_scope,
    )
    if cached_result is not None:
        return cached_result
    try:
        result = dict(callback())
    except DagExternalExecutionUncertainError as exc:
        try:
            _write_ledger(
                ledger_path,
                unit_id=unit_id,
                idempotency_token=token,
                scope=guard_scope,
                status="failed",
                error=str(exc),
            )
        finally:
            # Preserve the original side-effect boundary and token instead of
            # obscuring it under nested adapter/submitter guards.
            raise
    except BaseException as exc:
        detail = str(exc).strip() or type(exc).__name__
        try:
            _write_ledger(
                ledger_path,
                unit_id=unit_id,
                idempotency_token=token,
                scope=guard_scope,
                status="failed",
                error=detail,
            )
        finally:
            raise DagExternalExecutionUncertainError(
                unit_id=unit_id,
                idempotency_token=token,
                detail=detail,
            ) from exc
    result_token = str(result.get("idempotency_token", "")).strip()
    if result_token and result_token != token:
        detail = "execution result returned a mismatched idempotency token"
        _write_ledger(
            ledger_path,
            unit_id=unit_id,
            idempotency_token=token,
            scope=guard_scope,
            status="failed",
            error=detail,
        )
        raise DagExternalExecutionUncertainError(
            unit_id=unit_id,
            idempotency_token=token,
            detail=detail,
        )
    result["idempotency_token"] = token
    _write_ledger(
        ledger_path,
        unit_id=unit_id,
        idempotency_token=token,
        scope=guard_scope,
        status="completed",
        result=result,
    )
    return result


def _begin_execution(
    *,
    run_root: Path,
    unit_id: str,
    idempotency_token: str,
    scope: str,
) -> tuple[Path, dict[str, Any] | None]:
    ledger_dir = run_root / ".agilab-idempotency"
    if not _ensure_directory_hierarchy_durable(ledger_dir):
        raise OSError(f"Could not durably create idempotency ledger directory: {ledger_dir}")
    token_digest = hashlib.sha256(f"{scope}\0{idempotency_token}".encode()).hexdigest()
    ledger_path = ledger_dir / f"{token_digest}.json"
    try:
        fd = os.open(ledger_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        try:
            recorded = json.loads(ledger_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            recorded = {}
        matches_claim = (
            isinstance(recorded, Mapping)
            and recorded.get("unit_id") == unit_id
            and recorded.get("idempotency_token") == idempotency_token
            and recorded.get("scope") == scope
        )
        if matches_claim and recorded.get("status") == "completed":
            result = recorded.get("result")
            if isinstance(result, Mapping):
                return ledger_path, dict(result)
        status = str(recorded.get("status", "running")) if isinstance(recorded, Mapping) else "running"
        raise DagExternalExecutionUncertainError(
            unit_id=unit_id,
            idempotency_token=idempotency_token,
            detail=f"the durable `{scope}` ledger is already {status}",
        ) from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(
                _ledger_payload(
                    unit_id=unit_id,
                    idempotency_token=idempotency_token,
                    scope=scope,
                    status="running",
                ),
                stream,
                indent=2,
                sort_keys=True,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        fsync_directory(ledger_dir)
    except BaseException:
        # Retain even a partial exclusive claim so a second process fails closed.
        raise
    return ledger_path, None


def _write_ledger(
    path: Path,
    *,
    unit_id: str,
    idempotency_token: str,
    scope: str,
    status: str,
    result: Mapping[str, Any] | None = None,
    error: str = "",
) -> None:
    write_json_atomic(
        path,
        _ledger_payload(
            unit_id=unit_id,
            idempotency_token=idempotency_token,
            scope=scope,
            status=status,
            result=result,
            error=error,
        ),
    )


def _ledger_payload(
    *,
    unit_id: str,
    idempotency_token: str,
    scope: str,
    status: str,
    result: Mapping[str, Any] | None = None,
    error: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "agilab.dag_stage_idempotency.v1",
        "unit_id": unit_id,
        "idempotency_token": idempotency_token,
        "scope": scope,
        "status": status,
    }
    if result is not None:
        payload["result"] = dict(result)
    if error:
        payload["error"] = error
    return payload


__all__ = [
    "DagExternalExecutionUncertainError",
    "execute_idempotently",
    "fsync_directory",
    "write_json_atomic",
]
