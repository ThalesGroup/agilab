from __future__ import annotations

import importlib.util
import json
import pytest
import sys
from pathlib import Path


MODULE_PATH = Path("tools/release/github_platform_policy.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("github_platform_policy_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_checked_in_platform_policy_builds_fail_closed_rulesets() -> None:
    module = _load_module()
    policy = module.load_policy()

    main = module.desired_main_ruleset(policy)
    tag = module.desired_tag_ruleset(policy, 42)

    assert main["enforcement"] == "active"
    assert main["conditions"]["ref_name"]["include"] == ["refs/heads/main"]
    assert {rule["type"] for rule in main["rules"]} >= {
        "deletion",
        "non_fast_forward",
        "required_signatures",
        "pull_request",
    }
    pull_request = next(rule for rule in main["rules"] if rule["type"] == "pull_request")
    assert pull_request["parameters"]["required_approving_review_count"] == 1
    assert pull_request["parameters"]["require_last_push_approval"] is True
    assert not any(rule["type"] == "required_status_checks" for rule in main["rules"])
    assert policy["actions"]["enabled"] is False
    assert tag["enforcement"] == "active"
    assert tag["conditions"]["ref_name"]["include"] == ["refs/tags/v*.*.*"]
    assert tag["bypass_actors"] == [
        {"actor_id": 42, "actor_type": "Team", "bypass_mode": "always"}
    ]
    assert {rule["type"] for rule in tag["rules"]} == {
        "creation",
        "update",
        "deletion",
        "non_fast_forward",
    }
    expected_environments = module.expected_pypi_environment_names()
    assert "pypi-agilab" in expected_environments
    assert "pypi-agi-env" in expected_environments
    assert all(name.startswith("pypi-") for name in expected_environments)


def test_environment_payload_preserves_existing_protection_and_enables_custom_refs() -> None:
    module = _load_module()
    existing = {
        "protection_rules": [
            {"type": "wait_timer", "wait_timer": 7},
            {
                "type": "required_reviewers",
                "prevent_self_review": True,
                "reviewers": [{"reviewer": {"id": 9, "type": "Team"}}],
            },
        ]
    }

    payload = module._environment_payload(existing)

    assert payload["wait_timer"] == 7
    assert payload["prevent_self_review"] is True
    assert payload["reviewers"] == [{"id": 9, "type": "Team"}]
    assert payload["deployment_branch_policy"] == {
        "protected_branches": False,
        "custom_branch_policies": True,
    }


def test_custom_policy_reconciliation_deletes_unexpected_refs_before_adding_missing() -> None:
    module = _load_module()
    policy = module.load_policy()

    class FakeApi:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, dict | None]] = []

        def request(self, method: str, path: str, payload: dict | None = None):
            self.calls.append((method, path, payload))
            if method == "GET":
                return {
                    "branch_policies": [
                        {"id": 1, "name": "main", "type": "branch"},
                        {"id": 2, "name": "feature/*", "type": "branch"},
                    ]
                }
            return None

    api = FakeApi()
    module._ensure_custom_policies(api, policy, "pypi-agilab")

    mutations = [call for call in api.calls if call[0] != "GET"]
    assert mutations == [
        (
            "DELETE",
            "repos/ThalesGroup/agilab/environments/pypi-agilab/"
            "deployment-branch-policies/2",
            None,
        ),
        (
            "POST",
            "repos/ThalesGroup/agilab/environments/pypi-agilab/"
            "deployment-branch-policies",
            {"name": "v*.*.*", "type": "tag"},
        ),
    ]


def test_subset_match_accepts_github_response_metadata_but_not_missing_policy() -> None:
    module = _load_module()

    assert module._contains(
        {"name": "protected-main", "id": 1, "rules": [{"type": "deletion", "extra": True}]},
        {"name": "protected-main", "rules": [{"type": "deletion"}]},
    )
    assert not module._contains(
        {"name": "protected-main", "rules": []},
        {"name": "protected-main", "rules": [{"type": "deletion"}]},
    )


def _cost_checkout(tmp_path):
    root = tmp_path
    workflows = root / ".github/workflows"
    workflows.mkdir(parents=True)
    policy = _load_module().load_policy()
    (root / ".github/platform-policy.json").write_text(json.dumps(policy))
    (workflows / "manual.yml").write_text(
        "name: explicit\non:\n  workflow_dispatch:\njobs: {}\n"
    )
    return root


@pytest.mark.parametrize(
    "event",
    [
        "push",
        "pull_request",
        "schedule",
        "workflow_run",
        "repository_dispatch",
        "workflow_call",
    ],
)
def test_new_automatic_workflow_is_rejected_offline(tmp_path, event):
    module = _load_module()
    root = _cost_checkout(tmp_path)
    assert module.check_workflow_cost(root)["status"] == "pass"
    (root / ".github/workflows/future-unknown.yaml").write_text(
        f"on: [{event}]\njobs: {{}}\n"
    )
    result = module.check_workflow_cost(root)
    assert result["status"] == "fail"
    assert any("future-unknown.yaml" in failure for failure in result["failures"])


