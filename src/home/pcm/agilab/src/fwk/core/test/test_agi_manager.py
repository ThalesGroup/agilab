import pytest
import sys
from pathlib import Path
core_src = str(Path(__file__).parent.parent / 'src')
sys.path.insert(0, core_src)

from agi_core.managers.agi_manager import AgiManager


def dummy_function(x):
    return x


def test_convert_functions_to_names():
    # Create a sample nested structure containing functions and other types.
    sample_structure = {
        'list_with_funcs': [
            lambda x: x,  # This lambda function should be converted to "<lambda>"
            dummy_function  # This should be converted to "dummy_function"
        ],
        'tuple_with_funcs': (
            sum,  # Built-in sum should be converted to "sum"
            max  # Built-in max should be converted to "max"
        ),
        'simple_values': {
            'a_string': 'hello',
            'a_number': 123
        }
    }

    # Use the method to convert functions to names.
    converted = AgiManager.convert_functions_to_names(sample_structure)

    # Verify that the functions have been replaced by their names.
    assert converted['list_with_funcs'][0] == "<lambda>"
    assert converted['list_with_funcs'][1] == "dummy_function"
    assert converted['tuple_with_funcs'][0] == "sum"
    assert converted['tuple_with_funcs'][1] == "max"
    assert converted['simple_values']['a_string'] == 'hello'
    assert converted['simple_values']['a_number'] == 123