from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "agent_context_router.py"
SPEC = importlib.util.spec_from_file_location("agent_context_router_test", MODULE_PATH)
assert SPEC and SPEC.loader
agent_context_router = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent_context_router)


def _skill_index() -> dict[str, dict[str, str]]:
    return {
        name: {"name": name, "path": f".claude/skills/{name}/SKILL.md", "description": name}
        for name in [
            "advanced-svg-system-design",
            "agilab-docs",
            "agilab-evidence-contracts",
            "agilab-example-maturity",
            "agilab-installer",
            "agilab-intent-router",
            "agilab-prompt-eval-regression",
            "agilab-pypi-release-maintenance",
            "agilab-release-verification",
            "agilab-security-review-patterns",
            "agilab-streamlit-pages",
            "agilab-testing",
            "agilab-ui-robot-validation",
            "codex-session-learning",
            "notebook-to-agilab-project",
            "plan-before-code",
            "repo-skill-maintenance",
            "scientific-svg-figures",
            "svg-diagram-tuning",
        ]
    }


def test_recommend_context_matches_docs_and_evidence_rules() -> None:
    payload = agent_context_router.recommend_context(
        files=[
            "docs/source/proof-capsule.rst",
            "src/agilab/run_markdown_evidence.py",
        ],
        prompt="sync doc and update the run evidence manifest",
        skills=_skill_index(),
    )

    assert payload["schema"] == "agilab.agent_context_recommendation.v1"
    assert payload["status"] == "pass"
    matched_ids = {rule["id"] for rule in payload["matched_rules"]}
    assert {"docs-public-claims", "evidence-proof"} <= matched_ids
    skill_names = [skill["name"] for skill in payload["recommended_skills"]]
    assert skill_names[:2] == ["plan-before-code", "agilab-intent-router"]
    assert "agilab-docs" in skill_names
    assert "agilab-evidence-contracts" in skill_names


def test_recommend_context_matches_release_prompt_without_files() -> None:
    payload = agent_context_router.recommend_context(
        prompt="ready for release, check PyPI and Hugging Face sync",
        skills=_skill_index(),
    )

    matched_ids = [rule["id"] for rule in payload["matched_rules"]]
    assert matched_ids == ["release-publication"]
    skill_names = [skill["name"] for skill in payload["recommended_skills"]]
    assert "agilab-release-verification" in skill_names
    assert "agilab-pypi-release-maintenance" in skill_names


def test_validate_rules_reports_unknown_skill() -> None:
    rules = {
        "schema": "agilab.agent_context_rules.v1",
        "baseline": {
            "runbooks": [{"path": "AGENT_CONVENTIONS.md", "purpose": "short"}],
            "skills": ["plan-before-code"],
        },
        "rules": [
            {
                "id": "bad",
                "label": "Bad",
                "paths": ["*.py"],
                "terms": [],
                "skills": ["missing-skill"],
                "reason": "exercise validation",
            }
        ],
    }

    report = agent_context_router.validate_rules(rules, skills=_skill_index())

    assert report["schema"] == "agilab.agent_context_rules_validation.v1"
    assert report["status"] == "fail"
    assert any("missing-skill" in issue["message"] for issue in report["issues"])


def test_cli_json_output_is_machine_readable(capsys) -> None:
    rc = agent_context_router.main(
        [
            "--files",
            "src/agilab/pages/1_PROJECT.py",
            "--prompt",
            "fix Streamlit sidebar state",
            "--json",
        ]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "agilab.agent_context_recommendation.v1"
    assert any(rule["id"] == "streamlit-ui" for rule in payload["matched_rules"])
