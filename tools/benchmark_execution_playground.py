from __future__ import annotations

import argparse
import importlib
import json
import logging
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from agi_env import AgiEnv
from agi_node.agi_dispatcher import BaseWorker


APPS_PATH = Path("src/agilab/apps/builtin")
APPS = {
    "execution_pandas_project": {
        "manager_module": "execution_pandas.execution_pandas",
        "manager_class": "ExecutionPandas",
        "worker_module": "execution_pandas_worker.execution_pandas_worker",
        "worker_class": "ExecutionPandasWorker",
        "engine": "pandas",
        "execution_model": "process",
    },
    "execution_polars_project": {
        "manager_module": "execution_polars.execution_polars",
        "manager_class": "ExecutionPolars",
        "worker_module": "execution_polars_worker.execution_polars_worker",
        "worker_class": "ExecutionPolarsWorker",
        "engine": "polars",
        "execution_model": "threads",
    },
}
MODE_LABELS = {
    0: "mono",
    4: "parallel",
}


def _load_classes(env: AgiEnv, app_name: str):
    if str(env.app_src) not in sys.path:
        sys.path.insert(0, str(env.app_src))
    config = APPS[app_name]
    manager_module = importlib.import_module(config["manager_module"])
    worker_module = importlib.import_module(config["worker_module"])
    return (
        getattr(manager_module, config["manager_class"]),
        getattr(worker_module, config["worker_class"]),
        config,
    )


