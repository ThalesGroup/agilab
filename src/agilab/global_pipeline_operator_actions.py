# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Operator action execution proof for AGILAB global pipeline runs."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from agilab.global_pipeline_app_dispatch_smoke import (
    run_queue_baseline_app,
    run_relay_followup_app,
)
from agilab.global_pipeline_live_state_updates import (
    SCHEMA as LIVE_STATE_UPDATES_SCHEMA,
    load_live_state_updates,
    persist_live_state_updates,
)


SCHEMA = "agilab.global_pipeline_operator_actions.v1"
DEFAULT_RUN_ID = "global-dag-operator-actions-proof"
PERSISTENCE_FORMAT = "json"
CREATED_AT = "2026-04-25T00:00:14Z"
UPDATED_AT = "2026-04-25T00:00:18Z"
QUEUE_RETRY_REQUESTED_AT = "2026-04-25T00:00:14Z"
QUEUE_RETRY_COMPLETED_AT = "2026-04-25T00:00:16Z"
RELAY_PARTIAL_REQUESTED_AT = "2026-04-25T00:00:16Z"
RELAY_PARTIAL_COMPLETED_AT = "2026-04-25T00:00:18Z"


@dataclass(frozen=True)
class OperatorActionIssue:
    level: str
    location: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "level": self.level,
            "location": self.location,
            "message": self.message,
        }


@dataclass(frozen=True)
class OperatorActionProof:
    ok: bool
    issues: tuple[OperatorActionIssue, ...]
    path: str
    live_state_updates_path: str
    operator_actions: dict[str, Any]
    reloaded_actions: dict[str, Any]

    @property
    def round_trip_ok(self) -> bool:
        return self.operator_actions == self.reloaded_actions

    @property
    def action_request_count(self) -> int:
        return _summary_int(self.operator_actions, "action_request_count")

    @property
    def completed_action_count(self) -> int:
        return _summary_int(self.operator_actions, "completed_action_count")

    @property
    def retry_execution_count(self) -> int:
        return _summary_int(self.operator_actions, "retry_execution_count")

    @property
    def partial_rerun_execution_count(self) -> int:
        return _summary_int(self.operator_actions, "partial_rerun_execution_count")

    @property
    def real_action_execution_count(self) -> int:
        return _summary_int(self.operator_actions, "real_action_execution_count")

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": [issue.as_dict() for issue in self.issues],
            "path": self.path,
            "live_state_updates_path": self.live_state_updates_path,
            "round_trip_ok": self.round_trip_ok,
            "action_request_count": self.action_request_count,
            "completed_action_count": self.completed_action_count,
            "retry_execution_count": self.retry_execution_count,
            "partial_rerun_execution_count": self.partial_rerun_execution_count,
            "real_action_execution_count": self.real_action_execution_count,
            "operator_actions": self.operator_actions,
            "reloaded_actions": self.reloaded_actions,
        }


def _issue(location: str, message: str) -> OperatorActionIssue:
    return OperatorActionIssue(level="error", location=location, message=message)


def _summary_int(state: Mapping[str, Any], key: str) -> int:
    summary = state.get("summary", {})
    value = summary.get(key, 0) if isinstance(summary, dict) else 0
    return int(value or 0)


def _action_refresh(live_state_updates: Mapping[str, Any]) -> dict[str, Any]:
    updates = live_state_updates.get("updates", [])
    if not isinstance(updates, list):
        return {}
    for update in updates:
        if isinstance(update, dict) and update.get("kind") == "operator_actions_update":
            payload = update.get("payload", {})
            return payload if isinstance(payload, dict) else {}
    return {}


def _absolute_result_path(result: Mapping[str, Any], key: str) -> str:
    workspace = Path(str(result.get("workspace", "")))
    path = Path(str(result.get(key, "")))
    return str(path if path.is_absolute() else workspace / path)


def _artifact_row(
    *,
    artifact_id: str,
    producer: str,
    kind: str,
    path: str,
    metrics: Mapping[str, Any],
    available_at: str,
) -> dict[str, Any]:
    return {
        "artifact": artifact_id,
        "producer": producer,
        "kind": kind,
        "path": path,
        "status": "available",
        "available_at": available_at,
        "packets_generated": int(metrics.get("packets_generated", 0) or 0),
        "packets_delivered": int(metrics.get("packets_delivered", 0) or 0),
    }


def _action_event(
    *,
    timestamp: str,
    kind: str,
    action_id: str,
    unit_id: str,
    status: str,
    detail: str,
) -> dict[str, str]:
    return {
        "timestamp": timestamp,
        "kind": kind,
        "action_id": action_id,
        "unit_id": unit_id,
        "status": status,
        "detail": detail,
    }


