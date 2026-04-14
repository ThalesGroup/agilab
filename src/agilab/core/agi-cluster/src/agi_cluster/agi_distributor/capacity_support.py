import json
import logging
import os
import pickle
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import humanize
import numpy as np
import polars as pl
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split

from agi_env import AgiEnv
from agi_node.agi_dispatcher.base_worker import BaseWorker


logger = logging.getLogger(__name__)


async def benchmark(
    agi_cls: Any,
    env: AgiEnv,
    scheduler: Optional[str] = None,
    workers: Optional[Dict[str, int]] = None,
    verbose: int = 0,
    mode_range: Optional[List[int]] = None,
    rapids_enabled: bool = False,
    **args: Any,
) -> str:
    mode_range = mode_range or list(range(agi_cls.PYTHON_MODE, agi_cls.MODES))
    rapids_mode_mask = agi_cls._RAPIDS_SET if rapids_enabled else agi_cls._RAPIDS_RESET
    runs: Dict[int, Dict[str, Any]] = {}

    if not BaseWorker._is_cython_installed(env):
        await agi_cls.install(
            env,
            scheduler=scheduler,
            workers=workers,
            verbose=verbose,
            modes_enabled=agi_cls.CYTHON_MODE,
            **args,
        )
    agi_cls._mode_auto = True

    if os.path.exists(env.benchmark):
        os.remove(env.benchmark)
    local_modes = [mode for mode in mode_range if not (mode & agi_cls.DASK_MODE)]
    dask_modes = [mode for mode in mode_range if mode & agi_cls.DASK_MODE]

    async def _record(run_value: str, key: int) -> None:
        runtime = run_value.split()
        if len(runtime) < 2:
            raise ValueError(f"Unexpected run format: {run_value}")
        runtime_float = float(runtime[1])
        runs[key] = {
            "mode": runtime[0],
            "timing": humanize.precisedelta(timedelta(seconds=runtime_float)),
            "seconds": runtime_float,
        }

    for mode in local_modes:
        run_mode = mode & rapids_mode_mask
        run = await agi_cls.run(
            env,
            scheduler=scheduler,
            workers=workers,
            mode=run_mode,
            **args,
        )
        if isinstance(run, str):
            await _record(run, mode)

    if dask_modes:
        await agi_cls._benchmark_dask_modes(
            env,
            scheduler,
            workers,
            dask_modes,
            rapids_mode_mask,
            runs,
            **args,
        )

    ordered_runs = sorted(runs.items(), key=lambda item: item[1]["seconds"])
    for idx, (_mode_key, run_data) in enumerate(ordered_runs, start=1):
        run_data["order"] = idx

    if not ordered_runs:
        raise RuntimeError("No ordered runs available after sorting.")

    best_mode_key, best_run_data = ordered_runs[0]

    for mode in runs:
        runs[mode]["delta"] = runs[mode]["seconds"] - best_run_data["seconds"]

    agi_cls._best_mode[env.target] = best_run_data
    agi_cls._mode_auto = False

    runs_str_keys = {str(key): value for key, value in runs.items()}
    with open(env.benchmark, "w") as handle:
        json.dump(runs_str_keys, handle)

    return json.dumps(runs_str_keys)


async def benchmark_dask_modes(
    agi_cls: Any,
    env: AgiEnv,
    scheduler: Optional[str],
    workers: Optional[Dict[str, int]],
    mode_range: List[int],
    rapids_mode_mask: int,
    runs: Dict[int, Dict[str, Any]],
    **args: Any,
) -> None:
    workers_dict = workers or agi_cls._worker_default

    agi_cls.env = env
    agi_cls.target_path = env.manager_path
    agi_cls._target = env.target
    agi_cls._workers = workers_dict
    agi_cls._args = args
    agi_cls._rapids_enabled = bool(rapids_mode_mask == agi_cls._RAPIDS_SET)

    first_mode = mode_range[0] & rapids_mode_mask
    agi_cls._mode = first_mode
    await agi_cls._start(scheduler)
    try:
        for mode in mode_range:
            run_mode = mode & rapids_mode_mask
            agi_cls._mode = run_mode
            run = await agi_cls._distribute()
            agi_cls._update_capacity()
            if isinstance(run, str):
                runtime = run.split()
                if len(runtime) < 2:
                    raise ValueError(f"Unexpected run format: {run}")
                runtime_float = float(runtime[1])
                runs[mode] = {
                    "mode": runtime[0],
                    "timing": humanize.precisedelta(timedelta(seconds=runtime_float)),
                    "seconds": runtime_float,
                }
    finally:
        await agi_cls._stop()


