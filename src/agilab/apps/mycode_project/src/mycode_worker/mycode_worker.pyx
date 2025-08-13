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

import warnings
import logging
from agi_env import AgiEnv, normalize_path
from agi_node.dag_worker import DagWorker

logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")


###############################################################################
#                      Agi Mandatory FUNCTIONS
###############################################################################
# class MyCodeWorker:
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
        if(self.mode & 2 and "cy" not in __file__):
            raise RuntimeError("Cython requested but not executed")

    def get_work(self, work: str,args,prev_result):
        """
        :param work: contain the worker function name called by BaseWorker.do_work
        this is type string and not type function to avoid manager (e.g. Mycode) to be dependant of MyCodeWorker
        :return:
        """
        # if it comes in as "FlightSimWorker.work", turn it into "work"
        method = getattr(self, work, None)
        if method is None:
            raise AttributeError(f"No such method '{work}' on {self.__class__.__name__}")
        return method(args, prev_result)

    def algo_A(self,args,prev_result):
        """
        Perform algorithm A.

        This method belongs to MyCodeWorker class.

        Args:
            self: Instance of MyCodeWorker.

        Returns:
            None

        Prints:
            str: Print statement indicating the execution of algorithm A.
        """
        logging.info(f"MyCodeWorker.algo_A")
        logging.info(f"args: {args}")
        logging.info(f"previous_result: {prev_result}")
        return args

    def algo_B(self,args,prev_result):
        """
        Prints a message indicating the execution of `algo_B` method in MyCodeWorker class.

        Args:
            self: Reference to the instance of MyCodeWorker class.

        Returns:
            None
        """
        logging.info(f"MyCodeWorker.algo_B")
        logging.info(f"args: {args}")
        logging.info(f"previous_result: {prev_result}")
        return args

    def algo_C(self,args,prev_result):
        """
        Prints a message indicating that the algo_C method of MyCodeWorker has been called.

        Args:
            self (): The MyCodeWorker instance on which the method is called.

        Returns:
            None
        """
        print(f"MyCodeWorker.algo_C")
        logging.info(f"args: {args}")
        logging.info(f"previous_result: {prev_result}")
        return args

    def algo_X(self):
        """
        Perform a specific algorithm X.

        This method prints a message indicating the execution of algorithm X.

        Args:
            self: The object instance.

        Returns:
            None
        """
        logging.info(f"MyCodeWorker.algo_X")

    def algo_Y(self):
        """
        Perform algorithm Y.

        This method is a part of the MyCodeWorker class.

        Args:
            self: The instance of the MyCodeWorker class.

        Returns:
            None
        """
        print(f"MyCodeWorker.algo_Y")

    def algo_Z(self):
        """
        Perform a specific algorithm Z.

        This function is part of the MyCodeWorker class.

        Returns:
            None
        """
        logging.info(f"MyCodeWorker.algo_Z")

    def stop(self):
        """
        Stop the current action.

        Raises:
            NotImplementedError: This method needs to be implemented in a subclass.
        """
        super().stop()