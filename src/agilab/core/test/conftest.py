from __future__ import annotations

import pytest

from agi_env import AgiEnv


@pytest.fixture(autouse=True)
def reset_agienv_singleton():
    """Keep AgiEnv singleton state from leaking across core tests."""
    AgiEnv.reset()
    yield
    AgiEnv.reset()


@pytest.fixture
def pandas_parquet_io_stub(monkeypatch):
    """Exercise parquet dispatch without requiring pyarrow/fastparquet."""
    import pandas as pd

    def _to_parquet_stub(self, path, *_args, **_kwargs):
        self.to_csv(path, index=False)

    def _read_parquet_stub(path, *_args, **_kwargs):
        return pd.read_csv(path)

    monkeypatch.setattr(pd.DataFrame, "to_parquet", _to_parquet_stub)
    monkeypatch.setattr(pd, "read_parquet", _read_parquet_stub)
