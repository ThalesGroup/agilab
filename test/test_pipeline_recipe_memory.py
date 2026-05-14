from __future__ import annotations

import json
import importlib.util
from pathlib import Path
import sys


def _load_module():
    module_path = Path("src/agilab/pipeline_recipe_memory.py")
    spec = importlib.util.spec_from_file_location("agilab.pipeline_recipe_memory_test", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


memory = _load_module()


def test_lab_steps_recipe_cards_redact_and_filter_to_validated(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text(
        """
demo_project = [
  { D = "Clean telemetry", Q = "Group by bearer and average latency", M = "qwen3-coder", C = "df['latency_ms_avg'] = df.groupby('bearer')['latency_ms'].transform('mean')", validation_status = "pass" },
  { D = "Draft", Q = "Email result to user@example.com", C = "token = 'sk-ABCDEF1234567890SECRET'\\nprint(token)" }
]
""",
        encoding="utf-8",
    )

    all_cards = memory.load_recipe_cards([tmp_path], include_candidates=True)
    cards = memory.load_recipe_cards([tmp_path])

    assert len(all_cards) == 2
    assert len(cards) == 1
    card = cards[0]
    assert card.validation_status == "validated"
    assert card.intent == "Group by bearer and average latency"
    assert "latency_ms_avg" in card.output_columns
    assert "groupby" in card.operations
    assert "qwen3-coder" == card.model
    assert str(tmp_path) not in card.source_path

    draft = next(item for item in all_cards if item.validation_status == "candidate")
    assert "<email>" in draft.intent
    assert "sk-ABCDEF<redacted>" in draft.code
    assert "SECRET" not in draft.code


def test_notebook_supervisor_metadata_and_plain_cells_are_mined(tmp_path):
    supervisor_notebook = tmp_path / "supervisor.ipynb"
    supervisor_notebook.write_text(
        json.dumps(
            {
                "cells": [],
                "metadata": {
                    "agilab": {
                        "steps": [
                            {
                                "description": "Score route reliability",
                                "question": "Rank routes by reliability score",
                                "model": "gpt-oss:20b",
                                "code": "df['route_rank'] = df['reliability'].rank(ascending=False)",
                                "validation_status": "success",
                            }
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    plain_notebook = tmp_path / "plain.ipynb"
    plain_notebook.write_text(
        json.dumps(
            {
                "cells": [
                    {"cell_type": "markdown", "source": ["Smooth signal\n"]},
                    {
                        "cell_type": "code",
                        "execution_count": 1,
                        "source": ["df['smoothed'] = df['value'].rolling(3).mean()\n"],
                        "outputs": [],
                    },
                ],
                "metadata": {},
            }
        ),
        encoding="utf-8",
    )

    cards = memory.load_recipe_cards([tmp_path])

    intents = {card.intent for card in cards}
    assert "Rank routes by reliability score" in intents
    assert "Smooth signal" in intents
    assert any("rank" in card.operations for card in cards)
    assert any("rolling" in card.operations for card in cards)


def test_recipe_search_context_and_promotion_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    memory_path = tmp_path / "cards.jsonl"
    envars = {memory.RECIPE_MEMORY_PATH_ENV: str(memory_path)}

    card = memory.promote_validated_recipe(
        question="Compute queue pressure by relay path",
        code="df['queue_pressure'] = df['queue_depth'] / df['capacity']",
        model="qwen3-coder",
        df_columns=["queue_depth", "capacity"],
        source_path=tmp_path / "df.csv",
        source_ref="page:autofix",
        envars=envars,
    )

    assert card is not None
    assert memory_path.exists()
    assert memory.promote_validated_recipe(
        question="Compute queue pressure by relay path",
        code="df['queue_pressure'] = df['queue_depth'] / df['capacity']",
        source_path=tmp_path / "df.csv",
        source_ref="page:autofix",
        envars=envars,
    ) is not None

    cards = memory.load_recipe_cards_from_memory(memory_path)
    assert len(cards) == 1
    matches = memory.search_recipe_cards("queue pressure capacity", cards)
    assert [match.id for match in matches] == [card.id]

    context = memory.build_recipe_context("queue pressure capacity", cards)
    assert "Relevant validated AGILAB recipe memory" in context
    assert "queue_pressure" in context
    assert "```python" in context


def test_augment_question_uses_roots_and_can_be_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text(
        """
demo_project = [
  { Q = "Normalize packet loss by traffic volume", C = "df['loss_rate'] = df['packet_loss'] / df['traffic_volume']", validation_status = "validated" }
]
""",
        encoding="utf-8",
    )
    session_state = {"steps_file": str(steps_file)}
    question = "Calculate packet loss rate"

    augmented = memory.augment_question_with_recipe_memory(
        question,
        session_state=session_state,
        envars={memory.RECIPE_MEMORY_PATH_ENV: str(tmp_path / "missing.jsonl")},
    )

    assert augmented.startswith(question)
    assert "loss_rate" in augmented

    disabled = memory.augment_question_with_recipe_memory(
        question,
        session_state=session_state,
        envars={memory.RECIPE_MEMORY_ENABLED_ENV: "0"},
    )
    assert disabled == question


def test_malformed_sources_are_ignored(tmp_path):
    (tmp_path / "bad_lab_steps.toml").write_text("[[broken]\n", encoding="utf-8")
    (tmp_path / "bad.ipynb").write_text("{bad json", encoding="utf-8")
    (tmp_path / "cards.jsonl").write_text("not json\n{}\n", encoding="utf-8")

    assert memory.load_recipe_cards([tmp_path], include_candidates=True) == []
