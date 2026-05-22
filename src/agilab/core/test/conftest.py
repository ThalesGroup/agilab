from __future__ import annotations

from pathlib import Path

import pytest

from agi_env import AgiEnv


@pytest.fixture(autouse=True)
def isolate_core_test_environment(tmp_path_factory, monkeypatch):
    """Keep core tests independent from developer-local AGILAB state."""

    fake_home = tmp_path_factory.mktemp("agilab_fake_home")
    fake_agilab = fake_home / ".agilab"
    fake_agilab.mkdir()
    fake_localappdata = fake_home / "AppData" / "Local"
    fake_localappdata.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("LOCALAPPDATA", str(fake_localappdata))
    monkeypatch.setenv("APPDATA", str(fake_home / "AppData" / "Roaming"))
    monkeypatch.delenv("AGI_CLUSTER_ENABLED", raising=False)
    monkeypatch.setenv("AGI_CLUSTER_SHARE", "")
    monkeypatch.setenv("AGI_LOCAL_SHARE", "")
    monkeypatch.delenv("APPS_REPOSITORY", raising=False)
    monkeypatch.delenv("APPS_PATH", raising=False)
    monkeypatch.delenv("AGILAB_LOG_ABS", raising=False)
    monkeypatch.delenv("CLUSTER_CREDENTIALS", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)

    share_dir = fake_home / ".local" / "share" / "agilab"
    share_dir.mkdir(parents=True, exist_ok=True)
    repo_agilab_dir = Path(__file__).resolve().parents[2]
    (share_dir / ".agilab-path").write_text(str(repo_agilab_dir) + "\n", encoding="utf-8")
    (fake_localappdata / "agilab").mkdir(parents=True, exist_ok=True)
    (fake_localappdata / "agilab" / ".agilab-path").write_text(
        str(repo_agilab_dir) + "\n",
        encoding="utf-8",
    )
    (fake_agilab / ".env").write_text(
        "AGI_CLUSTER_SHARE=\nAGI_LOCAL_SHARE=\nAPPS_REPOSITORY=\n",
        encoding="utf-8",
    )

    original_logger = AgiEnv.logger
    AgiEnv.reset()
    AgiEnv.resources_path = fake_agilab
    AgiEnv.envars = {}
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
