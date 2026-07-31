#!/usr/bin/env python3
"""Audit or apply AGILAB's GitHub-side release and repository policy."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

try:
    from tools.pypi_trusted_publisher_contract import trusted_publisher_claims
except ModuleNotFoundError:  # pragma: no cover - direct tools/ script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from pypi_trusted_publisher_contract import trusted_publisher_claims


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY_PATH = REPO_ROOT / ".github" / "platform-policy.json"
SCHEMA = "agilab.github_platform_policy.v1"


class GhApi:
    """Small JSON wrapper around the authenticated GitHub CLI."""

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        argv = ["gh", "api", "--method", method, path]
        if payload is not None:
            argv.extend(["--input", "-"])
        completed = subprocess.run(
            argv,
            input=json.dumps(payload) if payload is not None else None,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(f"GitHub API {method} {path} failed: {detail}")
        output = completed.stdout.strip()
        return json.loads(output) if output else None


def load_policy(path: Path = DEFAULT_POLICY_PATH) -> dict[str, Any]:
    policy = json.loads(path.read_text(encoding="utf-8"))
    if policy.get("schema") != SCHEMA:
        raise ValueError(f"unsupported GitHub platform policy schema: {policy.get('schema')!r}")
    if not policy.get("repository"):
        raise ValueError("GitHub platform policy requires repository")
    return policy


def _repo_path(policy: dict[str, Any], suffix: str) -> str:
    return f"repos/{policy['repository']}/{suffix.lstrip('/')}"


def _team(api: GhApi, policy: dict[str, Any], slug: str) -> dict[str, Any]:
    owner = str(policy["repository"]).split("/", 1)[0]
    return api.request("GET", f"orgs/{owner}/teams/{quote(slug, safe='')}")


def desired_main_ruleset(policy: dict[str, Any]) -> dict[str, Any]:
    config = policy["main_ruleset"]
    return {
        "name": config["name"],
        "target": "branch",
        "enforcement": "active",
        "bypass_actors": [],
        "conditions": {
            "ref_name": {"include": ["refs/heads/main"], "exclude": []},
        },
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {"type": "required_signatures"},
            {
                "type": "pull_request",
                "parameters": {
                    "dismiss_stale_reviews_on_push": True,
                    "require_code_owner_review": False,
                    "require_last_push_approval": True,
                    "required_approving_review_count": 1,
                    "required_review_thread_resolution": True,
                    "allowed_merge_methods": ["squash", "merge", "rebase"],
                },
            },
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": True,
                    "do_not_enforce_on_create": False,
                    "required_status_checks": [
                        {"context": context}
                        for context in config["required_status_checks"]
                    ],
                },
            },
        ],
    }


def desired_tag_ruleset(policy: dict[str, Any], team_id: int) -> dict[str, Any]:
    config = policy["release_tag_ruleset"]
    return {
        "name": config["name"],
        "target": "tag",
        "enforcement": "active",
        "bypass_actors": [
            {
                "actor_id": team_id,
                "actor_type": "Team",
                "bypass_mode": "always",
            }
        ],
        "conditions": {
            "ref_name": {"include": ["refs/tags/v*.*.*"], "exclude": []},
        },
        "rules": [
            {"type": "creation"},
            {"type": "update"},
            {"type": "deletion"},
            {"type": "non_fast_forward"},
        ],
    }


def _environment_payload(
    environment: dict[str, Any] | None,
    *,
    reviewer: dict[str, Any] | None = None,
    prevent_self_review: bool = False,
) -> dict[str, Any]:
    wait_timer = 0
    reviewers: list[dict[str, Any]] = []
    existing_prevent_self_review = False
    for rule in (environment or {}).get("protection_rules") or []:
        if rule.get("type") == "wait_timer":
            wait_timer = int(rule.get("wait_timer") or 0)
        elif rule.get("type") == "required_reviewers":
            existing_prevent_self_review = bool(rule.get("prevent_self_review"))
            for row in rule.get("reviewers") or []:
                resolved = row.get("reviewer") or row
                if resolved.get("id") and resolved.get("type"):
                    reviewers.append(
                        {"id": int(resolved["id"]), "type": str(resolved["type"])}
                    )
    if reviewer is not None:
        reviewers = [{"id": int(reviewer["id"]), "type": str(reviewer["type"])}]
    return {
        "wait_timer": wait_timer,
        "prevent_self_review": prevent_self_review or existing_prevent_self_review,
        "reviewers": reviewers,
        "deployment_branch_policy": {
            "protected_branches": False,
            "custom_branch_policies": True,
        },
    }


def _custom_policies(api: GhApi, policy: dict[str, Any], environment: str) -> list[dict[str, Any]]:
    encoded = quote(environment, safe="")
    result = api.request(
        "GET",
        _repo_path(policy, f"environments/{encoded}/deployment-branch-policies?per_page=100"),
    )
    return list((result or {}).get("branch_policies") or [])


def _ensure_custom_policies(api: GhApi, policy: dict[str, Any], environment: str) -> None:
    encoded = quote(environment, safe="")
    existing = _custom_policies(api, policy, environment)
    desired = {
        (str(row["name"]), str(row["type"]))
        for row in policy["deployment_ref_policies"]
    }
    existing_identities = {
        (str(row.get("name")), str(row.get("type")))
        for row in existing
    }
    for row in existing:
        identity = (str(row.get("name")), str(row.get("type")))
        if identity in desired:
            continue
        policy_id = int(row["id"])
        api.request(
            "DELETE",
            _repo_path(
                policy,
                f"environments/{encoded}/deployment-branch-policies/{policy_id}",
            ),
        )
    for name, policy_type in sorted(desired - existing_identities):
        api.request(
            "POST",
            _repo_path(policy, f"environments/{encoded}/deployment-branch-policies"),
            {"name": name, "type": policy_type},
        )


def _environment_names(api: GhApi, policy: dict[str, Any]) -> list[str]:
    result = api.request("GET", _repo_path(policy, "environments?per_page=100"))
    return sorted(str(row["name"]) for row in (result or {}).get("environments") or [])


def expected_pypi_environment_names() -> set[str]:
    """Return every environment in the checked-in trusted-publisher contract."""

    return {claim.environment for claim in trusted_publisher_claims()}


def _rulesets(api: GhApi, policy: dict[str, Any]) -> list[dict[str, Any]]:
    result = api.request("GET", _repo_path(policy, "rulesets?per_page=100"))
    return list(result or [])


def _upsert_ruleset(api: GhApi, policy: dict[str, Any], payload: dict[str, Any]) -> None:
    existing = next((row for row in _rulesets(api, policy) if row.get("name") == payload["name"]), None)
    if existing is None:
        api.request("POST", _repo_path(policy, "rulesets"), payload)
    else:
        api.request("PUT", _repo_path(policy, f"rulesets/{existing['id']}"), payload)


def apply_policy(api: GhApi, policy: dict[str, Any]) -> None:
    approval = policy["release_approval_environment"]
    reviewer_team = _team(api, policy, approval["reviewer_team"])
    admin_team = _team(api, policy, policy["release_tag_ruleset"]["bypass_team"])
    existing_environment_names = set(_environment_names(api, policy))
    environment_names = sorted(
        existing_environment_names | expected_pypi_environment_names()
    )
    approval_name = str(approval["name"])
    if approval_name not in environment_names:
        environment_names.append(approval_name)

    for name in sorted(environment_names):
        if not (name.startswith(str(policy["pypi_environment_prefix"])) or name == approval_name):
            continue
        encoded = quote(name, safe="")
        current = (
            api.request("GET", _repo_path(policy, f"environments/{encoded}"))
            if name in existing_environment_names
            else None
        )
        reviewer = None
        prevent_self_review = False
        if name == approval_name:
            reviewer = {"id": reviewer_team["id"], "type": "Team"}
            prevent_self_review = bool(approval["prevent_self_review"])
        api.request(
            "PUT",
            _repo_path(policy, f"environments/{encoded}"),
            _environment_payload(
                current,
                reviewer=reviewer,
                prevent_self_review=prevent_self_review,
            ),
        )
        _ensure_custom_policies(api, policy, name)

    _upsert_ruleset(api, policy, desired_main_ruleset(policy))
    _upsert_ruleset(api, policy, desired_tag_ruleset(policy, int(admin_team["id"])))

    active_names = {policy["main_ruleset"]["name"], policy["release_tag_ruleset"]["name"]}
    for ruleset in _rulesets(api, policy):
        if ruleset.get("name") in policy.get("retire_rulesets", []) and ruleset.get("name") not in active_names:
            api.request("DELETE", _repo_path(policy, f"rulesets/{ruleset['id']}"))


def _contains(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _contains(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return False
        return all(any(_contains(candidate, item) for candidate in actual) for item in expected)
    return actual == expected


def audit_policy(api: GhApi, policy: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    approval = policy["release_approval_environment"]
    approval_name = str(approval["name"])
    reviewer_team = _team(api, policy, approval["reviewer_team"])
    admin_team = _team(api, policy, policy["release_tag_ruleset"]["bypass_team"])
    names = _environment_names(api, policy)
    expected_refs = {
        (str(row["name"]), str(row["type"]))
        for row in policy["deployment_ref_policies"]
    }
    relevant_names = sorted(
        name
        for name in set(names) | expected_pypi_environment_names()
        if name.startswith(str(policy["pypi_environment_prefix"])) or name == approval_name
    )
    environment_failures: list[str] = []
    for name in relevant_names:
        try:
            env = api.request("GET", _repo_path(policy, f"environments/{quote(name, safe='')}"))
        except RuntimeError:
            environment_failures.append(name)
            continue
        branch_policy = env.get("deployment_branch_policy") or {}
        refs = {
            (str(row.get("name")), str(row.get("type")))
            for row in _custom_policies(api, policy, name)
        }
        if not branch_policy.get("custom_branch_policies") or refs != expected_refs:
            environment_failures.append(name)
    checks.append(
        {
            "name": "pypi-environment-ref-policies",
            "status": "pass" if relevant_names and not environment_failures else "fail",
            "details": {"environment_count": len(relevant_names), "failures": environment_failures},
        }
    )

    approval_ok = False
    if approval_name in names:
        env = api.request("GET", _repo_path(policy, f"environments/{quote(approval_name, safe='')}"))
        for rule in env.get("protection_rules") or []:
            reviewers = [row.get("reviewer") or row for row in rule.get("reviewers") or []]
            if (
                rule.get("type") == "required_reviewers"
                and bool(rule.get("prevent_self_review"))
                and any(int(row.get("id") or 0) == int(reviewer_team["id"]) for row in reviewers)
            ):
                approval_ok = True
                break
    checks.append(
        {
            "name": "release-approval-environment",
            "status": "pass" if approval_ok else "fail",
            "details": {"environment": approval_name, "reviewer_team": approval["reviewer_team"]},
        }
    )

    summaries = _rulesets(api, policy)
    for label, desired in (
        ("main-ruleset", desired_main_ruleset(policy)),
        ("release-tag-ruleset", desired_tag_ruleset(policy, int(admin_team["id"]))),
    ):
        summary = next((row for row in summaries if row.get("name") == desired["name"]), None)
        actual = (
            api.request("GET", _repo_path(policy, f"rulesets/{summary['id']}"))
            if summary is not None
            else None
        )
        checks.append(
            {
                "name": label,
                "status": "pass" if _contains(actual, desired) else "fail",
                "details": {"ruleset": desired["name"]},
            }
        )

    failed = [check["name"] for check in checks if check["status"] != "pass"]
    return {
        "schema": SCHEMA,
        "repository": policy["repository"],
        "status": "pass" if not failed else "fail",
        "checks": checks,
        "failed_checks": failed,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    parser.add_argument("--apply", action="store_true", help="Apply the checked-in policy before auditing it.")
    parser.add_argument("--compact", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    policy = load_policy(args.policy)
    api = GhApi()
    if args.apply:
        apply_policy(api, policy)
    report = audit_policy(api, policy)
    print(json.dumps(report, sort_keys=True) if args.compact else json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
