from pathlib import Path
from unittest import mock

import pytest

import agi_env.share_mount_support as share_mount_support


def test_read_cluster_setting_handles_empty_and_invalid_files(tmp_path: Path):
    settings = tmp_path / "app_settings.toml"
    settings.write_text("", encoding="utf-8")
    assert share_mount_support._read_cluster_setting(settings) is None

    settings.write_text("[cluster]\ncluster_enabled = true\n", encoding="utf-8")
    assert share_mount_support._read_cluster_setting(settings) is True

    settings.write_text("[cluster\ncluster_enabled = true\n", encoding="utf-8")
    assert share_mount_support._read_cluster_setting(settings) is None


def test_read_cluster_setting_propagates_unexpected_runtime_bug(tmp_path: Path, monkeypatch):
    settings = tmp_path / "app_settings.toml"
    settings.write_text("[cluster]\ncluster_enabled = true\n", encoding="utf-8")
    original_is_file = Path.is_file

    def _runtime_is_file(self):
        if self == settings:
            raise RuntimeError("is_file bug")
        return original_is_file(self)

    monkeypatch.setattr(Path, "is_file", _runtime_is_file, raising=False)

    with pytest.raises(RuntimeError, match="is_file bug"):
        share_mount_support._read_cluster_setting(settings)


def test_cluster_enabled_from_settings_handles_lookup_oserror_and_env_fallback(monkeypatch):
    monkeypatch.setenv("AGI_CLUSTER_ENABLED", "true")

    enabled = share_mount_support.cluster_enabled_from_settings(
        is_worker_env=False,
        resolve_workspace_settings_fn=lambda: (_ for _ in ()).throw(OSError("workspace unavailable")),
        find_source_settings_fn=lambda: None,
        envars={},
    )

    assert enabled is True


def test_cluster_enabled_from_settings_propagates_unexpected_lookup_bug():
    with pytest.raises(RuntimeError, match="lookup bug"):
        share_mount_support.cluster_enabled_from_settings(
            is_worker_env=False,
            resolve_workspace_settings_fn=lambda: (_ for _ in ()).throw(RuntimeError("lookup bug")),
            find_source_settings_fn=lambda: None,
            envars={},
        )


def test_is_usable_dir_handles_oserror_and_propagates_runtime_bug(monkeypatch, tmp_path: Path):
    share_dir = tmp_path / "share"
    share_dir.mkdir()

    monkeypatch.setattr(share_mount_support.os, "listdir", lambda _path: (_ for _ in ()).throw(OSError("denied")))
    assert share_mount_support._is_usable_dir(str(share_dir)) is False

    monkeypatch.setattr(
        share_mount_support.os,
        "listdir",
        lambda _path: (_ for _ in ()).throw(RuntimeError("listdir bug")),
    )
    with pytest.raises(RuntimeError, match="listdir bug"):
        share_mount_support._is_usable_dir(str(share_dir))


def test_fstab_bind_source_for_target_handles_oserror_and_parses_bind(monkeypatch):
    bind_text = "/src /target none bind 0 0\n"
    mock_open = mock.mock_open(read_data=bind_text)
    monkeypatch.setattr(share_mount_support, "open", mock_open, raising=False)
    assert share_mount_support._fstab_bind_source_for_target("/target") == "/src"

    def _permission_open(*_args, **_kwargs):
        raise PermissionError("no access")

    monkeypatch.setattr(share_mount_support, "open", _permission_open, raising=False)
    assert share_mount_support._fstab_bind_source_for_target("/target") is None

