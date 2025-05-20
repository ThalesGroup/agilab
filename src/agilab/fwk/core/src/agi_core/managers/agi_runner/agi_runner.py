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
from IPython.core.ultratb import FormattedTB
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
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import timedelta
from ipaddress import ip_address as is_ip
from pathlib import Path, PurePosixPath, PureWindowsPath
from tempfile import gettempdir
from typing import Any, Dict, List, Optional, Union
import sysconfig
import logging

# External Libraries
import humanize
import numpy as np
import polars as pl
import psutil
from dask.distributed import Client
import json
import asyncssh
from scp import SCPClient
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
import subprocess
import inspect

# Patch for IPython ≥8.37 (theme_name) vs ≤8.36 (color_scheme)
_sig = inspect.signature(FormattedTB.__init__).parameters
_tb_kwargs = dict(mode='Verbose', call_pdb=True)
if 'color_scheme' in _sig:
    _tb_kwargs['color_scheme'] = 'Linux'
else:
    _tb_kwargs['theme_name'] = 'Linux'

sys.excepthook = FormattedTB(**_tb_kwargs)

# Project Libraries:
from agi_env import AgiEnv
from agi_core.managers.agi_manager import AgiManager
from agi_core.workers.agi_worker import AgiWorker

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
        3. Run `uv sync` before using AGI.
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
        AGI._rapids_install = rapids_enabled
        AGI.init_logging(verbose)
        logging.info(f"AGI instance created for target {target} with verbosity {verbose}")

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
                    exit(1)
                AGI._mode = env.mode2int(mode)
            elif isinstance(mode, int):
                AGI._mode = int(mode)
            else:
                logging.info("parameter <mode> must be an int, a list of int or a string")
                exit(1)

            AGI._run_types = ["run", "sync --upgrade", "sync", "simulate"]
            if AGI._mode:
                if AGI._mode & AGI.RUN_MASK not in range(0, AGI.RAPIDS_MODE):
                    raise ValueError(f"mode {AGI._mode} not implemented")
            else:
                # 16 first modes are "run" type, then there 16, 17 and 18
                AGI._run_type = AGI._run_types[(AGI._mode & AGI.DEPLOYEMENT_MASK) >> AGI.DASK_MODE]
            AGI._args = args
            AGI._verbose = verbose
            AGI.debug = True if verbose > 3 else False
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
                "AgiDataWorker": "data-worker",
                "AgiDagWorker": "dag-worker",
                "AgiAgentWorker": "agent-worker",
            }
            # AGI.install_worker_group = AGI.agi_workers[env.base_worker_cls]
            AGI.install_worker_group = ["agi-worker ", AGI.agi_workers[env.base_worker_cls]]
            base_worker_dir = str(env.workers_root / "src")
            if base_worker_dir not in sys.path:
                sys.path.insert(0, base_worker_dir)
            AGI._target_module = AGI._load_module(
                AGI._target,
                env.module,
                path=env.app_src_path,
            )
            if not AGI._target_module:
                raise RuntimeError(f"failed to load {AGI._target}")

            target_class = getattr(AGI._target_module, env.target_class)
            AGI._target_inst = target_class(env, **args)

            try:
                return await AGI.main(scheduler)
            except Exception as err:
                logging.error(err)
                if verbose > 1:
                    logging.error(traceback.format_exc())
                raise

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
            if not run:
                raise InterruptedError(f"mode {m} interrupted unexpectedly")

            if isinstance(run, str):
                # Assume run string splits into two parts:
                #  runtime[0] -> an identifying string for the mode,
                #  runtime[1] -> the time in seconds as a float
                runtime = run.split()
                if len(runtime) < 2:
                    raise ValueError(f"Unexpected run format: {run}")
                runtime_float = float(runtime[1])
            else:
                raise TypeError(f"Unexpected run type: {type(run)}")

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
        return json.dumps(runs_str_keys)

    @staticmethod
    def init_logging(verbosity: int = 1):
        """
        Initialize logging with a level based on verbosity:
        0 = WARNING, 1 = INFO, 2 or more = DEBUG
        """
        level = logging.WARNING  # default

        if verbosity >= 2:
            level = logging.DEBUG
        elif verbosity == 1:
            level = logging.INFO

        logging.basicConfig(
            level=level,
            format="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S",
        )
        logging.debug(f"Logging initialized at level {logging.getLevelName(level)}")

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
    def _load_module(module, package=None, path=None):
        """load a module

        Args:
          module: the name of the Agi apps module
          package: the package name where is the module (Default value = None)
          path: the path where is the package (Default value = None)

        Returns:
          : the instance of the module

        """
        path = AgiEnv.normalize_path(path)
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
            app_path = AGI.env.app_path
            cmd = f"uv add {module_to_install}"
            logging.info(f"{cmd} from {app_path}")
            AgiEnv.run(cmd, app_path)
            AGI._module_to_clean.append(module_to_install)
            return AGI._load_module(module, package, path)

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
    def _get_stderr(func, *args, **kwargs):
        f = io.StringIO()
        with redirect_stderr(f):
            result = func(*args, **kwargs)
        return f.getvalue(), result

    @staticmethod
    def _read_stdout(output_stream):
        for line in output_stream:
            if line.strip():
                AgiEnv.log_info(line.strip())

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
                AgiEnv.log_info(line)
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
                    AgiEnv.log_info(line)
                    AGI._worker_init_error = line.endswith('[ProjectError]')
            elif chan.exit_status_ready():
                break
            else:
                time.sleep(0.1)


    @staticmethod
    async def _exec_ssh_async(ip: str, cmd: str):
        """
        Execute a remote SSH command asynchronously using asyncssh.

        Usage:
            async with AGI._ssh_connect(ip) as conn:
                result = await conn.run(cmd, check=True)
        """
        try:
            async with AGI._ssh_connect(ip) as conn:
                result = await conn.run(cmd, check=True)
                AgiEnv.log_info(f"Command on {ip}: {cmd}\nOutput: {result.stdout.strip()}")
                return result.stdout.strip()
        except Exception as e:
            AgiEnv.log_error(f"Failed to execute SSH command on {ip}: {e}")
            raise

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

    @staticmethod
    def _kill(ip: str | None = None, current_pid: int | None = None, force: bool = True):
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
        for pid_file in env.wenv_abs.glob("dask-pid*"):
            try:
                text = pid_file.read_text().strip()
                pid = int(text)
                if pid != current_pid:
                    pids_to_kill.append(pid)
            except Exception:
                logging.warning(f"Could not read PID from {pid_file}, skipping")
            try:
                pid_file.unlink()
            except Exception as e:
                logging.warning(f"Failed to remove pid file {pid_file}: {e}")

        python_exe = "uv run python"
        cmds: list[str] = []

        # 2) If force, kill by process name
        if force:
            cmds.append(
                python_exe
                + ' -c "import psutil, getpass; me=getpass.getuser(); '
                  "[p.terminate() for p in psutil.process_iter(attrs=['name','username']) "
                  "if p.info['username']==me and p.info['name'].startswith('dask')]"
                  '"'
            )

        # 3) If we found any explicit pid files, terminate those PIDs
        if pids_to_kill:
            cmds.append(
                python_exe
                + ' -c "import os, psutil; '
                  f"pids={pids_to_kill}; "
                  "[psutil.Process(pid).terminate() for pid in pids if pid!=os.getpid()]"
                  '"'
            )

        last_res = None
        for cmd in cmds:
            # choose working directory based on local vs remote
            cwd = env.manager_root if ip == localhost else str(env.wenv_abs)
            if AGI._is_local(ip):
                AGI.run(cmd, cwd)
            else:
                AGI._exec_ssh(ip, cmd)

            # handle tuple or dict result
            if isinstance(last_res, dict):
                out = last_res.get("stdout", "")
                err = last_res.get("stderr", "")
                logging.info(out)
                if err:
                    raise RuntimeError(err)

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
    def _clean_dirs(ip):
        """Clean up remote worker

        Args:
          ip: address of remote worker

        Returns:

        """
        env = AGI.env
        wenv = env.wenv_rel

        AGI._exec_ssh(
            ip,
            cmd=(
                "uv run python -c \"import os, glob, shutil\n"
                "from tempfile import gettempdir\n"
                "wenv_path = os.path.abspath(os.path.expanduser('$wenv'))\n"
                "patterns = [os.path.join(gettempdir(), 'dask-scratch-space'), os.path.join(wenv_path, '*y')]\n"
                "[shutil.rmtree(path, ignore_errors=True) for pat in patterns for path in glob.glob(pat)]\""
            )
        )

    @staticmethod
    def _get_clean_nodes(scheduler):
        list_ip = set(list(AGI.workers) + [AGI._get_scheduler(scheduler)[0]])
        localhost_ip = socket.gethostbyname("localhost")
        if not list_ip:
            list_ip.add(localhost_ip)
        for ip in list_ip:
            if not AGI._is_local(ip) and not is_ip(ip):
                raise ValueError("error: invalid ip address")
        for ip in list_ip:
            try:
                if not AGI._is_local(ip) and (AGI._mode & 4):
                    AGI._kill(ip, os.getpid(), force=True)
            except:
                pass

                # remove the dask tempdir, the build dirs and the wenv dirs
            if AGI._is_local(ip):
                AGI._clean_dirs_local()
            else:
                AGI._clean_dirs(ip)
        return list_ip


    @staticmethod
    def _install_cluster(scheduler):
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
        python = f"uv run -p {pyvers} python"

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

            try:
                wenv_rel = env.wenv_rel
                pyvers = env.python_version

                # 1) Check uv
                try:
                    AGI._exec_ssh(ip, 'uv --version')
                except Exception:
                    # Try Windows installer
                    try:
                        AGI._exec_ssh(ip,
                                      'powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
                                      )
                    except Exception:
                        # Fallback to Unix installer
                        AGI._exec_ssh(ip, 'curl -LsSf https://astral.sh/uv/install.sh | sh')
                        AGI._exec_ssh(ip, 'source $HOME/.local/bin/env')

                # 2) Install Python
                AGI._exec_ssh(ip, f"uv python install {pyvers}")

                # 3) Bootstrap the uv environment
                cmd = (
                    f"{python} -c \"import os, subprocess; "
                    f"subprocess.run(['uv','init','--bare'], cwd=r'{wenv_rel}', check=True) "
                    "if not os.path.exists('pyproject.toml') else None\""
                )
                AGI._exec_ssh(ip, cmd)

                # 4) Make remote wenv dir
                AGI._exec_ssh(
                    ip,
                    f"uv run -p {pyvers} python -c "
                    f"\"import os; os.makedirs(r'{wenv_rel}', exist_ok=True)\""
                )

            except Exception as e:
                msg = str(e).splitlines()[0]
                raise RuntimeError(f"Node {ip} setup failed: {msg}")


    @staticmethod
    async def _install(scheduler):
        AGI._initialize_installation()
        env = AGI.env
        app_path = env.app_path
        wenv_rel = env.wenv_rel
        wenv_abs = env.wenv_abs
        pyvers = env.python_version
        extras = "--dev -p " + pyvers
        extras += " --config-file uv.toml" if AGI._rapids_install else ""
        options = {"manager": extras, "worker": extras}
        if isinstance(env.base_worker_cls, str):
            options["worker"] += " --extra " + " --extra ".join(AGI.install_worker_group)
        if AGI._mode & 4:
            AGI._install_cluster(scheduler)
        node_ips = AGI._get_clean_nodes(scheduler)
        AGI._venv_todo(node_ips)
        start_time = time.time()
        logging.info(f"********   Starting {AGI._run_type} for {app_path} in .env on 127.0.0.1")

        AGI._install_env_local(app_path, Path(wenv_rel), options)
        # logging.info(AGI.run(cmd, wenv_abs))
        if AGI._mode & 4:
            tasks = []
            for ip in node_ips:
                logging.info(f"********   Starting {AGI._run_type} for Agi_worker in .venv on {ip}")
                if not AGI._is_local(ip):
                    tasks.append(asyncio.create_task(
                        AGI._install_env_remote(ip, env, wenv_rel, options["worker"])
                    ))
            await asyncio.gather(*tasks)

        if AGI._verbose:
            duration = AGI._format_duration(time.time() - start_time)
            logging.info(f"\n********   Agi {AGI._run_type} completed in {duration}")

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
    def _install_env_local(src: Path, wenv_rel: Path, options: dict):
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

        has_rapids_hw = AGI._hardware_supports_rapids()

        # Commande pour manager selon si rapids supporté
        app_path = env.app_path.absolute()
        if has_rapids_hw:
            cmd_manager = f"uv {run_type} {options['manager']} --extra managers --project {app_path}"
        else:
            cmd_manager = f"uv --config-file uv.toml {run_type} {options['manager']} --extra managers --project {app_path}"

        logging.info(f"Installing manager: {cmd_manager}")
        AgiEnv.run(cmd_manager, app_path)

        # Copier les fichiers pyproject.toml et setup_core dans wenv_abs
        wenv_abs = env.wenv_abs
        logging.info(f"Copying {src / 'pyproject.toml'} -> {wenv_abs}")
        shutil.copy2(src / "pyproject.toml", wenv_abs)
        logging.info(f"Copying {env.setup_core} -> {wenv_abs}")
        shutil.copy2(env.setup_core, wenv_abs)

        # Commande pour workers selon si rapids supporté
        if has_rapids_hw:
            cmd_worker = f"uv {run_type} --project {wenv_abs} {options['worker']} --extra workers"
        else:
            cmd_worker = f"uv --config-file uv.toml {run_type} --project {wenv_abs} {options['worker']} --extra workers"

        logging.info(f"Installing workers: {cmd_worker}")
        AgiEnv.run(cmd_worker, wenv_abs)

        # Build worker lib local
        wenv = AGI._build_worker_lib(is_local=True)

        # Lancer le script post_install
        cmd_post = f"cd {wenv} && uv run -p {pyvers} python {env.post_install} {env.data_dir}"
        logging.info(f"Running post-install script: {cmd_post}")
        AgiEnv.run(cmd_post, wenv)

        # Cleanup modules
        AGI._uninstall_modules()
        AGI._install_done_local = True

    @staticmethod
    async def _exec_ssh(ip: str, cmd: str) -> str:
        """Run remote command asynchronously via SSH using asyncssh."""
        try:
            async with asyncssh.connect(ip) as conn:
                result = await conn.run(cmd, check=True)
                AgiEnv.log_info(f"Command on {ip}: {cmd}\nOutput: {result.stdout.strip()}")
                return result.stdout.strip()
        except (asyncssh.Error, OSError) as e:
            AgiEnv.log_error(f"SSH command failed on {ip}: {e}")
            raise

    @staticmethod
    async def get_ssh_connection(ip: str) -> asyncssh.SSHClientConnection:
        """
        Establish an SSH connection asynchronously using asyncssh.
        The caller is responsible for closing the connection.

        Raises:
            ValueError: if SSH username is not set.
            ConnectionError: on connection failures.
        """
        user = AGI.env.user
        password = AGI.env.password

        if not user:
            raise ValueError("SSH username is not configured. Please set 'user' in your .env file.")

        try:
            conn = await asyncssh.connect(
                ip,
                username=user,
                password=password,
                known_hosts=None,
                client_keys=None,
                # You can add other asyncssh.connect params here if needed
            )
            return conn

        except asyncssh.PermissionDenied:
            err_msg = f"Authentication failed for SSH user '{user}' on host {ip}."
            AgiEnv.log_error(err_msg)
            raise ConnectionError(err_msg)

        except (asyncssh.ConnectionLost, asyncssh.ConnectionFailed):
            err_msg = f"Could not connect to {ip}. Host unreachable or no SSH service running."
            AgiEnv.log_error(err_msg)
            raise ConnectionError(err_msg)

        except Exception as e:
            err_msg = f"SSH connection to {ip} failed: {e.__class__.__name__}: {e}"
            AgiEnv.log_error(err_msg)
            raise ConnectionError(err_msg)

    @staticmethod
    async def _send_file(ip: str, local_path: Path, remote_path: Path):
        """
        Send a single file asynchronously to remote host via SFTP.
        Opens and closes connection for each call.
        """
        try:
            conn = await AGI.get_ssh_connection(ip)
            try:
                async with conn.start_sftp_client() as sftp:
                    await sftp.put(str(local_path), str(remote_path))
                    AgiEnv.log_info(f"Sent file {local_path} to {ip}:{remote_path}")
            finally:
                conn.close()
                await conn.wait_closed()
        except (asyncssh.Error, OSError) as e:
            AgiEnv.log_error(f"Failed to send file {local_path} to {ip}: {e}")
            raise

    @staticmethod
    async def _send_files(ip: str, files: list[Path], remote_dir: Path):
        """
        Send multiple files asynchronously to remote host, opening one connection reused for all files.
        """
        try:
            conn = await AGI.get_ssh_connection(ip)
            try:
                async with conn.start_sftp_client() as sftp:
                    tasks = []
                    for f in files:
                        remote_path = remote_dir / f.name
                        tasks.append(sftp.put(str(f), str(remote_path)))
                    await asyncio.gather(*tasks)
                    AgiEnv.log_info(f"Sent {len(files)} files to {ip}:{remote_dir}")
            finally:
                conn.close()
                await conn.wait_closed()
        except (asyncssh.Error, OSError) as e:
            AgiEnv.log_error(f"Failed to send files to {ip}:{remote_dir}: {e}")
            raise

    @staticmethod
    async def _install_env_remote(ip: str, env, wenv_rel: Path, option: str):
        """Install packages and set up the environment on a remote node."""
        pyvers = env.python_version
        python = f"uv run -p {pyvers} python"
        env = AGI.env
        wenv_abs = env.wenv_abs
        wenv_rel = env.wenv_rel

        AGI._send_file(ip, env.setup_core, wenv_rel)

        # Send app source code
        egg_file = next(iter(wenv_abs.glob(f"{env.app}*.egg")), None)
        if egg_file:
            AGI._send_files(ip, [egg_file, env.pyproject, env.uvproject], wenv_rel)
        else:
            raise RuntimeError(cmd)

        # 1) Bootstrap ensurepip
        cmd = python + " -m ensurepip"
        AGI._exec_ssh(ip, cmd)

        # 4) Unzip egg into remote venv src/
        cmd = (
            f"{python} -c \"import os, pathlib, zipfile;"
            f" root = '{wenv_rel}';"
            f" os.makedirs(os.path.join(root,'src'), exist_ok=True);"
            f" [zipfile.ZipFile(str(e)).extractall(os.path.join(root,'src'))"
            f"  for e in pathlib.Path(root).glob('*.egg')]\""
        )

        AGI._exec_ssh(ip, cmd)

        # 5) Check remote Rapids hardware support via nvidia-smi
        check_rapids = (f"cd {wenv_rel} && {python} -c \"import subprocess, sys, shutil;"
                        "r = subprocess.run(['nvidia-smi'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
                        "sys.exit(0 if r.returncode == 0 else 1)\""
                        )

        result = AGI._exec_ssh(ip, check_rapids)
        has_rapids_hw = (result != "")
        logging.info(f"Remote Rapids-capable GPU: {has_rapids_hw}")

        # 6) Build and run uv sync, adding --config-file only when has_rapids_hw
        if has_rapids_hw:
            sync_cmd = f"cd {wenv_rel} && uv sync --upgrade {option}"
        else:
            sync_cmd = f"cd {wenv_rel} && uv --config-file uv.toml sync --upgrade {option}"

        AGI._exec_ssh(ip, sync_cmd);

        # 7) Post-install script
        cmd= f"cd {wenv_rel} && uv run -p {pyvers} python {env.post_install} {env.data_dir}"
        AGI._exec_ssh(ip, cmd)

        #####################################################
        # install env & core for enabling dask worker spawn
        ##################################################

        # init venv
        cmd = (
            f"{python} -c "
            "\"import os, subprocess; "
            f"ROOT = r'{wenv_rel}'; "
            "subprocess.run(['uv','init','--bare'], cwd=ROOT, check=True) "
            "if not os.path.exists(os.path.join(ROOT, 'pyproject.toml')) else None\""
        )
        AGI._exec_ssh(ip, cmd);

        # Bootstrap ensurepip
        cmd = f"cd {wenv_rel} && uv run python -m ensurepip"
        AGI._exec_ssh(ip, cmd);

        cmd = f"cd {wenv_rel} && uv pip install -e ."
        AGI._exec_ssh(ip, cmd)

        # build agi_env*.whl
        wenv = env.agi_fwk_env_path
        dist = wenv / "dist"
        cmd = f"cd {wenv} && uv build --wheel"
        AgiEnv.run(cmd, venv=wenv)

        whl = next(iter(dist.glob("agi_env*.whl")))
        if whl:
            AGI._send_file(ip, whl, wenv_rel)
        else:
            raise RuntimeError(cmd)

        cmd = f"cd {wenv_rel} && uv add {Path(whl).name}"
        AGI._exec_ssh(ip, cmd)

        # build agi_core*.whl
        wenv = env.core_root
        dist = wenv / "dist"
        cmd = f"cd {wenv} && uv build --wheel"
        AgiEnv.run(cmd, venv=wenv)

        whl = next(iter(dist.glob("agi_core*.whl" )))
        if whl:
            AGI._send_file(ip, whl, wenv_rel)
        else:
            raise RuntimeError(cmd)

        cmd = f"cd {wenv_rel} && uv add {Path(whl).name}"
        AGI._exec_ssh(ip, cmd)
        setup = wenv_rel / "setup"
        out_dir = Path('..') / wenv_rel.name
        # build target_worker lib
        cmd = f"cd {wenv_rel} && uv run python {setup} build_ext -b {out_dir}"
        AGI._exec_ssh(ip, cmd)


    @staticmethod
    def _should_install_pip():
        return str(getpass.getuser()).startswith("T0") and not (Path(sys.prefix) / "Scripts/pip.exe").exists()

    @staticmethod
    def _uninstall_modules():
        """Uninstall specified modules."""
        for module in AGI._module_to_clean:
            cmd = f"uv run python -m pip uninstall {module} -y"
            logging.info(f"Executing: {cmd}")
            AgiEnv.run(cmd, AGI.env.core_root)
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
        """uv config

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
            modes_enabled=RUN_MASK, verbose=1, **args
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
        await AGI.run(module_name,
                      scheduler=scheduler,
                      workers=workers,
                      env=env,
                      mode=(AGI.INSTALL_MODE | modes_enabled),
                      rapids_enabled=AGI.INSTALL_MODE & modes_enabled,
                      verbose=verbose, **args)

    @staticmethod
    async def update(
            module_name, module_path, scheduler: Optional[str] = None, workers: Optional[Dict[str, int]] = None,
            modes_enabled=RUN_MASK, verbose=1, **args
    ):
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
        await AGI.run(module_name_or_path, scheduler=scheduler, workers=workers,
                      mode=(AGI.UPDATE_MODE | modes_enabled) & AGI.DASK_RESET,
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
        list_ip: any ip V4 with ssh access and python (upto you to link it to python3) with psutil and uv synced
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

        if (AGI._mode_auto and AGI._mode == AGI.DASK_MODE) or not AGI._mode_auto:
            if AGI._mode & AGI.DASK_MODE:
                if scheduler is None:
                    if list(AGI.workers) == ["127.0.0.1"]:
                        scheduler = "127.0.0.1"
                    else:
                        logging.info("AGI.run(...scheduler='scheduler ip address' is required\nStop")
                        exit(1)

                AGI._scheduler_ip, AGI._scheduler_port = AGI._get_scheduler(scheduler)

            # Clean cluster environment by killing old processes
            for ip in set(list(AGI.workers) + [AGI._scheduler_ip]):
                try:
                    AGI._kill(ip, os.getpid(), force=True)
                except Exception:
                    pass

            toml_local = env.app_path / "pyproject.toml"
            wenv_rel = env.wenv_rel

            if AGI._is_local(AGI._scheduler_ip):
                await asyncio.sleep(1)  # non-blocking sleep
                cmd = (
                    f"uv run --project {env.wenv_abs} dask scheduler --port {AGI._scheduler_port} "
                    f"--host {AGI._scheduler_ip} --pid-file dask_pid"
                )
                logging.info(f"Starting dask scheduler locally: {cmd}")
                result = AGI._exec_bg(cmd, env.app_path)  # assuming _exec_bg is sync
                logging.info(result)
            else:
                # Create remote directory
                cmd = f"python3 -c \"import os; os.makedirs('{wenv_rel}', exist_ok=True)\""
                await AGI._exec_ssh(AGI._scheduler_ip, cmd)

                toml_wenv = wenv_rel / "pyproject.toml"
                await AGI._send_file(AGI._scheduler_ip, toml_local, toml_wenv)

                cmd = (
                    f"uv run --project {wenv_rel} dask scheduler --port {AGI._scheduler_port} "
                    f"--host {AGI._scheduler_ip} --pid-file dask_pid"
                )
                # Run scheduler asynchronously over SSH without awaiting completion (fire and forget)
                asyncio.create_task(AGI._exec_ssh_async(AGI._scheduler_ip, cmd))

            try:
                await asyncio.sleep(1)  # Give scheduler a moment to start
                AGI._dask_client = await Client(AGI._scheduler, timeout=AGI.TIMEOUT)
            except Exception as e:
                logging.error("Dask Client instantiation trouble, run aborted due to:")
                logging.info(e)
                exit(1)

            AGI._install_done = True

            if AGI._worker_init_error:
                raise FileNotFoundError(f"Please run AGI.install([{AGI._scheduler_ip}])")

        return True

        @staticmethod
        async def _detect_export_cmd(ip: str) -> str:
            if AGI._is_local(ip):
                return AGI.env.export_local_bin

            # probe remote OS via SSH
            try:
                proc = await asyncio.create_subprocess_shell(
                    f'ssh {ip} uname -s',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL
                )
                out, _ = await proc.communicate()
                os_id = out.decode().strip().lower()
            except Exception:
                os_id = ''

            if any(x in os_id for x in ('linux', 'darwin', 'bsd')):
                return 'export PATH="$HOME/.local/bin:$PATH";'
            else:
                return 'set PATH=%USERPROFILE%\\.local\\bin;%PATH% &&'

    @staticmethod
    async def _start(scheduler):
        """
        Start Dask workers on local and remote hosts,
        setting PATH correctly for each OS.
        """
        # helper to pick export_local_bin for a given host

        env = AGI.env
        # start the scheduler first
        if not await AGI._start_scheduler(scheduler):
            return

        # launch each worker
        for i, (ip, n) in enumerate(AGI.workers.items()):
            export_cmd = await AGI._detect_export_cmd(ip)

            for j in range(n):
                logging.info(f"starting worker #{i}.{j} on {ip}")

                # choose absolute vs. relative paths
                if AGI._is_local(ip):
                    pid_file = env.wenv_abs / "dask-pid"
                    proj_dir = env.wenv_abs
                else:
                    AGI._install_done = True
                    pid_file = Path(env.wenv_rel) / "dask-pid"
                    wenv_rel = env.wenv_rel

                # build the command
                cmd = (
                    f'{export_cmd} '
                    f'uv --project {env.wenv_abs} run dask worker {AGI._scheduler} --no-nanny '
                    f'--pid-file {pid_file}#{i}.{j}'
                )

                logging.info(cmd)

                # execute locally or over SSH
                if AGI._is_local(ip):
                    AGI._exec_bg(cmd, env.wenv_abs)
                else:
                    await AGI._exec_ssh_async(ip, cmd)

                if AGI._worker_init_error:
                    raise FileNotFoundError(f"Please run AGI.install([{ip}])")

        # wait for all workers to sync
        await AGI._sync()

        # optionally build Cython/cluster libs
        if (not AGI._mode_auto) or (AGI._mode < 6) or (AGI._mode & AGI.CYTHON_MODE):
            await AGI._build_cluster_libs()


    @staticmethod
    async def _sync():
        """
        wait for all dask workers started
        """
        if not isinstance(AGI._dask_client, Client):
            return
        runners = list(AGI._dask_client.scheduler_info()["workers"].keys())
        ip_counts = {}

        # initialize ip_counts list with 0 workers per IP
        for i, (ip_worker, n_workers) in enumerate(AGI.workers.items()):
            ip_counts[ip_worker] = 0

        for runner in runners:
            # Split the worker_key using ":" to separate the IP and port
            ip_runner = runner.split(":")[1][
                        2:
                        ]  # retrieve IP address of runner, ignore port number
            ip_counts[ip_runner] += 1

        while True:
            runners = list(AGI._dask_client.scheduler_info()["workers"].keys())
            worker_to_start = sum(AGI.workers.values()) - len(runners)

            if not worker_to_start:
                break

            for i, (ip_worker, n_workers) in enumerate(AGI.workers.items(), start=1):
                count_runners = ip_counts[ip_worker]

                if count_runners <= n_workers:
                    nb_remaining_workers = n_workers - count_runners
                    logging.info(f"waiting for workers to attach: {nb_remaining_workers}")
            time.sleep(1)

        logging.info(f"All workers successfully attached to scheduler")

    @staticmethod
    def _build_worker_lib(is_local=True):
        """

        Args:
          is_local: (Default value = True)

        Returns:

        """
        env = AGI.env
        pyvers = env.python_version
        wenv = AgiEnv.normalize_path(str(env.wenv_abs))
        is_cy = AGI._mode & AGI.CYTHON_MODE
        packages = "agi_worker, "
        baseworker = env.base_worker_cls
        if baseworker.startswith("AgiAgent"):
            packages += "agent_worker"
        elif baseworker.startswith("AgiDag"):
            packages += "dag_worker"
        elif baseworker.startswith("AgiData"):
            packages += "data_worker"

        app_path = env.app_path
        wenv_abs = env.wenv_abs
        shutil.copy(env.setup_core, app_path)
        cmd = f"cd {app_path} && uv run python setup bdist_egg --packages \"{packages}\" -d {wenv_abs}"
        AgiEnv.run(cmd, app_path)
        # compile in cython when cython is requested
        if is_local:
            cmd = f"cd {wenv_abs} && uv pip install -e ."
            AgiEnv.run(cmd, wenv_abs)

            if is_cy:
                # cython compilation of wenv/src into wenw
                shutil.copy(env.setup_core, wenv_abs)
                cmd = f"cd {app_path} && uv run python setup build_ext -b {wenv_abs}"
                res = AgiEnv.run(cmd, app_path)
                worker_lib = next(iter(wenv_abs.glob("*_cy.*")), None)
                if not worker_lib:
                    raise RuntimeError(cmd)

                # Get the current interpreter's platlib path (e.g. '/usr/lib/python3.12/site-packages')
                platlib = sysconfig.get_path("platlib")
                platlib_idx = platlib.index('.venv')
                wenv_platlib = platlib[platlib_idx:]
                target_platlib = wenv_abs / wenv_platlib
                destination = os.path.join(target_platlib, os.path.basename(worker_lib))

                # Copy the file while preserving metadata.
                shutil.copy2(worker_lib, destination)
                AgiEnv.log_info(res)
            # os.remove(env.setup_app)
        else:

            # finally BUILD AND LOAD THE TARGET WORKER EGG ON all workers
            for worker in list(AGI._dask_client.scheduler_info()["workers"].keys()):
                AGI._dask_client.run(
                    AgiWorker.build,
                    env.target_worker,
                    AGI._dask_client.scheduler_info()["workers"][worker][
                        "local_directory"
                    ],
                    worker,
                    mode=AGI._mode,
                    verbose=AGI._verbose,
                    workers=[worker],
                )

        return wenv

    @staticmethod
    async def _build_cluster_libs():
        """
        workers init
        """
        AGI._build_worker_lib(is_local=False)

        # worker
        if (AGI._dask_client.scheduler.pool.open == 0) and AGI._verbose:
            runners = list(AGI._dask_client.scheduler_info()["workers"].keys())
            logging.info("warning: no scheduler found but requested mode is dask=1 => switch to dask")

    @staticmethod
    def _run_local():
        """

        Returns:

        """
        env = AGI.env
        # check first that install is done
        if not (env.wenv_abs / ".venv").exists():
            logging.info("Worker installlation not found")
            exit(1)

        pid_file = env.wenv_abs / "dask-pid-0"
        current_pid = os.getpid()
        with open(pid_file, "w") as f:
            f.write(str(current_pid))

        AGI._kill(current_pid=current_pid, force=True)

        if AGI._mode & AGI.CYTHON_MODE:
            wenv_abs = env.wenv_abs
            cython_lib_path = Path(wenv_abs)

            # Look for any files or directories in the Cython lib path that match the "*cy*" pattern.
            cython_libs = list(cython_lib_path.glob("*cy*"))
            if cython_libs:
                lib_path = AgiEnv.normalize_path(cython_libs[0])
            else:
                AGI._build_worker_lib(is_local=True)
        # do distribut
        cmd = (f'uv run --project {env.wenv_abs} python -c "from agi_core.workers.agi_worker import AgiWorker;'
               f'print(AgiWorker.run(\'{env.app}\', {AGI.workers}, {AGI._mode}, {AGI._verbose}, {AGI._args}))"')
        res = AgiEnv.run(cmd, env.wenv_abs)
        return res.split('\n')[-2]

    @staticmethod
    async def main(scheduler):
        cond_clean = (
            True
        )

        AGI._jobs = bg.BackgroundJobManager()

        if (AGI._mode & AGI.DEPLOYEMENT_MASK) == AGI.SIMULATE_MODE:
            # case simulate mode #0b11xxxx
            res = AGI._run_local()

        elif AGI._mode >= AGI.INSTALL_MODE:
            # case install modes
            t = time.time()

            # clean local env
            AGI._clean_dirs_local()

            await AGI._install(scheduler)

            # clean both proc and dir
            AGI._get_clean_nodes(scheduler)

            res = time.time() - t

        elif (AGI._mode & AGI.DEPLOYEMENT_MASK) == AGI.SIMULATE_MODE:
            # case simulate mode #0b11xxxx
            res = AGI._run_local()

        elif AGI._mode & AGI.DASK_MODE:
            # case distributed run
            # start the cluster
            await AGI._start(scheduler)

            # do the run
            res = await AGI._run_by_mode()
            AGI._update_model()

            # stop the cluster
            AGI._stop()
        else:
            # case local run
            res = AGI._run_local()

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
                    env.target_worker,
                    env.target_worker_class,
                    env.target_worker,
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

        if AGI._verbose > 2:
            AGI._run_time = AGI._dask_client.run(
                AgiWorker._get_stdout,
                AgiWorker.do_works,
                workers_tree,
                workers_tree_info,
                workers=AGI._dask_workers,
            )
            raise SystemExit(AGI._run_time)
        else:
            AGI._run_time = AGI._dask_client.run(
                AgiWorker.do_works,
                workers_tree,
                workers_tree_info,
                workers=AGI._dask_workers,
            )

        runtime = time.time() - t

        return f"{env.mode2str(AGI._mode)} {runtime}"

    @staticmethod
    def _stop():
        """Stop the Dask workers and scheduler"""
        logging.info(f"stop Agi fwk")

        # AGI._dask_client.retire_workers() # causing comm close error on ubuntu

        i = 0
        while len(AGI._dask_client.scheduler_info()["workers"]) and (i < AGI.TIMEOUT):
            i += 1
            AGI._dask_client.retire_workers()
            time.sleep(1)

        if (
                AGI._mode_auto and (AGI._mode == 7 or AGI._mode == 15)
        ) or not AGI._mode_auto:
            AGI._dask_client.shutdown()

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
            # if True: # bug a corriger sur chunk_fastest
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
                    AgiWorker._get_stdout,
                    AgiWorker.get_worker_info,
                    AgiWorker.worker_id,
                    workers=AGI._dask_workers,
                )
            ]
        )

        infos = {}

        for res in res_workers_info:
            for worker, info in res.items():
                if info[0]:
                    logging.info(worker, ":", info[0])
                infos[worker] = info[1]

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
