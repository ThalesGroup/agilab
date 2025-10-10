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

"""Dispatch helpers for coordinating AGILab worker execution."""

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
import traceback
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from types import SimpleNamespace

# External Libraries:
import numpy as np
from distutils.sysconfig import get_python_lib
import psutil
import humanize
import datetime
import logging
import socket
from copy import deepcopy

from agi_env import AgiEnv, normalize_path
from .base_worker import BaseWorker

logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")
workers_default = {socket.gethostbyname("localhost"): 1}


class WorkDispatcher:
    """Builds and runs distribution plans for target applications."""

    args = {}
    verbose = None

    def __init__(self, args=None):
        """Store ``args`` for later use when evaluating distribution plans."""
        WorkDispatcher.args = args

    @staticmethod
    def _convert_functions_to_names(workers_plan):
        """Recursively replace callables in ``workers_plan`` by their ``__name__``."""
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

        return _convert(workers_plan)

    @staticmethod
    async def _do_distrib(env, workers, args):
        """Build the distribution plan for ``env`` given worker layout and args."""
        base_worker_dir = str(env.cluster_root / "src")
        if base_worker_dir not in sys.path:
            sys.path.insert(0, base_worker_dir)
        target_module = await WorkDispatcher._load_module(
            env.target,
            env.target,
            path=env.app_src,
            env=env,
        )
        if not target_module:
            raise RuntimeError(f"failed to load {env.target}")

        target_class = getattr(target_module, env.target_class)
        target_inst = target_class(env, **args)

        file = env.distribution_tree
        workers_plan = []
        workers_plan_metadata = []
        rebuild_tree = False
        if file.exists():
            with open(file, "r") as f:
                data = json.load(f)
            workers_plan = data.get("work_plan")
            workers_plan_metadata = data.get("work_plan_metadata", [])
            if workers_plan is None or (
                data["workers"] != workers
                or data["target_args"] != args
            ):
                rebuild_tree = True

        if not file.exists() or rebuild_tree:
            workers_plan, workers_plan_metadata, part, nb_unit, weight_unit = (
                target_inst.build_distribution(workers)
            )

            data = {
                "target_args": args,
                "workers": workers,
                "work_plan_metadata": workers_plan_metadata,
                "work_plan": WorkDispatcher._convert_functions_to_names(workers_plan),
                "partition_key": part,
                "nb_unit": nb_unit,
                "weights_unit": weight_unit,
            }

            def convert_dates(obj):
                if isinstance(obj, (datetime.date, datetime.datetime)):
                    return obj.isoformat()
                raise TypeError(f"Type {type(obj)} not serializable")

            with open(file, "w") as f:
                json.dump(data, f, default=convert_dates, indent=2)

        loaded_workers = {}
        workers_work_item_tree_iter = iter(workers_plan)
        for ip, nb_workers in workers.items():
            for i, chunks in enumerate(workers_work_item_tree_iter):
                if ip not in loaded_workers:
                    loaded_workers[ip] = 0
                if chunks:
                    loaded_workers[ip] += 1

        workers_plan = [chunks for chunks in workers_plan if chunks]

        return loaded_workers.copy(), workers_plan, workers_plan_metadata

    @staticmethod
    def _onerror(func, path, exc_info):
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
                logging.info(f"optimal - workers capacities {capacities} - {nchunk2} works to be done")
                chunks = WorkDispatcher._make_chunks_optimal(weights, capacities)
            else:
                logging.info(f"fastest - workers capacities {capacities} - {nchunk2} works to be done")
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
            env: Optional[AgiEnv] = None,
            attempted_install: bool = False,
    ) -> Any:
        """load a module

        Args:
          env: the current Agi environment (used for fallback install)
          module: the name of the Agi apps module
          package: the package name where the module lives (Default value = None)
          path: the path where the package lives (Default value = None)

        Returns:
          : the instance of the module

        """
        logging.info(f"import {module} from {package} located in {path}")
        if path:
            try:
                candidate = Path(path)
                if candidate.is_file():
                    candidate = candidate.parent
                candidate = candidate.resolve()
                candidate_str = str(candidate)
                if candidate_str not in sys.path:
                    sys.path.insert(0, candidate_str)
            except Exception:
                pass

        try:
            if package:
                # Import module from a package
                return importlib.import_module(f"{package}.{module}")
            else:
                # Import module directly
                return importlib.import_module(module)

        except ModuleNotFoundError as e:
            module_to_install = (str(e).replace("No module named ", "").lower().replace("'", ""))
            # Only attempt install if an environment is provided
            if env is None or attempted_install:
                raise
            app_path = env.active_app
            cmd = f"{env.uv} add --upgrade {module_to_install}"
            logging.info(f"{cmd} from {app_path}")
            await AgiEnv.run(cmd, app_path)
            return await WorkDispatcher._load_module(
                module,
                package,
                path,
                env=env,
                attempted_install=True,
            )
