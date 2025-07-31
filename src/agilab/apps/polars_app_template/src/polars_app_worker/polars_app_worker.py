import warnings
from agi_env import AgiEnv, normalize_path
from agi_node.polars_worker import PolarsWorker
logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")


class PolarsAppWorker(PolarsWorker):
    """class derived from AgiDataWorker"""

    pool_vars = None

    def start(self):
        """init"""
        logging.info(f"from: {__file__}")

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
        Stop the PolarsAppWorker and print a message if verbose is greater than 0.

        No Args.

        No Returns.
        """
        logging.info("PolarsAppWorker All done !\n", end="")
        """
        pools_done
        """
        super().stop()