def build_operator_actions(
    *,
    repo_root: Path,
    live_state_updates: Mapping[str, Any],
    live_state_updates_path: Path | str,
    action_workspace: Path,
    run_id: str = DEFAULT_RUN_ID,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    action_workspace = action_workspace.resolve()
    action_workspace.mkdir(parents=True, exist_ok=True)
    action_refresh = _action_refresh(live_state_updates)
    retry_action_ids = [
        str(value)
        for value in action_refresh.get("retry_action_ids", [])
        if str(value)
    ]
    partial_rerun_action_ids = [
        str(value)
        for value in action_refresh.get("partial_rerun_action_ids", [])
        if str(value)
    ]
    queue_retry_action_id = "queue_baseline:retry"
    relay_partial_action_id = "relay_followup:partial_rerun"
    if retry_action_ids and queue_retry_action_id not in retry_action_ids:
        queue_retry_action_id = retry_action_ids[0]
    if partial_rerun_action_ids and relay_partial_action_id not in partial_rerun_action_ids:
        relay_partial_action_id = partial_rerun_action_ids[0]

    queue_result = run_queue_baseline_app(
        repo_root=repo_root,
        run_root=action_workspace / "retry_queue_baseline",
    )
    relay_result = run_relay_followup_app(
        repo_root=repo_root,
        run_root=action_workspace / "partial_rerun_relay_followup",
        queue_result=queue_result,
    )
    queue_metrics = queue_result.get("summary_metrics", {})
    relay_metrics = relay_result.get("summary_metrics", {})
    queue_artifacts = [
        _artifact_row(
            artifact_id="queue_metrics_retry",
            producer="queue_baseline",
            kind="summary_metrics",
            path=_absolute_result_path(queue_result, "summary_metrics_path"),
            metrics=queue_metrics if isinstance(queue_metrics, dict) else {},
            available_at=QUEUE_RETRY_COMPLETED_AT,
        ),
        _artifact_row(
            artifact_id="queue_reduce_summary_retry",
            producer="queue_baseline",
            kind="reduce_artifact",
            path=_absolute_result_path(queue_result, "reduce_artifact_path"),
            metrics=queue_metrics if isinstance(queue_metrics, dict) else {},
            available_at=QUEUE_RETRY_COMPLETED_AT,
        ),
    ]
    relay_artifacts = [
        _artifact_row(
            artifact_id="relay_metrics_partial_rerun",
            producer="relay_followup",
            kind="summary_metrics",
            path=_absolute_result_path(relay_result, "summary_metrics_path"),
            metrics=relay_metrics if isinstance(relay_metrics, dict) else {},
            available_at=RELAY_PARTIAL_COMPLETED_AT,
        ),
        _artifact_row(
            artifact_id="relay_reduce_summary_partial_rerun",
            producer="relay_followup",
            kind="reduce_artifact",
            path=_absolute_result_path(relay_result, "reduce_artifact_path"),
            metrics=relay_metrics if isinstance(relay_metrics, dict) else {},
            available_at=RELAY_PARTIAL_COMPLETED_AT,
        ),
    ]
    requests = [
        {
            "id": "operator-action-001",
            "action_id": queue_retry_action_id,
            "unit_id": "queue_baseline",
            "action": "retry",
            "requested_at": QUEUE_RETRY_REQUESTED_AT,
            "completed_at": QUEUE_RETRY_COMPLETED_AT,
            "status": "completed",
            "execution_mode": "real_app_entry_action_replay",
            "attempt": 2,
            "workspace": str(action_workspace / "retry_queue_baseline"),
            "output_artifact_ids": [
                "queue_metrics_retry",
                "queue_reduce_summary_retry",
            ],
        },
        {
            "id": "operator-action-002",
            "action_id": relay_partial_action_id,
            "unit_id": "relay_followup",
            "action": "partial_rerun",
            "requested_at": RELAY_PARTIAL_REQUESTED_AT,
            "completed_at": RELAY_PARTIAL_COMPLETED_AT,
            "status": "completed",
            "execution_mode": "real_app_entry_action_replay",
            "artifact_scope": ["relay_metrics"],
            "consumed_artifact_ids": ["queue_metrics_retry"],
            "workspace": str(action_workspace / "partial_rerun_relay_followup"),
            "output_artifact_ids": [
                "relay_metrics_partial_rerun",
                "relay_reduce_summary_partial_rerun",
            ],
        },
    ]
    artifacts = [*queue_artifacts, *relay_artifacts]
    events = [
        _action_event(
            timestamp=QUEUE_RETRY_REQUESTED_AT,
            kind="action_requested",
            action_id=queue_retry_action_id,
            unit_id="queue_baseline",
            status="accepted",
            detail="operator retry request accepted for queue_baseline",
        ),
        _action_event(
            timestamp=QUEUE_RETRY_COMPLETED_AT,
            kind="action_completed",
            action_id=queue_retry_action_id,
            unit_id="queue_baseline",
            status="completed",
            detail="queue_baseline retry replay completed through the real app entry",
        ),
        _action_event(
            timestamp=RELAY_PARTIAL_REQUESTED_AT,
            kind="action_requested",
            action_id=relay_partial_action_id,
            unit_id="relay_followup",
            status="accepted",
            detail="operator partial-rerun request accepted for relay_followup",
        ),
        _action_event(
            timestamp=RELAY_PARTIAL_COMPLETED_AT,
            kind="action_completed",
            action_id=relay_partial_action_id,
            unit_id="relay_followup",
            status="completed",
            detail="relay_followup partial rerun completed through the real app entry",
        ),
    ]
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "persistence_format": PERSISTENCE_FORMAT,
        "run_status": "completed",
        "created_at": CREATED_AT,
        "updated_at": UPDATED_AT,
        "source": {
            "live_state_updates_path": str(live_state_updates_path),
            "live_state_updates_schema": live_state_updates.get("schema", ""),
            "live_state_updates_run_id": live_state_updates.get("run_id", ""),
            "live_state_updates_run_status": live_state_updates.get("run_status", ""),
            "source_real_execution_scope": live_state_updates.get("summary", {}).get(
                "source_real_execution_scope", ""
            ),
        },
        "summary": {
            "action_request_count": len(requests),
            "completed_action_count": len(
                [request for request in requests if request.get("status") == "completed"]
            ),
            "retry_execution_count": len(
                [request for request in requests if request.get("action") == "retry"]
            ),
            "partial_rerun_execution_count": len(
                [request for request in requests if request.get("action") == "partial_rerun"]
            ),
            "real_action_execution_count": len(
                [
                    request
                    for request in requests
                    if request.get("execution_mode") == "real_app_entry_action_replay"
                ]
            ),
            "output_artifact_count": len(artifacts),
            "event_count": len(events),
            "source_real_execution_scope": live_state_updates.get("summary", {}).get(
                "source_real_execution_scope", ""
            ),
        },
        "operator_controls": {
            "request_source": "json_contract",
            "ui_component": False,
            "streaming_transport": False,
        },
        "requests": requests,
        "artifacts": artifacts,
        "events": events,
        "provenance": {
            "projection_mode": "operator_action_execution_from_live_updates",
            "source_live_state_updates_schema": live_state_updates.get("schema", ""),
            "source_live_state_updates_run_id": live_state_updates.get("run_id", ""),
            "source_live_state_updates_path": str(live_state_updates_path),
        },
    }


