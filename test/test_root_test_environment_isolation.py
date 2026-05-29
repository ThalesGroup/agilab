from __future__ import annotations

import os
from pathlib import Path


def test_root_tests_patch_path_home_to_isolated_home() -> None:
    fake_home = Path(os.environ["HOME"])

    assert Path.home() == fake_home
    assert os.environ["USERPROFILE"] == str(fake_home)
    assert os.environ["LOCALAPPDATA"] == str(fake_home / "AppData" / "Local")
    assert os.environ["APPDATA"] == str(fake_home / "AppData" / "Roaming")
    assert os.environ["AGI_CLUSTER_SHARE"] == ""
    assert os.environ["AGI_LOCAL_SHARE"] == ""

    env_file = fake_home / ".agilab" / ".env"
    assert env_file.exists()
    assert "AGI_CLUSTER_SHARE=" in env_file.read_text(encoding="utf-8")


def test_root_tests_seed_isolated_agilab_path_markers() -> None:
    fake_home = Path(os.environ["HOME"])
    marker = fake_home / ".local" / "share" / "agilab" / ".agilab-path"
    windows_marker = Path(os.environ["LOCALAPPDATA"]) / "agilab" / ".agilab-path"

    assert marker.exists()
    assert windows_marker.exists()
    assert marker.read_text(encoding="utf-8") == windows_marker.read_text(encoding="utf-8")
