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
Module mycode_worker extension of your_code


    Auteur: yourself

"""

# -*- coding: utf-8 -*-
# https://github.com/cython/cython/wiki/enhancements-compilerdirectives
# cython:infer_types True
# cython:boundscheck False
# cython:cdivision True
# mycode_worker.py
from __future__ import annotations

import logging

# Import the generic DAG worker (which already imports BaseWorker from agi_dispatcher)
from agi_node.dag_worker import DagWorker


class MycodeWorker(DagWorker):
    """
    Custom algorithms only. No generic plumbing here.
    You can freely vary method signatures; DagWorker._invoke adapts the call.
    """

    def start(self, *args, **kwargs):
        # If BaseWorker/DagWorker defines __init__, keep it; otherwise this is harmless
        super().__init__(*args, **kwargs) if hasattr(super(), "__init__") else None
        if not hasattr(self, "logger"):
            self.logger = logging.getLogger(self.__class__.__name__)

    # --- Partition 1 (matches your working logs) ---

    def algo_A(self, args, prev_result):
        self.logger.info("MyCodeWorker.algo_A")
        self.logger.info(f"args: {args}")
        self.logger.info(f"previous_result: {prev_result}")
        return {"a": 15, "b": 20, "c": 30}

    def algo_B(self, args):
        self.logger.info("MyCodeWorker.algo_B")
        self.logger.info(f"args: {args}")
        return [15, 20, 30]

    def algo_C(self, prev_result):
        self.logger.info("MyCodeWorker.algo_C")
        self.logger.info(f"previous_result: {prev_result}")
        return 3

    # --- Partition 2 (the ones that previously crashed due to signature mismatch) ---

    def algo_X(self):
        self.logger.info("MyCodeWorker.algo_X")
        return "X"

    def algo_Y(self, *, args=None, previous_result=None):
        self.logger.info("MyCodeWorker.algo_Y")
        self.logger.info(f"args: {args}")
        self.logger.info(f"previous_result: {previous_result}")
        return "Y"

    def algo_Z(self, args, prev_result):
        self.logger.info("MyCodeWorker.algo_Z")
        self.logger.info(f"args: {args}")
        self.logger.info(f"previous_result: {prev_result}")
        return "Z"
