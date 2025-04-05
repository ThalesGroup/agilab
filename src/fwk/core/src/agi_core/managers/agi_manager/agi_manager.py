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

import json
import os
import socket

# External Libraries
import warnings
from copy import deepcopy
from pathlib import Path

warnings.filterwarnings("ignore")
workers_default = {socket.gethostbyname("localhost"): 1}


class AgiManager:
    """
    Class AgiManager for orchestration of jobs by the target.
    """

    args = {}
    verbose = None

    def __init__(self, args=None):
        """
        Initialize the AgiManager with input arguments.

        Args:
            args: The input arguments for initializing the AgiManager.

        Returns:
            None
        """
        AgiManager.args = args

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
    def do_distrib(inst, agi_env, workers):
        """
        Build the distribution tree.

        Args:
            inst: The instance for building the distribution tree.

        Returns:
            None
        """
        file = agi_env.distribution_tree
        workers_tree = []
        rebuild_tree = False
        if file.exists():
            with open(file, "r") as f:
                data = json.load(f)
            workers_tree = data["workers_tree"]
            if (
                data["workers"] != workers
                or data["target_args"] != AgiManager.args
            ):
                rebuild_tree = True

        if not file.exists() or rebuild_tree:
            workers_tree, workers_tree_info, part, nb_unit, weight_unit = (
                inst.build_distribution()
            )

            data = {
                "target_args": inst.args,
                "workers": workers,
                "workers_chunks": workers_tree_info,
                "workers_tree": AgiManager.convert_functions_to_names(workers_tree),
                "partition_key": part,
                "nb_unit": nb_unit,
                "weights_unit": weight_unit,
            }

            with open(file, "w") as f:
                json.dump(data, f)

        loaded_workers = {}
        workers_work_item_tree_iter = iter(workers_tree)
        for ip, nb_workers in workers.items():
            for i in range(nb_workers):
                chunks = next(workers_work_item_tree_iter)
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