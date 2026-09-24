"""Project cloning retains data and reports incomplete LFS or link operations."""
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agi_env.project import project_clone_support as clone


@pytest.mark.parametrize("result", [
    SimpleNamespace(returncode=1, stdout="", stderr="server unavailable"),
    SimpleNamespace(returncode=0, stdout="", stderr=""),
])
def test_lfs_pull_failure_or_unresolved_payload_never_claims_materialization(tmp_path, monkeypatch, result):
    (tmp_path / ".git").mkdir()
    dataset = tmp_path / "app_project" / "dataset.7z"
    dataset.parent.mkdir()
    dataset.write_bytes(clone.GIT_LFS_POINTER_SIGNATURE + b"\noid sha256:fixture\nsize 123\n")
    run = Mock(return_value=result)
    monkeypatch.setattr(clone.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="Failed to materialize|unresolved dataset pointers remain"):
        clone._ensure_git_lfs_dataset_payloads(dataset.parent, Mock())
    assert dataset.read_bytes().startswith(clone.GIT_LFS_POINTER_SIGNATURE)
    assert run.call_args.args[0][-1] == "--include=app_project/dataset.7z"
    assert run.call_args.kwargs["timeout"] == clone.GIT_LFS_PULL_TIMEOUT_SECONDS


@pytest.mark.parametrize("directory,error", [(False, FileExistsError), (False, OSError), (True, OSError)])
def test_confined_clone_link_failure_uses_directory_fallback_only(tmp_path, monkeypatch, directory, error):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    target = source / ("alpha" if directory else "alpha.py")
    if directory:
        target.mkdir()
    else:
        target.write_text("value = 1")
    link = source / "alias"
    link.symlink_to(target, target_is_directory=directory)
    symlink = Mock(side_effect=error("link unavailable"))
    monkeypatch.setattr(clone, "os", SimpleNamespace(path=SimpleNamespace(relpath=os.path.relpath), symlink=symlink))
    fallback = Mock(return_value=True)
    clone._clone_confined_symlink(
        link, destination / "alias", source_root=source, dest_root=destination,
        rename_map={"alpha": "beta"}, link_directory_fn=fallback,
    )
    expected_target = destination / ("beta" if directory else "beta.py")
    symlink.assert_called_once_with(
        os.path.relpath(expected_target, start=destination), destination / "alias",
        target_is_directory=directory,
    )
    if directory:
        fallback.assert_called_once_with(expected_target, destination / "alias")
    else:
        fallback.assert_not_called()


def test_unremovable_project_symlink_preserves_link_and_skips_copy(tmp_path, monkeypatch):
    source, destination = tmp_path / "source", tmp_path / "destination"
    project = source / "demo_project"
    project.mkdir(parents=True)
    (project / "payload").write_text("source")
    destination.mkdir()
    missing = destination / "missing"
    link = destination / "demo_project"
    link.symlink_to(missing, target_is_directory=True)
    original = Path.unlink
    def unlink(path, *args, **kwargs):
        if path == link:
            raise OSError("locked link")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", unlink)
    copy = Mock()
    monkeypatch.setattr(clone.shutil, "copytree", copy)
    logger = Mock()
    clone.copy_existing_projects(
        source, destination, ensure_dir_fn=lambda path: path.mkdir(parents=True, exist_ok=True), logger=logger
    )
    assert link.is_symlink()
    assert not missing.exists()
    copy.assert_not_called()
    logger.warning.assert_called_once()


def test_file_rename_changes_only_matching_stem():
    assert clone._renamed_relative_path(Path("alpha/sub/alpha.py"), {"alpha": "beta"}, file_target=True) == Path("beta/sub/beta.py")
