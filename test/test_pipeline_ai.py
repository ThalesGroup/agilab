from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import urllib.error

import pandas as pd
import pytest


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


def test_ollama_available_models_deduplicates_and_handles_invalid_payloads(monkeypatch):
    class FakeResponse:
        def __init__(self, body: str):
            self._body = body

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return self._body.encode("utf-8")

    available = getattr(pipeline_ai._ollama_available_models, "__wrapped__", pipeline_ai._ollama_available_models)

    monkeypatch.setattr(
        pipeline_ai.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(
            '{"models":[{"name":"mistral:instruct"},{"name":"deepseek-coder"},{"name":"mistral:instruct"}]}'
        ),
    )
    assert available("http://127.0.0.1:11434") == ["mistral:instruct", "deepseek-coder"]

    monkeypatch.setattr(
        pipeline_ai.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse("not-json"),
    )
    assert available("http://127.0.0.1:11434") == []


def test_default_ollama_model_prefers_code_model_and_fallbacks(monkeypatch):
    monkeypatch.setattr(
        pipeline_ai,
        "_ollama_available_models",
        lambda _endpoint: ["mistral:instruct", "codestral:latest"],
    )
    assert pipeline_ai._default_ollama_model("http://ollama", prefer_code=True) == "codestral:latest"
    assert pipeline_ai._default_ollama_model("http://ollama", preferred="mistral:instruct") == "mistral:instruct"

    monkeypatch.setattr(pipeline_ai, "_ollama_available_models", lambda _endpoint: [])
    assert pipeline_ai._default_ollama_model("http://ollama", preferred="fallback-model") == "fallback-model"


def test_prompt_to_plaintext_flattens_list_content_and_unknown_roles():
    text = pipeline_ai._prompt_to_plaintext(
        [
            {"role": "system", "content": "rules"},
            {"role": "critic", "content": ["alpha", "beta"]},
        ],
        "continue",
    )

    assert "System: rules" in text
    assert "Critic: alpha\nbeta" in text
    assert text.endswith("User: continue")


def test_ollama_generate_success_and_error_paths(monkeypatch):
    captured = {}

    class FakeResponse:
        def __init__(self, body: str):
            self._body = body

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return self._body.encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["payload"] = request.data.decode("utf-8")
        return FakeResponse('{"response":"  print(42)  "}')

    monkeypatch.setattr(pipeline_ai.urllib.request, "urlopen", fake_urlopen)
    text = pipeline_ai._ollama_generate(
        endpoint="http://127.0.0.1:11434",
        model="deepseek-coder",
        prompt="hello",
        num_ctx=4096,
        num_predict=256,
        seed=7,
    )
    assert text == "print(42)"
    assert captured["url"].endswith("/api/generate")
    assert '"num_ctx": 4096' in captured["payload"]
    assert '"num_predict": 256' in captured["payload"]
    assert '"seed": 7' in captured["payload"]

    http_error = pipeline_ai.urllib.error.HTTPError(
        url="http://127.0.0.1:11434/api/generate",
        code=500,
        msg="boom",
        hdrs=None,
        fp=None,
    )
    http_error.read = lambda: b"server exploded"  # type: ignore[attr-defined]
    monkeypatch.setattr(
        pipeline_ai.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(http_error),
    )
    with pytest.raises(RuntimeError, match="Ollama error 500: server exploded"):
        pipeline_ai._ollama_generate(endpoint="http://127.0.0.1:11434", model="x", prompt="q")

    monkeypatch.setattr(
        pipeline_ai.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(pipeline_ai.urllib.error.URLError("down")),
    )
    with pytest.raises(RuntimeError, match="Unable to reach Ollama"):
        pipeline_ai._ollama_generate(endpoint="http://127.0.0.1:11434", model="x", prompt="q")


def test_ollama_generate_rejects_invalid_json_and_non_dict_payloads(monkeypatch):
    class FakeResponse:
        def __init__(self, body: str):
            self._body = body

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return self._body.encode("utf-8")

    monkeypatch.setattr(pipeline_ai.urllib.request, "urlopen", lambda *_args, **_kwargs: FakeResponse("not-json"))
    with pytest.raises(RuntimeError, match="invalid JSON"):
        pipeline_ai._ollama_generate(endpoint="http://127.0.0.1:11434", model="x", prompt="q")

    monkeypatch.setattr(pipeline_ai.urllib.request, "urlopen", lambda *_args, **_kwargs: FakeResponse('["bad"]'))
    with pytest.raises(RuntimeError, match="unexpected payload"):
        pipeline_ai._ollama_generate(endpoint="http://127.0.0.1:11434", model="x", prompt="q")


