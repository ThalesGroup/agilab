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


def test_recommend_context_can_emit_tokki_profile_packs() -> None:
    payload = agent_context_router.recommend_context(
        files=[
            "src/agilab/pages/4_ANALYSIS.py",
            "src/agilab/notebooks/notebook_export_support.py",
        ],
        prompt="fix notebook sync in the analysis page",
        skills=_skill_index(),
        profile="tokki",
    )

    profile = payload["context_profile"]

    assert profile["id"] == "tokki"
    assert profile["estimated_token_budget"] <= profile["max_total_tokens"]
    assert profile["baseline_files"] == [
        "AGENT_CONVENTIONS.md",
        "agent-context-rules.json",
        "tools/impact_validate.py",
    ]
    pack_ids = [pack["rule_id"] for pack in profile["matched_packs"]]
    assert "streamlit-ui" in pack_ids
    assert "notebook-import-export" in pack_ids
    notebook_pack = next(pack for pack in profile["matched_packs"] if pack["rule_id"] == "notebook-import-export")
    assert "test/test_pipeline_editor.py" in notebook_pack["files"]


def test_recommend_context_routes_tokki_prompt_to_context_profile_pack() -> None:
    payload = agent_context_router.recommend_context(
        prompt="make AGILAB tokki friendly with token saving context packs",
        skills=_skill_index(),
        profile="tokki",
    )

    matched_ids = [rule["id"] for rule in payload["matched_rules"]]
    profile_pack_ids = [pack["rule_id"] for pack in payload["context_profile"]["matched_packs"]]

    assert "agent-skills" in matched_ids
    assert "agent-skills" in profile_pack_ids


def test_cli_text_output_reports_tokki_profile(capsys) -> None:
    rc = agent_context_router.main(
        [
            "--files",
            "src/agilab/pages/4_ANALYSIS.py",
            "--prompt",
            "fix Streamlit sidebar state",
            "--profile",
            "tokki",
        ]
    )

    assert rc == 0
    output = capsys.readouterr().out
    assert "Context profile: tokki" in output
    assert "streamlit-ui" in output


def test_cli_reports_unknown_context_profile(capsys) -> None:
    rc = agent_context_router.main(["--profile", "missing"])

    captured = capsys.readouterr()
    assert rc == 2
    assert "unknown context profile: missing" in captured.err


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
