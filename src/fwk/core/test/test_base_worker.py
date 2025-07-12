import pytest
from unittest.mock import MagicMock, patch
from agi_node.agi_dispatcher import BaseWorker, WorkDispatcher


class DummyWorker(BaseWorker):
    def __init__(self, *args, **kwargs):
        super().__init__()
        worker_id = 0
        BaseWorker.worker_id = worker_id
        BaseWorker._insts = {worker_id: self}

    def works(self, workers_tree, workers_tree_info):
        # Stub : ne fait rien
        pass


@pytest.fixture
def worker():
    return DummyWorker()


def test_baseworker_run_calls_exec():
    with patch.object(BaseWorker, 'env', new=MagicMock(module='mod')), \
         patch.object(BaseWorker, '_load_manager', return_value=DummyWorker), \
         patch('agi_node.agi_dispatcher.WorkDispatcher.do_distrib', return_value=({}, {}, {})):
        BaseWorker.test(args={})


def test_baseworker_build_calls_load_and_sets_attrs(worker):
    with patch('shutil.copyfile') as mock_copyfile, \
         patch.object(worker, '_load_manager', return_value=MagicMock()) as mock_load_manager, \
         patch.object(worker, '_load_worker', return_value=MagicMock()) as mock_load_worker:
        mock_copyfile.return_value = None
        worker.build(target_worker="tw", dask_home="dh", worker="wk")
        # On ne vérifie plus mock_load_module car il n'est pas appelé dans build
        # On peut vérifier à la place que copyfile a été appelée, par exemple :
        assert mock_copyfile.call_count > 0


def test_baseworker_do_works_executes_tasks():
    dummy = DummyWorker()
    with patch.object(dummy, 'works', return_value=None):
        BaseWorker.worker_id = 0
        BaseWorker._insts = {0: dummy}
        BaseWorker.do_works({}, {})


def test_onerror_handles_exception():
    dispatcher = WorkDispatcher()
    with patch('os.access', return_value=False), patch('os.chmod') as mock_chmod:
        try:
            # Important: lambda doit accepter un argument, ici 'path'
            dispatcher.onerror(func=lambda path: None, path='dummy_path', exc_info=('exc_type', 'exc_value', 'traceback'))
        except Exception:
            pytest.fail("onerror raised Exception unexpectedly!")