def test_chat_ollama_local_success_and_missing_model(monkeypatch):
    errors: list[str] = []
    fake_st = SimpleNamespace(session_state={}, error=lambda message: errors.append(str(message)))
    monkeypatch.setattr(pipeline_ai, "st", fake_st)
    monkeypatch.setattr(pipeline_ai, "_default_ollama_model", lambda *_args, **_kwargs: "fallback-model")
    monkeypatch.setattr(pipeline_ai, "_ollama_generate", lambda **kwargs: kwargs["prompt"])

    text, model = pipeline_ai.chat_ollama_local(
        "show chart",
        [{"role": "assistant", "content": "previous"}],
        {
            pipeline_ai.UOAIC_MODEL_ENV: "custom-model",
            pipeline_ai.UOAIC_TEMPERATURE_ENV: "0.3",
            pipeline_ai.UOAIC_NUM_CTX_ENV: "2048",
        },
    )

    assert model == "custom-model"
    assert "User: show chart" in text
    assert pipeline_ai.CODE_STRICT_INSTRUCTIONS in text

    monkeypatch.setattr(pipeline_ai, "_default_ollama_model", lambda *_args, **_kwargs: "")
    with pytest.raises(RuntimeError, match="Missing Ollama model"):
        pipeline_ai.chat_ollama_local("show chart", [], {})
    assert any("Ollama model name" in msg for msg in errors)


def test_chat_offline_success_stub_and_request_error(monkeypatch):
    errors: list[str] = []
    fake_st = SimpleNamespace(
        session_state={"gpt_oss_backend_active": "real"},
        error=lambda message: errors.append(str(message)),
    )
    monkeypatch.setattr(pipeline_ai, "st", fake_st)

    class FakeRequestException(Exception):
        pass

    class FakeResponse:
        def __init__(self, data):
            self._data = data

        def raise_for_status(self):
            return None

        def json(self):
            return self._data

    fake_requests = SimpleNamespace(
        exceptions=SimpleNamespace(RequestException=FakeRequestException),
        post=lambda endpoint, json, timeout: FakeResponse(
            {
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "text", "text": "print('ok')"}],
                    }
                ]
            }
        ),
    )
    monkeypatch.setitem(sys.modules, "requests", fake_requests)

    text, model = pipeline_ai.chat_offline("question", [], {"GPT_OSS_MODEL": "gpt-oss-mini"})
    assert text == "print('ok')"
    assert model == "gpt-oss-mini"

    fake_st.session_state["gpt_oss_backend_active"] = "stub"
    fake_requests.post = lambda endpoint, json, timeout: FakeResponse({"output": []})
    text, _model = pipeline_ai.chat_offline("smooth column", [], {"GPT_OSS_MODEL": "gpt-oss-mini"})
    assert "stub backend" in text

    def failing_post(endpoint, json, timeout):
        raise FakeRequestException("offline")

    fake_requests.post = failing_post
    with pytest.raises(RuntimeError):
        pipeline_ai.chat_offline("question", [], {"GPT_OSS_MODEL": "gpt-oss-mini"})
    assert any("Failed to reach GPT-OSS" in msg for msg in errors)


def test_chat_offline_handles_invalid_json_payload(monkeypatch):
    errors: list[str] = []
    fake_st = SimpleNamespace(session_state={}, error=lambda message: errors.append(str(message)))
    monkeypatch.setattr(pipeline_ai, "st", fake_st)

    class FakeRequestException(Exception):
        pass

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            raise ValueError("bad json")

    fake_requests = SimpleNamespace(
        exceptions=SimpleNamespace(RequestException=FakeRequestException),
        post=lambda endpoint, json, timeout: FakeResponse(),
    )
    monkeypatch.setitem(sys.modules, "requests", fake_requests)

    with pytest.raises(RuntimeError):
        pipeline_ai.chat_offline("question", [], {"GPT_OSS_MODEL": "gpt-oss-mini"})
    assert errors == ["GPT-OSS returned an invalid JSON payload."]


def test_chat_universal_offline_formats_sources_and_raises(monkeypatch):
    errors: list[str] = []
    fake_st = SimpleNamespace(session_state={}, error=lambda message: errors.append(str(message)))
    monkeypatch.setattr(pipeline_ai, "st", fake_st)

    class Doc:
        def __init__(self, metadata):
            self.metadata = metadata

    class Chain:
        def invoke(self, payload):
            assert "User: where from?" in payload["query"]
            return {
                "result": "answer",
                "source_documents": [
                    Doc({"source": "doc1.pdf", "page": 2}),
                    Doc({"path": "doc2.txt"}),
                ],
            }

    monkeypatch.setattr(
        pipeline_ai,
        "_ensure_uoaic_runtime",
        lambda envars: {"chain": Chain(), "model_label": "uoaic"},
    )

    text, model = pipeline_ai.chat_universal_offline("where from?", [], {})
    assert model == "uoaic"
    assert "answer" in text
    assert "doc1.pdf (page 2)" in text
    assert "doc2.txt" in text

    class BrokenChain:
        def invoke(self, payload):
            raise ValueError("broken rag")

    monkeypatch.setattr(
        pipeline_ai,
        "_ensure_uoaic_runtime",
        lambda envars: {"chain": BrokenChain(), "model_label": "uoaic"},
    )
    with pytest.raises(RuntimeError):
        pipeline_ai.chat_universal_offline("where from?", [], {})
    assert any("Universal Offline AI Chatbot invocation failed" in msg for msg in errors)


