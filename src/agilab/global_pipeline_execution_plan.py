# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Read-only execution-plan helpers for AGILAB global pipeline DAGs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shlex
from typing import Any

from agilab.global_pipeline_dag import DEFAULT_DAG_RELATIVE_PATH, GlobalPipelineDag, build_global_pipeline_dag
from agilab.multi_app_dag import load_multi_app_dag


SCHEMA = "agilab.global_pipeline_execution_plan.v1"
DEFAULT_UNIT_STATUS = "pending"
DEFAULT_RUNNER_STATUS = "not_executed"


@dataclass(frozen=True)
class ExecutionPlanIssue:
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
class ExecutionPlan:
    ok: bool
    issues: tuple[ExecutionPlanIssue, ...]
    schema: str
    runner_status: str
    dag_path: str
    graph_schema: str
    execution_order: tuple[str, ...]
    runnable_units: tuple[dict[str, Any], ...]

    @property
    def unit_count(self) -> int:
        return len(self.runnable_units)

    @property
    def pending_count(self) -> int:
        return sum(1 for unit in self.runnable_units if unit.get("status") == DEFAULT_UNIT_STATUS)

    @property
    def not_executed_count(self) -> int:
        return sum(1 for unit in self.runnable_units if unit.get("runner_status") == DEFAULT_RUNNER_STATUS)

    @property
    def ready_unit_ids(self) -> tuple[str, ...]:
        return tuple(
            str(unit["id"])
            for unit in self.runnable_units
            if unit.get("ready") is True
        )

    @property
    def blocked_unit_ids(self) -> tuple[str, ...]:
        return tuple(
            str(unit["id"])
            for unit in self.runnable_units
            if unit.get("ready") is False
        )

    @property
    def artifact_dependency_count(self) -> int:
        return sum(len(unit.get("artifact_dependencies", [])) for unit in self.runnable_units)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": [issue.as_dict() for issue in self.issues],
            "schema": self.schema,
            "runner_status": self.runner_status,
            "dag_path": self.dag_path,
            "graph_schema": self.graph_schema,
            "execution_order": list(self.execution_order),
            "unit_count": self.unit_count,
            "pending_count": self.pending_count,
            "not_executed_count": self.not_executed_count,
            "ready_unit_ids": list(self.ready_unit_ids),
            "blocked_unit_ids": list(self.blocked_unit_ids),
            "artifact_dependency_count": self.artifact_dependency_count,
            "runnable_units": list(self.runnable_units),
        }


def _issue(location: str, message: str) -> ExecutionPlanIssue:
    return ExecutionPlanIssue(level="error", location=location, message=message)


