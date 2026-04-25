# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Read-only runner-state helpers for AGILAB global pipeline DAGs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agilab.global_pipeline_execution_plan import ExecutionPlan, build_execution_plan


SCHEMA = "agilab.global_pipeline_runner_state.v1"
RUNNER_MODE = "read_only_preview"
RUN_STATUS = "not_started"
RUNNABLE_STATUS = "runnable"
BLOCKED_STATUS = "blocked"


@dataclass(frozen=True)
class RunnerStateIssue:
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
class RunnerState:
    ok: bool
    issues: tuple[RunnerStateIssue, ...]
    schema: str
    runner_mode: str
    run_status: str
    dag_path: str
    plan_schema: str
    plan_runner_status: str
    execution_order: tuple[str, ...]
    state_units: tuple[dict[str, Any], ...]

    @property
    def unit_count(self) -> int:
        return len(self.state_units)

    @property
    def runnable_count(self) -> int:
        return sum(1 for unit in self.state_units if unit.get("dispatch_status") == RUNNABLE_STATUS)

    @property
    def blocked_count(self) -> int:
        return sum(1 for unit in self.state_units if unit.get("dispatch_status") == BLOCKED_STATUS)

    @property
    def completed_count(self) -> int:
        return sum(1 for unit in self.state_units if unit.get("dispatch_status") == "completed")

    @property
    def failed_count(self) -> int:
        return sum(1 for unit in self.state_units if unit.get("dispatch_status") == "failed")

    @property
    def runnable_unit_ids(self) -> tuple[str, ...]:
        return tuple(
            str(unit["id"])
            for unit in self.state_units
            if unit.get("dispatch_status") == RUNNABLE_STATUS
        )

    @property
    def blocked_unit_ids(self) -> tuple[str, ...]:
        return tuple(
            str(unit["id"])
            for unit in self.state_units
            if unit.get("dispatch_status") == BLOCKED_STATUS
        )

    @property
    def transition_count(self) -> int:
        return sum(len(unit.get("transitions", [])) for unit in self.state_units)

    @property
    def retry_policy_count(self) -> int:
        return sum(1 for unit in self.state_units if "retry" in unit)

    @property
    def partial_rerun_record_count(self) -> int:
        return sum(1 for unit in self.state_units if "partial_rerun" in unit)

    @property
    def operator_state_count(self) -> int:
        return sum(1 for unit in self.state_units if "operator_ui" in unit)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": [issue.as_dict() for issue in self.issues],
            "schema": self.schema,
            "runner_mode": self.runner_mode,
            "run_status": self.run_status,
            "dag_path": self.dag_path,
            "plan_schema": self.plan_schema,
            "plan_runner_status": self.plan_runner_status,
            "execution_order": list(self.execution_order),
            "unit_count": self.unit_count,
            "runnable_count": self.runnable_count,
            "blocked_count": self.blocked_count,
            "completed_count": self.completed_count,
            "failed_count": self.failed_count,
            "runnable_unit_ids": list(self.runnable_unit_ids),
            "blocked_unit_ids": list(self.blocked_unit_ids),
            "transition_count": self.transition_count,
            "retry_policy_count": self.retry_policy_count,
            "partial_rerun_record_count": self.partial_rerun_record_count,
            "operator_state_count": self.operator_state_count,
            "state_units": list(self.state_units),
        }


def _issue(location: str, message: str) -> RunnerStateIssue:
    return RunnerStateIssue(level="error", location=location, message=message)


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _artifact_names(dependencies: list[dict[str, str]]) -> list[str]:
    return [
        dependency["artifact"]
        for dependency in dependencies
        if dependency.get("artifact")
    ]


def _transition(from_status: str, to_status: str, condition: str) -> dict[str, str]:
    return {
        "from": from_status,
        "to": to_status,
        "condition": condition,
    }


def _dependency_summary(dependencies: list[dict[str, str]]) -> str:
    if not dependencies:
        return "all artifact dependencies satisfied"
    parts = [
        f"{dependency.get('artifact', 'artifact')} from {dependency.get('from', 'upstream')}"
        for dependency in dependencies
    ]
    return "waiting for " + ", ".join(parts)


