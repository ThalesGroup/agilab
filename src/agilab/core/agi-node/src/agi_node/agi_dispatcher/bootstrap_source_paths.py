"""Bootstrap repo-local source paths for dispatcher scripts."""

from __future__ import annotations

from pathlib import Path
import sys


def bootstrap_core_source_paths(*, source_file: str | Path | None = None) -> tuple[Path, ...]:
    """Insert repo-local AGI core source roots into ``sys.path`` when available."""
    source_path = Path(source_file or __file__).resolve()
    core_root = None
    for parent in source_path.parents:
        if parent.name == "core" and parent.parent.name == "agilab":
            core_root = parent
            break
    if core_root is None:
        return ()

    candidates = (
        core_root / "agi-env" / "src",
        core_root / "agi-node" / "src",
        core_root / "agi-cluster" / "src",
        core_root / "agi-core" / "src",
    )
    added: list[Path] = []
    for candidate in reversed(candidates):
        if candidate.is_dir():
            candidate_str = str(candidate)
            sys.path[:] = [entry for entry in sys.path if entry != candidate_str]
            sys.path.insert(0, candidate_str)
            added.append(candidate)
    return tuple(reversed(added))
