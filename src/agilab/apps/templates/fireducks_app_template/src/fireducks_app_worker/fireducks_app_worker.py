import logging
import warnings

from fireducks_worker import FireducksWorker
from agi_node import MutableNamespace

logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")


global_vars = None


class FireducksAppWorker(FireducksWorker):
    """Example worker derived from :class:`FireducksWorker`."""

    pool_vars = None

    def start(self):  # pragma: no cover - template hook
        logging.info("from: %s", __file__)
        if not isinstance(self.args, MutableNamespace):
            payload = self.args if isinstance(self.args, dict) else vars(self.args)
            self.args = MutableNamespace(**payload)

    def work_init(self):  # pragma: no cover - template hook
        global global_vars
        pass

    def pool_init(self, worker_vars):  # pragma: no cover - template hook
        global global_vars
        global_vars = worker_vars

    def work_pool(self, x=None):  # pragma: no cover - template hook
        global global_vars
        return super().work_pool(x)

    def work_done(self, worker_df):  # pragma: no cover - template hook
        super().work_done(worker_df)

    def stop(self):  # pragma: no cover - template hook
        logging.info("FireducksAppWorker All done !\n")
        super().stop()
