"""Failure contracts for creating local workspace settings at startup."""

from pathlib import Path
import tomllib

import pytest

from agilab.about_page import bootstrap


def test_cluster_disable_refuses_uninspectable_source(tmp_path, monkeypatch):
    target = tmp_path / "apps" / "demo_project" / "app_settings.toml"
    source = tmp_path / "source.toml"
    original = Path.is_file

    def inspect(path):
        if path == source:
            raise PermissionError("source is unreadable")
        return original(path)

    monkeypatch.setattr(Path, "is_file", inspect)
    with pytest.raises(OSError, match="cannot be inspected"):
        bootstrap.disable_cluster_in_app_settings(target, source_settings_path=source)
    assert not target.exists()


def test_cluster_disable_rejects_scalar_table_without_rewriting(tmp_path):
    target = tmp_path / "apps" / "demo_project" / "app_settings.toml"
    target.parent.mkdir(parents=True)
    original = 'cluster = "remote"\n[application]\nname = "preserve"\n'
    target.write_text(original)
    with pytest.raises(ValueError, match="must be a TOML table"):
        bootstrap.disable_cluster_in_app_settings(target)
    assert target.read_text() == original


def test_cluster_disable_seeds_full_source_already_disabled(tmp_path):
    target = tmp_path / "apps" / "demo_project" / "app_settings.toml"
    source = tmp_path / "source.toml"
    source.write_text(
        '[cluster]\ncluster_enabled = false\n[application]\nname = "preserve"\n'
    )
    assert bootstrap.disable_cluster_in_app_settings(
        target, source_settings_path=source
    )
    saved = tomllib.loads(target.read_text())
    for section, value in tomllib.loads(source.read_text()).items():
        assert saved[section] == value
    before = target.stat().st_mtime_ns
    assert not bootstrap.disable_cluster_in_app_settings(target)
    assert target.stat().st_mtime_ns == before


def test_cluster_disable_refuses_missing_source_without_partial_settings(tmp_path):
    target = tmp_path / "apps" / "demo_project" / "app_settings.toml"
    with pytest.raises(FileNotFoundError, match="no longer exist"):
        bootstrap.disable_cluster_in_app_settings(
            target, source_settings_path=tmp_path / "removed.toml"
        )
    assert not target.exists()


def test_confined_settings_reject_symlink_escape(tmp_path):
    app = tmp_path / "apps" / "demo_project"
    app.mkdir(parents=True)
    outside = tmp_path / "private.toml"
    outside.write_text("[cluster]\ncluster_enabled = true\n")
    settings = app / "app_settings.toml"
    settings.symlink_to(outside)
    with pytest.raises(ValueError, match="workspace"):
        bootstrap.disable_cluster_in_app_settings(settings)
    assert tomllib.loads(outside.read_text())["cluster"]["cluster_enabled"] is True
