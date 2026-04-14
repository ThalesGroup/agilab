from __future__ import annotations

import json
import textwrap
from collections.abc import Mapping, Sequence
from typing import Any


RUN_MODE_LABELS: tuple[str, ...] = (
    "0: python",
    "1: pool of process",
    "2: cython",
    "3: pool and cython",
    "4: dask",
    "5: dask and pool",
    "6: dask and cython",
    "7: dask and pool and cython",
    "8: rapids",
    "9: rapids and pool",
    "10: rapids and cython",
    "11: rapids and pool and cython",
    "12: rapids and dask",
    "13: rapids and dask and pool",
    "14: rapids and dask and cython",
    "15: rapids and dask and pool and cython",
)


def _python_string(value: Any) -> str:
    return json.dumps(str(value))


def serialize_args_payload(args: Mapping[str, Any]) -> str:
    return ", ".join(
        f"{key}={_python_string(value)}" if isinstance(value, str) else f"{key}={value!r}"
        for key, value in args.items()
    )


def optional_string_expr(enabled: bool, value: Any) -> str:
    if not enabled or value in (None, ""):
        return "None"
    return _python_string(value)


def optional_python_expr(enabled: bool, value: Any) -> str:
    if not enabled or value in (None, "", {}, []):
        return "None"
    return repr(value)


def build_install_snippet(
    *,
    env: Any,
    verbose: int,
    mode: Any,
    scheduler: str,
    workers: str,
    workers_data_path: str,
) -> str:
    return _build_agi_snippet(
        env=env,
        verbose=verbose,
        method="install",
        arguments=(
            "app_env",
            f"modes_enabled={mode!r}",
            f"scheduler={scheduler}",
            f"workers={workers}",
            f"workers_data_path={workers_data_path}",
        ),
    )


def build_distribution_snippet(
    *,
    env: Any,
    verbose: int,
    scheduler: str,
    workers: str,
    args_serialized: str,
) -> str:
    arguments = [
        "app_env",
        f"scheduler={scheduler}",
        f"workers={workers}",
    ]
    if args_serialized.strip():
        arguments.append(args_serialized)
    return _build_agi_snippet(
        env=env,
        verbose=verbose,
        method="get_distrib",
        arguments=tuple(arguments),
    )


def build_run_snippet(
    *,
    env: Any,
    verbose: int,
    run_mode: int | None,
    scheduler: str,
    workers: str,
    args_serialized: str,
) -> str:
    arguments = [
        "app_env",
        f"mode={run_mode!r}",
        f"scheduler={scheduler}",
        f"workers={workers}",
    ]
    if args_serialized.strip():
        arguments.append(args_serialized)
    return _build_agi_snippet(
        env=env,
        verbose=verbose,
        method="run",
        arguments=tuple(arguments),
    )


def compute_run_mode(cluster_params: Mapping[str, Any], cluster_enabled: bool) -> int:
    return (
        int(cluster_params.get("pool", False))
        + int(cluster_params.get("cython", False)) * 2
        + int(cluster_enabled) * 4
        + int(cluster_params.get("rapids", False)) * 8
    )


def describe_run_mode(run_mode: int | None, benchmark_enabled: bool) -> str:
    if benchmark_enabled:
        return "Run mode benchmark (all modes)"
    if run_mode is None or run_mode < 0 or run_mode >= len(RUN_MODE_LABELS):
        return "Run mode unknown"
    return f"Run mode {RUN_MODE_LABELS[run_mode]}"


def workplan_selection_key(partition: Any, worker_index: int, chunk_index: int) -> str:
    return f"worker_partition_{partition}_{worker_index}_{chunk_index}"


def reassign_distribution_plan(
    *,
    workers: Sequence[str],
    work_plan_metadata: Sequence[Sequence[Any]],
    work_plan: Sequence[Sequence[Any]],
    selections: Mapping[str, Any],
) -> tuple[list[list[Any]], list[list[Any]]]:
    new_work_plan_metadata: list[list[Any]] = [[] for _ in workers]
    new_work_plan: list[list[Any]] = [[] for _ in workers]
    worker_positions = {worker: index for index, worker in enumerate(workers)}

    for worker_index, (chunks, files_tree) in enumerate(zip(work_plan_metadata, work_plan)):
        for chunk_index, (chunk, files) in enumerate(zip(chunks, files_tree)):
            partition = chunk[0] if isinstance(chunk, (list, tuple)) and chunk else None
            selected_worker = selections.get(workplan_selection_key(partition, worker_index, chunk_index))
            if selected_worker not in worker_positions and worker_index < len(workers):
                selected_worker = workers[worker_index]
            target_index = worker_positions.get(selected_worker)
            if target_index is None:
                continue
            new_work_plan_metadata[target_index].append(chunk)
            new_work_plan[target_index].append(files)

    return new_work_plan_metadata, new_work_plan


def update_distribution_payload(
    payload: Mapping[str, Any],
    *,
    target_args: Mapping[str, Any],
    work_plan_metadata: Sequence[Sequence[Any]],
    work_plan: Sequence[Sequence[Any]],
) -> dict[str, Any]:
    updated = dict(payload)
    updated["target_args"] = dict(target_args)
    updated["work_plan_metadata"] = [list(chunks) for chunks in work_plan_metadata]
    updated["work_plan"] = [list(files) for files in work_plan]
    return updated


def _build_agi_snippet(
    *,
    env: Any,
    verbose: int,
    method: str,
    arguments: Sequence[str],
) -> str:
    indented_arguments = ",\n".join(f"        {argument}" for argument in arguments)
    return textwrap.dedent(
        f"""
        import asyncio
        from pathlib import Path
        from agi_cluster.agi_distributor import AGI
        from agi_env import AgiEnv

        APPS_PATH = {_python_string(env.apps_path)}
        APP = {_python_string(env.app)}

        async def main():
            app_env = AgiEnv(apps_path=APPS_PATH, app=APP, verbose={int(verbose)})
            res = await AGI.{method}(
{indented_arguments}
            )
            print(res)
            return res

        if __name__ == "__main__":
            asyncio.run(main())
        """
    ).strip()
