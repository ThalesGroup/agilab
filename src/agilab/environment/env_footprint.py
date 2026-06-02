from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Iterable, Sequence


SCHEMA = "agilab.env_footprint.v1"
SIZE_EXCLUDE_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
    "node_modules",
}
BUILD_OUTPUT_NAMES = {".pytest_cache", "__pycache__", "build", "dist", "htmlcov"}


def _allocated_bytes(stat_result: os.stat_result) -> int:
    return int(getattr(stat_result, "st_blocks", 0) or 0) * 512 or int(stat_result.st_size)


def _format_bytes(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{value} B"


def _path_entry(path: Path, *, allocated_bytes: int, apparent_bytes: int) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists() or path.is_symlink(),
        "allocated_bytes": allocated_bytes,
        "allocated_human": _format_bytes(allocated_bytes),
        "apparent_bytes": apparent_bytes,
        "apparent_human": _format_bytes(apparent_bytes),
    }
    if path.is_symlink():
        try:
            entry["symlink_target"] = os.readlink(path)
        except OSError:
            entry["symlink_target"] = "<unreadable>"
    return entry


def _scan_path(
    path: Path,
    *,
    seen: set[tuple[int, int]] | None = None,
    exclude_dirs: set[str] | None = None,
) -> tuple[int, int]:
    path = path.expanduser()
    if not (path.exists() or path.is_symlink()):
        return 0, 0
    exclude_dirs = exclude_dirs or set()
    apparent = 0
    allocated = 0
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            stat_result = current.lstat()
        except OSError:
            continue
        inode_key = (stat_result.st_dev, stat_result.st_ino)
        apparent += int(stat_result.st_size)
        if seen is None or inode_key not in seen:
            allocated += _allocated_bytes(stat_result)
            if seen is not None:
                seen.add(inode_key)
        if current.is_dir() and not current.is_symlink():
            try:
                children = sorted(current.iterdir(), key=lambda child: child.name)
            except OSError:
                continue
            for child in reversed(children):
                if child.is_dir() and not child.is_symlink() and child.name in exclude_dirs:
                    continue
                stack.append(child)
    return allocated, apparent


def _entry_for(path: Path, *, exclude_dirs: set[str] | None = None) -> dict[str, Any]:
    allocated, apparent = _scan_path(path, exclude_dirs=exclude_dirs)
    return _path_entry(path, allocated_bytes=allocated, apparent_bytes=apparent)


def _iter_venvs(root: Path) -> Iterable[Path]:
    root = root.expanduser()
    if not root.exists():
        return
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            children = sorted(current.iterdir(), key=lambda child: child.name)
        except OSError:
            continue
        for child in children:
            if child.name == ".venv":
                if child.is_dir() or child.is_symlink():
                    yield child
                continue
            if child.is_dir() and not child.is_symlink():
                if child.name in {".git", "__pycache__", "node_modules"}:
                    continue
                stack.append(child)


def _iter_build_outputs(root: Path) -> Iterable[Path]:
    root = root.expanduser()
    if not root.exists():
        return
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            children = sorted(current.iterdir(), key=lambda child: child.name)
        except OSError:
            continue
        for child in children:
            if not child.is_dir() or child.is_symlink():
                continue
            if child.name in BUILD_OUTPUT_NAMES:
                yield child
                continue
            if child.name in {".git", ".venv", "node_modules"}:
                continue
            stack.append(child)


def _category(name: str, paths: Sequence[Path], *, exclude_dirs: set[str] | None = None) -> dict[str, Any]:
    entries = [_entry_for(path, exclude_dirs=exclude_dirs) for path in paths]
    allocated = sum(int(entry["allocated_bytes"]) for entry in entries)
    apparent = sum(int(entry["apparent_bytes"]) for entry in entries)
    return {
        "name": name,
        "allocated_bytes": allocated,
        "allocated_human": _format_bytes(allocated),
        "apparent_bytes": apparent,
        "apparent_human": _format_bytes(apparent),
        "entries": entries,
    }


def _existing(paths: Iterable[Path]) -> list[Path]:
    seen: set[Path] = set()
    result: list[Path] = []
    for path in paths:
        expanded = path.expanduser()
        if expanded in seen:
            continue
        seen.add(expanded)
        if expanded.exists() or expanded.is_symlink():
            result.append(expanded)
    return result


