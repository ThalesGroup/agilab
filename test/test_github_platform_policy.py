from __future__ import annotations

import importlib.util
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
        "required_status_checks",
    }
    pull_request = next(rule for rule in main["rules"] if rule["type"] == "pull_request")
    assert pull_request["parameters"]["required_approving_review_count"] == 1
    assert pull_request["parameters"]["require_last_push_approval"] is True
    status_checks = next(rule for rule in main["rules"] if rule["type"] == "required_status_checks")
    contexts = {row["context"] for row in status_checks["parameters"]["required_status_checks"]}
    assert {"root-tests", "local-only-policy"} <= contexts
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
