"""Numerical equivalence and scoped executor contracts for the pandas worker."""
from pathlib import Path
from types import SimpleNamespace
import sys

import numpy as np
import pandas as pd
import pytest

PROJECT_SRC = Path(__file__).resolve().parents[1] / "src/agilab/apps/builtin/execution_pandas_project/src"
sys.path.insert(0, str(PROJECT_SRC))
from execution_pandas_worker import execution_pandas_worker as worker_module  # noqa: E402


@pytest.mark.parametrize("rows", [0, 1, 17])
@pytest.mark.parametrize("passes", [1, 3])
@pytest.mark.parametrize("stride", [0, 1, 4])
def test_numeric_kernel_matches_vectorized_scores_and_checksum(rows, passes, stride):
    rng = np.random.default_rng(52)
    x, y, signal, weight = (np.ascontiguousarray(rng.normal(size=rows)) for _ in range(4))
    first, last = np.empty(rows), np.empty(rows)
    checksum = worker_module._typed_numeric_score_kernel(x, y, signal, weight, first, last, passes, stride)
    np.testing.assert_allclose(first, np.abs(x * 1.3 - y * .35 + signal * weight), rtol=1e-12)
    np.testing.assert_allclose(last, np.abs(x * (passes + .3) - y * (.35 + (passes - 1) * .05) + signal * weight), rtol=1e-12)
    reference = worker_module._tail_checksum_from_arrays(x, y, signal, weight, pass_count=passes, sample_stride=stride)
    assert checksum == pytest.approx(reference, rel=1e-12, abs=1e-12)


@pytest.mark.parametrize("choice,environment,free_threading,expected", [
    ("thread", "process", False, "threads"),
    ("process", "thread", True, "process"),
    ("auto", "thread", False, "threads"),
    ("auto", "invalid", False, "process"),
    (None, "auto", True, "threads"),
    ("invalid", "process", True, "process"),
])
def test_executor_label_uses_explicit_choice_then_runtime(monkeypatch, choice, environment, free_threading, expected):
    monkeypatch.setenv(worker_module.worker_pool_support.POOL_EXECUTOR_ENV, environment)
    monkeypatch.setattr(worker_module.worker_pool_support, "_free_threading_active", lambda: free_threading)
    assert worker_module._pool_execution_model_label(SimpleNamespace(pool_executor=choice)) == expected


@pytest.mark.parametrize("old_environment", [None, "process"])
@pytest.mark.parametrize("old_label", [None, "serial"])
def test_executor_override_restores_state_after_work_failure(monkeypatch, old_environment, old_label):
    key = worker_module.worker_pool_support.POOL_EXECUTOR_ENV
    if old_environment is None:
        monkeypatch.delenv(key, raising=False)
    else:
        monkeypatch.setenv(key, old_environment)
    worker = SimpleNamespace()
    if old_label is not None:
        worker._execution_model_label = old_label
    with pytest.raises(RuntimeError, match="work failed"):
        with worker_module._pool_executor_context(worker, SimpleNamespace(pool_executor="thread")):
            assert worker_module.os.environ[key] == "thread"
            assert worker_module._execution_model_label(worker) == "threads"
            raise RuntimeError("work failed")
    assert worker_module.os.environ.get(key) == old_environment
    assert getattr(worker, "_execution_model_label", None) == old_label


def test_numeric_input_conversion_materializes_noncontiguous_integer_values():
    series = pd.Series(np.arange(20)[::2])
    result = worker_module._as_contiguous_float64(series)
    assert result.dtype == np.float64
    assert result.flags.c_contiguous
    np.testing.assert_array_equal(result, np.arange(20)[::2])
