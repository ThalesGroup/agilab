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

"""
node module

    Auteur: Jean-Pierre Morard

"""

######################################################
# Agi Framework call back functions
######################################################
# Internal Libraries:
import getpass
import io
import importlib
import os
import shutil
import sys
import stat
import tempfile
import time
import subprocess
import warnings
import abc
import traceback
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# External Libraries:
import numpy as np
from distributed.worker_state_machine import BaseWorker
from distutils.sysconfig import get_python_lib
import psutil
import humanize
import datetime
import logging
import socket
from copy import deepcopy

from agi_env import AgiEnv, normalize_path

logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")
workers_default = {socket.gethostbyname("localhost"): 1}


class BaseWorker(abc.ABC):
    """
    class BaseWorker v1.0
    """

    _insts = {}
    _built = None
    _pool_init = None
    _work_pool = None
    share_path = None
    verbose = 1
    mode = None
    env = None
    worker_id = None
    worker = None
    home_dir = None
    logs = None
    dask_home = None
    worker = None
    t0 = None
    is_managed_pc = getpass.getuser().startswith("T0")
    cython_decorators = ["njit"]

    def start(self):
        """
        Start the worker and print out a message if verbose mode is enabled.

        Args:
            None

        Returns:
            None
        """
        """ """
        logging.info(
            f"BaseWorker.start - worker #{BaseWorker.worker_id}: {BaseWorker.worker} - mode: {self.mode}")
        self.start()

    def stop(self):
        """
        Returns:
        """
        logging.info(f"stop - worker #{self.worker_id}: {self.worker} - mode: {self.mode}"
                        )

    @staticmethod
    def expand_and_join(path1, path2):
        """
        Join two paths after expanding the first path.

        Args:
            path1 (str): The first path to expand and join.
            path2 (str): The second path to join with the expanded first path.

        Returns:
            str: The joined path.
        """
        if os.name == "nt" and not BaseWorker.is_managed_pc:
            path = Path(path1)
            parts = path.parts
            if "Users" in parts:
                index = parts.index("Users") + 2
                path = Path(*parts[index:])
            net_path = BaseWorker.normalize_path("\\\\127.0.0.1\\" + str(path))
            try:
                # your nfs account in order to mount it as net drive on windows
                cmd = f'net use Z: "{net_path}" /user:your-name your-password'
                logging.info(cmd)
                subprocess.run(cmd, shell=True, check=True)
            except Exception as e:
                logging.error(f"Mount failed: {e}")
        return BaseWorker.join(BaseWorker.expand(path1), path2)

    @staticmethod
    def expand(path, base_directory=None):
        # Normalize Windows-style backslashes to POSIX forward slashes
        """
        Expand a given path to an absolute path.
        Args:
            path (str): The path to expand.
            base_directory (str, optional): The base directory to use for expanding the path. Defaults to None.

        Returns:
            str: The expanded absolute path.

        Raises:
            None

        Note:
            This method handles both Unix and Windows paths and expands '~' notation to the user's home directory.
        """
        normalized_path = path.replace("\\", "/")

        # Check if the path starts with `~`, expand to home directory only in that case
        if normalized_path.startswith("~"):
            expanded_path = Path(normalized_path).expanduser()
        else:
            # Use base_directory if provided; otherwise, assume current working directory
            base_directory = (
                Path(base_directory).expanduser()
                if base_directory
                else Path("~/").expanduser()
            )
            expanded_path = (base_directory / normalized_path).resolve()

        if os.name != "nt":
            return str(expanded_path)
        else:
            return normalize_path(expanded_path)

    @staticmethod
    def join(path1, path2):
        # path to data base on symlink Path.home()/data(symlink)
        """
        Join two file paths.

        Args:
            path1 (str): The first file path.
            path2 (str): The second file path.

        Returns:
            str: The combined file path.

        Raises:
            None
        """
        path = os.path.join(BaseWorker.expand(path1), path2)

        if os.name != "nt":
            path = path.replace("\\", "/")
        return path

       # dans node.py (en dehors de la classe BaseWorker)
    def get_logs_and_result(func, *args, verbosity=logging.CRITICAL, **kwargs):
        import io
        import logging

        log_stream = io.StringIO()
        handler = logging.StreamHandler(log_stream)
        logger = logging.getLogger()

        if verbosity >= 2:
            level = logging.DEBUG
        elif verbosity == 1:
            level = logging.INFO
        else:
            level = logging.WARNING

        logger.setLevel(level)
        logger.addHandler(handler)

        try:
            result = func(*args, **kwargs)
        finally:
            logger.removeHandler(handler)

        return log_stream.getvalue(), result


    @staticmethod
    def exec(cmd, path, worker):
        """execute a command within a subprocess

        Args:
          cmd: the str of the command
          path: the path where to lunch the command
          worker:
        Returns:
        """
        import subprocess

        path = normalize_path(path)

        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, check=True, cwd=path
        )
        if result.returncode != 0:
            if result.stderr.startswith("WARNING"):
                logging.error(f"warning: worker {worker} - {cmd}")
                logging.error(result.stderr)
            else:
                raise RuntimeError(
                    f"error on node {worker} - {cmd} {result.stderr}"
                )

        return result

    @staticmethod
    def _log_import_error(module, target_class, target_module):
        logging.error(f"file:  {__file__}")
        logging.error(f"__import__('{module}', fromlist=['{target_class}'])")
        logging.error(f"getattr('{target_module} {target_class}')")
        logging.error(f"sys.path: {sys.path}")

    @staticmethod
    def _load_module(module_name, module_class):
        try:
            module = __import__(module_name, fromlist=[module_class])
        except ModuleNotFoundError:
            raise ModuleNotFoundError(f"module {module_name} is not installed")
        return getattr(module, module_class)

    @staticmethod
    def _load_manager():
        env = BaseWorker.env
        module_name = env.module
        module_class = env.target_class
        module_name += '.' + module_name
        if module_name in sys.modules:
            del sys.modules[module_name]
        return BaseWorker._load_module(module_name, module_class)

    @staticmethod
    def _load_worker(mode):
        env = BaseWorker.env
        module_name = env.target_worker
        module_class = env.target_worker_class
        if module_name in sys.modules:
            del sys.modules[module_name]
        if mode & 2:
            module_name += "_cy"
        else:
            module_name += '.' + module_name

        return BaseWorker._load_module(module_name, module_class)

    @staticmethod
    def is_cython_installed(env):
        module_class = env.target_worker_class
        module_name = env.target_worker + "_cy"

        try:
           __import__(module_name, fromlist=[module_class])

        except ModuleNotFoundError:
            return False

        return True

    @staticmethod
    async def run(workers={"127.0.0.1": 1}, mode=0, env=None, verbose=None, args=None):
        """
        :param app:
        :param workers:
        :param mode:
        :param verbose:
        :param args:
        :return:
        """
        if not env:
            env = BaseWorker.env
        else:
            BaseWorker.env = env

        if mode & 2:
            wenv_abs = env.wenv_abs

            # Look for any files or directories in the Cython lib path that match the "*cy*" pattern.
            cython_libs = list((wenv_abs / "dist").glob("*cy*"))

            # If a Cython library is found, normalize its path and set it as lib_path.
            lib_path = (
                str(Path(cython_libs[0].parent).resolve()) if cython_libs else None
            )

            if lib_path:
                if lib_path not in sys.path:
                    sys.path.insert(0, lib_path)
            else:
                logging.info(f"warning: no cython library found at {lib_path}")
                exit(0)


        try:
            workers, workers_tree, workers_tree_info = await WorkDispatcher.do_distrib(env, workers, args)
        except Exception as err:
            logging.error(traceback.format_exc())
            sys.exit(1)

        if mode == 48:
            return workers_tree

        t = time.time()
        BaseWorker.do_works(workers_tree, workers_tree_info)
        runtime = time.time() - t
        env._run_time = runtime

        return f"{env.mode2str(mode)} {humanize.precisedelta(datetime.timedelta(seconds=runtime))}"

    @staticmethod
    def onerror(func, path, exc_info):
        """
        Error handler for `shutil.rmtree`.
        If it’s a permission error, make it writable and retry.
        Otherwise re-raise.
        """
        exc_type, exc_value, _ = exc_info

        # handle permission errors or any non-writable path
        if exc_type is PermissionError or not os.access(path, os.W_OK):
            try:
                os.chmod(path, stat.S_IWUSR | stat.S_IREAD)
                func(path)
            except Exception as e:
                logging.error(f"warning failed to grant write access to {path}: {e}")
        else:
            # not a permission problem—re-raise so you see real errors
            raise exc_value

    @staticmethod
    def new(
            app,
            mode=mode,
            env=None,
            verbose=0,
            worker_id=0,
            worker="localhost",
            args=None,
    ):
        """new worker instance
        Args:
          module: instanciate and load target mycode_worker module
          target_worker:
          target_worker_class:
          target_package:
          mode: (Default value = mode)
          verbose: (Default value = 0)
          worker_id: (Default value = 0)
          worker: (Default value = 'localhost')
          args: (Default value = None)
        Returns:
        """
        try:
            if env == None:
                install_type = 1 if worker.startswith("localhost") or worker.startswith("127.0.0.1") else 2
                BaseWorker.env = AgiEnv(active_app=app, install_type=install_type, verbose=verbose)
            elif env == 0:
                install_type = 1 if worker.startswith("localhost") or worker.startswith("127.0.0.1") else 2
                BaseWorker.env = AgiEnv(active_app=app, install_type=install_type, verbose=verbose, debug=True)
            else:
                BaseWorker.env = env

            logging.info(f"venv: {sys.prefix}")
            logging.info(f"BaseWorker.new - worker #{worker_id}: {worker} from: {os.path.relpath(__file__)}")

            # import of derived Class of WorkDispatcher, name target_inst which is typically an instance of MyCode
            worker_class = BaseWorker._load_worker(mode)

            # Instantiate the class with arguments
            worker_inst = worker_class()
            worker_inst.mode = mode
            worker_inst.args = args
            worker_inst.verbose = verbose

            # Instantiate the base class
            BaseWorker.verbose = verbose
            # BaseWorker._pool_init = worker_inst.pool_init
            # BaseWorker._work_pool = worker_inst.work_pool
            BaseWorker._insts[worker_id] = worker_inst
            BaseWorker._built = False
            BaseWorker.worker = Path(worker).name
            BaseWorker.worker_id = worker_id
            BaseWorker.t0 = time.time()
            logging.info(f"worker #{worker_id}: {worker} starting...")
            BaseWorker.start(worker_inst)

        except Exception as e:
            logging.error(traceback.format_exc())
            raise

    @staticmethod
    def get_worker_info(worker_id):
        """def get_worker_info():

        Args:
          worker_id:
        Returns:
        """

        worker = BaseWorker.worker

        # Informations sur la RAM
        ram = psutil.virtual_memory()
        ram_total = [ram.total / 10 ** 9]
        ram_available = [ram.available / 10 ** 9]

        # Nombre de CPU
        cpu_count = [psutil.cpu_count()]

        # Fréquence de l'horloge du CPU
        cpu_frequency = [psutil.cpu_freq().current / 10 ** 3]

        # path = BaseWorker.share_path
        if not BaseWorker.share_path:
            path = tempfile.gettempdir()
        else:
            path = normalize_path(BaseWorker.share_path)
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)

        size = 10 * 1024 * 1024
        file = os.path.join(path, f"{worker}".replace(":", "_"))
        # start timer
        start = time.time()
        with open(file, "w") as af:
            af.write("\x00" * size)

        # how much time it took
        elapsed = time.time() - start
        time.sleep(1)
        write_speed = [size / elapsed]

        # delete the output-data file
        os.remove(file)

        # Retourner les informations sous forme de dictionnaire
        system_info = {
            "ram_total": ram_total,
            "ram_available": ram_available,
            "cpu_count": cpu_count,
            "cpu_frequency": cpu_frequency,
            "network_speed": write_speed,
        }

        return system_info

    @staticmethod
    def build(target_worker, dask_home, worker, mode=0, verbose=0):
        """
        Function to build target code on a target Worker.

        Args:
            target_worker (str): module to build
            dask_home (str): path to dask home
            worker: current worker
            mode: (Default value = 0)
            verbose: (Default value = 0)
        """

        # Log file dans le home_dir + nom du target_worker_trace.txt
        if str(getpass.getuser()).startswith("T0"):
            prefix = "~/MyApp/"
        else:
            prefix = "~/"
        BaseWorker.home_dir = Path(prefix).expanduser().absolute()
        BaseWorker.logs = BaseWorker.home_dir / f"{target_worker}_trace.txt"
        BaseWorker.dask_home = dask_home
        BaseWorker.worker = worker

        logging.info(
            f"build - worker #{BaseWorker.worker_id}: {worker} from: {os.path.relpath(__file__)}"
        )

        try:
            logging.info("set verbose=3 to see something in this trace file ...")

            if verbose > 2:
                logging.info("starting worker_build ...")
                logging.info(f"home_dir: {BaseWorker.home_dir}")
                logging.info(
                    f"worker_build(target_worker={target_worker}, dask_home={dask_home}, mode={mode}, verbose={verbose}, worker={worker})"
                )
                for x in Path(dask_home).glob("*"):
                    logging.info(f"{x}")

            # Exemple supposé : définir egg_src (non défini dans ton code)
            egg_src = dask_home + "/some_egg_file"  # adapte selon contexte réel

            extract_path = BaseWorker.home_dir / "wenv" / target_worker
            extract_src = extract_path / "src"

            if not mode & 2:
                egg_dest = extract_path / (os.path.basename(egg_src) + ".egg")

                logging.info(f"copy: {egg_src} to {egg_dest}")
                shutil.copyfile(egg_src, egg_dest)

                if str(egg_dest) in sys.path:
                    sys.path.remove(str(egg_dest))
                sys.path.insert(0, str(egg_dest))

                logging.info("sys.path:")
                for x in sys.path:
                    logging.info(f"{x}")

                logging.info("done!")

        except Exception as err:
            logging.error(
                f"worker<{worker}> - fail to build {target_worker} from {dask_home}, see {BaseWorker.logs} for details"
            )
            raise err

    @staticmethod
    def do_works(workers_tree, workers_tree_info):
        """run of workers

        Args:
          workers_tree: distribution tree
          workers_tree_info:
        Returns:
            logs: str, the log output from this worker
        """
        log_stream = io.StringIO()
        handler = logging.StreamHandler(log_stream)
        logger = logging.getLogger()  # root logger; adjust if you use a named logger

        # Optionally, only add if not already present (avoid duplicate logs)
        already_has_handler = any(isinstance(h, logging.StreamHandler) and h.stream == log_stream for h in logger.handlers)
        if not already_has_handler:
            logger.addHandler(handler)

        try:
            worker_id = BaseWorker.worker_id
            if worker_id is not None:
                logging.info(f"do_works - worker #{worker_id}: {BaseWorker.worker} from {os.path.relpath(__file__)}")
                logging.info(f"BaseWorker.work - #{worker_id + 1} / {len(workers_tree)}")
                BaseWorker._insts[worker_id].works(workers_tree, workers_tree_info)
            else:
                logging.error(f"this worker is not initialized")
                raise Exception(f"failed to do_works")

        except Exception as e:
            import traceback
            logging.error(traceback.format_exc())
            raise
        finally:
            logger.removeHandler(handler)

        # Return the logs
        return log_stream.getvalue()

