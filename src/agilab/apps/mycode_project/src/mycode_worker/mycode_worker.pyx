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
import warnings

logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")

# Import the generic DAG worker (which already imports BaseWorker from agi_dispatcher)
from agi_node.dag_worker import DagWorker


class MycodeWorker(DagWorker):
    """class derived from DagWorker"""

    def start(self):
        """
        Start the function.

        This function prints the file name if the 'verbose' attribute is greater than 0.

        Args:
            self: The current instance of the class.

        Returns:
            None
        """
        logging.info(f"from: {__file__}")
        if(self._mode & 2 and "cy" not in __file__):
            raise RuntimeError("Cython requested but not executed")

    def get_work(self, work: str,args,previous_result):
        """
        :param work: contain the worker function name called by BaseWorker.do_work
        this is type string and not type function to avoid manager (e.g. Mycode) to be dependant of MyCodeWorker
        :return:
        """
        # if it comes in as "FlightSimWorker.work", turn it into "work"
        method = getattr(self, work, None)
        if method is None:
            raise AttributeError(f"No such method '{work}' on {self.__class__.__name__}")
        return method(args, previous_result)

    # --- Partition 1 (matches your working logs) ---

    def algo_A(self, args=None, previous_result=None):
        logger.info("MyCodeWorker.algo_A")
        logger.info(f"args: {args}")
        logger.info(f"previous_result: {previous_result}")
        # example return
        return {"a": 15, "b": 20, "c": 30}

    # only needs args
    def algo_B(self,  args=None, previous_result=None):
        logger.info("MyCodeWorker.algo_B")
        logger.info(f"args: {args}")
        return [15, 20, 30]

    # only needs previous result
    def algo_C(self, args=None, previous_result=None):
        logger.info("MyCodeWorker.algo_C")
        logger.info(f"previous_result: {previous_result}")
        return 3

    # --- Partition 2 style (the ones that crashed before due to signatures) ---

    # needs nothing
    def algo_X(self, args=None, previous_result=None):
        logger.info("MyCodeWorker.algo_X")
        return "X"

    # kwargs form (name-aware)
    def algo_Y(self, args=None, previous_result=None):
        logger.info("MyCodeWorker.algo_Y")
        logger.info(f"args: {args}")
        logger.info(f"previous_result: {previous_result}")
        return "Y"

    # classic two-arg form still fine
    def algo_Z(self, args, previous_result):
        logger.info("MyCodeWorker.algo_Z")
        logger.info(f"args: {args}")
        logger.info(f"previous_result: {previous_result}")
        return "Z"

    def stop(self):
        """
        Stop the current action.

        Raises:
            NotImplementedError: This method needs to be implemented in a subclass.
        """
        super().stop()