async def calibration(agi_cls: Any, log: Any = logger) -> None:
    res_workers_info = agi_cls._dask_client.gather(
        [
            agi_cls._dask_client.run(
                BaseWorker._get_worker_info,
                BaseWorker._worker_id,
                workers=agi_cls._dask_workers,
            )
        ]
    )

    infos = {}
    for res in res_workers_info:
        for worker, info in res.items():
            if info:
                log.info(f"{worker}:{info}")
            infos[worker] = info

    agi_cls.workers_info = infos
    agi_cls._capacity = {}
    workers_info = {}

    for worker, info in agi_cls.workers_info.items():
        ipport = worker.split("/")[-1]
        values = list(agi_cls.workers_info[worker].values())
        values.insert(0, [agi_cls._workers[ipport.split(":")[0]]])
        data = np.array(values).reshape(1, 6)
        agi_cls._capacity[ipport] = agi_cls._capacity_predictor.predict(data)[0]
        info["label"] = agi_cls._capacity[ipport]
        workers_info[ipport] = info

    agi_cls.workers_info = workers_info
    if not agi_cls._capacity:
        fallback_keys = list(workers_info.keys())
        if not fallback_keys:
            fallback_keys = [
                worker.split("://")[-1] for worker in (agi_cls._dask_workers or [])
            ]
        if not fallback_keys and agi_cls._workers:
            for ip, count in agi_cls._workers.items():
                for idx in range(count):
                    fallback_keys.append(f"{ip}:{idx}")
        if not fallback_keys:
            fallback_keys = ["localhost:0"]
        log.warning(
            "Capacity predictor returned no data; assuming uniform capacity for %s worker(s).",
            len(fallback_keys),
        )
        if not workers_info:
            agi_cls.workers_info = {ipport: {"label": 1.0} for ipport in fallback_keys}
        agi_cls._capacity = {ipport: 1.0 for ipport in fallback_keys}

    cap_min = min(agi_cls._capacity.values()) if agi_cls._capacity else 1.0
    workers_capacity = {}
    for ipport, pred_cap in agi_cls._capacity.items():
        workers_capacity[ipport] = round(pred_cap / cap_min, 1)

    agi_cls._capacity = dict(
        sorted(workers_capacity.items(), key=lambda item: item[1], reverse=True)
    )


def train_capacity(agi_cls: Any, train_home: Path, log: Any = logger) -> None:
    data_file = train_home / agi_cls._capacity_data_file
    if data_file.exists():
        balancer_csv = data_file
    else:
        raise FileNotFoundError(data_file)

    schema = {
        "nb_workers": pl.Int64,
        "ram_total": pl.Float64,
        "ram_available": pl.Float64,
        "cpu_count": pl.Float64,
        "cpu_frequency": pl.Float64,
        "network_speed": pl.Float64,
        "label": pl.Float64,
    }

    df = pl.read_csv(
        balancer_csv,
        has_header=True,
        skip_rows_after_header=2,
        schema_overrides=schema,
        ignore_errors=False,
    )
    columns = df.columns
    X = df.select(columns[:-1]).to_numpy()
    y = df.select(columns[-1]).to_numpy().ravel()

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.2,
        random_state=42,
    )
    agi_cls._capacity_predictor = RandomForestRegressor().fit(X_train, y_train)

    log.info(
        "AGI.balancer_train_mode - Accuracy of the prediction of the workers capacity = %s",
        agi_cls._capacity_predictor.score(X_test, y_test),
    )

    capacity_model = os.path.join(train_home, agi_cls._capacity_model_file)
    with open(capacity_model, "wb") as handle:
        pickle.dump(agi_cls._capacity_predictor, handle)


def update_capacity(agi_cls: Any) -> None:
    workers_rt = {}
    balancer_cols = [
        "nb_workers",
        "ram_total",
        "ram_available",
        "cpu_count",
        "cpu_frequency",
        "network_speed",
        "label",
    ]

    for wrt in agi_cls._run_time:
        if isinstance(wrt, str):
            return

        worker = list(wrt.keys())[0]
        for worker_name, info in agi_cls.workers_info.items():
            if worker_name == worker:
                info["run_time"] = wrt[worker]
                workers_rt[worker_name] = info

    current_state = deepcopy(workers_rt)

    for worker, data in workers_rt.items():
        worker_cap = data["label"]
        worker_rt = data["run_time"]
        for other_worker, other_data in current_state.items():
            if other_worker != worker:
                other_rt = other_data["run_time"]
                delta = worker_rt - other_rt
                workers_rt[worker]["label"] -= (
                    0.1 * worker_cap * delta / worker_rt / (len(current_state) - 1)
                )
            else:
                workers_rt[worker]["nb_workers"] = int(
                    agi_cls._workers[worker.split(":")[0]]
                )

    for worker_name, data in workers_rt.items():
        del data["run_time"]
        df = pl.DataFrame(data)
        df = df[balancer_cols]

        if df[0, -1] and df[0, -1] != float("inf"):
            with open(agi_cls._capacity_data_file, "a") as handle:
                df.write_csv(
                    handle,
                    include_header=False,
                    line_terminator="\r",
                )
        else:
            raise RuntimeError(f"{worker_name} workers BaseWorker.do_works failed")

    agi_cls._train_capacity(Path(agi_cls.env.home_abs))
