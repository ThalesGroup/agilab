from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


GLOBAL_DAG_SAMPLE_RELATIVE_PATH = Path("docs/source/data/multi_app_dag_sample.json")
UAV_QUEUE_TEMPLATE_RELATIVE_PATH = Path(
    "src/agilab/apps/builtin/uav_queue_project/dag_templates/uav_queue_to_relay.json"
)
UAV_QUEUE_ADAPTER = "uav_queue_to_relay_controlled"
CONTROLLED_RUNNER_STATUS = "controlled_real_stage_execution"
QUEUE_UNIT_ID = "queue_baseline"
RELAY_UNIT_ID = "relay_followup"


@dataclass(frozen=True)
class DagStageRequirement:
    unit_id: str
    app: str


@dataclass(frozen=True)
class DagExecutionAdapter:
    adapter_id: str
    template_path: Path
    runner_status: str
    stage_requirements: tuple[DagStageRequirement, ...]
    executable_message: str


@dataclass(frozen=True)
class DagRealRunSupport:
    supported: bool
    status: str
    message: str
    adapter: str = ""


UAV_QUEUE_TO_RELAY_ADAPTER = DagExecutionAdapter(
    adapter_id=UAV_QUEUE_ADAPTER,
    template_path=UAV_QUEUE_TEMPLATE_RELATIVE_PATH,
    runner_status=CONTROLLED_RUNNER_STATUS,
    stage_requirements=(
        DagStageRequirement(unit_id=QUEUE_UNIT_ID, app="uav_queue_project"),
        DagStageRequirement(unit_id=RELAY_UNIT_ID, app="uav_relay_queue_project"),
    ),
    executable_message="Controlled AGILAB execution is enabled for this checked-in UAV queue-to-relay DAG.",
)

REGISTERED_DAG_EXECUTION_ADAPTERS = (UAV_QUEUE_TO_RELAY_ADAPTER,)
LEGACY_EXECUTABLE_DAG_PATHS = (GLOBAL_DAG_SAMPLE_RELATIVE_PATH,)


def repo_relative_text(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(repo_root.resolve(strict=False)).as_posix()
    except ValueError:
        return str(path.expanduser())


def resolve_real_run_support(
    *,
    units: Iterable[Mapping[str, Any]],
    dag_path: Path | None,
    repo_root: Path,
) -> DagRealRunSupport:
    if dag_path is None:
        return DagRealRunSupport(
            supported=False,
            status="Preview-only",
            message="No DAG contract is selected.",
        )

    source_resolution = _resolve_source_adapter(dag_path, repo_root)
    if isinstance(source_resolution, DagRealRunSupport):
        return source_resolution

    missing_or_wrong = _stage_requirement_mismatches(units, source_resolution)
    if missing_or_wrong == "missing":
        return DagRealRunSupport(
            supported=False,
            status="Preview-only",
            message="This DAG does not contain the controlled queue and relay stages.",
        )
    if missing_or_wrong == "wrong_app":
        return DagRealRunSupport(
            supported=False,
            status="Preview-only",
            message="This DAG does not map queue and relay stages to the expected built-in apps.",
        )

    return DagRealRunSupport(
        supported=True,
        status="Executable",
        message=source_resolution.executable_message,
        adapter=source_resolution.adapter_id,
    )


def registered_adapter_for_source(dag_path: Path, repo_root: Path) -> DagExecutionAdapter | None:
    relative = repo_relative_text(dag_path, repo_root)
    return _registered_adapter_for_relative_path(relative)


def adapter_marker_status(dag_path: Path, adapter: DagExecutionAdapter) -> DagRealRunSupport | None:
    execution = _dag_execution_payload(dag_path)
    if str(execution.get("runner_status", "")).strip() != adapter.runner_status:
        return DagRealRunSupport(
            supported=False,
            status="Preview-only",
            message="The app-owned DAG template is missing the controlled execution status marker.",
        )
    if str(execution.get("adapter", "")).strip() != adapter.adapter_id:
        return DagRealRunSupport(
            supported=False,
            status="Preview-only",
            message="The app-owned DAG template is missing the controlled execution adapter marker.",
        )
    return None


def _resolve_source_adapter(
    dag_path: Path,
    repo_root: Path,
) -> DagExecutionAdapter | DagRealRunSupport:
    relative = repo_relative_text(dag_path, repo_root)
    legacy_adapter = _legacy_adapter_for_relative_path(relative)
    if legacy_adapter is not None:
        return legacy_adapter

    adapter = _registered_adapter_for_relative_path(relative)
    if adapter is None:
        return DagRealRunSupport(
            supported=False,
            status="Preview-only",
            message=(
                "No controlled execution adapter is registered for this DAG source. "
                "Workspace and custom DAGs remain preview-only."
            ),
        )

    marker_status = adapter_marker_status(dag_path, adapter)
    if marker_status is not None:
        return marker_status
    return adapter


def _legacy_adapter_for_relative_path(relative: str) -> DagExecutionAdapter | None:
    if relative in {path.as_posix() for path in LEGACY_EXECUTABLE_DAG_PATHS}:
        return UAV_QUEUE_TO_RELAY_ADAPTER
    return None


def _registered_adapter_for_relative_path(relative: str) -> DagExecutionAdapter | None:
    for adapter in REGISTERED_DAG_EXECUTION_ADAPTERS:
        if relative == adapter.template_path.as_posix():
            return adapter
    return None


def _stage_requirement_mismatches(
    units: Iterable[Mapping[str, Any]],
    adapter: DagExecutionAdapter,
) -> str:
    unit_by_id = {str(unit.get("id", "")): unit for unit in units if isinstance(unit, Mapping)}
    for requirement in adapter.stage_requirements:
        unit = unit_by_id.get(requirement.unit_id)
        if not isinstance(unit, Mapping):
            return "missing"
        if str(unit.get("app", "")) != requirement.app:
            return "wrong_app"
    return ""


def _dag_execution_payload(dag_path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(dag_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    execution = payload.get("execution")
    return execution if isinstance(execution, Mapping) else {}
