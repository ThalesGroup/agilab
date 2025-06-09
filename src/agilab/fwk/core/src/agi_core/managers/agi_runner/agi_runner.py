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

from IPython.lib import backgroundjobs as bg
import asyncio
import getpass
import glob
import importlib
import io
import os
import pickle
import random
import re
import shutil
import socket
import sys
import time
import traceback
import warnings
from copy import deepcopy
from datetime import timedelta
from ipaddress import ip_address as is_ip
from pathlib import Path, PurePosixPath, PureWindowsPath
from tempfile import gettempdir
from typing import Any, Dict, List, Optional, Union
import sysconfig
from asyncssh import ProcessError
from contextlib import redirect_stdout, redirect_stderr

# External Libraries
import humanize
import numpy as np
import polars as pl
import psutil
from dask.distributed import Client, print
import json
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
import subprocess
import logging

# Project Libraries:
from agi_env import AgiEnv, normalize_path
from agi_core.managers.agi_manager import AgiManager
from agi_core.workers.agi_worker import AgiWorker

# os.environ["DASK_DISTRIBUTED__LOGGING__DISTRIBUTED__LEVEL"] = "INFO"
logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")
workers_default = {socket.gethostbyname("localhost"): 1}


class AGI:
    """
    Agi Class.

    Agi (Speedy-Python-Dask) is a scalable fwk based on Cython, Dask, and a pool of processes that supports High-Performance Computing (HPC) with or without output data.
    It offers a command-line interface in Python and an optional LAB with Streamlit, featuring advanced capabilities like embedded ChatGPT and visualizations.

    Agi stands for Speedy-Python-Dask.

    **To run on a cluster:**
        1. Create a Agi account on each host with SSH access.
        2. Copy your project's `pyproject.toml` to each host.
        3. Run `uv -q sync` before using AGI.
        4. To run with output data, provide a shared directory accessible from all hosts. Use this directory in your Python target code as both input and output.

    **Remarks:**
        - Interactive Matplotlib graphics are not supported by Jupyter Lab. Use Jupyter Notebook instead.
        - While debugging in a Jupyter cell, it's better to comment out `#%%time` to allow line numbers to display correctly.
    """

    # Constants as class attributes
    TIMEOUT = 10
    PYTHON_MODE = 1
    CYTHON_MODE = 2
    DASK_MODE = 4
    RAPIDS_MODE = 16
    INSTALL_MASK = 0b11 << DASK_MODE
    INSTALL_MODE = 0b01 << DASK_MODE
    UPDATE_MODE = 0b10 << DASK_MODE
    SIMULATE_MODE = 0b11 << DASK_MODE
    DEPLOYEMENT_MASK = 0b110000
    RUN_MASK = 0b001111
    RAPIDS_SET = 0b111111
    RAPIDS_RESET = 0b110111
    DASK_RESET = 0b111011
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
    _verbose: Optional[int] = None
    _worker_init_error: bool = False
    workers: Optional[Dict[str, int]] = None
    _capacity: Optional[Dict[str, float]] = None
    _capacity_data_file: Optional[Path] = None
    _capacity_model_file: Optional[Path] = None
    _capacity_predictor: Optional[RandomForestRegressor] = None
    _worker_default: Dict[str, int] = workers_default
    _run_time: Dict[str, Any] = {}
    _run_type: Optional[str] = None
    _run_types: List[str] = []
    _sys_path_to_clean: List[str] = []
    _target_built: Optional[Any] = None
    _module_to_clean: List[str] = []
    best_mode: Dict[str, Any] = {}
    workers_tree: Optional[Any] = None
    workers_tree_info: Optional[Any] = None
    debug: Optional[bool] = None
    _ip_local_cache: set = set({"127.0.0.1", "::1"})  # Cache with default local IPs
    env: Optional[AgiEnv] = None

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
        pass

    @staticmethod
    async def run(
            target: str,
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
        env.active(target, env.install_type)

        if not workers:
            workers = workers_default
        elif not isinstance(workers, dict):
            raise ValueError("workers must be a dict. {'ip-address':nb-worker}")

        AGI.target_path = env.module_path
        AGI._target = env.target
        AGI._rapids_enabled = rapids_enabled
        logging.info(f"AGI instance created for target {target} with verbosity {env.verbose}")

        if mode is None or isinstance(mode, list):
            mode_range = range(8) if mode is None else sorted(mode)
            return await AGI._run_all_modes(
                target, env, scheduler, workers, verbose, mode_range, rapids_enabled, **args
            )
        else:
            if isinstance(mode, str):
                pattern = r"^[dcrp]+$"
                if not re.fullmatch(pattern, mode.lower()):
                    logging.info("parameter <mode> must only contain the letters 'd', 'c', 'r', 'p'")
                    sys.exit(1)
                AGI._mode = env.mode2int(mode)
            elif isinstance(mode, int):
                AGI._mode = int(mode)
            else:
                logging.info("parameter <mode> must be an int, a list of int or a string")
                sys.exit(1)

            AGI._run_types = ["run", "sync --upgrade", "sync", "simulate"]
            if AGI._mode:
                if AGI._mode & AGI.RUN_MASK not in range(0, AGI.RAPIDS_MODE):
                    raise ValueError(f"mode {AGI._mode} not implemented")
            else:
                # 16 first modes are "run" type, then there 16, 17 and 18
                AGI._run_type = AGI._run_types[(AGI._mode & AGI.DEPLOYEMENT_MASK) >> AGI.DASK_MODE]
            AGI._args = args
            AGI._verbose = verbose
            AGI.workers = workers
            AGI._run_time = {}

            AGI._capacity_data_file = env.resource_path / "balancer_df.csv"
            AGI._capacity_model_file = env.resource_path / "balancer_model.pkl"
            path = Path(AGI._capacity_model_file)

            if path.is_file():
                with open(path, "rb") as f:
                    AGI._capacity_predictor = pickle.load(f)
            else:
                AGI._train_model(env.home_abs)

            # import of derived Class of AgiManager, name target_inst which is typically instance of Flight or MyCode
            AGI.agi_workers = {
                "PolarsWorker": "polars-worker",
                "PandasWorker": "pandas-worker",
                "DagWorker": "dag-worker",
                "AgentWorker": "agent-worker",
            }
            # AGI.install_worker_group = AGI.agi_workers[env.base_worker_cls]
            AGI.install_worker_group = ["agi-worker ", AGI.agi_workers[env.base_worker_cls]]
            base_worker_dir = str(env.workers_root / "src")
            if base_worker_dir not in sys.path:
                sys.path.insert(0, base_worker_dir)
            AGI._target_module = await AGI._load_module(
                AGI._target,
                env.module,
                path=env.app_src,
            )
            if not AGI._target_module:
                raise RuntimeError(f"failed to load {AGI._target}")

            target_class = getattr(AGI._target_module, env.target_class)
            AGI._target_inst = target_class(env, **args)

            try:
                return await AGI.main(scheduler)

            except ProcessError as e:
                logging.error(f"failed to run \n{e}")
                return

            except ConnectionError as e:
                logging.error(f"failed to connect \n{e}")
                return

            except Exception as err:
                logging.error(err)
                logging.error(traceback.format_exc())

    @staticmethod
    async def _run_all_modes(
            target,
            env,
            scheduler=None,
            workers=None,
            verbose=0,
            mode_range=None,
            rapids_enabled=None,
            **args,
    ):
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
        AGI._mode_auto = True
        rapids_mode_mask = AGI.RAPIDS_SET if rapids_enabled else AGI.RAPIDS_RESET
        runs = {}
        if env.benchmark.exists():
            os.remove(env.benchmark)
        for m in mode_range:
            # Determine which run mode to use.
            run_mode = m & rapids_mode_mask if rapids_enabled else m

            # Run the target with the current mode.
            run = await AGI.run(
                target,
                env,
                scheduler=scheduler,
                workers=workers,
                verbose=verbose,
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

        AGI.best_mode[target] = best_run_data
        AGI._mode_auto = False

        # Convert numeric keys to strings for valid JSON output.
        runs_str_keys = {str(k): v for k, v in runs.items()}

        # Return a JSON-formatted string
        with open(env.benchmark, "w") as f:
            json.dump(runs_str_keys, f)

        return json.dumps(runs_str_keys)

    @staticmethod
    def _is_local(ip):
        """

        Args:
          ip:

        Returns:

        """
        if (
                not ip or ip in AGI._ip_local_cache
        ):  # Check if IP is None, empty, or cached
            return True

        for _, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET and ip == addr.address:
                    AGI._ip_local_cache.add(ip)  # Cache the local IP found
                    return True

        return False

    @staticmethod
    def get_default_local_ip():
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
    def find_free_port(start=5000, end=10000, attempts=100):
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
    def _get_scheduler(ip_sched):
        """get scheduler ip V4 address
        when no scheduler provided, scheduler address is localhost or the first address if workers are not local.
        port is random

        Args:
          ip_sched:

        Returns:

        """
        port = AGI.find_free_port()
        if not ip_sched:
            if AGI.workers:
                ip = list(AGI.workers)[0]
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
    async def _load_module(module, package=None, path=None):
        """load a module

        Args:
          module: the name of the Agi apps module
          package: the package name where is the module (Default value = None)
          path: the path where is the package (Default value = None)

        Returns:
          : the instance of the module

        """
        path = normalize_path(path)
        if path not in sys.path:
            sys.path.insert(0, path)
            AGI._sys_path_to_clean.append(path)
        logging.info(f"import {module} from {package} located in {path}")
        try:
            if package:
                # Import module from a package
                return importlib.import_module(f"{package}.{module}")
            else:
                # Import module directly
                return importlib.import_module(module)

        except ModuleNotFoundError as e:
            module_to_install = (str(e).replace("No module named ", "").lower().replace("'", ""))
            app_path = AGI.env.app_abs
            cmd = f"uv -q --upgrade add {module_to_install}"
            logging.info(f"{cmd} from {app_path}")
            await AgiEnv.run(cmd, app_path)
            AGI._module_to_clean.append(module_to_install)
            return await AGI._load_module(module, package, path)

    @staticmethod
    def _get_stdout(func, *args, **kwargs):
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
    def _read_stderr(output_stream):
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
                logging.info(line)
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
                    logging.info(line)
                    AGI._worker_init_error = line.endswith('[ProjectError]')
            elif chan.exit_status_ready():
                break
            else:
                time.sleep(0.1)

    @staticmethod
    async def _kill(ip: str | None = None, current_pid: int | None = None, force: bool = True):
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
        localhost = socket.gethostbyname("localhost")
        ip = ip or localhost
        current_pid = current_pid or os.getpid()
        # 1) Collect PIDs from any pid files and remove those files
        pids_to_kill: list[int] = []
        for pid_file in Path().home().glob("dask-pid*"):
            try:
                text = pid_file.read_text().strip()
                pid = int(text)
                if pid != current_pid:
                    pids_to_kill.append(pid)
            except Exception:
                AGI.env.log_warning(f"Could not read PID from {pid_file}, skipping")
            try:
                pid_file.unlink()
            except Exception as e:
                AGI.env.log_warning(f"Failed to remove pid file {pid_file}: {e}")

        cmds: list[str] = []

        # 2) If force, kill by process name
        if force:
            cmd = (
                f'python3 -c "import getpass, psutil, os;'
                'me = getpass.getuser();\n'
                'my_pid = os.getpid();\n'
                'for p in psutil.process_iter([\'name\', \'username\', \'cmdline\', \'pid\']):\n'
                '    try:\n'
                '        if p.info.get(\'pid\') == my_pid:\n'
                '            continue\n'
                '        if p.info.get(\'username\') and me in p.info[\'username\'] and ('
                '            (p.info.get(\'name\') and \'dask\' in p.info[\'name\']) or '
                '            (p.info.get(\'cmdline\') and any(\'dask\' in s.lower() for s in p.info[\'cmdline\']))):\n'
                '            p.kill()\n'
                '    except (psutil.NoSuchProcess, psutil.AccessDenied):\n'
                '        pass"'
            )
            cmds.append(cmd)

        # 3) If we found any explicit pid files, terminate those PIDs
        if pids_to_kill:
            cmds.append(
                'python3 -c "import os, psutil; '
                f"pids={pids_to_kill}; "
                "[psutil.Process(p).kill() for p in pids if p!=os.getpid()]"
                '"'
            )

        last_res = None
        for cmd in cmds:
            # choose working directory based on local vs remote
            cwd = env.manager_root if ip == localhost else str(env.wenv_abs)
            if AGI._is_local(ip):
                AgiEnv.run(cmd, cwd)
            else:
                last_res = await env.exec_ssh(ip, cmd)

            # handle tuple or dict result
            if isinstance(last_res, dict):
                out = last_res.get("stdout", "")
                err = last_res.get("stderr", "")
                logging.info(out)
                if err:
                    logging.error(err)

        return last_res

    @staticmethod
    def _clean_dirs_local():
        """Clean up local worker env directory

        Args:
          wenv: worker environment dictionary

        Returns:

        """
        for d in [
            f"{gettempdir()}/dask-scratch-space",
            f"{AGI.env.wenv_abs}/*y",
        ]:
            for x in glob.glob(d):
                try:
                    shutil.rmtree(x, ignore_errors=True)
                except:
                    pass

    @staticmethod
    async def _clean_dirs(ip):
        """Clean up remote worker

        Args:
          ip: address of remote worker

        Returns:

        """
        env = AGI.env
        wenv_rel = env.wenv_rel
        wenv_abs = env.wenv_abs
        if wenv_abs.exists():
            env.remove_dir_forcefully(str(wenv_abs))
        os.makedirs(wenv_abs / "src", exist_ok=True)

        await env.exec_ssh(
            ip,
            cmd=(
                f"python3 -c \"import os, glob, shutil\n"
                f"from tempfile import gettempdir\n"
                f"wenv_path = os.path.abspath(os.path.expanduser('{wenv_rel}'))\n"
                f"patterns = [os.path.join(gettempdir(), 'dask-scratch-space'), os.path.join(wenv_path, '*y')]\n"
                f"[shutil.rmtree(path, ignore_errors=True) for pat in patterns for path in glob.glob(pat)]\n"
                f"os.makedirs(os.path.join(wenv_path, 'src'))\n\""
            )
        )

    @staticmethod
    async def _get_clean_nodes(scheduler, force=True):
        list_ip = set(list(AGI.workers) + [AGI._get_scheduler(scheduler)[0]])
        localhost_ip = socket.gethostbyname("localhost")
        if not list_ip:
            list_ip.add(localhost_ip)

        for ip in list_ip:  # remove the dask tempdir, the build dirs and the wenv dirs
            if AGI._is_local(ip):
                me = getpass.getuser()
                self_pid = os.getpid()

                for p in psutil.process_iter(['pid', 'username', 'cmdline']):
                    try:
                        if (
                                p.info['username'].endswith(me)
                                and p.info['pid'] != self_pid
                                and p.info['cmdline']
                                and any('dask' in s.lower() for s in p.info['cmdline'])
                        ):
                            p.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                AGI._clean_dirs_local()
            else:
                try:
                    await AGI._kill(ip, os.getpid(), force=force)
                except:
                    pass
                AGI._clean_dirs(ip)

        return list_ip

    @staticmethod
    async def _install_cluster(scheduler):
        """
        Validate and prepare each remote node in the cluster:
        - Verify each IP is valid and reachable.
        - Detect and install Python interpreters if missing.
        - Detect and install 'uv' CLI via pip if missing.
        - Use 'uv' to install the specified Python version, create necessary directories, and install packages.
        """
        list_ip = set(list(AGI.workers) + [AGI._get_scheduler(scheduler)[0]])
        localhost_ip = socket.gethostbyname("localhost")
        env = AGI.env
        pyvers = env.python_version

        # You can remove this check or keep it if you expect no scheduler/workers (rare)
        if not list_ip:
            list_ip.add(localhost_ip)

        # Validate IPs
        for ip in list_ip:
            if not AGI._is_local(ip) and not is_ip(ip):
                raise ValueError(f"Invalid IP address: {ip}")

        # Prepare each remote node (skip local)
        for ip in list_ip:
            if AGI._is_local(ip):
                continue

            # install psutil
            await env.exec_ssh(ip, "pip3 install psutil")

            wenv_rel = env.wenv_rel
            pyvers = env.python_version

            # 1) Check if need to export path (linux and macos)
            cmd_prefix = await AGI._detect_export_cmd(ip)

            env.set_env_var(f"{ip}_CMD_PREFIX", cmd_prefix)

            # 2) Check uv
            try:
                await env.exec_ssh(ip, f"{cmd_prefix} uv -q --version")
            except Exception:
                # Try Windows installer
                try:
                    await env.exec_ssh(ip,
                                       'powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
                                       )
                except Exception:
                    # Fallback to Unix installer
                    await env.exec_ssh(ip, 'curl -LsSf https://astral.sh/uv/install.sh | sh')
                    await env.exec_ssh(ip, 'source $HOME/.local/bin/env')

            # 3) Install Python
            await env.exec_ssh(ip, f"{cmd_prefix} uv -q python install {pyvers}")
            await env.exec_ssh(ip, f"pip3 install psutil")

            # 4) Bootstrap the uv -q environment
            pyproject = wenv_rel / 'pyproject.toml'
            cmd = (
                f"{cmd_prefix} mkdir -p 'wenv/flight_worker'; "
                f"uv  --project {wenv_rel} run -p {pyvers} python -c \"import os, subprocess; "
                f"subprocess.run(['uv','init','--bare'], cwd=r'{wenv_rel}', check=True) "
                f"if not os.path.exists('{pyproject}') else None\""
            )
            await env.exec_ssh(ip, cmd)

    @staticmethod
    async def _install(scheduler):
        AGI._initialize_installation()
        env = AGI.env
        app_path = env.app_abs
        wenv_rel = env.wenv_rel
        wenv_abs = env.wenv_abs
        pyvers = env.python_version
        extras = "--dev -p " + pyvers
        extras += " --config-file uv.toml" if AGI._rapids_enabled else ""
        options = {"manager": extras, "worker": extras}
        if isinstance(env.base_worker_cls, str):
            options["worker"] += " --extra " + " --extra ".join(AGI.install_worker_group)
        if AGI._mode & 4:
            await AGI._install_cluster(scheduler)
        node_ips = await AGI._get_clean_nodes(scheduler)
        AGI._venv_todo(node_ips)
        start_time = time.time()
        logging.info(f"********   Starting {AGI._run_type} for {app_path} in .env on 127.0.0.1")

        await AGI._install_app_local(app_path, Path(wenv_rel), options)
        # logging.info(AGI.run(cmd, wenv_abs))
        if AGI._mode & 4:
            tasks = []
            for ip in node_ips:
                logging.info(f"********   Starting {AGI._run_type} for Agi_worker in .venv on {ip}")
                if not AGI._is_local(ip):
                    tasks.append(asyncio.create_task(
                        AGI._install_app_remote(ip, env, wenv_rel, options["worker"])
                    ))
            await asyncio.gather(*tasks)

        if AGI._verbose:
            duration = AGI._format_duration(time.time() - start_time)
            logging.info(f"********   Agi {AGI._run_type} completed in {duration}")

    @staticmethod
    def _initialize_installation():
        """Initialize installation flags and run type."""
        AGI._run_type = AGI._run_types[(AGI._mode & AGI.DEPLOYEMENT_MASK) >> 4]
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
    async def _install_app_local(src: Path, wenv_rel: Path, options: dict):
        """
        Installe l’environnement localement.

        Args:
            src: chemin vers la racine du projet local
            wenv_rel: chemin relatif vers l’environnement virtuel local
            options: dict contenant les options 'manager' et 'worker' pour la commande uv
        """
        env = AGI.env
        pyvers = env.python_version
        run_type = AGI._run_type
        ip = "127.0.0.1"
        has_rapids_hw = AGI._hardware_supports_rapids() and AGI._rapids_enabled
        env.has_rapids_hw = has_rapids_hw
        if has_rapids_hw:
            env.set_env_var(ip, "has_rapids_hw")
        else:
            env.set_env_var(ip, "no_rapids_hw")

        logging.info(f"Rapids-capable GPU[{ip}]: {has_rapids_hw}")

        # Commande pour manager selon si rapids supporté
        app_path = env.app_abs
        if has_rapids_hw:
            cmd_manager = f"uv -q {run_type} {options['manager']} --extra managers --project {app_path}"
        else:
            cmd_manager = f"uv -q --config-file uv.toml {run_type} {options['manager']} --extra managers --project {app_path}"

        logging.info(f"Installing manager: {cmd_manager}")
        await AgiEnv.run(cmd_manager, app_path)

        # Copier les fichiers pyproject.toml et setup_core dans wenv_abs
        wenv_abs = env.wenv_abs
        logging.info(f"Copying {src / 'pyproject.toml'} -> {wenv_abs}")
        shutil.copy2(src / "pyproject.toml", wenv_abs)
        logging.info(f"Copying {env.setup_core} -> {wenv_abs}")
        shutil.copy(env.setup_core, wenv_abs / env.setup_core.stem)

        # Commande pour workers selon si rapids supporté
        if has_rapids_hw:
            cmd_worker = f"uv -q --config-file uv.toml {run_type} --project {wenv_abs} {options['worker']} --extra workers"
        else:
            cmd_worker = f"uv -q {run_type} --project {wenv_abs} {options['worker']} --extra workers"

        logging.info(f"Installing workers: {cmd_worker}")
        await AgiEnv.run(cmd_worker, wenv_abs)

        # Build worker lib local
        wenv = await AGI._build_lib_local(is_local=True)

        # Lancer le script post_install
        cmd_post = f"uv -q --project {wenv} run -p {pyvers} python {env.app_abs / env.post_install} {env.data_dir}"
        logging.info(f"Running post-install script: {cmd_post}")
        await AgiEnv.run(cmd_post, wenv)

        # Cleanup modules
        await AGI._uninstall_modules()
        AGI._install_done_local = True

    @staticmethod
    async def _install_app_remote(ip: str, env, wenv_rel: Path, option: str):
        """Install packages and set up the environment on a remote node."""
        pyvers = env.python_version
        python = f"uv -q run -p {pyvers} python"
        wenv_abs = env.wenv_abs
        wenv_rel = env.wenv_rel
        dist_rel = env.dist_rel
        dist_abs = env.dist_abs

        cmd_prefix = env.envars.get(f"{ip}_CMD_PREFIX", "")

        cmd = f"{cmd_prefix} uv run python -c \"import os; os.makedirs('{dist_rel}', exist_ok=True)\""
        await env.exec_ssh(ip, cmd)

        # Then send the files to the remote directory
        try:
            egg_file = next(iter(dist_abs.glob(f"{env.app}*.egg")), None)
        except StopIteration:
            logging.error(f"searching for {wenv_abs / env.app}*.egg")
            raise FileNotFoundError("no existing egg file")

        await env.send_files(ip, [env.setup_core, env.worker_pyproject, env.uvproject], wenv_rel)
        await env.send_file(ip, egg_file, dist_rel)

        # continue with bootstrap and unzip...
        cmd = f"{cmd_prefix} uv run -q --project {wenv_rel} python -m ensurepip"
        await env.exec_ssh(ip, cmd)

        cmd = (
            f"{cmd_prefix} uv run python -c \"import os, pathlib, zipfile;"
            f"root = pathlib.Path('{wenv_rel}');"
            f"root_src = root / 'src';"
            f"[zipfile.ZipFile(str(e)).extractall(str(root_src))"
            f"for e in (root / 'dist').glob('*.egg')]\""
        )
        await env.exec_ssh(ip, cmd)

        # 5) Check remote Rapids hardware support via nvidia-smi
        check_rapids = 'nvidia-smi'
        result = await env.exec_ssh(ip, check_rapids)
        has_rapids_hw = (result != "") and AGI._rapids_enabled
        env.has_rapids_hw = has_rapids_hw
        if has_rapids_hw:
            env.set_env_var(ip, "has_rapids_hw")

        logging.info(f"Rapids-capable GPU[{ip}]: {has_rapids_hw}")

        # 6) Build and run uv -q sync, adding --config-file only when has_rapids_hw
        if has_rapids_hw:
            sync_cmd = f"{cmd_prefix} uv sync -q --upgrade --project {wenv_rel} --config-file {wenv_rel / 'uv.toml'} {option} --refresh-package dask"
        else:
            sync_cmd = f"{cmd_prefix} uv sync -q --upgrade --project {wenv_rel} {option} --refresh-package dask "

        await env.exec_ssh(ip, sync_cmd)

        # 7) Post-install script
        cmd = f"{cmd_prefix} uv run -q --project {wenv_rel} -p {pyvers} python {env.post_install_rel} {env.data_dir}"
        await env.exec_ssh(ip, cmd)

        #####################################################
        # install env & core for enabling dask worker spawn
        ##################################################

        # init venv
        cmd = (
            f"{cmd_prefix} {python} -c "
            "\"import os, subprocess; "
            f"ROOT = r'{wenv_rel}'; "
            "subprocess.run(['uv','init','--bare'], cwd=ROOT, check=True) "
            "if not os.path.exists(os.path.join(ROOT, 'pyproject.toml')) else None\""
        )
        await env.exec_ssh(ip, cmd)

        # Bootstrap ensurepip
        cmd = f"{cmd_prefix} uv -q --project {wenv_rel} run python -m ensurepip"
        await env.exec_ssh(ip, cmd)

        cmd = f"{cmd_prefix} uv -q --project {wenv_rel} pip install -e {wenv_rel}"
        await env.exec_ssh(ip, cmd)

        # build agi_env*.whl
        wenv = env.agi_fwk_env_path
        cmd = f"{cmd_prefix} uv -q --project {wenv} build --wheel"
        await AgiEnv.run(cmd, venv=wenv)
        src = wenv / "dist"
        try:
            whl = next(iter(src.glob("agi_env*.whl")))
            await env.send_file(ip, whl, dist_rel)
        except StopIteration:
            raise RuntimeError(cmd)

        cmd = f"{cmd_prefix} uv -q --upgrade --project {dist_rel} add {dist_rel / whl.name}"
        await env.exec_ssh(ip, cmd)

        # build agi_core*.whl
        wenv = env.core_root
        src = wenv / "dist"
        cmd = f"{cmd_prefix} uv -q --project {wenv} build --wheel"
        await AgiEnv.run(cmd, venv=wenv)
        try:
            whl = next(iter(src.glob("agi_core*.whl")))
            await env.send_file(ip, whl, dist_rel)
        except StopIteration:
            raise RuntimeError(cmd)

        cmd = f"{cmd_prefix} uv -q --upgrade --project {dist_rel} add {dist_rel / whl.name}"
        await env.exec_ssh(ip, cmd)

        # build target_worker lib
        cmd = f"{cmd_prefix} uv -q --project {wenv_rel} run python {wenv_rel / env.setup_app.name} build_ext -i 2 -b {wenv_rel}"
        await env.exec_ssh(ip, cmd)

    @staticmethod
    def _should_install_pip():
        return str(getpass.getuser()).startswith("T0") and not (Path(sys.prefix) / "Scripts/pip.exe").exists()

    @staticmethod
    async def _uninstall_modules():
        """Uninstall specified modules."""
        for module in AGI._module_to_clean:
            cmd = f"uv -q pip uninstall {module} -y"
            logging.info(f"Executing: {cmd}")
            await AgiEnv.run(cmd, AGI.env.core_root)
        AGI._module_to_clean.clear()

    @staticmethod
    def _format_duration(seconds):
        """Format the duration from seconds to a human-readable format.

        Args:
            seconds (float): The duration in seconds.

        Returns:
            str: The formatted duration.
        """
        return humanize.precisedelta(timedelta(seconds=seconds))

    @staticmethod
    def _venv_todo(list_ip):
        """uv -q config

        Args:
          list_ip: return:

        Returns:

        """
        t = time.time()

        AGI._local_ip, AGI._remote_ip = [], []

        for ip in list_ip:
            (AGI._local_ip.append(ip) if AGI._is_local(ip) else AGI._remote_ip.append(ip))
        AGI._install_todo = 2 * len(AGI._remote_ip)
        logging.info(f"********   {AGI._install_todo} remote .venv to {AGI._run_type}")

    @staticmethod
    async def install(
            module_name, env, scheduler: Optional[str] = None, workers: Optional[Dict[str, int]] = None,
            modes_enabled=RUN_MASK, verbose=None, **args
    ):
        """
        Update the cluster's virtual environment.

        Args:
            module_name_or_path (str):
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
        mode = (AGI.INSTALL_MODE | modes_enabled)
        await AGI.run(module_name,
                      scheduler=scheduler,
                      workers=workers,
                      env=env,
                      mode=mode,
                      rapids_enabled=AGI.INSTALL_MODE & modes_enabled,
                      verbose=verbose, **args)

    @staticmethod
    async def update(
            module_name, scheduler: Optional[str] = None, workers: Optional[Dict[str, int]] = None,
            env=None, modes_enabled=RUN_MASK, verbose=None, **args
    ):
        """
        install cluster virtual environment
        Parameters
        ----------
        package: any Agi target apps or project created with AGILAB
        list_ip: any ip V4 with ssh access and python (upto you to link it to python3) with psutil and uv -q synced
        mode_enabled: this is typically a mode mask to know for example if cython or rapids are required
        force_update: make a Spud.update before the installation, default is True
        verbose: verbosity [0-3]

        Returns
        -------

        """
        AGI._run_type = "upgrade"
        await AGI.run(module_name, scheduler=scheduler, workers=workers,
                      env=env, mode=(AGI.UPDATE_MODE | modes_enabled) & AGI.DASK_RESET,
                      rapids_enabled=AGI.UPDATE_MODE & modes_enabled,
                      verbose=verbose, **args)

    @staticmethod
    async def distribute(app, env, scheduler=None, workers=None, verbose=0, **args
                         ):
        """
        check the distribution with a dry run
        Parameters
        ----------
        package: any Agi target apps or project created by AGILAB
        list_ip: any ip V4 with ssh access and python (upto you to link it to python3) with psutil and uv -q synced
        verbose: verbosity [0-3]

        Returns
        the distribution tree
        -------
        """
        AGI._run_type = "simulate"
        return await AGI.run(app, env, scheduler, workers, verbose, mode=AGI.SIMULATE_MODE, **args)

    @staticmethod
    async def _start_scheduler(scheduler):
        """
        Start Dask scheduler either locally or remotely.

        Returns:
            bool: True on success.

        Raises:
            FileNotFoundError: if worker initialization error occurs.
            SystemExit: on fatal error starting scheduler or Dask client.
        """
        env = AGI.env
        env.has_rapids_hw = True
        if (AGI._mode_auto and AGI._mode == AGI.DASK_MODE) or not AGI._mode_auto:
            if AGI._mode & AGI.DASK_MODE:
                if scheduler is None:
                    if list(AGI.workers) == ["127.0.0.1"]:
                        scheduler = "127.0.0.1"
                    else:
                        logging.info("AGI.run(...scheduler='scheduler ip address' is required -> Stop")

                AGI._scheduler_ip, AGI._scheduler_port = AGI._get_scheduler(scheduler)

            # Clean cluster environment by killing old processes
            for ip in list(AGI.workers):
                if not env.envars.get(ip, None):
                    env.has_rapids_hw = False
                try:
                    await AGI._kill(ip, os.getpid(), force=True)
                except Exception as e:
                    raise

            try:
                await AGI._kill(AGI._scheduler_ip, os.getpid(), force=True)
            except Exception as e:
                raise

            toml_local = env.app_abs / "pyproject.toml"
            wenv_rel = env.wenv_rel

            if AGI._is_local(AGI._scheduler_ip):
                await asyncio.sleep(1)  # non-blocking sleep
                cmd = (
                    f"uv -q run --project {env.wenv_abs} dask scheduler --port {AGI._scheduler_port} "
                    f"--host {AGI._scheduler_ip} --pid-file dask_pid"
                )
                logging.info(f"Starting dask scheduler locally: {cmd}")
                result = AGI._exec_bg(cmd, env.app_abs)  # assuming _exec_bg is sync
                logging.info(result)
            else:
                # Create remote directory
                cmd = f"python3 -c \"import os; os.makedirs('{wenv_rel}', exist_ok=True)\""
                await env.exec_ssh(AGI._scheduler_ip, cmd)

                toml_wenv = wenv_rel / "pyproject.toml"
                await env.send_file(AGI._scheduler_ip, toml_local, toml_wenv)

                cmd = (
                    f"uv -q --project {wenv_rel} run dask scheduler --port {AGI._scheduler_port} "
                    f"--host {AGI._scheduler_ip} --pid-file {wenv_rel / dask_pid}"
                )
                # Run scheduler asynchronously over SSH without awaiting completion (fire and forget)
                asyncio.create_task(env.exec_ssh_async(AGI._scheduler_ip, cmd))

            try:
                await asyncio.sleep(1)  # Give scheduler a moment to start
                client = await Client(AGI._scheduler,
                                      heartbeat_interval=5000,
                                      timeout=AGI.TIMEOUT)
                client.forward_logging()
                AGI._dask_client = client
            except Exception as e:
                logging.error("Dask Client instantiation trouble, run aborted due to:")
                logging.info(e)
                sys.exit(1)

            AGI._install_done = True
            if AGI._worker_init_error:
                raise FileNotFoundError(f"Please run AGI.install([{AGI._scheduler_ip}])")

        return True

    @staticmethod
    async def _detect_export_cmd(ip: str) -> str | None:
        if AGI._is_local(ip):
            return AGI.env.export_local_bin

        # probe remote OS via SSH
        try:
            os_id = await AGI.env.exec_ssh(ip, "uname -s")
        except Exception:
            os_id = ''

        if any(x in os_id for x in ('Linux', 'Darwin', 'BSD')):
            return 'export PATH="$HOME/.local/bin:$PATH";'
        else:
            return None  # 'set PATH=%USERPROFILE%\\.local\\bin;%PATH% &&'

    @staticmethod
    async def _start(scheduler):
        """_start(
        Start Dask workers locally and remotely,
        launching remote workers detached in background,
        compatible with Windows and POSIX.
        """
        env = AGI.env
        # Start scheduler first
        if not await AGI._start_scheduler(scheduler):
            return False

        for i, (ip, n) in enumerate(AGI.workers.items()):
            is_local = AGI._is_local(ip)

            cmd_prefix = env.envars.get(f"{ip}_CMD_PREFIX", "")

            for j in range(n):
                try:
                    logging.info(f"Starting worker #{i}.{j} on [{ip}]")
                    pid_file = f"dask-pid-{i}.{j}"

                    if is_local:
                        wenv_abs = env.wenv_abs
                        cmd = (
                            # f'{export_cmd} '
                            f'{cmd_prefix} uv -q --project {wenv_abs} run dask worker tcp://{AGI._scheduler} --no-nanny '
                            f'--pid-file {pid_file}'
                        )
                        # Run locally in background (non-blocking)
                        AGI._exec_bg(cmd, str(wenv_abs))
                    else:
                        wenv_rel = env.wenv_rel
                        cmd = f'{cmd_prefix} uv -q --project {wenv_rel} run dask worker tcp://{AGI._scheduler} --no-nanny --pid-file {pid_file}'
                        asyncio.create_task(env.exec_ssh_async(ip, cmd))
                        logging.info(f"Launched remote worker in background on {ip}: {cmd}")

                except Exception as e:
                    logging.error(f"Failed to start worker on {ip}: {e}")
                    raise

                if AGI._worker_init_error:
                    raise FileNotFoundError(f"Please run AGI.install([{ip}])")

        await AGI._sync(timeout=AGI.TIMEOUT)

        if not AGI._mode_auto or (AGI._mode_auto and AGI._mode == 0):
            # in case of core src has changed
            AGI._build_lib_local(is_local=True)
            await AGI._build_lib_remote()
            if not (AGI._mode & AGI.CYTHON_MODE):
                # load lib
                for egg_file in (AGI.env.wenv_abs / "dist").glob("*.egg"):
                    AGI._dask_client.upload_file(str(egg_file))

    @staticmethod
    async def _sync(timeout=60):
        if not isinstance(AGI._dask_client, Client):
            return
        start = time.time()
        expected_workers = sum(AGI.workers.values())

        while True:
            try:
                info = AGI._dask_client.scheduler_info()
                workers_info = info.get("workers")
                if workers_info is None:
                    logging.info("Scheduler info 'workers' not ready yet.")
                    await asyncio.sleep(1)
                    if time.time() - start > timeout:
                        logging.error(f"Timeout waiting for scheduler workers info.")
                        sys.exit(1)
                    continue

                runners = list(workers_info.keys())
                current_count = len(runners)
                remaining = expected_workers - current_count

                if runners:
                    logging.info(f"Current workers connected: {runners}")
                logging.info(f"Waiting for number of workers to attach: {remaining} remaining...")

                if current_count >= expected_workers:
                    break

                if remaining <= 0:
                    break

                if time.time() - start > timeout:
                    logging.error("Timeout waiting for all workers. {remaining} workers missing.")
                    sys.exit(1)
                await asyncio.sleep(1)

            except Exception as e:
                logging.info(f"Exception in _sync: {e}")
                await asyncio.sleep(1)
                if time.time() - start > timeout:
                    raise TimeoutError(f"Timeout waiting for all workers due to exception: {e}")

        logging.info("All workers successfully attached to scheduler")

    @staticmethod
    async def _build_lib_local(is_local=True):
        """

        Args:
          is_local: (Default value = True)

        Returns:

        """
        env = AGI.env
        wenv = normalize_path(str(env.wenv_abs))
        is_cy = AGI._mode & AGI.CYTHON_MODE
        packages = "agi_worker, "

        baseworker = env.base_worker_cls
        if baseworker.startswith("Agent"):
            packages += "agent_worker"
        elif baseworker.startswith("Dag"):
            packages += "dag_worker"
        elif baseworker.startswith("Pandas"):
            packages += "pandas_worker"
        elif baseworker.startswith("Polars"):
            packages += "polars_worker"

        app_path = env.app_abs
        wenv_abs = env.wenv_abs
        shutil.copy(env.setup_core, app_path / env.setup_core.stem)

        cmd = f"uv -q --project {app_path} run python {env.setup_app} bdist_egg --packages \"{packages}\" --install_type {env.install_type} -d {wenv_abs}"
        await AgiEnv.run(cmd, app_path)

        dask_client = AGI._dask_client
        if dask_client:
            egg_files = list((wenv_abs / "dist").glob("*.egg"))
            for egg_file in egg_files:
                dask_client.upload_file(str(egg_file))
        # compile in cython when cython is requested
        if is_local:
            cmd = f"uv -q --project {wenv_abs} pip install -e ."
            await AgiEnv.run(cmd, wenv_abs)

            if is_cy:
                # cython compilation of wenv/src into wenw
                shutil.copy(env.setup_core, wenv_abs)
                cmd = f"uv -q --project {app_path} run python {env.setup_app} build_ext -b {wenv_abs}"
                res = await AgiEnv.run(cmd, app_path)
                try:
                    worker_lib = next(iter((wenv_abs / 'dist').glob("*_cy.*")), None)
                except StopIteration:
                    raise RuntimeError(cmd)

                platlib = sysconfig.get_path("platlib")
                platlib_idx = platlib.index('.venv')
                wenv_platlib = platlib[platlib_idx:]
                target_platlib = wenv_abs / wenv_platlib
                destination = os.path.join(target_platlib, os.path.basename(worker_lib))

                # Copy the file while preserving metadata.
                destination_dir = os.path.dirname(destination)
                os.makedirs(destination_dir, exist_ok=True)  # create directory if missing
                shutil.copy2(worker_lib, destination)
                logging.info(res)
        return wenv

    @staticmethod
    async def _build_lib_remote():
        """
        workers init
        """
        # worker
        if (AGI._dask_client.scheduler.pool.open == 0) and AGI._verbose:
            runners = list(AGI._dask_client.scheduler_info()["workers"].keys())
            logging.info("warning: no scheduler found but requested mode is dask=1 => switch to dask")

    @staticmethod
    async def _run_local():
        """

        Returns:

        """
        env = AGI.env
        env.has_rapids_hw = env.envars.get("127.0.0.1", "HAS_RAPIDS_HW")

        # check first that install is done
        if not (env.wenv_abs / ".venv").exists():
            logging.info("Worker installlation not found")
            sys.exit(1)

        pid_file = "dask-pid-0"
        current_pid = os.getpid()
        with open(pid_file, "w") as f:
            f.write(str(current_pid))

        await AGI._kill(current_pid=current_pid, force=True)

        if AGI._mode & AGI.CYTHON_MODE:
            wenv_abs = env.wenv_abs
            cython_lib_path = Path(wenv_abs)

            # Look for any files or directories in the Cython lib path that match the "*cy*" pattern.
            cython_libs = list(cython_lib_path.glob("*cy*"))
            if cython_libs:
                lib_path = normalize_path(cython_libs[0])
            else:
                AGI._build_lib_local(is_local=True)

        if env.debug:
            AgiWorker.new(env.app, mode=AGI._mode, verbose=AGI._verbose, args=AGI._args)
            res = AgiWorker.run(AGI.workers, mode=AGI._mode, verbose=AGI._verbose, args=AGI._args)
        else:
            cmd = (
                f"uv -q run --project {env.wenv_abs} python -c \"from agi_core.workers.agi_worker import AgiWorker;"
                f"from dask.distributed import print;"
                f"AgiWorker.new('{env.app}', mode={AGI._mode}, verbose={AGI._verbose}, args={AGI._args});"
                f"res = AgiWorker.run({AGI.workers}, mode={AGI._mode}, verbose={AGI._verbose}, args={AGI._args});"
                f"print(res)\""
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
    async def _run_by_mode():
        """
        workers run calibration and targets job
        """
        env = AGI.env

        # AGI distribute work on cluster
        AGI._dask_workers = [
            worker.split("/")[-1]
            for worker in list(AGI._dask_client.scheduler_info()["workers"].keys())
        ]
        logging.info(f"AGI run mode={AGI._mode} on {list(AGI._dask_workers)} ... ")

        AGI.workers, workers_tree, workers_tree_info = AgiManager.do_distrib(
            AGI._target_inst, env, AGI.workers
        )
        AGI.workers_tree = workers_tree
        AGI.workers_tree_info = workers_tree_info

        AGI._scale_cluster()

        if AGI._mode == AGI.INSTALL_MODE:
            workers_tree

        AGI._dask_client.gather(
            [
                AGI._dask_client.submit(
                    AgiWorker.new,
                    env.app,
                    mode=AGI._mode,
                    verbose=AGI._verbose,
                    worker_id=list(AGI._dask_workers).index(worker),
                    worker=worker,
                    args=AGI._args,
                    workers=[worker],
                )
                for worker in AGI._dask_workers
            ]
        )

        await AGI._calibration()

        t = time.time()

        AGI._run_time = AGI._dask_client.run(
            AgiWorker.do_works,
            workers_tree,
            workers_tree_info,
            workers=AGI._dask_workers,
        )

        runtime = time.time() - t
        print(f"{env.mode2str(AGI._mode)} {runtime}")
        return f"{env.mode2str(AGI._mode)} {runtime}"

    @staticmethod
    async def main(scheduler):
        cond_clean = (
            True
        )

        AGI._jobs = bg.BackgroundJobManager()

        if (AGI._mode & AGI.DEPLOYEMENT_MASK) == AGI.SIMULATE_MODE:
            # case simulate mode #0b11xxxx
            res = await AGI._run_local()

        elif AGI._mode >= AGI.INSTALL_MODE:
            # case install modes
            t = time.time()

            # clean both proc and dir
            await AGI._get_clean_nodes(scheduler)

            # clean local env
            AGI._clean_dirs_local()

            await AGI._install(scheduler)

            # clean both proc and dir
            AGI._get_clean_nodes(scheduler)

            res = time.time() - t

        elif (AGI._mode & AGI.DEPLOYEMENT_MASK) == AGI.SIMULATE_MODE:
            # case simulate mode #0b11xxxx
            res = await AGI._run_local()

        elif AGI._mode & AGI.DASK_MODE:

            await AGI._start(scheduler)

            res = await AGI._run_by_mode()
            AGI._update_model()

            # stop the cluster
            await AGI._stop()
        else:
            # case local run
            res = await AGI._run_local()

        AGI._clean_job(cond_clean)

        for p in AGI._sys_path_to_clean:
            if p in sys.path:
                sys.path.remove(p)
        return res

    @staticmethod
    def _clean_job(cond_clean):
        """

        Args:
          cond_clean:

        Returns:

        """
        # clean background job
        if AGI._jobs and cond_clean:
            if AGI._verbose:
                AGI._jobs.flush()
            else:
                with open(os.devnull, "w") as f, redirect_stdout(f), redirect_stderr(f):
                    AGI._jobs.flush()

    @staticmethod
    def _scale_cluster():
        """Remove unnecessary workers"""
        if AGI._dask_workers:
            nb_kept_workers = {}
            workers_to_remove = []
            for dask_worker in AGI._dask_workers:
                ip = dask_worker.split(":")[0]
                if ip in AGI.workers:
                    if ip not in nb_kept_workers:
                        nb_kept_workers[ip] = 0
                    if nb_kept_workers[ip] >= AGI.workers[ip]:
                        workers_to_remove.append(dask_worker)
                    else:
                        nb_kept_workers[ip] += 1
                else:
                    workers_to_remove.append(dask_worker)

            if workers_to_remove:
                logging.info(f"unused workers: {len(workers_to_remove)}")
                for worker in workers_to_remove:
                    AGI._dask_workers.remove(worker)

    @staticmethod
    async def _stop():
        """Stop the Dask workers and scheduler"""
        env = AGI.env
        logging.info("stop Agi fwk")

        i = 0
        while len(AGI._dask_client.scheduler_info()["workers"]) and (i < AGI.TIMEOUT):
            i += 1
            AGI._dask_client.retire_workers()
            await asyncio.sleep(1)

        if (
                AGI._mode_auto and (AGI._mode == 7 or AGI._mode == 15)
        ) or not AGI._mode_auto:
            AGI._dask_client.shutdown()

        await env.close_all_connections()

    @staticmethod
    def make_chunks(nchunk2, weights: list, capacities=None, verbose=0, threshold=12):
        """Partitions the nchunk2 weighted into n chuncks, in a smart way
        chunks and chunks_sizes must be left to None

        Args:
          nchunk2: list of number of chunks level 2
          weights: the list of weight level2
          capacities: the lnewist of workers capacity (Default value = None)
          verbose: whether to display run detail or not (Default value = 0)
          threshold: the number of nchunk2 max to run the optimal algo otherwise downgrade to suboptimal one (Default value = 12)
          weights: list:


        Returns:
          : list of chunk per my_code_worker containing list of works per my_code_worker containing list of chunks level 1

        """
        if not AGI.workers:
            AGI.workers = workers_default
        caps = []

        if not capacities:
            for w in list(AGI.workers.values()):
                for j in range(w):
                    caps.append(1)
            capacities = caps
        capacities = np.array(list(capacities))

        if len(weights) > 1:
            if nchunk2 < threshold:
                logging.info(f"AGI.chunk_algo_optimal - workers capacities {capacities} - {nchunk2} works to be done")
                chunks = AGI._make_chunks_optimal(weights, capacities)
            else:
                logging.info(f"AGI.load_algo_fastest - workers capacities {capacities} - {nchunk2} works to be done")
                chunks = AGI._make_chunks_fastest(weights, capacities)

            return chunks

        else:
            return [
                [
                    [
                        chk,
                    ]
                    for chk in weights
                ]
            ]

    @staticmethod
    def _make_chunks_optimal(subsets: list, chkweights, chunks=None, chunks_sizes=None):
        """Partitions subsets in nchk non-weighted chunks, in a slower but optimal recursive way

        Args:
          subsets: list of tuples ('label', size)
          chkweights: list containing the relative size of each chunk
          chunks: internal usage must be None (Default value = None)
          chunks_sizes: internal must be None (Default value = None)

        Returns:
          : list of chunks weighted

        """
        racine = False
        best_chunks = None

        nchk = len(chkweights)
        if chunks is None:  # 1ere execution
            chunks = [[] for _ in range(nchk)]
            chunks_sizes = np.array([0] * nchk)
            subsets.sort(reverse=True, key=lambda i: i[1])
            racine = True

        if not subsets:  # finished when all subsets are partitioned
            return [chunks, max(chunks_sizes)]

        # Optimisation: We check if the weighted difference between the biggest and the smalest chunk
        # is more than the weighted sum of the remaining subsets
        if max(chunks_sizes) > min(
                np.array(chunks_sizes + sum([i[1] for i in subsets])) / chkweights
        ):
            # If yes, we won't make the biggest chunk bigger by filling the smallest chunk
            smallest_chunk_index = np.argmin(
                chunks_sizes + sum([i[1] for i in subsets]) / chkweights
            )
            chunks[smallest_chunk_index] += subsets
            chunks_sizes[smallest_chunk_index] += (
                    sum([i[1] for i in subsets]) / chkweights[smallest_chunk_index]
            )
            return [chunks, max(chunks_sizes)]

        chunks_choices = []
        chunks_choices_max_size = np.array([])
        inserted_chunk_sizes = []
        for i in range(nchk):
            # We add the next subset to the ith chunk if we haven't already tried a similar chunk
            if (chunks_sizes[i], chkweights[i]) not in inserted_chunk_sizes:
                inserted_chunk_sizes.append((chunks_sizes[i], chkweights[i]))
                subsets2 = deepcopy(subsets)[1:]
                chunk_pool = deepcopy(chunks)
                chunk_pool[i].append(subsets[0])
                chunks_sizes2 = deepcopy(chunks_sizes)
                chunks_sizes2[i] += subsets[0][1] / chkweights[i]
                chunks_choices.append(
                    AGI._make_chunks_optimal(
                        subsets2, chkweights, chunk_pool, chunks_sizes2
                    )
                )
                chunks_choices_max_size = np.append(
                    chunks_choices_max_size, chunks_choices[-1][1]
                )

        best_chunks = chunks_choices[np.argmin(chunks_choices_max_size)]

        if racine:
            return best_chunks[0]
        else:
            return best_chunks

    @staticmethod
    def _make_chunks_fastest(subsets: list, chk_weights):
        """Partitions subsets in nchk weighted chunks, in a fast but non optimal way

        Args:
          subsets: list of tuples ('label', size)
          chk_weights: list containing the relative size of each chunk

        Returns:
          : list of chunk weighted

        """
        nchk = len(chk_weights)

        subsets.sort(reverse=True, key=lambda j: j[1])
        chunks = [[] for _ in range(nchk)]
        chunks_sizes = np.array([0] * nchk)

        for subset in subsets:
            # We add each subset to the chunk that will be the smallest if it is added to it
            smallest_chunk = np.argmin(chunks_sizes + (subset[1] / chk_weights))
            chunks[smallest_chunk].append(subset)
            chunks_sizes[smallest_chunk] += subset[1] / chk_weights[smallest_chunk]

        return chunks

    @staticmethod
    async def _calibration():
        """
        balancer calibration
        """
        res_workers_info = AGI._dask_client.gather(
            [
                AGI._dask_client.run(
                    # AgiWorker.get_logs_and_result,
                    AgiWorker.get_worker_info,
                    AgiWorker.worker_id,
                    workers=AGI._dask_workers,
                )
            ]
        )

        infos = {}

        for res in res_workers_info:
            for worker, info in res.items():
                if info:
                    logging.info(f"{worker}:{info}")
                infos[worker] = info

        AGI.workers_info = infos
        AGI._capacity = {}
        workers_info = {}

        for worker, info in AGI.workers_info.items():
            ipport = worker.split("/")[-1]
            infos = list(AGI.workers_info[worker].values())
            infos.insert(0, [AGI.workers[ipport.split(":")[0]]])
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
    def _train_model(train_home):
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

        logging.info(
            f"AGI.balancer_train_mode - Accuracy of the prediction of the workers capacity = "
            f"{AGI._capacity_predictor.score(X_test, y_test)}"
        )

        capacity_model = os.path.join(train_home, AGI._capacity_model_file)
        with open(capacity_model, "wb") as f:
            pickle.dump(AGI._capacity_predictor, f)

    @staticmethod
    def _update_model():
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
            worker_cap = data["label"]  # Capacité actuelle du my_code_wprker
            worker_rt = data["run_time"]  # Temps d'exécution du my_code_worker

            # Calculer le delta de temps et mettre à jour la capacité pour chaque autre my_code_worker
            for other_worker, other_data in current_state.items():
                if other_worker != worker:
                    other_rt = other_data[
                        "run_time"
                    ]  # Temps d'exécution de l'autre my_code_worker
                    delta = worker_rt - other_rt
                    workers_rt[worker]["label"] -= (
                            0.1 * worker_cap * delta / worker_rt / (len(current_state) - 1)
                    )
                else:
                    workers_rt[worker]["nb_workers"] = int(
                        AGI.workers[worker.split(":")[0]]
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
                raise RuntimeError(f"{w} workers AgiWorker.do_works failed")

        AGI._train_model(AGI.env.home_abs)

    @staticmethod
    def _exec_bg(cmd, cwd):
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
