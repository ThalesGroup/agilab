import os
import warnings
import logging
import asyncio
from pathlib import Path
from typing import Any

from pydantic import BaseModel

# Removed unused imports: Unpack, Literal, validator, conint, confloat

from agi_env.agi_env import AgiEnv  # Added import for environment-specific checks
from agent_worker import AgentWorker  # Corrected import

logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")


class AgentAppArgs(BaseModel):
    """
    A class representing the arguments for an Agent App.

    Attributes:
        data_dir (str): Relative path to the data directory. Defaults to '~/data/AgentApp'.
    """

    data_dir: str = "~/data/AgentApp"  # Added a default attribute


class AgentAppWorker(AgiAgentWorker):
    """Class derived from AgiAgentWorker."""

    def __init__(self, **args: dict):
        """
        Initialize the AgentAppWorker object.

        Args:
            **args (dict): Keyword arguments to initialize the object.
                - data_dir (str): Relative path to the data directory. Defaults to '~/data/AgentApp'.

        Returns:
            None

        Notes:
            This constructor initializes the AgentAppWorker object with the given arguments,
            sets up the data directory, and initializes necessary attributes.
        """
        super().__init__()  # Initialize the parent class

        # Retrieve 'data_dir' from args or use default
        home_rel = args.get("data_dir", "~/data/AgentApp")

        if env.is_managed_pc:
            home_rel = home_rel.replace("~", "~/MyApp")

        path_abs = Path(home_rel).expanduser()
        self.path_rel = home_rel

        try:
            if not path_abs.exists():
                logging.info(f"Creating data directory at {path_abs}")
                path_abs.mkdir(parents=True, exist_ok=True)

                # Assuming AGI.env.app_abs is defined in AgiAgentWorker or its parents
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

        # Initialize other attributes
        self.message_queue = asyncio.Queue()
        self.state = {}  # Node's state (e.g., routing table)
        self.node_id = args.get(
            "node_id", "default_node_id"
        )  # Set a default or retrieve from args

    def worker_init(self) -> None:
        """
        Initialize worker-specific attributes.

        Args:
            None

        Returns:
            None

        Notes:
            Sets up the node ID, message queue, and state.
        """
        if self.verbose > 0:
            logging.info(f"Initializing worker from: {__file__}")

        # Ensure node_id is set; it should be provided in args or set to a default
        if not hasattr(self, "node_id"):
            self.node_id = "default_node_id"
            logging.warning("node_id not provided. Using default 'default_node_id'.")

    def work(self, work: Any) -> None:
        """
        Perform work assigned to the AgentAppWorker.

        Args:
            work (Any): The work task to be performed.

        Returns:
            None

        Notes:
            This method should implement the logic to handle the given work task.
        """
        if self.verbose > 0:
            logging.info(f"Executing work from: {__file__}")

        logging.info(f"Doing work: {work}")
        # Implement the actual work logic here

    def end(self) -> None:
        """
        Ends the process of the AgentAppWorker.

        This method is called when the process is complete.

        Args:
            None

        Returns:
            None

        Notes:
            Prints a message if verbose level is greater than 0 and performs any necessary cleanup.
        """
        if self.verbose > 0:
            logging.info("AgentAppWorker All done!\n")
        super().stop()

    async def send_message(self, target_node: Any, message: str) -> None:
        """
        Sends a message to a target node asynchronously.

        Args:
            target_node (Any): The target node to send the message to.
            message (str): The message to be sent.

        Raises:
            Any exceptions that may occur during the message sending process.
        """
        try:
            await target_node.receive_message(message)
            logging.info(f"Sent message to {target_node.node_id}: {message}")
        except Exception as e:
            logging.error(f"Failed to send message to {target_node.node_id}: {e}")
            raise e

    async def receive_message(self, message: Any) -> None:
        """
        Receive a message and put it in the message queue.

        Args:
            message (Any): The message to be added to the message queue.

        Returns:
            None
        """
        await self.message_queue.put(message)
        logging.info(f"Received message: {message}")

    async def process_messages(self) -> None:
        """
        Asynchronously process messages from a message queue.

        Returns:
            None

        Notes:
            Continuously listens for incoming messages and handles them.
        """
        while True:
            message = await self.message_queue.get()
            logging.info(f"Processing message: {message}")
            await self.handle_message(message)

    async def handle_message(self, message: Any) -> None:
        """
        Handle a message in an asynchronous manner.

        Args:
            message (Any): The message to be handled.

        Returns:
            None

        Notes:
            Implement the logic to handle incoming messages, such as updating state or responding.
        """
        # Implement OLSRv2 message handling logic here
        logging.debug(f"Handling message: {message}")
        pass