def write_operator_actions(path: Path, actions: Mapping[str, Any]) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(actions, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_operator_actions(path: Path) -> dict[str, Any]:
    return json.loads(path.expanduser().read_text(encoding="utf-8"))


def persist_operator_actions(
    *,
    repo_root: Path,
    output_path: Path,
    live_state_updates_path: Path | None = None,
    workspace_path: Path | None = None,
    dag_path: Path | None = None,
    run_id: str = DEFAULT_RUN_ID,
) -> OperatorActionProof:
    repo_root = repo_root.resolve()
    output_path = output_path.expanduser()
    workspace_path = (
        workspace_path
        or (output_path.parent / "global_pipeline_operator_actions_workspace")
    )
    if live_state_updates_path is None:
        generated_live_state_updates_path = (
            output_path.parent / "global_pipeline_live_state_updates.json"
        )
        persist_live_state_updates(
            repo_root=repo_root,
            output_path=generated_live_state_updates_path,
            workspace_path=workspace_path / "source_live_state",
            dag_path=dag_path,
        )
        live_state_updates_path = generated_live_state_updates_path

    live_state_updates = load_live_state_updates(live_state_updates_path)
    issues: list[OperatorActionIssue] = []
    actions = build_operator_actions(
        repo_root=repo_root,
        live_state_updates=live_state_updates,
        live_state_updates_path=live_state_updates_path,
        action_workspace=workspace_path,
        run_id=run_id,
    )
    path = write_operator_actions(output_path, actions)
    reloaded = load_operator_actions(path)
    if actions != reloaded:
        issues.append(
            _issue(
                "persistence.round_trip",
                "operator actions changed after JSON write/read",
            )
        )
    if actions.get("source", {}).get("live_state_updates_schema") != LIVE_STATE_UPDATES_SCHEMA:
        issues.append(
            _issue(
                "source.live_state_updates_schema",
                "operator action source is not a live-state-updates JSON",
            )
        )
    return OperatorActionProof(
        ok=not issues,
        issues=tuple(issues),
        path=str(path),
        live_state_updates_path=str(live_state_updates_path),
        operator_actions=actions,
        reloaded_actions=reloaded,
    )


__all__ = [
    "DEFAULT_RUN_ID",
    "PERSISTENCE_FORMAT",
    "SCHEMA",
    "OperatorActionIssue",
    "OperatorActionProof",
    "build_operator_actions",
    "load_operator_actions",
    "persist_operator_actions",
    "write_operator_actions",
]
