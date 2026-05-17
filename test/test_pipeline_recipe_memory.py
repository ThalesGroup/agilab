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


def test_recipe_memory_edge_sources_candidates_and_helpers(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert memory.recipe_memory_enabled({memory.RECIPE_MEMORY_ENABLED_ENV: "off"}) is False
    assert memory.recipe_memory_path({}) == tmp_path / memory.DEFAULT_MEMORY_RELATIVE_PATH
    assert memory.redact_recipe_text(
        f"{tmp_path}/file user@example.com bearer abcdefghijklmnopqrstuvwxyz GITHUB_TOKEN=secret",
        home=tmp_path,
    ) == "$HOME/file <email> bearer <redacted> GITHUB_TOKEN=<redacted>"
    assert memory.build_recipe_card(
        intent="",
        code="print('x')",
        source_kind="test",
        source_path=tmp_path,
        source_ref="empty",
    ) is None
    assert memory.build_recipe_card(
        intent="intent",
        code="",
        source_kind="test",
        source_path=tmp_path,
        source_ref="empty",
    ) is None

    missing_steps = tmp_path / "missing_lab_steps.toml"
    assert memory.load_recipe_cards_from_lab_steps(missing_steps) == []
    steps_file = tmp_path / "lab_steps_extra.toml"
    steps_file.write_text(
        """
__meta__ = { schema = "ignored" }
ignored = "bad"
demo_project = [
  "skip",
  { D = "Validated bool", C = "df['a'] = 1", validated = true },
  { Q = "Failed row", C = "df['b'] = 2", status = "failed" },
]
""",
        encoding="utf-8",
    )
    step_cards = memory.load_recipe_cards_from_lab_steps(steps_file)
    assert [card.validation_status for card in step_cards] == ["validated", "failed"]

    invalid_notebook = tmp_path / "notebook_array.ipynb"
    invalid_notebook.write_text("[]", encoding="utf-8")
    assert memory.load_recipe_cards_from_notebook(invalid_notebook) == []
    weird_notebook = tmp_path / "weird.ipynb"
    weird_notebook.write_text(
        json.dumps(
            {
                "metadata": [],
                "cells": [
                    "skip",
                    {"cell_type": "raw", "source": "skip"},
                    {
                        "cell_type": "code",
                        "execution_count": None,
                        "source": "df['draft'] = 1",
                        "outputs": [{"output_type": "error"}],
                    },
                    {"cell_type": "code", "execution_count": None, "source": ""},
                ],
            }
        ),
        encoding="utf-8",
    )
    weird_cards = memory.load_recipe_cards_from_notebook(weird_notebook)
    assert len(weird_cards) == 1
    assert weird_cards[0].intent == "Notebook code cell 3"
    assert weird_cards[0].validation_status == "failed"
    assert memory._cards_from_notebook_cells(tmp_path / "x.ipynb", "bad") == []
    assert memory._cell_source_text(["a", "b"]) == "ab"
    assert memory._cell_source_text(12) == "12"

    memory_file = tmp_path / "cards.jsonl"
    valid_card = memory.build_recipe_card(
        intent="Assign tuple outputs",
        code="import pandas as pd\nfrom numpy import array\ndf['x'], df['y'] = 1, 2\ndf = df.assign(z=3)",
        validation_status="pass",
        source_kind="test",
        source_path=tmp_path / "source.py",
        source_ref="direct",
    )
    assert valid_card is not None
    memory_file.write_text(
        "\n"
        + json.dumps({"schema": "wrong"})
        + "\n"
        + json.dumps({"schema": memory.SCHEMA, "id": "", "intent": "bad"})
        + "\n"
        + json.dumps(valid_card.as_dict())
        + "\n",
        encoding="utf-8",
    )
    assert memory.load_recipe_cards_from_memory(tmp_path / "missing.jsonl") == []
    assert memory.load_recipe_cards_from_memory(memory_file) == [valid_card]
    assert memory.append_recipe_card(memory_file, valid_card) is False

    unsupported = tmp_path / "ignored.txt"
    unsupported.write_text("ignored", encoding="utf-8")
    assert memory.discover_recipe_sources([None, unsupported]) == []
    assert memory.discover_recipe_sources([steps_file, steps_file]) == [steps_file]
    assert memory.discover_recipe_sources([steps_file, weird_notebook, memory_file], max_files=2) == [
        steps_file,
        weird_notebook,
    ]
    assert len(memory.load_recipe_cards([steps_file, weird_notebook, memory_file], include_candidates=True, max_cards=2)) == 2
    assert memory.search_recipe_cards("", [valid_card]) == []
    assert memory.search_recipe_cards("tuple outputs", [valid_card], include_candidates=False) == [valid_card]
    clipped = memory.build_recipe_context("tuple outputs", [valid_card], max_code_chars=20)
    assert "# ... clipped ..." in clipped
    assert memory._cards_from_supervisor_steps(tmp_path / "supervisor.json", ["bad"]) == []
    assert memory._should_augment("") is False

    class BadPath:
        def __str__(self):
            raise ValueError("bad path")

    assert all(
        not isinstance(root, BadPath)
        for root in memory._recipe_roots({}, {}, df_file=BadPath(), cwd=tmp_path)
    )


def test_recipe_memory_augment_and_promotion_fallback_branches(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    memory_path = tmp_path / "cards.jsonl"
    envars = {
        memory.RECIPE_MEMORY_PATH_ENV: str(memory_path),
        memory.RECIPE_MEMORY_INCLUDE_CANDIDATES_ENV: "1",
    }
    candidate = memory.build_recipe_card(
        intent="Create candidate metric",
        code="df['candidate_metric'] = df['a'] + df['b']",
        validation_status="validated",
        source_kind="test",
        source_path=tmp_path,
        source_ref="candidate",
    )
    assert candidate is not None
    assert memory.append_recipe_card(memory_path, candidate) is True

    assert memory.augment_question_with_recipe_memory("Traceback: boom", envars=envars) == "Traceback: boom"
    assert memory.augment_question_with_recipe_memory("failing code: df", envars=envars) == "failing code: df"
    assert memory.augment_question_with_recipe_memory("unrelated words", envars=envars, cwd=tmp_path) == "unrelated words"
    augmented = memory.augment_question_with_recipe_memory(
        "candidate metric",
        session_state={
            "recipe_memory_roots": [tmp_path / "missing"],
            "env": type("Env", (), {"active_app": tmp_path})(),
        },
        envars={
            **envars,
            memory.RECIPE_MEMORY_ROOTS_ENV: str(tmp_path / "missing_a") + memory.os.pathsep + str(tmp_path / "missing_b"),
        },
        df_file=tmp_path / "data" / "df.csv",
        cwd=tmp_path,
    )
    assert "candidate_metric" in augmented

    assert memory.promote_validated_recipe(
        question="",
        code="df['x'] = 1",
        envars={memory.RECIPE_MEMORY_PATH_ENV: str(tmp_path / "unused.jsonl")},
    ) is None
    monkeypatch.setattr(memory, "append_recipe_card", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("boom")))
    assert memory.promote_validated_recipe(
        question="Store metric",
        code="df['x'] = 1",
        envars={memory.RECIPE_MEMORY_PATH_ENV: str(tmp_path / "blocked.jsonl")},
    ) is None
    assert memory._lookup_setting("MISSING_RECIPE_SETTING", None, default="fallback") == "fallback"
    assert memory._truthy("yes") is True
    assert memory._dedupe_sorted(["b", "a", "a", ""], limit=1) == ["a"]
    assert memory._string_hints("Use groupby and route_rank custom_metric") == [
        "groupby",
        "route_rank",
        "custom_metric",
    ]
    assert memory._extract_imports("import os\nfrom pathlib import Path") == ["os", "pathlib"]
    assert memory._extract_imports("import broken syntax!") == ["broken"]
    assert memory._imports_from_lines("from pandas import DataFrame\nimport numpy.random\n") == ["pandas", "numpy"]
    assert memory._extract_dataframe_outputs("bad syntax [") == []
    assert memory._extract_dataframe_outputs("df['x'] = 1\n(df['y'], other) = (2, 3)\ndf.assign(z=4)") == [
        "x",
        "y",
        "z",
    ]
    assert memory._extract_operations("bad syntax [") == []
    assert memory._extract_operations("df.groupby('a').agg({'b':'mean'}).sort_values('b')") == [
        "agg",
        "groupby",
        "sort_values",
    ]
    assert memory._node_name(memory.ast.Constant("x")) == ""
    assert memory._constant_string(memory.ast.Constant(1)) == ""
    assert memory._normalize_status("FAILED") == "failed"
    assert memory._normalize_status("success") == "validated"
    assert memory._normalize_status("") == "candidate"
    draft = memory.build_recipe_card(
        intent="Draft metric",
        code="df['draft'] = 1",
        source_kind="test",
        source_path=tmp_path,
        source_ref="draft",
    )
    assert draft is not None
    assert memory._is_eligible(draft) is False
    assert memory._tokens("the route_rank and groupby") == {"route_rank", "groupby"}
