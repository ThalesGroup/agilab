import sys
from pathlib import Path

ROOT = Path(__file__).resolve()
CORE_NODE = ROOT.parents[3] / "core/node/src"
APP_SRC = ROOT.parents[1] / "src"
for candidate in (CORE_NODE, APP_SRC):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from agi_node.polars_worker.polars_worker import PolarsWorker
from mycode_worker import MycodeWorker


def test_worker_inherits_polars():
    assert issubclass(MycodeWorker, PolarsWorker)


def test_worker_instance_is_polars():
    worker = MycodeWorker()
    assert isinstance(worker, PolarsWorker)
