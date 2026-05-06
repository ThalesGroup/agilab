import json
import logging
import os
import pickle
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, cast

import humanize
import numpy as np
import polars as pl
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split

from agi_env import AgiEnv
from agi_cluster.agi_distributor.run_request_support import RunRequest
from agi_node.agi_dispatcher.base_worker import BaseWorker


logger = logging.getLogger(__name__)


def _is_cython_installed(env: AgiEnv) -> bool:
    cython_check = cast(Callable[[AgiEnv], bool], BaseWorker._is_cython_installed)
    return cython_check(env)


def _benchmark_path(env: AgiEnv) -> Path:
    benchmark_path = cast(Path | None, env.benchmark)
    if benchmark_path is None:
        raise RuntimeError("Benchmark path is not configured.")
    return benchmark_path


def _manager_path(env: AgiEnv) -> Path:
    manager_path = getattr(env, "manager_path", None)
    if not isinstance(manager_path, Path):
        raise RuntimeError("Manager path is not configured.")
    return manager_path


def _worker_host(worker: Any) -> str:
    value = str(worker or "").strip()
    if "://" in value:
        value = value.rsplit("://", 1)[-1]
    if "@" in value:
        value = value.rsplit("@", 1)[-1]
    if value.startswith("[") and "]" in value:
        return value[1:value.index("]")]
    if value.count(":") == 1:
        value = value.split(":", 1)[0]
    return value


def _node_count(workers: Mapping[str, int] | None) -> int:
    if not workers:
        return 1
    hosts = {_worker_host(worker) for worker in workers if _worker_host(worker)}
    return max(len(hosts), 1)


def _best_single_node_host(agi_cls: Any, workers: Mapping[str, int]) -> str:
    for worker, _capacity in sorted(
        (getattr(agi_cls, "_capacity", {}) or {}).items(),
        key=lambda item: item[1],
        reverse=True,
    ):
        host = _worker_host(worker)
        if host:
            return host
    for host in workers:
        worker_host = _worker_host(host)
        if worker_host:
            return worker_host
    return ""


def _best_single_node_workers(agi_cls: Any, workers: Mapping[str, int]) -> dict[str, int]:
    host = _best_single_node_host(agi_cls, workers)
    return {host: 1} if host else {}


_TRUE_RAPIDS_CAPABILITIES = {"1", "true", "yes", "on", "hw_rapids_capable"}
_FALSE_RAPIDS_CAPABILITIES = {"0", "false", "no", "off", "no_rapids_hw"}


