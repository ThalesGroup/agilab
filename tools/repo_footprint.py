#!/usr/bin/env python3
"""
Repo footprint helper for AGILAB checkouts.

This tool distinguishes:
- working-tree footprint (`.venv`, caches, build outputs)
- local Git footprint (`.git/objects`, `.git/lfs`)
- remote history size (which only changes after a history rewrite + force-push)

Typical usage:
  uv run python tools/repo_footprint.py audit
  uv run python tools/repo_footprint.py lfs-prune --dry-run
  uv run python tools/repo_footprint.py realign-local --preserve docs/source/foo.rst --apply
  uv run python tools/repo_footprint.py history-rewrite \\
      --remove-path docs/html --remove-path .idea/shelf --apply --push
"""

from __future__ import annotations

import argparse
import heapq
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Sequence


def _run(
    cmd: Sequence[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    capture_output: bool = True,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(cmd),
        cwd=str(cwd) if cwd else None,
        check=check,
        text=True,
        input=input_text,
        capture_output=capture_output,
    )


def _git(
    repo: Path,
    *args: str,
    check: bool = True,
    capture_output: bool = True,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return _run(
        ["git", *args],
        cwd=repo,
        check=check,
        capture_output=capture_output,
        input_text=input_text,
    )


def _require_repo(repo_arg: str) -> Path:
    repo = Path(repo_arg).expanduser().resolve()
    _git(repo, "rev-parse", "--show-toplevel")
    return repo


def _repo_root(repo: Path) -> Path:
    return Path(_git(repo, "rev-parse", "--show-toplevel").stdout.strip()).resolve()


def _git_dir(repo: Path) -> Path:
    git_dir = _git(repo, "rev-parse", "--git-dir").stdout.strip()
    path = Path(git_dir)
    if not path.is_absolute():
        path = (repo / path).resolve()
    return path


def _human_bytes(num_bytes: int | None) -> str:
    if num_bytes is None:
        return "n/a"
    value = float(num_bytes)
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{num_bytes} B"


def _du_bytes(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        out = _run(["du", "-sk", str(path)], capture_output=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    if not out:
        return None
    try:
        kib = int(out.split()[0])
    except (ValueError, IndexError):
        return None
    return kib * 1024


def _print_section(title: str) -> None:
    print(f"\n{title}")
    print("-" * len(title))


def _largest_head_files(repo: Path, limit: int) -> list[tuple[int, str]]:
    proc = _git(repo, "ls-tree", "-r", "-l", "HEAD")
    top: list[tuple[int, str]] = []
    for line in proc.stdout.splitlines():
        if "\t" not in line:
            continue
        meta, path = line.split("\t", 1)
        parts = meta.split()
        if len(parts) < 4:
            continue
        size_str = parts[3]
        if size_str == "-":
            continue
        try:
            size = int(size_str)
        except ValueError:
            continue
        if len(top) < limit:
            heapq.heappush(top, (size, path))
        else:
            heapq.heappushpop(top, (size, path))
    return sorted(top, reverse=True)


def _largest_historical_blobs(repo: Path, limit: int) -> list[tuple[int, str, str]]:
    rev_list = subprocess.Popen(
        ["git", "rev-list", "--objects", "--all"],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
    )
    cat_file = subprocess.Popen(
        ["git", "cat-file", "--batch-check=%(objecttype) %(objectname) %(objectsize) %(rest)"],
        cwd=repo,
        text=True,
        stdin=rev_list.stdout,
        stdout=subprocess.PIPE,
    )
    assert rev_list.stdout is not None
    rev_list.stdout.close()
    assert cat_file.stdout is not None

    top: list[tuple[int, str, str]] = []
    for line in cat_file.stdout:
        parts = line.rstrip("\n").split(" ", 3)
        if len(parts) < 4:
            continue
        obj_type, sha, size_str, path = parts
        if obj_type != "blob":
            continue
        try:
            size = int(size_str)
        except ValueError:
            continue
        item = (size, path, sha)
        if len(top) < limit:
            heapq.heappush(top, item)
        else:
            heapq.heappushpop(top, item)

    cat_file.wait()
    rev_list.wait()
    return sorted(top, reverse=True)


def _print_completed(label: str, completed: subprocess.CompletedProcess[str]) -> None:
    out = (completed.stdout or "") + (completed.stderr or "")
    out = out.strip()
    print(f"$ {' '.join(completed.args)}")
    if out:
        print(out)


def _command_exists(cmd: Sequence[str]) -> bool:
    try:
        _run(cmd, capture_output=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def _audit(args: argparse.Namespace) -> int:
    repo = _repo_root(_require_repo(args.repo))
    git_dir = _git_dir(repo)

    _print_section("Repository")
    print(f"root: {repo}")
    print(f"git dir: {git_dir}")

    _print_section("Status")
    status = _git(repo, "status", "--short", "--branch")
    print(status.stdout.strip() or "clean")

    _print_section("Git Storage")
    for rel in (".", "objects", "lfs", "logs"):
        path = git_dir / rel if rel != "." else git_dir
        print(f"{path}: {_human_bytes(_du_bytes(path))}")

    print()
    print(_git(repo, "count-objects", "-vH").stdout.strip())

    if _command_exists(["git", "lfs", "version"]):
        _print_section("LFS Prune Dry Run")
        dry_run = _git(repo, "lfs", "prune", "--dry-run", check=False)
        _print_completed("lfs-prune", dry_run)

    _print_section(f"Largest Files In HEAD (top {args.limit})")
    for size, path in _largest_head_files(repo, args.limit):
        print(f"{_human_bytes(size):>10}  {path}")

    _print_section(f"Largest Historical Blobs (top {args.limit})")
    for size, path, sha in _largest_historical_blobs(repo, args.limit):
        print(f"{_human_bytes(size):>10}  {sha[:12]}  {path}")
    return 0


def _lfs_prune(args: argparse.Namespace) -> int:
    repo = _repo_root(_require_repo(args.repo))
    if not _command_exists(["git", "lfs", "version"]):
        print("git-lfs is not installed or not available in PATH.", file=sys.stderr)
        return 2
    cmd = ["git", "lfs", "prune"]
    if args.dry_run or not args.apply:
        cmd.append("--dry-run")
    completed = _run(cmd, cwd=repo, check=False)
    _print_completed("lfs-prune", completed)
    return completed.returncode


def _default_mirror_dir(repo: Path) -> Path:
    return Path(tempfile.gettempdir()) / f"{repo.name}-rewrite.git"


def _default_bundle_path(repo: Path) -> Path:
    return Path(tempfile.gettempdir()) / f"{repo.name}-pre-rewrite.bundle"


def _remote_url(repo: Path, remote_name: str) -> str:
    return _git(repo, "remote", "get-url", remote_name).stdout.strip()


def _history_rewrite(args: argparse.Namespace) -> int:
    repo = _repo_root(_require_repo(args.repo))
    mirror_dir = Path(args.mirror_dir).expanduser().resolve() if args.mirror_dir else _default_mirror_dir(repo)
    bundle_path = Path(args.bundle).expanduser().resolve() if args.bundle else _default_bundle_path(repo)
    remove_paths: list[str] = list(args.remove_path or [])

    if not remove_paths and not args.strip_blobs_bigger_than:
        print("Nothing to rewrite: provide --remove-path and/or --strip-blobs-bigger-than.", file=sys.stderr)
        return 2

    refs = list(args.refs or [])
    remote_url = _remote_url(repo, args.remote_name)

    print("History rewrite plan")
    print("--------------------")
    print(f"repo: {repo}")
    print(f"mirror dir: {mirror_dir}")
    print(f"backup bundle: {bundle_path}")
    print(f"remote: {args.remote_name} -> {remote_url}")
    print(f"refs: {refs if refs else 'ALL REFS'}")
    if remove_paths:
        print(f"remove paths: {remove_paths}")
    if args.strip_blobs_bigger_than:
        print(f"strip blobs bigger than: {args.strip_blobs_bigger_than}")
    print(f"push rewritten refs: {'yes' if args.push else 'no'}")

    if not args.apply:
        print("\nDry run only. Re-run with --apply to execute.")
        return 0

    if not _command_exists(["git", "filter-repo", "--version"]):
        print("git-filter-repo is required but not available.", file=sys.stderr)
        return 2

    if mirror_dir.exists():
        print(f"Mirror directory already exists: {mirror_dir}", file=sys.stderr)
        print("Remove it or pass a different --mirror-dir.", file=sys.stderr)
        return 2
    if bundle_path.exists():
        print(f"Backup bundle already exists: {bundle_path}", file=sys.stderr)
        print("Remove it or pass a different --bundle.", file=sys.stderr)
        return 2

    _run(["git", "clone", "--mirror", str(repo), str(mirror_dir)], capture_output=True)
    _git(mirror_dir, "bundle", "create", str(bundle_path), "--all")

    filter_cmd = ["git", "filter-repo"]
    if refs:
        filter_cmd.extend(["--refs", *refs])
    if args.strip_blobs_bigger_than:
        filter_cmd.extend(["--strip-blobs-bigger-than", args.strip_blobs_bigger_than])
    if remove_paths:
        for path in remove_paths:
            filter_cmd.extend(["--path", path])
        filter_cmd.append("--invert-paths")
    _run(filter_cmd, cwd=mirror_dir, capture_output=True)

    if args.push:
        _git(mirror_dir, "remote", "add", args.remote_name, remote_url)
        if refs:
            refspecs = [f"{ref}:{ref}" for ref in refs]
            _git(mirror_dir, "push", args.remote_name, "--force", *refspecs)
        else:
            _git(mirror_dir, "push", args.remote_name, "--force", "--all")
            _git(mirror_dir, "push", args.remote_name, "--force", "--tags")

    print("\nRewrite complete.")
    print(f"mirror: {mirror_dir}")
    print(f"backup bundle: {bundle_path}")
    return 0


def _copy_preserved(src: Path, dst: Path) -> None:
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _realign_local(args: argparse.Namespace) -> int:
    repo = _repo_root(_require_repo(args.repo))
    preserve_paths = [Path(p) for p in (args.preserve or [])]
    preserve_dir = (
        Path(args.preserve_dir).expanduser().resolve()
        if args.preserve_dir
        else Path(tempfile.mkdtemp(prefix=f"{repo.name}-preserve-"))
    )

    print("Local realign plan")
    print("------------------")
    print(f"repo: {repo}")
    print(f"target ref: {args.target_ref}")
    print(f"preserve dir: {preserve_dir}")
    print(f"preserve paths: {[str(p) for p in preserve_paths] if preserve_paths else 'none'}")
    print(f"fetch first: {'yes' if args.fetch else 'no'}")
    print(f"run gc: {'yes' if args.gc else 'no'}")

    if not args.apply:
        print("\nDry run only. Re-run with --apply to execute.")
        return 0

    preserved: list[tuple[Path, Path]] = []
    preserve_dir.mkdir(parents=True, exist_ok=True)

    for rel in preserve_paths:
        target = (repo / rel).resolve()
        if not target.exists():
            print(f"skip missing preserve path: {rel}")
            continue
        snapshot = preserve_dir / rel
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        _copy_preserved(target, snapshot)
        preserved.append((snapshot, repo / rel))

    if args.fetch:
        _git(repo, "fetch", args.remote_name, "--prune", "--tags")

    _git(repo, "reset", "--hard", args.target_ref)

    for snapshot, target in preserved:
        _copy_preserved(snapshot, target)

    if args.gc:
        _git(repo, "reflog", "expire", "--expire=now", "--all")
        _git(repo, "gc", "--prune=now")

    print("\nRealign complete.")
    print(f"preserved files snapshot: {preserve_dir}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="Measure local Git footprint and show the biggest files/blobs.")
    audit.add_argument("--repo", default=".", help="Repository root or any path inside the repo.")
    audit.add_argument("--limit", type=int, default=10, help="How many largest files/blobs to show.")
    audit.set_defaults(func=_audit)

    lfs_prune = sub.add_parser("lfs-prune", help="Run git lfs prune (dry-run by default).")
    lfs_prune.add_argument("--repo", default=".", help="Repository root or any path inside the repo.")
    lfs_prune.add_argument("--dry-run", action="store_true", help="Force dry-run output.")
    lfs_prune.add_argument("--apply", action="store_true", help="Actually prune local LFS cache.")
    lfs_prune.set_defaults(func=_lfs_prune)

    rewrite = sub.add_parser("history-rewrite", help="Rewrite Git history in an isolated mirror clone.")
    rewrite.add_argument("--repo", default=".", help="Repository root or any path inside the repo.")
    rewrite.add_argument("--remote-name", default="origin", help="Remote to push back to when --push is used.")
    rewrite.add_argument("--mirror-dir", help="Mirror clone path. Defaults to /tmp/<repo>-rewrite.git")
    rewrite.add_argument("--bundle", help="Backup bundle path. Defaults to /tmp/<repo>-pre-rewrite.bundle")
    rewrite.add_argument(
        "--remove-path",
        action="append",
        default=[],
        help="Remove this path from history. Repeat for multiple paths.",
    )
    rewrite.add_argument(
        "--strip-blobs-bigger-than",
        help="Drop historical blobs larger than this size (for example 2M, 50M).",
    )
    rewrite.add_argument(
        "--refs",
        nargs="*",
        help="Explicit refs to rewrite/push (for example refs/heads/main refs/tags/v1). Defaults to all refs.",
    )
    rewrite.add_argument("--push", action="store_true", help="Force-push rewritten refs back to the configured remote.")
    rewrite.add_argument("--apply", action="store_true", help="Execute the rewrite. Otherwise only print the plan.")
    rewrite.set_defaults(func=_history_rewrite)

    realign = sub.add_parser("realign-local", help="Realign a local checkout to a remote ref after a rewrite.")
    realign.add_argument("--repo", default=".", help="Repository root or any path inside the repo.")
    realign.add_argument("--remote-name", default="origin", help="Remote name used by --fetch.")
    realign.add_argument("--target-ref", default="origin/main", help="Target ref to reset the current branch to.")
    realign.add_argument(
        "--preserve",
        action="append",
        default=[],
        help="Relative path to preserve across the hard reset. Repeat for multiple paths.",
    )
    realign.add_argument("--preserve-dir", help="Where preserved files are copied before the reset.")
    realign.add_argument("--fetch", action=argparse.BooleanOptionalAction, default=True, help="Fetch/prune before resetting.")
    realign.add_argument("--gc", action=argparse.BooleanOptionalAction, default=True, help="Expire reflogs and run git gc after reset.")
    realign.add_argument("--apply", action="store_true", help="Execute the realign. Otherwise only print the plan.")
    realign.set_defaults(func=_realign_local)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
