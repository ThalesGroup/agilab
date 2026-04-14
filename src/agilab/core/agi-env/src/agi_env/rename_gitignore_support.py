"""Pure content-rename and gitignore helpers for AGILAB."""

from __future__ import annotations

import re
from pathlib import Path

from pathspec import PathSpec
from pathspec.patterns import GitWildMatchPattern


def replace_text_content(txt: str, rename_map: dict) -> str:
    """Replace whole-word content occurrences according to ``rename_map``."""

    boundary = r"(?<![0-9A-Za-z_]){token}(?![0-9A-Za-z_])"
    for old, new in sorted(rename_map.items(), key=lambda kv: len(kv[0]), reverse=True):
        token = re.escape(old)
        pattern = re.compile(boundary.format(token=token))
        txt = pattern.sub(new, txt)
    return txt


def load_gitignore_spec(gitignore_path: Path) -> PathSpec:
    """Load a gitignore file into a ``PathSpec``."""

    lines = gitignore_path.read_text(encoding="utf-8").splitlines()
    return PathSpec.from_lines(GitWildMatchPattern, lines)


def is_relative_to(path: Path, other: Path) -> bool:
    """Return ``True`` if ``path`` lies under ``other``."""

    try:
        path.relative_to(other)
        return True
    except ValueError:
        return False
