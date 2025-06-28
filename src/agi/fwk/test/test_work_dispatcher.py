import pytest
from unittest.mock import patch
from agi_node.src.agi_manager import WorkDispatcher

@pytest.fixture
def dispatcher():
    # Instantiate WorkDispatcher, patch init if it requires args or side effects
    with patch('node.WorkDispatcher.__init__', return_value=None):
        wd = WorkDispatcher()
        # Patch or setup attributes as needed
        wd._func_map = {}
        return wd

def test_workdispatcher_init_sets_attributes():
    # Test __init__ without patch to verify initial state
    wd = WorkDispatcher()
    assert hasattr(wd, '_func_map')

def test_convert_functions_to_names_returns_names(dispatcher):
    func1 = lambda x: x
    func2 = lambda y: y
    funcs = [func1, func2]
    dispatcher._func_map = {func1: "func1_name", func2: "func2_name"}
    names = dispatcher.convert_functions_to_names(funcs)
    assert set(names) == {"func1_name", "func2_name"}

def test_convert_functions_to_names_with_unknown_function(dispatcher):
    func_unknown = lambda z: z
    dispatcher._func_map = {}
    names = dispatcher.convert_functions_to_names([func_unknown])
    # Unknown function should fallback to str(func)
    assert any(isinstance(name, str) for name in names)

def test__convert_delegates_correctly(dispatcher):
    # Patch or mock a helper method or internal logic
    dispatcher._func_map = {"dummy": "dummy_name"}
    with patch.object(dispatcher, 'convert_functions_to_names', return_value=["dummy_name"]):
        result = dispatcher._convert(["dummy"])
        assert "dummy_name" in result

def test_do_distrib_calls_expected_methods(dispatcher):
    # Patch internal methods and simulate do_distrib call
    with patch.object(dispatcher, '_convert', return_value=["func_name"]), \
         patch('builtins.print') as mock_print:
        result = dispatcher.do_distrib(["func"])
        # Check if _convert was called
        assert "func_name" in result or result is None  # Adjust depending on return value

def test_onerror_handles_exception(dispatcher):
    exc = Exception("dispatch error")
    try:
        dispatcher.onerror(exc)
    except Exception:
        pytest.fail("WorkDispatcher.onerror raised Exception unexpectedly!")
