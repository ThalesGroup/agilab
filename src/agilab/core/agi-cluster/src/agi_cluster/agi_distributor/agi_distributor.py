# BSD 3-Clause License
#
# Copyright (c) 2025, Jean-Pierre Morard, THALES SIX GTS France SAS
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
# 3. Neither the name of Jean-Pierre Morard nor the names of its contributors, or THALES SIX GTS France SAS, may be used to endorse or promote products derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""Cluster workplan utilities for distributing AGILab workloads."""
import traceback
from typing import Tuple, Set  # Ajoute Tuple et Set
from IPython.lib import backgroundjobs as bg
import asyncio
import getpass
import io
import os
import pickle
import random
import re
import shutil
import socket
import sys
import shlex
import time
import warnings
from copy import deepcopy
from datetime import timedelta
from ipaddress import ip_address as is_ip
from pathlib import Path
from tempfile import gettempdir


# --- Added minimal TestPyPI fallback for uv sync ---
def _agi__version_missing_on_pypi(project_path):
    """Return True if any pinned 'agi*' or 'agilab' dependency version in pyproject.toml
    is not available on pypi.org (so we should use TestPyPI fallback)."""
    try:
        import json, urllib.request, re
        pyproj = (project_path / 'pyproject.toml')
        if not pyproj.exists():
            return False
        text = pyproj.read_text(encoding='utf-8', errors='ignore')
        # naive scan for lines like: agi-core = "==1.2.3" or "1.2.3"
        deps = re.findall(r'^(?:\s*)(ag(?:i[-_].+|ilab))\s*=\s*["\']([^"\']+)["\']', text, flags=re.MULTILINE)
        if not deps:
            return False
        # extract exact pins
        pairs = []
        for name, spec in deps:
            m = re.match(r'^(?:==\s*)?(\d+(?:\.\d+){1,2})$', spec.strip())
            if m:
                version = m.group(1)
                pairs.append((name.replace('_', '-'), version))
        if not pairs:
            return False
        # check first pair only to keep it minimal/fast
        pkg, ver = pairs[0]
        try:
            with urllib.request.urlopen(f'https://pypi.org/pypi/{pkg}/json', timeout=5) as r:
                data = json.load(r)
            exists = ver in data.get('releases', {})
            return not exists
        except Exception:
            # If pypi query fails, don't force fallback.
            return False
    except Exception:
        return False


# --- end added helper ---
from typing import Any, Dict, List, Optional, Union
import sysconfig
from contextlib import redirect_stdout, redirect_stderr
import errno

# External Libraries
import asyncssh
from asyncssh.process import ProcessError
from contextlib import asynccontextmanager
import humanize
import numpy as np
import polars as pl
import psutil
from dask.distributed import Client, wait
import json
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
import subprocess
import logging
import runpy
import tomlkit
from packaging.requirements import Requirement
from importlib.metadata import PackageNotFoundError, version as pkg_version

# Project Libraries:
from agi_env import AgiEnv, normalize_path

_node_src = str(Path(sys.prefix).parents[1] / "agi-node/src")
if _node_src not in sys.path:
    sys.path.append(_node_src)
from agi_node.agi_dispatcher import WorkDispatcher, BaseWorker

# os.environ["DASK_DISTRIBUTED__LOGGING__DISTRIBUTED__LEVEL"] = "INFO"
logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")
_workers_default = {socket.gethostbyname("localhost"): 1}


