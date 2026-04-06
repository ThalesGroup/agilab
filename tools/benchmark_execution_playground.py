from __future__ import annotations

import argparse
import importlib
import json
import logging
import statistics
import sys
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


def _run_once(app_name: str, mode: int) -> float:
    env = AgiEnv(apps_path=APPS_PATH, app=app_name, verbose=0)
    manager_cls, worker_cls, _ = _load_classes(env, app_name)
    manager = manager_cls.from_toml(env, settings_path=env.app_settings_file)

    # Keep benchmark outputs isolated per mode so repeated runs do not mix files.
    manager.args.reset_target = True
    manager.args.data_out = env.resolve_share_path(
        Path("execution_playground") / "benchmarks" / app_name / MODE_LABELS[mode]
    )

    workers = {"127.0.0.1": 1}
    work_plan, metadata, *_ = manager.build_distribution(workers)

    worker = worker_cls()
    worker.env = env
    worker.args = manager.args.model_dump(mode="json")
    worker._worker_id = 0
    worker.worker_id = 0
    worker.verbose = 0
    worker._mode = mode

    BaseWorker._t0 = time.time()
    worker.start()
    return worker.works(work_plan, metadata)


def run_benchmarks(repeats: int, warmups: int) -> dict[str, Any]:
    results: dict[str, Any] = {"environment": {}, "apps": {}}
    results["environment"] = {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "repeats": repeats,
        "warmups": warmups,
    }

    for app_name, config in APPS.items():
        app_result: dict[str, Any] = {
            "engine": config["engine"],
            "execution_model": config["execution_model"],
            "modes": {},
        }
        for mode in (0, 4):
            samples: list[float] = []
            for idx in range(warmups + repeats):
                seconds = _run_once(app_name, mode)
                if idx >= warmups:
                    samples.append(seconds)
            app_result["modes"][str(mode)] = {
                "label": MODE_LABELS[mode],
                "samples_seconds": samples,
                "median_seconds": statistics.median(samples),
                "min_seconds": min(samples),
                "max_seconds": max(samples),
            }
        mono = app_result["modes"]["0"]["median_seconds"]
        parallel = app_result["modes"]["4"]["median_seconds"]
        app_result["parallel_speedup_vs_mono"] = mono / parallel if parallel else None
        results["apps"][app_name] = app_result
    return results


def _markdown_table(results: dict[str, Any]) -> str:
    lines = [
        "| App | Worker path | Mono median (s) | Parallel median (s) | Parallel speedup |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for app_name, app in results["apps"].items():
        lines.append(
            "| {app} | {path} | {mono:.3f} | {parallel:.3f} | {speedup:.2f}x |".format(
                app=app_name,
                path=f'{app["engine"]} / {app["execution_model"]}',
                mono=app["modes"]["0"]["median_seconds"],
                parallel=app["modes"]["4"]["median_seconds"],
                speedup=app["parallel_speedup_vs_mono"],
            )
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark the execution playground worker paths.")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--md-out", type=Path)
    args = parser.parse_args()

    logging.disable(logging.INFO)
    results = run_benchmarks(repeats=args.repeats, warmups=args.warmups)
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
