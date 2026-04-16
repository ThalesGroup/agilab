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


def test_cluster_enabled_from_settings_prefers_worker_env_and_settings_value(tmp_path: Path):
    settings = tmp_path / "app_settings.toml"
    settings.write_text("[cluster]\ncluster_enabled = false\n", encoding="utf-8")

    assert share_mount_support.cluster_enabled_from_settings(
        is_worker_env=True,
        resolve_workspace_settings_fn=lambda: settings,
        find_source_settings_fn=lambda: None,
        envars={"AGI_CLUSTER_ENABLED": "true"},
        environ={"AGI_CLUSTER_ENABLED": "true"},
    ) is True

    assert share_mount_support.cluster_enabled_from_settings(
        is_worker_env=False,
        resolve_workspace_settings_fn=lambda: settings,
        find_source_settings_fn=lambda: None,
        envars={"AGI_CLUSTER_ENABLED": "true"},
        environ={"AGI_CLUSTER_ENABLED": "true"},
    ) is False


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


def test_share_mount_support_path_and_mount_helpers(tmp_path: Path, monkeypatch):
    assert share_mount_support._parse_bool(1) is True
    assert share_mount_support._parse_bool(0) is False
    assert share_mount_support._abs_path("cluster/share", home_path=tmp_path) == str(
        (tmp_path / "cluster" / "share").resolve(strict=False)
    )

    existing = tmp_path / "existing"
    existing.mkdir()
    assert share_mount_support._same_storage(str(existing), str(existing)) is True
    assert share_mount_support._same_storage(str(existing), str(tmp_path / "missing")) is False

    fstab_text = "# comment\nsrc-only /skip\nrelative/source /target none bind,rw 0 0\n"
    monkeypatch.setattr(share_mount_support, "open", mock.mock_open(read_data=fstab_text), raising=False)
    assert share_mount_support._fstab_bind_source_for_target("/target") == "relative/source"

    share_dir = tmp_path / "cluster"
    share_dir.mkdir()
    mountinfo_text = f"24 23 0:21 / {share_dir} rw - bind none rw\n"
    monkeypatch.setattr(share_mount_support, "_is_usable_dir", lambda _path: True)
    monkeypatch.setattr(share_mount_support, "open", mock.mock_open(read_data=mountinfo_text), raising=False)
    assert share_mount_support.is_mounted(str(share_dir), home_path=tmp_path) is True

    def _missing_mountinfo(*_args, **_kwargs):
        raise FileNotFoundError("no mountinfo")

    monkeypatch.setattr(share_mount_support, "open", _missing_mountinfo, raising=False)
    assert share_mount_support.is_mounted(str(share_dir), home_path=tmp_path) is True

    monkeypatch.setattr(
        share_mount_support,
        "open",
        mock.mock_open(read_data="24 23 0:21 / /different rw - bind none rw\n"),
        raising=False,
    )
    monkeypatch.setattr(
        share_mount_support,
        "_fstab_bind_source_for_target",
        lambda _target: "relative/source",
    )
    monkeypatch.setattr(
        share_mount_support,
        "_same_storage",
        lambda left, right: left == str(share_dir) and right == str((tmp_path / "relative" / "source").resolve(strict=False)),
    )
    assert share_mount_support.is_mounted(str(share_dir), home_path=tmp_path) is True


def test_resolve_share_path_fail_fast_and_local_fallback(tmp_path: Path, monkeypatch):
    env_path = tmp_path / ".env"

    with pytest.raises(RuntimeError, match="distinct from AGI_LOCAL_SHARE"):
        share_mount_support.resolve_share_path(
            cluster_share="shared",
            local_share="shared",
            cluster_enabled=True,
            env_path=env_path,
            home_path=tmp_path,
        )

    monkeypatch.setattr(share_mount_support, "is_mounted", lambda _path, home_path: True)
    assert (
        share_mount_support.resolve_share_path(
            cluster_share="clustershare",
            local_share="localshare",
            cluster_enabled=True,
            env_path=env_path,
            home_path=tmp_path,
        )
        == "clustershare"
    )

    monkeypatch.setattr(share_mount_support, "is_mounted", lambda _path, home_path: False)
    with pytest.raises(RuntimeError, match="requires AGI_CLUSTER_SHARE to be mounted and writable"):
        share_mount_support.resolve_share_path(
            cluster_share="clustershare",
            local_share="localshare",
            cluster_enabled=True,
            env_path=env_path,
            home_path=tmp_path,
        )

    assert (
        share_mount_support.resolve_share_path(
            cluster_share="clustershare",
            local_share="localshare",
            cluster_enabled=False,
            env_path=env_path,
            home_path=tmp_path,
        )
        == "localshare"
    )
