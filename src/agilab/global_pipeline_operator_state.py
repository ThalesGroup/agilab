# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Operator-state projection for AGILAB global pipeline dispatch evidence."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from agilab.global_pipeline_app_dispatch_smoke import (
    DEFAULT_RUN_ID as DEFAULT_DISPATCH_RUN_ID,
    persist_app_dispatch_smoke,
)
from agilab.global_pipeline_dispatch_state import (
    SCHEMA as DISPATCH_STATE_SCHEMA,
    load_dispatch_state,
)


SCHEMA = "agilab.global_pipeline_operator_state.v1"
DEFAULT_RUN_ID = "global-dag-operator-state-proof"
PERSISTENCE_FORMAT = "json"
CREATED_AT = "2026-04-25T00:00:06Z"
UPDATED_AT = "2026-04-25T00:00:06Z"


@dataclass(frozen=True)
class OperatorStateIssue:
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
class OperatorStateProof:
    ok: bool
    issues: tuple[OperatorStateIssue, ...]
    path: str
    dispatch_state_path: str
    operator_state: dict[str, Any]
    reloaded_state: dict[str, Any]

    @property
    def round_trip_ok(self) -> bool:
        return self.operator_state == self.reloaded_state

    @property
    def completed_unit_ids(self) -> tuple[str, ...]:
        summary = self.operator_state.get("summary", {})
        values = summary.get("completed_unit_ids", [])
        return tuple(str(value) for value in values if str(value))

    @property
    def visible_unit_count(self) -> int:
        units = self.operator_state.get("operator_units", [])
        return len(units) if isinstance(units, list) else 0

    @property
    def retry_action_count(self) -> int:
        return _summary_int(self.operator_state, "retry_action_count")

    @property
    def partial_rerun_action_count(self) -> int:
        return _summary_int(self.operator_state, "partial_rerun_action_count")

    @property
    def handoff_count(self) -> int:
        handoffs = self.operator_state.get("handoffs", [])
        return len(handoffs) if isinstance(handoffs, list) else 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": [issue.as_dict() for issue in self.issues],
            "path": self.path,
            "dispatch_state_path": self.dispatch_state_path,
            "round_trip_ok": self.round_trip_ok,
            "visible_unit_count": self.visible_unit_count,
            "completed_unit_ids": list(self.completed_unit_ids),
            "retry_action_count": self.retry_action_count,
            "partial_rerun_action_count": self.partial_rerun_action_count,
            "handoff_count": self.handoff_count,
            "operator_state": self.operator_state,
            "reloaded_state": self.reloaded_state,
        }


def _issue(location: str, message: str) -> OperatorStateIssue:
    return OperatorStateIssue(level="error", location=location, message=message)


def _summary_int(state: Mapping[str, Any], key: str) -> int:
    summary = state.get("summary", {})
    value = summary.get(key, 0) if isinstance(summary, dict) else 0
    return int(value or 0)


