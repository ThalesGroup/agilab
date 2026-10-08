#!/usr/bin/env python3
"""Create a verified, server-signed commit for the release evidence PR."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


RELEASE_METADATA_PATHS = (
    "CHANGELOG.md",
    "badges/pypi-version-agilab.svg",
    "docs/source/data/release_proof.toml",
    "docs/source/release-proof.rst",
    "docs/.docs_source_mirror_stamp.json",
)
CREATE_COMMIT_MUTATION = """
mutation($input: CreateCommitOnBranchInput!) {
  createCommitOnBranch(input: $input) {
    commit { oid }
    ref { target { oid } }
  }
}
"""


class GitHubGraphQLError(RuntimeError):
    def __init__(self, endpoint: str, errors: list[dict[str, Any]]) -> None:
        super().__init__(f"GitHub rejected the release evidence request: {endpoint}")
        self.errors = errors


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], text=True, capture_output=True, check=False
    )
    if result.returncode:
        raise RuntimeError(f"Git release evidence inspection failed: {args[0]}")
    return result.stdout


def _github_api(
    endpoint: str, payload: dict[str, Any] | None = None, *, method: str | None = None
) -> dict[str, Any]:
    argv = ["gh", "api", endpoint]
    if method or payload is not None:
        argv.extend(["--method", method or "POST"])
    if payload is not None:
        argv.extend(["--input", "-"])
    result = subprocess.run(
        argv,
        input=json.dumps(payload) if payload is not None else None,
        text=True,
        capture_output=True,
        check=False,
    )
    try:
        response = json.loads(result.stdout)
    except ValueError:
        response = None
    if isinstance(response, dict) and response.get("errors"):
        raise GitHubGraphQLError(endpoint, response["errors"])
    if result.returncode:
        # Never echo a credential, request body, or potentially sensitive CLI log.
        raise RuntimeError(
            f"GitHub release evidence request failed: {endpoint}; "
            "check authentication and repository Contents: write permission"
        )
    if method == "DELETE" and not result.stdout.strip():
        return {}
    if not isinstance(response, dict):
        raise RuntimeError(f"GitHub rejected the release evidence request: {endpoint}")
    return response


def create_signed_commit(
    root: Path,
    repository: str,
    branch: str,
    expected_head: str,
    message: str = "docs(release): record HF Space sync",
) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Expected a GitHub OWNER/REPOSITORY name")
    if not re.fullmatch(r"automation/release-evidence-[A-Za-z0-9_.-]+", branch):
        raise ValueError("Only a new automation/release-evidence-* branch is permitted")
    if not re.fullmatch(r"[0-9a-f]{40}", expected_head):
        raise ValueError("Expected a full lowercase source commit SHA")
    if _git(root, "rev-parse", "HEAD").strip() != expected_head:
        raise ValueError("Release evidence checkout differs from expected source HEAD")

    changed = sorted(
        filter(
            None,
            _git(
                root,
                "diff",
                "--no-ext-diff",
                "--no-textconv",
                "--no-renames",
                "--name-only",
                "-z",
                expected_head,
                "--",
            ).split("\0"),
        )
    )
    if not changed or not set(changed) <= set(RELEASE_METADATA_PATHS):
        raise ValueError("Changes must be limited to the five release evidence paths")
    additions = []
    expected_blobs = {}
    for name in changed:
        path = root / name
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o111:
            raise ValueError(
                f"Release evidence must be a regular, non-executable file: {name}"
            )
        entry = _git(root, "ls-tree", expected_head, "--", name)
        if not entry.startswith("100644 blob "):
            raise ValueError(
                f"Release evidence path is absent or has an unsupported mode: {name}"
            )
        content = path.read_bytes()
        additions.append(
            {"path": name, "contents": base64.b64encode(content).decode("ascii")}
        )
        expected_blobs[name] = hashlib.sha1(
            b"blob " + str(len(content)).encode("ascii") + b"\0" + content
        ).hexdigest()

    # A unique review branch is created, never an existing branch/tag overwritten.
    ref = _github_api(
        f"repos/{repository}/git/refs",
        {"ref": f"refs/heads/{branch}", "sha": expected_head},
    )
    if ref.get("object", {}).get("sha") != expected_head:
        raise RuntimeError("GitHub created the review branch at an unexpected commit")
    response = _github_api(
        "graphql",
        {
            "query": CREATE_COMMIT_MUTATION,
            "variables": {
                "input": {
                    "branch": {
                        "repositoryNameWithOwner": repository,
                        "branchName": branch,
                    },
                    "expectedHeadOid": expected_head,
                    "message": {"headline": message},
                    "fileChanges": {"additions": additions},
                }
            },
        },
    )
    created = response.get("data", {}).get("createCommitOnBranch") or {}
    oid = created.get("commit", {}).get("oid", "")
    if (
        not re.fullmatch(r"[0-9a-f]{40}", oid)
        or created.get("ref", {}).get("target", {}).get("oid") != oid
    ):
        raise RuntimeError("GitHub did not return the expected committed review branch")

    commit = _github_api(f"repos/{repository}/commits/{oid}")
    verification = commit.get("commit", {}).get("verification", {})
    actual_blobs = {item["filename"]: item["sha"] for item in commit.get("files", [])}
    if (
        commit.get("sha") != oid
        or [parent["sha"] for parent in commit.get("parents", [])] != [expected_head]
        or actual_blobs != expected_blobs
    ):
        raise RuntimeError(
            "Server commit parent or release evidence blobs differ from the request"
        )
    if (
        verification.get("verified") is not True
        or verification.get("reason") != "valid"
    ):
        raise RuntimeError(
            "GitHub did not verify the server-signed release evidence commit; "
            "stop before creating the PR or dispatching checks"
        )
    return {
        "branch": branch,
        "commit": oid,
        "parent": expected_head,
        "verified": True,
        "verification_reason": "valid",
        "files": changed,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = create_signed_commit(
            args.root, args.repository, args.branch, args.expected_head
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Release evidence commit failed: {exc}", file=sys.stderr)
        return 1
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as output:
            output.write(f"release_commit={result['commit']}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