def _string_field(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    return str(value).strip() if isinstance(value, str) else ""


def _resolve_dag_path(repo_root: Path, dag_path: Path | None) -> Path:
    path = (dag_path or (repo_root / DEFAULT_DAG_RELATIVE_PATH)).expanduser()
    return path if path.is_absolute() else repo_root / path


def _payload_rows(payload: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    rows = payload.get("nodes")
    if not isinstance(rows, list):
        return ()
    return tuple(row for row in rows if isinstance(row, dict))


def _payload_edges(payload: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    rows = payload.get("edges")
    if not isinstance(rows, list):
        return ()
    return tuple(row for row in rows if isinstance(row, dict))


def _artifact_paths(rows: Any) -> dict[str, str]:
    if not isinstance(rows, list):
        return {}
    paths: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        artifact_id = str(row.get("id", "")).strip()
        path = str(row.get("path", "")).strip()
        if artifact_id:
            paths[artifact_id] = path
    return paths


def _pipeline_view_by_dag_node(graph: GlobalPipelineDag) -> dict[str, str]:
    return {view.dag_node: view.path for view in graph.app_pipeline_views}


def _artifact_dependencies(payload: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    rows_by_id = {
        _string_field(row, "id"): row
        for row in _payload_rows(payload)
        if _string_field(row, "id")
    }
    dependencies: dict[str, list[dict[str, str]]] = {node_id: [] for node_id in rows_by_id}
    for edge in _payload_edges(payload):
        source = _string_field(edge, "from")
        target = _string_field(edge, "to")
        artifact = _string_field(edge, "artifact")
        source_row = rows_by_id.get(source, {})
        source_paths = _artifact_paths(source_row.get("produces"))
        dependencies.setdefault(target, []).append(
            {
                "artifact": artifact,
                "from": source,
                "from_app": _string_field(source_row, "app"),
                "source_path": source_paths.get(artifact, ""),
                "handoff": _string_field(edge, "handoff"),
            }
        )
    return dependencies


def _produced_artifacts(row: dict[str, Any]) -> list[dict[str, str]]:
    rows = row.get("produces")
    if not isinstance(rows, list):
        return []
    artifacts: list[dict[str, str]] = []
    for artifact in rows:
        if not isinstance(artifact, dict):
            continue
        artifact_id = str(artifact.get("id", "")).strip()
        if not artifact_id:
            continue
        artifacts.append(
            {
                "artifact": artifact_id,
                "path": str(artifact.get("path", "")).strip(),
                "kind": str(artifact.get("kind", "")).strip(),
            }
        )
    return artifacts


def _execution_stage_bindings(payload: dict[str, Any]) -> dict[str, str]:
    execution = payload.get("execution")
    if not isinstance(execution, dict):
        return {}
    bindings = execution.get("stage_bindings")
    if not isinstance(bindings, dict):
        return {}
    return {
        str(stage_id).strip(): str(entrypoint).strip()
        for stage_id, entrypoint in bindings.items()
        if str(stage_id).strip() and str(entrypoint).strip()
    }


def _command_parts(value: Any) -> list[str]:
    if isinstance(value, str):
        return [part for part in shlex.split(value) if part]
    if isinstance(value, list):
        return [str(part).strip() for part in value if str(part).strip()]
    return []


def _execution_contract(row: dict[str, Any], stage_bindings: dict[str, str]) -> dict[str, Any]:
    node_id = _string_field(row, "id")
    execution = row.get("execution")
    execution = execution if isinstance(execution, dict) else {}
    entrypoint = str(execution.get("entrypoint", "")).strip() or stage_bindings.get(node_id, "")
    command = _command_parts(execution.get("command"))
    contract: dict[str, Any] = {}
    if entrypoint:
        contract["entrypoint"] = entrypoint
    if command:
        contract["command"] = command
    params = execution.get("params")
    if not isinstance(params, dict):
        params = execution.get("run_params")
    if isinstance(params, dict):
        contract["params"] = dict(params)
    steps = execution.get("steps")
    if not isinstance(steps, list):
        steps = execution.get("run_steps")
    if isinstance(steps, list):
        contract["steps"] = list(steps)
    for key in ("data_in", "data_out", "reset_target"):
        if key in execution:
            contract[key] = execution.get(key)
    for key in ("rapids_enabled", "benchmark_best_single_node"):
        if key in execution:
            contract[key] = bool(execution.get(key))
    return contract


def build_execution_plan(
    *,
    repo_root: Path,
    dag_path: Path | None = None,
) -> ExecutionPlan:
    repo_root = repo_root.resolve()
    resolved_dag_path = _resolve_dag_path(repo_root, dag_path)
    graph = build_global_pipeline_dag(repo_root=repo_root, dag_path=resolved_dag_path)
    payload = load_multi_app_dag(resolved_dag_path)
    rows_by_id = {
        _string_field(row, "id"): row
        for row in _payload_rows(payload)
        if _string_field(row, "id")
    }
    dependencies = _artifact_dependencies(payload)
    pipeline_views = _pipeline_view_by_dag_node(graph)
    stage_bindings = _execution_stage_bindings(payload)
    issues = [
        _issue(f"global_pipeline_dag.{issue.location}", issue.message)
        for issue in graph.issues
    ]

    runnable_units: list[dict[str, Any]] = []
    for order_index, node_id in enumerate(graph.execution_order):
        row = rows_by_id.get(node_id)
        if row is None:
            issues.append(_issue(f"units[{order_index}]", f"execution node {node_id!r} is missing"))
            continue
        app = _string_field(row, "app")
        artifact_dependencies = dependencies.get(node_id, [])
        unit: dict[str, Any] = {
            "id": node_id,
            "order_index": order_index,
            "app": app,
            "status": DEFAULT_UNIT_STATUS,
            "runner_status": DEFAULT_RUNNER_STATUS,
            "ready": not artifact_dependencies,
            "depends_on": [dependency["from"] for dependency in artifact_dependencies],
            "artifact_dependencies": artifact_dependencies,
            "produces": _produced_artifacts(row),
            "provenance": {
                "source_dag": graph.dag_path,
                "source_graph_schema": graph.schema,
                "source_graph_runner_status": graph.runner_status,
                "pipeline_view": pipeline_views.get(node_id, ""),
                "contract_node_id": node_id,
                "contract_app": app,
                "planning_mode": "read_only",
            },
        }
        execution_contract = _execution_contract(row, stage_bindings)
        if execution_contract:
            unit["execution_contract"] = execution_contract
        runnable_units.append(unit)

    return ExecutionPlan(
        ok=graph.ok and not issues and bool(runnable_units),
        issues=tuple(issues),
        schema=SCHEMA,
        runner_status=DEFAULT_RUNNER_STATUS,
        dag_path=graph.dag_path,
        graph_schema=graph.schema,
        execution_order=graph.execution_order,
        runnable_units=tuple(runnable_units),
    )


__all__ = [
    "DEFAULT_RUNNER_STATUS",
    "DEFAULT_UNIT_STATUS",
    "ExecutionPlan",
    "ExecutionPlanIssue",
    "SCHEMA",
    "build_execution_plan",
]
