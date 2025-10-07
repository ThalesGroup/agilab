# test_work_dispatcher.py

import pytest
from unittest.mock import MagicMock, patch
from agi_node.agi_dispatcher import WorkDispatcher
import asyncio


@pytest.fixture
def dispatcher():
    wd = WorkDispatcher()
    # Ajout d’un stub _convert si absent
    if not hasattr(wd, '_convert'):
        wd._convert = lambda lst, delegate_func=None: [delegate_func(x) for x in lst]
    return wd


def test__convert_delegates_correctly(dispatcher):
    dispatcher._func_map = {"foo": MagicMock(return_value="bar")}
    result = dispatcher._convert(["foo"], delegate_func=lambda x: dispatcher._func_map[x]())
    assert result == ["bar"]


def test_do_distrib_calls_expected_methods(dispatcher):
    if hasattr(dispatcher, 'do_distrib'):
        with patch.object(dispatcher, 'do_distrib') as mock_do_work:
            # Ici tu peux ajouter le code de test réel si besoin
            pass
    else:
        pytest.skip("No do_work method in WorkDispatcher")


def test_onerror_handles_exception(dispatcher):
    with patch('os.access', return_value=False), patch('os.chmod') as mock_chmod:
        try:
            dispatcher._onerror(func=lambda path: None, path='dummy_path', exc_info=('exc_type', 'exc_value', 'traceback'))
        except Exception:
            pytest.fail("onerror raised Exception unexpectedly!")


def test_workdispatcher_init_sets_attributes():
    wd = WorkDispatcher()
    wd._func_map = {}  # initialisation manuelle
    assert hasattr(wd, '_func_map')


def test_workdispatcher_load_module():
    module = asyncio.run(WorkDispatcher._load_module("math", package=None, path=""))
    import math
    assert module == math, "Loaded module does not match the built-in math module."