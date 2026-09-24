"""Local deployment failures surface missing dependencies and retain safe copies."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agi_cluster.agi_distributor.deployment import deployment_local_support as deployment


@pytest.mark.parametrize("failure", [None, PermissionError("directory locked")])
def test_posix_removal_never_invokes_windows_command(monkeypatch, tmp_path, failure):
    target = tmp_path / "worker-env"
    target.mkdir()
    remove = Mock(side_effect=failure)
    command = Mock(side_effect=AssertionError("must not run cmd on POSIX"))
    monkeypatch.setattr(deployment, "shutil", SimpleNamespace(rmtree=remove))
    monkeypatch.setattr(deployment, "subprocess", SimpleNamespace(run=command))
    with pytest.raises(OSError, match="directory locked" if failure else "Failed to remove"):
        deployment._force_remove(target, os_name="posix")
    assert target.is_dir()
    command.assert_not_called()


def test_windows_removal_fallback_receives_only_exact_target(monkeypatch, tmp_path):
    target = tmp_path / "worker env"
    target.mkdir()
    monkeypatch.setattr(deployment, "shutil", SimpleNamespace(rmtree=Mock(side_effect=PermissionError("locked"))))
    command = Mock()
    monkeypatch.setattr(deployment, "subprocess", SimpleNamespace(run=command))
    log = Mock()
    deployment._force_remove(target, os_name="nt", env_logger=log)
    command.assert_called_once_with(["cmd", "/c", "rmdir", "/s", "/q", str(target)], check=False)
    log.warn.assert_called_once()


def test_removal_symlink_unlinks_only_link_not_target(monkeypatch, tmp_path):
    target = tmp_path / "user-data"
    target.mkdir()
    marker = target / "preserve.txt"
    marker.write_text("preserve")
    link = tmp_path / "venv-link"
    link.symlink_to(target, target_is_directory=True)
    rmtree = Mock(side_effect=AssertionError("must not recursively remove linked target"))
    monkeypatch.setattr(deployment, "shutil", SimpleNamespace(rmtree=rmtree))
    deployment._force_remove(link)
    assert not link.exists()
    assert marker.read_text() == "preserve"
    rmtree.assert_not_called()


@pytest.mark.parametrize("missing_distributions,missing_modules", [(("package-a",), ()), ((), ("module_a",)), (("package-a",), ("module_a",))])
def test_post_install_dependency_failure_names_unready_contract(monkeypatch, tmp_path, missing_distributions, missing_modules):
    monkeypatch.setattr(deployment, "_project_venv_dependency_failures", lambda *_args, **_kwargs: (missing_distributions, missing_modules))
    with pytest.raises(RuntimeError, match="declared worker dependencies") as raised:
        deployment._require_project_venv_dependencies(tmp_path, {}, environment_name="worker", python_version="3.13")
    message = str(raised.value)
    assert ("missing distributions: package-a" in message) is bool(missing_distributions)
    assert ("missing modules: module_a" in message) is bool(missing_modules)
    assert "Re-run Deploy workers" in message


@pytest.mark.parametrize("extension", [".py", ".so", ".pyd", ".dylib", ".cpython-313-darwin.so", ".cp313-win_amd64.pyd"])
def test_worker_import_probe_accepts_supported_module_artifacts(tmp_path, extension):
    (tmp_path / ("module_a" + extension)).write_bytes(b"probe only; never imported")
    assert deployment._module_available_on_root(tmp_path, "module_a")
    assert not deployment._module_available_on_root(tmp_path, "missing")


def test_worker_import_probe_fails_closed_on_native_scan_error(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "glob", Mock(side_effect=OSError("unreadable native directory")))
    assert not deployment._module_available_on_root(tmp_path, "module_a")


@pytest.mark.parametrize("text,expected", [
    ("invalid [toml", None), ("[project]\nname='demo'\n", ()),
    ("[project]\ndependencies=['numpy>=2', 'pandas']\n", ("numpy>=2", "pandas")),
])
def test_dependency_read_cache_retains_parse_failure_or_declared_sequence(monkeypatch, tmp_path, text, expected):
    path = tmp_path / "pyproject.toml"
    path.write_text(text)
    monkeypatch.setattr(deployment, "_PYPROJECT_DEPENDENCY_CACHE", {})
    assert deployment._pyproject_dependency_strings(path) == expected
    # A cached result avoids re-reading identical stat identity, including failure.
    monkeypatch.setattr(Path, "read_text", Mock(side_effect=AssertionError("unexpected second read")))
    assert deployment._pyproject_dependency_strings(path) == expected


def test_missing_pyproject_is_not_an_empty_dependency_contract(tmp_path):
    assert deployment._pyproject_dependency_strings(tmp_path / "missing.toml") is None


def test_failed_resource_copy_never_publishes_success_stamp(monkeypatch, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "resource.txt").write_text("version one")
    destination = tmp_path / "destination"
    copytree = Mock(side_effect=OSError("disk full"))
    proxy = SimpleNamespace(**{key: getattr(deployment.shutil, key) for key in dir(deployment.shutil)})
    proxy.copytree = copytree
    monkeypatch.setattr(deployment, "shutil", proxy)
    stamp = Mock()
    monkeypatch.setattr(deployment, "_write_deploy_copy_stamp", stamp)
    with pytest.raises(OSError, match="disk full"):
        deployment._copy_package_resources(source, destination)
    stamp.assert_not_called()
    assert (source / "resource.txt").read_text() == "version one"


def test_uv_source_map_ignores_non_local_or_malformed_entries(tmp_path):
    path = tmp_path / "pyproject.toml"
    path.write_text('''[tool.uv.sources]
valid-package = { path = "../local project" }
remote = { git = "https://example.invalid/repo.git" }
blank = { path = "" }
invalid = "not a table"
''')
    assert deployment._local_uv_source_projects(path) == {
        "valid-package": (tmp_path / "../local project").resolve()}
