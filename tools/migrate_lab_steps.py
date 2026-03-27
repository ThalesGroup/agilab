#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agilab.pipeline_steps import upgrade_steps_file  # noqa: E402


def _iter_step_files(targets: list[str], pattern: str) -> list[Path]:
    candidates = [Path(target).expanduser() for target in targets] if targets else [Path.home() / "export"]
    found: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate.is_file():
            file_path = candidate.resolve()
            if file_path not in seen:
                seen.add(file_path)
                found.append(file_path)
            continue
        if not candidate.exists():
            continue
        for file_path in sorted(candidate.glob(pattern)):
            resolved = file_path.resolve()
            if resolved not in seen and resolved.is_file():
                seen.add(resolved)
                found.append(resolved)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description="Upgrade legacy exported AGILab lab_steps snippets in place.")
    parser.add_argument(
        "targets",
        nargs="*",
        help="One or more lab_steps.toml files or directories to scan. Defaults to ~/export.",
    )
    parser.add_argument(
        "--pattern",
        default="**/lab_steps.toml",
        help="Glob used when a target is a directory. Default: %(default)s",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report potential upgrades without writing changes.",
    )
    args = parser.parse_args()

    step_files = _iter_step_files(args.targets, args.pattern)
    if not step_files:
        print("No lab_steps.toml files found.")
        return 0

    total_files = 0
    total_scanned = 0
    total_changed = 0
    for steps_file in step_files:
        result = upgrade_steps_file(steps_file, write=not args.dry_run)
        total_files += result["files"]
        total_scanned += result["scanned_steps"]
        total_changed += result["changed_steps"]
        status = "would upgrade" if args.dry_run else "upgraded"
        if result["changed_steps"]:
            print(f"{status}: {steps_file} ({result['changed_steps']} step(s))")
        else:
            print(f"clean: {steps_file}")

    action = "would be upgraded" if args.dry_run else "upgraded"
    print(
        f"Scanned {len(step_files)} file(s), {total_scanned} step(s); "
        f"{total_changed} step(s) {action} across {total_files if total_changed else 0} file(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
