import os
import sys
import warnings
import logging
from pathlib import Path
from typing import Any, Dict

from pydantic import BaseModel

# Removed unused imports: validator, conint, confloat, Literal, Unpack

warnings.filterwarnings("ignore")

from agim.agim import AgiManager

# Initialize logging configuration
logging.basicConfig(
    level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
)


class AgentAppArgs(BaseModel):
    """
    A class representing the arguments for an Agent App.

    Attributes:
        data_dir (str): Relative path to the data directory. Defaults to '~/data/AgentApp'.
    """

    data_dir: str = "~/data/AgentApp"  # Added a default attribute


class Main(AgiManager):
    """
    A class representing the main application.

    Inherits from AgiManager.

    Attributes:
        worker_vars (Dict[str, Any]): Variables required for initializing the work pool.
    """

    worker_vars: Dict[str, Any] = {}  # Changed from global variables to class attribute

    def __init__(self, **args: Dict[str, Any]):
        """
        Initialize the Main application with the provided arguments.

        Args:
            **args (dict): Keyword arguments to initialize the application.
                - data_dir (str): Relative path to the data directory. Defaults to '~/data/AgentApp'.

        Returns:
            None

        Notes:
            This constructor initializes the Main application with the given arguments, sets the home directory for data storage,
            and performs any necessary setup. Adjusts the home directory if running on a Thales-managed computer.
        """
        super().__init__()  # Initialize the parent class

        # Retrieve 'data_dir' from args or use default
        home_rel = args.get("data_dir", "~/data/AgentApp")

        # Example of adjusting path if running on a Thales-managed computer
        if (
            hasattr(self, "env")
            and hasattr(self.env, "is_managed_pc")
            and self.env.is_managed_pc
        ):
            home_rel = home_rel.replace("~", "~/MyApp")

        path_abs = Path(home_rel).expanduser()
        self.path_rel = str(path_abs)

        try:
            if not path_abs.exists():
                logging.info(f"Creating data directory at {path_abs}")
                path_abs.mkdir(parents=True, exist_ok=True)

                # Example of additional setup: copying default config or data files
                # Replace the following lines with actual setup logic as needed
                # config_src = Path(self.env.app_path) / "default_config.yaml"
                # config_dst = path_abs / "config.yaml"
                # config_src.copy(config_dst)
        except Exception as e:
            logging.error(f"Failed to initialize data directory: {e}")
            raise e  # Re-raise the exception after logging

        # Update args with the absolute directory path
        args["dir_path"] = self.path_rel
        logging.info(f"Application initialized with data directory: {self.path_rel}")

    @staticmethod
    def pool_init(vars: Dict[str, Any]) -> None:
        """
        Initialize the work pool process.

        Args:
            vars (dict): Variables required for initializing the pool.

        Returns:
            None

        Notes:
            Sets the class attribute 'worker_vars' with the provided variables.
        """
        Main.worker_vars = vars
        logging.info("Work pool initialized with provided variables.")

    def perform_work(self) -> None:
        """
        Perform the main work of the application.

        Args:
            None

        Returns:
            None

        Notes:
            Executes the core functionality of the Main application.
        """
        logging.info("Starting main work...")
        # Implement the actual work logic here
        try:
            # Example work process
            result = self.work()
            logging.info(f"Work completed with result: {result}")
        except Exception as e:
            logging.error(f"An error occurred during work: {e}")
            raise e

    def stop(self) -> None:
        """
        Stop the Main application and perform cleanup.

        Args:
            None

        Returns:
            None

        Notes:
            Performs necessary cleanup operations before shutting down the application.
        """
        if hasattr(self, "verbose") and self.verbose > 0:
            print("Main Application All done!\n", end="")
            logging.info("Main application stopped successfully.")
        super().stop()

    def build_distribution(self) -> Any:
        """
        Builds a distribution for workers.

        Returns:
            Any: The distribution structure required for workers.

        Note:
            This function is a method of a class and uses class attributes or methods within its implementation.
        """
        # Implement the distribution logic as required
        # Example placeholder return value
        distribution = {
            "workers_tree": [],
            "workers_tree_info": [],
            "worker_id": "id",
            "number_of_functions": "nb_fct",
            "additional_info": "",
        }
        logging.info("Built distribution for workers.")
        return distribution