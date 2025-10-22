from mycode_worker import MycodeWorker
from agi_node.polars_worker.polars_worker import PolarsWorker


def test_worker_is_polars_subclass():
    assert issubclass(MycodeWorker, PolarsWorker)


def test_worker_instance():
    worker = MycodeWorker()
    assert isinstance(worker, PolarsWorker)
