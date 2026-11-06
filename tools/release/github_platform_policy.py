#!/usr/bin/env python3
"""Audit or apply AGILAB's GitHub-side release and repository policy."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
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
    payload = {
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
                        for context in config.get("required_status_checks", [])
                    ],
                },
            },
        ],
    }

    if not config.get("required_status_checks"):
        payload["rules"] = [
            rule
            for rule in payload["rules"]
            if rule["type"] != "required_status_checks"
        ]
    return payload


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

    # Offline cost checks also run in fresh Mac hooks without release dependencies.
    from tools.pypi_trusted_publisher_contract import trusted_publisher_claims

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
    if policy.get("actions", {}).get("enabled") is not False:
        raise ValueError("Source policy must keep Actions disabled")
    api.request("PUT", _repo_path(policy, "actions/permissions"), {"enabled": False})
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
                "status": "pass" if _ruleset_matches(actual, desired) else "fail",
                "details": {"ruleset": desired["name"]},
            }
        )

    actions = api.request("GET", _repo_path(policy, "actions/permissions"))
    checks.append(
        {
            "name": "actions-disabled",
            "status": "pass"
            if policy.get("actions", {}).get("enabled") is False
            and actions.get("enabled") is False
            else "fail",
            "details": {
                "desired_enabled": False,
                "observed_enabled": actions.get("enabled"),
            },
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


def _ruleset_matches(actual: Any, desired: dict[str, Any]) -> bool:
    if not _contains(actual, desired):
        return False
    # Subset comparison cannot establish absence: [] used to accept all seven
    # retired checks. Compare this rule exactly while allowing API metadata.
    actual_checks = [
        r for r in actual.get("rules", []) if r.get("type") == "required_status_checks"
    ]
    expected_checks = [
        r for r in desired["rules"] if r["type"] == "required_status_checks"
    ]
    if len(actual_checks) != len(expected_checks):
        return False
    if expected_checks:

        def contexts(rule):
            return sorted(
                (row["context"], row.get("integration_id"))
                for row in rule["parameters"]["required_status_checks"]
            )

        if contexts(actual_checks[0]) != contexts(expected_checks[0]):
            return False

    def actor_identity(rows):
        return sorted(
            (r.get("actor_type"), r.get("actor_id"), r.get("bypass_mode")) for r in rows
        )

    return actor_identity(actual.get("bypass_actors", [])) == actor_identity(
        desired["bypass_actors"]
    )


def _workflow_events(text: str) -> set[str]:
    try:
        import yaml
    except ModuleNotFoundError as exc:
        if exc.name != "yaml":
            raise
        raise ModuleNotFoundError(
            "Workflow cost checks require PyYAML in the hook interpreter. "
            "Use a project .venv containing PyYAML. For a fresh checkout without "
            ".venv, prepare only the lightweight guard environment: "
            "uv venv --python 3.13 .venv; "
            "uv pip install --python .venv/bin/python PyYAML. "
            "No full project sync or Actions run is needed."
        ) from exc

    class WorkflowLoader(yaml.SafeLoader):
        pass

    WorkflowLoader.yaml_implicit_resolvers = {
        key: [
            (tag, pattern) for tag, pattern in rows if tag != "tag:yaml.org,2002:bool"
        ]
        for key, rows in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }

    def mapping(loader, node):
        result = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node)
            if (
                not isinstance(key, (str, int, float, bool))
                or key in result
                or key == "<<"
            ):
                raise ValueError("duplicate or unsupported YAML mapping declaration")
            result[key] = loader.construct_object(value_node)
        return result

    WorkflowLoader.add_constructor("tag:yaml.org,2002:map", mapping)
    try:
        payload = yaml.load(text, Loader=WorkflowLoader)
    except yaml.YAMLError as exc:
        raise ValueError("malformed workflow YAML") from exc
    if not isinstance(payload, dict) or "on" not in payload:
        raise ValueError("workflow must declare exactly one on event")
    declaration = payload["on"]
    if isinstance(declaration, str):
        events = {declaration}
    elif isinstance(declaration, list):
        if any(not isinstance(item, str) for item in declaration) or len(
            set(declaration)
        ) != len(declaration):
            raise ValueError("invalid or duplicate workflow events")
        events = set(declaration)
    elif isinstance(declaration, dict):
        events = set(declaration)
        if any(
            value is not None and not isinstance(value, dict)
            for value in declaration.values()
        ):
            raise ValueError("malformed workflow event configuration")
    else:
        raise ValueError("malformed workflow on declaration")
    if events != {"workflow_dispatch"}:
        raise ValueError(
            "only explicit workflow_dispatch is allowed; automatic Actions are prohibited"
        )
    return events


def _git_bytes(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.PIPE)


def _workflow_inputs(root: Path, ref: str | None) -> tuple[bytes, dict[str, str]]:
    if ref is None:
        directory = root / ".github/workflows"
        if directory.is_symlink():
            raise ValueError("workflow directory must not be a symlink")
        files = {}
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                raise ValueError("workflow directory contains a symlink")
            if path.suffix.lower() in {".yaml", ".yml"}:
                if path.is_symlink() or not path.is_file():
                    raise ValueError(f"workflow must be a regular file: {path}")
                files[path.relative_to(root).as_posix()] = path.read_text(
                    encoding="utf-8"
                )
        return (root / ".github/platform-policy.json").read_bytes(), files
    commit = (
        _git_bytes(root, "rev-parse", "--verify", ref + "^{commit}").decode().strip()
    )
    if not re.fullmatch(r"[0-9a-f]{40,64}", commit):
        raise ValueError("invalid nominated commit identity")
    policy = _git_bytes(root, "show", commit + ":.github/platform-policy.json")
    files = {}
    for entry in _git_bytes(
        root, "ls-tree", "-r", "-z", commit, "--", ".github/workflows"
    ).split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode, kind, oid = metadata.decode().split()
        path = raw_path.decode()
        if Path(path).suffix.lower() not in {".yaml", ".yml"}:
            continue
        if mode not in {"100644", "100755"} or kind != "blob":
            raise ValueError(f"nominated workflow must be a regular blob: {path}")
        files[path] = _git_bytes(root, "cat-file", "blob", oid).decode("utf-8")
    return policy, files


def check_workflow_cost(root: Path, *, ref: str | None = None) -> dict[str, Any]:
    failures = []
    count = 0
    try:
        policy_raw, workflows = _workflow_inputs(root, ref)

        def unique_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate platform policy key")
                result[key] = value
            return result

        policy = json.loads(policy_raw, object_pairs_hook=unique_pairs)
        if policy.get("actions", {}).get("enabled") is not False:
            failures.append("desired repository Actions must remain disabled")
        checks = policy.get("main_ruleset", {}).get("required_status_checks", [])
        if checks != []:
            failures.append("portable CI status checks must not be required")
        if not workflows:
            failures.append("workflow inventory is missing or empty")
        for name, text in workflows.items():
            count += 1
            try:
                _workflow_events(text)
            except (ValueError, TypeError) as exc:
                failures.append(f"{name}: {exc}")
    except (
        OSError,
        ValueError,
        TypeError,
        AttributeError,
        subprocess.SubprocessError,
        ImportError,
    ) as exc:
        failures.append(f"workflow policy unavailable: {exc}")
    # YAML parser exceptions are converted below in the per-workflow wrapper.
    return {
        "schema": "agilab.workflow_cost_policy.v1",
        "ref": ref or "working-tree",
        "status": "fail" if failures else "pass",
        "workflow_count": count,
        "failures": failures,
    }


def check_pushed_workflow_cost(root: Path, push_spec: Path) -> list[dict[str, Any]]:
    from tools.pre_push_changed_files import parse_pre_push_records

    text = push_spec.read_text(encoding="utf-8")
    records = parse_pre_push_records(text)
    if not records or len(records) != len(
        [line for line in text.splitlines() if line.strip()]
    ):
        raise ValueError("missing or malformed nominated pre-push records")
    reports = []
    for _local_ref, local_sha, _remote_ref, _remote_sha in records:
        if not re.fullmatch(r"[0-9a-f]{40,64}", local_sha):
            raise ValueError("invalid nominated local commit")
        if set(local_sha) == {"0"}:
            continue  # Deletion starts no Actions; real service protections still apply.
        reports.append(check_workflow_cost(root, ref=local_sha))
    return reports


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    parser.add_argument(
        "--check-workflow-cost",
        action="store_true",
        help="Offline default-deny workflow cost policy; never contacts GitHub",
    )
    parser.add_argument("--pre-push-spec", type=Path)
    parser.add_argument("--ref", action="append", default=[])
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the checked-in policy before auditing it.",
    )
    parser.add_argument("--compact", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.check_workflow_cost:
        if args.apply:
            raise ValueError("offline workflow policy cannot apply service changes")
        try:
            reports = (
                check_pushed_workflow_cost(REPO_ROOT, args.pre_push_spec)
                if args.pre_push_spec
                else [
                    check_workflow_cost(REPO_ROOT, ref=ref)
                    for ref in (args.ref or [None])
                ]
            )
            print(
                json.dumps(
                    {"checks": reports, "live_api_contacted": False}, sort_keys=True
                )
            )
            return 0 if all(report["status"] == "pass" for report in reports) else 1
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
    policy = load_policy(args.policy)
    api = GhApi()
    if args.apply:
        apply_policy(api, policy)
    report = audit_policy(api, policy)
    print(json.dumps(report, sort_keys=True) if args.compact else json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