class WorkDispatcher:
    """
    Class WorkDispatcher for orchestration of jobs by the target.
    """

    args = {}
    verbose = None

    def __init__(self, args=None):
        """
        Initialize the WorkDispatcher with input arguments.

        Args:
            args: The input arguments for initializing the WorkDispatcher.

        Returns:
            None
        """
        WorkDispatcher.args = args

    @staticmethod
    def convert_functions_to_names(workers_tree):
        """
        Converts functions in a nested structure to their names.
        """
        def _convert(val):
            if isinstance(val, list):
                return [_convert(item) for item in val]
            elif isinstance(val, tuple):
                return tuple(_convert(item) for item in val)
            elif isinstance(val, dict):
                return {key: _convert(value) for key, value in val.items()}
            elif callable(val):
                return val.__name__
            else:
                return val

        return _convert(workers_tree)

    @staticmethod
    async def do_distrib(env, workers, args):
        """
        Build the distribution tree.

        Args:
            inst: The instance for building the distribution tree.

        Returns:
            None
        """
        base_worker_dir = str(env.cluster_root / "src")
        if base_worker_dir not in sys.path:
            sys.path.insert(0, base_worker_dir)
        target_module = await WorkDispatcher._load_module(
            env.target,
            env.module,
            path=env.app_src,
        )
        if not target_module:
            raise RuntimeError(f"failed to load {env.target}")

        target_class = getattr(target_module, env.target_class)
        target_inst = target_class(env, **args)

        file = env.distribution_tree
        workers_tree = []
        workers_tree_info = []
        rebuild_tree = False
        if file.exists():
            with open(file, "r") as f:
                data = json.load(f)
            workers_tree = data["workers_tree"]
            if (
                data["workers"] != workers
                or data["target_args"] != args
            ):
                rebuild_tree = True

        if not file.exists() or rebuild_tree:
            workers_tree, workers_tree_info, part, nb_unit, weight_unit = (
                target_inst.build_distribution(workers)
            )

            data = {
                "target_args": args,
                "workers": workers,
                "workers_chunks": workers_tree_info,
                "workers_tree": WorkDispatcher.convert_functions_to_names(workers_tree),
                "partition_key": part,
                "nb_unit": nb_unit,
                "weights_unit": weight_unit,
            }

            def convert_dates(obj):
                if isinstance(obj, (datetime.date, datetime.datetime)):
                    return obj.isoformat()
                raise TypeError(f"Type {type(obj)} not serializable")

            with open("output.json", "w") as f:
                json.dump(data, f, default=convert_dates, indent=2)

        loaded_workers = {}
        workers_work_item_tree_iter = iter(workers_tree)
        for ip, nb_workers in workers.items():
            for i, chunks in enumerate(workers_work_item_tree_iter):
                if ip not in loaded_workers:
                    loaded_workers[ip] = 0
                if chunks:
                    loaded_workers[ip] += 1

        workers_tree = [chunks for chunks in workers_tree if chunks]

        return loaded_workers.copy(), workers_tree, workers_tree_info

    @staticmethod
    def onerror(func, path, exc_info):
        """
        Error handler for `shutil.rmtree`.

        If the error is due to an access error (read-only file),
        it attempts to add write permission and then retries.

        If the error is for another reason, it re-raises the error.

        Usage: `shutil.rmtree(path, onerror=onerror)`

        Args:
            func (function): The function that raised the error.
            path (str): The path name passed to the function.
            exc_info (tuple): The exception information returned by `sys.exc_info()`.

        Returns:
            None
        """
        # Check if file access issue
        if not os.access(path, os.W_OK):
            # Try to change the permissions of the file to writable
            os.chmod(path, stat.S_IWUSR)
            # Try the operation again
            func(path)
        # else:
        # Reraise the error if it's not a permission issue
        # raise

    @staticmethod
    def make_chunks(
    nchunk2: int,
    weights: List[Any],
    capacities: Optional[List[Any]] = None,
    workers: Dict = None,
    verbose: int = 0,
    threshold: int = 12,
) -> List[List[List[Any]]]:
        """Partitions the nchunk2 weighted into n chuncks, in a smart way
        chunks and chunks_sizes must be left to None

        Args:
          nchunk2: list of number of chunks level 2
          weights: the list of weight level2
          capacities: the list of workers capacity (Default value = None)
          verbose: whether to display run detail or not (Default value = 0)
          threshold: the number of nchunk2 max to run the optimal algo otherwise downgrade to suboptimal one (Default value = 12)
          weights: list:


        Returns:
          : list of chunk per your_worker containing list of works per your_worker containing list of chunks level 1

        """
        if not workers:
            workers = workers_default
        caps = []

        if not capacities:
            for w in list(workers.values()):
                for j in range(w):
                    caps.append(1)
            capacities = caps
        capacities = np.array(list(capacities))

        if len(weights) > 1:
            if nchunk2 < threshold:
                logging.info(f"chunk_algo_optimal - workers capacities {capacities} - {nchunk2} works to be done")
                chunks = WorkDispatcher._make_chunks_optimal(weights, capacities)
            else:
                logging.info(f"load_algo_fastest - workers capacities {capacities} - {nchunk2} works to be done")
                chunks = WorkDispatcher._make_chunks_fastest(weights, capacities)

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
    def _make_chunks_optimal(
    subsets: List[Any],
    chkweights: List[Any],
    chunks: Optional[List[Any]] = None,
    chunks_sizes: Optional[Any] = None
) -> Any:
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
                    WorkDispatcher._make_chunks_optimal(
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
    def _make_chunks_fastest(subsets: List[Any], chk_weights: List[Any]) -> List[List[Any]]:
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
    async def _load_module(
            module: str,
            package: Optional[str] = None,
            path: Optional[Union[str, Path]] = None,
    ) -> Any:
        """load a module

        Args:
          module: the name of the Agi apps module
          package: the package name where is the module (Default value = None)
          path: the path where is the package (Default value = None)

        Returns:
          : the instance of the module

        """
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
            app_path = AGI.env.active_app
            cmd = f"{AGI.env.uv} add --upgrade {module_to_install}"
            logging.info(f"{cmd} from {app_path}")
            await AgiEnv.run(cmd, app_path)
            return await WorkDispatcher._load_module(module, package, path)