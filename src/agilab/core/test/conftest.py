from __future__ import annotations

import os
from pathlib import Path

import pytest

from agi_env import AgiEnv


_ORIGINAL_PATH_HOME = Path.home


def _home_from_env() -> Path:
    """Resolve ``Path.home()`` while honouring an overridden ``HOME`` env var.

    On Windows ``Path.home()`` reads ``USERPROFILE``/``HOMEDRIVE``+``HOMEPATH``
    before ``HOME``, which leaks the developer profile into tests that only
    ``monkeypatch.setenv("HOME", ...)``.  We prefer ``HOME`` when set so tests
    stay fully isolated across platforms.
    """

    home = os.environ.get("HOME")
    if home:
        return Path(home)
    return _ORIGINAL_PATH_HOME()


@pytest.fixture(autouse=True)
def isolate_core_test_environment(tmp_path_factory, monkeypatch):
    """Keep core tests independent from developer-local AGILAB state."""

    monkeypatch.setattr(Path, "home", staticmethod(_home_from_env))

    fake_home = tmp_path_factory.mktemp("agilab_fake_home")
    fake_agilab = fake_home / ".agilab"
    fake_agilab.mkdir()
    fake_localappdata = fake_home / "AppData" / "Local"
    fake_localappdata.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("HOMEDRIVE", str(fake_home.drive) if fake_home.drive else "")
    monkeypatch.setenv("HOMEPATH", str(fake_home)[len(fake_home.drive):] if fake_home.drive else str(fake_home))
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