class AGI:
    """Coordinate installation, scheduling, and execution of AGILab workloads."""

    # Constants as class attributes
    _TIMEOUT = 10
    PYTHON_MODE = 1
    CYTHON_MODE = 2
    DASK_MODE = 4
    RAPIDS_MODE = 16
    _INSTALL_MASK = 0b11 << DASK_MODE
    _INSTALL_MODE = 0b01 << DASK_MODE
    _UPDATE_MODE = 0b10 << DASK_MODE
    _SIMULATE_MODE = 0b11 << DASK_MODE
    _DEPLOYEMENT_MASK = 0b110000
    _RUN_MASK = 0b001111
    _RAPIDS_SET = 0b111111
    _RAPIDS_RESET = 0b110111
    _DASK_RESET = 0b111011
    _args: Optional[Dict[str, Any]] = None
    _dask_client: Optional[Client] = None
    _dask_scheduler: Optional[Any] = None
    _dask_workers: Optional[List[str]] = None
    _jobs: Optional[bg.BackgroundJobManager] = None
    _local_ip: List[str] = []
    _install_done_local: bool = False
    _mode: Optional[int] = None
    _mode_auto: bool = False
    _remote_ip: List[str] = []
    _install_done: bool = False
    _install_todo: Optional[int] = 0
    _scheduler: Optional[str] = None
    _scheduler_ip: Optional[str] = None
    _target: Optional[str] = None
    verbose: Optional[int] = None
    _worker_init_error: bool = False
    _workers: Optional[Dict[str, int]] = None
    _capacity: Optional[Dict[str, float]] = None
    _capacity_data_file: Optional[Path] = None
    _capacity_model_file: Optional[Path] = None
    _capacity_predictor: Optional[RandomForestRegressor] = None
    _worker_default: Dict[str, int] = _workers_default
    _run_time: Dict[str, Any] = {}
    _run_type: Optional[str] = None
    _run_types: List[str] = []
    _target_built: Optional[Any] = None
    _module_to_clean: List[str] = []
    _ssh_connections = {}
    _best_mode: Dict[str, Any] = {}
    _work_plan: Optional[Any] = None
    _work_plan_metadata: Optional[Any] = None
    debug: Optional[bool] = None  # Cache with default local IPs
    env: Optional[AgiEnv] = None
    _service_futures: Dict[str, Any] = {}
    _service_workers: List[str] = []
    _service_shutdown_on_stop: bool = True
    _service_stop_timeout: Optional[float] = 30.0
    _service_poll_interval: Optional[float] = None

    def __init__(self, target: str, verbose: int = 1):
        """
        Initialize a Agi object with a target and verbosity level.

        Args:
            target (str): The target for the env object.
            verbose (int): Verbosity level (0-3).

        Returns:
            None

        Raises:
            None
        """
        # At the top of __init__:
        if hasattr(AGI, "_instantiated") and AGI._instantiated:
            raise RuntimeError("AGI class is a singleton. Only one instance allowed per process.")
        AGI._instantiated = True

    @staticmethod
    async def run(
            env: AgiEnv,  # some_default_value must be defined
            scheduler: Optional[str] = None,
            workers: Optional[Dict[str, int]] = None,
            verbose: int = 0,
            mode: Optional[Union[int, List[int], str]] = None,
            rapids_enabled: bool = False,
            **args: Any,
    ) -> Any:
        """
        Compiles the target module in Cython and runs it on the cluster.

        Args:
            target (str): The target Python module to run.
            scheduler (str, optional): IP and port address of the Dask scheduler. Defaults to '127.0.0.1:8786'.
            workers (dict, optional): Dictionary of worker IPs and their counts. Defaults to `workers_default`.
            verbose (int, optional): Verbosity level. Defaults to 0.
            mode (int or list, optional): Mode(s) for execution. Defaults to None.
                - Bitmask `0b----` (4 bits) where each bit enables/disables specific features:
                    - `1---`: Rapids
                    - `-1--`: Dask
                    - `--1-`: Cython
                    - `---1`: Pool
                - `mode` can also be a list of modes to chain for the run.
            rapids_enabled (bool, optional): Flag to enable RAPIDS. Defaults to False.
            **args (Any): Additional keyword arguments.

        Returns:
            Any: Result of the execution.

        Raises:
            ValueError: If `mode` is invalid.
            RuntimeError: If the target module fails to load.
        """
        AGI.env = env

        if not workers:
            workers = _workers_default
        elif not isinstance(workers, dict):
            raise ValueError("workers must be a dict. {'ip-address':nb-worker}")

        AGI.target_path = env.manager_path
        AGI._target = env.target
        AGI._rapids_enabled = rapids_enabled
        if env.verbose > 0:
            logger.info(f"AGI instance created for target {env.target} with verbosity {env.verbose}")

        if mode is None or isinstance(mode, list):
            mode_range = range(8) if mode is None else sorted(mode)
            return await AGI._benchmark(
                env, scheduler, workers, verbose, mode_range, rapids_enabled, **args
            )
        else:
            if isinstance(mode, str):
                pattern = r"^[dcrp]+$"
                if not re.fullmatch(pattern, mode.lower()):
                    raise ValueError("parameter <mode> must only contain the letters 'd', 'c', 'r', 'p'")
                AGI._mode = env.mode2int(mode)
            elif isinstance(mode, int):
                AGI._mode = int(mode)
            else:
                raise ValueError("parameter <mode> must be an int, a list of int or a string")

            AGI._run_types = ["run --no-sync", "sync --dev", "sync --upgrade --dev", "simulate"]
            if AGI._mode:
                if AGI._mode & AGI._RUN_MASK not in range(0, AGI.RAPIDS_MODE):
                    raise ValueError(f"mode {AGI._mode} not implemented")
            else:
                # 16 first modes are "run" type, then there 16, 17 and 18
                AGI._run_type = AGI._run_types[(AGI._mode & AGI._DEPLOYEMENT_MASK) >> AGI.DASK_MODE]
            AGI._args = args
            AGI.verbose = verbose
            AGI._workers = workers
            AGI._run_time = {}

            AGI._capacity_data_file = env.resources_path / "balancer_df.csv"
            AGI._capacity_model_file = env.resources_path / "balancer_model.pkl"
            path = Path(AGI._capacity_model_file)

            if path.is_file():
                with open(path, "rb") as f:
                    AGI._capacity_predictor = pickle.load(f)
            else:
                AGI._train_capacity(env.home_abs)

            # import of derived Class of WorkDispatcher, name target_inst which is typically instance of Flight or MyCode
            AGI.agi_workers = {
                "PolarsWorker": "polars-worker",
                "PandasWorker": "pandas-worker",
                "FireducksWorker": "fireducks-worker",
                "DagWorker": "dag-worker",
            }
            AGI.install_worker_group = [AGI.agi_workers[env.base_worker_cls]]

            try:
                return await AGI._main(scheduler)

            except ProcessError as e:
                logger.error(f"failed to run \n{e}")
                return

            except ConnectionError as e:
                logger.error(f"failed to connect \n{e}")
                return

            except ModuleNotFoundError as e:
                logger.error(f"failed to load module \n{e}")
                return

            except Exception as err:
                logger.error(f"Unhandled exception in AGI.run: {err}", exc_info=True)
                logger.info(traceback.format_exc())

    @staticmethod
    async def serve(
            env: AgiEnv,
            scheduler: Optional[str] = None,
            workers: Optional[Dict[str, int]] = None,
            verbose: int = 0,
            mode: Optional[Union[int, str]] = None,
            rapids_enabled: bool = False,
            action: str = "start",
            poll_interval: Optional[float] = None,
            shutdown_on_stop: bool = True,
            stop_timeout: Optional[float] = 30.0,
            **args: Any,
    ) -> Dict[str, Any]:
        """Manage persistent worker services without invoking the run workplan.

        ``action="start"`` provisions workers and submits ``BaseWorker.loop`` as a
        long-lived service task pinned to each Dask worker. ``action="stop"``
        signals the loop through ``BaseWorker.break`` and optionally tears down
        the Dask cluster when ``shutdown_on_stop`` is true.
        """

        command = (action or "start").lower()
        if command not in {"start", "stop"}:
            raise ValueError("action must be 'start' or 'stop'")

        AGI._service_shutdown_on_stop = shutdown_on_stop
        AGI._service_stop_timeout = stop_timeout
        AGI._service_poll_interval = poll_interval

        if command == "stop":
            client = AGI._dask_client

            if not AGI._service_futures:
                logger.info("AGI.serve(stop): no active service loops to stop.")
                if shutdown_on_stop and client:
                    await AGI._stop()
                if AGI._jobs:
                    AGI._clean_job(True)
                return {"status": "idle", "workers": [], "pending": []}

            if client is None:
                logger.error(
                    "AGI.serve(stop): service futures registered but Dask client is unavailable"
                )
                pending = list(AGI._service_futures.keys())
                AGI._service_futures.clear()
                AGI._service_workers = []
                if AGI._jobs:
                    AGI._clean_job(True)
                return {"status": "error", "workers": [], "pending": pending}

            future_map = {future: worker for worker, future in AGI._service_futures.items()}

            break_tasks = [
                client.submit(
                    BaseWorker.break_loop,
                    workers=[worker],
                    allow_other_workers=False,
                    pure=False,
                    key=f"agi-serve-break-{env.target}-{worker.replace(':', '-')}",
                )
                for worker in list(AGI._service_futures.keys())
            ]
            client.gather(break_tasks)

            wait_kwargs: Dict[str, Any] = {}
            if stop_timeout is not None:
                wait_kwargs["timeout"] = stop_timeout

            done, not_done = wait(list(future_map.keys()), **wait_kwargs)

            stopped_workers = [future_map[f] for f in done]
            pending_workers = [future_map[f] for f in not_done]

            if done:
                client.gather(list(done), errors="raise")

            if pending_workers:
                logger.warning(
                    "Service loop shutdown timed out on workers: %s", pending_workers
                )

            AGI._service_futures.clear()
            AGI._service_workers = []

            if shutdown_on_stop:
                await AGI._stop()

            if AGI._jobs:
                AGI._clean_job(True)

            status = "stopped" if not pending_workers else "partial"
            return {"status": status, "workers": stopped_workers, "pending": pending_workers}

        # command == "start"
        if AGI._service_futures:
            raise RuntimeError(
                "Service loop already running. Please call AGI.serve(..., action='stop') first."
            )

        if not workers:
            workers = _workers_default
        elif not isinstance(workers, dict):
            raise ValueError("workers must be a dict. {'ip-address':nb-worker}")

        AGI._jobs = bg.BackgroundJobManager()
        AGI.env = env
        AGI.target_path = env.manager_path
        AGI._target = env.target
        AGI._rapids_enabled = rapids_enabled

        if env.verbose > 0:
            logger.info(
                "AGI service instance created for target %s with verbosity %s",
                env.target,
                env.verbose,
            )

        if mode is None:
            AGI._mode = AGI.DASK_MODE
        elif isinstance(mode, str):
            pattern = r"^[dcrp]+$"
            if not re.fullmatch(pattern, mode.lower()):
                raise ValueError("parameter <mode> must only contain the letters 'd', 'c', 'r', 'p'")
            AGI._mode = env.mode2int(mode)
        elif isinstance(mode, int):
            AGI._mode = int(mode)
        else:
            raise ValueError("parameter <mode> must be an int or a string")

        if not (AGI._mode & AGI.DASK_MODE):
            raise ValueError("AGI.serve requires Dask mode (include 'd' in mode)")

        if AGI._mode & AGI._RUN_MASK not in range(0, AGI.RAPIDS_MODE):
            raise ValueError(f"mode {AGI._mode} not implemented")

        AGI._mode_auto = False
        AGI._run_types = ["run --no-sync", "sync --dev", "sync --upgrade --dev", "simulate"]
        AGI._run_type = AGI._run_types[0]
        AGI._args = args
        AGI.verbose = verbose
        AGI._workers = workers
        AGI._run_time = {}

        AGI._capacity_data_file = env.resources_path / "balancer_df.csv"
        AGI._capacity_model_file = env.resources_path / "balancer_model.pkl"
        path = Path(AGI._capacity_model_file)

        if path.is_file():
            with open(path, "rb") as f:
                AGI._capacity_predictor = pickle.load(f)
        else:
            AGI._train_capacity(env.home_abs)

        AGI.agi_workers = {
            "PolarsWorker": "polars-worker",
            "PandasWorker": "pandas-worker",
            "FireducksWorker": "fireducks-worker",
            "DagWorker": "dag-worker",
        }
        AGI.install_worker_group = [AGI.agi_workers[env.base_worker_cls]]

        client = AGI._dask_client
        if client is None or getattr(client, "status", "") in {"closed", "closing"}:
            await AGI._start(scheduler)
            client = AGI._dask_client
        else:
            await AGI._sync()

        if client is None:
            raise RuntimeError("Failed to obtain Dask client for service start")

        AGI._dask_workers = [
            worker.split("/")[-1]
            for worker in list(client.scheduler_info()["workers"].keys())
        ]

        dask_workers = list(AGI._dask_workers)

        init_futures = [
            client.submit(
                BaseWorker._new,
                env=0 if env.debug else None,
                app=env.target_worker,
                mode=AGI._mode,
                verbose=AGI.verbose,
                worker_id=index,
                worker=worker,
                args=AGI._args,
                workers=[worker],
                allow_other_workers=False,
                pure=False,
                key=f"agi-worker-init-{env.target}-{worker.replace(':', '-')}",
            )
            for index, worker in enumerate(dask_workers)
        ]
        client.gather(init_futures)

        service_futures: Dict[str, Any] = {}
        for worker in dask_workers:
            future = client.submit(
                BaseWorker.loop,
                poll_interval=poll_interval,
                workers=[worker],
                allow_other_workers=False,
                pure=False,
                key=f"agi-serve-loop-{env.target}-{worker.replace(':', '-')}",
            )
            service_futures[worker] = future

        AGI._service_futures = service_futures
        AGI._service_workers = dask_workers

        logger.info("Service loops started for workers: %s", dask_workers)
        return {"status": "running", "workers": dask_workers, "pending": []}

    @staticmethod
    async def _benchmark(
            env: AgiEnv,
            scheduler: Optional[str] = None,
            workers: Optional[Dict[str, int]] = None,
            verbose: int = 0,
            mode_range: Optional[Union[List[int], range]] = None,
            rapids_enabled: Optional[bool] = None,
            **args: Any,
    ) -> str:
        """
        Run all modes to find the fastest one.

        Returns:
            dict: A dictionary where keys are each mode (from mode_range) and values are dicts
                  with keys including:
                    - "mode": an identifying string for the mode,
                    - "timing": a human-readable formatted string of the runtime,
                    - "time": the runtime in seconds (as a float),
                    - "order": the rank order (an integer, 1 for fastest, etc.).
        """
        rapids_mode_mask = AGI._RAPIDS_SET if rapids_enabled else AGI._RAPIDS_RESET
        if not BaseWorker._is_cython_installed(env):
            await AGI.install(
                env,
                scheduler=scheduler,
                workers=workers,
                verbose=verbose,
                modes_enabled=AGI.CYTHON_MODE,
                **args,
            )
        AGI._mode_auto = True
        runs = {}
        if env.benchmark.exists():
            os.remove(env.benchmark)
        for m in mode_range:
            # Determine which run mode to use.
            run_mode = m & rapids_mode_mask if rapids_enabled else m

            # Run the target with the current mode.
            run = await AGI.run(
                env,
                scheduler=scheduler,
                workers=workers,
                mode=run_mode,
                **args,
            )
            if isinstance(run, str):
                # Assume run string splits into two parts:
                #  runtime[0] -> an identifying string for the mode,
                #  runtime[1] -> the time in seconds as a float
                runtime = run.split()
                if len(runtime) < 2:
                    raise ValueError(f"Unexpected run format: {run}")
                runtime_float = float(runtime[1])

                # Store in dictionary with key m
                runs[m] = {
                    "mode": runtime[0],
                    "timing": humanize.precisedelta(timedelta(seconds=runtime_float)),
                    "seconds": runtime_float,
                }

        # Sort the runs by "seconds" (fastest to slowest) and assign order values.
        ordered_runs = sorted(runs.items(), key=lambda item: item[1]["seconds"])
        for idx, (mode_key, run_data) in enumerate(ordered_runs, start=1):
            run_data["order"] = idx

        # The fastest run is the first in the ordered list.
        if not ordered_runs:
            raise RuntimeError("No ordered runs available after sorting.")

        best_mode_key, best_run_data = ordered_runs[0]

        # Calculate delta based on "seconds"
        for m in runs:
            runs[m]["delta"] = runs[m]["seconds"] - best_run_data["seconds"]

        AGI._best_mode[env.target] = best_run_data
        AGI._mode_auto = False

        # Convert numeric keys to strings for valid JSON output.
        runs_str_keys = {str(k): v for k, v in runs.items()}

        # Return a JSON-formatted string
        with open(env.benchmark, "w") as f:
            json.dump(runs_str_keys, f)

        return json.dumps(runs_str_keys)

    @staticmethod
    def get_default_local_ip() -> str:
        """
        Get the default local IP address of the machine.

        Returns:
            str: The default local IP address.

        Raises:
            Exception: If unable to determine the local IP address.
        """
        """ """
        try:
            # Attempt to connect to a non-local address and capture the local endpoint's IP
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            return "Unable to determine local IP"

    @staticmethod
    def find_free_port(start: int = 5000, end: int = 10000, attempts: int = 100) -> int:
        for _ in range(attempts):
            port = random.randint(start, end)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                # set SO_REUSEADDR to avoid 'address already in use' issues during testing
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    sock.bind(("localhost", port))
                    # if binding succeeds, the port is free; close socket and return port
                    return port
                except OSError:
                    # port is already in use, try another
                    continue
        raise RuntimeError("No free port found in the specified range.")

    @staticmethod
    def _get_scheduler(ip_sched: Optional[Union[str, Dict[str, int]]] = None) -> Tuple[str, int]:
        """get scheduler ip V4 address
        when no scheduler provided, scheduler address is localhost or the first address if workers are not local.
        port is random

        Args:
          ip_sched:

        Returns:

        """
        port = AGI.find_free_port()
        if not ip_sched:
            if AGI._workers:
                ip = list(AGI._workers)[0]
            else:
                ip = socket.gethostbyname("localhost")
        elif isinstance(ip_sched, dict):
            # end-user already has provided a port
            ip, port = list(ip_sched.items())[0]
        elif not isinstance(ip_sched, str):
            raise ValueError("Scheduler ip address is not valid")
        else:
            ip = ip_sched
        AGI._scheduler = f"{ip}:{port}"
        return ip, port

    @staticmethod
    def _get_stdout(func: Any, *args: Any, **kwargs: Any) -> Tuple[str, Any]:
        """to get the stdout stream

        Args:
          func: param args:
          kwargs: return: the return of the func
          *args:
          **kwargs:

        Returns:
          : the return of the func

        """
        f = io.StringIO()
        with redirect_stdout(f):
            result = func(*args, **kwargs)
        return f.getvalue(), result

    @staticmethod
    def _read_stderr(output_stream: Any) -> None:
        """Read remote stderr robustly on Linux (UTF-8), Windows OEM (CP850), then ANSI (CP1252)."""

        def decode_bytes(bs: bytes) -> str:
            # try UTF-8, then OEM (CP850) for console accents, then ANSI (CP1252)
            for enc in ('utf-8', 'cp850', 'cp1252'):
                try:
                    return bs.decode(enc)
                except Exception:
                    continue
            # final fallback
            return bs.decode('cp850', errors='replace')

        chan = getattr(output_stream, 'channel', None)
        if chan is None:
            # simple iteration fallback
            for raw in output_stream:
                if isinstance(raw, bytes):
                    decoded = decode_bytes(raw)
                else:
                    decoded = decode_bytes(raw.encode('latin-1', errors='replace'))
                line = decoded.strip()
                logger.info(line)
                AGI._worker_init_error = line.endswith('[ProjectError]')
            return

        # non-blocking channel read
        while True:
            if chan.recv_stderr_ready():
                try:
                    raw = chan.recv_stderr(1024)
                except Exception:
                    continue
                if not raw:
                    break
                decoded = decode_bytes(raw)
                for part in decoded.splitlines():
                    line = part.strip()
                    logger.info(line)
                    AGI._worker_init_error = line.endswith('[ProjectError]')
            elif chan.exit_status_ready():
                break
            else:
                time.sleep(0.1)

    @staticmethod
    async def send_file(
            env: AgiEnv,
            ip: str,
            local_path: Path,
            remote_path: Path,
            user: str = None,
            password: str = None
    ):
        if AgiEnv.is_local(ip):
            shutil.copyfile(local_path, remote_path)
            return

        if not user:
            user = env.user
        if not password:
            password = env.password

        user_at_ip = f"{user}@{ip}" if user else ip
        remote = f"{user_at_ip}:{remote_path}"

        cmd, cmd_base = [], []

        if password and os.name != "nt":
            cmd_base = ["sshpass"]
            cmd += cmd_base + ["-p", password]

        cmd_end = ["scp", str(local_path), remote]
        cmd = cmd + cmd_end

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                logger.error(f"SCP failed sending {local_path} to {remote}: {stderr.decode().strip()}")
                raise ConnectionError(f"SCP error: {stderr.decode().strip()}")

            logger.info(f"Sent file {local_path} to {remote}")

        except Exception as e:
            try:
                cmd = cmd_base + cmd_end
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await process.communicate()

                if process.returncode:
                    logger.error(f"SCP failed sending {local_path} to {remote}: {stderr.decode().strip()}")
                    raise ConnectionError(f"SCP error: {stderr.decode().strip()}")

                logger.info(f"Sent file {local_path} to {remote}")

            except Exception as e:
                raise

    @staticmethod
    async def send_files(env: AgiEnv, ip: str, files: list[Path], remote_dir: Path, user: str = None):
        tasks = []
        for f in files:
            remote_path = remote_dir / f.name
            tasks.append(AGI.send_file(env, ip, f, remote_path, user=user))
        await asyncio.gather(*tasks)
        # logger.info(f"Sent {len(files)} files to {user if user else self.user}@{ip}:{remote_dir}")

    @staticmethod
    def _remove_dir_forcefully(path):
        import shutil
        import os
        import time

        def onerror(func, path, exc_info):
            import stat
            if not os.access(path, os.W_OK):
                os.chmod(path, stat.S_IWUSR)
                func(path)
            else:
                logger.info(f"{path} not removed due to {exc_info[1]}")

        try:
            shutil.rmtree(path, onerror=onerror)
        except Exception as e:
            logger.error(f"Exception while deleting {path}: {e}")
            time.sleep(1)
            try:
                shutil.rmtree(path, onerror=onerror)
            except Exception as e2:
                logger.error(f"Second failure deleting {path}: {e2}")
                raise

    @staticmethod
    async def _kill(ip: Optional[str] = None, current_pid: Optional[int] = None, force: bool = True) -> Optional[Any]:
        """
        Terminate 'uv' and Dask processes on the given host and clean up pid files.

        Args:
            ip (str, optional): IP address of the host to kill processes on. Defaults to local host.
            current_pid (int, optional): PID of this process to exclude. Defaults to this process.
            force (bool, optional): Whether to kill all 'dask' processes by name. Defaults to True.
        Returns:
            The result of the last kill command (dict or None).
        """
        env = AGI.env
        uv = env.uv
        localhost = socket.gethostbyname("localhost")
        ip = ip or localhost
        current_pid = current_pid or os.getpid()

        # 1) Collect PIDs from any pid files and remove those files
        pids_to_kill: list[int] = []
        for pid_file in Path(env.wenv_abs.parent).glob("*.pid"):
            try:
                text = pid_file.read_text().strip()
                pid = int(text)
                if pid != current_pid:
                    pids_to_kill.append(pid)
            except Exception:
                logger.warning(f"Could not read PID from {pid_file}, skipping")
            try:
                pid_file.unlink()
            except Exception as e:
                logger.warning(f"Failed to remove pid file {pid_file}: {e}")

        cmds: list[str] = []
        cli_rel = env.wenv_rel.parent / "cli.py"
        cli_abs = env.wenv_abs.parent / cli_rel.name
        cmd_prefix = env.envars.get(f"{ip}_CMD_PREFIX", "")
        kill_prefix = f'{cmd_prefix}{uv} run --no-sync python'

        if env.is_local(ip):
            if not (cli_abs).exists():
                shutil.copy(env.cluster_pck / "agi_distributor/cli.py", cli_abs)
            if force:
                cmd = f"{kill_prefix} '{cli_abs}' kill"
                cmds.append(cmd)
        else:
            if force:
                cmd = f"{kill_prefix} '{cli_rel}' kill"
                cmds.append(cmd)

        last_res = None
        for cmd in cmds:
            # choose working directory based on local vs remote
            cwd = env.agi_cluster if ip == localhost else str(env.wenv_abs)
            if env.is_local(ip):
                if env.debug:
                    sys.argv = cmd.split('python ')[1].split(" ")
                    runpy.run_path(sys.argv[0], run_name="__main__")
                else:
                    await AgiEnv.run(cmd, cwd)
            else:
                cli = env.wenv_rel.parent / "cli.py"
                last_res = await AGI.exec_ssh(ip, cmd)

            # handle tuple or dict result
            if isinstance(last_res, dict):
                out = last_res.get("stdout", "")
                err = last_res.get("stderr", "")
                logger.info(out)
                if err:
                    logger.error(err)

        return last_res

    @staticmethod
    def _clean_dirs_local() -> None:
        """Clean up local worker env directory

        Args:
          wenv: worker environment dictionary

        Returns:

        """
        me = getpass.getuser()
        self_pid = os.getpid()
        for p in psutil.process_iter(['pid', 'username', 'cmdline']):
            try:
                if (
                        p.info['username'] and p.info['username'].endswith(me)
                        and p.info['pid'] and p.info['pid'] != self_pid
                        and p.info['cmdline']
                        and any('dask' in s.lower() for s in p.info['cmdline'])
                ):
                    p.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        for d in [
            f"{gettempdir()}/dask-scratch-space",
            f"{AGI.env.wenv_abs}",
        ]:
            try:
                shutil.rmtree(d, ignore_errors=True)
            except:
                pass

    @staticmethod
    async def _clean_dirs(ip: str) -> None:
        """Clean up remote worker

        Args:
          ip: address of remote worker

        Returns:

        """
        env = AGI.env
        uv = env.uv
        wenv_abs = env.wenv_abs
        if wenv_abs.exists():
            AGI._remove_dir_forcefully(str(wenv_abs))
        os.makedirs(wenv_abs / "src", exist_ok=True)
        cmd_prefix = env.envars.get(f"{ip}_CMD_PREFIX", "")
        wenv = env.wenv_rel
        cli = wenv.parent / 'cli.py'
        cmd = (f"{cmd_prefix}{uv} run --no-sync -p {env.python_version} python {cli} clean {wenv}")
        await AGI.exec_ssh(ip, cmd)

    @staticmethod
    async def _clean_nodes(scheduler_addr: Optional[str], force: bool = True) -> Set[str]:
        # Compose list of IPs: workers plus scheduler's IP
        list_ip = set(list(AGI._workers) + [AGI._get_scheduler(scheduler_addr)[0]])
        localhost_ip = socket.gethostbyname("localhost")
        if not list_ip:
            list_ip.add(localhost_ip)

        for ip in list_ip:
            if AgiEnv.is_local(ip):
                # Assuming this cleans local dirs once per IP (or should be once per call)
                AGI._clean_dirs_local()

        await AGI._clean_remote_procs(list_ip=list_ip, force=force)
        await AGI._clean_remote_dirs(list_ip=list_ip)

        return list_ip

    @staticmethod
    async def _clean_remote_procs(list_ip: Set[str], force: bool = True) -> None:
        tasks = []
        for ip in list_ip:
            if not AgiEnv.is_local(ip):
                tasks.append(asyncio.create_task(AGI._kill(ip, os.getpid(), force=force)))

        if tasks:
            await asyncio.gather(*tasks)

    @staticmethod
    async def _clean_remote_dirs(list_ip: Set[str]) -> None:
        tasks = []
        for ip in list_ip:
            tasks.append(asyncio.create_task(AGI._clean_dirs(ip)))
        if tasks:
            await asyncio.gather(*tasks)

    @staticmethod
    async def _prepare_local_env() -> None:
        """
        Validate and prepare each remote node in the cluster:
        - Verify each IP is valid and reachable.
        - Detect and install Python interpreters if missing.
        - Detect and install 'uv' CLI via pip if missing.
        - Use 'uv' to install the specified Pytho
        n version, create necessary directories, and install packages.
        """
        env = AGI.env
        wenv_abs = env.wenv_abs
        pyvers = env.python_version
        env = AGI.env
        ip = "127.0.0.1"
        hw_rapids_capable = AGI._hardware_supports_rapids() and AGI._rapids_enabled
        env.hw_rapids_capable = hw_rapids_capable

        os.makedirs(wenv_abs, exist_ok=True)
        file = env.worker_pyproject
        if env.verbose > 0:
            logger.info(f"Copying {file} -> {wenv_abs}")
        shutil.copy(file, wenv_abs / file.name)

        file = env.cli
        if env.verbose > 0:
            logger.info(f"Copying {file} -> {wenv_abs.parent}")
        shutil.copy(file, wenv_abs.parent)

        if hw_rapids_capable:
            AgiEnv.set_env_var(ip, "hw_rapids_capable")
        else:
            AgiEnv.set_env_var(ip, "no_rapids_hw")

        if env.verbose > 0:
            logger.info(f"Rapids-capable GPU[{ip}]: {hw_rapids_capable}")

        # # Install Python

        # TODO: Check install freethreaded for workers only

        cmd_prefix = await AGI._detect_export_cmd(ip)
        AgiEnv.set_env_var(f"{ip}_CMD_PREFIX", cmd_prefix)
        # uv = cmd_prefix + env.uv

        #
        # AgiEnv.run(f"{uv} python install {pyvers}", wenv_abs.parent)
        #
        # cli = wenv_abs.parent / file.name
        # cmd = f"{uv} run python {cli} platform"
        # res = await AgiEnv.run(cmd, wenv_abs.parent)
        # pyvers = res.split(':')[-1].strip()
        # AgiEnv.set_env_var(f"{ip}_PYTHON_VERSION", pyvers)
        # await AgiEnv.run(f"{cmd_prefix}{env.uv} python install {pyvers}", wenv_abs)

        # cmd = (
        #     f"{uv} --project {wenv_abs} init --bare --no-workspace"
        # )
        # await AgiEnv.run(cmd, wenv_abs)

        # cmd = f"{uv} run -p {pyvers} --project {wenv_abs} python {cli} threaded"
        # await AgiEnv.run(cmd, wenv_abs)

    @staticmethod
    async def _prepare_cluster_env(scheduler_addr: Optional[str]) -> None:
        """
        Validate and prepare each remote node in the cluster:
        - Verify each IP is valid and reachable.
        - Detect and install Python interpreters if missing.
        - Detect and install 'uv' CLI via pip if missing.
        - Use 'uv' to install the specified Pytho
        n version, create necessary directories, and install packages.
        """
        list_ip = set(list(AGI._workers) + [AGI._get_scheduler(scheduler_addr)[0]])
        localhost_ip = socket.gethostbyname("localhost")
        env = AGI.env
        dist_rel = env.dist_rel
        wenv_rel = env.wenv_rel
        pyvers_worker = env.pyvers_worker

        # You can remove this check or keep it if you expect no scheduler/workers (rare)
        if not list_ip:
            list_ip.add(localhost_ip)

        # Validate IPs
        for ip in list_ip:
            if not env.is_local(ip) and not is_ip(ip):
                raise ValueError(f"Invalid IP address: {ip}")

        # Prepare each remote node (skip local)
        AGI.list_ip = list_ip
        for ip in list_ip:
            if env.is_local(ip):
                continue

            # 1) Check if need to export path (linux and macos)
            cmd_prefix = await AGI._detect_export_cmd(ip)
            AgiEnv.set_env_var(f"{ip}_CMD_PREFIX", cmd_prefix)
            uv_is_installed = True

            # 2) Check uv
            try:
                await AGI.exec_ssh(ip, f"{cmd_prefix}{env.uv} --version")
                await AGI.exec_ssh(ip, f"{cmd_prefix}{env.uv} self update")
            except Exception:
                uv_is_installed = False
                # Try Windows installer
                try:
                    await AGI.exec_ssh(ip,
                                       'powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
                                       )
                    uv_is_installed = True
                except Exception:
                    uv_is_installed = False
                    # Fallback to Unix installer
                    await AGI.exec_ssh(ip, 'curl -LsSf https://astral.sh/uv/install.sh | sh')
                    # Rely on PATH export via cmd_prefix for subsequent commands
                    # await AGI.exec_ssh(ip, 'source ~/.local/bin/env')
                    uv_is_installed = True

            if not uv_is_installed or not AgiEnv.check_internet():
                logger.error("Failed to install uv")
                raise EnvironmentError("Failed to install uv")

            # 3) Install Python
            cmd_prefix = env.envars.get(f"{ip}_CMD_PREFIX", "")
            uv = cmd_prefix + env.uv

            cmd = f"{uv} run python -c \"import os; os.makedirs('{dist_rel}', exist_ok=True)\""
            await AGI.exec_ssh(ip, cmd)

            await AGI.exec_ssh(ip, f"{uv} python install {pyvers_worker}")
            await AGI.send_files(env, ip, [env.cluster_pck / "agi_distributor/cli.py"],
                                 wenv_rel.parent)

            # cmd = f"{uv} run --no-sync python {cli} platform"
            # res =  await AGI.exec_ssh(ip, cmd)
            # pyvers_worker = res.split(':')[-1]
            # AgiEnv.set_env_var(f"{ip}_PYTHON_VERSION", pyvers_worker)
            # await AGI.exec_ssh(ip, f"{cmd_prefix}{env.uv} python install {pyvers_worker}")

            await AGI._kill(ip, force=True)
            await AGI._clean_dirs(ip)

            cmd = f"{uv} --project {wenv_rel} init --bare --no-workspace"
            await AGI.exec_ssh(ip, cmd)

            # cmd = f"{uv} run --no-sync -p {pyvers} python {env.wenv_rel.parent / "cli.py"} platform"
            # await AGI.exec_ssh(ip, cmd)

    @staticmethod
    async def _deploy_application(scheduler_addr: Optional[str]) -> None:
        AGI._reset_deploy_state()
        env = AGI.env
        app_path = env.active_app
        wenv_rel = env.wenv_rel
        if isinstance(env.base_worker_cls, str):
            options_worker = " --extra " + " --extra ".join(AGI.install_worker_group)

        # node_ips = await AGI._clean_nodes(scheduler)
        node_ips = set(list(AGI._workers) + [AGI._get_scheduler(scheduler_addr)[0]])
        AGI._venv_todo(node_ips)
        start_time = time.time()
        if env.verbose > 0:
            logger.info(f"Installing {app_path} on 127.0.0.1")

        await AGI._deploy_local_worker(app_path, Path(wenv_rel), options_worker)
        # logger.info(AGI.run(cmd, wenv_abs))
        if AGI._mode & 4:
            tasks = []
            for ip in node_ips:
                if env.verbose > 0:
                    logger.info(f"Installing worker on {ip}")
                if not env.is_local(ip):
                    tasks.append(asyncio.create_task(
                        AGI._deploy_remote_worker(ip, env, wenv_rel, options_worker)
                    ))
            await asyncio.gather(*tasks)

        if AGI.verbose:
            duration = AGI._format_elapsed(time.time() - start_time)
            if env.verbose > 0:
                logger.info(f"uv {AGI._run_type} completed in {duration}")

    @staticmethod
    def _reset_deploy_state() -> None:
        """Initialize installation flags and run type."""
        AGI._run_type = AGI._run_types[(AGI._mode & AGI._DEPLOYEMENT_MASK) >> 4]
        AGI._install_done_local = False
        AGI._install_done = False
        AGI._worker_init_error = False

    @staticmethod
    def _hardware_supports_rapids() -> bool:
        try:
            subprocess.run(
                ["nvidia-smi"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    @staticmethod
    async def _deploy_local_worker(src: Path, wenv_rel: Path, options_worker: str) -> None:
        """
        Installe l’environnement localement.

        Args:
            src: chemin vers la racine du projet local
            wenv_rel: chemin relatif vers l’environnement virtuel local
            options_worker: le setup
        """
        env = AGI.env
        run_type = AGI._run_type
        if (not env.is_source_env) and (not env.is_worker_env) and isinstance(run_type, str) and "--dev" in run_type:
            run_type = " ".join(part for part in run_type.split() if part != "--dev")
        ip = "127.0.0.1"
        hw_rapids_capable = AGI._hardware_supports_rapids() and AGI._rapids_enabled
        env.hw_rapids_capable = hw_rapids_capable
        repo_root: Path | None = None
        repo_env_project: Path | None = None
        repo_node_project: Path | None = None
        repo_core_project: Path | None = None
        repo_cluster_project: Path | None = None
        repo_agilab_root: Path | None = None
        dependency_info: dict[str, dict[str, Any]] = {}
        dep_versions: dict[str, str] = {}
        worker_pyprojects: set[str] = set()
        # in case of core src has changed
        AGI._build_lib_local()

        def _cleanup_editable(site_packages: Path) -> None:
            patterns = (
                '__editable__.agi_env*.pth',
                '__editable__.agi_node*.pth',
                '__editable__.agi_core*.pth',
                '__editable__.agi_cluster*.pth',
                '__editable__.agilab*.pth',
            )
            for pattern in patterns:
                for editable in site_packages.glob(pattern):
                    try:
                        editable.unlink()
                    except FileNotFoundError:
                        pass

        async def _ensure_pip(uv_cmd: str, project: Path) -> None:
            cmd = f"{uv_cmd} run --project '{project}' python -m ensurepip --upgrade"
            await AgiEnv.run(cmd, project)

        def _format_dependency_spec(name: str, extras: set[str], specifiers: list[str]) -> str:
            extras_part = ''
            if extras:
                extras_part = '[' + ','.join(sorted(extras)) + ']'
            spec_part = ''
            if specifiers:
                spec_part = ','.join(specifiers)
            return f"{name}{extras_part}{spec_part}"

        def _update_pyproject_dependencies(
            pyproject_file: Path,
            pinned_versions: dict[str, str] | None,
            *,
            filter_to_worker: bool = False,
        ) -> None:
            try:
                data = tomlkit.parse(pyproject_file.read_text())
            except FileNotFoundError:
                data = tomlkit.document()

            project_tbl = data.get("project")
            if project_tbl is None:
                project_tbl = tomlkit.table()

            deps = project_tbl.get("dependencies")
            if deps is None:
                deps = tomlkit.array()
            else:
                if not isinstance(deps, tomlkit.items.Array):
                    arr = tomlkit.array()
                    for item in deps:
                        arr.append(item)
                    deps = arr

            existing = {str(item) for item in deps}
            for key, meta in dependency_info.items():
                if filter_to_worker and worker_pyprojects and not (meta['sources'] & worker_pyprojects):
                    continue
                version = (pinned_versions or {}).get(key)
                if version:
                    extras_part = ''
                    if meta['extras']:
                        extras_part = '[' + ','.join(sorted(meta['extras'])) + ']'
                    spec = f"{meta['name']}{extras_part}=={version}"
                else:
                    spec = _format_dependency_spec(
                        meta['name'],
                        meta['extras'],
                        meta['specifiers'],
                    )
                if spec not in existing:
                    deps.append(spec)
                    existing.add(spec)

            project_tbl["dependencies"] = deps
            data["project"] = project_tbl
            pyproject_file.write_text(tomlkit.dumps(data))


        def _gather_dependency_specs(projects: list[Path | None]) -> None:
            seen_pyprojects: set[Path] = set()
            for project_path in projects:
                if not project_path:
                    continue
                pyproject_file = project_path / 'pyproject.toml'
                try:
                    resolved_pyproject = pyproject_file.resolve(strict=True)
                except FileNotFoundError:
                    continue
                if resolved_pyproject in seen_pyprojects:
                    continue
                seen_pyprojects.add(resolved_pyproject)
                try:
                    project_doc = tomlkit.parse(resolved_pyproject.read_text())
                except Exception:
                    continue
                deps = project_doc.get('project', {}).get('dependencies')
                if not deps:
                    continue
                for dep in deps:
                    try:
                        req = Requirement(str(dep))
                    except Exception:
                        continue
                    if req.marker and not req.marker.evaluate():
                        continue
                    normalized = req.name.lower()
                    if normalized.startswith('agi-') or normalized == 'agilab':
                        continue
                    meta = dependency_info.setdefault(
                        normalized,
                        {
                            'name': req.name,
                            'extras': set(),
                            'specifiers': [],
                            'has_exact': False,
                            'sources': set(),
                        },
                    )
                    if req.extras:
                        meta['extras'].update(req.extras)
                    meta['sources'].add(str(resolved_pyproject))
                    if req.specifier:
                        for specifier in req.specifier:
                            spec_str = str(specifier)
                            if specifier.operator in {'==', '==='}:
                                meta['has_exact'] = True
                                if not meta['specifiers'] or meta['specifiers'][0] != spec_str:
                                    meta['specifiers'] = [spec_str]
                                break
                            if meta['has_exact']:
                                continue
                            if spec_str not in meta['specifiers']:
                                meta['specifiers'].append(spec_str)

        if env.install_type == 0:
            repo_root = AgiEnv.read_agilab_path()
            if repo_root:
                repo_env_project = repo_root / "core" / "agi-env"
                repo_node_project = repo_root / "core" / "agi-node"
                repo_core_project = repo_root / "core" / "agi-core"
                repo_cluster_project = repo_root / "core" / "agi-cluster"
                try:
                    repo_agilab_root = repo_root.parents[1]
                except IndexError:
                    repo_agilab_root = None

            env_project = (
                repo_env_project
                if repo_env_project and repo_env_project.exists()
                else env.agi_env
            )
            node_project = (
                repo_node_project
                if repo_node_project and repo_node_project.exists()
                else env.agi_node
            )
            core_project = (
                repo_core_project
                if repo_core_project and repo_core_project.exists()
                else None
            )
            cluster_project = (
                repo_cluster_project
                if repo_cluster_project and repo_cluster_project.exists()
                else None
            )
            agilab_project = (
                repo_agilab_root
                if repo_agilab_root and repo_agilab_root.exists()
                else None
            )

            projects_for_specs = [
                agilab_project,
                env_project,
                node_project,
                core_project,
                cluster_project,
            ]
            _gather_dependency_specs(projects_for_specs)
            for project_path in (env_project, node_project, core_project, cluster_project):
                if not project_path:
                    continue
                pyproject_file = project_path / "pyproject.toml"
                try:
                    worker_pyprojects.add(str(pyproject_file.resolve(strict=True)))
                except FileNotFoundError:
                    continue
        else:
            env_project = env.agi_env
            node_project = env.agi_node
            core_project = None
            cluster_project = None
            agilab_project = None
            worker_pyprojects = set()

        wenv_abs = env.wenv_abs
        cmd_prefix = env.envars.get(f"{ip}_CMD_PREFIX", "")
        uv = cmd_prefix + env.uv
        pyvers = env.python_version

        if hw_rapids_capable:
            AgiEnv.set_env_var(ip, "hw_rapids_capable")
        else:
            AgiEnv.set_env_var(ip, "no_rapids_hw")

        if env.verbose > 0:
            logger.info(f"Rapids-capable GPU[{ip}]: {hw_rapids_capable}")

        # =========
        # MANAGER install command with and without rapids capable
        # =========

        app_path = env.active_app
        if (not env.is_source_env) and (not env.is_worker_env) and dependency_info:
            _update_pyproject_dependencies(
                app_path / "pyproject.toml",
                pinned_versions=None,
                filter_to_worker=False,
            )
        extra_indexes = ""
        if str(run_type).strip().startswith("sync") and _agi__version_missing_on_pypi(app_path):
            extra_indexes = (
                "PIP_INDEX_URL=https://test.pypi.org/simple "
                "PIP_EXTRA_INDEX_URL=https://pypi.org/simple "
            )
        if hw_rapids_capable:
            cmd_manager = (
                f"{extra_indexes}{uv} {run_type} --config-file uv_config.toml --project '{app_path}'"
            )
        else:
            cmd_manager = f"{extra_indexes}{uv} {run_type} --project '{app_path}'"

        if env.verbose > 0:
            logger.info(f"Installing manager: {cmd_manager}")
        await AgiEnv.run(cmd_manager, app_path)

        if (not env.is_source_env) and (not env.is_worker_env):
            await _ensure_pip(uv, app_path)

            for project_path in (
                agilab_project,
                env_project,
                node_project,
                core_project,
                cluster_project,
            ):
                if project_path and project_path.exists():
                    if repo_agilab_root and project_path.resolve() == repo_agilab_root.resolve():
                        continue
                    cmd = (
                        f"{uv} run --project '{app_path}' python -m pip install "
                        f"--upgrade --no-deps '{project_path}'"
                    )
                    await AgiEnv.run(cmd, app_path)

            resources_src = env_project / 'src/agi_env/resources'
            if not resources_src.exists():
                resources_src = env.env_pck / 'resources'
            manager_resources = app_path / 'agilab/core/agi-env/src/agi_env/resources'
            if resources_src.exists():
                manager_resources.parent.mkdir(parents=True, exist_ok=True)
                if manager_resources.exists():
                    shutil.rmtree(manager_resources)
                shutil.copytree(resources_src, manager_resources, dirs_exist_ok=True)

            site_packages_manager = env.env_pck.parent
            _cleanup_editable(site_packages_manager)

            if dependency_info:
                dep_versions = {}
                for key, meta in dependency_info.items():
                    try:
                        dep_versions[key] = pkg_version(meta['name'])
                    except PackageNotFoundError:
                        logger.debug("Dependency %s not installed in manager environment", meta['name'])

        if env.is_source_env:
            cmd = f"{uv} pip install -e '{env.agi_env}'"
            await AgiEnv.run(cmd, app_path)
            cmd = f"{uv} pip install -e '{env.agi_node}'"
            await AgiEnv.run(cmd, app_path)
            cmd = f"{uv} pip install -e '{env.agi_cluster}'"
            await AgiEnv.run(cmd, app_path)
            cmd = f"{uv} pip install -e ."
            await AgiEnv.run(cmd, app_path)

        # ========
        # WORKER install command with and without rapids capable
        # ========

        uv_worker = cmd_prefix + env.uv_worker
        pyvers_worker = env.pyvers_worker

        worker_extra_indexes = ""
        if str(run_type).strip().startswith("sync") and _agi__version_missing_on_pypi(wenv_abs):
            worker_extra_indexes = (
                "PIP_INDEX_URL=https://test.pypi.org/simple; "
                "PIP_EXTRA_INDEX_URL=https://pypi.org/simple; "
            )

        if (not env.is_source_env) and (not env.is_worker_env) and dep_versions:
            _update_pyproject_dependencies(
                wenv_abs / "pyproject.toml",
                dep_versions,
                filter_to_worker=True,
            )

        if hw_rapids_capable:
            cmd_worker = (
                f"{worker_extra_indexes}{uv_worker} {run_type} --python {pyvers_worker} "
                f"--config-file uv_config.toml --project '{wenv_abs}'"
            )
        else:
            cmd_worker = (
                f"{worker_extra_indexes}{uv_worker} {run_type} {options_worker} "
                f"--python {pyvers_worker} --project '{wenv_abs}'"
            )

        if env.verbose > 0:
            logger.info(f"Installing workers: {cmd_worker}")
        await AgiEnv.run(cmd_worker, wenv_abs)

        #############
        # install env
        ##############

        if (not env.is_source_env) and (not env.is_worker_env):
            await _ensure_pip(uv_worker, wenv_abs)

            worker_resources_src = env_project / 'src/agi_env/resources'
            if not worker_resources_src.exists():
                worker_resources_src = env.env_pck / 'resources'
            resources_dest = wenv_abs / 'agilab/core/agi-env/src/agi_env/resources'
            resources_dest.parent.mkdir(parents=True, exist_ok=True)
            if resources_dest.exists():
                shutil.rmtree(resources_dest)
            if worker_resources_src.exists():
                shutil.copytree(worker_resources_src, resources_dest, dirs_exist_ok=True)

            for project_path in (
                agilab_project,
                env_project,
                node_project,
                core_project,
                cluster_project,
            ):
                if project_path and project_path.exists():
                    if repo_agilab_root and project_path.resolve() == repo_agilab_root.resolve():
                        continue
                    cmd = (
                        f"{uv_worker} run --project '{wenv_abs}' python -m pip install "
                        f"--upgrade --no-deps '{project_path}'"
                    )
                    await AgiEnv.run(cmd, wenv_abs)

            python_dirs = env.pyvers_worker.split(".")
            if python_dirs[-1].endswith("t"):
                python_dir = f"{python_dirs[0]}.{python_dirs[1]}t"
            else:
                python_dir = f"{python_dirs[0]}.{python_dirs[1]}"
            site_packages_worker = (
                wenv_abs / ".venv" / "lib" / f"python{python_dir}" / "site-packages"
            )
            _cleanup_editable(site_packages_worker)

        else:
            # build agi_env*.whl
            menv = env.agi_env
            cmd = f"{uv} --project '{menv}' build --wheel"
            await AgiEnv.run(cmd, menv)
            src = menv / "dist"
            try:
                whl = next(iter(src.glob("agi_env*.whl")))
                # shutil.copy2(whl, wenv_abs)
            except StopIteration:
                raise RuntimeError(cmd)

            cmd = f"{uv_worker} pip install --project '{wenv_abs}' -e '{env.agi_env}'"
            await AgiEnv.run(cmd, wenv_abs)

            # build agi_node*.whl
            menv = env.agi_node
            cmd = f"{uv} --project '{menv}' build --wheel"
            await AgiEnv.run(cmd, menv)
            src = menv / "dist"
            try:
                whl = next(iter(src.glob("agi_node*.whl")))
                shutil.copy2(whl, wenv_abs)
            except StopIteration:
                raise RuntimeError(cmd)

            cmd = f"{uv_worker} pip install --project '{wenv_abs}' -e '{env.agi_node}'"
            await AgiEnv.run(cmd, wenv_abs)

        # Install the app sources into the worker venv using the absolute app path
        cmd = f"{uv_worker} pip install --project '{wenv_abs}' -e '{env.active_app}'"
        await AgiEnv.run(cmd, wenv_abs)

        # dataset
        dest = wenv_abs / "src" / env.target_worker
        os.makedirs(dest, exist_ok=True)
        src = env.dataset_archive
        if src.exists():
            os.makedirs(env.home_abs / env.data_rel / "dataset", exist_ok=True)
            shutil.copy2(src, dest)

        # # Post-install script
        # dest = env.home_abs / env.post_install_rel
        # os.makedirs(dest.parent, exist_ok=True)
        # shutil.copy2(env.post_install, dest)
        #
        # python_bin = wenv_abs / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        # cmd = (
        #     f"{shlex.quote(str(python_bin))} {shlex.quote(str(dest))} "
        #     f"{shlex.quote(str(env.app))} "
        #     f"{shlex.quote(str(env.data_rel))}"
        # )
        # await AgiEnv.run(cmd, wenv_abs)

        # Build target_worker lib local
        await AGI._build_lib_local()

        # Cleanup modules
        await AGI._uninstall_modules()
        AGI._install_done_local = True

        cli = wenv_abs.parent / "cli.py"
        cmd = f"{uv_worker} run --no-sync --project '{wenv_abs}' python '{cli}' threaded"
        await AgiEnv.run(cmd, wenv_abs)

    @staticmethod
    async def _deploy_remote_worker(ip: str, env: AgiEnv, wenv_rel: Path, option: str) -> None:
        """Install packages and set up the environment on a remote node."""

        wenv_abs = env.wenv_abs
        wenv_rel = env.wenv_rel
        dist_rel = env.dist_rel
        dist_abs = env.dist_abs
        pyvers = env.pyvers_worker
        cmd_prefix = env.envars.get(f"{ip}_CMD_PREFIX", "")
        uv = cmd_prefix + env.uv_worker

        cmd = f"{uv} run -p {pyvers} python -c \"import os; os.makedirs('{dist_rel}', exist_ok=True)\""
        await AGI.exec_ssh(ip, cmd)

        # Then send the files to the remote directory
        try:
            egg_file = next(iter(dist_abs.glob(f"{env.app}*.egg")), None)
        except StopIteration:
            logger.error(f"searching for {wenv_abs / env.app}*.egg")
            raise FileNotFoundError(f"no existing egg file in {wenv_abs / env.app}*")

        # build agi_env*.whl
        wenv = env.agi_env / 'dist'
        try:
            env_whl = next(iter(wenv.glob("agi_env*.whl")))
        except StopIteration:
            raise FileNotFoundError(f"no existing whl file in {wenv / "agi_env*"}")

        # build agi_node*.whl
        wenv = env.agi_node / 'dist'
        try:
            node_whl = next(iter(wenv.glob("agi_node*.whl")))
        except StopIteration:
            raise FileNotFoundError(f"no existing whl file in {wenv / "agi_node*"}")

        await AGI.send_files(env, ip,
                             [egg_file, node_whl, env_whl, env.worker_pyproject, env.uvproject],
                             wenv_rel)

        # 5) Check remote Rapids hardware support via nvidia-smi
        hw_rapids_capable = False
        if AGI._rapids_enabled:
            check_rapids = 'nvidia-smi'

            try:
                result = await AGI.exec_ssh(ip, check_rapids)
            except Exception as e:
                logger.error(f"rapids is requested but not supported by node [{ip}]")
                raise

            hw_rapids_capable = (result != "") and AGI._rapids_enabled
            env.hw_rapids_capable = hw_rapids_capable
            if hw_rapids_capable:
                AgiEnv.set_env_var(ip, "hw_rapids_capable")
            logger.info(f"Rapids-capable GPU[{ip}]: {hw_rapids_capable}")

        # unzip egg to get src/
        cli = env.wenv_rel.parent / "cli.py"
        cmd = f"{uv} run -p {pyvers} python  {cli} unzip {wenv_rel}"
        await AGI.exec_ssh(ip, cmd)

        #############
        # install env
        #############

        cmd = f"{uv} --project {wenv_rel} run -p {pyvers} python -m ensurepip"
        await AGI.exec_ssh(ip, cmd)

        cmd = f"{uv} --project {wenv_rel} run -p {pyvers} python -m pip install -e {wenv_rel}"
        await AGI.exec_ssh(ip, cmd)

        # install env
        cmd = f"{uv} --project {wenv_rel} add -p {pyvers} --upgrade {wenv_rel / env_whl.name}"
        await AGI.exec_ssh(ip, cmd)

        # install node
        cmd = f"{uv} --project {wenv_rel} add -p {pyvers} --upgrade {wenv_rel / node_whl.name}"
        await AGI.exec_ssh(ip, cmd)

        # unzip egg to get src/
        cli = env.wenv_rel.parent / "cli.py"
        cmd = f"{uv} run --no-sync -p {pyvers} python {cli} unzip {wenv_rel}"
        await AGI.exec_ssh(ip, cmd)

        # Post-install script
        cmd = f"{uv} --project {wenv_rel} run --no-sync -p {pyvers} python -m {env.post_install_rel} {wenv_rel.stem} {env.data_rel}"
        await AGI.exec_ssh(ip, cmd)

        # build target_worker lib from src/
        if env.verbose > 1:
            cmd = (
                f"{uv} --project '{wenv_rel}' run --no-sync -p {pyvers} python -m "
                f"agi_node.agi_dispatcher.build  --app-path  '{wenv_rel}' build_ext -b '{wenv_rel}'"
            )
        else:
            cmd = (
                f"{uv} --project '{wenv_rel}' run --no-sync -p {pyvers} python -m "
                f"agi_node.agi_dispatcher.build --app-path '{wenv_rel}' -q build_ext -b '{wenv_rel}'"
            )
        await AGI.exec_ssh(ip, cmd)

    @staticmethod
    def _should_install_pip() -> bool:
        return str(getpass.getuser()).startswith("T0") and not (Path(sys.prefix) / "Scripts/pip.exe").exists()

    @staticmethod
    async def _uninstall_modules() -> None:
        """Uninstall specified modules."""
        for module in AGI._module_to_clean:
            cmd = f"{env.uv} pip uninstall {module} -y"
            logger.info(f"Executing: {cmd}")
            await AgiEnv.run(cmd, AGI.env.agi_env)
        AGI._module_to_clean.clear()

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        """Format the duration from seconds to a human-readable format.

        Args:
            seconds (float): The duration in seconds.

        Returns:
            str: The formatted duration.
        """
        return humanize.precisedelta(timedelta(seconds=seconds))

    @staticmethod
    def _venv_todo(list_ip: Set[str]) -> None:
        """

        Args:
          list_ip: return:

        Returns:

        """
        t = time.time()

        AGI._local_ip, AGI._remote_ip = [], []

        for ip in list_ip:
            (AGI._local_ip.append(ip) if AgiEnv.is_local(ip) else AGI._remote_ip.append(ip))
        AGI._install_todo = 2 * len(AGI._remote_ip)
        if AGI.env.verbose > 0:
            logger.info(f"remote worker to install: {AGI._install_todo} ")

    @staticmethod
    async def install(
            env: AgiEnv,
            scheduler: Optional[str] = None,
            workers: Optional[Dict[str, int]] = None,
            modes_enabled: int = _RUN_MASK,
            verbose: Optional[int] = None,
            **args: Any,
    ) -> None:
        """
        Update the cluster's virtual environment.

        Args:
            project_path (Path):
                The name of the module to install or the path to the module.
            list_ip (List[str], optional):
                A list of IPv4 addresses with SSH access. Each IP should have Python,
                `psutil`, and `pdm` installed. Defaults to None.
            modes_enabled (int, optional):
                Bitmask indicating enabled modes. Defaults to `0b0111`.
            verbose (int, optional):
                Verbosity level (0-3). Higher numbers increase the verbosity of the output.
                Defaults to 1.
            **args:
                Additional keyword arguments.

        Returns:
            bool:
                `True` if the installation was successful, `False` otherwise.

        Raises:
            ValueError:
                If `module_name_or_path` is invalid.
            ConnectionError:
        """
        AGI._run_type = "sync"
        mode = (AGI._INSTALL_MODE | modes_enabled)
        await AGI.run(
            env=env,
            scheduler=scheduler,
            workers=workers,
            mode=mode,
            rapids_enabled=AGI._INSTALL_MODE & modes_enabled,
            verbose=verbose, **args
        )

    @staticmethod
    async def update(
            env: Optional[AgiEnv] = None,
            scheduler: Optional[str] = None,
            workers: Optional[Dict[str, int]] = None,
            modes_enabled: int = _RUN_MASK,
            verbose: Optional[int] = None,
            **args: Any,
    ) -> None:
        """
        install cluster virtual environment
        Parameters
        ----------
        package: any Agi target apps or project created with AGILAB
        list_ip: any ip V4 with ssh access and python (upto you to link it to python3) with psutil and uv synced
        mode_enabled: this is typically a mode mask to know for example if cython or rapids are required
        force_update: make a Spud.update before the installation, default is True
        verbose: verbosity [0-3]

        Returns
        -------

        """
        AGI._run_type = "upgrade"
        await AGI.run(env=env, scheduler=scheduler, workers=workers,
                      mode=(AGI._UPDATE_MODE | modes_enabled) & AGI._DASK_RESET,
                      rapids_enabled=AGI._UPDATE_MODE & modes_enabled, **args)

    @staticmethod
    async def get_distrib(
            env: AgiEnv,
            scheduler: Optional[str] = None,
            workers: Optional[Dict[str, int]] = None,
            verbose: int = 0,
            **args: Any,
    ) -> Any:
        """
        check the distribution with a dry run
        Parameters
        ----------
        package: any Agi target apps or project created by AGILAB
        list_ip: any ip V4 with ssh access and python (upto you to link it to python3) with psutil and uv synced
        verbose: verbosity [0-3]

        Returns
        the distribution tree
        -------
        """
        AGI._run_type = "simulate"
        return await AGI.run(env, scheduler, workers, mode=AGI._SIMULATE_MODE, **args)

    # Backward compatibility alias
    @staticmethod
    async def distribute(
            env: AgiEnv,
            scheduler: Optional[str] = None,
            workers: Optional[Dict[str, int]] = None,
            verbose: int = 0,
            **args: Any,
    ) -> Any:
        return await AGI.get_distrib(env, scheduler, workers, verbose=verbose, **args)

    @staticmethod
    async def _start_scheduler(scheduler: Optional[str]) -> bool:
        """
        Start Dask scheduler either locally or remotely.

        Returns:
            bool: True on success.

        Raises:
            FileNotFoundError: if worker initialization error occurs.
            SystemExit: on fatal error starting scheduler or Dask client.
        """
        env = AGI.env
        cli_rel = env.wenv_rel.parent / "cli.py"

        if (AGI._mode_auto and AGI._mode == AGI.DASK_MODE) or not AGI._mode_auto:
            env.hw_rapids_capable = True
            if AGI._mode & AGI.DASK_MODE:
                if scheduler is None:
                    if list(AGI._workers) == ["127.0.0.1"]:
                        scheduler = "127.0.0.1"
                    else:
                        logger.info("AGI.run(...scheduler='scheduler ip address' is required -> Stop")

                AGI._scheduler_ip, AGI._scheduler_port = AGI._get_scheduler(scheduler)

            # Clean worker
            for ip in list(AGI._workers):
                await AGI.send_file(env, ip, env.cluster_pck / "agi_distributor/cli.py",
                                    cli_rel.parent)
                hw_rapids_capable = env.envars.get(ip, None)
                if not hw_rapids_capable or hw_rapids_capable == "no_rapids_hw":
                    env.hw_rapids_capable = False
                try:
                    await AGI._kill(ip, os.getpid(), force=True)
                except Exception as e:
                    raise

            # clean scheduler
            try:
                await AGI._kill(AGI._scheduler_ip, os.getpid(), force=True)
            except Exception as e:
                raise

            toml_local = env.active_app / "pyproject.toml"
            wenv_rel = env.wenv_rel
            wenv_abs = env.wenv_abs
            if env.is_local(AGI._scheduler_ip):
                await asyncio.sleep(1)  # non-blocking sleep
                cmd = (
                    f"{env.uv} run --no-sync --project {env.wenv_abs} dask scheduler --port {AGI._scheduler_port} "
                    f"--host {AGI._scheduler_ip} --pid-file {wenv_abs.parent / 'dask_scheduler.pid'} "
                )
                logger.info(f"Starting dask scheduler locally: {cmd}")
                result = AGI._exec_bg(cmd, env.app)
                if result:  # assuming _exec_bg is sync
                    logger.info(result)
            else:
                # Create remote directory
                cmd = f"{env.uv} run --no-sync python -c \"import os; os.makedirs('{wenv_rel}', exist_ok=True)\""
                await AGI.exec_ssh(AGI._scheduler_ip, cmd)

                toml_wenv = wenv_rel / "pyproject.toml"
                await AGI.send_file(AGI._scheduler_ip, toml_local, toml_wenv)

                cmd = (
                    f"{env.uv} --project {wenv_rel} run --no-sync dask scheduler --port {AGI._scheduler_port} "
                    f"--host {AGI._scheduler_ip} --pid-file dask_scheduler.pid"
                )
                # Run scheduler asynchronously over SSH without awaiting completion (fire and forget)
                asyncio.create_task(AGI.exec_ssh_async(AGI._scheduler_ip, cmd))

            try:
                await asyncio.sleep(1)  # Give scheduler a moment to start
                client = await Client(AGI._scheduler,
                                      heartbeat_interval=5000,
                                      timeout=AGI._TIMEOUT)
                AGI._dask_client = client
            except Exception as e:
                logger.error("Dask Client instantiation trouble, run aborted due to:")
                logger.info(e)
                raise RuntimeError("Failed to instantiate Dask Client") from e

            AGI._install_done = True
            if AGI._worker_init_error:
                raise FileNotFoundError(f"Please run AGI.install([{AGI._scheduler_ip}])")

        return True

    @staticmethod
    async def _detect_export_cmd(ip: str) -> Optional[str]:
        if AgiEnv.is_local(ip):
            return AgiEnv.export_local_bin

        # probe remote OS via SSH
        try:
            os_id = await AGI.exec_ssh(ip, "uname -s")
        except Exception:
            os_id = ''

        if any(x in os_id for x in ('Linux', 'Darwin', 'BSD')):
            return 'export PATH="~/.local/bin:$PATH";'
        else:
            return ""  # 'set PATH=%USERPROFILE%\\.local\\bin;%PATH% &&'

    @staticmethod
    async def _start(scheduler: Optional[str]) -> bool:
        """_start(
        Start Dask workers locally and remotely,
        launching remote workers detached in background,
        compatible with Windows and POSIX.
        """
        env = AGI.env

        # Start scheduler first
        if not await AGI._start_scheduler(scheduler):
            return False

        for i, (ip, n) in enumerate(AGI._workers.items()):
            is_local = env.is_local(ip)
            cmd_prefix = env.envars.get(f"{ip}_CMD_PREFIX", "")

            for j in range(n):
                try:
                    logger.info(f"Starting worker #{i}.{j} on [{ip}]")
                    pid_file = f"dask_worker_{i}_{j}.pid"

                    if is_local:
                        wenv_abs = env.wenv_abs
                        cmd = (
                            # f'{export_cmd} '
                            f'{cmd_prefix}{env.uv} --project {wenv_abs} run --no-sync dask worker tcp://{AGI._scheduler} --no-nanny '
                            f'--pid-file {wenv_abs / pid_file}'
                        )
                        # Run locally in background (non-blocking)
                        AGI._exec_bg(cmd, str(wenv_abs))
                    else:
                        wenv_rel = env.wenv_rel
                        cmd = f'{cmd_prefix}{env.uv} --project {wenv_rel} run --no-sync dask worker tcp://{AGI._scheduler} --no-nanny --pid-file {wenv_rel.parent / pid_file}'
                        asyncio.create_task(AGI.exec_ssh_async(ip, cmd))
                        logger.info(f"Launched remote worker in background on {ip}: {cmd}")

                except Exception as e:
                    logger.error(f"Failed to start worker on {ip}: {e}")
                    raise

                if AGI._worker_init_error:
                    raise FileNotFoundError(f"Please run AGI.install([{ip}])")

        await AGI._sync(timeout=AGI._TIMEOUT)

        if not AGI._mode_auto or (AGI._mode_auto and AGI._mode == 0):
            await AGI._build_lib_remote()
            if AGI._mode & AGI.DASK_MODE:
                # load lib
                for egg_file in (AGI.env.wenv_abs / "dist").glob("*.egg"):
                    AGI._dask_client.upload_file(str(egg_file))

    @staticmethod
    async def _sync(timeout: int = 60) -> None:
        if not isinstance(AGI._dask_client, Client):
            return
        start = time.time()
        expected_workers = sum(AGI._workers.values())

        while True:
            try:
                info = AGI._dask_client.scheduler_info()
                workers_info = info.get("workers")
                if workers_info is None:
                    logger.info("Scheduler info 'workers' not ready yet.")
                    await asyncio.sleep(3)
                    if time.time() - start > timeout:
                        logger.error(f"Timeout waiting for scheduler workers info.")
                        raise TimeoutError("Timed out waiting for scheduler workers info")
                    continue

                runners = list(workers_info.keys())
                current_count = len(runners)
                remaining = expected_workers - current_count

                if runners:
                    logger.info(f"Current workers connected: {runners}")
                logger.info(f"Waiting for number of workers to attach: {remaining} remaining...")

                if current_count >= expected_workers:
                    break

                if remaining <= 0:
                    break

                if time.time() - start > timeout:
                    logger.error("Timeout waiting for all workers. {remaining} workers missing.")
                    raise TimeoutError("Timed out waiting for all workers to attach")
                await asyncio.sleep(3)

            except Exception as e:
                logger.info(f"Exception in _sync: {e}")
                await asyncio.sleep(1)
                if time.time() - start > timeout:
                    raise TimeoutError(f"Timeout waiting for all workers due to exception: {e}")

        logger.info("All workers successfully attached to scheduler")

    @staticmethod
    async def _build_lib_local():
        """

        Returns:

        """
        env = AGI.env
        wenv = normalize_path(str(env.wenv_abs))
        is_cy = AGI._mode & AGI.CYTHON_MODE
        packages = "agi_dispatcher, "

        baseworker = env.base_worker_cls
        if baseworker.startswith("Agent"):
            packages += "agent_worker"
        elif baseworker.startswith("Dag"):
            packages += "dag_worker"
        elif baseworker.startswith("Pandas"):
            packages += "pandas_worker"
        elif baseworker.startswith("Polars"):
            packages += "polars_worker"
        elif baseworker.startswith("Fireducks"):
            packages += "fireducks_worker"

        app_path = env.active_app
        wenv_abs = env.wenv_abs
        module = getattr(env, "setup_app_module", "agi_node.agi_dispatcher.build")

        # build egg and unzip it into wenv
        uv = env.uv
        cmd_prefix = env.envars.get(f"127.0.0.1_CMD_PREFIX", "")
        if env.is_free_threading_available:
            uv = cmd_prefix + " PYTHON_GIL=0 " + env.uv
        app_path_q = shlex.quote(str(app_path))
        wenv_abs_q = shlex.quote(str(wenv_abs))
        module_cmd = f"python -m {module}"
        app_arg = f"--app-path {app_path_q}"
        if env.verbose > 1:
            cmd = (
                f"{env.uv} --project {app_path_q} run --no-sync "
                f"{module_cmd} {app_arg} bdist_egg --packages \"{packages}\" -d {wenv_abs_q}"
            )
        else:
            cmd = (
                f"{env.uv} --project {app_path_q} run --no-sync "
                f"{module_cmd} {app_arg} -q bdist_egg --packages \"{packages}\" -d {wenv_abs_q}"
            )

        await AgiEnv.run(cmd, app_path)

        dask_client = AGI._dask_client
        if dask_client:
            egg_files = list((wenv_abs / "dist").glob("*.egg"))
            for egg_file in egg_files:
                dask_client.upload_file(str(egg_file))

        # compile in cython when cython is requested
        if is_cy:
            # cython compilation of wenv/src into wenv
            if env.verbose > 1:
                cmd = (
                    f"{env.uv} --project {wenv_abs_q} run --no-sync "
                    f"{module_cmd} --app-path {wenv_abs_q} build_ext -b {wenv_abs_q}"
                )
            else:
                cmd = (
                    f"{env.uv} --project {wenv_abs_q} run --no-sync "
                    f"{module_cmd} --app-path {wenv_abs_q} -q build_ext -b {wenv_abs_q}"
                )

            res = await AgiEnv.run(cmd, app_path)
            try:
                worker_lib = next(iter((wenv_abs / 'dist').glob("*_cy.*")), None)
            except StopIteration:
                raise RuntimeError(cmd)

            # platlib = sysconfig.get_path("platlib")
            # platlib_idx = platlib.index('.venv')
            # wenv_platlib = platlib[platlib_idx:]
            # target_platlib = wenv_abs / wenv_platlib
            # destination = os.path.join(target_platlib, os.path.basename(worker_lib))

            python_dirs = env.pyvers_worker.split(".")
            if python_dirs[-1][-1] == "t":
                python_version = python_dirs[0] + "." + python_dirs[1] + "t"
            else:
                python_version = python_dirs[0] + "." + python_dirs[1]
            destination_dir = wenv_abs / f".venv/lib/python{python_version}/site-packages"

            # Copy the file while preserving metadata into the site-packages directory.
            os.makedirs(destination_dir, exist_ok=True)
            shutil.copy2(worker_lib, destination_dir / os.path.basename(worker_lib))
            if res != "":
                logger.info(res)

        return

    @staticmethod
    async def _build_lib_remote() -> None:
        """
        workers init
        """
        # worker
        if (AGI._dask_client.scheduler.pool.open == 0) and AGI.verbose:
            runners = list(AGI._dask_client.scheduler_info()["workers"].keys())
            logger.info("warning: no scheduler found but requested mode is dask=1 => switch to dask")

    @staticmethod
    async def _run() -> Any:
        """

        Returns:

        """
        env = AGI.env
        env.hw_rapids_capable = env.envars.get("127.0.0.1", "hw_rapids_capable")

        # check first that install is done
        if not (env.wenv_abs / ".venv").exists():
            logger.info("Worker installation not found")
            raise FileNotFoundError("Worker installation (.venv) not found")

        pid_file = "dask_worker_0.pid"
        current_pid = os.getpid()
        with open(pid_file, "w") as f:
            f.write(str(current_pid))

        await AGI._kill(current_pid=current_pid, force=True)

        if AGI._mode & AGI.CYTHON_MODE:
            wenv_abs = env.wenv_abs
            cython_lib_path = Path(wenv_abs)

        logging.info(f"debug={env.debug}")

        if env.debug:
            BaseWorker._new(env=env, mode=AGI._mode, verbose=env.verbose, args=AGI._args)
            res = await BaseWorker._run(env=env, mode=AGI._mode, workers=AGI._workers, verbose=env.verbose,
                                       args=AGI._args)
        else:
            cmd = (
                f"{env.uv} run --preview-features python-upgrade --no-sync --project {env.wenv_abs} python -c \""
                f"from agi_node.agi_dispatcher import  BaseWorker\n"
                f"import asyncio\n"
                f"async def main():\n"
                f"  BaseWorker._new(app='{env.target_worker}', mode={AGI._mode}, verbose={env.verbose}, args={AGI._args})\n"
                f"  res = await BaseWorker._run(mode={AGI._mode}, workers={AGI._workers}, args={AGI._args})\n"
                f"  print(res)\n"
                f"if __name__ == '__main__':\n"
                f"  asyncio.run(main())\""
            )

            res = await AgiEnv.run_async(cmd, env.wenv_abs)

        if res:
            if isinstance(res, list):
                return res
            else:
                res_lines = res.split('\n')
                if len(res_lines) < 2:
                    return res
                else:
                    return res.split('\n')[-2]

    @staticmethod
    async def _distribute() -> str:
        """
        workers run calibration and targets job
        """
        env = AGI.env

        # AGI distribute work on cluster
        AGI._dask_workers = [
            worker.split("/")[-1]
            for worker in list(AGI._dask_client.scheduler_info()["workers"].keys())
        ]
        logger.info(f"AGI run mode={AGI._mode} on {list(AGI._dask_workers)} ... ")

        AGI._workers, workers_plan, workers_plan_metadata = await WorkDispatcher._do_distrib(
            env, AGI._workers, AGI._args
        )
        AGI._work_plan = workers_plan
        AGI._work_plan_metadata = workers_plan_metadata

        AGI._scale_cluster()

        if AGI._mode == AGI._INSTALL_MODE:
            workers_plan

        dask_workers = list(AGI._dask_workers)
        client = AGI._dask_client

        AGI._dask_client.gather(
            [
                client.submit(
                    BaseWorker._new,
                    env=0 if env.debug else None,
                    app=env.target_worker,
                    mode=AGI._mode,
                    verbose=AGI.verbose,
                    worker_id=dask_workers.index(worker),
                    worker=worker,
                    args=AGI._args,
                    workers=[worker],
                )
                for worker in dask_workers
            ]
        )

        await AGI._calibration()

        t = time.time()

        # --- Capture logs from each worker! ---
        worker_logs = client.run(
            BaseWorker._do_works,
            workers_plan,
            workers_plan_metadata,
            workers=dask_workers,
        )

        # LOG ONLY, no print:
        for worker, log in worker_logs.items():
            logger.info(f"\n=== Worker {worker} logs ===\n{log}")

        runtime = time.time() - t
        logger.info(f"{env.mode2str(AGI._mode)} {runtime}")
        return f"{env.mode2str(AGI._mode)} {runtime}"

    @staticmethod
    async def _main(scheduler: Optional[str]) -> Any:
        cond_clean = True

        AGI._jobs = bg.BackgroundJobManager()

        if (AGI._mode & AGI._DEPLOYEMENT_MASK) == AGI._SIMULATE_MODE:
            # case simulate mode #0b11xxxx
            res = await AGI._run()

        elif AGI._mode >= AGI._INSTALL_MODE:
            # case install modes
            t = time.time()

            if AGI._mode & AGI.DASK_MODE:
                await AGI._prepare_cluster_env(scheduler)
            AGI._clean_dirs_local()
            await AGI._prepare_local_env()

            await AGI._deploy_application(scheduler)

            res = time.time() - t

        elif (AGI._mode & AGI._DEPLOYEMENT_MASK) == AGI._SIMULATE_MODE:
            # case simulate mode #0b11xxxx
            res = await AGI._run()

        elif AGI._mode & AGI.DASK_MODE:

            await AGI._start(scheduler)

            res = await AGI._distribute()
            AGI._update_capacity()

            # stop the cluster
            await AGI._stop()
        else:
            # case local run
            res = await AGI._run()

        AGI._clean_job(cond_clean)

        return res

    @staticmethod
    def _clean_job(cond_clean: bool) -> None:
        """

        Args:
          cond_clean:

        Returns:

        """
        # clean background job
        if AGI._jobs and cond_clean:
            if AGI.verbose:
                AGI._jobs.flush()
            else:
                with open(os.devnull, "w") as f, redirect_stdout(f), redirect_stderr(f):
                    AGI._jobs.flush()

    @staticmethod
    def _scale_cluster() -> None:
        """Remove unnecessary workers"""
        if AGI._dask_workers:
            nb_kept_workers = {}
            workers_to_remove = []
            for dask_worker in AGI._dask_workers:
                ip = dask_worker.split(":")[0]
                if ip in AGI._workers:
                    if ip not in nb_kept_workers:
                        nb_kept_workers[ip] = 0
                    if nb_kept_workers[ip] >= AGI._workers[ip]:
                        workers_to_remove.append(dask_worker)
                    else:
                        nb_kept_workers[ip] += 1
                else:
                    workers_to_remove.append(dask_worker)

            if workers_to_remove:
                logger.info(f"unused workers: {len(workers_to_remove)}")
                for worker in workers_to_remove:
                    AGI._dask_workers.remove(worker)

    @staticmethod
    async def _stop() -> None:
        """Stop the Dask workers and scheduler"""
        env = AGI.env
        logger.info("stop Agi core")

        i = 0
        while len(AGI._dask_client.scheduler_info()["workers"]) and (i < AGI._TIMEOUT):
            i += 1
            AGI._dask_client.retire_workers()
            await asyncio.sleep(1)

        if (
                AGI._mode_auto and (AGI._mode == 7 or AGI._mode == 15)
        ) or not AGI._mode_auto:
            AGI._dask_client.shutdown()

        await AGI._close_all_connections()

    @staticmethod
    async def _calibration() -> None:
        """
        balancer calibration
        """
        res_workers_info = AGI._dask_client.gather(
            [
                AGI._dask_client.run(
                    # BaseWorker.get_logs_and_result,
                    BaseWorker._get_worker_info,
                    BaseWorker._worker_id,
                    workers=AGI._dask_workers,
                )
            ]
        )

        infos = {}

        for res in res_workers_info:
            for worker, info in res.items():
                if info:
                    logger.info(f"{worker}:{info}")
                infos[worker] = info

        AGI.workers_info = infos
        AGI._capacity = {}
        workers_info = {}

        for worker, info in AGI.workers_info.items():
            ipport = worker.split("/")[-1]
            infos = list(AGI.workers_info[worker].values())
            infos.insert(0, [AGI._workers[ipport.split(":")[0]]])
            data = np.array(infos).reshape(1, 6)
            AGI._capacity[ipport] = AGI._capacity_predictor.predict(data)[0]
            info["label"] = AGI._capacity[ipport]
            workers_info[ipport] = info

        AGI.workers_info = workers_info
        cap_min = min(AGI._capacity.values())
        workers_capacity = {}

        for ipport, pred_cap in AGI._capacity.items():
            workers_capacity[ipport] = round(pred_cap / cap_min, 1)

        AGI._capacity = dict(
            sorted(workers_capacity.items(), key=lambda item: item[1], reverse=True)
        )

    @staticmethod
    def _train_capacity(train_home: Path) -> None:
        """train the balancer model

        Args:
          train_home:

        Returns:

        """
        data_file = train_home / AGI._capacity_data_file
        if data_file.exists():
            balancer_csv = data_file
        else:
            raise FileNotFoundError(data_file)

        schema = {
            "nb_workers": pl.Int64,
            "ram_total": pl.Float64,
            "ram_available": pl.Float64,
            "cpu_count": pl.Float64,  # Assuming CPU count can be a float
            "cpu_frequency": pl.Float64,
            "network_speed": pl.Float64,
            "label": pl.Float64,
        }

        # Read the CSV file with correct parameters
        df = pl.read_csv(
            balancer_csv,
            has_header=True,  # Correctly identifies the header row
            skip_rows_after_header=2,  # Skips the next two rows after the header
            schema_overrides=schema,  # Applies the defined schema
            ignore_errors=False,  # Set to True if you want to skip malformed rows
        )
        # Get the list of column names
        columns = df.columns

        # Select all columns except the last one as features
        X = df.select(columns[:-1]).to_numpy()

        # Select the last column as the target variable
        y = df.select(columns[-1]).to_numpy().ravel()

        # Split the data into training and testing sets
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42
        )
        AGI._capacity_predictor = RandomForestRegressor().fit(X_train, y_train)

        logger.info(
            f"AGI.balancer_train_mode - Accuracy of the prediction of the workers capacity = "
            f"{AGI._capacity_predictor.score(X_test, y_test)}"
        )

        capacity_model = os.path.join(train_home, AGI._capacity_model_file)
        with open(capacity_model, "wb") as f:
            pickle.dump(AGI._capacity_predictor, f)

    @staticmethod
    def _update_capacity() -> None:
        """update the balancer model"""
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

        for wrt in AGI._run_time:
            if isinstance(wrt, str):
                return

            worker = list(wrt.keys())[0]

            for w, info in AGI.workers_info.items():
                if w == worker:
                    info["run_time"] = wrt[w]
                    workers_rt[w] = info

        current_state = deepcopy(workers_rt)

        for worker, data in workers_rt.items():
            worker_cap = data["label"]  # Capacité actuelle du mycode_wprker
            worker_rt = data["run_time"]  # Temps d'exécution du mycode_worker

            # Calculer le delta de temps et mettre à jour la capacité pour chaque autre mycode_worker
            for other_worker, other_data in current_state.items():
                if other_worker != worker:
                    other_rt = other_data[
                        "run_time"
                    ]  # Temps d'exécution de l'autre mycode_worker
                    delta = worker_rt - other_rt
                    workers_rt[worker]["label"] -= (
                            0.1 * worker_cap * delta / worker_rt / (len(current_state) - 1)
                    )
                else:
                    workers_rt[worker]["nb_workers"] = int(
                        AGI._workers[worker.split(":")[0]]
                    )

        for w, data in workers_rt.items():
            del data["run_time"]
            df = pl.DataFrame(data)
            df = df[balancer_cols]

            if df[0, -1] and df[0, -1] != float("inf"):
                with open(AGI._capacity_data_file, "a") as f:
                    df.write_csv(
                        f,
                        include_header=False,
                        line_terminator="\r",
                    )
            else:
                raise RuntimeError(f"{w} workers BaseWorker.do_works failed")

        AGI._train_capacity(AGI.env.home_abs)

    @staticmethod
    def _exec_bg(cmd: str, cwd: str) -> None:
        """
        Execute background command
        Args:
            cmd: the command to be run
            cwd: the current working directory

        Returns:
            """
        AGI._jobs.new("subprocess.Popen(cmd, shell=True)", cwd=cwd)

        if not AGI._jobs.result(0):
            raise RuntimeError(f"running {cmd} at {cwd}")

    @asynccontextmanager
    async def get_ssh_connection(ip: str, timeout_sec: int = 5):

        env = AGI.env
        if AgiEnv.is_local(ip):
            env.user = getpass.getuser()

        if not env.user:
            raise ValueError("SSH username is not configured. Please set 'user' in your .env file.")

        conn = AGI._ssh_connections.get(ip)
        if conn and not conn.is_closed():
            yield conn
            return

        try:
            ssh_dir = Path("~/.ssh").expanduser()
            keys = []

            for file in ssh_dir.iterdir():
                if not file.is_file():
                    continue

                name = file.name
                if name.startswith('authorized_keys'):
                    continue
                if name.startswith('known_hosts'):
                    continue
                if name.endswith('.pub'):
                    continue

                keys.append(str(file))

            client_keys = keys if keys else None

            conn = await asyncio.wait_for(
                asyncssh.connect(
                    ip,
                    username=env.user,
                    password=env.password,
                    known_hosts=None,
                    client_keys=client_keys,
                ),
                timeout=timeout_sec
            )

            AGI._ssh_connections[ip] = conn
            yield conn

        except asyncio.TimeoutError:
            err_msg = f"Connection to {ip} timed out after {timeout_sec} seconds."
            logger.error(err_msg)
            raise

        except asyncssh.PermissionDenied:
            err_msg = f"Authentication failed for SSH user '{env.user}' on host {ip}."
            logger.error(err_msg)
            raise

        except OSError as e:
            if e.errno == errno.EHOSTUNREACH:
                err_msg = (
                    f"Unable to connect to {ip} on SSH port 22. "
                    "Please check that the device is powered on, network cable connected, and SSH service running."
                )
                raise ConnectionError(err_msg)
            elif e.errno in (errno.EACCES, errno.ECONNREFUSED):
                logger.error(str(e))
            else:
                logger.error(str(e))
            raise

        except asyncssh.Error as e:
            logger.error(e.command if hasattr(e, 'command') else "No command attribute")
            logger.error(e)
            raise

        except Exception as e:
            logger.error(f"Unexpected error while connecting to {ip}: {e}")
            raise

    @staticmethod
    async def exec_ssh(ip: str, cmd: str) -> str:
        try:
            async with AGI.get_ssh_connection(ip) as conn:
                msg = f"[{ip}] {cmd}"
                if AgiEnv.verbose > 0 or AgiEnv.debug:
                    logger.info(msg)
                result = await conn.run(cmd, check=True)
                stdout = result.stdout
                stderr = result.stderr
                if isinstance(stdout, bytes):
                    stdout = stdout.decode('utf-8', errors='replace')
                if isinstance(stderr, bytes):
                    stderr = stderr.decode('utf-8', errors='replace')
                if stderr:
                    logger.info(f"[{ip}] {stderr.strip()}")
                if AgiEnv.verbose > 0 or AgiEnv.debug:
                    if stdout:
                        logger.info(f"[{ip}] {stdout.strip()}")
                return (stdout or '').strip() + "\n" + (stderr or '').strip()

        except ConnectionError:
            raise

        except ProcessError as e:
            stdout = getattr(e, 'stdout', '')
            stderr = getattr(e, 'stderr', '')
            if isinstance(stdout, bytes):
                stdout = stdout.decode('utf-8', errors='replace')
            if isinstance(stderr, bytes):
                stderr = stderr.decode('utf-8', errors='replace')
            logger.error(f"Remote command stderr: {stderr.strip()}")
            raise

        except (asyncssh.Error, OSError) as e:
            logger.error(e)
            raise

    @staticmethod
    async def exec_ssh_async(ip: str, cmd: str) -> str:
        """
        Execute a remote command via SSH and return the last line of its stdout output.
        """
        async with AGI.get_ssh_connection(ip) as conn:
            process = await conn.create_process(cmd)

            # Read entire stdout output as bytes
            stdout = await process.stdout.read()
            await process.wait()

            # Decode output safely
            # stdout_str = stdout.decode('utf-8', errors='replace')

            # Split output into lines and get the last non-empty line
            lines = [line.strip() for line in stdout.splitlines() if line.strip()]
            if lines:
                return lines[-1]
            else:
                return ""  # or None if no output

    @staticmethod
    async def _close_all_connections():
        """
        Ferme proprement toutes les connexions SSH ouvertes.
        À appeler à la fin de ton programme ou avant arrêt.
        """
        for conn in AGI._ssh_connections.values():
            conn.close()
            await conn.wait_closed()
        AGI._ssh_connections.clear()
