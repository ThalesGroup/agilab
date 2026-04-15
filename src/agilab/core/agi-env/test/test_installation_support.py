from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

import agi_env.installation_support as installation_support


def test_installation_marker_path_uses_platform_specific_roots(tmp_path: Path):
    home = tmp_path / "home"
    localappdata = tmp_path / "localappdata"

    assert installation_support.installation_marker_path(
        os_name="posix",
        home=home,
    ) == home / ".local/share/agilab/.agilab-path"
    assert installation_support.installation_marker_path(
        os_name="nt",
        localappdata=localappdata,
    ) == localappdata / "agilab/.agilab-path"


def test_read_agilab_installation_marker_logs_invalid_marker(tmp_path: Path):
    marker = tmp_path / ".agilab-path"
    marker.write_text(str(tmp_path / "missing-install"), encoding="utf-8")
    mock_logger = mock.Mock()

    assert installation_support.read_agilab_installation_marker(marker, logger=mock_logger) is None
    assert mock_logger.error.called


def test_read_agilab_installation_marker_logs_permission_and_missing_errors(tmp_path: Path, monkeypatch):
    marker = tmp_path / ".agilab-path"
    marker.write_text("demo\n", encoding="utf-8")
    mock_logger = mock.Mock()
    original_open = Path.open

    def _permission_open(self, *args, **kwargs):
        if self == marker:
            raise PermissionError("denied")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(installation_support.Path, "open", _permission_open, raising=False)
    assert installation_support.read_agilab_installation_marker(marker, logger=mock_logger) is None

    def _missing_open(self, *args, **kwargs):
        if self == marker:
            raise FileNotFoundError("gone")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(installation_support.Path, "open", _missing_open, raising=False)
    assert installation_support.read_agilab_installation_marker(marker, logger=mock_logger) is None
    assert mock_logger.error.call_count >= 2


def test_read_agilab_installation_marker_propagates_unexpected_runtime_bug(tmp_path: Path, monkeypatch):
    install_root = tmp_path / "agilab_install"
    install_root.mkdir()
    marker = tmp_path / ".agilab-path"
    marker.write_text(str(install_root), encoding="utf-8")
    original_exists = installation_support.Path.exists

    def _runtime_exists(self):
        if self == install_root:
            raise RuntimeError("exists bug")
        return original_exists(self)

    monkeypatch.setattr(installation_support.Path, "exists", _runtime_exists, raising=False)

    with pytest.raises(RuntimeError, match="exists bug"):
        installation_support.read_agilab_installation_marker(marker)


def test_read_agilab_installation_marker_returns_false_when_marker_missing(tmp_path: Path):
    marker = tmp_path / ".agilab-path"

    assert installation_support.read_agilab_installation_marker(marker) is False


def test_read_agilab_installation_marker_returns_install_root(tmp_path: Path):
    install_root = tmp_path / "agilab_install"
    install_root.mkdir()
    marker = tmp_path / ".agilab-path"
    marker.write_text(str(install_root), encoding="utf-8")

    assert installation_support.read_agilab_installation_marker(marker) == install_root


def test_locate_agilab_installation_path_prefers_installed_spec(tmp_path: Path):
    installed_root = tmp_path / "site-packages" / "agilab"
    installed_root.mkdir(parents=True)
    (installed_root / "apps").mkdir()
    init_file = installed_root / "__init__.py"
    init_file.write_text("", encoding="utf-8")

    located = installation_support.locate_agilab_installation_path(
        module_file=tmp_path / "ignored" / "agi_env.py",
        find_spec=lambda _name: SimpleNamespace(origin=str(init_file)),
    )

    assert located == installed_root.resolve()


def test_locate_agilab_installation_path_falls_back_to_repo_and_parent(tmp_path: Path):
    repo_root = tmp_path / "repo-root"
    (repo_root / "apps").mkdir(parents=True)
    located = installation_support.locate_agilab_installation_path(
        module_file=repo_root / "x" / "y" / "z" / "w" / "agi_env.py",
        find_spec=lambda _name: None,
    )
    assert located == repo_root

    fallback_root = tmp_path / "fallback" / "agilab"
    (fallback_root / "apps").mkdir(parents=True)
    located = installation_support.locate_agilab_installation_path(
        module_file=fallback_root / "pkg" / "one" / "two" / "agi_env.py",
        find_spec=lambda _name: None,
    )
    assert located == fallback_root
