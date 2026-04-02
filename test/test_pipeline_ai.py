from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pandas as pd


def _load_module(module_name: str, relative_path: str):
    module_path = Path(relative_path)
    importlib.invalidate_caches()
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


pipeline_ai = _load_module("agilab.pipeline_ai", "src/agilab/pipeline_ai.py")


def test_extract_code_splits_detail_and_python_block():
    message = "Use this.\n```python\nprint('ok')\n```\nDone."

    code, detail = pipeline_ai.extract_code(message)

    assert code == "print('ok')"
    assert detail == "Use this.\n\nDone."


def test_normalize_gpt_oss_endpoint_appends_responses_path():
    assert pipeline_ai._normalize_gpt_oss_endpoint("") == pipeline_ai.DEFAULT_GPT_OSS_ENDPOINT
    assert (
        pipeline_ai._normalize_gpt_oss_endpoint("http://127.0.0.1:8000")
        == "http://127.0.0.1:8000/v1/responses"
    )
    assert (
        pipeline_ai._normalize_gpt_oss_endpoint("http://127.0.0.1:8000/v1")
        == "http://127.0.0.1:8000/v1/responses"
    )


def test_build_autofix_prompt_truncates_large_inputs():
    prompt = pipeline_ai._build_autofix_prompt(
        original_request="smooth the column",
        failing_code="x" * 7000,
        traceback_text="y" * 5000,
        attempt=2,
    )

    assert "attempt 2" in prompt
    assert "smooth the column" in prompt
    assert len(prompt) < 12000


def test_normalize_ollama_endpoint_strips_generate_path_and_uses_env(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://ollama.local:11434/")

    assert pipeline_ai._normalize_ollama_endpoint("") == "http://ollama.local:11434"
    assert (
        pipeline_ai._normalize_ollama_endpoint("http://127.0.0.1:11434/api/generate")
        == "http://127.0.0.1:11434"
    )


def test_exec_code_on_df_returns_updated_dataframe():
    source = pd.DataFrame({"value": [1, 2, 3]})

    updated, error = pipeline_ai._exec_code_on_df("df['double'] = df['value'] * 2", source)

    assert error == ""
    assert updated is not None
    assert list(updated["double"]) == [2, 4, 6]
    assert "double" not in source.columns


def test_exec_code_on_df_reports_runtime_error():
    updated, error = pipeline_ai._exec_code_on_df("raise ValueError('boom')", pd.DataFrame({"x": [1]}))

    assert updated is None
    assert "ValueError: boom" in error


def test_exec_code_on_df_requires_dataframe_output():
    updated, error = pipeline_ai._exec_code_on_df("df = 42", pd.DataFrame({"x": [1]}))

    assert updated is None
    assert "DataFrame named `df`" in error


def test_normalize_identifier_handles_digits_and_fallback():
    assert pipeline_ai._normalize_identifier("Flight Level (%)") == "flight_level"
    assert pipeline_ai._normalize_identifier("12-bearers") == "_12_bearers"
    assert pipeline_ai._normalize_identifier("", fallback="service") == "service"


def test_synthesize_stub_response_builds_savgol_code_with_odd_window():
    response = pipeline_ai._synthesize_stub_response("Apply savgol on column Air-Speed with window 8")

    assert "from scipy.signal import savgol_filter" in response
    assert "column = 'air_speed'" in response
    assert "window_length = 9" in response


def test_synthesize_stub_response_returns_generic_stub_message():
    response = pipeline_ai._synthesize_stub_response("Summarize the dataframe")

    assert "stub backend" in response
    assert "real backend" in response


def test_format_for_responses_wraps_plain_text_and_preserves_list_content():
    conversation = [
        {"role": "system", "content": "rules"},
        {"role": "assistant", "content": [{"type": "text", "text": "already structured"}]},
    ]

    formatted = pipeline_ai._format_for_responses(conversation)

    assert formatted[0] == {
        "role": "system",
        "content": [{"type": "text", "text": "rules"}],
    }
    assert formatted[1]["content"] == [{"type": "text", "text": "already structured"}]


def test_response_to_text_prefers_output_text_then_structured_and_legacy_choices():
    direct = SimpleNamespace(output_text="  done  ")
    assert pipeline_ai._response_to_text(direct) == "done"

    structured = SimpleNamespace(
        output=[
            SimpleNamespace(
                type="message",
                content=[
                    SimpleNamespace(type="text", text="alpha"),
                    SimpleNamespace(type="output_text", text=SimpleNamespace(value="beta")),
                ],
            )
        ]
    )
    assert pipeline_ai._response_to_text(structured) == "alpha\nbeta"

    legacy = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=" legacy "))])
    assert pipeline_ai._response_to_text(legacy) == "legacy"


def test_load_env_file_map_reads_comments_and_missing_files(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "# OPENAI_MODEL=gpt-5.4",
                "AGI_LOG_DIR=/tmp/logs",
                "#ignored line",
                "SPACED = hello",
            ]
        ),
        encoding="utf-8",
    )

    values = pipeline_ai._load_env_file_map(env_file)

    assert values == {
        "OPENAI_MODEL": "gpt-5.4",
        "AGI_LOG_DIR": "/tmp/logs",
        "SPACED": "hello",
    }
    assert pipeline_ai._load_env_file_map(tmp_path / "missing.env") == {}


def test_redact_sensitive_masks_openai_style_keys():
    message = "bad key sk-ABCD1234567890 and project key sk-proj-WXYZabcdefgh123456"

    redacted = pipeline_ai._redact_sensitive(message)

    assert "sk-ABCD12…" in redacted
    assert "sk-proj…" in redacted
    assert "1234567890" not in redacted


def test_prompt_to_gpt_oss_messages_separates_system_and_normalizes_roles():
    instructions, history = pipeline_ai._prompt_to_gpt_oss_messages(
        [
            {"role": "system", "content": "obey"},
            {"role": "assistant", "content": "done"},
            {"role": "critic", "content": "fallback role"},
        ],
        "next step?",
    )

    assert instructions == "obey"
    assert history[0] == {
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": "done"}],
    }
    assert history[1] == {
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": "fallback role"}],
    }
    assert history[-1]["content"] == [{"type": "input_text", "text": "next step?"}]


def test_format_uoaic_question_flattens_history_with_code_preamble():
    text = pipeline_ai._format_uoaic_question(
        [
            {"role": "system", "content": "rules"},
            {"role": "assistant", "content": "previous answer"},
        ],
        "plot value",
    )

    assert text.startswith(pipeline_ai.CODE_STRICT_INSTRUCTIONS)
    assert "System: rules" in text
    assert "Assistant: previous answer" in text
    assert text.endswith("User: plot value")


def test_normalize_user_path_resolves_relative_paths(monkeypatch, tmp_path):
    target = tmp_path / "dataset.csv"
    target.write_text("x", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    normalized = pipeline_ai._normalize_user_path("dataset.csv")

    assert normalized == str(target.resolve())


def test_resolve_uoaic_path_uses_pipeline_export_root_for_relative_paths(monkeypatch, tmp_path):
    export_root = tmp_path / "export"
    export_root.mkdir()
    monkeypatch.setattr(pipeline_ai, "_pipeline_export_root", lambda env: export_root)

    resolved = pipeline_ai._resolve_uoaic_path("docs/manual.pdf", env=object())

    assert resolved == (export_root / "docs/manual.pdf").resolve()


def test_resolve_uoaic_path_raises_for_empty_input():
    try:
        pipeline_ai._resolve_uoaic_path("", env=None)
    except ValueError as exc:
        assert "Path is empty" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected ValueError for empty input")
