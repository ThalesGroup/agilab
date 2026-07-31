# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Guards for the pre-push skip-ci scope check."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "skip_ci_scope_guard", REPO_ROOT / "tools" / "skip_ci_scope_guard.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = _load()


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch):
    """A throwaway git repo the guard can inspect."""

    def run(*args: str) -> None:
        subprocess.run(args, cwd=tmp_path, check=True, capture_output=True)

    run("git", "init", "-q", ".")
    run("git", "config", "user.email", "guard@test")
    run("git", "config", "user.name", "guard")
    (tmp_path / "docs").mkdir()
    (tmp_path / "tools").mkdir()
    (tmp_path / "docs" / "a.md").write_text("base\n", encoding="utf-8")
    run("git", "add", "-A")
    run("git", "commit", "-qm", "base")
    monkeypatch.setattr(MODULE, "REPO_ROOT", tmp_path)

    def commit(message: str, path: str, content: str) -> str:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        run("git", "add", "-A")
        run("git", "commit", "-qm", message)
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
        ).stdout.strip()

    return commit


def test_docs_only_skip_is_allowed(repo) -> None:
    """A pure docs refresh is exactly what [skip ci] is for."""

    sha = repo("docs: refresh [skip ci]", "docs/a.md", "changed\n")
    assert MODULE.find_offences([sha]) == []


@pytest.mark.parametrize(
    "path", ["tools/thing.py", "src/agilab/thing.py", "test/test_thing.py", ".github/workflows/ci.yml"]
)
def test_code_change_with_skip_is_blocked(repo, path: str) -> None:
    sha = repo(f"chore: touch {path} [skip ci]", path, "print('x')\n")
    offences = MODULE.find_offences([sha])
    assert [offence.code_files for offence in offences] == [(path,)]


@pytest.mark.parametrize("directive", ["[skip ci]", "[ci skip]", "[no ci]", "[skip actions]"])
def test_every_github_skip_directive_is_recognised(repo, directive: str) -> None:
    sha = repo(f"chore: tweak {directive}", "tools/thing.py", "print('x')\n")
    assert MODULE.find_offences([sha])


def test_directive_matching_is_case_insensitive(repo) -> None:
    sha = repo("chore: tweak [SKIP CI]", "tools/thing.py", "print('x')\n")
    assert MODULE.find_offences([sha])


def test_code_change_without_skip_is_allowed(repo) -> None:
    sha = repo("fix: real change with CI", "tools/thing.py", "print('x')\n")
    assert MODULE.find_offences([sha]) == []


@pytest.mark.parametrize("path", ["tools/README.md", "src/agilab/notes.rst", "test/fixture.svg"])
def test_inert_files_under_code_paths_may_skip(repo, path: str) -> None:
    """Docs and assets living beside code should not force a full matrix."""

    sha = repo(f"docs: {path} [skip ci]", path, "text\n")
    assert MODULE.find_offences([sha]) == []


def test_pre_push_spec_ignores_branch_deletions() -> None:
    zero = "0" * 40
    spec = f"refs/heads/gone {zero} refs/heads/gone abc123\n"
    assert MODULE._parse_pre_push_spec(spec) == []


def test_pre_push_spec_parses_a_normal_push() -> None:
    spec = "refs/heads/topic aaa111 refs/heads/topic bbb222\n"
    assert MODULE._parse_pre_push_spec(spec) == [("bbb222", "aaa111")]


def test_render_names_the_offending_files() -> None:
    offence = MODULE.Offence(
        commit="abc123def456",
        subject="chore: tweak [skip ci]",
        directive="[skip ci]",
        code_files=("tools/thing.py",),
    )
    rendered = MODULE.render([offence])
    assert "tools/thing.py" in rendered
    assert "[skip ci]" in rendered
    assert "AGILAB_ALLOW_SKIP_CI=1" in rendered
