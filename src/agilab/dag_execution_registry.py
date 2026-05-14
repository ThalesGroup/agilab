from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


GLOBAL_DAG_SAMPLE_RELATIVE_PATH = Path("docs/source/data/multi_app_dag_sample.json")
UAV_QUEUE_TEMPLATE_RELATIVE_PATH = Path(
    "src/agilab/apps/builtin/uav_queue_project/dag_templates/uav_queue_to_relay.json"
)
FLIGHT_TO_WEATHER_TEMPLATE_RELATIVE_PATH = Path(
    "src/agilab/apps/builtin/flight_telemetry_project/dag_templates/flight_to_weather.json"
)
UAV_QUEUE_ADAPTER = "uav_queue_to_relay_controlled"
CONTROLLED_CONTRACT_ADAPTER = "controlled_contract_dag"
FLIGHT_TO_WEATHER_ADAPTER = CONTROLLED_CONTRACT_ADAPTER
CONTROLLED_RUNNER_STATUS = "controlled_real_stage_execution"
CONTROLLED_CONTRACT_RUNNER_STATUS = "controlled_contract_stage_execution"
QUEUE_UNIT_ID = "queue_baseline"
RELAY_UNIT_ID = "relay_followup"
FLIGHT_CONTEXT_UNIT_ID = "flight_context"
WEATHER_FORECAST_REVIEW_UNIT_ID = "weather_forecast_review"
FLIGHT_REDUCE_SUMMARY_ARTIFACT_ID = "flight_reduce_summary"
FORECAST_METRICS_ARTIFACT_ID = "forecast_metrics"


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
    missing_stage_message: str = "This DAG does not contain the stages required by the controlled adapter."
    wrong_app_message: str = "This DAG does not map controlled stages to the expected built-in apps."


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
    missing_stage_message="This DAG does not contain the controlled queue and relay stages.",
    wrong_app_message="This DAG does not map queue and relay stages to the expected built-in apps.",
)

FLIGHT_TO_WEATHER_DAG_ADAPTER = DagExecutionAdapter(
    adapter_id=CONTROLLED_CONTRACT_ADAPTER,
    template_path=FLIGHT_TO_WEATHER_TEMPLATE_RELATIVE_PATH,
    runner_status=CONTROLLED_CONTRACT_RUNNER_STATUS,
    stage_requirements=(
        DagStageRequirement(unit_id=FLIGHT_CONTEXT_UNIT_ID, app="flight_telemetry_project"),
        DagStageRequirement(unit_id=WEATHER_FORECAST_REVIEW_UNIT_ID, app="weather_forecast_project"),
    ),
    executable_message=(
        "Controlled contract DAG execution is enabled for this checked-in app-owned DAG."
    ),
    missing_stage_message="This DAG does not contain the controlled flight and weather stages.",
    wrong_app_message="This DAG does not map flight and weather stages to the expected built-in apps.",
)

REGISTERED_DAG_EXECUTION_ADAPTERS = (UAV_QUEUE_TO_RELAY_ADAPTER, FLIGHT_TO_WEATHER_DAG_ADAPTER)
LEGACY_EXECUTABLE_DAG_PATHS = (GLOBAL_DAG_SAMPLE_RELATIVE_PATH,)
APP_OWNED_DAG_TEMPLATE_PREFIX = Path("src/agilab/apps/builtin")


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
    unit_rows = tuple(unit for unit in units if isinstance(unit, Mapping))
    if dag_path is None:
        return DagRealRunSupport(
            supported=False,
            status="Preview-only",
            message="No DAG contract is selected.",
        )

    source_resolution = _resolve_source_adapter(dag_path, repo_root)
    if isinstance(source_resolution, DagRealRunSupport):
        return source_resolution

    missing_or_wrong = _stage_requirement_mismatches(unit_rows, source_resolution)
    if missing_or_wrong == "missing":
        return DagRealRunSupport(
            supported=False,
            status="Preview-only",
            message=source_resolution.missing_stage_message,
        )
    if missing_or_wrong == "wrong_app":
        return DagRealRunSupport(
            supported=False,
            status="Preview-only",
            message=source_resolution.wrong_app_message,
        )

    contract_issue = _controlled_contract_stage_issue(unit_rows, source_resolution)
    if contract_issue:
        return DagRealRunSupport(
            supported=False,
            status="Preview-only",
            message=contract_issue,
        )

    return DagRealRunSupport(
        supported=True,
        status="Executable",
        message=source_resolution.executable_message,
        adapter=source_resolution.adapter_id,
    )


def registered_adapter_for_source(dag_path: Path, repo_root: Path) -> DagExecutionAdapter | None:
    relative = repo_relative_text(dag_path, repo_root)
    return _adapter_for_relative_path(relative)


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

    adapter = _adapter_for_relative_path(relative)
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


def _adapter_for_relative_path(relative: str) -> DagExecutionAdapter | None:
    adapter = _registered_adapter_for_relative_path(relative)
    if adapter is not None:
        return adapter
    if _is_app_owned_dag_template_path(relative):
        return DagExecutionAdapter(
            adapter_id=CONTROLLED_CONTRACT_ADAPTER,
            template_path=Path(relative),
            runner_status=CONTROLLED_CONTRACT_RUNNER_STATUS,
            stage_requirements=(),
            executable_message=(
                "Controlled contract DAG execution is enabled for this checked-in app-owned DAG."
            ),
            missing_stage_message="This DAG does not contain any executable stages.",
            wrong_app_message="This DAG contains a controlled stage that is not mapped to a checked-in built-in app.",
        )
    return None


def _is_app_owned_dag_template_path(relative: str) -> bool:
    path = Path(relative)
    parts = path.parts
    prefix_parts = APP_OWNED_DAG_TEMPLATE_PREFIX.parts
    return (
        len(parts) >= len(prefix_parts) + 3
        and parts[: len(prefix_parts)] == prefix_parts
        and parts[len(prefix_parts) + 1] == "dag_templates"
        and path.suffix == ".json"
    )


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


def _has_declared_artifact(row: Any) -> bool:
    if not isinstance(row, Mapping):
        return False
    artifact_id = str(row.get("artifact", "") or row.get("id", "")).strip()
    artifact_path = str(row.get("path", "")).strip()
    return bool(artifact_id and artifact_path)


def _has_execution_contract(row: Any) -> bool:
    if not isinstance(row, Mapping):
        return False
    entrypoint = str(row.get("entrypoint", "")).strip()
    command = row.get("command")
    has_command = (
        isinstance(command, str) and bool(command.strip())
    ) or (
        isinstance(command, list) and any(str(part).strip() for part in command)
    )
    return bool(entrypoint or has_command)


def _controlled_contract_stage_issue(
    units: Iterable[Mapping[str, Any]],
    adapter: DagExecutionAdapter,
) -> str:
    if adapter.adapter_id != CONTROLLED_CONTRACT_ADAPTER:
        return ""
    unit_rows = [unit for unit in units if isinstance(unit, Mapping)]
    if not unit_rows:
        return "This controlled contract DAG does not contain any executable stages."
    for unit in unit_rows:
        unit_id = str(unit.get("id", "")).strip() or "stage"
        produces = unit.get("produces")
        if not isinstance(produces, list) or not any(_has_declared_artifact(artifact) for artifact in produces):
            return f"Controlled contract stage `{unit_id}` must declare at least one produced artifact."
        if not _has_execution_contract(unit.get("execution_contract")):
            return f"Controlled contract stage `{unit_id}` must declare `execution.entrypoint` or `execution.command`."
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
