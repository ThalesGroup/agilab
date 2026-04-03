from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from agi_env import AgiEnv


REAL_HOME = Path.home().resolve()


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


@pytest.fixture(autouse=True)
def preserve_real_user_state_for_root_tests(tmp_path):
    """
    Root tests, especially Streamlit AppTests, must not leak writes into the
    developer's real ~/.agilab, ~/.local/share/agilab, or ~/export trees.
    """

    tracked_files = [
        REAL_HOME / ".agilab" / ".env",
        REAL_HOME / ".local" / "share" / "agilab" / "app_state.toml",
        REAL_HOME / ".local" / "share" / "agilab" / ".last-active-app",
    ]
    tracked_export_root = REAL_HOME / "export"
    backup_root = tmp_path / "real_user_state_backup"

    for src in tracked_files:
        if not src.exists():
            continue
        dst = backup_root / src.relative_to(REAL_HOME)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    export_snapshots: list[tuple[Path, Path]] = []
    if tracked_export_root.exists():
        for src in tracked_export_root.rglob("AGI_*.py"):
            dst = backup_root / src.relative_to(REAL_HOME)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            export_snapshots.append((src, dst))

    yield

    for src in tracked_files:
        backup = backup_root / src.relative_to(REAL_HOME)
        if backup.exists():
            src.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, src)
        elif src.exists():
            src.unlink()

    if tracked_export_root.exists():
        current_exports = list(tracked_export_root.rglob("AGI_*.py"))
        for src in current_exports:
            backup = backup_root / src.relative_to(REAL_HOME)
            if not backup.exists():
                src.unlink()

    for src, backup in export_snapshots:
        src.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup, src)
