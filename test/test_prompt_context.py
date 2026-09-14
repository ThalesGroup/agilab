from __future__ import annotations

import json
import pytest

from agilab.pipeline.prompt_context import (
    PromptBudget,
    PromptContextError,
    assemble_prompt_context,
    build_repair_prompt,
)


def test_large_project_context_is_bounded_and_required_content_is_intact():
    prompt = [{"role": "system", "content": "Preserve evidence."}]
    prompt += [
        {"role": "user", "content": f"Example {i}: " + "example " * 2000}
        for i in range(40)
    ]
    context = assemble_prompt_context(
        "Repair result.", prompt, instructions="Return code."
    )
    assert context.question == "Repair result."
    assert context.messages[0] == prompt[0]
    assert context.receipt["input_bytes"] <= context.receipt["input_budget_bytes"]
    assert context.receipt["omitted_indices"]
    assert "optional messages omitted" in context.messages[-1]["content"]
    assert "Example" not in json.dumps(context.receipt)


def test_duplicate_examples_removed_as_complete_pairs():
    pair = [
        {"role": "user", "content": "Example?"},
        {"role": "assistant", "content": "Answer."},
    ]
    context = assemble_prompt_context("Actual task", pair + pair)
    assert list(context.messages) == pair
    assert context.receipt["duplicate_indices"] == [2, 3]


def test_required_request_or_instructions_overflow_fails_without_clipping():
    for question, messages in [
        ("request " * 20000, []),
        ("task", [{"role": "system", "content": "guard " * 20000}]),
    ]:
        with pytest.raises(PromptContextError, match="Required assistant"):
            assemble_prompt_context(question, messages)


def test_unicode_and_pair_atomicity_respect_byte_budget():
    pair = [
        {"role": "user", "content": "é" * 70},
        {"role": "assistant", "content": "答" * 70},
    ]
    context = assemble_prompt_context(
        "Keep this task.", pair, budget=PromptBudget(650, 100)
    )
    selected = context.receipt["selected_indices"]
    assert selected == [] or selected == [0, 1]
    assert context.receipt["input_bytes"] <= 550


def test_autofix_retains_fault_at_tail_with_explicit_omissions():
    code = "value = 1\n" * 700 + 'raise ValueError("CRITICAL_TAIL_MARKER")\n'
    result = build_repair_prompt(
        original_request="Repair result",
        failing_code=code,
        traceback_text='File "<lab_step>", line 701\nValueError: bad',
        attempt=1,
        instructions="Return code.",
    )
    assert "CRITICAL_TAIL_MARKER" in result
    assert "lines omitted" in result
    assert "sha256=" in result
    assert "Repair result" in result


def test_long_preceding_lines_do_not_displace_the_failing_line():
    code = (
        ("# " + "x" * 1000 + "\n") * 40
        + 'raise ValueError("FAULT")\n'
        + "value = 1\n" * 40
    )
    result = build_repair_prompt(
        original_request="repair",
        failing_code=code,
        traceback_text='File "<lab_step>", line 41\nValueError',
        attempt=1,
        instructions="Return code.",
    )
    assert "FAULT" in result
    assert len(result.encode()) < 12000


def test_large_original_autofix_request_fails_explicitly():
    with pytest.raises(PromptContextError, match="Required assistant"):
        build_repair_prompt(
            original_request="request " * 20000,
            failing_code="pass",
            traceback_text="error",
            attempt=1,
            instructions="Return code.",
        )


def test_invalid_preprompt_shape_is_actionable():
    with pytest.raises(PromptContextError, match="object"):
        assemble_prompt_context("request", ["not a message"])
