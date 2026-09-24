"""Cython inference must preserve Python semantics around rebinding and imports."""

import pytest
from agi_node.agi_dispatcher import cython_type_preprocess as preprocess


@pytest.mark.parametrize(
    "source, args, expected",
    [
        ("import cython\ndef run():\n    value = 1.5\n    return value\n", (), 1.5),
        ("# coding: utf-8\n\ndef run():\n    value = 1.5\n    return value\n", (), 1.5),
        (
            "def run():\n    value: float = 1.5\n    value: bool = True\n    result = value * 2\n    return result\n",
            (),
            2,
        ),
        (
            "def run(float):\n    value: float = 1.5\n    result = value * 2\n    return result\n",
            (str,),
            3.0,
        ),
        ("def run():\n    value = 1.5\n    value += 2.5\n    return value\n", (), 4.0),
        (
            "def run():\n    value = 1.5\n    value += int('2')\n    return value\n",
            (),
            3.5,
        ),
        (
            "def run():\n    values = [1.5]\n    values[0] += 2.5\n    return values[0]\n",
            (),
            4.0,
        ),
        (
            "def run():\n    value = 1.5\n    try:\n        raise ValueError('expected')\n    except ValueError as value:\n        return str(value)\n",
            (),
            "expected",
        ),
        (
            "def run(value):\n    match value:\n        case {'count': count, **rest}:\n            return count, rest\n        case [first, *others]:\n            return first, others\n",
            ({"count": 2, "extra": 3},),
            (2, {"extra": 3}),
        ),
    ],
)
def test_rendered_cython_python_retains_original_behavior(source, args, expected):
    rendered, preview = preprocess.preprocess_source(source, filename="worker.py")
    original_namespace = {}
    rendered_namespace = {}
    exec(compile(source, "original_worker.py", "exec"), original_namespace)
    exec(compile(rendered, "rendered_worker.py", "exec"), rendered_namespace)
    assert original_namespace["run"](*args) == expected
    assert rendered_namespace["run"](*args) == expected
    assert preview is not None
    if source.startswith("import cython"):
        assert rendered.count("import cython") == 1
