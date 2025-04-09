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
import re
import traceback

from pydantic import BaseModel, validator, conint, confloat
import shutil
import warnings
from pathlib import Path
from typing import Unpack, Literal
import py7zr
import polars as pl
from datetime import date

from agi_core.managers.agi_runner import AGI
from agi_core.managers.agi_manager import AgiManager
from agi_env import AgiEnv

warnings.filterwarnings("ignore")


class FlightArgs(BaseModel):
    """FlightArgs contains Arguments for Flight"""

    data_source: Literal["file", "hawk"]
    path: Path
    files: str
    nfile: int = conint
    nskip: int = conint
    nread: int = conint(ge=0)
    sampling_rate: float = confloat(ge=0)
    datemin: date
    datemax: date
    output_format: Literal["parquet", "csv"]

    @validator("datemax")
    def check_date_order(cls, v, values):
        """
        Check the order of dates and validate the 'datemax' value.

        Args:
            cls: The class itself.
            v: The 'datemax' value to be validated.
            values (dict): A dictionary containing the input values.

        Returns:
            Any: The validated 'datemax' value.

        Raises:
            ValueError: If 'datemax' is not after 'datemin' or after "2021/06/01".
        """
        datemin = values.get("datemin")
        if datemin and date(2021, 6, 1) >= v < datemin:
            raise ValueError('datemax must be after datemin and before "2021/06/01"')
        return v

    @validator("datemin")
    def check_date(cls, v, values):
        """
        Check if the given date is greater than a specified minimum date.

        Args:
            v (datetime.date): The date to be validated.
            values (dict): A dictionary containing the values of all fields.

        Returns:
            datetime.date: The validated date.

        Raises:
            ValueError: If the input date is not greater than "2020/01/01".
        """
        if v < date(2020, 1, 1):
            raise ValueError('datemin must be greater than "2020/01/01"')
        return v

    @validator("files")
    def check_valid_regex(cls, value):
        """
        Check if the input string is a valid regular expression.

        Args:
            value (str): The string to be validated as a regex.

        Returns:
            str: The input string if it is a valid regex.

        Raises:
            ValueError: If the input string is not a valid regex.
        """
        try:
            if value.startswith("*"):
                value = '.' + value
            re.compile(value)

        except re.error:
            raise ValueError(f"The provided string '{value}' is not a valid regex.")
        return value


class Flight(AgiManager):
    """Flight class provides methods to orchester the run"""

    ivq_logs = None

    def __init__(self, env, **args: Unpack[FlightArgs]):

        # Handling defaults and specific behaviors
        """
        Initialize a Flight object with provided arguments.

        Args:
            **args (Unpack[FlightArgs]): Keyword arguments to configure the Flight object.
                Possible arguments include:
                    - data_source (str): Source of the data, either 'file' or 'hawk'.
                    - files (str): Path pattern or file name.
                    - path (str): Path to store data files.
                      remark: There is also src/flight_worker/dataset.7z for dataset replication per worker
                    - nfile (int): Maximum number of files to process.
                    - datemin (str): Minimum date for data processing.
                    - datemax (str): Maximum date for data processing.
                    - output_format (str): Output format for processed data, either 'parquet' or 'csv'.

        Raises:
            ValueError: If an invalid input mode is provided for data_source.
        """
        args["data_source"] = args.get("data_source", "file")
        self.data_source = args["data_source"]
        if self.data_source == "file":
            args["files"] = args.get("files", "*")
            path = args.get("path", os.path.join("~/data", "flight"))
            if env.is_managed_pc:
                path = path.replace("~", "~/MyApp")
            # path_abs = AgiEnv.normalize_path(os.path.expanduser(path))
            # if not os.path.exists(path_abs):
            # this is not working on Thales managed PC
            # os.link(src=os.path.join(AGI.env.app_path, "data"), dst=path_abs)
            # os.makedirs(path_abs, exist_ok=True)
            # data_src = os.path.join(AGI.env.app_path, "data.7z")
            # Extract contents of src_archive directly to path_abs
            # with py7zr.SevenZipFile(data_src, mode="r") as archive:
            # archive.extractall(path_abs)
            args["nfile"] = args.get("nfile", 999_999_999_999)
            if args["nfile"] == 0:
                args["nfile"] = 999_999_999_999
            args["path"] = path

        elif self.data_source == "hawk":
            # implement another logic
            pass

        self.path = AgiEnv.normalize_path(Path(path).expanduser())
        self.files = args["files"]
        self.nfile = args["nfile"]
        AgiManager.args = args
        self.data_out = os.path.join(self.path, "dataframes")
        """
          remove dataframe files from previous run
          """
        try:
            if os.path.exists(self.data_out):
                shutil.rmtree(
                    self.data_out, ignore_errors=False, onerror=AgiManager.onerror
                )
            os.makedirs(self.data_out, exist_ok=True)
        except Exception as e:
            print(f"warning issue while trying to remove directory: {e}")

        return

    def build_distribution(self):
        """build_distrib: to provide the list of files per planes (level1) and per workers (level2)
        the level 1 has been think to prevent that à job that requires all the output-data of a plane have to wait for another
        my_code_worker which would have collapse the overall performance

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
            workers_chunks = AGI.make_chunks(
                len(planes_partition), planes_partition_size, self.verbose, threshold=12
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
                            .head(self.nfile)
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
        if self.data_source == "file":
            path = AgiEnv.normalize_path(self.path)
            home_dir = Path.home()

            # Assuming 'self.path' is the base directory and 'self.files' is the pattern for the files you're interested in
            self.logs_ivq = {
                str(f.relative_to(home_dir)): os.path.getsize(f) // 1000
                for f in Path(self.path).rglob(self.files)
                if f.is_file()
            }

            if not self.logs_ivq:
                raise FileNotFoundError(
                    f"Error in make_chunk: no files found with Path('{self.path}').rglob('{self.files}')"
                )

            # Convert dict_items to a list of tuples before creating a Polars DataFrame
            df = pl.DataFrame(list(self.logs_ivq.items()), schema=["files", "size"])

        elif self.data_source == "hawk":
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
        df = df.group_by("id_plane").head(self.nfile)

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