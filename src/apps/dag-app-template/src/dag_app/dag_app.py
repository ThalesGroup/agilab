import os
import sys
import warnings
import logging
from pathlib import Path
from typing import List, Tuple

from pydantic import BaseModel

# Removed unused imports: validator, conint, confloat

from agi_env.agi_env import AgiEnv  # Added import for AgiEnv

# Removed: from pydantic import validator, conint, confloat

from agim.agim import AgiManager

warnings.filterwarnings("ignore")

# Initialize logging configuration
logging.basicConfig(
    level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
)


class DagArgs(BaseModel):
    """
    A class representing DagArgs.

    Attributes:
        data_dir (str): Relative path to the data directory. Defaults to '~/data/DagApp'.
    """

    data_dir: str = "~/data/DagApp"  # Added a default attribute


class DagApp(AgiManager):
    """
    A class representing a DagApp.

    Inherits from AgiManager.

    Attributes:
        args (DagArgs): Arguments passed to the constructor.
    """

    worker_vars: dict = {}  # Changed from global variables to class attribute

    def __init__(self, **args: dict):
        """
        Initialize the DagApp object.

        Args:
            **args (dict): Keyword arguments to initialize the object.
                - data_dir (str): Relative path to the data directory. Defaults to '~/data/DagApp'.

        Returns:
            None

        Notes:
            This constructor initializes the DagApp object with the given arguments, sets the home directory for data storage,
            and performs any necessary setup. Adjusts the home directory if running on a Thales-managed computer.
        """
        super().__init__()  # Initialize the parent class

        # Retrieve 'data_dir' from args or use default
        home_rel = args.get("data_dir", os.path.join("~", "data", "DagApp"))

        if env.is_managed_pc:
            home_rel = home_rel.replace("~", "~/MyApp")

        path_abs = Path(os.path.expanduser(home_rel))
        self.path_rel = home_rel

        try:
            if not path_abs.exists():
                logging.info(f"Creating data directory at {path_abs}")
                path_abs.mkdir(parents=True, exist_ok=True)

                # Assuming AGI.env.app_path is defined in AgiManager or its parents
                data_src = Path(AGI.env.app_path) / "data.7z"
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
        DagApp.worker_vars = vars
        logging.info("Work pool initialized with provided variables.")

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
        workers_chunks = AGI.make_chunks(
            to_split, weights=[(i, 1) for i in range(to_split)]
        )

        workers_tree = [
            [
                [DagApp.work, []],  # Work 0 for worker 0
            ],
        ]

        workers_tree_info = [
            [
                ("call 1.1", len(workers_tree[0][0])),  # Work 0 for worker 0
            ],
        ]

        logging.info(f"Built distribution with {to_split} splits.")

        return workers_tree, workers_tree_info, "id", "nb_fct", ""