@pytest.mark.parametrize(
    "text",
    [
        "name: missing\njobs: {}",
        "on: [workflow_dispatch, workflow_dispatch]",
        "on: false",
        "on: [workflow_dispatch",
        "on: workflow_dispatch\non: push",
        "on: {workflow_dispatch: null, workflow_dispatch: null}",
        "on: {workflow_dispatch: invalid}",
    ],
)
def test_malformed_missing_or_duplicate_event_declarations_fail(tmp_path, text):
    module = _load_module()
    root = _cost_checkout(tmp_path)
    (root / ".github/workflows/future.yml").write_text(text)
    assert module.check_workflow_cost(root)["status"] == "fail"


def test_disabled_actions_and_no_ci_requirements_are_desired(tmp_path):
    module = _load_module()
    root = _cost_checkout(tmp_path)
    assert module.check_workflow_cost(root)["status"] == "pass"
    path = root / ".github/platform-policy.json"
    policy = json.loads(path.read_text())
    policy["actions"]["enabled"] = True
    path.write_text(json.dumps(policy))
    assert module.check_workflow_cost(root)["status"] == "fail"
    policy["actions"]["enabled"] = False
    policy["main_ruleset"]["required_status_checks"] = ["obsolete"]
    path.write_text(json.dumps(policy))
    assert module.check_workflow_cost(root)["status"] == "fail"


def test_clean_working_tree_cannot_hide_an_automatic_workflow_in_nominated_sha(
    tmp_path, monkeypatch
):
    module = _load_module()
    root = _cost_checkout(tmp_path)
    policy_raw = (root / ".github/platform-policy.json").read_bytes()
    bad, good = "a" * 40, "b" * 40
    calls = []

    def git_bytes(_root, *args):
        calls.append(args)
        if args[0] == "rev-parse":
            return args[-1].split("^")[0].encode()
        if args[0] == "show":
            return policy_raw
        if args[0] == "ls-tree":
            oid = "c" * 40 if args[3] == bad else "d" * 40
            return f"100644 blob {oid}\t.github/workflows/new-unlisted.yml\0".encode()
        if args[:2] == ("cat-file", "blob"):
            return b"on: push\n" if args[-1] == "c" * 40 else b"on: workflow_dispatch\n"
        raise AssertionError(args)

    monkeypatch.setattr(module, "_git_bytes", git_bytes)
    assert module.check_workflow_cost(root)["status"] == "pass"
    spec = root / "push-spec.txt"
    spec.write_text(f"refs/heads/task {bad} refs/heads/task {'0' * 40}\n")
    result = module.check_pushed_workflow_cost(root, spec)
    assert result[0]["status"] == "fail" and result[0]["ref"] == bad
    spec.write_text(f"refs/heads/task {good} refs/heads/task {'0' * 40}\n")
    assert module.check_pushed_workflow_cost(root, spec)[0]["status"] == "pass"
    assert any(args[0] == "ls-tree" and args[3] == bad for args in calls)


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("none", "pass"),
        ("old-checks", "fail"),
        ("actions-enabled", "fail"),
        ("unsigned", "fail"),
    ],
)
def test_audit_checks_absence_and_disabled_actions_without_weakening_protection(
    monkeypatch, mutation, expected
):
    module = _load_module()
    policy = module.load_policy()
    main = module.desired_main_ruleset(policy)
    tags = module.desired_tag_ruleset(policy, 42)
    if mutation == "old-checks":
        main["rules"].append(
            {
                "type": "required_status_checks",
                "parameters": {
                    "required_status_checks": [{"context": str(i)} for i in range(7)]
                },
            }
        )
    if mutation == "unsigned":
        main["rules"] = [
            rule for rule in main["rules"] if rule["type"] != "required_signatures"
        ]
    names = ["pypi-agilab", policy["release_approval_environment"]["name"]]
    monkeypatch.setattr(module, "_team", lambda *a: {"id": 42})
    monkeypatch.setattr(module, "_environment_names", lambda *a: names)
    monkeypatch.setattr(
        module, "expected_pypi_environment_names", lambda: {"pypi-agilab"}
    )
    monkeypatch.setattr(
        module, "_custom_policies", lambda *a: policy["deployment_ref_policies"]
    )
    monkeypatch.setattr(
        module,
        "_rulesets",
        lambda *a: [{"id": 1, "name": main["name"]}, {"id": 2, "name": tags["name"]}],
    )

    class Api:
        def request(self, method, path):
            assert method == "GET"
            if path.endswith("rulesets/1"):
                return main
            if path.endswith("rulesets/2"):
                return tags
            if path.endswith("actions/permissions"):
                return {"enabled": mutation == "actions-enabled"}
            return {
                "deployment_branch_policy": {"custom_branch_policies": True},
                "protection_rules": [
                    {
                        "type": "required_reviewers",
                        "prevent_self_review": True,
                        "reviewers": [{"reviewer": {"id": 42, "type": "Team"}}],
                    }
                ],
            }

    report = module.audit_policy(Api(), policy)
    assert report["status"] == expected


def test_local_pre_push_cost_guard_runs_before_general_skip_escape():
    hook = Path(".githooks/pre-push").read_text()
    assert hook.index("--check-workflow-cost --pre-push-spec") < hook.index(
        "AGILAB_SKIP_LOCAL_GUARDS"
    )