def test_ask_gpt_routes_to_selected_provider(monkeypatch):
    fake_st = SimpleNamespace(session_state={"lab_prompt": [], "lab_llm_provider": "gpt-oss"})
    monkeypatch.setattr(pipeline_ai, "st", fake_st)
    monkeypatch.setattr(pipeline_ai, "chat_offline", lambda *args: ("```python\nprint(1)\n```", "gpt-oss"))
    result = pipeline_ai.ask_gpt("q", Path("df.csv"), "page", {})
    assert result[2:] == ["gpt-oss", "print(1)", ""]

    fake_st.session_state["lab_llm_provider"] = pipeline_ai.UOAIC_PROVIDER
    fake_st.session_state[pipeline_ai.UOAIC_MODE_STATE_KEY] = pipeline_ai.UOAIC_MODE_RAG
    monkeypatch.setattr(pipeline_ai, "chat_universal_offline", lambda *args: ("final answer.", "uoaic"))
    result = pipeline_ai.ask_gpt("q", Path("df.csv"), "page", {})
    assert result[2:] == ["uoaic", "", "final answer."]

    fake_st.session_state["lab_llm_provider"] = "openai"
    monkeypatch.setattr(pipeline_ai, "chat_online", lambda *args: ("```python\nprint(2)\n```", "gpt-5"))
    result = pipeline_ai.ask_gpt("q", Path("df.csv"), "page", {})
    assert result[2:] == ["gpt-5", "print(2)", ""]


def test_maybe_autofix_generated_code_paths(monkeypatch):
    logs: list[str] = []
    fake_st = SimpleNamespace(
        session_state={
            "lab_llm_provider": pipeline_ai.UOAIC_PROVIDER,
            pipeline_ai.UOAIC_AUTOFIX_STATE_KEY: True,
            pipeline_ai.UOAIC_AUTOFIX_MAX_STATE_KEY: 2,
            "loaded_df": pd.DataFrame({"x": [1]}),
        }
    )
    monkeypatch.setattr(pipeline_ai, "st", fake_st)
    push_run_log = lambda *_args: logs.append(_args[1])
    get_run_placeholder = lambda _page: "placeholder"
    env = SimpleNamespace(envars={})

    code, model, detail = pipeline_ai._maybe_autofix_generated_code(
        original_request="q",
        df_path=Path("df.csv"),
        index_page="page",
        env=env,
        merged_code="df['y'] = df['x'] + 1",
        model_label="m",
        detail="",
        load_df_cached=lambda path: pd.DataFrame({"x": [1]}),
        push_run_log=push_run_log,
        get_run_placeholder=get_run_placeholder,
    )
    assert code == "df['y'] = df['x'] + 1"
    assert any("validated successfully" in entry for entry in logs)

    logs.clear()
    monkeypatch.setattr(
        pipeline_ai,
        "ask_gpt",
        lambda *args, **kwargs: [Path("df.csv"), "fix", "m2", "df['z'] = df['x'] * 2", "fixed"],
    )
    code, model, detail = pipeline_ai._maybe_autofix_generated_code(
        original_request="q",
        df_path=Path("df.csv"),
        index_page="page",
        env=env,
        merged_code="raise ValueError('boom')",
        model_label="m",
        detail="",
        load_df_cached=lambda path: pd.DataFrame({"x": [1]}),
        push_run_log=push_run_log,
        get_run_placeholder=get_run_placeholder,
    )
    assert code.startswith("# fixed\n")
    assert "df['z'] = df['x'] * 2" in code
    assert model == "m2"
    assert detail == "fixed"
    assert any("success on attempt 1" in entry for entry in logs)

    logs.clear()
    fake_st.session_state["loaded_df"] = pd.DataFrame()
    fake_st.session_state["df_file"] = ""
    code, model, detail = pipeline_ai._maybe_autofix_generated_code(
        original_request="q",
        df_path=Path("df.csv"),
        index_page="page",
        env=env,
        merged_code="raise ValueError('boom')",
        model_label="m",
        detail="",
        load_df_cached=lambda path: pd.DataFrame(),
        push_run_log=push_run_log,
        get_run_placeholder=get_run_placeholder,
    )
    assert code == "raise ValueError('boom')"
    assert any("no dataframe is loaded" in entry for entry in logs)
