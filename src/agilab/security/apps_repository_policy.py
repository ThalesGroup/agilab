"""Shared trust policy for executable external AGILAB app repositories."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

APPS_ALLOWLIST_ENV = "AGILAB_APPS_REPOSITORY_ALLOWLIST"
APPS_ALLOWLIST_FILE_ENV = "AGILAB_APPS_REPOSITORY_ALLOWLIST_FILE"
HEX_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class AppsRepositoryPolicyResult:
    """One deterministic decision shared by installers and security checks."""

    status: str
    summary: str
    remediation: str
    details: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _resolve_path(raw_path: str | None, *, cwd: Path) -> Path | None:
    value = str(raw_path or "").strip().strip("'\"")
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = cwd / path
    return path.resolve(strict=False)


def _resolve_git_dir(repo: Path) -> Path | None:
    dot_git = repo / ".git"
    if dot_git.is_dir():
        return dot_git
    if dot_git.is_file():
        text = dot_git.read_text(encoding="utf-8", errors="ignore").strip()
        if text.startswith("gitdir:"):
            git_dir = Path(text.split(":", 1)[1].strip()).expanduser()
            if not git_dir.is_absolute():
                git_dir = dot_git.parent / git_dir
            return git_dir.resolve(strict=False)
    return None


def _git_common_dir(git_dir: Path) -> Path:
    common_file = git_dir / "commondir"
    if not common_file.is_file():
        return git_dir
    raw = common_file.read_text(encoding="utf-8", errors="ignore").strip()
    common = Path(raw).expanduser()
    if not common.is_absolute():
        common = git_dir / common
    return common.resolve(strict=False)


def _git_config_value(repo: Path, section: str, key: str) -> str | None:
    """Read a simple Git config value, including linked-worktree configs."""

    git_dir = _resolve_git_dir(repo)
    if git_dir is None:
        return None
    config_path = _git_common_dir(git_dir) / "config"
    if not config_path.is_file():
        return None
    current_section: str | None = None
    for raw_line in config_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1].strip()
            continue
        if current_section != section or "=" not in line:
            continue
        raw_key, raw_value = line.split("=", 1)
        if raw_key.strip() == key:
            return raw_value.strip()
    return None


def _git_origin_url(repo: Path) -> str | None:
    return _git_config_value(repo, 'remote "origin"', "url")


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    git_env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    git_env.update(
        {
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    try:
        return subprocess.run(
            [
                "git",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.untrackedCache=false",
                "-C",
                str(repo),
                *args,
            ],
            check=False,
            capture_output=True,
            env=git_env,
            text=True,
        )
    except OSError:
        return None


def _verified_git_state(repo: Path) -> tuple[dict[str, Any], str | None]:
    probe = _run_git(repo, "rev-parse", "--is-inside-work-tree")
    if probe is None or probe.returncode != 0 or probe.stdout.strip() != "true":
        return {"is_git_checkout": False, "git_verified": False}, None
    branch = _run_git(repo, "symbolic-ref", "--quiet", "--short", "HEAD")
    head = _run_git(repo, "rev-parse", "--verify", "HEAD^{commit}")
    origin = _run_git(repo, "config", "--local", "--get", "remote.origin.url")
    worktree = _run_git(
        repo,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--ignored=matching",
    )
    origin_url = (
        origin.stdout.strip()
        if origin is not None and origin.returncode == 0 and origin.stdout.strip()
        else None
    )
    worktree_clean = bool(
        worktree is not None
        and worktree.returncode == 0
        and not worktree.stdout.strip()
    )
    if head is None or head.returncode != 0 or not HEX_SHA_RE.match(head.stdout.strip()):
        return (
            {
                "is_git_checkout": True,
                "git_verified": True,
                "head_state": "unknown",
                "worktree_clean": worktree_clean,
            },
            origin_url,
        )
    if branch is not None and branch.returncode == 0 and branch.stdout.strip():
        return (
            {
                "is_git_checkout": True,
                "git_verified": True,
                "head_state": "branch",
                "name": branch.stdout.strip(),
                "worktree_clean": worktree_clean,
            },
            origin_url,
        )
    return (
        {
            "is_git_checkout": True,
            "git_verified": True,
            "head_state": "detached",
            "commit": head.stdout.strip(),
            "worktree_clean": worktree_clean,
        },
        origin_url,
    )


def _redact_url(value: str | None) -> str | None:
    if not value:
        return value
    return re.sub(r"(https?://)[^/@:\s]+(:[^/@\s]+)?@", r"\1<redacted>@", value)


def _split_allowlist(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[\n,;]", value) if item.strip()]


def apps_repository_allowlist(config: Mapping[str, str], *, cwd: Path) -> list[str]:
    """Return exact reviewed origin URLs from the env and optional file."""

    allowlist = _split_allowlist(str(config.get(APPS_ALLOWLIST_ENV) or ""))
    file_path = _resolve_path(config.get(APPS_ALLOWLIST_FILE_ENV), cwd=cwd)
    if file_path and file_path.is_file():
        for raw_line in file_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if line and not line.startswith("#"):
                allowlist.extend(_split_allowlist(line))
    return sorted(set(allowlist))


def _git_head_state(repo: Path) -> dict[str, Any]:
    git_dir = _resolve_git_dir(repo)
    if git_dir is None:
        return {"is_git_checkout": False}
    head_path = git_dir / "HEAD"
    if not head_path.is_file():
        return {"is_git_checkout": True, "head_state": "unknown"}
    head = head_path.read_text(encoding="utf-8", errors="ignore").strip()
    if head.startswith("ref:"):
        ref = head.split(":", 1)[1].strip()
        short = ref.removeprefix("refs/heads/").removeprefix("refs/tags/")
        return {
            "is_git_checkout": True,
            "head_state": "branch" if ref.startswith("refs/heads/") else "ref",
            "ref": ref,
            "name": short,
        }
    if HEX_SHA_RE.match(head):
        return {"is_git_checkout": True, "head_state": "detached", "commit": head}
    return {"is_git_checkout": True, "head_state": "unknown", "head": head[:64]}


def evaluate_apps_repository_policy(
    config: Mapping[str, str],
    *,
    cwd: Path,
    strict: bool | None = None,
    allow_floating: bool | None = None,
) -> AppsRepositoryPolicyResult:
    """Evaluate one repository using the same policy on every installer surface."""

    path = _resolve_path(config.get("APPS_REPOSITORY"), cwd=cwd)
    if strict is None:
        strict = _truthy(config.get("AGILAB_STRICT_APPS_REPOSITORY")) or _truthy(
            config.get("AGILAB_SHARED_MODE")
        )
    if allow_floating is None:
        allow_floating = _truthy(config.get("AGILAB_ALLOW_FLOATING_APPS_REPOSITORY")) or _truthy(
            config.get("AGILAB_DEV_APPS_REPOSITORY")
        )
    allowlist = apps_repository_allowlist(config, cwd=cwd)
    base_details: dict[str, Any] = {
        "path": str(path) if path else None,
        "strict": strict,
        "allow_floating": allow_floating,
        "allowlist_configured": bool(allowlist),
        "allowlist_size": len(allowlist),
    }
    if path is None:
        return AppsRepositoryPolicyResult(
            "pass",
            "APPS_REPOSITORY is not configured.",
            "No action required unless you install external apps.",
            base_details,
        )
    if not path.exists():
        return AppsRepositoryPolicyResult(
            "fail" if strict else "warn",
            "APPS_REPOSITORY points to a missing path.",
            "Point APPS_REPOSITORY to an allowlisted reviewed checkout pinned to an immutable revision.",
            base_details,
        )
    if not path.is_dir():
        return AppsRepositoryPolicyResult(
            "fail" if strict else "warn",
            "APPS_REPOSITORY is not a directory.",
            "Use a reviewed Git checkout directory for external apps.",
            base_details,
        )

    git_state, origin_url = _verified_git_state(path)
    details = {**base_details, **git_state}
    if not git_state.get("is_git_checkout"):
        return AppsRepositoryPolicyResult(
            "fail" if strict else "warn",
            "APPS_REPOSITORY is not a Git checkout.",
            "Use an allowlisted Git checkout pinned to a commit SHA or immutable tag before shared use.",
            details,
        )

    details["origin_url"] = _redact_url(origin_url)
    if strict and not origin_url:
        return AppsRepositoryPolicyResult(
            "fail",
            "APPS_REPOSITORY is pinned but has no origin URL to match against an allowlist.",
            "Configure a reviewed origin URL before installing external apps in a shared environment.",
            details,
        )
    if strict and not allowlist:
        return AppsRepositoryPolicyResult(
            "fail",
            "Strict APPS_REPOSITORY mode requires an origin allowlist.",
            (
                f"Set {APPS_ALLOWLIST_ENV} or {APPS_ALLOWLIST_FILE_ENV} to the exact "
                "reviewed repository origin URL."
            ),
            details,
        )
    if strict and origin_url not in allowlist:
        return AppsRepositoryPolicyResult(
            "fail",
            "APPS_REPOSITORY origin is not in the configured allowlist.",
            (
                f"Add the exact reviewed origin URL to {APPS_ALLOWLIST_ENV} or "
                f"{APPS_ALLOWLIST_FILE_ENV}, then rerun the gate."
            ),
            details,
        )

    if git_state.get("head_state") == "unknown":
        return AppsRepositoryPolicyResult(
            "fail" if strict else "warn",
            "APPS_REPOSITORY does not resolve to a committed Git revision.",
            "Checkout a reviewed commit SHA or immutable tag before installing external apps.",
            details,
        )

    if not git_state.get("worktree_clean"):
        if strict and not allow_floating:
            return AppsRepositoryPolicyResult(
                "fail",
                "APPS_REPOSITORY contains unreviewed working-tree content (modified, untracked, or ignored).",
                (
                    "Restore a clean reviewed checkout, or use AGILAB_DEV_APPS_REPOSITORY=1 "
                    "only for an explicit development install."
                ),
                details,
            )
        return AppsRepositoryPolicyResult(
            "warn",
            "APPS_REPOSITORY contains unreviewed working-tree content (modified, untracked, or ignored).",
            "Restore a clean reviewed checkout before shared use.",
            details,
        )

    if git_state.get("head_state") == "branch":
        branch = str(git_state.get("name") or "")
        if strict and not allow_floating:
            return AppsRepositoryPolicyResult(
                "fail",
                f"APPS_REPOSITORY is on floating branch '{branch}'.",
                (
                    "Checkout a reviewed commit SHA or immutable tag, or set "
                    "AGILAB_DEV_APPS_REPOSITORY=1 only for an explicit development install."
                ),
                details,
            )
        return AppsRepositoryPolicyResult(
            "warn",
            f"APPS_REPOSITORY is on floating branch '{branch}'.",
            "Pin the checkout to a reviewed commit or immutable tag before shared use.",
            details,
        )

    if allowlist and origin_url and origin_url not in allowlist:
        return AppsRepositoryPolicyResult(
            "warn",
            "APPS_REPOSITORY origin is not in the configured allowlist.",
            f"Add the exact reviewed origin URL to {APPS_ALLOWLIST_ENV} before shared use.",
            details,
        )
    return AppsRepositoryPolicyResult(
        "pass",
        (
            "APPS_REPOSITORY is pinned and allowlisted."
            if strict
            else "APPS_REPOSITORY is a Git checkout and is not on a floating branch."
        ),
        "Keep the referenced commit reviewed and scanned.",
        details,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate an external AGILAB apps repository.")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    config = dict(os.environ)
    config["APPS_REPOSITORY"] = args.repository
    result = evaluate_apps_repository_policy(config, cwd=Path.cwd())
    if args.json:
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
    else:
        stream = sys.stderr if result.status == "fail" else sys.stdout
        marker = {"pass": "OK", "warn": "Warning", "fail": "Error"}[result.status]
        print(f"{marker}: {result.summary}", file=stream)
        if result.status != "pass":
            print(result.remediation, file=stream)
    return 1 if result.status == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
