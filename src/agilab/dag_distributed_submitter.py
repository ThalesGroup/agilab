from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .orchestrate_page_support import compute_run_mode


@dataclass(frozen=True)
class DagDistributedStageConfig:
    scheduler: str
    workers: dict[str, int]
    workers_data_path: str
    mode: int
    verbose: int = 0

    @property
    def worker_nodes(self) -> int:
        return len(self.workers)

    @property
    def worker_slots(self) -> int:
        return sum(self.workers.values())


DagStageRunner = Callable[..., Mapping[str, Any]]


def load_dag_distributed_settings(env: Any, app_settings: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Load active app settings, with in-memory Streamlit settings taking precedence."""
    file_settings = _load_settings_file(getattr(env, "app_settings_file", None))
    if not isinstance(app_settings, Mapping):
        return file_settings

    merged = dict(file_settings)
    for key, value in app_settings.items():
        if key == "cluster" and isinstance(value, Mapping):
            file_cluster = merged.get("cluster")
            cluster = dict(file_cluster) if isinstance(file_cluster, Mapping) else {}
            cluster.update(dict(value))
            merged["cluster"] = cluster
        else:
            merged[key] = value
    return merged


def dag_distributed_stage_config_from_settings(
    settings: Mapping[str, Any],
    *,
    verbose: int = 0,
) -> DagDistributedStageConfig | None:
    cluster_params = settings.get("cluster")
    if not isinstance(cluster_params, Mapping) or not bool(cluster_params.get("cluster_enabled", False)):
        return None

    scheduler = str(cluster_params.get("scheduler", "") or "").strip()
    workers = _coerce_workers(cluster_params.get("workers"))
    workers_data_path = str(cluster_params.get("workers_data_path", "") or "").strip()
    if not scheduler or not workers or not workers_data_path:
        return None

    mode = compute_run_mode(cluster_params, cluster_enabled=True)
    return DagDistributedStageConfig(
        scheduler=scheduler,
        workers=workers,
        workers_data_path=workers_data_path,
        mode=mode,
        verbose=int(verbose or 0),
    )


def build_global_dag_distributed_stage_submitter(
    *,
    env: Any,
    app_settings: Mapping[str, Any] | None = None,
    verbose: int = 0,
    runner_fn: DagStageRunner | None = None,
) -> Callable[..., Mapping[str, Any]] | None:
    settings = load_dag_distributed_settings(env, app_settings)
    config = dag_distributed_stage_config_from_settings(settings, verbose=verbose)
    if config is None:
        return None
    runner = runner_fn or run_agilab_stage_subprocess

    def _submit_stage(
        *,
        repo_root: Path,
        lab_dir: Path,
        run_root: Path,
        unit: dict[str, Any],
        artifact: dict[str, Any],
        execution_contract: dict[str, Any],
        timestamp: str,
    ) -> Mapping[str, Any]:
        return submit_distributed_stage(
            config=config,
            runner_fn=runner,
            repo_root=repo_root,
            lab_dir=lab_dir,
            run_root=run_root,
            unit=unit,
            artifact=artifact,
            execution_contract=execution_contract,
            timestamp=timestamp,
        )

    return _submit_stage


def build_distributed_request_preview_rows(
    state: Mapping[str, Any],
    *,
    repo_root: Path,
    config: DagDistributedStageConfig,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    units = state.get("units")
    if not isinstance(units, list):
        return rows
    for unit in units:
        if not isinstance(unit, Mapping):
            continue
        contract = unit.get("execution_contract")
        if not isinstance(contract, Mapping) or not contract:
            continue
        unit_id = str(unit.get("id", "") or "stage").strip() or "stage"
        app_name = str(unit.get("app", "") or "").strip()
        request_payload = request_payload_from_execution_contract(contract)
        rows.append(
            {
                "Stage": unit_id,
                "App": app_name or "-",
                "Status": str(unit.get("dispatch_status", "") or "-"),
                "Backend": "distributed",
                "Nodes": str(config.worker_nodes),
                "Worker slots": str(config.worker_slots),
                "Scheduler": config.scheduler,
                "Workers Data Path": config.workers_data_path,
                "Mode": str(config.mode),
                "Apps path": _preview_apps_path(repo_root, app_name),
                "Request": _compact_json(request_payload),
            }
        )
    return rows


def submit_distributed_stage(
    *,
    config: DagDistributedStageConfig,
    runner_fn: DagStageRunner,
    repo_root: Path,
    lab_dir: Path,
    run_root: Path,
    unit: Mapping[str, Any],
    artifact: Mapping[str, Any],
    execution_contract: Mapping[str, Any],
    timestamp: str,
) -> Mapping[str, Any]:
    unit_id = str(unit.get("id", "") or "stage").strip() or "stage"
    app_name = str(unit.get("app", "") or "").strip()
    if not app_name:
        raise RuntimeError(f"Distributed DAG stage `{unit_id}` is missing its app name.")

    apps_path = resolve_stage_apps_path(repo_root, app_name)
    request_payload = request_payload_from_execution_contract(execution_contract)
    run_root.mkdir(parents=True, exist_ok=True)

    runner_result = dict(
        runner_fn(
            config=config,
            repo_root=repo_root,
            lab_dir=lab_dir,
            run_root=run_root,
            apps_path=apps_path,
            app_name=app_name,
            unit=dict(unit),
            artifact=dict(artifact),
            execution_contract=dict(execution_contract),
            request_payload=request_payload,
            timestamp=timestamp,
        )
    )
    evidence_path = _distributed_evidence_path(run_root, artifact)
    evidence_payload = {
        "schema": "agilab.distributed_dag_stage_submission.v1",
        "unit_id": unit_id,
        "app": app_name,
        "apps_path": str(apps_path),
        "artifact": dict(artifact),
        "created_at": timestamp,
        "execution_contract": dict(execution_contract),
        "request_payload": request_payload,
        "cluster": {
            "scheduler": config.scheduler,
            "workers": config.workers,
            "workers_data_path": config.workers_data_path,
            "mode": config.mode,
            "worker_nodes": config.worker_nodes,
            "worker_slots": config.worker_slots,
        },
        "runner_result": _jsonable(runner_result),
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    default_metrics = {
        "stage_completed": 1,
        "distributed_submissions": 1,
        "worker_nodes": config.worker_nodes,
        "worker_slots": config.worker_slots,
    }
    runner_metrics = runner_result.get("summary_metrics")
    if isinstance(runner_metrics, Mapping):
        default_metrics.update(runner_metrics)

    result: dict[str, Any] = {
        "contract_artifact_path": str(evidence_path),
        "reduce_artifact_path": str(evidence_path),
        "summary_metrics_path": str(evidence_path),
        "submission_evidence_path": str(evidence_path),
        "summary_metrics": default_metrics,
        "distributed_submission": {
            "app": app_name,
            "apps_path": str(apps_path),
            "scheduler": config.scheduler,
            "workers": config.workers,
            "workers_data_path": config.workers_data_path,
            "mode": config.mode,
        },
    }
    result.update(runner_result)
    result["summary_metrics"] = default_metrics
    result.setdefault("submission_evidence_path", str(evidence_path))
    return result


def run_agilab_stage_subprocess(
    *,
    config: DagDistributedStageConfig,
    repo_root: Path,
    run_root: Path,
    apps_path: Path,
    app_name: str,
    request_payload: Mapping[str, Any],
    timestamp: str,
    **_kwargs: Any,
) -> Mapping[str, Any]:
    run_root.mkdir(parents=True, exist_ok=True)
    script_path = run_root / "run_distributed_stage.py"
    script_path.write_text(
        _stage_run_script(
            config=config,
            apps_path=apps_path,
            app_name=app_name,
            request_payload=request_payload,
        ),
        encoding="utf-8",
    )
    command = [sys.executable, str(script_path)]
    stdout_path = run_root / "distributed_stage.stdout.log"
    stderr_path = run_root / "distributed_stage.stderr.log"
    # Do not use capture_output here: AGI stages may launch background Dask
    # processes which inherit pipe file descriptors and prevent EOF.
    with stdout_path.open("w", encoding="utf-8") as stdout_handle, stderr_path.open(
        "w",
        encoding="utf-8",
    ) as stderr_handle:
        completed = subprocess.run(
            command,
            cwd=repo_root,
            env=os.environ.copy(),
            text=True,
            stdout=stdout_handle,
            stderr=stderr_handle,
            check=False,
        )
    stdout_tail = _tail_file(stdout_path)
    stderr_tail = _tail_file(stderr_path)
    payload = {
        "created_at": timestamp,
        "command": command,
        "script": str(script_path),
        "returncode": completed.returncode,
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
    }
    if completed.returncode:
        detail = stderr_tail.strip() or stdout_tail.strip() or f"exit {completed.returncode}"
        raise RuntimeError(f"Distributed DAG stage `{app_name}` failed: {_tail(detail, max_chars=4000)}")
    return payload


def resolve_stage_apps_path(repo_root: Path, app_name: str) -> Path:
    candidates = (
        repo_root / "src" / "agilab" / "apps" / "builtin",
        repo_root / "src" / "agilab" / "apps",
    )
    for apps_path in candidates:
        app_path = apps_path / app_name
        if app_path.is_dir():
            return apps_path
    raise RuntimeError(
        f"Distributed DAG stage app `{app_name}` was not found under "
        "`src/agilab/apps/builtin` or `src/agilab/apps`."
    )


def request_payload_from_execution_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
    params = contract.get("params") or contract.get("run_params") or {}
    steps = contract.get("steps") or contract.get("run_steps") or []
    payload: dict[str, Any] = {
        "params": dict(params) if isinstance(params, Mapping) else {},
        "steps": list(steps) if isinstance(steps, list) else [],
        "data_in": contract.get("data_in"),
        "data_out": contract.get("data_out"),
        "reset_target": contract.get("reset_target"),
        "rapids_enabled": bool(contract.get("rapids_enabled", False)),
        "benchmark_best_single_node": bool(contract.get("benchmark_best_single_node", False)),
    }
    return payload


def _preview_apps_path(repo_root: Path, app_name: str) -> str:
    if not app_name:
        return "-"
    try:
        apps_path = resolve_stage_apps_path(repo_root, app_name)
    except RuntimeError:
        return "missing"
    try:
        return apps_path.resolve(strict=False).relative_to(repo_root.resolve(strict=False)).as_posix()
    except ValueError:
        return str(apps_path)


def _compact_json(value: Mapping[str, Any]) -> str:
    return json.dumps(_jsonable(dict(value)), sort_keys=True, separators=(",", ":"))


def _stage_run_script(
    *,
    config: DagDistributedStageConfig,
    apps_path: Path,
    app_name: str,
    request_payload: Mapping[str, Any],
) -> str:
    request_json = json.dumps(dict(request_payload), sort_keys=True)
    workers_json = json.dumps(config.workers, sort_keys=True)
    return f'''\
import asyncio
import json

from agi_cluster.agi_distributor import AGI, RunRequest, StepRequest
from agi_env import AgiEnv


APPS_PATH = {str(apps_path)!r}
APP = {app_name!r}
REQUEST_PAYLOAD = json.loads({request_json!r})
WORKERS = json.loads({workers_json!r})


async def main():
    app_env = AgiEnv(apps_path=APPS_PATH, app=APP, verbose={int(config.verbose)!r})
    await AGI.install(
        app_env,
        scheduler={config.scheduler!r},
        workers=WORKERS,
        workers_data_path={config.workers_data_path!r},
        modes_enabled={int(config.mode)!r},
        verbose={int(config.verbose)!r},
    )
    steps = [
        StepRequest(name=step["name"], args=step.get("args") or {{}})
        for step in REQUEST_PAYLOAD.get("steps", [])
    ]
    request = RunRequest(
        params=REQUEST_PAYLOAD.get("params") or {{}},
        steps=steps,
        data_in=REQUEST_PAYLOAD.get("data_in"),
        data_out=REQUEST_PAYLOAD.get("data_out"),
        reset_target=REQUEST_PAYLOAD.get("reset_target"),
        scheduler={config.scheduler!r},
        workers=WORKERS,
        workers_data_path={config.workers_data_path!r},
        verbose={int(config.verbose)!r},
        mode={int(config.mode)!r},
        rapids_enabled=bool(REQUEST_PAYLOAD.get("rapids_enabled", False)),
        benchmark_best_single_node=bool(REQUEST_PAYLOAD.get("benchmark_best_single_node", False)),
    )
    result = await AGI.run(app_env, request=request)
    print(json.dumps({{"result": result}}, default=str))


if __name__ == "__main__":
    asyncio.run(main())
'''


def _distributed_evidence_path(run_root: Path, artifact: Mapping[str, Any]) -> Path:
    artifact_id = str(artifact.get("artifact", "") or artifact.get("id", "") or "stage_result").strip()
    declared_path = str(artifact.get("path", "") or "").strip()
    declared = Path(declared_path)
    if declared_path and not declared.is_absolute() and ".." not in declared.parts:
        return run_root / declared
    return run_root / f"{artifact_id}.json"


def _load_settings_file(path_value: Any) -> dict[str, Any]:
    if path_value in (None, ""):
        return {}
    path = Path(path_value)
    try:
        with path.open("rb") as handle:
            loaded = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return dict(loaded) if isinstance(loaded, Mapping) else {}


def _coerce_workers(value: Any) -> dict[str, int]:
    if isinstance(value, str):
        value = _loads_mapping_text(value)
    if not isinstance(value, Mapping):
        return {}
    workers: dict[str, int] = {}
    for host, slots in value.items():
        host_text = str(host).strip()
        try:
            slot_count = int(slots)
        except (TypeError, ValueError):
            continue
        if host_text and slot_count > 0:
            workers[host_text] = slot_count
    return workers


def _loads_mapping_text(value: str) -> Mapping[str, Any] | None:
    text = value.strip()
    if not text:
        return None
    for loader in (json.loads, ast.literal_eval):
        try:
            loaded = loader(text)
        except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
            continue
        return loaded if isinstance(loaded, Mapping) else None
    return None


def _tail(text: str, *, max_chars: int = 20000) -> str:
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _tail_file(path: Path, *, max_chars: int = 20000) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - (max_chars * 4)))
            data = handle.read()
    except OSError:
        return ""
    return _tail(data.decode("utf-8", errors="replace"), max_chars=max_chars)


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        if isinstance(value, Mapping):
            return {str(key): _jsonable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [_jsonable(item) for item in value]
        return str(value)