def _rapids_capability_value(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    if normalized in _TRUE_RAPIDS_CAPABILITIES:
        return True
    if normalized in _FALSE_RAPIDS_CAPABILITIES:
        return False
    return None


def _rapids_capability_sources(env: AgiEnv) -> list[Mapping[str, Any]]:
    sources: list[Mapping[str, Any]] = []
    for source in (os.environ, getattr(type(env), "envars", None), getattr(env, "envars", None)):
        if isinstance(source, Mapping) and all(source is not existing for existing in sources):
            sources.append(source)
    return sources


def _worker_rapids_capability(env: AgiEnv, host: str) -> bool | None:
    normalized_host = _worker_host(host)
    for envars in _rapids_capability_sources(env):
        for key, value in envars.items():
            if _worker_host(key) != normalized_host:
                continue
            capability = _rapids_capability_value(value)
            if capability is not None:
                return capability
    try:
        if env.is_local(normalized_host):
            return _rapids_capability_value(getattr(env, "hw_rapids_capable", None))
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        pass
    return None


def _worker_rapids_capable(env: AgiEnv, host: str) -> bool:
    return _worker_rapids_capability(env, host) is True


def _best_single_node_modes(
    mode_range: List[int],
    *,
    rapids_capable: bool,
    rapids_mode_bit: int,
    prefer_requested_rapids: bool = False,
) -> list[int]:
    modes: list[int] = []
    requested_modes = {int(mode) for mode in mode_range}
    for mode in mode_range:
        mode_int = int(mode)
        if (
            prefer_requested_rapids
            and not (mode_int & rapids_mode_bit)
            and (mode_int | rapids_mode_bit) in requested_modes
        ):
            continue
        best_mode = mode_int | rapids_mode_bit if rapids_capable else mode_int
        if best_mode not in modes:
            modes.append(best_mode)
    return modes


def _rapids_run_mode_bit(agi_cls: Any) -> int:
    try:
        bit = int(getattr(agi_cls, "_RAPIDS_SET")) ^ int(getattr(agi_cls, "_RAPIDS_RESET"))
    except (AttributeError, TypeError, ValueError):
        bit = 0
    return bit or 8


def _rapids_requested_for_best_node(
    agi_cls: Any,
    mode_range: List[int],
    rapids_mode_mask: int,
) -> bool:
    rapids_bit = _rapids_run_mode_bit(agi_cls)
    return bool(
        rapids_mode_mask == agi_cls._RAPIDS_SET
        or any(int(mode) & rapids_bit for mode in mode_range)
    )


def _auto_rapids_requires_best_node_capability(
    agi_cls: Any,
    mode_range: List[int],
    rapids_mode_mask: int,
) -> bool:
    rapids_bit = _rapids_run_mode_bit(agi_cls)
    return bool(
        rapids_mode_mask == agi_cls._RAPIDS_SET
        and any(not (int(mode) & rapids_bit) for mode in mode_range)
    )


async def benchmark(
    agi_cls: Any,
    env: AgiEnv,
    request: RunRequest,
) -> str:
    request_mode = request.mode
    if request_mode is None:
        benchmark_modes: list[int] = list(range(8))
    elif isinstance(request_mode, list):
        benchmark_modes = sorted(request_mode)
    elif isinstance(request_mode, int):
        benchmark_modes = [request_mode]
    else:
        raise TypeError("Benchmark mode must be None, an int, or a list of ints.")
    benchmark_modes = benchmark_modes or list(range(8))
    rapids_mode_mask = agi_cls._RAPIDS_SET if request.rapids_enabled else agi_cls._RAPIDS_RESET
    runs: Dict[int | str, Dict[str, Any]] = {}

    benchmark_path = _benchmark_path(env)

    if not _is_cython_installed(env):
        await agi_cls.install(
            env,
            scheduler=request.scheduler,
            workers=request.workers,
            verbose=request.verbose,
            modes_enabled=agi_cls.CYTHON_MODE,
            **request.to_app_kwargs(),
        )
    agi_cls._mode_auto = True

    if os.path.exists(benchmark_path):
        os.remove(benchmark_path)
    local_modes = [mode for mode in benchmark_modes if not (mode & agi_cls.DASK_MODE)]
    dask_modes = [mode for mode in benchmark_modes if mode & agi_cls.DASK_MODE]

    async def _record(
        run_value: str,
        key: int | str,
        *,
        nodes: int,
        variant: str,
        node: str,
    ) -> None:
        runtime = run_value.split()
        if len(runtime) < 2:
            raise ValueError(f"Unexpected run format: {run_value}")
        runtime_float = float(runtime[1])
        runs[key] = {
            "variant": variant,
            "nodes": nodes,
            "node": node,
            "mode": runtime[0],
            "timing": humanize.precisedelta(timedelta(seconds=runtime_float)),
            "seconds": runtime_float,
        }

    for mode in local_modes:
        run_mode = mode & rapids_mode_mask
        run = await agi_cls.run(
            env,
            request=request.with_execution(mode=run_mode),
        )
        if isinstance(run, str):
            await _record(run, mode, nodes=1, variant="local", node="local")

    if dask_modes:
        await agi_cls._benchmark_dask_modes(
            env,
            request,
            dask_modes,
            rapids_mode_mask,
            runs,
            include_best_single_node=request.benchmark_best_single_node,
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
    with open(benchmark_path, "w") as handle:
        json.dump(runs_str_keys, handle)

    return json.dumps(runs_str_keys)


async def benchmark_dask_modes(
    agi_cls: Any,
    env: AgiEnv,
    request: RunRequest,
    mode_range: List[int],
    rapids_mode_mask: int,
    runs: Dict[int | str, Dict[str, Any]],
    *,
    include_best_single_node: bool = False,
) -> None:
    workers_dict = request.workers or agi_cls._worker_default
    cluster_node_count = _node_count(workers_dict)

    agi_cls.env = env
    agi_cls.target_path = _manager_path(env)
    agi_cls._target = env.target
    agi_cls._workers = workers_dict
    agi_cls._args = request.to_dispatch_kwargs()
    agi_cls._worker_args = request.to_app_kwargs()
    agi_cls._rapids_enabled = bool(rapids_mode_mask == agi_cls._RAPIDS_SET)

    first_mode = mode_range[0] & rapids_mode_mask
    agi_cls._mode = first_mode
    await agi_cls._start(request.scheduler)
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
                    "variant": "cluster",
                    "nodes": cluster_node_count,
                    "node": "cluster",
                    "mode": runtime[0],
                    "timing": humanize.precisedelta(timedelta(seconds=runtime_float)),
                    "seconds": runtime_float,
                }
        if include_best_single_node:
            best_host = _best_single_node_host(agi_cls, workers_dict)
            best_workers = {best_host: 1} if best_host else {}
            if best_workers and _node_count(workers_dict) > 1:
                previous_hw_rapids_capable = getattr(env, "hw_rapids_capable", None)
                previous_rapids_enabled = getattr(agi_cls, "_rapids_enabled", False)
                rapids_capability = _worker_rapids_capability(env, best_host)
                rapids_capable = rapids_capability is True
                if (
                    _rapids_requested_for_best_node(agi_cls, mode_range, rapids_mode_mask)
                    and not rapids_capable
                    and _auto_rapids_requires_best_node_capability(
                        agi_cls,
                        mode_range,
                        rapids_mode_mask,
                    )
                ):
                    if rapids_capability is False:
                        logger.warning(
                            "RAPIDS requested for best-node benchmark, but best node %s is marked as not RAPIDS-capable; "
                            "running non-RAPIDS best-node modes.",
                            best_host,
                        )
                    else:
                        logger.warning(
                            "RAPIDS requested for best-node benchmark, but capability for best node %s is unknown; "
                            "run INSTALL with RAPIDS enabled or refresh hardware discovery, then rerun the benchmark. "
                            "Running non-RAPIDS best-node modes.",
                            best_host,
                        )
                best_modes = _best_single_node_modes(
                    mode_range,
                    rapids_capable=rapids_capable,
                    rapids_mode_bit=_rapids_run_mode_bit(agi_cls),
                    prefer_requested_rapids=_rapids_requested_for_best_node(
                        agi_cls,
                        mode_range,
                        rapids_mode_mask,
                    ),
                )
                try:
                    if rapids_capable:
                        # RAPIDS is encoded in the run mode here; keep the
                        # display helper from adding another RAPIDS bit.
                        env.hw_rapids_capable = False
                    for mode in best_modes:
                        run_mode = mode if rapids_capable else mode & rapids_mode_mask
                        agi_cls._mode = run_mode
                        agi_cls._workers = dict(best_workers)
                        agi_cls._rapids_enabled = rapids_capable or previous_rapids_enabled
                        run = await agi_cls._distribute()
                        agi_cls._update_capacity()
                        if isinstance(run, str):
                            runtime = run.split()
                            if len(runtime) < 2:
                                raise ValueError(f"Unexpected run format: {run}")
                            runtime_float = float(runtime[1])
                            runs[f"{mode}:best-node"] = {
                                "variant": "best-node",
                                "nodes": 1,
                                "node": best_host,
                                "mode": runtime[0],
                                "timing": humanize.precisedelta(timedelta(seconds=runtime_float)),
                                "seconds": runtime_float,
                            }
                finally:
                    env.hw_rapids_capable = previous_hw_rapids_capable
                    agi_cls._rapids_enabled = previous_rapids_enabled
    finally:
        agi_cls._workers = workers_dict
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
