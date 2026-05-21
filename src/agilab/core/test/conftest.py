from __future__ import annotations

from pathlib import Path

import pytest

from agi_env import AgiEnv


@pytest.fixture(autouse=True)
def isolate_core_test_environment(tmp_path, monkeypatch):
    """Keep core tests independent from developer-local AGILAB state."""

    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("AGI_CLUSTER_ENABLED", raising=False)
    monkeypatch.delenv("AGI_CLUSTER_SHARE", raising=False)
    monkeypatch.delenv("APPS_REPOSITORY", raising=False)
    monkeypatch.delenv("CLUSTER_CREDENTIALS", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)

    share_dir = fake_home / ".local" / "share" / "agilab"
    share_dir.mkdir(parents=True, exist_ok=True)
    repo_agilab_dir = Path(__file__).resolve().parents[2]
    (share_dir / ".agilab-path").write_text(str(repo_agilab_dir) + "\n", encoding="utf-8")

    original_logger = AgiEnv.logger
    AgiEnv.reset()
    yield
    AgiEnv.logger = original_logger
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
