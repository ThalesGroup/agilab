from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "session_intent_synthesis.py"
SPEC = importlib.util.spec_from_file_location("session_intent_synthesis_test", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_session_intent_synthesis_classifies_sessions_and_redacts_tokens(tmp_path: Path) -> None:
    sessions_root = tmp_path / "sessions"
    memory_root = tmp_path / "memories"
    session = sessions_root / "rollout.jsonl"
    _write_jsonl(
        session,
        [
            {"type": "session_meta", "payload": {"base_instructions": {"text": "ignore review AGILAB"}}},
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "review AGILAB and write a deep doc"}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "fed-back from claude: review AGILAB"}],
                },
            },
            {
                "type": "compacted",
                "payload": {
                    "replacement_history": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_text",
                                    "text": "update repos with https://pypi.org/account/confirm-login/?token=SECRET",
                                }
                            ],
                        }
                    ]
                },
            },
        ],
    )
    memory_root.mkdir()
    (memory_root / "summary.md").write_text("cluster validation must rediscover worker ip\n", encoding="utf-8")

    payload = module.build_synthesis(
        session_paths=[session],
        memory_paths=[memory_root / "summary.md"],
    )

    by_id = {item["id"]: item for item in payload["intents"]}
    assert by_id["deep_audit"]["observations"] == 1
    assert by_id["safe_repo_sync"]["observations"] == 1
    assert by_id["cluster_validation"]["observations"] == 1
    assert "<redacted>" in by_id["safe_repo_sync"]["redacted_examples"][0]
    assert "SECRET" not in json.dumps(payload)
    assert module.redact("uv run tool --password Abyx2633! --openai-api-key sk-real-secret") == (
        "uv run tool --password <redacted> --openai-api-key <redacted>"
    )


def test_session_intent_synthesis_cli_writes_output(tmp_path: Path) -> None:
    sessions_root = tmp_path / "sessions"
    memory_root = tmp_path / "memories"
    output = tmp_path / "session_intents.json"
    _write_jsonl(
        sessions_root / "rollout.jsonl",
        [
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "next move ?"}],
                },
            }
        ],
    )

    rc = module.main(
        [
            "--sessions-root",
            str(sessions_root),
            "--memory-root",
            str(memory_root),
            "--output",
            str(output),
        ]
    )

    assert rc == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    by_id = {item["id"]: item for item in payload["intents"]}
    assert by_id["continue_current_scope"]["observations"] == 1


def test_session_rule_proposals_detect_candidates_and_existing_rules(tmp_path: Path) -> None:
    sessions_root = tmp_path / "sessions"
    session = sessions_root / "rollout.jsonl"
    _write_jsonl(
        session,
        [
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "do it + next move is cheaper"}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "do it + next move is cheaper"}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "could you add it as a rule token=SECRET"}],
                },
            },
        ],
    )

    payload = module.build_rule_proposals(
        session_paths=[session],
        memory_paths=[],
        rule_surface_texts={
            "AGENT_LEARNINGS.md": (
                "When the user combines execution and follow-up planning in one message, "
                "treat it as an ordered single turn."
            )
        },
        min_observations=1,
    )

    by_id = {proposal["id"]: proposal for proposal in payload["proposals"]}
    assert by_id["combined_execution_followup"]["status"] == "already-covered"
    assert by_id["combined_execution_followup"]["observations"] == 2
    assert by_id["combined_execution_followup"]["redacted_examples"] == ["do it + next move is cheaper"]
    assert by_id["combined_execution_followup"]["duplicate_paths"] == ["AGENT_LEARNINGS.md"]
    assert by_id["explicit_rule_request"]["status"] == "candidate"
    assert "<redacted>" in json.dumps(by_id["explicit_rule_request"])
    assert "SECRET" not in json.dumps(payload)

    markdown = module.render_rule_proposals_markdown(payload)
    assert "# Session Rule Proposals" in markdown
    assert "combined_execution_followup" in markdown
    assert "already-covered" in markdown


def test_session_rule_proposal_cli_writes_json_and_markdown(tmp_path: Path) -> None:
    sessions_root = tmp_path / "sessions"
    memory_root = tmp_path / "memories"
    rules_root = tmp_path / "repo"
    output = tmp_path / "session_intents.json"
    rule_output = tmp_path / "session_rule_proposals.json"
    rule_markdown = tmp_path / "session_rule_proposals.md"
    _write_jsonl(
        sessions_root / "rollout.jsonl",
        [
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "you missed the docs source"}],
                },
            }
        ],
    )
    memory_root.mkdir()
    rules_root.mkdir()

    rc = module.main(
        [
            "--sessions-root",
            str(sessions_root),
            "--memory-root",
            str(memory_root),
            "--output",
            str(output),
            "--propose-rules",
            "--rule-output",
            str(rule_output),
            "--rule-markdown-output",
            str(rule_markdown),
            "--rules-root",
            str(rules_root),
            "--min-rule-observations",
            "1",
        ]
    )

    assert rc == 0
    payload = json.loads(rule_output.read_text(encoding="utf-8"))
    by_id = {proposal["id"]: proposal for proposal in payload["proposals"]}
    assert by_id["missed_surface_correction"]["status"] == "candidate"
    assert "docs source" in by_id["missed_surface_correction"]["redacted_examples"][0]
    assert "missed_surface_correction" in rule_markdown.read_text(encoding="utf-8")
