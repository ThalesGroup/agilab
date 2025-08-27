# -*- coding: utf-8 -*-
# https://github.com/cython/cython/wiki/enhancements-compilerdirectives
# cython:infer_types True
# cython:boundscheck False
# cython:cdivision True

import getpass
import glob
import os
import re
import shutil
import subprocess
import traceback
import warnings
from datetime import datetime as dt
from pathlib import Path
import logging

from numpy.linalg import norm  # Imported norm
from agi_env import normalize_path
from agi_node.polars_worker import PolarsWorker
from agi_node.agi_dispatcher import BaseWorker

logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")

import polars as pl
from geopy.distance import geodesic


class FlightWorker(PolarsWorker):
    """Class derived from AgiDataWorker"""

    pool_vars = {}

    def preprocess_df(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Preprocess the DataFrame by parsing the date column and creating
        previous coordinate columns. This operation is done once per file.
        """
        df = df.with_columns(
            [
                # Convert date column from string to datetime only once
                pl.col("date")
                .str.strptime(pl.Datetime, format="%Y-%m-%d %H:%M:%S")
                .alias("date"),
                # Create shifted columns for previous latitude and longitude
                pl.col("lat").shift(1).alias("prev_lat"),
                pl.col("long").shift(1).alias("prev_long"),
            ]
        )
        return df

    def calculate_speed(self, new_column_name: str, df: pl.DataFrame) -> pl.DataFrame:
        """
        Compute the speed (in meters) between consecutive coordinate pairs
        and add it to the DataFrame under the provided column name.
        Assumes that the previous coordinate columns are already present.
        """
        df = df.with_columns(
            [
                pl.struct(["prev_lat", "prev_long", "lat", "long"])
                .map_elements(
                    lambda row: (
                        0
                        if row["prev_lat"] is None
                        else geodesic(
                            (row["prev_lat"], row["prev_long"]),
                            (row["lat"], row["long"]),
                        ).meters
                    ),
                    return_dtype=pl.Float64,
                )
                .alias(new_column_name),
            ]
        )
        return df

    def start(self):
        """Initialize global variables and setup paths."""
        global global_vars

        logging.info(f"from: {__file__}")

        if os.name == "nt" and not getpass.getuser().startswith("T0"):
            path = Path(self.args["path"])
            parts = path.parts
            if "Users" in parts:
                index = parts.index("Users") + 2
                path = Path(*parts[index:])
            net_path = normalize_path("\\\\127.0.0.1\\" + str(path))
            try:
                # Your NFS account in order to mount it as net drive on Windows
                cmd = f'net use Z: "{net_path}" /user:your-credentials'
                logging.info(cmd)
                subprocess.run(cmd, shell=True, check=True)
            except Exception as e:
                logging.info(f"Failed to map network drive: {e}")

        # Path to database on symlink Path.home()/data(symlink)
        self.home_rel = (Path("~/") / self.args["path"]).expanduser()
        path = normalize_path(self.home_rel)
        self.data_out = normalize_path(self.home_rel.parent / "dataframe")
        if os.name != "nt":
            self.data_out = self.data_out.replace("\\", "/")

        # Remove dataframe files from previous run
        try:
            shutil.rmtree(self.data_out, ignore_errors=True, onerror=self.onerror)
            os.makedirs(self.data_out, exist_ok=True)
        except Exception as e:
            logging.info(f"Error removing directory: {e}")

        self.args["path"] = path

        if self.verbose > 1:
            logging.info(f"Worker #{self.worker_id} dataframe root path = {self.data_out}")

        if self.verbose > 0:
            logging.info(f"FlightWorker.start on flight_worker {self.worker_id}\n")
        args = self.args

        if args["data_source"] == "file":
            # Implement your file logic
            pass
        else:
            # Implement your HAWK logic
            pass

        self.pool_vars["args"] = self.args
        self.pool_vars["verbose"] = self.verbose
        global_vars = self.pool_vars

    def work_init(self):
        """Initialize work by reading from shared space."""
        global global_vars
        pass

    def pool_init(self, worker_vars):
        """Initialize the pool with worker variables.

        Args:
            worker_vars (dict): Variables specific to the worker.

        """
        global global_vars
        global_vars = worker_vars

    def work_pool(self, file):
        """Parse IVQ log files.

        Args:
            file (str): The log file to parse.

        Returns:
            pl.DataFrame: Parsed data.
        """
        global global_vars

        args = global_vars["args"]
        verbose = global_vars["verbose"]
        data_source = global_vars["args"]["data_source"]

        prefix = "~/"
        if data_source == "file":
            if os.name != "nt":
                file = os.path.normpath(os.path.expanduser(prefix + file)).replace(
                    "\\", "/"
                )
            else:
                file = normalize_path(os.path.expanduser(prefix + file))

            if not Path(file).is_file():
                raise FileNotFoundError(f"FlightWorker.work_pool({file})\n")

        # Read the CSV file using Polars.
        df = pl.read_csv(file)

        # If the first column is redundant (e.g. named "Unnamed: 0"), drop it.
        if df.columns and (df.columns[0].startswith("Unnamed") or df.columns[0] == ""):
            df = df.drop(df.columns[0])

        # Preprocess the DataFrame (date parsing, cleaning, etc.)
        df = self.preprocess_df(df)

        # Create previous coordinate columns if they are not already present.
        # This assumes "lat" and "long" are valid column names.
        if "lat" in df.columns and "long" in df.columns:
            df = df.with_columns([
                pl.col("lat").shift(1).alias("prev_lat"),
                pl.col("long").shift(1).alias("prev_long"),
            ])

        # Calculate speed using the existing calculate_speed function.
        df = self.calculate_speed("speed", df)
        return df

    def work_done(self, worker_df):
        """Concatenate dataframe if any and save the results.

        Args:
            worker_df (pl.DataFrame): Output dataframe for one plane.

        """
        if worker_df.is_empty():
            return

        os.makedirs(self.data_out, exist_ok=True)

        # Process each plane separately
        for plane in worker_df.select(pl.col("aircraft")).unique().to_series():
            plane_df = worker_df.filter(pl.col("aircraft") == plane).sort("date")

            # Create (or replace) "worker_id" from "aircraft":
            plane_df = plane_df.with_columns(pl.col("aircraft").alias("worker_id"))

            try:
                if self.args["output_format"] == "parquet":
                    filename = (Path(self.data_out) / str(plane)).with_suffix(".parquet")
                    # Ensure that the "date" column is present and correctly typed.
                    # You might want to cast it to a datetime type if needed.
                    plane_df.write_parquet(str(filename))
                elif self.args["output_format"] == "csv":
                    timestamp = dt.now().strftime("%Y-%m-%d_%H-%M-%S")
                    filename = f"{self.data_out}/{str(plane)+'_'+timestamp}.csv"
                    plane_df.write_csv(str(filename))
                if self.verbose > 0:
                    logging.info(f"Saved dataframe for plane {plane} with shape {plane_df.shape} in {filename}")
            except Exception as e:
                logging.info(traceback.format_exc())
                logging.info(f"Error saving dataframe for plane {plane}: {e}")

    def stop(self):
        try:
            """Finalize the worker by listing saved dataframes."""
            files = glob.glob(os.path.join(self.data_out, "**"), recursive=True)
            df_files = [f for f in files if re.search(r"\.(csv|parquet)$", f)]
            n_df = len(df_files)
            if self.verbose > 0:
                logging.info(f"FlightWorker.worker_end - {n_df} dataframes:")
                for f in df_files:
                    logging.info('\t' + str(Path(f)))
                if not n_df:
                    logging.info("No dataframe created")

        except Exception as err:
            logging.info(f"Error while trying to find dataframes: {err}")

        # call the base class stop()
        super().stop()