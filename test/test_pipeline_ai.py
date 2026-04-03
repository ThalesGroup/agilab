from __future__ import annotations

from contextlib import nullcontext
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


def test_extract_code_handles_plain_python_empty_and_non_python_text():
    assert pipeline_ai.extract_code("value = 1\nprint(value)") == ("value = 1\nprint(value)", "")
    assert pipeline_ai.extract_code("") == ("", "")
    assert pipeline_ai.extract_code("not valid python!") == ("", "not valid python!")


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


def test_response_to_text_handles_text_chunks_and_empty_payloads():
    chunked = SimpleNamespace(output=[SimpleNamespace(type="tool", text=SimpleNamespace(value="chunk"))])
    assert pipeline_ai._response_to_text(chunked) == "chunk"

    broken_legacy = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace())])
    assert pipeline_ai._response_to_text(broken_legacy) == ""
    assert pipeline_ai._response_to_text(None) == ""


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


def test_load_uoaic_modules_reports_missing_package_and_dependency(monkeypatch, tmp_path):
    errors: list[str] = []
    fake_st = SimpleNamespace(session_state={}, error=lambda message: errors.append(str(message)))
    monkeypatch.setattr(pipeline_ai, "st", fake_st)

    monkeypatch.setattr(
        pipeline_ai.importlib_metadata,
        "distribution",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(pipeline_ai.importlib_metadata.PackageNotFoundError()),
    )
    with pytest.raises(RuntimeError):
        pipeline_ai._load_uoaic_modules()
    assert any("universal-offline-ai-chatbot" in message for message in errors)

    class FakeDist:
        files = []

        @staticmethod
        def locate_file(path):
            return tmp_path / "missing"

        @staticmethod
        def read_text(_name):
            return ""

    monkeypatch.setattr(pipeline_ai.importlib_metadata, "distribution", lambda *_args, **_kwargs: FakeDist())
    monkeypatch.setattr(
        pipeline_ai.importlib,
        "import_module",
        lambda _name: (_ for _ in ()).throw(ImportError("missing dep", name="numpy")),
    )
    errors.clear()
    with pytest.raises(RuntimeError):
        pipeline_ai._load_uoaic_modules()
    assert any("Missing dependency `numpy`" in message for message in errors)


def test_ensure_uoaic_runtime_handles_missing_cached_and_build_paths(monkeypatch, tmp_path):
    errors: list[str] = []
    fake_st = SimpleNamespace(
        session_state={},
        error=lambda message: errors.append(str(message)),
        spinner=lambda *_args, **_kwargs: nullcontext(),
    )
    monkeypatch.setattr(pipeline_ai, "st", fake_st)
    monkeypatch.setattr(pipeline_ai, "_resolve_uoaic_path", lambda raw, env: Path(raw))

    with pytest.raises(RuntimeError, match="Missing Universal Offline data directory"):
        pipeline_ai._ensure_uoaic_runtime({})
    assert any("Configure the Universal Offline data directory" in message for message in errors)

    data_dir = tmp_path / "docs"
    db_dir = tmp_path / "vectorstore" / "db"
    data_dir.mkdir(parents=True)
    cached_runtime = {
        "data_path": pipeline_ai.normalize_path(data_dir),
        "db_path": pipeline_ai.normalize_path(db_dir),
        "chain": "cached-chain",
    }
    fake_st.session_state = {
        "env": object(),
        pipeline_ai.UOAIC_DATA_STATE_KEY: str(data_dir),
        pipeline_ai.UOAIC_DB_STATE_KEY: str(db_dir),
        pipeline_ai.UOAIC_RUNTIME_KEY: cached_runtime,
    }
    assert pipeline_ai._ensure_uoaic_runtime({}) is cached_runtime

    built: dict[str, object] = {}
    fake_st.session_state = {
        "env": object(),
        pipeline_ai.UOAIC_DATA_STATE_KEY: str(data_dir),
        pipeline_ai.UOAIC_DB_STATE_KEY: str(db_dir),
    }

    chunker = SimpleNamespace(create_chunks=lambda docs: ["chunked"])
    embedding = SimpleNamespace(get_embedding_model=lambda: "embedding-model")
    loader = SimpleNamespace(load_pdf_files=lambda path: ["doc.pdf"])
    model_loader = SimpleNamespace(load_llm=lambda: SimpleNamespace(model_name="ollama-mini"))
    prompts = SimpleNamespace(
        CUSTOM_PROMPT_TEMPLATE="template",
        set_custom_prompt=lambda template: f"PROMPT::{template}",
    )
    qa_chain = SimpleNamespace(
        setup_qa_chain=lambda llm, db, prompt: {"llm": llm, "db": db, "prompt": prompt}
    )
    vectorstore = SimpleNamespace(
        build_vector_db=lambda chunks, embedding_model, path: built.update(
            chunks=chunks,
            embedding_model=embedding_model,
            path=path,
        ),
        load_vector_db=lambda path, embedding_model: {"path": path, "embedding_model": embedding_model},
    )
    monkeypatch.setattr(
        pipeline_ai,
        "_load_uoaic_modules",
        lambda: (chunker, embedding, loader, model_loader, prompts, qa_chain, vectorstore),
    )

    runtime = pipeline_ai._ensure_uoaic_runtime({})
    assert runtime["model_label"] == "ollama-mini"
    assert runtime["prompt"] == "PROMPT::template"
    assert runtime["vector_store"]["path"] == str(db_dir)
    assert built["path"] == str(db_dir)
    assert built["chunks"] == ["chunked"]


