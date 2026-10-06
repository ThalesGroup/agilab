"""Verify a pre-existing release tag against the immutable publication source."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path


def validate_release_tag(repo_root: Path, tag: str, expected_commit: str) -> dict[str, str]:
    tag = tag.removeprefix("refs/tags/")
    if not tag.startswith("v"):
        tag = f"v{tag}"
    if not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
        raise ValueError("Publication source must be a complete commit SHA.")
    ref = f"refs/tags/{tag}"
    git_env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    checked = subprocess.run(
        ["git", "-C", str(repo_root), "check-ref-format", ref],
        capture_output=True, text=True, check=False, env=git_env,
    )
    if checked.returncode:
        raise ValueError("Invalid release tag reference.")
    resolved = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--verify", "--quiet",
         "--end-of-options", f"{ref}^{{commit}}"],
        capture_output=True, text=True, check=False, env=git_env,
    )
    if resolved.returncode:
        raise ValueError(
            f"Release tag {tag} is missing or does not resolve to a commit. "
            "Create it on the publication source using an authorized account before publishing."
        )
    actual = resolved.stdout.strip()
    if actual != expected_commit:
        raise ValueError(
            f"Release tag {tag} resolves to {actual}, expected {expected_commit}. "
            "Published release tags must not be moved."
        )
    return {"release_tag": tag, "release_commit": actual}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--tag", required=True)
    parser.add_argument("--expected-commit", required=True)
    args = parser.parse_args(argv)
    try:
        result = validate_release_tag(args.repo_root, args.tag, args.expected_commit)
    except ValueError as exc:
        parser.exit(2, f"{exc}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