def _unit_rows(dispatch_state: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    units = dispatch_state.get("units", [])
    if not isinstance(units, list):
        return ()
    return tuple(unit for unit in units if isinstance(unit, dict))


def _artifact_rows(dispatch_state: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    artifacts = dispatch_state.get("artifacts", [])
    if not isinstance(artifacts, list):
        return ()
    return tuple(artifact for artifact in artifacts if isinstance(artifact, dict))


def _artifact_ids_for_unit(artifacts: tuple[dict[str, Any], ...], unit_id: str) -> list[str]:
    return [
        str(artifact.get("artifact", ""))
        for artifact in artifacts
        if artifact.get("producer") == unit_id and artifact.get("artifact")
    ]


def _action_row(
    *,
    unit_id: str,
    action: str,
    enabled: bool,
    label: str,
    reason: str,
    artifact_scope: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": f"{unit_id}:{action}",
        "unit_id": unit_id,
        "action": action,
        "label": label,
        "enabled": enabled,
        "reason": reason,
        "artifact_scope": artifact_scope or [],
    }


def _operator_actions(
    *,
    unit: Mapping[str, Any],
    artifact_ids: list[str],
    completed_unit_ids: set[str],
) -> list[dict[str, Any]]:
    unit_id = str(unit.get("id", ""))
    status = str(unit.get("dispatch_status", ""))
    retry = unit.get("retry", {}) if isinstance(unit.get("retry"), dict) else {}
    partial_rerun = (
        unit.get("partial_rerun", {})
        if isinstance(unit.get("partial_rerun"), dict)
        else {}
    )
    required_completed = {
        str(value)
        for value in partial_rerun.get("requires_completed_dependencies", [])
        if str(value)
    }
    partial_scope = [
        str(value)
        for value in partial_rerun.get("artifact_scope", [])
        if str(value)
    ]
    completed = status == "completed"
    partial_ready = (
        completed
        and bool(partial_rerun.get("eligible_after_completion", False))
        and required_completed.issubset(completed_unit_ids)
    )
    return [
        _action_row(
            unit_id=unit_id,
            action="view_artifacts",
            enabled=bool(artifact_ids),
            label="View artifacts",
            reason=(
                "unit has available output artifacts"
                if artifact_ids
                else "unit has no available artifacts"
            ),
            artifact_scope=artifact_ids,
        ),
        _action_row(
            unit_id=unit_id,
            action="inspect_provenance",
            enabled=bool(unit.get("provenance")),
            label="Inspect provenance",
            reason="unit stores source DAG, plan, and pipeline-view provenance",
        ),
        _action_row(
            unit_id=unit_id,
            action="retry",
            enabled=completed,
            label="Retry unit",
            reason=(
                "unit completed with attempt "
                f"{retry.get('attempt', 0)}; retry can create a new persisted run"
                if completed
                else "unit must complete or fail before retry is available"
            ),
            artifact_scope=artifact_ids,
        ),
        _action_row(
            unit_id=unit_id,
            action="partial_rerun",
            enabled=partial_ready,
            label="Partial rerun",
            reason=(
                "completed dependencies are satisfied for scoped artifact regeneration"
                if partial_ready
                else "partial rerun requires completed dependencies"
            ),
            artifact_scope=partial_scope,
        ),
    ]


def _operator_unit_row(
    *,
    unit: Mapping[str, Any],
    artifacts: tuple[dict[str, Any], ...],
    completed_unit_ids: set[str],
) -> dict[str, Any]:
    unit_id = str(unit.get("id", ""))
    artifact_ids = _artifact_ids_for_unit(artifacts, unit_id)
    operator_ui = unit.get("operator_ui", {}) if isinstance(unit.get("operator_ui"), dict) else {}
    timestamps = unit.get("timestamps", {}) if isinstance(unit.get("timestamps"), dict) else {}
    real_execution = (
        unit.get("real_execution", {})
        if isinstance(unit.get("real_execution"), dict)
        else {}
    )
    return {
        "id": unit_id,
        "app": str(unit.get("app", "")),
        "operator_state": str(operator_ui.get("state") or unit.get("dispatch_status", "")),
        "severity": str(operator_ui.get("severity", "")),
        "message": str(operator_ui.get("message", "")),
        "dispatch_status": str(unit.get("dispatch_status", "")),
        "execution_mode": str(unit.get("execution_mode", "")),
        "real_execution": bool(real_execution),
        "app_entry": str(real_execution.get("app_entry", "")),
        "started_at": str(timestamps.get("started_at", "")),
        "completed_at": str(timestamps.get("completed_at", "")),
        "updated_at": str(timestamps.get("updated_at", "")),
        "artifact_ids": artifact_ids,
        "blocked_by_artifacts": list(operator_ui.get("blocked_by_artifacts", [])),
        "actions": _operator_actions(
            unit=unit,
            artifact_ids=artifact_ids,
            completed_unit_ids=completed_unit_ids,
        ),
        "provenance": dict(unit.get("provenance", {})),
    }


def _handoff_rows(
    *,
    units: tuple[dict[str, Any], ...],
    artifacts_by_id: Mapping[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for unit in units:
        for dependency in unit.get("artifact_dependencies", []):
            if not isinstance(dependency, dict):
                continue
            artifact_id = str(dependency.get("artifact", ""))
            artifact = artifacts_by_id.get(artifact_id, {})
            rows.append(
                {
                    "from": str(dependency.get("from", "")),
                    "to": str(unit.get("id", "")),
                    "artifact": artifact_id,
                    "status": str(artifact.get("status", "missing")),
                    "path": str(artifact.get("path", dependency.get("source_path", ""))),
                    "handoff": str(dependency.get("handoff", "")),
                }
            )
    return rows


def build_operator_state(
    *,
    dispatch_state: Mapping[str, Any],
    dispatch_state_path: Path | str,
    run_id: str = DEFAULT_RUN_ID,
) -> dict[str, Any]:
    units = _unit_rows(dispatch_state)
    artifacts = _artifact_rows(dispatch_state)
    artifacts_by_id = {
        str(artifact.get("artifact", "")): artifact
        for artifact in artifacts
        if artifact.get("artifact")
    }
    completed_unit_ids = {
        str(unit.get("id", ""))
        for unit in units
        if unit.get("dispatch_status") == "completed"
    }
    operator_units = [
        _operator_unit_row(
            unit=unit,
            artifacts=artifacts,
            completed_unit_ids=completed_unit_ids,
        )
        for unit in units
    ]
    action_rows = [
        action
        for unit in operator_units
        for action in unit.get("actions", [])
        if isinstance(action, dict)
    ]
    retry_action_count = sum(
        1
        for action in action_rows
        if action.get("action") == "retry" and action.get("enabled")
    )
    partial_rerun_action_count = sum(
        1
        for action in action_rows
        if action.get("action") == "partial_rerun" and action.get("enabled")
    )
    handoffs = _handoff_rows(units=units, artifacts_by_id=artifacts_by_id)
    source_summary = dispatch_state.get("summary", {})
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "persistence_format": PERSISTENCE_FORMAT,
        "run_status": "ready_for_operator_review",
        "created_at": CREATED_AT,
        "updated_at": UPDATED_AT,
        "source": {
            "dispatch_state_path": str(dispatch_state_path),
            "dispatch_state_schema": dispatch_state.get("schema", ""),
            "dispatch_run_id": dispatch_state.get("run_id", ""),
            "dispatch_run_status": dispatch_state.get("run_status", ""),
            "dispatch_real_execution_scope": (
                source_summary.get("real_execution_scope", "")
                if isinstance(source_summary, dict)
                else ""
            ),
            "source_dag": dispatch_state.get("provenance", {}).get("source_dag", ""),
            "source_runner_state_schema": dispatch_state.get("provenance", {}).get(
                "source_runner_state_schema", ""
            ),
        },
        "summary": {
            "unit_count": len(operator_units),
            "visible_unit_count": len(operator_units),
            "completed_unit_ids": sorted(completed_unit_ids),
            "operator_state_count": len(operator_units),
            "artifact_count": len(artifacts),
            "available_artifact_ids": [
                str(artifact.get("artifact", ""))
                for artifact in artifacts
                if artifact.get("status") == "available" and artifact.get("artifact")
            ],
            "handoff_count": len(handoffs),
            "operator_action_count": len(action_rows),
            "retry_action_count": retry_action_count,
            "partial_rerun_action_count": partial_rerun_action_count,
            "source_real_execution_scope": (
                source_summary.get("real_execution_scope", "")
                if isinstance(source_summary, dict)
                else ""
            ),
        },
        "operator_units": operator_units,
        "artifacts": list(artifacts),
        "handoffs": handoffs,
        "provenance": {
            "source_dispatch_state_schema": dispatch_state.get("schema", ""),
            "source_dispatch_run_id": dispatch_state.get("run_id", ""),
            "source_dispatch_state_path": str(dispatch_state_path),
            "projection_mode": "operator_state_from_persisted_dispatch_smoke",
        },
    }


def write_operator_state(path: Path, state: Mapping[str, Any]) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_operator_state(path: Path) -> dict[str, Any]:
    return json.loads(path.expanduser().read_text(encoding="utf-8"))


def persist_operator_state(
    *,
    repo_root: Path,
    output_path: Path,
    dispatch_state_path: Path | None = None,
    workspace_path: Path | None = None,
    dag_path: Path | None = None,
    run_id: str = DEFAULT_RUN_ID,
) -> OperatorStateProof:
    repo_root = repo_root.resolve()
    output_path = output_path.expanduser()
    if dispatch_state_path is None:
        generated_dispatch_state_path = (
            output_path.parent / "global_pipeline_app_dispatch_smoke_state.json"
        )
        persist_app_dispatch_smoke(
            repo_root=repo_root,
            output_path=generated_dispatch_state_path,
            run_root=workspace_path
            or (output_path.parent / "global_pipeline_operator_state_workspace"),
            dag_path=dag_path,
            run_id=DEFAULT_DISPATCH_RUN_ID,
        )
        dispatch_state_path = generated_dispatch_state_path

    dispatch_state = load_dispatch_state(dispatch_state_path)
    issues: list[OperatorStateIssue] = []
    state = build_operator_state(
        dispatch_state=dispatch_state,
        dispatch_state_path=dispatch_state_path,
        run_id=run_id,
    )
    path = write_operator_state(output_path, state)
    reloaded = load_operator_state(path)
    if state != reloaded:
        issues.append(
            _issue(
                "persistence.round_trip",
                "operator state changed after JSON write/read",
            )
        )
    if state.get("source", {}).get("dispatch_state_schema") != DISPATCH_STATE_SCHEMA:
        issues.append(
            _issue(
                "source.dispatch_state_schema",
                "operator state source is not a dispatch-state JSON",
            )
        )
    return OperatorStateProof(
        ok=not issues,
        issues=tuple(issues),
        path=str(path),
        dispatch_state_path=str(dispatch_state_path),
        operator_state=state,
        reloaded_state=reloaded,
    )


__all__ = [
    "DEFAULT_RUN_ID",
    "PERSISTENCE_FORMAT",
    "SCHEMA",
    "OperatorStateIssue",
    "OperatorStateProof",
    "build_operator_state",
    "load_operator_state",
    "persist_operator_state",
    "write_operator_state",
]
