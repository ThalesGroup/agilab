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

    my_code: module my_code
    Auteur: Jean-Pierre Morard
    Copyright: Thales SIX GTS France SAS
"""

from numba import njit, prange
import json
import os
import re
from pydantic import BaseModel, validator, conint, confloat
import shutil
import subprocess
import warnings
from pathlib import Path
from typing import Unpack, Literal
import py7zr
from datetime import date

from agi_core.managers.agi_runner import AGI
from agi_core.managers.agi_manager import AgiManager

warnings.filterwarnings("ignore")


class MyCodeArgs(BaseModel):
    """Class MyCodeArgs contains Arguments for MyCode"""

    mycode_param1: int = conint


class MyCode(AgiManager):
    """Class MyCode provides methods to orchestrate the run"""

    def __init__(self, env, **args: Unpack[MyCodeArgs]):
        """
        Initialize the object with the provided keyword arguments.

        Args:
            **args (Unpack[MyCodeArgs]): Keyword arguments to initialize the object.

        Returns:
            None
        """        
        pass

    def build_distribution(self):
        """Build distribution as a calling graph."""

        workers_tree = [
            [  # worker 0
                ("MyCodeWorker.algo_A", []),
                ("MyCodeWorker.algo_B", ["MyCodeWorker.algo_A"]),
                ("MyCodeWorker.algo_C", ["MyCodeWorker.algo_B"]),
            ],
            [  # worker 1
                ("MyCodeWorker.algo_X", []),
                ("MyCodeWorker.algo_Y", ["MyCodeWorker.algo_X"]),
                ("MyCodeWorker.algo_Z", ["MyCodeWorker.algo_Y"]),
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