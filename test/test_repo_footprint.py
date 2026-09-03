from __future__ import annotations

from types import SimpleNamespace

import pytest

from tools import repo_footprint


@pytest.mark.parametrize("preserve", ["../outside.txt", "/tmp/outside.txt", "."])
def test_realign_local_rejects_unconfined_preserve_path_before_git_mutation(
    tmp_path, monkeypatch, preserve: str
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git_calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(repo_footprint, "_require_repo", lambda _repo: repo)
    monkeypatch.setattr(repo_footprint, "_repo_root", lambda path: path)
    monkeypatch.setattr(
        repo_footprint,
        "_git",
        lambda _repo, *args, **_kwargs: git_calls.append(tuple(args)),
    )
    args = SimpleNamespace(
        repo=str(repo),
        preserve=[preserve],
        preserve_dir=str(tmp_path / "preserved"),
        target_ref="origin/main",
        fetch=False,
        remote_name="origin",
        gc=False,
        apply=True,
    )

    with pytest.raises(ValueError, match="preserve path"):
        repo_footprint._realign_local(args)

    assert git_calls == []


def test_realign_local_rejects_symlinked_preserve_tree_before_git_mutation(
    tmp_path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.txt").write_text("private\n", encoding="utf-8")
    linked = repo / "linked"
    try:
        linked.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlinks unavailable: {error}")
    git_calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(repo_footprint, "_require_repo", lambda _repo: repo)
    monkeypatch.setattr(repo_footprint, "_repo_root", lambda path: path)
    monkeypatch.setattr(
        repo_footprint,
        "_git",
        lambda _repo, *args, **_kwargs: git_calls.append(tuple(args)),
    )
    args = SimpleNamespace(
        repo=str(repo),
        preserve=["linked"],
        preserve_dir=str(tmp_path / "preserved"),
        target_ref="origin/main",
        fetch=False,
        remote_name="origin",
        gc=False,
        apply=True,
    )

    with pytest.raises(ValueError, match="symlink"):
        repo_footprint._realign_local(args)

    assert git_calls == []
    assert linked.is_symlink()


def test_realign_local_rejects_link_in_existing_snapshot_before_git_mutation(
    tmp_path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    source = repo / "docs"
    source.mkdir(parents=True)
    (source / "guide.md").write_text("guide\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("keep\n", encoding="utf-8")
    preserve_dir = tmp_path / "preserved"
    snapshot = preserve_dir / "docs"
    snapshot.mkdir(parents=True)
    try:
        (snapshot / "linked").symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlinks unavailable: {error}")
    git_calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(repo_footprint, "_require_repo", lambda _repo: repo)
    monkeypatch.setattr(repo_footprint, "_repo_root", lambda path: path)
    monkeypatch.setattr(
        repo_footprint,
        "_git",
        lambda _repo, *args, **_kwargs: git_calls.append(tuple(args)),
    )
    args = SimpleNamespace(
        repo=str(repo),
        preserve=["docs"],
        preserve_dir=str(preserve_dir),
        target_ref="origin/main",
        fetch=False,
        remote_name="origin",
        gc=False,
        apply=True,
    )

    with pytest.raises(ValueError, match="preserve snapshot.*symlink"):
        repo_footprint._realign_local(args)

    assert git_calls == []
    assert sentinel.read_text(encoding="utf-8") == "keep\n"
