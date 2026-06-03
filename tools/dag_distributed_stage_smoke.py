#!/usr/bin/env python3
"""Validate the distributed stage contract for a checked-in multi-app DAG."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import sys
import tomllib
from types import SimpleNamespace
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DAG_RELATIVE_PATH = Path("src/agilab/apps/builtin/flight_telemetry_project/dag_templates/flight_to_weather.json")
DEFAULT_OUTPUT = Path("test-results/dag-distributed-stage-smoke.json")
SCHEMA = "agilab.distributed_dag_stage_smoke.v1"


def _ensure_repo_on_path(repo_root: Path) -> None:
    src_root = repo_root / "src"
    for entry in (str(src_root), str(repo_root)):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    package = sys.modules.get("agilab")
    package_path = str(src_root / "agilab")
    package_paths = getattr(package, "__path__", None)
    if package_paths is not None and package_path not in list(package_paths):
        try:
            package_paths.append(package_path)
        except AttributeError:
            package.__path__ = [*package_paths, package_path]


_ensure_repo_on_path(REPO_ROOT)

from agilab.dag_distributed_submitter import (  # noqa: E402
    DagDistributedStageConfig,
    build_distributed_request_preview_rows,
    dag_distributed_stage_config_from_settings,
    load_dag_distributed_settings,
    request_payload_from_execution_contract,
    run_agilab_stage_subprocess,
    submit_distributed_stage,
)
from agilab.dag_run_engine import (  # noqa: E402
    DagRunEngine,
    GLOBAL_DAG_STAGE_BACKEND_DISTRIBUTED,
)


def build_smoke_report(
    *,
    repo_root: Path = REPO_ROOT,
    dag_path: Path | None = None,
    output_path: Path | None = None,
    settings: Mapping[str, Any] | None = None,
    settings_file: Path | None = None,
    execute: bool = False,
    require_two_nodes: bool = True,
    verbose: int = 0,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    dag_path = _resolve_path(repo_root, dag_path or DEFAULT_DAG_RELATIVE_PATH)
    output_path = _resolve_path(repo_root, output_path or DEFAULT_OUTPUT)
    lab_dir = output_path.parent / "dag_distributed_stage_smoke"
    engine = DagRunEngine(repo_root=repo_root, lab_dir=lab_dir, dag_path=dag_path)
    state, state_path, loaded_dag_path = engine.load_or_create_state(reset=True)

    loaded_settings = _load_settings(settings=settings, settings_file=settings_file)
    config = dag_distributed_stage_config_from_settings(loaded_settings, verbose=verbose)
    preview_rows = (
        build_distributed_request_preview_rows(state, repo_root=repo_root, config=config)
        if config is not None
        else []
    )
    contract_rows = _stage_contract_rows(state)
    two_node_ready = bool(config is not None and config.worker_nodes >= 2)
    cluster_ready = config is not None and (two_node_ready or not require_two_nodes)
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "pass" if (not execute or cluster_ready) else "fail",
        "mode": "execute" if execute else "dry_run",
        "dag_path": _repo_relative_text(loaded_dag_path or dag_path, repo_root),
        "state_path": str(state_path),
        "cluster_ready": bool(config is not None),
        "two_node_ready": two_node_ready,
        "required_nodes": 2 if require_two_nodes else 1,
        "stage_count": len(contract_rows),
        "stage_contracts": contract_rows,
        "distributed_request_preview": preview_rows,
        "executed_unit_ids": [],
        "failed_unit_ids": [],
        "message": "Distributed DAG stage smoke dry-run completed.",
    }
    if config is not None:
        report["cluster"] = _cluster_payload(config)
    elif execute:
        report["message"] = (
            "Distributed DAG stage execution requires enabled cluster settings with scheduler, "
            "workers, and Workers Data Path."
        )
    if execute and config is not None and require_two_nodes and config.worker_nodes < 2:
        report["message"] = "Distributed DAG stage execution requires at least two configured worker nodes."
    if execute and cluster_ready and config is not None:
        execution_report = _execute_ready_stage_waves(engine, state, config=config)
        report.update(execution_report)
        report["status"] = "pass" if not execution_report["failed_unit_ids"] else "fail"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _execute_ready_stage_waves(
    engine: DagRunEngine,
    state: Mapping[str, Any],
    *,
    config: DagDistributedStageConfig,
) -> dict[str, Any]:
    executed_unit_ids: list[str] = []
    failed_unit_ids: list[str] = []
    current_state = dict(state)

    def _submit_stage(**kwargs: Any) -> Mapping[str, Any]:
        return submit_distributed_stage(config=config, runner_fn=run_agilab_stage_subprocess, **kwargs)

    execution_engine = DagRunEngine(
        repo_root=engine.repo_root,
        lab_dir=engine.lab_dir,
        dag_path=engine.dag_path,
        state_filename=engine.state_filename,
        stage_submit_fn=_submit_stage,
        now_fn=engine.now_fn,
    )
    max_waves = max(1, len(current_state.get("units", [])) if isinstance(current_state.get("units"), list) else 1)
    messages: list[str] = []
    for _index in range(max_waves):
        result = execution_engine.run_ready_controlled_stages(
            current_state,
            execution_backend=GLOBAL_DAG_STAGE_BACKEND_DISTRIBUTED,
        )
        messages.append(result.message)
        current_state = dict(result.state)
        execution_engine.write_state(current_state)
        executed_unit_ids.extend(result.executed_unit_ids)
        failed_unit_ids.extend(result.failed_unit_ids)
        if result.failed_unit_ids or not result.executed_unit_ids:
            break
        summary = current_state.get("summary", {})
        if isinstance(summary, Mapping) and summary.get("completed_count") == summary.get("unit_count"):
            break

    return {
        "executed_unit_ids": executed_unit_ids,
        "failed_unit_ids": failed_unit_ids,
        "message": " ".join(messages).strip() or "Distributed DAG stage execution completed.",
        "final_state": current_state,
    }


def _stage_contract_rows(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    units = state.get("units")
    if not isinstance(units, list):
        return []
    rows: list[dict[str, Any]] = []
    for unit in units:
        if not isinstance(unit, Mapping):
            continue
        contract = unit.get("execution_contract")
        if not isinstance(contract, Mapping):
            continue
        rows.append(
            {
                "stage": str(unit.get("id", "") or ""),
                "app": str(unit.get("app", "") or ""),
                "status": str(unit.get("dispatch_status", "") or ""),
                "entrypoint": str(contract.get("entrypoint", "") or ""),
                "request_payload": request_payload_from_execution_contract(contract),
            }
        )
    return rows


def _load_settings(
    *,
    settings: Mapping[str, Any] | None,
    settings_file: Path | None,
) -> dict[str, Any]:
    if settings is not None:
        return dict(settings)
    if settings_file is None:
        return {}
    return load_dag_distributed_settings(SimpleNamespace(app_settings_file=settings_file), None)


def _cluster_payload(config: DagDistributedStageConfig) -> dict[str, Any]:
    return {
        "scheduler": config.scheduler,
        "workers": config.workers,
        "workers_data_path": config.workers_data_path,
        "mode": config.mode,
        "worker_nodes": config.worker_nodes,
        "worker_slots": config.worker_slots,
    }


def _settings_from_cli(args: argparse.Namespace) -> dict[str, Any] | None:
    if not (args.scheduler or args.workers or args.workers_data_path):
        return None
    return {
        "cluster": {
            "cluster_enabled": True,
            "scheduler": args.scheduler,
            "workers": _parse_workers(args.workers),
            "workers_data_path": args.workers_data_path,
            "pool": args.pool,
            "cython": args.cython,
            "rapids": args.rapids,
        }
    }


def _parse_workers(value: str) -> dict[str, int]:
    text = str(value or "").strip()
    if not text:
        return {}
    for loader in (json.loads, ast.literal_eval):
        try:
            loaded = loader(text)
        except (json.JSONDecodeError, ValueError, SyntaxError):
            continue
        if isinstance(loaded, Mapping):
            return {str(host): int(slots) for host, slots in loaded.items() if int(slots) > 0}
    workers: dict[str, int] = {}
    for item in text.split(","):
        host, sep, slots = item.partition("=")
        host = host.strip()
        if not host:
            continue
        workers[host] = int(slots.strip()) if sep else 1
    return workers


def _resolve_path(repo_root: Path, path: Path) -> Path:
    path = path.expanduser()
    return path if path.is_absolute() else repo_root / path


def _repo_relative_text(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(repo_root.resolve(strict=False)).as_posix()
    except ValueError:
        return str(path)


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        loaded = tomllib.load(handle)
    return dict(loaded) if isinstance(loaded, Mapping) else {}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--dag", type=Path, default=DEFAULT_DAG_RELATIVE_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--settings-file", type=Path)
    parser.add_argument("--settings-json", help="Inline app_settings-like JSON cluster payload.")
    parser.add_argument("--scheduler", default="")
    parser.add_argument("--workers", default="")
    parser.add_argument("--workers-data-path", default="")
    parser.add_argument("--pool", action="store_true", default=True)
    parser.add_argument("--no-pool", action="store_false", dest="pool")
    parser.add_argument("--cython", action="store_true", default=True)
    parser.add_argument("--no-cython", action="store_false", dest="cython")
    parser.add_argument("--rapids", action="store_true", default=False)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-single-node", action="store_true")
    parser.add_argument("--verbose", type=int, default=0)
    parser.add_argument("--compact", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings: Mapping[str, Any] | None = _settings_from_cli(args)
    settings_file = args.settings_file
    if args.settings_json:
        loaded = json.loads(args.settings_json)
        if not isinstance(loaded, Mapping):
            raise SystemExit("--settings-json must decode to a JSON object.")
        settings = dict(loaded)
        settings_file = None
    elif settings is None and settings_file is not None and settings_file.suffix.lower() == ".json":
        settings = json.loads(settings_file.read_text(encoding="utf-8"))
        settings_file = None
    elif settings is None and settings_file is not None and settings_file.suffix.lower() == ".toml":
        settings = _load_toml(settings_file)
        settings_file = None

    report = build_smoke_report(
        repo_root=args.repo_root,
        dag_path=args.dag,
        output_path=args.output,
        settings=settings,
        settings_file=settings_file,
        execute=args.execute,
        require_two_nodes=not args.allow_single_node,
        verbose=args.verbose,
    )
    print(json.dumps(report, sort_keys=True if args.compact else False, separators=(",", ":") if args.compact else None))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
