"""Cython preprocessing keeps dynamic Python bindings and async scopes intact."""

import asyncio
import inspect

import pytest
from agi_node.agi_dispatcher import cython_type_preprocess as preprocess


@pytest.mark.parametrize(
    "source,args,expected",
    [
        (
            "def run(value: 'float'):\n    result = value + 1\n    return result\n",
            (2.5,),
            3.5,
        ),
        (
            "import contextlib\ndef run():\n    value = 1.5\n    with contextlib.nullcontext('replacement') as value:\n        return value\n",
            (),
            "replacement",
        ),
        (
            "def run():\n    value = 1.5\n    async def value():\n        return 'async replacement'\n    return value()\n",
            (),
            "async replacement",
        ),
        (
            "async def run():\n    from contextlib import asynccontextmanager\n    @asynccontextmanager\n    async def context():\n        yield 'async value'\n    value = 1.5\n    async with context() as value:\n        return value\n",
            (),
            "async value",
        ),
        (
            "def run(item):\n    value = 1.5\n    match item:\n        case (int(value) | str(value)) as captured:\n            return value, captured\n        case _:\n            return None\n",
            ("dynamic",),
            ("dynamic", "dynamic"),
        ),
        (
            "def run():\n    value = 1.5\n    value += complex(1, 2)\n    return value\n",
            (),
            2.5 + 2j,
        ),
    ],
)
def test_cython_render_preserves_binding_scope_and_runtime_value(
    source, args, expected
):
    rendered, preview = preprocess.preprocess_source(source, filename="worker.py")
    results = []
    for text in (source, rendered):
        namespace = {}
        exec(compile(text, "worker.py", "exec"), namespace)
        result = namespace["run"](*args)
        results.append(asyncio.run(result) if inspect.isawaitable(result) else result)
    assert results == [expected, expected]
    assert preview is not None
