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

    Auteur: yourself

"""

import warnings

from agi_core.workers.data_worker import AgiDataWorker

warnings.filterwarnings("ignore")


class DataAppWorker(AgiDataWorker):
    """class derived from AgiDataWorker"""

    pool_vars = None

    def start(self):
        """init"""
        if self.verbose > 0:
            print(f"from: {__file__}\n", end="")

    def work_init(self):
        """work_init : read from space"""
        global global_vars
        pass

    def pool_init(self, worker_vars):
        """pool_init: where to initialize work_pool process

        Args:
          vars:

        Returns:

        """
        global global_vars

        global_vars = worker_vars

    def work_pool(self, x=None):
        """work_pool_task

        Args:
          x: (Default value = None)

        Returns:

        """
        global global_vars

        pass

    def work_done(self, worker_df):
        """receive concatenate dataframe or work_id  in case without output-data

        Args:
          worker_df:

        Returns:

        """
        pass

    def stop(self):
        """
        Stop the DataAppWorker and print a message if verbose is greater than 0.

        No Args.

        No Returns.
        """
        if self.verbose > 0:
            print("DataAppWorker All done !\n", end="")
        """
        pools_done
        """
        super().stop()