def _transitions_for_unit(dependencies: list[dict[str, str]]) -> list[dict[str, str]]:
    runnable_condition = "all artifact dependencies are available"
    transitions = [
        _transition(RUNNABLE_STATUS, "completed", "app runner records successful completion"),
        _transition(RUNNABLE_STATUS, "failed", "app runner records failure"),
        _transition("failed", RUNNABLE_STATUS, "retry requested and retry budget remains"),
        _transition("completed", RUNNABLE_STATUS, "operator requests a partial rerun"),
    ]
    if dependencies:
        return [
            _transition("pending", BLOCKED_STATUS, _dependency_summary(dependencies)),
            _transition(BLOCKED_STATUS, RUNNABLE_STATUS, runnable_condition),
            *transitions,
        ]
    return [
        _transition("pending", RUNNABLE_STATUS, runnable_condition),
        *transitions,
    ]


def _operator_ui_state(unit_id: str, dependencies: list[dict[str, str]]) -> dict[str, Any]:
    artifacts = _artifact_names(dependencies)
    if dependencies:
        return {
            "state": "waiting_for_artifacts",
            "severity": "info",
            "message": f"{unit_id} is blocked until {', '.join(artifacts)} is available.",
            "blocked_by_artifacts": artifacts,
        }
    return {
        "state": "ready_to_dispatch",
        "severity": "info",
        "message": f"{unit_id} is ready for dispatch; no upstream artifacts are pending.",
        "blocked_by_artifacts": [],
    }


def _retry_metadata(unit_id: str) -> dict[str, Any]:
    return {
        "policy": "metadata_only",
        "attempt": 0,
        "max_attempts": 0,
        "status": "not_scheduled",
        "last_error": "",
        "next_action": f"configure retry policy before dispatching {unit_id}",
    }


def _partial_rerun_metadata(unit: dict[str, Any]) -> dict[str, Any]:
    produced = unit.get("produces", [])
    artifact_scope = [
        artifact.get("artifact", "")
        for artifact in produced
        if isinstance(artifact, dict) and artifact.get("artifact")
    ]
    return {
        "policy": "metadata_only",
        "requested": False,
        "eligible_after_completion": True,
        "requires_completed_dependencies": _as_str_list(unit.get("depends_on")),
        "artifact_scope": artifact_scope,
    }


def _provenance(plan: ExecutionPlan, unit: dict[str, Any]) -> dict[str, Any]:
    unit_provenance = unit.get("provenance", {})
    return {
        "source_plan_schema": plan.schema,
        "source_plan_runner_status": plan.runner_status,
        "source_dag": plan.dag_path,
        "source_unit_id": str(unit.get("id", "")),
        "source_app": str(unit.get("app", "")),
        "pipeline_view": str(unit_provenance.get("pipeline_view", "")),
        "runner_state_mode": RUNNER_MODE,
        "planning_mode": str(unit_provenance.get("planning_mode", "")),
    }


def build_runner_state(
    *,
    repo_root: Path,
    dag_path: Path | None = None,
) -> RunnerState:
    plan = build_execution_plan(repo_root=repo_root, dag_path=dag_path)
    issues = [
        _issue(f"execution_plan.{issue.location}", issue.message)
        for issue in plan.issues
    ]

    state_units: list[dict[str, Any]] = []
    for unit in plan.runnable_units:
        unit_id = str(unit.get("id", ""))
        dependencies = [
            dependency
            for dependency in unit.get("artifact_dependencies", [])
            if isinstance(dependency, dict)
        ]
        dispatch_status = RUNNABLE_STATUS if unit.get("ready") is True else BLOCKED_STATUS
        state_units.append(
            {
                "id": unit_id,
                "order_index": unit.get("order_index"),
                "app": str(unit.get("app", "")),
                "plan_status": str(unit.get("status", "")),
                "plan_runner_status": str(unit.get("runner_status", "")),
                "dispatch_status": dispatch_status,
                "depends_on": _as_str_list(unit.get("depends_on")),
                "artifact_dependencies": dependencies,
                "transitions": _transitions_for_unit(dependencies),
                "retry": _retry_metadata(unit_id),
                "partial_rerun": _partial_rerun_metadata(unit),
                "operator_ui": _operator_ui_state(unit_id, dependencies),
                "provenance": _provenance(plan, unit),
            }
        )

    return RunnerState(
        ok=plan.ok and not issues and bool(state_units),
        issues=tuple(issues),
        schema=SCHEMA,
        runner_mode=RUNNER_MODE,
        run_status=RUN_STATUS,
        dag_path=plan.dag_path,
        plan_schema=plan.schema,
        plan_runner_status=plan.runner_status,
        execution_order=plan.execution_order,
        state_units=tuple(state_units),
    )


__all__ = [
    "BLOCKED_STATUS",
    "RUNNER_MODE",
    "RUNNABLE_STATUS",
    "RUN_STATUS",
    "RunnerState",
    "RunnerStateIssue",
    "SCHEMA",
    "build_runner_state",
]
