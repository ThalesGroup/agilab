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
Package your_code

    mycode: module mycode
    Auteur: Jean-Pierre Morard
    Copyright: Thales SIX GTS France SAS
"""

from numba import njit, prange
import json
import os
import re
import shutil
import subprocess
import warnings
from pathlib import Path
from typing import Any

import py7zr

from agi_node.agi_dispatcher import WorkDispatcher, BaseWorker
import logging

from .app_args import (
    ArgsOverrides,
    MycodeArgs,
    dump_args,
    ensure_defaults,
    load_args,
    merge_args,
)

logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")


class Mycode(BaseWorker):
    """Class MyCode provides methods to orchestrate the run"""

    def __init__(
        self,
        env,
        args: MycodeArgs | None = None,
        **kwargs: ArgsOverrides,
    ) -> None:
        self.env = env
        if args is None:
            args = MycodeArgs(**kwargs)
        self.args = args
        WorkDispatcher.args = self.args.model_dump(mode="json")

    @classmethod
    def from_toml(
        cls,
        env,
        settings_path: str | Path = "app_settings.toml",
        section: str = "args",
        **overrides: ArgsOverrides,
    ) -> "Mycode":
        base = load_args(settings_path, section=section)
        merged = ensure_defaults(merge_args(base, overrides or None))
        return cls(env, args=merged)

    def to_toml(
        self,
        settings_path: str | Path = "app_settings.toml",
        section: str = "args",
        create_missing: bool = True,
    ) -> None:
        dump_args(self.args, settings_path, section=section, create_missing=create_missing)

    def as_dict(self) -> dict[str, Any]:
        return self.args.model_dump(mode="json")

    def build_distribution(self, workers):
        """Build distribution as a calling graph."""

        # workers_tree is a list representing multiple "workers" (parallel execution units).
        # Each worker is represented as a list of tasks.
        #
        # Each task is stored as a tuple:
        #    (
        #        function_info: dict,   # Metadata about the function to execute
        #            {
        #                "functions name": str,   # Name/identifier of the function
        #                "args": dict | list      # Arguments to pass to the function
        #            }
        #        dependencies: list[str]          # List of function names this task depends on
        #    )
        #
        # Structure:
        # [
        #     [  # Worker 0's tasks
        #         ({"functions name": ..., "args": ...}, [dependency names]),
        #     ],
        #     [  # Worker 1's tasks
        #     ],
        #     ...
        # ]
        #
        # Example meaning:
        # workers_tree[0][1] → Second task of worker 0:
        #   function: "algo_B", args: [15, 20, 30], dependencies: ["algo_A"]

        workers_tree = [
            [  # worker 0
                (
                    {
                        "functions name": "algo_A",
                        "args": {"a":15,"b":20,"c":30}
                    }, []),
                (
                    {
                        "functions name": "algo_B",
                        "args": [15, 20, 30]
                    },
                    ["algo_A"]),
                (
                    {
                        "functions name": "algo_C",
                        "args": 3
                    },
                    ["algo_B","algo_A"]),
            ],
            [  # worker 1
                (
                    {
                        "functions name": "algo_X",
                        "args": {"a":15,"b":20,"c":30}
                    }, []),
                (
                    {
                        "functions name": "algo_Y",
                        "args": {"a":15,"b":20,"c":30}
                    },
                    ["algo_X"]),
                (
                    {
                        "functions name": "algo_Z",
                        "args": {"a": 15, "b": 20, "c": 30}
                    },
                    ["algo_Y"]),
            ],
        ]

        workers_tree_info = [
            [  # worker 0
                ("algo A", 1.1),
                ("algo B", 1.2),
                ("algo C", 1.3),
            ],
            [  # worker 1
                ("algo X", 2.1),
                ("algo Y", 2.2),
                ("algo Z", 2.3),
            ],
        ]

        return workers_tree, workers_tree_info, "id", "main", "unit"