def test_chat_online_handles_success_key_prompt_and_model_errors(monkeypatch):
    infos: list[str] = []
    errors: list[str] = []
    prompts: list[str] = []
    fake_st = SimpleNamespace(
        session_state={},
        info=lambda message: infos.append(str(message)),
        error=lambda message: errors.append(str(message)),
    )
    monkeypatch.setattr(pipeline_ai, "st", fake_st)
    monkeypatch.setattr(pipeline_ai, "_load_env_file_map", lambda _path: {})
    monkeypatch.setattr(pipeline_ai, "prompt_for_openai_api_key", lambda message: prompts.append(str(message)))

    class FakeOpenAIError(Exception):
        def __init__(self, message, status_code=None):
            super().__init__(message)
            self.status_code = status_code

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAIError=FakeOpenAIError))

    monkeypatch.setattr(pipeline_ai, "ensure_cached_api_key", lambda _envars: "")
    monkeypatch.setattr(pipeline_ai, "is_placeholder_api_key", lambda key: not key)
    with pytest.raises(RuntimeError, match="OpenAI API key unavailable"):
        pipeline_ai.chat_online("question", [], {})
    assert any("OpenAI API key appears missing" in message for message in prompts)

    class SuccessClient:
        class chat:
            class completions:
                @staticmethod
                def create(model, messages):
                    return SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content="```python\nprint(1)\n```"))]
                    )

    monkeypatch.setattr(pipeline_ai, "ensure_cached_api_key", lambda _envars: "sk-demo-1234567890")
    monkeypatch.setattr(pipeline_ai, "is_placeholder_api_key", lambda _key: False)
    monkeypatch.setattr(
        pipeline_ai,
        "make_openai_client_and_model",
        lambda envars, api_key: (SuccessClient(), "gpt-5", False),
    )
    text, model = pipeline_ai.chat_online("question", [], {})
    assert "print(1)" in text
    assert model == "gpt-5"

    class FailingClient:
        class chat:
            class completions:
                @staticmethod
                def create(model, messages):
                    raise FakeOpenAIError("model_not_found", status_code=404)

    monkeypatch.setattr(
        pipeline_ai,
        "make_openai_client_and_model",
        lambda envars, api_key: (FailingClient(), "missing-model", False),
    )
    with pytest.raises(RuntimeError, match="model_not_found"):
        pipeline_ai.chat_online("question", [], {})
    assert any("requested model is unavailable" in message for message in infos)


def test_configure_assistant_engine_and_gpt_oss_controls(monkeypatch):
    messages: list[tuple[str, str]] = []

    class FakeSidebar:
        def selectbox(self, label, options, index=0, help=None):
            if label == "Assistant engine":
                return "GPT-OSS (local)"
            if label == "GPT-OSS backend":
                return "stub"
            raise AssertionError(label)

        def text_input(self, label, value="", help=None):
            return value

        def button(self, *args, **kwargs):
            return False

        def warning(self, message):
            messages.append(("warning", str(message)))

        def success(self, message):
            messages.append(("success", str(message)))

        def info(self, message):
            messages.append(("info", str(message)))

    fake_st = SimpleNamespace(
        session_state={
            "index_page": "page",
            "page": [0, 0, 0, "stale-model"],
            "gpt_oss_server_started": True,
            "gpt_oss_backend_active": "stub",
            "gpt_oss_endpoint": "http://127.0.0.1:8000",
        },
        sidebar=FakeSidebar(),
    )
    monkeypatch.setattr(pipeline_ai, "st", fake_st)
    env = SimpleNamespace(envars={})

    provider = pipeline_ai.configure_assistant_engine(env)
    assert provider == "gpt-oss"
    assert env.envars["LAB_LLM_PROVIDER"] == "gpt-oss"
    assert fake_st.session_state["_experiment_reload_required"] is True
    assert fake_st.session_state["page"][3] == ""

    pipeline_ai.gpt_oss_controls(env)
    assert any(kind == "success" and "GPT-OSS server running" in message for kind, message in messages)


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
