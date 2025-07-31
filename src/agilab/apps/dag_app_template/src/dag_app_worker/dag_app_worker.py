import os
import sys
import warnings
import logging
from pathlib import Path
from typing import List, Tuple

from pydantic import BaseModel

# Removed unused imports: validator, conint, confloat

import env  # Added import for environment-specific checks
import py7zr  # Added import for handling .7z archives

from dag_worker import DagWorker  # Corrected import
logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")


class DagArgs(BaseModel):
    """
    A class representing DagArgs.

    Attributes:
        data_dir (str): Relative path to the data directory. Defaults to '~/data/DagApp'.
    """

    data_dir: str = "~/data/DagApp"  # Added a default attribute


class DagAppWorker(DagWorker):
    """
    A class representing a DagAppWorker.

    Inherits from DagWorker.

    Attributes:
        worker_vars (dict): Variables required for initializing the work pool.
    """

    worker_vars: dict = {}  # Changed from global variables to class attribute

    def __init__(self, **args: dict):
        """
        Initialize the DagAppWorker object.

        Args:
            **args (dict): Keyword arguments to initialize the object.
                - data_dir (str): Relative path to the data directory. Defaults to '~/data/DagApp'.

        Returns:
            None

        Notes:
            This constructor initializes the DagAppWorker object with the given arguments, sets the home directory for data storage,
            and performs any necessary setup. Adjusts the home directory if running on a Thales-managed computer.
        """
        super().__init__()  # Initialize the parent class

        # Retrieve 'data_dir' from args or use default
        home_rel = args.get("data_dir", "~/data/DagApp")

        if env.is_managed_pc:
            home_rel = home_rel.replace("~", "~/MyApp")

        path_abs = Path(home_rel).expanduser()
        self.path_rel = home_rel

        try:
            if not path_abs.exists():
                logging.info(f"Creating data directory at {path_abs}")
                path_abs.mkdir(parents=True, exist_ok=True)

                # Assuming AGI.env.app_abs is defined in DagWorker or its parents
                data_src = Path(self.env.app_abs) / "data.7z"
                if not data_src.is_file():
                    logging.error(f"Data archive not found at {data_src}")
                    raise FileNotFoundError(f"Data archive not found at {data_src}")

                logging.info(f"Extracting data archive from {data_src} to {path_abs}")
                with py7zr.SevenZipFile(data_src, mode="r") as archive:
                    archive.extractall(path=path_abs)
        except Exception as e:
            logging.error(f"Failed to initialize data directory: {e}")
            raise e  # Re-raise the exception after logging

        # Update args with the absolute directory path
        args["dir_path"] = str(path_abs)

    @staticmethod
    def pool_init(vars: dict) -> None:
        """
        Initialize the work pool process.

        Args:
            vars (dict): Variables required for initializing the pool.

        Returns:
            None
        """
        # Using class attribute instead of global variable
        DagAppWorker.worker_vars = vars
        logging.info("Work pool initialized with provided variables.")

    def work(self) -> None:
        """
        Perform work in the DagAppWorker.

        Args:
            None

        Returns:
            None

        Notes:
            Prints information about the work being done if verbose mode is enabled.
        """
        if self.verbose > 0:
            logging.info(f"Starting work in DagAppWorker from: {__file__}")

        logging.info("Doing work")
        # Implement the actual work logic here
        pass

    def stop(self) -> None:
        """
        Stop the DagAppWorker and perform cleanup.

        Args:
            None

        Returns:
            None
        """
        if self.verbose > 0:
            print("DagAppWorker All done!\n", end="")
            logging.info("DagAppWorker stopped successfully.")
        super().stop()

    def build_distribution(
        self,
    ) -> Tuple[List[List], List[List[Tuple[int, int]]], str, str, str]:
        """
        Builds a distribution for workers.

        Returns:
            tuple: A tuple containing the workers tree, workers tree information, worker ID, number of functions, and an empty string.

        Note:
            This function is a method of a class and uses class attributes or methods within its implementation.
        """
        to_split = 1
        workers_chunks = self.make_chunks(
            to_split, weights=[(i, 1) for i in range(to_split)]
        )

        workers_tree = [
            [
                [self.work, []],  # Work 0 for worker 0
            ],
        ]

        workers_tree_info = [
            [
                ("call 1.1", len(workers_tree[0][0])),  # Work 0 for worker 0
            ],
        ]

        logging.info(f"Built distribution with {to_split} splits.")

        # The last three return values are placeholders. Replace them with actual variables as needed.
        return workers_tree, workers_tree_info, "id", "nb_fct", ""