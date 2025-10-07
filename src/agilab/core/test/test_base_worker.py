import pytest
from unittest.mock import patch
from agi_node.agi_dispatcher import BaseWorker, WorkDispatcher

class DummyWorker(BaseWorker):
    def __init__(self, *args, **kwargs):
        super().__init__()
        worker_id = 0
        BaseWorker._worker_id = worker_id
        BaseWorker._insts = {worker_id: self}

    def works(self, workers_tree, workers_tree_info):
        # Stub : ne fait rien
        pass


def teardown_function(_fn):
    BaseWorker._worker_id = None
    BaseWorker._insts = {}
    BaseWorker._env = None
    BaseWorker.env = None

def test_baseworker_do_works_executes_tasks():
    dummy = DummyWorker()
    with patch.object(dummy, 'works', return_value=None):
        BaseWorker._worker_id = 0
        BaseWorker._insts = {0: dummy}
        BaseWorker._do_works({}, {})


def test_onerror_handles_exception():
    dispatcher = WorkDispatcher()
    with patch('os.access', return_value=False), patch('os.chmod') as mock_chmod:
        try:
            # Important: lambda doit accepter un argument, ici 'path'
            dispatcher._onerror(func=lambda path: None, path='dummy_path', exc_info=('exc_type', 'exc_value', 'traceback'))
        except Exception:
            pytest.fail("_onerror raised Exception unexpectedly!")