def _run_child(payload_path: Path) -> int:
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    app_name = payload["app_name"]
    mode = int(payload["mode"])

    env = AgiEnv(apps_path=APPS_PATH, app=app_name, verbose=0)
    _, worker_cls, _ = _load_classes(env, app_name)

    worker = worker_cls()
    worker.env = env
    worker.args = payload["args"]
    worker._worker_id = 0
    worker.worker_id = 0
    worker.verbose = 0
    worker._mode = mode

    BaseWorker._t0 = time.time()
    worker.start()
    seconds = worker.works([payload["work_plan"]], [payload["work_plan_metadata"]])
    result = {"seconds": seconds}
    payload_path.with_suffix(".result.json").write_text(
        json.dumps(result, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


def _worker_output_root(env: AgiEnv, app_name: str, worker_count: int, mode: int, sample_idx: int, worker_idx: int) -> Path:
    return env.resolve_share_path(
        Path("execution_playground")
        / "benchmarks"
        / app_name
        / f"{worker_count}_workers"
        / MODE_LABELS[mode]
        / f"sample_{sample_idx}"
        / f"worker_{worker_idx}"
    )


def _run_once(app_name: str, mode: int, worker_count: int, sample_idx: int) -> dict[str, Any]:
    env = AgiEnv(apps_path=APPS_PATH, app=app_name, verbose=0)
    manager_cls, _, _ = _load_classes(env, app_name)
    manager = manager_cls.from_toml(env, settings_path=env.app_settings_file)
    manager.args.reset_target = True

    workers = {"127.0.0.1": worker_count}
    work_plan, metadata, *_ = manager.build_distribution(workers)
    active_plans = [
        (idx, chunk, metadata[idx])
        for idx, chunk in enumerate(work_plan)
        if chunk
    ]

    if not active_plans:
        raise RuntimeError(f"No active work plan for {app_name} with {worker_count} worker(s)")

    with tempfile.TemporaryDirectory(prefix=f"agilab-bench-{app_name}-") as tmp_dir:
        tmp_root = Path(tmp_dir)
        commands: list[tuple[subprocess.Popen[str], Path]] = []
        t0 = time.perf_counter()
        for worker_idx, chunk, chunk_meta in active_plans:
            args = manager.args.model_dump(mode="json")
            args["data_out"] = str(
                _worker_output_root(
                    env=env,
                    app_name=app_name,
                    worker_count=worker_count,
                    mode=mode,
                    sample_idx=sample_idx,
                    worker_idx=worker_idx,
                )
            )
            payload = {
                "app_name": app_name,
                "mode": mode,
                "args": args,
                "work_plan": chunk,
                "work_plan_metadata": chunk_meta,
            }
            payload_path = tmp_root / f"worker_{worker_idx}.json"
            payload_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            proc = subprocess.Popen(
                [sys.executable, __file__, "--child-run", str(payload_path)],
                cwd=str(Path.cwd()),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            commands.append((proc, payload_path))

        worker_seconds: list[float] = []
        for proc, payload_path in commands:
            stdout, stderr = proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(
                    f"Benchmark child failed for {app_name} mode={mode} workers={worker_count}:\n{stderr or stdout}"
                )
            result_path = payload_path.with_suffix(".result.json")
            result = json.loads(result_path.read_text(encoding="utf-8"))
            worker_seconds.append(float(result["seconds"]))
        wall_seconds = time.perf_counter() - t0

    return {
        "wall_seconds": wall_seconds,
        "worker_seconds": worker_seconds,
        "active_workers": len(active_plans),
    }


def run_benchmarks(repeats: int, warmups: int, worker_counts: list[int]) -> dict[str, Any]:
    results: dict[str, Any] = {"environment": {}, "apps": {}}
    results["environment"] = {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "repeats": repeats,
        "warmups": warmups,
        "worker_counts": worker_counts,
    }

    for app_name, config in APPS.items():
        app_result: dict[str, Any] = {
            "engine": config["engine"],
            "execution_model": config["execution_model"],
            "worker_counts": {},
        }
        for worker_count in worker_counts:
            worker_count_result: dict[str, Any] = {"modes": {}}
            for mode in (0, 4):
                samples: list[float] = []
                active_workers: int | None = None
                for idx in range(warmups + repeats):
                    sample = _run_once(
                        app_name=app_name,
                        mode=mode,
                        worker_count=worker_count,
                        sample_idx=idx,
                    )
                    active_workers = sample["active_workers"]
                    if idx >= warmups:
                        samples.append(sample["wall_seconds"])
                worker_count_result["modes"][str(mode)] = {
                    "label": MODE_LABELS[mode],
                    "active_workers": active_workers,
                    "samples_seconds": samples,
                    "median_seconds": statistics.median(samples),
                    "min_seconds": min(samples),
                    "max_seconds": max(samples),
                }

            mono = worker_count_result["modes"]["0"]["median_seconds"]
            parallel = worker_count_result["modes"]["4"]["median_seconds"]
            worker_count_result["parallel_speedup_vs_mono"] = mono / parallel if parallel else None
            app_result["worker_counts"][str(worker_count)] = worker_count_result
        results["apps"][app_name] = app_result
    return results


def _markdown_table(results: dict[str, Any]) -> str:
    worker_counts = results["environment"]["worker_counts"]
    headers = ["App", "Worker path", "Mode"] + [f"{count} worker" if count == 1 else f"{count} workers" for count in worker_counts]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---", "---", "---"] + ["---:" for _ in worker_counts]) + " |",
    ]
    for app_name, app in results["apps"].items():
        mono_values = []
        parallel_values = []
        for count in worker_counts:
            entry = app["worker_counts"][str(count)]["modes"]
            mono_values.append(f'{entry["0"]["median_seconds"]:.3f}')
            parallel_values.append(f'{entry["4"]["median_seconds"]:.3f}')
        lines.append(
            f'| {app_name} | {app["engine"]} / {app["execution_model"]} | mono | '
            + " | ".join(mono_values)
            + " |"
        )
        lines.append(
            f'| {app_name} | {app["engine"]} / {app["execution_model"]} | parallel | '
            + " | ".join(parallel_values)
            + " |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark the execution playground worker paths.")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--worker-counts", default="1,2,4")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--md-out", type=Path)
    parser.add_argument("--child-run", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()

    logging.disable(logging.CRITICAL)

    if args.child_run:
        return _run_child(args.child_run)

    worker_counts = [int(item) for item in args.worker_counts.split(",") if item.strip()]
    results = run_benchmarks(repeats=args.repeats, warmups=args.warmups, worker_counts=worker_counts)
    payload = json.dumps(results, indent=2, sort_keys=True)
    table = _markdown_table(results)

    print(payload)
    print()
    print(table)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(payload + "\n", encoding="utf-8")
    if args.md_out:
        args.md_out.parent.mkdir(parents=True, exist_ok=True)
        args.md_out.write_text(table + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
