import sys
from pathlib import Path

APP_SRC = Path(__file__).resolve().parents[1] / "src"
if str(APP_SRC) not in sys.path:
    sys.path.insert(0, str(APP_SRC))

from mycode_worker import MycodeWorker
from agi_node.polars_worker.polars_worker import PolarsWorker


def test_worker_is_polars_subclass():
    assert issubclass(MycodeWorker, PolarsWorker)


def test_worker_instance():
    worker = MycodeWorker()
    assert isinstance(worker, PolarsWorker)
