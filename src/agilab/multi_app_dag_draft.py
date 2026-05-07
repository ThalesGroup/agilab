from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .multi_app_dag import SCHEMA, MultiAppDagValidation, validate_multi_app_dag
from .dag_execution_registry import CONTROLLED_CONTRACT_ADAPTER, CONTROLLED_CONTRACT_RUNNER_STATUS


DEFAULT_EXECUTION = {
    "mode": "sequential_dependency_order",
    "runner_status": "contract_only",
}
CONTROLLED_CONTRACT_EXECUTION = {
    "mode": "sequential_dependency_order",
    "runner_status": CONTROLLED_CONTRACT_RUNNER_STATUS,
    "adapter": CONTROLLED_CONTRACT_ADAPTER,
}


@dataclass(frozen=True)
class DagStage:
    id: str
    app: str
    purpose: str = ""

    def as_payload(self) -> dict[str, str]:
        return {key: value for key, value in {
            "id": self.id,
            "app": self.app,
            "purpose": self.purpose,
        }.items() if value}


@dataclass(frozen=True)
class DagArtifact:
    node: str
    id: str
    kind: str = ""
    path: str = ""

    def as_node_payload(self) -> dict[str, str]:
        return {key: value for key, value in {
            "id": self.id,
            "kind": self.kind,
            "path": self.path,
        }.items() if value}


@dataclass(frozen=True)
class DagHandoff:
    source: str
    target: str
    artifact: str
    handoff: str = ""

    def as_payload(self) -> dict[str, str]:
        return {key: value for key, value in {
            "from": self.source,
            "to": self.target,
            "artifact": self.artifact,
            "handoff": self.handoff,
        }.items() if value}


