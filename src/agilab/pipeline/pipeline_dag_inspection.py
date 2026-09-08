"""Pure DAG inspection models shared by the WORKFLOW renderer."""

from typing import Any, Dict

from agilab.environment.logging_utils import redact_log_value

from agilab.dag.dag_execution_adapters import available_artifact_ids as _available_artifact_ids


def _workplan_artifact_id(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    return str(row.get("artifact", "") or row.get("id", "") or "").strip()



def _multi_app_dag_workplan_state(unit: dict[str, Any]) -> str:
    status = str(
        unit.get("dispatch_status", "")
        or unit.get("status", "")
        or unit.get("plan_status", "")
        or ""
    ).strip()
    return {
        "blocked": "waiting",
        "completed": "done",
        "failed": "failed",
        "planned": "planned",
        "runnable": "ready",
        "running": "running",
        "stale": "stale",
    }.get(status, status or "planned")



def _multi_app_dag_workplan_needs(unit: dict[str, Any]) -> str:
    dependencies = unit.get("artifact_dependencies", [])
    if not isinstance(dependencies, list):
        return "none"
    labels: list[str] = []
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            continue
        artifact_id = _workplan_artifact_id(dependency)
        producer = str(dependency.get("from", "") or "").strip()
        if artifact_id and producer:
            labels.append(f"{artifact_id} from {producer}")
        elif artifact_id:
            labels.append(artifact_id)
    return ", ".join(labels) if labels else "none"



def _multi_app_dag_workplan_produces(unit: dict[str, Any]) -> str:
    produced = unit.get("produces", [])
    if not isinstance(produced, list):
        return "none"
    labels = [_workplan_artifact_id(artifact) for artifact in produced]
    labels = [label for label in labels if label]
    return ", ".join(labels) if labels else "none"



def _multi_app_dag_missing_inputs(state: Dict[str, Any], unit: Dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve missing inputs against recorded artifact availability and producers."""
    available = _available_artifact_ids(state)
    units = {
        str(row["id"]): row for row in _multi_app_dag_units(state) if row.get("id")
    }
    dependencies = unit.get("artifact_dependencies", [])
    dependencies = list(dependencies) if isinstance(dependencies, list) else []
    operator_ui = unit.get("operator_ui", {})
    recorded = operator_ui.get("blocked_by_artifacts", []) if isinstance(operator_ui, dict) else []
    declared = {_workplan_artifact_id(dep) for dep in dependencies if isinstance(dep, dict)}
    if isinstance(recorded, list):
        dependencies.extend({"artifact": name} for name in recorded if isinstance(name, str) and name not in declared)
    missing = []
    seen: set[tuple[str, str]] = set()
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            continue
        artifact_id = _workplan_artifact_id(dependency)
        producer_id = str(dependency.get("from", "") or "").strip()
        if not artifact_id or artifact_id in available or (artifact_id, producer_id) in seen:
            continue
        seen.add((artifact_id, producer_id))
        producers = [producer_id] if producer_id else [
            candidate_id for candidate_id, candidate in units.items()
            if isinstance(candidate.get("produces"), list)
            and any(isinstance(item, dict) and _workplan_artifact_id(item) == artifact_id for item in candidate["produces"])
        ]
        missing.append({
            "artifact": artifact_id,
            "producers": [
                {"id": candidate_id, "state": _multi_app_dag_workplan_state(units[candidate_id]) if candidate_id in units else "not in plan"}
                for candidate_id in producers
            ],
        })
    return missing



def _multi_app_dag_units(state: Dict[str, Any]) -> list[dict[str, Any]]:
    units = state.get("units", [])
    if not isinstance(units, list):
        return []
    return [unit for unit in units if isinstance(unit, dict)]



def _multi_app_dag_executor_label(unit: Dict[str, Any]) -> str:
    executor = str(unit.get("executor", "") or "").strip()
    if executor:
        return executor

    contract = unit.get("execution_contract")
    if not isinstance(contract, dict):
        return "preview"

    entrypoint = str(contract.get("entrypoint", "")).strip()
    if entrypoint:
        return entrypoint

    command = contract.get("command")
    if isinstance(command, str) and command.strip():
        return f"command: {command.strip()}"
    if isinstance(command, list):
        command_text = " ".join(str(part).strip() for part in command if str(part).strip())
        if command_text:
            return f"command: {command_text}"
    return "preview"



def _state_units_for_display(state: Dict[str, Any]) -> list[dict[str, str]]:
    units = state.get("units", [])
    if not isinstance(units, list):
        return []
    rows: list[dict[str, str]] = []
    for unit in units:
        if not isinstance(unit, dict):
            continue
        operator_ui = unit.get("operator_ui", {})
        blocked_by = operator_ui.get("blocked_by_artifacts", []) if isinstance(operator_ui, dict) else []
        rows.append(
            {
                "unit": str(unit.get("id", "")),
                "app": str(unit.get("app", "")),
                "executor": _multi_app_dag_executor_label(unit),
                "status": _multi_app_dag_workplan_state(unit),
                "depends_on": ", ".join(str(item) for item in unit.get("depends_on", []) if str(item)),
                "blocked_by": ", ".join(
                    str(item)
                    for item in blocked_by
                    if str(item)
                ),
            }
        )
    return rows


def _multi_app_dag_stage_links(state: Dict[str, Any]) -> dict[tuple[str, str], set[str]]:
    """Resolve stage connections without conflating explicitly named producers."""
    units = {str(unit["id"]): unit for unit in _multi_app_dag_units(state) if unit.get("id")}
    producers: dict[str, set[str]] = {}
    for unit_id, unit in units.items():
        for artifact in unit.get("produces", []):
            if isinstance(artifact, dict) and _workplan_artifact_id(artifact):
                producers.setdefault(_workplan_artifact_id(artifact), set()).add(unit_id)
    links: dict[tuple[str, str], set[str]] = {}
    for unit_id, unit in units.items():
        for dependency in unit.get("artifact_dependencies", []):
            if not isinstance(dependency, dict):
                continue
            artifact_id = _workplan_artifact_id(dependency)
            source = str(dependency.get("from", "") or "")
            sources = {source} if source else producers.get(artifact_id, set())
            for source_id in sorted(sources):
                if source_id in units and source_id != unit_id:
                    links.setdefault((source_id, unit_id), set()).add(artifact_id)
        for source in unit.get("depends_on", []):
            if isinstance(source, str) and source in units and source != unit_id:
                links.setdefault((source, unit_id), set())
    return links



def _multi_app_dag_graph_state(
    state: Dict[str, Any], selected_unit_id: str, *, focus: bool,
    neighbor_offset: int = 0, neighbor_limit: int | None = None,
) -> Dict[str, Any]:
    """Keep a selected stage and its immediate artifact producers/consumers."""
    if not focus:
        return state
    raw_units = state.get("units", [])
    units = [unit for unit in raw_units if isinstance(unit, dict)] if isinstance(raw_units, list) else []
    selected = next((unit for unit in units if unit.get("id") == selected_unit_id), None)
    if selected is None:
        return state

    neighbor_ids = {
        target if source == selected_unit_id else source
        for source, target in _multi_app_dag_stage_links(state)
        if selected_unit_id in (source, target)
    }
    neighbors = [unit for unit in units if unit.get("id") in neighbor_ids]
    if neighbor_limit is not None:
        start = max(0, neighbor_offset)
        neighbors = neighbors[start:start + max(0, neighbor_limit)]
    visible_ids = {selected_unit_id, *(unit["id"] for unit in neighbors)}
    visible = [unit for unit in units if unit.get("id") in visible_ids]
    return {**state, "units": visible}



def _multi_app_dag_stage_output_rows(state: Dict[str, Any], selected: dict[str, Any]) -> list[dict[str, str]]:
    """Show declared outputs and records attributed to this stage, without file IO."""
    declared = {
        _workplan_artifact_id(artifact): artifact
        for artifact in selected.get("produces", [])
        if isinstance(artifact, dict) and _workplan_artifact_id(artifact)
    }
    records = state.get("artifacts", [])
    recorded = {
        _workplan_artifact_id(artifact): artifact
        for artifact in (records if isinstance(records, list) else [])
        if isinstance(artifact, dict) and _workplan_artifact_id(artifact)
        and artifact.get("producer") == selected.get("id")
    }
    rows = []
    for artifact_id in dict.fromkeys([*declared, *recorded]):
        record = recorded.get(artifact_id)
        artifact = record if record is not None else declared[artifact_id]
        rows.append({
            "Output": artifact_id,
            "Status": f"recorded {record.get('status', 'unknown')}" if record is not None else "planned",
            "Location": str(artifact.get("path", "") or ""),
            "Recorded at": str(artifact.get("available_at", "") or "") if record is not None else "",
            "Recorded SHA-256": str(artifact.get("sha256", "") or "") if record is not None else "",
        })
    return [{key: redact_log_value(value) for key, value in row.items()} for row in rows]