def _repo_root_from_here() -> Path:
    for candidate in (Path.cwd(), *Path.cwd().parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src" / "agilab").is_dir():
            return candidate
    return Path.cwd()


def build_footprint(repo_root: Path | None = None, home: Path | None = None, *, top: int = 12) -> dict[str, Any]:
    repo_root = (repo_root or _repo_root_from_here()).expanduser().resolve(strict=False)
    home = (home or Path.home()).expanduser().resolve(strict=False)
    agi_space = home / "agi-space"
    wenv = home / "wenv"
    uv_cache = Path(os.environ.get("UV_CACHE_DIR", home / ".cache" / "uv")).expanduser()
    uv_store = home / ".local" / "share" / "uv"
    agilab_state = home / ".local" / "share" / "agilab"
    agilab_user = home / ".agilab"

    repo_venvs = sorted(_iter_venvs(repo_root), key=lambda path: path.as_posix())
    root_venv = repo_root / ".venv"
    project_venvs = [path for path in repo_venvs if path != root_venv]
    worker_venvs = sorted(_iter_venvs(wenv), key=lambda path: path.as_posix())
    agi_space_venvs = sorted(_iter_venvs(agi_space), key=lambda path: path.as_posix())
    build_outputs = sorted(_iter_build_outputs(repo_root), key=lambda path: path.as_posix())

    categories = [
        _category("source_tree", [repo_root / "src" / "agilab"], exclude_dirs=SIZE_EXCLUDE_DIRS),
        _category("root_venv", _existing([root_venv])),
        _category("project_venvs", project_venvs),
        _category("agi_space_venvs", agi_space_venvs),
        _category("worker_venvs", worker_venvs),
        _category("uv_cache", _existing([uv_cache])),
        _category("uv_python_store", _existing([uv_store])),
        _category("agilab_state", _existing([agilab_state, agilab_user]), exclude_dirs=SIZE_EXCLUDE_DIRS),
        _category("build_outputs", build_outputs),
    ]

    category_paths = [
        Path(entry["path"])
        for category in categories
        for entry in category["entries"]
        if entry["exists"]
    ]
    unique_seen: set[tuple[int, int]] = set()
    unique_allocated = 0
    unique_apparent = 0
    for path in category_paths:
        allocated, apparent = _scan_path(path, seen=unique_seen)
        unique_allocated += allocated
        unique_apparent += apparent

    raw_allocated = sum(int(category["allocated_bytes"]) for category in categories)
    raw_apparent = sum(int(category["apparent_bytes"]) for category in categories)
    all_entries = sorted(
        (
            entry
            for category in categories
            for entry in category["entries"]
            if entry["exists"]
        ),
        key=lambda entry: int(entry["allocated_bytes"]),
        reverse=True,
    )

    return {
        "schema": SCHEMA,
        "repo_root": str(repo_root),
        "home": str(home),
        "uv_link_mode": os.environ.get("UV_LINK_MODE", ""),
        "summary": {
            "raw_allocated_bytes": raw_allocated,
            "raw_allocated_human": _format_bytes(raw_allocated),
            "raw_apparent_bytes": raw_apparent,
            "raw_apparent_human": _format_bytes(raw_apparent),
            "unique_allocated_bytes": unique_allocated,
            "unique_allocated_human": _format_bytes(unique_allocated),
            "unique_apparent_bytes": unique_apparent,
            "unique_apparent_human": _format_bytes(unique_apparent),
            "hardlink_savings_bytes": max(raw_allocated - unique_allocated, 0),
            "hardlink_savings_human": _format_bytes(max(raw_allocated - unique_allocated, 0)),
        },
        "categories": categories,
        "top_entries": all_entries[: max(top, 0)],
    }


def _print_text(report: dict[str, Any]) -> None:
    summary = report["summary"]
    print(f"AGILAB environment footprint ({report['schema']})")
    print(f"repo_root: {report['repo_root']}")
    print(f"home: {report['home']}")
    print(f"uv_link_mode: {report['uv_link_mode'] or '<not set>'}")
    print(
        "total: "
        f"{summary['unique_allocated_human']} unique allocated "
        f"({summary['raw_allocated_human']} raw category sum, "
        f"{summary['hardlink_savings_human']} hardlink/overlap savings)"
    )
    print("")
    print("Categories:")
    for category in report["categories"]:
        print(f"- {category['name']}: {category['allocated_human']} ({len(category['entries'])} entries)")
    if report["top_entries"]:
        print("")
        print("Largest entries:")
        for entry in report["top_entries"]:
            print(f"- {entry['allocated_human']}: {entry['path']}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report AGILAB install and environment footprint.")
    parser.add_argument("--repo-root", type=Path, default=None, help="Repository root to inspect.")
    parser.add_argument("--home", type=Path, default=None, help="Home directory to inspect.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    parser.add_argument("--top", type=int, default=12, help="Number of largest entries to include.")
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = build_footprint(repo_root=args.repo_root, home=args.home, top=args.top)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_text(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