@dataclass(frozen=True)
class DagDraftSpec:
    dag_id: str
    label: str
    description: str
    execution: Mapping[str, Any]
    stages: tuple[DagStage, ...]
    produced_artifacts: tuple[DagArtifact, ...]
    consumed_artifacts: tuple[DagArtifact, ...]
    handoffs: tuple[DagHandoff, ...]

    def as_payload(self, *, base_payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(base_payload or {})
        produces_by_node = _artifacts_by_node(self.produced_artifacts)
        consumes_by_node = _artifacts_by_node(self.consumed_artifacts)
        nodes: list[dict[str, Any]] = []
        for stage in self.stages:
            node = stage.as_payload()
            if produces_by_node.get(stage.id):
                node["produces"] = [artifact.as_node_payload() for artifact in produces_by_node[stage.id]]
            if consumes_by_node.get(stage.id):
                node["consumes"] = [artifact.as_node_payload() for artifact in consumes_by_node[stage.id]]
            nodes.append(node)
        payload.update(
            {
                "schema": SCHEMA,
                "dag_id": self.dag_id.strip(),
                "label": self.label.strip(),
                "description": self.description.strip(),
                "execution": dict(self.execution) if isinstance(self.execution, Mapping) else dict(DEFAULT_EXECUTION),
                "nodes": nodes,
                "edges": [handoff.as_payload() for handoff in self.handoffs],
            }
        )
        return payload


def clean_dag_cell(value: Any) -> str:
    if value is None:
        return ""
    try:
        import pandas as pd

        if pd.isna(value):
            return ""
    except (ImportError, TypeError, ValueError):
        pass
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def dag_editor_rows(value: Any, columns: Sequence[str]) -> list[dict[str, str]]:
    try:
        import pandas as pd
    except ImportError:
        pd = None  # type: ignore[assignment]

    if pd is not None and isinstance(value, pd.DataFrame):
        records = value.to_dict("records")
    elif isinstance(value, list):
        records = value
    else:
        records = []

    rows: list[dict[str, str]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        row = {column: clean_dag_cell(record.get(column)) for column in columns}
        if any(row.values()):
            rows.append(row)
    return rows


def dag_draft_spec_from_rows(
    *,
    base_payload: Mapping[str, Any],
    dag_id: str,
    label: str,
    description: str,
    stage_rows: Sequence[Mapping[str, Any]],
    produced_artifact_rows: Sequence[Mapping[str, Any]],
    consumed_artifact_rows: Sequence[Mapping[str, Any]],
    handoff_rows: Sequence[Mapping[str, Any]],
    controlled_contract_execution: bool = False,
) -> DagDraftSpec:
    execution = _execution_payload(base_payload, controlled_contract_execution=controlled_contract_execution)
    return DagDraftSpec(
        dag_id=dag_id,
        label=label,
        description=description,
        execution=execution,
        stages=tuple(
            DagStage(
                id=clean_dag_cell(row.get("id")),
                app=clean_dag_cell(row.get("app")),
                purpose=clean_dag_cell(row.get("purpose")),
            )
            for row in stage_rows
            if clean_dag_cell(row.get("id"))
        ),
        produced_artifacts=_artifact_tuple(produced_artifact_rows),
        consumed_artifacts=_artifact_tuple(consumed_artifact_rows),
        handoffs=tuple(
            DagHandoff(
                source=clean_dag_cell(row.get("from")),
                target=clean_dag_cell(row.get("to")),
                artifact=clean_dag_cell(row.get("artifact")),
                handoff=clean_dag_cell(row.get("handoff")),
            )
            for row in handoff_rows
            if clean_dag_cell(row.get("from")) or clean_dag_cell(row.get("to")) or clean_dag_cell(row.get("artifact"))
        ),
    )


def build_dag_payload_from_editor(
    base_payload: Mapping[str, Any],
    *,
    dag_id: str,
    label: str,
    description: str,
    stage_rows: Sequence[Mapping[str, Any]],
    produced_artifact_rows: Sequence[Mapping[str, Any]],
    consumed_artifact_rows: Sequence[Mapping[str, Any]],
    handoff_rows: Sequence[Mapping[str, Any]],
    controlled_contract_execution: bool = False,
) -> dict[str, Any]:
    spec = dag_draft_spec_from_rows(
        base_payload=base_payload,
        dag_id=dag_id,
        label=label,
        description=description,
        stage_rows=stage_rows,
        produced_artifact_rows=produced_artifact_rows,
        consumed_artifact_rows=consumed_artifact_rows,
        handoff_rows=handoff_rows,
        controlled_contract_execution=controlled_contract_execution,
    )
    return spec.as_payload(base_payload=base_payload)


def format_validation_issues_for_user(validation: MultiAppDagValidation) -> str:
    if validation.ok:
        return ""
    lines = ["How to fix the DAG draft:"]
    for issue in validation.issues:
        lines.append(f"- {_user_guidance_for_issue(issue.location, issue.message)}")
        lines.append(f"  Detail: {issue.location}: {issue.message}")
    return "\n".join(lines)


def format_validation_error_for_user(payload: Mapping[str, Any], *, repo_root: Path) -> str:
    return format_validation_issues_for_user(validate_multi_app_dag(payload, repo_root=repo_root))


def _artifact_tuple(rows: Sequence[Mapping[str, Any]]) -> tuple[DagArtifact, ...]:
    return tuple(
        DagArtifact(
            node=clean_dag_cell(row.get("node")),
            id=clean_dag_cell(row.get("id")),
            kind=clean_dag_cell(row.get("kind")),
            path=clean_dag_cell(row.get("path")),
        )
        for row in rows
        if clean_dag_cell(row.get("node")) or clean_dag_cell(row.get("id")) or clean_dag_cell(row.get("path"))
    )


def _execution_payload(
    base_payload: Mapping[str, Any],
    *,
    controlled_contract_execution: bool,
) -> Mapping[str, Any]:
    if controlled_contract_execution:
        return dict(CONTROLLED_CONTRACT_EXECUTION)
    execution = base_payload.get("execution")
    return execution if isinstance(execution, Mapping) else DEFAULT_EXECUTION


def _artifacts_by_node(artifacts: Sequence[DagArtifact]) -> dict[str, list[DagArtifact]]:
    grouped: dict[str, list[DagArtifact]] = {}
    for artifact in artifacts:
        if not artifact.node or not artifact.id or not artifact.path:
            continue
        grouped.setdefault(artifact.node, []).append(artifact)
    return grouped


def _user_guidance_for_issue(location: str, message: str) -> str:
    if location == "dag_id" or "dag_id is required" in message:
        return "Name the DAG with a portable DAG id."
    if location.startswith("nodes") and "at least two apps" in message:
        return "Choose stages from at least two different apps."
    if location == "nodes" or "nodes must be" in message:
        return "Choose at least two stages."
    if location == "edges" and "cross-app edge" in message:
        return "Connect stages with at least one cross-app artifact handoff."
    if location.startswith("edges") and "source node does not produce artifact" in message:
        return "Select the artifact as a produced artifact for the source stage before using it in a connection."
    if location.startswith("edges") and "target node does not consume artifact" in message:
        return "Let the editor infer consumed artifacts from the selected connection, or align the target consumed artifact."
    if location.startswith("edges") and "cycle" in message:
        return "Remove the circular dependency so stages can run in one direction."
    if "artifact path must be portable" in message:
        return "Use relative artifact paths inside the project or share, not absolute paths or parent-directory escapes."
    if "node app" in message:
        return "Choose an app from the checked-in app list."
    return message


__all__ = [
    "CONTROLLED_CONTRACT_EXECUTION",
    "DagArtifact",
    "DagDraftSpec",
    "DagHandoff",
    "DagStage",
    "build_dag_payload_from_editor",
    "clean_dag_cell",
    "dag_draft_spec_from_rows",
    "dag_editor_rows",
    "format_validation_error_for_user",
    "format_validation_issues_for_user",
]
