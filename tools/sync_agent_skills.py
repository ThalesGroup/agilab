#!/usr/bin/env python3
"""Sync selected shared repo skills from `.claude/skills` into `.codex/skills`.

`--check` runs the read-only side of the mechanism instead: it reports drift
between the canonical tree and the Codex mirror, then verifies the Tokki agent
enumerates every canonical skill (`tokki skills list --skills-dir
.claude/skills`). Tokki has no repo mirror of its own; the canonical tree is
its skill source.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLAUDE_ROOT = ROOT / ".claude" / "skills"
CODEX_ROOT = ROOT / ".codex" / "skills"
SKIP_NAMES = {"README.md", ".DS_Store"}
TOKKI_LIST_TIMEOUT_SECONDS = 120


def iter_skill_dirs(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    )


def iter_skill_files(skill_dir: Path) -> list[Path]:
    # Follow directory symlinks so the check sees the same tree that
    # sync_skill's copytree(symlinks=False) materializes into the mirror.
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(skill_dir, followlinks=True):
        dirnames[:] = [name for name in dirnames if name not in SKIP_NAMES]
        for name in filenames:
            if name in SKIP_NAMES:
                continue
            files.append((Path(dirpath) / name).relative_to(skill_dir))
    return sorted(files)


def _is_executable(path: Path) -> bool:
    return bool(path.stat().st_mode & 0o111)


def sync_skill(source: Path, destination_root: Path) -> Path:
    destination = destination_root / source.name
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(*SKIP_NAMES),
    )
    return destination


def collect_skill_drift(source: Path, destination_root: Path) -> list[str]:
    destination = destination_root / source.name
    if not destination.exists():
        return [f"{source.name}: missing from {destination_root}"]
    source_files = set(iter_skill_files(source))
    destination_files = set(iter_skill_files(destination))
    drift = [
        f"{source.name}/{relative}: missing from mirror"
        for relative in sorted(source_files - destination_files)
    ]
    drift.extend(
        f"{source.name}/{relative}: not in canonical source"
        for relative in sorted(destination_files - source_files)
    )
    for relative in sorted(source_files & destination_files):
        source_file = source / relative
        destination_file = destination / relative
        if source_file.read_bytes() != destination_file.read_bytes():
            drift.append(f"{source.name}/{relative}: content differs")
        if _is_executable(source_file) != _is_executable(destination_file):
            drift.append(f"{source.name}/{relative}: executable bit differs")
    return drift


def verify_tokki_skill_visibility(claude_root: Path | None = None) -> bool:
    """Confirm the Tokki agent sees every canonical skill; skip when absent."""
    root = claude_root if claude_root is not None else CLAUDE_ROOT
    executable = shutil.which("tokki")
    if executable is None:
        print("tokki not on PATH; skipped tokki skill visibility check")
        return False
    command = [executable, "skills", "list", "--skills-dir", str(root), "--json"]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=TOKKI_LIST_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise SystemExit(
            f"tokki skills list timed out after {TOKKI_LIST_TIMEOUT_SECONDS}s"
        )
    if result.returncode != 0:
        raise SystemExit(
            f"tokki skills list failed ({result.returncode}): {result.stderr.strip()}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise SystemExit(f"tokki skills list returned invalid JSON: {error}")
    seen = {
        entry.get("name")
        for entry in payload.get("skills", [])
        if isinstance(entry, dict)
    }
    expected = {path.name for path in iter_skill_dirs(root)}
    missing = sorted(expected - seen)
    if missing:
        raise SystemExit(
            f"tokki does not see {len(missing)} canonical skill(s): "
            + ", ".join(missing)
        )
    print(f"tokki sees {len(expected)} skill(s) from {root}")
    return True


def validate_skills_root(skills_root: Path, *, python_executable: str = sys.executable, root: Path = ROOT) -> None:
    subprocess.run(
        [
            python_executable,
            str(root / "tools" / "codex_skills.py"),
            "--root",
            str(skills_root),
            "validate",
            "--strict",
        ],
        check=True,
        cwd=str(root),
    )


def refresh_codex_skill_index(*, python_executable: str = sys.executable, root: Path = ROOT) -> None:
    # Validate first: `generate` exits 2 on front-matter issues without
    # printing them, while `validate` reports each issue.
    for action in (["validate", "--strict"], ["generate"]):
        subprocess.run(
            [
                python_executable,
                str(root / "tools" / "codex_skills.py"),
                "--root",
                ".codex/skills",
                *action,
            ],
            check=True,
            cwd=str(root),
        )


def refresh_skill_badges(*, python_executable: str = sys.executable, root: Path = ROOT) -> None:
    subprocess.run(
        [python_executable, str(root / "tools" / "generate_skill_badges.py")],
        check=True,
        cwd=str(root),
    )


def refresh_agent_skill_catalog(*, python_executable: str = sys.executable, root: Path = ROOT) -> None:
    subprocess.run(
        [python_executable, str(root / "tools" / "agent_skill_catalog.py"), "--apply"],
        check=True,
        cwd=str(root),
    )


def refresh_capability_manifest(*, python_executable: str = sys.executable, root: Path = ROOT) -> None:
    subprocess.run(
        [python_executable, str(root / "tools" / "agilab_capabilities_manifest.py"), "--apply"],
        check=True,
        cwd=str(root),
    )
    subprocess.run(
        [python_executable, str(root / "tools" / "agilab_capabilities_lint.py"), "--check"],
        check=True,
        cwd=str(root),
    )
    subprocess.run(
        [python_executable, str(root / "tools" / "agenticweb_manifest.py"), "--apply"],
        check=True,
        cwd=str(root),
    )
    subprocess.run(
        [python_executable, str(root / "tools" / "agenticweb_manifest.py"), "--check"],
        check=True,
        cwd=str(root),
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--all",
        action="store_true",
        help="Sync every repo Claude skill into `.codex/skills`.",
    )
    selection.add_argument(
        "--skills",
        nargs="+",
        help="Subset of skill folder names to sync.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Report drift between `.claude/skills` and `.codex/skills` and "
            "verify Tokki skill visibility without syncing anything."
        ),
    )
    args = parser.parse_args(argv)
    if not args.check and not args.all and not args.skills:
        parser.error("one of --all or --skills is required unless --check is used")
    return args


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    if not CLAUDE_ROOT.exists():
        raise SystemExit(f"Missing source skills root: {CLAUDE_ROOT}")

    skill_dirs = iter_skill_dirs(CLAUDE_ROOT)
    if args.skills:
        selected = set(args.skills)
        skill_dirs = [path for path in skill_dirs if path.name in selected]
        missing = sorted(selected - {path.name for path in skill_dirs})
        if missing:
            raise SystemExit(f"Unknown skill(s): {', '.join(missing)}")

    if args.check:
        drift: list[str] = []
        for source in skill_dirs:
            drift.extend(collect_skill_drift(source, CODEX_ROOT))
        if not args.skills and CODEX_ROOT.exists():
            canonical_names = {path.name for path in iter_skill_dirs(CLAUDE_ROOT)}
            drift.extend(
                f"{path.name}: mirror-only skill, not in canonical source"
                for path in iter_skill_dirs(CODEX_ROOT)
                if path.name not in canonical_names
            )
        for line in drift:
            print(f"- {line}")
        verify_tokki_skill_visibility()
        if drift:
            print(
                f"{len(drift)} drift issue(s) between {CLAUDE_ROOT} and {CODEX_ROOT}"
            )
            return 1
        print(
            f"No drift between {CLAUDE_ROOT} and {CODEX_ROOT} "
            f"for {len(skill_dirs)} skill(s)"
        )
        return 0

    CODEX_ROOT.mkdir(parents=True, exist_ok=True)

    validate_skills_root(CLAUDE_ROOT)

    synced: list[Path] = []
    for source in skill_dirs:
        synced.append(sync_skill(source, CODEX_ROOT))

    refresh_codex_skill_index()
    refresh_skill_badges()
    refresh_agent_skill_catalog()
    refresh_capability_manifest()
    verify_tokki_skill_visibility()

    print(f"Synced {len(synced)} skill(s) from {CLAUDE_ROOT} to {CODEX_ROOT}")
    for path in synced:
        print(f"- {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
