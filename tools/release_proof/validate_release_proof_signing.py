#!/usr/bin/env python3
"""Qualify release proof signing with an owned disposable Actions branch."""

from __future__ import annotations

import argparse
import base64
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import sys

if __package__:
    from tools.release_proof import create_signed_release_proof_commit as signing
else:  # pragma: no cover - direct workflow entrypoint
    import create_signed_release_proof_commit as signing


def validate_signing(
    root: Path, repository: str, source: str, run_id: str, attempt: str
) -> dict[str, object]:
    if not all(re.fullmatch(r"[1-9][0-9]*", value) for value in (run_id, attempt)):
        raise ValueError(
            "Validation requires the exact positive Actions run ID and attempt"
        )
    branch = f"automation/release-evidence-signing-validation-{run_id}-{attempt}"
    receipt: dict[str, object] = {
        "schema": "agilab.release_proof_bot_signing_validation.v1",
        "status": "fail",
        "repository": repository,
        "source": source,
        "run_id": run_id,
        "run_attempt": attempt,
        "branch": branch,
        "checked_at": datetime.now(UTC).isoformat(),
        "cleanup": "not-created-or-retained-unverified",
    }
    path = root / "CHANGELOG.md"
    original = path.read_bytes()
    try:
        path.write_bytes(
            original
            + f"\n<!-- Signing validation fixture: {run_id}/{attempt} -->\n".encode()
        )
        result = signing.create_signed_commit(
            root,
            repository,
            branch,
            source,
            message="test(release): validate server-signed proof commit",
        )
        receipt["signed_commit"] = result
        oid = str(result["commit"])
        commit = signing._github_api(f"repos/{repository}/commits/{oid}")
        if commit.get("author", {}).get("login") != "github-actions[bot]":
            raise RuntimeError("Validation requires the real github-actions[bot] token")
        receipt["github_author"] = commit["author"]["login"]
        receipt["verification"] = {
            key: commit["commit"]["verification"].get(key)
            for key in ("verified", "reason", "verified_at")
        }
        receipt["parent"] = [parent["sha"] for parent in commit["parents"]]
        receipt["blobs"] = {item["filename"]: item["sha"] for item in commit["files"]}
        ref_endpoint = f"repos/{repository}/git/ref/heads/{branch}"
        if signing._github_api(ref_endpoint)["object"]["sha"] != oid:
            raise RuntimeError(
                "Owned validation branch changed before the stale-head probe"
            )
        try:
            signing._github_api(
                "graphql",
                {
                    "query": signing.CREATE_COMMIT_MUTATION,
                    "variables": {
                        "input": {
                            "branch": {
                                "repositoryNameWithOwner": repository,
                                "branchName": branch,
                            },
                            "expectedHeadOid": source,
                            "message": {
                                "headline": "test(release): stale head must be rejected"
                            },
                            "fileChanges": {
                                "additions": [
                                    {
                                        "path": "CHANGELOG.md",
                                        "contents": base64.b64encode(
                                            path.read_bytes()
                                            + b"\n<!-- Stale-head probe must not commit -->\n"
                                        ).decode("ascii"),
                                    }
                                ]
                            },
                        }
                    },
                },
            )
        except signing.GitHubGraphQLError as exc:
            if not any(error.get("type") == "STALE_DATA" for error in exc.errors):
                raise RuntimeError(
                    "Stale-head probe failed for a different API reason"
                ) from exc
            receipt["stale_head_rejected"] = True
            receipt["stale_head_error_type"] = "STALE_DATA"
        else:
            raise RuntimeError("GitHub accepted a stale expectedHeadOid")
        # Re-read exact ownership immediately before deleting this unique branch.
        if signing._github_api(ref_endpoint)["object"]["sha"] != oid:
            raise RuntimeError(
                "Owned branch changed; refuse cleanup of a different commit"
            )
        receipt["head_after_stale_probe"] = oid
        signing._github_api(
            f"repos/{repository}/git/refs/heads/{branch}", method="DELETE"
        )
        receipt["cleanup"] = "owned-branch-deleted"
        receipt["status"] = "pass"
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        receipt["error"] = str(exc)
    finally:
        path.write_bytes(original)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = validate_signing(
        args.root, args.repository, args.source, args.run_id, args.run_attempt
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": result["status"], "receipt": str(args.output)}))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
