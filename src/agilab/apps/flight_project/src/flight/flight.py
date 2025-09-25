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

import os
import traceback
import logging
import warnings
from pathlib import Path
from typing import Any

import py7zr
import polars as pl

from agi_env import AgiEnv
from agi_node.agi_dispatcher import BaseWorker, WorkDispatcher
from .flight_args import (
    FlightArgs,
)
logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")


class Flight(BaseWorker):
    """Flight class provides methods to orchestrate the run."""

    ivq_logs = None
    auto_prepare_output_dir = True

    def __init__(
        self,
        env,
        args: FlightArgs | None = None,
        **raw_args: Any,
    ) -> None:
        self.env = env

        if args is None:
            if not raw_args:
                raise ValueError("Flight requires arguments to be provided via args model or keyword values")
            args = FlightArgs(**raw_args)

        self.setup_args(
            args,
            env=env,
            error="Flight requires an initialized FlightArgs instance",
            output_field="data_uri",
        )

        WorkDispatcher.args = self.args.model_dump(mode="json")

    def build_distribution(self, workers):
        """build_distrib: to provide the list of files per planes (level1) and per workers (level2)
        the level 1 has been think to prevent that à job that requires all the output-data of a plane have to wait for another
        flight_worker which would have collapse the overall performance

        Args:

        Returns:

        """
        try:
            # create list of works weighted
            planes_partition, planes_partition_size, df = self.get_partition_by_planes(
                self.get_data_from_files()
            )

            # get the second level of the distribution tree by by dispatching these works per workers
            # make chunk of planes by worker with a load balancing that takes into consideration workers capacities
            workers_chunks = WorkDispatcher.make_chunks(
                len(planes_partition), planes_partition_size, verbose=self.verbose, workers=workers, threshold=12
            )
            if workers_chunks:
                # build tree: workers = dask workers -> works = planes -> files <=> list of list of list
                # files by plane are capped  to max number of files requested per workers

                workers_planes_dist = []
                df = df.with_columns([pl.col("id_plane").cast(pl.Int64)])

                for planes in workers_chunks:
                    workers_planes_dist.append(
                        [
                            df.filter(pl.col("id_plane") == plane_id)["files"]
                            .head(self.args.nfile)
                            .to_list()
                            for plane_id, _ in planes
                        ]
                    )

                workers_chunks = [
                    [(plane, round(size / 1000, 3)) for plane, size in chunk]
                    for chunk in workers_chunks
                ]

            # tree: workers -> planes -> files
        except Exception as e:
            print(traceback.format_exc())
            print(f"warning issue while trying to build distribution: {e}")
        return workers_planes_dist, workers_chunks, "plane", "files", "ko"

    def get_data_from_hawk(self):
        """get output-data from ELK/HAWK"""
        # implement your hawk logic
        pass

    @staticmethod
    def extract_plane_from_file_name(file_path):
        """provide airplane id from log file name

        Args:
          file_path:

        Returns:

        """
        return int(file_path.split("/")[-1].split("_")[2][2:4])

    def get_data_from_files(self):
        """get output-data slices from files or from ELK/HAWK"""
        if self.args.data_source == "file":
            data_uri = Path(self.args.data_uri)
            home_dir = Path.home()

            self.logs_ivq = {
                str(f.relative_to(home_dir)): os.path.getsize(f) // 1000
                for f in data_uri.rglob(self.args.files)
                if f.is_file()
            }

            if not self.logs_ivq:
                raise FileNotFoundError(
                    "Error in make_chunk: no files found with"
                    f" Path('{data_uri}').rglob('{self.args.files}')"
                )

            df = pl.DataFrame(list(self.logs_ivq.items()), schema=["files", "size"])

        elif self.args.data_source == "hawk":
            # implement your HAWK logic
            pass

        return df

    def get_partition_by_planes(self, df):
        """build the first level of the distribution tree with planes as atomics partition

        Args:
          s: df: dataframe containing the output-data to partition
          df:

        Returns:

        """
        df = df.with_columns(
            pl.col("files")
            .str.extract(
                r"(?:.*/)?(\d{2})_")  # Optionally match directories, then capture two digits followed by an underscore
            .cast(pl.Int32)  # Cast the captured string to Int32
            .alias("id_plane")  # Rename the column
        )

        # Get the first 'nfile' rows per 'id_plane' group
        df = df.group_by("id_plane").head(self.args.nfile)

        # Sort the DataFrame by 'id_plane'
        df = df.sort("id_plane")

        # Compute the sum of 'size' per 'id_plane' and sort in descending order
        planes_partition = (
            df.group_by("id_plane")
            .agg(pl.col("size").sum().alias("size"))
            .sort("size", descending=True)
        )

        # Extract 'id_plane' and 'size' into lists and create tuples
        planes_partition_size = list(
            zip(
                planes_partition["id_plane"].to_list(),
                planes_partition["size"].to_list(),
            )
        )

        return planes_partition, planes_partition_size, df
