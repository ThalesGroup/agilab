from __future__ import annotations

from pathlib import Path

import pytest

from agi_env import AgiEnv


@pytest.fixture(autouse=True)
def reset_agienv_singleton():
    """Keep singleton state from leaking across tests."""
    AgiEnv.reset()
    yield
    AgiEnv.reset()


@pytest.fixture(autouse=True)
def isolate_home_for_root_tests(tmp_path, monkeypatch):
    """Keep runner-local ~/.agilab state from leaking into root test imports."""
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("AGI_CLUSTER_ENABLED", raising=False)
    monkeypatch.delenv("AGI_CLUSTER_SHARE", raising=False)
    monkeypatch.delenv("AGI_SHARE_DIR", raising=False)
    monkeypatch.delenv("APPS_REPOSITORY", raising=False)
    monkeypatch.delenv("AGILAB_APPS_REPOSITORY", raising=False)
    monkeypatch.delenv("APP_DEFAULT", raising=False)

    share_dir = fake_home / ".local" / "share" / "agilab"
    share_dir.mkdir(parents=True, exist_ok=True)
    repo_agilab_dir = (Path(__file__).resolve().parents[1] / "src" / "agilab").resolve()
    (share_dir / ".agilab-path").write_text(str(repo_agilab_dir) + "\n", encoding="utf-8")
