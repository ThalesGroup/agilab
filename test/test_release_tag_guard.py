"""Release source guards exercise real lightweight and annotated Git tags."""
from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest


_SPEC = importlib.util.spec_from_file_location(
    "release_tag_guard", Path(__file__).resolve().parents[1] / "tools" / "release" / "release_tag_guard.py"
)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
validate_release_tag = _MODULE.validate_release_tag


@pytest.fixture
def tag_repo(tmp_path: Path) -> tuple[Path, str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update({
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_AUTHOR_NAME": "Release Guard Test", "GIT_AUTHOR_EMAIL": "guard@example.invalid",
        "GIT_COMMITTER_NAME": "Release Guard Test", "GIT_COMMITTER_EMAIL": "guard@example.invalid",
    })
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-c", "core.hooksPath=" + os.devnull, "-C", str(tmp_path), *args],
            env=env, text=True, capture_output=True, check=True,
        ).stdout.strip()
    git("init")
    git("commit", "--allow-empty", "--no-gpg-sign", "-m", "first publication source")
    first = git("rev-parse", "HEAD")
    git("tag", "v2026.10.05_1", first)
    git("tag", "-a", "--no-sign", "v2026.10.05_2", first, "-m", "annotated publication source")
    git("commit", "--allow-empty", "--no-gpg-sign", "-m", "later main")
    return tmp_path, first, git("rev-parse", "HEAD")


@pytest.mark.parametrize("tag", ["v2026.10.05_1", "refs/tags/v2026.10.05_1", "2026.10.05_1", "v2026.10.05_2"])
def test_accepts_exact_release_source_and_dereferences_annotated_tags(tag_repo, tag):
    repo, first, _ = tag_repo
    assert validate_release_tag(repo, tag, first)["release_commit"] == first


def test_rejects_missing_release_tag_before_publication(tag_repo):
    repo, first, _ = tag_repo
    with pytest.raises(ValueError, match="missing"):
        validate_release_tag(repo, "v2026.10.05_3", first)


def test_rejects_tag_pointing_to_another_commit(tag_repo):
    repo, _, later = tag_repo
    with pytest.raises(ValueError, match="must not be moved"):
        validate_release_tag(repo, "v2026.10.05_1", later)


@pytest.mark.parametrize("tag", ["vbad^", "vbad..tag", "refs/tags/vbad:tag"])
def test_rejects_invalid_tag_references(tag_repo, tag):
    repo, first, _ = tag_repo
    with pytest.raises(ValueError, match="Invalid release tag"):
        validate_release_tag(repo, tag, first)


def test_requires_complete_expected_commit(tag_repo):
    repo, first, _ = tag_repo
    with pytest.raises(ValueError, match="complete commit SHA"):
        validate_release_tag(repo, "v2026.10.05_1", first[:7])


def test_explicit_repository_ignores_an_ambient_git_directory(tag_repo, tmp_path, monkeypatch):
    repo, first, _ = tag_repo
    foreign = tmp_path / "foreign"
    git_env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    subprocess.run(["git", "init", str(foreign)], capture_output=True, text=True, check=True, env=git_env)
    assert (foreign / ".git").is_dir()
    monkeypatch.setenv("GIT_DIR", str(foreign / ".git"))
    assert validate_release_tag(repo, "v2026.10.05_1", first)["release_commit"] == first
