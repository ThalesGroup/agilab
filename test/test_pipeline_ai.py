from __future__ import annotations

from contextlib import nullcontext
import importlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from types import ModuleType
import urllib.error
from unittest.mock import patch

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


def _load_module_with_missing(module_name: str, relative_path: str, *missing_modules: str):
    original_import = __import__

    def _patched_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in missing_modules:
            raise ModuleNotFoundError(name)
        return original_import(name, globals, locals, fromlist, level)

    with patch("builtins.__import__", _patched_import):
        return _load_module(module_name, relative_path)


pipeline_ai = _load_module("agilab.pipeline_ai", "src/agilab/pipeline_ai.py")
pipeline_ai_support_direct = _load_module(
    "agilab.pipeline_ai_support_direct",
    "src/agilab/pipeline_ai_support.py",
)
pipeline_ai_uoaic_direct = _load_module(
    "agilab.pipeline_ai_uoaic_direct",
    "src/agilab/pipeline_ai_uoaic.py",
)
pipeline_ai_controls_direct = _load_module(
    "agilab.pipeline_ai_controls_direct",
    "src/agilab/pipeline_ai_controls.py",
)


@pytest.fixture(autouse=True)
def reload_pipeline_ai_modules(isolate_home_for_root_tests):
    """Keep the real pipeline_ai module graph clean across the full root suite."""
    global pipeline_ai
    _load_module("agilab.pipeline_ai_support", "src/agilab/pipeline_ai_support.py")
    _load_module("agilab.pipeline_ai_uoaic", "src/agilab/pipeline_ai_uoaic.py")
    _load_module("agilab.pipeline_ai_controls", "src/agilab/pipeline_ai_controls.py")
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


def test_format_uoaic_question_handles_list_content_blank_entries_and_fallback_roles():
    text = pipeline_ai._format_uoaic_question(
        [
            {"role": "user", "content": ["first", "second"]},
            {"role": "", "content": "fallback role"},
            {"role": "assistant", "content": "   "},
        ],
        "next",
    )

    assert "User: first\nsecond" in text
    assert "Assistant: fallback role" in text
    assert "Assistant:    " not in text


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


def test_resolve_uoaic_path_uses_cwd_for_relative_and_absolute_paths(monkeypatch, tmp_path):
    absolute = (tmp_path / "docs").resolve()
    monkeypatch.chdir(tmp_path)

    assert pipeline_ai._resolve_uoaic_path(str(absolute), env=None) == absolute
    assert pipeline_ai._resolve_uoaic_path("docs/manual.pdf", env=None) == (tmp_path / "docs" / "manual.pdf").resolve()


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


def test_pipeline_ai_import_falls_back_when_pipeline_modules_are_unavailable():
    fallback = _load_module_with_missing(
        "agilab.pipeline_ai_fallback",
        "src/agilab/pipeline_ai.py",
        "agilab.pipeline_openai",
        "agilab.pipeline_steps",
    )

    assert callable(fallback.chat_online)
    assert callable(fallback._pipeline_export_root)
    assert callable(fallback.prompt_for_openai_api_key)


def test_pipeline_ai_import_falls_back_when_env_and_ai_submodules_are_unavailable():
    fallback = _load_module_with_missing(
        "agilab.pipeline_ai_full_fallback",
        "src/agilab/pipeline_ai.py",
        "agilab.env_file_utils",
        "agilab.pipeline_ai_support",
        "agilab.pipeline_ai_uoaic",
        "agilab.pipeline_ai_controls",
    )

    assert fallback._load_env_file_map(Path("missing.env")) == {}
    assert fallback.UOAIC_PROVIDER == "universal-offline-ai-chatbot"
    assert callable(fallback._configure_assistant_engine_impl)
    assert callable(fallback._gpt_oss_controls_impl)


def test_pipeline_ai_import_fallback_raises_when_env_file_utils_local_spec_is_missing(monkeypatch):
    original_spec = importlib.util.spec_from_file_location

    def _fake_spec(name, location, *args, **kwargs):
        if name == "agilab_env_file_utils_fallback":
            return None
        return original_spec(name, location, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "spec_from_file_location", _fake_spec)

    with pytest.raises(ModuleNotFoundError, match="env_file_utils"):
        _load_module_with_missing(
            "agilab.pipeline_ai_fallback_missing_env_file_utils",
            "src/agilab/pipeline_ai.py",
            "agilab.env_file_utils",
        )


def test_pipeline_ai_import_fallback_raises_when_pipeline_openai_local_spec_is_missing(monkeypatch):
    original_spec = importlib.util.spec_from_file_location

    def _fake_spec(name, location, *args, **kwargs):
        if name == "agilab_pipeline_openai_fallback":
            return None
        return original_spec(name, location, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "spec_from_file_location", _fake_spec)

    with pytest.raises(ModuleNotFoundError, match="pipeline_openai"):
        _load_module_with_missing(
            "agilab.pipeline_ai_fallback_missing_pipeline_openai",
            "src/agilab/pipeline_ai.py",
            "agilab.pipeline_openai",
            "agilab.pipeline_steps",
        )


def test_pipeline_ai_import_fallback_raises_when_pipeline_steps_local_spec_is_missing(monkeypatch):
    original_spec = importlib.util.spec_from_file_location
    fake_openai = SimpleNamespace(
        ensure_cached_api_key=lambda *_args, **_kwargs: "",
        is_placeholder_api_key=lambda *_args, **_kwargs: False,
        make_openai_client_and_model=lambda *_args, **_kwargs: (None, "", False),
        prompt_for_openai_api_key=lambda *_args, **_kwargs: "",
    )

    def _fake_spec(name, location, *args, **kwargs):
        if name == "agilab_pipeline_steps_fallback":
            return None
        return original_spec(name, location, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "spec_from_file_location", _fake_spec)
    monkeypatch.setitem(sys.modules, "agilab.pipeline_openai", fake_openai)

    with pytest.raises(ModuleNotFoundError, match="pipeline_steps"):
        _load_module_with_missing(
            "agilab.pipeline_ai_fallback_missing_pipeline_steps",
            "src/agilab/pipeline_ai.py",
            "agilab.pipeline_steps",
        )


def test_pipeline_ai_import_fallback_raises_when_pipeline_ai_support_local_spec_is_missing(monkeypatch):
    original_spec = importlib.util.spec_from_file_location

    def _fake_spec(name, location, *args, **kwargs):
        if name == "agilab_pipeline_ai_support_fallback":
            return None
        return original_spec(name, location, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "spec_from_file_location", _fake_spec)

    with pytest.raises(ModuleNotFoundError, match="pipeline_ai_support"):
        _load_module_with_missing(
            "agilab.pipeline_ai_fallback_missing_pipeline_ai_support",
            "src/agilab/pipeline_ai.py",
            "agilab.pipeline_ai_support",
        )


def test_pipeline_ai_import_fallback_raises_when_pipeline_ai_uoaic_local_spec_is_missing(monkeypatch):
    original_spec = importlib.util.spec_from_file_location

    def _fake_spec(name, location, *args, **kwargs):
        if name == "agilab_pipeline_ai_uoaic_fallback":
            return None
        return original_spec(name, location, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "spec_from_file_location", _fake_spec)

    with pytest.raises(ModuleNotFoundError, match="pipeline_ai_uoaic"):
        _load_module_with_missing(
            "agilab.pipeline_ai_fallback_missing_pipeline_ai_uoaic",
            "src/agilab/pipeline_ai.py",
            "agilab.pipeline_ai_uoaic",
        )


def test_pipeline_ai_import_fallback_raises_when_pipeline_ai_controls_local_spec_is_missing(monkeypatch):
    original_spec = importlib.util.spec_from_file_location

    def _fake_spec(name, location, *args, **kwargs):
        if name == "agilab_pipeline_ai_controls_fallback":
            return None
        return original_spec(name, location, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "spec_from_file_location", _fake_spec)

    with pytest.raises(ModuleNotFoundError, match="pipeline_ai_controls"):
        _load_module_with_missing(
            "agilab.pipeline_ai_fallback_missing_pipeline_ai_controls",
            "src/agilab/pipeline_ai.py",
            "agilab.pipeline_ai_controls",
        )


def test_load_uoaic_modules_loads_modules_from_wheel_files(monkeypatch, tmp_path):
    errors: list[str] = []
    fake_st = SimpleNamespace(session_state={}, error=lambda message: errors.append(str(message)))
    monkeypatch.setattr(pipeline_ai, "st", fake_st)

    wheel_root = tmp_path / "wheel"
    src_dir = wheel_root / "src"
    src_dir.mkdir(parents=True)
    (wheel_root / "site.dist-info").write_text("dist-info marker", encoding="utf-8")

    module_files = {}
    for short in ("chunker", "embedding", "loader", "model_loader", "prompts", "qa_chain", "vectorstore"):
        file_path = src_dir / f"{short}.py"
        file_path.write_text(f"IDENT = '{short}'\n", encoding="utf-8")
        module_files[f"src/{short}.py"] = file_path

    class FakeDist:
        files = list(module_files)

        @staticmethod
        def locate_file(path):
            if path == "":
                return wheel_root / "site.dist-info"
            return module_files[str(path)]

        @staticmethod
        def read_text(_name):
            return ""

    monkeypatch.setattr(pipeline_ai.importlib_metadata, "distribution", lambda *_args, **_kwargs: FakeDist())
    monkeypatch.setattr(
        pipeline_ai.importlib,
        "import_module",
        lambda name: (_ for _ in ()).throw(ImportError("fallback", name=name)),
    )

    modules = pipeline_ai._load_uoaic_modules()

    assert [module.IDENT for module in modules] == [
        "chunker",
        "embedding",
        "loader",
        "model_loader",
        "prompts",
        "qa_chain",
        "vectorstore",
    ]
    assert errors == []


def test_load_uoaic_modules_reports_generic_file_load_failure(monkeypatch, tmp_path):
    errors: list[str] = []
    fake_st = SimpleNamespace(session_state={}, error=lambda message: errors.append(str(message)))
    monkeypatch.setattr(pipeline_ai, "st", fake_st)

    wheel_root = tmp_path / "wheel"
    wheel_root.mkdir()

    class FakeDist:
        files = []

        @staticmethod
        def locate_file(path):
            if path == "":
                return wheel_root
            return wheel_root / str(path)

        @staticmethod
        def read_text(_name):
            return ""

    monkeypatch.setattr(pipeline_ai.importlib_metadata, "distribution", lambda *_args, **_kwargs: FakeDist())
    monkeypatch.setattr(
        pipeline_ai.importlib,
        "import_module",
        lambda name: (_ for _ in ()).throw(ImportError("generic failure", name=name)),
    )

    with pytest.raises(RuntimeError):
        pipeline_ai._load_uoaic_modules()

    assert any("Failed to load Universal Offline AI Chatbot module files" in message for message in errors)


def test_load_uoaic_modules_record_fallback_and_spec_failure_paths(monkeypatch, tmp_path):
    errors: list[str] = []
    fake_st = SimpleNamespace(session_state={}, error=lambda message: errors.append(str(message)))
    monkeypatch.setattr(pipeline_ai, "st", fake_st)

    wheel_root = tmp_path / "wheel"
    wheel_root.mkdir()
    chunker_file = wheel_root / "src" / "chunker.py"
    chunker_file.parent.mkdir(parents=True)
    chunker_file.write_text("IDENT = 'chunker'\n", encoding="utf-8")

    class FakeDist:
        files = []

        @staticmethod
        def locate_file(path):
            return wheel_root / str(path)

        @staticmethod
        def read_text(_name):
            return "src/chunker.py,,\n"

    monkeypatch.setattr(pipeline_ai.importlib_metadata, "distribution", lambda *_args, **_kwargs: FakeDist())
    monkeypatch.setattr(
        pipeline_ai.importlib,
        "import_module",
        lambda name: (_ for _ in ()).throw(ImportError("fallback", name=name)),
    )

    class _Loader:
        @staticmethod
        def exec_module(_module):
            raise RuntimeError("boom")

    monkeypatch.setattr(
        pipeline_ai.importlib.util,
        "spec_from_file_location",
        lambda *_args, **_kwargs: SimpleNamespace(loader=_Loader()),
    )

    with pytest.raises(RuntimeError):
        pipeline_ai._load_uoaic_modules()

    assert any("Failed to load Universal Offline AI Chatbot module files" in message for message in errors)


def test_load_uoaic_modules_record_read_failure_uses_generic_error(monkeypatch, tmp_path):
    errors: list[str] = []
    fake_st = SimpleNamespace(session_state={}, error=lambda message: errors.append(str(message)))
    monkeypatch.setattr(pipeline_ai, "st", fake_st)

    wheel_root = tmp_path / "wheel"
    wheel_root.mkdir()

    class FakeDist:
        files = []

        @staticmethod
        def locate_file(path):
            return wheel_root / str(path)

        @staticmethod
        def read_text(_name):
            raise RuntimeError("record broken")

    monkeypatch.setattr(pipeline_ai.importlib_metadata, "distribution", lambda *_args, **_kwargs: FakeDist())
    monkeypatch.setattr(
        pipeline_ai.importlib,
        "import_module",
        lambda name: (_ for _ in ()).throw(ImportError("fallback", name=name)),
    )

    with pytest.raises(RuntimeError):
        pipeline_ai._load_uoaic_modules()

    assert any("Failed to load Universal Offline AI Chatbot module files" in message for message in errors)


def test_pipeline_ai_support_direct_module_covers_ollama_defaults_and_safety_edges(monkeypatch):
    monkeypatch.setattr(
        pipeline_ai_support_direct,
        "_ollama_available_models",
        lambda _endpoint: ["llama3:70b", "codestral:latest"],
    )
    assert (
        pipeline_ai_support_direct._default_ollama_model(
            "http://ollama",
            preferred="missing",
            prefer_code=True,
        )
        == "codestral:latest"
    )
    assert (
        pipeline_ai_support_direct._default_ollama_model(
            "http://ollama",
            preferred="llama3:70b",
        )
        == "llama3:70b"
    )

    monkeypatch.setattr(
        pipeline_ai_support_direct,
        "_ollama_available_models",
        lambda _endpoint: ["llama3:70b"],
    )
    assert (
        pipeline_ai_support_direct._default_ollama_model(
            "http://ollama",
            preferred="missing",
        )
        == "llama3:70b"
    )

    monkeypatch.setattr(
        pipeline_ai_support_direct,
        "_ollama_available_models",
        lambda _endpoint: [],
    )
    assert (
        pipeline_ai_support_direct._default_ollama_model(
            "http://ollama",
            preferred="fallback-model",
        )
        == "fallback-model"
    )

    with pytest.raises(pipeline_ai_support_direct._UnsafeCodeError, match="Syntax error"):
        pipeline_ai_support_direct._validate_code_safety("def broken(:\n    pass")
    with pytest.raises(pipeline_ai_support_direct._UnsafeCodeError, match="Import statements are not allowed"):
        pipeline_ai_support_direct._validate_code_safety("import os")
    with pytest.raises(pipeline_ai_support_direct._UnsafeCodeError, match="Import statements are not allowed"):
        pipeline_ai_support_direct._validate_code_safety("from os import path")
    with pytest.raises(pipeline_ai_support_direct._UnsafeCodeError, match="Call to blocked builtin"):
        pipeline_ai_support_direct._validate_code_safety("open('x')")
    with pytest.raises(pipeline_ai_support_direct._UnsafeCodeError, match="Access to '__class__'"):
        pipeline_ai_support_direct._validate_code_safety("x = 1\nx.__class__")
    with pytest.raises(pipeline_ai_support_direct._UnsafeCodeError, match="Access to module 'os'"):
        pipeline_ai_support_direct._validate_code_safety("os.system('echo hi')")

    updated, error = pipeline_ai_support_direct._exec_code_on_df(
        "import os",
        pd.DataFrame({"x": [1]}),
    )
    assert updated is None
    assert "Safety check failed" in error

    monkeypatch.setattr(
        pipeline_ai_support_direct,
        "_validate_code_safety",
        lambda _code: None,
    )
    monkeypatch.setattr(
        pipeline_ai_support_direct,
        "_SAFE_BUILTINS",
        {
            "danger": lambda: (_ for _ in ()).throw(
                pipeline_ai_support_direct._UnsafeCodeError("boom")
            )
        },
    )
    with pytest.raises(pipeline_ai_support_direct._UnsafeCodeError, match="boom"):
        pipeline_ai_support_direct._exec_code_on_df("danger()", pd.DataFrame({"x": [1]}))


def test_pipeline_ai_support_direct_module_loads_uoaic_modules_with_default_dependencies(monkeypatch, tmp_path):
    class FakeDist:
        @staticmethod
        def locate_file(_path):
            return tmp_path

    monkeypatch.setattr(
        pipeline_ai_support_direct.importlib_metadata,
        "distribution",
        lambda _name: FakeDist(),
    )
    monkeypatch.setattr(
        pipeline_ai_support_direct.importlib,
        "import_module",
        lambda name: SimpleNamespace(module_name=name),
    )

    modules = pipeline_ai_support_direct._load_uoaic_modules()

    assert [module.module_name for module in modules] == [
        "src.chunker",
        "src.embedding",
        "src.loader",
        "src.model_loader",
        "src.prompts",
        "src.qa_chain",
        "src.vectorstore",
    ]


def test_pipeline_ai_uoaic_import_falls_back_when_support_module_is_unavailable():
    fallback = _load_module_with_missing(
        "agilab.pipeline_ai_uoaic_fallback",
        "src/agilab/pipeline_ai_uoaic.py",
        "agilab.pipeline_ai_support",
    )

    assert fallback.UOAIC_PROVIDER == "universal-offline-ai-chatbot"
    assert callable(fallback.resolve_uoaic_path)
    assert callable(fallback.ensure_uoaic_runtime)


def test_pipeline_ai_uoaic_import_fallback_raises_when_support_local_spec_is_missing(monkeypatch):
    original_spec = importlib.util.spec_from_file_location

    def _fake_spec(name, location, *args, **kwargs):
        if name == "agilab_pipeline_ai_support_fallback":
            return None
        return original_spec(name, location, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "spec_from_file_location", _fake_spec)

    with pytest.raises(ModuleNotFoundError, match="pipeline_ai_support"):
        _load_module_with_missing(
            "agilab.pipeline_ai_uoaic_missing_support_spec",
            "src/agilab/pipeline_ai_uoaic.py",
            "agilab.pipeline_ai_support",
        )


def test_pipeline_ai_uoaic_direct_module_covers_default_wrappers(monkeypatch, tmp_path):
    monkeypatch.setattr(
        pipeline_ai_uoaic_direct.Path,
        "cwd",
        classmethod(lambda cls: tmp_path),
    )
    monkeypatch.setattr(
        pipeline_ai_uoaic_direct,
        "_resolve_uoaic_path_impl",
        lambda raw_path, base_dir=None: Path(base_dir or tmp_path) / raw_path,
    )
    assert pipeline_ai_uoaic_direct.resolve_uoaic_path("docs", env=object()) == tmp_path / "docs"

    captured_load: dict[str, object] = {}
    monkeypatch.setattr(
        pipeline_ai_uoaic_direct,
        "_load_uoaic_modules_impl",
        lambda **kwargs: captured_load.update(kwargs) or ("loaded",),
    )
    sentinel_distribution = lambda _name: "dist"
    sentinel_import_module = lambda name: f"import:{name}"
    sentinel_spec = lambda *args, **kwargs: "spec"
    sentinel_from_spec = lambda spec: f"module:{spec}"
    monkeypatch.setattr(
        pipeline_ai_uoaic_direct.importlib.metadata,
        "distribution",
        sentinel_distribution,
    )
    monkeypatch.setattr(
        pipeline_ai_uoaic_direct.importlib,
        "import_module",
        sentinel_import_module,
    )
    monkeypatch.setattr(
        pipeline_ai_uoaic_direct.importlib.util,
        "spec_from_file_location",
        sentinel_spec,
    )
    monkeypatch.setattr(
        pipeline_ai_uoaic_direct.importlib.util,
        "module_from_spec",
        sentinel_from_spec,
    )

    assert pipeline_ai_uoaic_direct.load_uoaic_modules() == ("loaded",)
    assert captured_load == {
        "distribution_fn": sentinel_distribution,
        "import_module_fn": sentinel_import_module,
        "spec_from_file_location_fn": sentinel_spec,
        "module_from_spec_fn": sentinel_from_spec,
    }

    captured_runtime: dict[str, object] = {}

    def _fake_ensure(envars, **kwargs):
        captured_runtime["envars"] = envars
        captured_runtime["resolved"] = kwargs["resolve_uoaic_path"]("docs", None)
        captured_runtime["modules"] = kwargs["load_uoaic_modules"]()
        return {"runtime": True}

    monkeypatch.setattr(
        pipeline_ai_uoaic_direct,
        "_ensure_uoaic_runtime_impl",
        _fake_ensure,
    )
    monkeypatch.setattr(
        pipeline_ai_uoaic_direct,
        "resolve_uoaic_path",
        lambda raw_path, env, pipeline_export_root_fn=None: tmp_path / "resolved" / raw_path,
    )
    deps = pipeline_ai_uoaic_direct.UoaicRuntimeDeps(
        session_state={},
        normalize_path_fn=str,
        pipeline_export_root_fn=lambda _env: tmp_path,
        load_modules_fn=lambda: ("modules",),
        error_sink=lambda _message: None,
        spinner_factory=nullcontext,
    )

    assert pipeline_ai_uoaic_direct.ensure_uoaic_runtime({}, env=object(), deps=deps) == {"runtime": True}
    assert captured_runtime["resolved"] == tmp_path / "resolved" / "docs"
    assert captured_runtime["modules"] == ("modules",)


def test_pipeline_ai_uoaic_render_controls_swallows_default_directory_creation_errors(monkeypatch, tmp_path):
    messages: list[tuple[str, str]] = []

    class _Sidebar:
        def selectbox(self, _label, options, index=0, **_kwargs):
            return options[1]

        def text_input(self, _label, value="", **_kwargs):
            return value

        def slider(self, _label, *, value, **_kwargs):
            return value

        def number_input(self, _label, *, value, **_kwargs):
            return value

        def checkbox(self, _label, *, value=False, **_kwargs):
            return value

        def button(self, *_args, **_kwargs):
            return False

        def expander(self, *_args, **_kwargs):
            return nullcontext()

        def caption(self, message):
            messages.append(("caption", str(message)))

        def warning(self, message):
            messages.append(("warning", str(message)))

        def info(self, message):
            messages.append(("info", str(message)))

        def error(self, message):
            messages.append(("error", str(message)))

        def success(self, message):
            messages.append(("success", str(message)))

    original_mkdir = pipeline_ai_uoaic_direct.Path.mkdir
    default_data_path = tmp_path / "uoaic" / "data"
    default_db_parent = tmp_path / "uoaic" / "vectorstore"

    def _fake_mkdir(self, *args, **kwargs):
        if self in {default_data_path, default_db_parent}:
            raise OSError("mkdir boom")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(
        pipeline_ai_uoaic_direct.Path,
        "mkdir",
        _fake_mkdir,
    )
    monkeypatch.setattr(
        pipeline_ai_uoaic_direct,
        "DEFAULT_UOAIC_BASE",
        tmp_path / "uoaic",
    )

    env = SimpleNamespace(envars={})
    deps = pipeline_ai_uoaic_direct.UoaicControlDeps(
        session_state={"lab_llm_provider": pipeline_ai_uoaic_direct.UOAIC_PROVIDER},
        sidebar=_Sidebar(),
        normalize_path_fn=str,
        default_ollama_model_fn=lambda *_args, **_kwargs: "",
        ensure_runtime_fn=lambda _envars: {"runtime": True},
        spinner_factory=nullcontext,
        normalize_user_path_fn=lambda raw: str(raw),
    )

    pipeline_ai_uoaic_direct.render_universal_offline_controls(env, deps=deps)

    assert env.envars[pipeline_ai_uoaic_direct.UOAIC_DATA_ENV] == str(default_data_path)
    assert env.envars[pipeline_ai_uoaic_direct.UOAIC_DB_ENV] == str(
        tmp_path / "uoaic" / "vectorstore" / "db_faiss"
    )


def test_pipeline_ai_controls_import_falls_back_when_uoaic_module_is_unavailable():
    fallback = _load_module_with_missing(
        "agilab.pipeline_ai_controls_fallback",
        "src/agilab/pipeline_ai_controls.py",
        "agilab.pipeline_ai_uoaic",
    )

    assert fallback.UOAIC_PROVIDER == "universal-offline-ai-chatbot"
    assert callable(fallback.configure_assistant_engine)


def test_pipeline_ai_controls_import_fallback_raises_when_uoaic_local_spec_is_missing(monkeypatch):
    original_spec = importlib.util.spec_from_file_location

    def _fake_spec(name, location, *args, **kwargs):
        if name == "agilab_pipeline_ai_uoaic_fallback":
            return None
        return original_spec(name, location, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "spec_from_file_location", _fake_spec)

    with pytest.raises(ModuleNotFoundError, match="pipeline_ai_uoaic"):
        _load_module_with_missing(
            "agilab.pipeline_ai_controls_missing_uoaic_spec",
            "src/agilab/pipeline_ai_controls.py",
            "agilab.pipeline_ai_uoaic",
        )


@pytest.mark.parametrize(
    ("case", "expected_error"),
    [
        ("invalid_data", "Invalid Universal Offline data directory"),
        ("invalid_db", "Invalid Universal Offline vector store directory"),
        ("embedding", "Failed to load the embedding model"),
        ("load_pdf", "Unable to load PDF documents"),
        ("no_docs", "No PDF documents found"),
        ("build_db", "Failed to build the Universal Offline vector store"),
        ("load_db", "Failed to load the Universal Offline vector store"),
        ("load_llm", "Failed to load the local Ollama model"),
        ("setup_chain", "Failed to initialise the Universal Offline AI Chatbot chain"),
    ],
)
def test_ensure_uoaic_runtime_reports_specific_failures(monkeypatch, tmp_path, case, expected_error):
    errors: list[str] = []
    fake_st = SimpleNamespace(
        session_state={"env": object()},
        error=lambda message: errors.append(str(message)),
        spinner=lambda *_args, **_kwargs: nullcontext(),
    )
    monkeypatch.setattr(pipeline_ai, "st", fake_st)

    data_dir = tmp_path / "docs"
    db_dir = tmp_path / "vectorstore" / "db"
    data_dir.mkdir(parents=True)

    if case in {"load_db", "load_llm", "setup_chain"}:
        db_dir.mkdir(parents=True)

    def _resolve(raw, _env):
        if case == "invalid_data":
            raise ValueError("bad data")
        if case == "invalid_db" and str(raw) == str(db_dir):
            raise ValueError("bad db")
        return Path(raw)

    monkeypatch.setattr(pipeline_ai, "_resolve_uoaic_path", _resolve)
    fake_st.session_state[pipeline_ai.UOAIC_DATA_STATE_KEY] = str(data_dir)
    fake_st.session_state[pipeline_ai.UOAIC_DB_STATE_KEY] = str(db_dir)

    chunker = SimpleNamespace(
        create_chunks=lambda docs: (_ for _ in ()).throw(ValueError("chunk boom"))
        if case == "build_db"
        else ["chunked"]
    )
    embedding = SimpleNamespace(
        get_embedding_model=lambda: (_ for _ in ()).throw(ValueError("embed boom"))
        if case == "embedding"
        else "embedding-model"
    )
    loader = SimpleNamespace(
        load_pdf_files=lambda path: (_ for _ in ()).throw(ValueError("pdf boom"))
        if case == "load_pdf"
        else ([] if case == "no_docs" else ["doc.pdf"])
    )
    model_loader = SimpleNamespace(
        load_llm=lambda: (_ for _ in ()).throw(ValueError("llm boom"))
        if case == "load_llm"
        else SimpleNamespace()
    )
    prompts = SimpleNamespace(
        CUSTOM_PROMPT_TEMPLATE="template",
        set_custom_prompt=lambda template: f"PROMPT::{template}",
    )
    qa_chain = SimpleNamespace(
        setup_qa_chain=lambda llm, db, prompt: (_ for _ in ()).throw(ValueError("chain boom"))
        if case == "setup_chain"
        else {"llm": llm, "db": db, "prompt": prompt}
    )
    vectorstore = SimpleNamespace(
        build_vector_db=lambda chunks, embedding_model, path: (_ for _ in ()).throw(ValueError("build boom"))
        if case == "build_db"
        else None,
        load_vector_db=lambda path, embedding_model: (_ for _ in ()).throw(ValueError("load boom"))
        if case == "load_db"
        else {"path": path, "embedding_model": embedding_model},
    )
    monkeypatch.setattr(
        pipeline_ai,
        "_load_uoaic_modules",
        lambda: (chunker, embedding, loader, model_loader, prompts, qa_chain, vectorstore),
    )

    with pytest.raises(RuntimeError):
        pipeline_ai._ensure_uoaic_runtime({})

    assert any(expected_error in message for message in errors)


def test_ensure_uoaic_runtime_uses_default_model_label_when_llm_has_no_name(monkeypatch, tmp_path):
    errors: list[str] = []
    fake_st = SimpleNamespace(
        session_state={"env": object()},
        error=lambda message: errors.append(str(message)),
        spinner=lambda *_args, **_kwargs: nullcontext(),
    )
    monkeypatch.setattr(pipeline_ai, "st", fake_st)

    data_dir = tmp_path / "docs"
    db_dir = tmp_path / "vectorstore" / "db"
    data_dir.mkdir(parents=True)
    db_dir.mkdir(parents=True)
    fake_st.session_state[pipeline_ai.UOAIC_DATA_STATE_KEY] = str(data_dir)
    fake_st.session_state[pipeline_ai.UOAIC_DB_STATE_KEY] = str(db_dir)
    monkeypatch.setattr(pipeline_ai, "_resolve_uoaic_path", lambda raw, _env: Path(raw))

    chunker = SimpleNamespace(create_chunks=lambda docs: ["chunked"])
    embedding = SimpleNamespace(get_embedding_model=lambda: "embedding-model")
    loader = SimpleNamespace(load_pdf_files=lambda path: ["doc.pdf"])
    model_loader = SimpleNamespace(load_llm=lambda: SimpleNamespace())
    prompts = SimpleNamespace(
        CUSTOM_PROMPT_TEMPLATE="template",
        set_custom_prompt=lambda template: f"PROMPT::{template}",
    )
    qa_chain = SimpleNamespace(setup_qa_chain=lambda llm, db, prompt: {"db": db, "prompt": prompt})
    vectorstore = SimpleNamespace(
        build_vector_db=lambda chunks, embedding_model, path: None,
        load_vector_db=lambda path, embedding_model: {"path": path},
    )
    monkeypatch.setattr(
        pipeline_ai,
        "_load_uoaic_modules",
        lambda: (chunker, embedding, loader, model_loader, prompts, qa_chain, vectorstore),
    )

    runtime = pipeline_ai._ensure_uoaic_runtime({"UOAIC_MODEL": "fallback-uoaic"})

    assert runtime["model_label"] == "fallback-uoaic"
    assert errors == []


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


def test_configure_assistant_engine_switches_back_to_openai(monkeypatch):
    fake_sidebar = SimpleNamespace(
        selectbox=lambda label, options, index=0, help=None: "OpenAI (online)",
        text_input=lambda *args, **kwargs: "",
    )
    fake_st = SimpleNamespace(
        session_state={
            "lab_llm_provider": "gpt-oss",
            "index_page": "page",
            "page": [0, 0, 0, "stale-model"],
            "gpt_oss_endpoint": "http://127.0.0.1:8000",
        },
        sidebar=fake_sidebar,
    )
    monkeypatch.setattr(pipeline_ai, "st", fake_st)
    monkeypatch.setattr(pipeline_ai, "get_default_openai_model", lambda: "gpt-5.4")
    env = SimpleNamespace(envars={"LAB_LLM_PROVIDER": "gpt-oss"})

    provider = pipeline_ai.configure_assistant_engine(env)

    assert provider == "openai"
    assert env.envars["LAB_LLM_PROVIDER"] == "openai"
    assert env.envars["OPENAI_MODEL"] == "gpt-5.4"
    assert "gpt_oss_endpoint" not in fake_st.session_state
    assert fake_st.session_state["page"][3] == ""


def test_gpt_oss_controls_start_button_persists_backend_checkpoint_and_flags(monkeypatch):
    messages: list[tuple[str, str]] = []

    class FakeSidebar:
        def selectbox(self, label, options, index=0, help=None):
            assert label == "GPT-OSS backend"
            return "transformers"

        def text_input(self, label, value="", help=None):
            if label == "GPT-OSS checkpoint / model":
                return "gpt-oss-demo"
            if label == "GPT-OSS extra flags":
                return "--temperature 0.1"
            return value

        def button(self, label, key=None):
            return key == "gpt_oss_start_btn"

        def warning(self, message):
            messages.append(("warning", str(message)))

        def success(self, message):
            messages.append(("success", str(message)))

        def info(self, message):
            messages.append(("info", str(message)))

    fake_st = SimpleNamespace(
        session_state={
            "lab_llm_provider": "gpt-oss",
            "gpt_oss_endpoint": "http://127.0.0.1:8000",
        },
        sidebar=FakeSidebar(),
    )
    monkeypatch.setattr(pipeline_ai, "st", fake_st)
    monkeypatch.setattr(
        pipeline_ai,
        "activate_gpt_oss",
        lambda env: fake_st.session_state.update(
            {
                "gpt_oss_server_started": True,
                "gpt_oss_backend_active": env.envars["GPT_OSS_BACKEND"],
                "gpt_oss_endpoint": "http://127.0.0.1:8000",
            }
        )
        or True,
    )

    env = SimpleNamespace(envars={})
    pipeline_ai.gpt_oss_controls(env)

    assert env.envars["GPT_OSS_BACKEND"] == "transformers"
    assert env.envars["GPT_OSS_CHECKPOINT"] == "gpt-oss-demo"
    assert env.envars["GPT_OSS_EXTRA_ARGS"] == "--temperature 0.1"
    assert any(kind == "success" and "GPT-OSS server running (transformers)" in message for kind, message in messages)


def test_gpt_oss_controls_start_button_success_without_existing_endpoint(monkeypatch):
    messages: list[tuple[str, str]] = []

    class FakeSidebar:
        def selectbox(self, label, options, index=0, help=None):
            return "transformers"

        def text_input(self, label, value="", help=None):
            if label == "GPT-OSS checkpoint / model":
                return "gpt-oss-demo"
            if label == "GPT-OSS extra flags":
                return ""
            return value

        def button(self, label, key=None):
            return key == "gpt_oss_start_btn"

        def success(self, message):
            messages.append(("success", str(message)))

        def info(self, message):
            messages.append(("info", str(message)))

        def warning(self, message):
            messages.append(("warning", str(message)))

    fake_st = SimpleNamespace(
        session_state={"lab_llm_provider": "gpt-oss"},
        sidebar=FakeSidebar(),
    )
    monkeypatch.setattr(pipeline_ai, "st", fake_st)

    def _activate(_env):
        fake_st.session_state["gpt_oss_endpoint"] = "http://127.0.0.1:9000/v1/responses"
        fake_st.session_state["gpt_oss_backend_active"] = "transformers"
        return True

    monkeypatch.setattr(pipeline_ai, "activate_gpt_oss", _activate)

    env = SimpleNamespace(envars={})
    pipeline_ai.gpt_oss_controls(env)

    assert env.envars["GPT_OSS_BACKEND"] == "transformers"
    assert any(kind == "success" and "http://127.0.0.1:9000/v1/responses" in message for kind, message in messages)


def test_universal_offline_controls_rag_mode_updates_env_and_rebuilds(monkeypatch, tmp_path):
    messages: list[tuple[str, str]] = []

    class FakeExpander:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeSidebar:
        def selectbox(self, label, options, index=0, help=None):
            assert label == "Local assistant mode"
            return "RAG (offline docs)"

        def expander(self, label, expanded=True):
            return FakeExpander()

        def text_input(self, label, value="", help=None):
            mapping = {
                "Ollama endpoint": "http://127.0.0.1:11434/api/generate",
                "Ollama model": "codegemma",
                "Universal Offline data directory": str(tmp_path / "docs"),
                "Universal Offline vector store directory": str(tmp_path / "vectorstore"),
            }
            return mapping.get(label, value)

        def slider(self, label, min_value=None, max_value=None, value=None, step=None, help=None):
            return 0.2 if label == "temperature" else 0.85

        def number_input(self, label, min_value=None, max_value=None, value=None, step=None, help=None):
            if label == "num_ctx (0 = default)":
                return 4096
            if label == "num_predict (0 = default)":
                return 512
            if label == "seed (0 = unset)":
                return 7
            if label == "Max fix attempts":
                return 3
            raise AssertionError(label)

        def checkbox(self, label, value=False, help=None):
            assert label == "Auto-run + auto-fix generated code"
            return True

        def button(self, label, key=None):
            return key == "uoaic_rebuild_btn"

        def caption(self, message):
            messages.append(("caption", str(message)))

        def warning(self, message):
            messages.append(("warning", str(message)))

        def info(self, message):
            messages.append(("info", str(message)))

        def success(self, message):
            messages.append(("success", str(message)))

        def error(self, message):
            messages.append(("error", str(message)))

    fake_st = SimpleNamespace(
        session_state={
            "lab_llm_provider": pipeline_ai.UOAIC_PROVIDER,
            pipeline_ai.UOAIC_MODE_STATE_KEY: pipeline_ai.UOAIC_MODE_OLLAMA,
        },
        sidebar=FakeSidebar(),
        spinner=lambda *_args, **_kwargs: nullcontext(),
        text_input=lambda *args, **kwargs: FakeSidebar().text_input(*args, **kwargs),
        slider=lambda *args, **kwargs: FakeSidebar().slider(*args, **kwargs),
        number_input=lambda *args, **kwargs: FakeSidebar().number_input(*args, **kwargs),
        checkbox=lambda *args, **kwargs: FakeSidebar().checkbox(*args, **kwargs),
    )
    monkeypatch.setattr(pipeline_ai, "st", fake_st)
    monkeypatch.setattr(pipeline_ai, "_default_ollama_model", lambda *_args, **_kwargs: "fallback-model")
    monkeypatch.setattr(pipeline_ai, "_ensure_uoaic_runtime", lambda envars: {"ok": True})
    monkeypatch.setattr(pipeline_ai, "DEFAULT_UOAIC_BASE", tmp_path / "uoaic")

    env = SimpleNamespace(envars={})
    pipeline_ai.universal_offline_controls(env)

    assert env.envars[pipeline_ai.UOAIC_MODE_ENV] == pipeline_ai.UOAIC_MODE_RAG
    assert env.envars[pipeline_ai.UOAIC_OLLAMA_ENDPOINT_ENV] == "http://127.0.0.1:11434"
    assert env.envars[pipeline_ai.UOAIC_MODEL_ENV] == "codegemma"
    assert env.envars[pipeline_ai.UOAIC_TEMPERATURE_ENV] == "0.2"
    assert env.envars[pipeline_ai.UOAIC_TOP_P_ENV] == "0.85"
    assert env.envars[pipeline_ai.UOAIC_NUM_CTX_ENV] == "4096"
    assert env.envars[pipeline_ai.UOAIC_NUM_PREDICT_ENV] == "512"
    assert env.envars[pipeline_ai.UOAIC_SEED_ENV] == "7"
    assert env.envars[pipeline_ai.UOAIC_AUTOFIX_ENV] == "1"
    assert env.envars[pipeline_ai.UOAIC_AUTOFIX_MAX_ENV] == "3"
    assert env.envars[pipeline_ai.UOAIC_DATA_ENV].endswith("/docs")
    assert env.envars[pipeline_ai.UOAIC_DB_ENV].endswith("/vectorstore")
    assert fake_st.session_state[pipeline_ai.UOAIC_REBUILD_FLAG_KEY] is True
    assert any(kind == "success" and "knowledge base updated" in message for kind, message in messages)


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


def test_maybe_autofix_generated_code_short_circuits_for_provider_attempts_and_df_reload(monkeypatch):
    logs: list[str] = []
    push_run_log = lambda *_args: logs.append(_args[1])
    get_run_placeholder = lambda _page: "placeholder"
    fake_st = SimpleNamespace(
        session_state={
            "lab_llm_provider": "openai",
            pipeline_ai.UOAIC_AUTOFIX_STATE_KEY: True,
        }
    )
    monkeypatch.setattr(pipeline_ai, "st", fake_st)
    env = SimpleNamespace(envars={})

    unchanged = pipeline_ai._maybe_autofix_generated_code(
        original_request="q",
        df_path=Path("df.csv"),
        index_page="page",
        env=env,
        merged_code="print('ok')",
        model_label="m",
        detail="detail",
        load_df_cached=lambda _path: pd.DataFrame({"x": [1]}),
        push_run_log=push_run_log,
        get_run_placeholder=get_run_placeholder,
    )
    assert unchanged == ("print('ok')", "m", "detail")

    fake_st.session_state["lab_llm_provider"] = pipeline_ai.UOAIC_PROVIDER
    fake_st.session_state[pipeline_ai.UOAIC_AUTOFIX_MAX_STATE_KEY] = 0
    unchanged = pipeline_ai._maybe_autofix_generated_code(
        original_request="q",
        df_path=Path("df.csv"),
        index_page="page",
        env=env,
        merged_code="print('ok')",
        model_label="m",
        detail="detail",
        load_df_cached=lambda _path: pd.DataFrame({"x": [1]}),
        push_run_log=push_run_log,
        get_run_placeholder=get_run_placeholder,
    )
    assert unchanged == ("print('ok')", "m", "detail")

    fake_st.session_state[pipeline_ai.UOAIC_AUTOFIX_MAX_STATE_KEY] = 2
    fake_st.session_state["loaded_df"] = pd.DataFrame()
    fake_st.session_state["df_file"] = "data.csv"
    seen = {}

    def _load_df(path):
        seen["path"] = path
        return pd.DataFrame()

    unchanged = pipeline_ai._maybe_autofix_generated_code(
        original_request="q",
        df_path=Path("df.csv"),
        index_page="page",
        env=env,
        merged_code="raise ValueError('boom')",
        model_label="m",
        detail="detail",
        load_df_cached=_load_df,
        push_run_log=push_run_log,
        get_run_placeholder=get_run_placeholder,
    )
    assert seen["path"] == Path("data.csv")
    assert unchanged[0] == "raise ValueError('boom')"
    assert any("no dataframe is loaded" in entry for entry in logs)


def test_chat_ollama_local_covers_missing_model_and_generation_failure(monkeypatch):
    errors: list[str] = []
    fake_st = SimpleNamespace(session_state={}, error=lambda message: errors.append(str(message)))
    monkeypatch.setattr(pipeline_ai, "st", fake_st)
    monkeypatch.setattr(pipeline_ai, "_default_ollama_model", lambda *_args, **_kwargs: "")

    with pytest.raises(RuntimeError, match="Missing Ollama model"):
        pipeline_ai.chat_ollama_local("question", [], {})

    monkeypatch.setattr(pipeline_ai, "_default_ollama_model", lambda *_args, **_kwargs: "codegemma")
    monkeypatch.setattr(
        pipeline_ai,
        "_ollama_generate",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("ollama boom")),
    )

    with pytest.raises(RuntimeError, match="ollama boom"):
        pipeline_ai.chat_ollama_local(
            "question",
            [],
            {
                pipeline_ai.UOAIC_MODEL_ENV: "codegemma",
                pipeline_ai.UOAIC_TEMPERATURE_ENV: "bad",
                pipeline_ai.UOAIC_TOP_P_ENV: "bad",
                pipeline_ai.UOAIC_NUM_CTX_ENV: "bad",
                pipeline_ai.UOAIC_NUM_PREDICT_ENV: "bad",
                pipeline_ai.UOAIC_SEED_ENV: "bad",
            },
        )

    assert any("Set an Ollama model name" in message for message in errors)
    assert any("ollama boom" in message for message in errors)


def test_extract_code_covers_fenced_blocks_without_newline_and_non_python_language():
    assert pipeline_ai.extract_code("```print('ok')```") == ("print('ok')", "")
    assert pipeline_ai.extract_code("```sql\nselect 1\n```") == ("sql\nselect 1", "")


def test_ollama_model_helpers_cover_error_empty_names_and_first_available(monkeypatch):
    monkeypatch.setattr(
        pipeline_ai.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert pipeline_ai._ollama_available_models("http://127.0.0.1:11434") == []

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "models": [
                        {"name": ""},
                        {"name": "mistral:7b"},
                        {"name": "mistral:7b"},
                        {"name": "codegemma:latest"},
                    ]
                }
            ).encode("utf-8")

    monkeypatch.setattr(pipeline_ai.urllib.request, "urlopen", lambda *_args, **_kwargs: _Resp())
    pipeline_ai._ollama_available_models.clear()
    assert pipeline_ai._ollama_available_models("http://127.0.0.1:11434") == [
        "mistral:7b",
        "codegemma:latest",
    ]
    monkeypatch.setattr(
        pipeline_ai,
        "_ollama_available_models",
        lambda _endpoint: ["llama3:70b", "codestral:22b"],
    )
    assert pipeline_ai._default_ollama_model("http://127.0.0.1:11434", preferred="missing") == "llama3:70b"


def test_ollama_generate_handles_http_error_without_readable_detail(monkeypatch):
    class _BrokenHttpError(urllib.error.HTTPError):
        def read(self):
            raise OSError("broken body")

    def _raise(*_args, **_kwargs):
        raise _BrokenHttpError("http://ollama/api/generate", 500, "server error", hdrs=None, fp=None)

    monkeypatch.setattr(pipeline_ai.urllib.request, "urlopen", _raise)

    with pytest.raises(RuntimeError, match="Ollama error 500: server error"):
        pipeline_ai._ollama_generate(endpoint="http://ollama", model="demo", prompt="hi")


def test_chat_online_covers_legacy_client_auth_and_unexpected_failures(monkeypatch):
    infos: list[str] = []
    errors: list[str] = []
    fake_st = SimpleNamespace(
        session_state={},
        info=lambda message: infos.append(str(message)),
        error=lambda message: errors.append(str(message)),
    )
    monkeypatch.setattr(pipeline_ai, "st", fake_st)
    monkeypatch.setattr(pipeline_ai, "_load_env_file_map", lambda _path: {"OPENAI_MODEL": "gpt-5.4-mini"})
    monkeypatch.setattr(pipeline_ai, "ensure_cached_api_key", lambda _envars: "sk-DEMO1234567890")
    monkeypatch.setattr(pipeline_ai, "is_placeholder_api_key", lambda _key: False)

    class FakeOpenAIError(Exception):
        def __init__(self, message, status_code=None):
            super().__init__(message)
            self.status_code = status_code

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAIError=FakeOpenAIError))

    class LegacyClient:
        class ChatCompletion:
            @staticmethod
            def create(model, messages):
                assert model == "legacy-model"
                assert messages[-1]["content"] == "question"
                return {"choices": [{"message": {"content": "```python\nprint(3)\n```"}}]}

    monkeypatch.setattr(
        pipeline_ai,
        "make_openai_client_and_model",
        lambda envars, api_key: (LegacyClient(), "legacy-model", False),
    )

    text, model = pipeline_ai.chat_online("question", [{"role": "assistant", "content": ""}], {})
    assert "print(3)" in text
    assert model == "legacy-model"

    monkeypatch.setattr(
        pipeline_ai,
        "make_openai_client_and_model",
        lambda _envars, _api_key: (_ for _ in ()).throw(RuntimeError("init boom")),
    )
    with pytest.raises(RuntimeError, match="init boom"):
        pipeline_ai.chat_online("question", [], {})

    class ForbiddenClient:
        class chat:
            class completions:
                @staticmethod
                def create(model, messages):
                    raise FakeOpenAIError("bad key sk-ABCD1234567890", status_code=401)

    monkeypatch.setattr(
        pipeline_ai,
        "make_openai_client_and_model",
        lambda envars, api_key: (ForbiddenClient(), "secure-model", False),
    )
    with pytest.raises(RuntimeError, match="bad key"):
        pipeline_ai.chat_online("question", [], {})

    class WeirdClient:
        class chat:
            class completions:
                @staticmethod
                def create(model, messages):
                    raise RuntimeError("weird sk-ABCD1234567890")

    monkeypatch.setattr(
        pipeline_ai,
        "make_openai_client_and_model",
        lambda envars, api_key: (WeirdClient(), "secure-model", False),
    )
    with pytest.raises(RuntimeError, match="weird"):
        pipeline_ai.chat_online("question", [], {})

    assert any("Failed to initialise OpenAI/Azure client" in message for message in errors)
    assert any("Authentication/authorization failed" in message for message in errors)
    assert any("Unexpected client error" in message for message in errors)


def test_configure_assistant_engine_and_controls_cover_additional_provider_paths(monkeypatch):
    messages: list[tuple[str, str]] = []

    class OllamaSidebar:
        def selectbox(self, label, options, index=0, help=None):
            assert label == "Assistant engine"
            return "Ollama (local)"

    fake_st = SimpleNamespace(
        session_state={
            "lab_llm_provider": "openai",
            "index_page": "page",
            "page": [0, 0, 0, "stale-model"],
        },
        sidebar=OllamaSidebar(),
    )
    monkeypatch.setattr(pipeline_ai, "st", fake_st)
    env = SimpleNamespace(envars={"OPENAI_MODEL": "gpt-5"})

    provider = pipeline_ai.configure_assistant_engine(env)
    assert provider == pipeline_ai.UOAIC_PROVIDER
    assert "OPENAI_MODEL" not in env.envars

    class GptOssSidebar:
        def selectbox(self, label, options, index=0, help=None):
            if label == "GPT-OSS backend":
                return "custom-backend"
            raise AssertionError(label)

        def text_input(self, label, value="", help=None):
            if label == "GPT-OSS checkpoint / model":
                return ""
            if label == "GPT-OSS extra flags":
                return ""
            return value

        def button(self, label, key=None):
            return False

        def warning(self, message):
            messages.append(("warning", str(message)))

        def success(self, message):
            messages.append(("success", str(message)))

        def info(self, message):
            messages.append(("info", str(message)))

    fake_st = SimpleNamespace(
        session_state={
            "lab_llm_provider": "gpt-oss",
            "gpt_oss_server_started": True,
            "gpt_oss_backend_active": "stub",
            "gpt_oss_checkpoint_active": "old-model",
            "gpt_oss_extra_args_active": "--old",
            "gpt_oss_endpoint": "http://remote-host:8000",
        },
        sidebar=GptOssSidebar(),
    )
    monkeypatch.setattr(pipeline_ai, "st", fake_st)
    env = SimpleNamespace(
        envars={
            "GPT_OSS_BACKEND": "custom-backend",
            "GPT_OSS_CHECKPOINT": "new-model",
            "GPT_OSS_EXTRA_ARGS": "--new",
            "GPT_OSS_ENDPOINT": "http://remote-host:8000",
        }
    )

    pipeline_ai.gpt_oss_controls(env)
    assert any("Restart GPT-OSS server to apply the new backend." in msg for kind, msg in messages if kind == "warning")
    assert any("Restart GPT-OSS server to apply updated checkpoint or flags." in msg for kind, msg in messages if kind == "warning")

    messages.clear()

    class EmptyEndpointSidebar(GptOssSidebar):
        def selectbox(self, label, options, index=0, help=None):
            return "stub"

    fake_st = SimpleNamespace(
        session_state={"lab_llm_provider": "gpt-oss", "gpt_oss_endpoint": "http://remote-host:8000"},
        sidebar=EmptyEndpointSidebar(),
    )
    monkeypatch.setattr(pipeline_ai, "st", fake_st)
    env = SimpleNamespace(envars={"GPT_OSS_ENDPOINT": "http://remote-host:8000"})
    pipeline_ai.gpt_oss_controls(env)
    assert any("Using GPT-OSS endpoint: http://remote-host:8000" in msg for kind, msg in messages if kind == "info")

    messages.clear()

    fake_st = SimpleNamespace(
        session_state={"lab_llm_provider": "gpt-oss"},
        sidebar=EmptyEndpointSidebar(),
    )
    monkeypatch.setattr(pipeline_ai, "st", fake_st)
    env = SimpleNamespace(envars={"GPT_OSS_ENDPOINT": ""})
    pipeline_ai.gpt_oss_controls(env)
    assert any("Configure a GPT-OSS endpoint" in msg for kind, msg in messages if kind == "warning")


def test_universal_offline_controls_cover_code_mode_and_invalid_rag_inputs(monkeypatch, tmp_path):
    messages: list[tuple[str, str]] = []

    class CodeSidebar:
        def selectbox(self, label, options, index=0, help=None):
            return "Code (Ollama)"

        def expander(self, label, expanded=True):
            return nullcontext()

        def text_input(self, label, value="", help=None):
            mapping = {
                "Ollama endpoint": "http://127.0.0.1:11434/",
                "Ollama model": "",
            }
            return mapping.get(label, value)

        def slider(self, *args, **kwargs):
            return kwargs["value"]

        def number_input(self, label, **kwargs):
            return 0 if "Max fix attempts" not in label else 0

        def checkbox(self, label, value=False, help=None):
            return False

        def caption(self, message):
            messages.append(("caption", str(message)))

    fake_st = SimpleNamespace(
        session_state={"lab_llm_provider": pipeline_ai.UOAIC_PROVIDER},
        sidebar=CodeSidebar(),
        text_input=lambda *args, **kwargs: CodeSidebar().text_input(*args, **kwargs),
        slider=lambda *args, **kwargs: CodeSidebar().slider(*args, **kwargs),
        number_input=lambda *args, **kwargs: CodeSidebar().number_input(*args, **kwargs),
        checkbox=lambda *args, **kwargs: CodeSidebar().checkbox(*args, **kwargs),
    )
    monkeypatch.setattr(pipeline_ai, "st", fake_st)
    monkeypatch.setattr(pipeline_ai, "_default_ollama_model", lambda *_args, **_kwargs: "fallback-model")
    env = SimpleNamespace(
        envars={
            pipeline_ai.UOAIC_MODEL_ENV: "old-model",
            pipeline_ai.UOAIC_NUM_CTX_ENV: "64",
            pipeline_ai.UOAIC_NUM_PREDICT_ENV: "64",
            pipeline_ai.UOAIC_SEED_ENV: "5",
        }
    )
    pipeline_ai.universal_offline_controls(env)
    assert pipeline_ai.UOAIC_MODEL_ENV not in env.envars
    assert pipeline_ai.UOAIC_NUM_CTX_ENV not in env.envars
    assert pipeline_ai.UOAIC_NUM_PREDICT_ENV not in env.envars
    assert pipeline_ai.UOAIC_SEED_ENV not in env.envars
    assert any("RAG knowledge-base settings are hidden" in msg for kind, msg in messages if kind == "caption")

    messages.clear()

    class RagSidebar:
        def selectbox(self, label, options, index=0, help=None):
            return "RAG (offline docs)"

        def expander(self, label, expanded=True):
            return nullcontext()

        def text_input(self, label, value="", help=None):
            mapping = {
                "Ollama endpoint": "http://127.0.0.1:11434",
                "Ollama model": "codegemma",
                "Universal Offline data directory": "bad-data",
                "Universal Offline vector store directory": "bad-db",
            }
            return mapping.get(label, value)

        def slider(self, *args, **kwargs):
            return kwargs["value"]

        def number_input(self, label, **kwargs):
            if label == "Max fix attempts":
                return 2
            return kwargs["value"]

        def checkbox(self, label, value=False, help=None):
            return False

        def button(self, label, key=None):
            return key == "uoaic_rebuild_btn"

        def caption(self, message):
            messages.append(("caption", str(message)))

        def warning(self, message):
            messages.append(("warning", str(message)))

        def info(self, message):
            messages.append(("info", str(message)))

        def error(self, message):
            messages.append(("error", str(message)))

        def success(self, message):
            messages.append(("success", str(message)))

    fake_st = SimpleNamespace(
        session_state={"lab_llm_provider": pipeline_ai.UOAIC_PROVIDER},
        sidebar=RagSidebar(),
        spinner=lambda *_args, **_kwargs: nullcontext(),
        text_input=lambda *args, **kwargs: RagSidebar().text_input(*args, **kwargs),
        slider=lambda *args, **kwargs: RagSidebar().slider(*args, **kwargs),
        number_input=lambda *args, **kwargs: RagSidebar().number_input(*args, **kwargs),
        checkbox=lambda *args, **kwargs: RagSidebar().checkbox(*args, **kwargs),
    )
    monkeypatch.setattr(pipeline_ai, "st", fake_st)
    monkeypatch.setattr(pipeline_ai, "_default_ollama_model", lambda *_args, **_kwargs: "fallback-model")
    monkeypatch.setattr(pipeline_ai, "_normalize_user_path", lambda raw: "" if raw.startswith("bad") else raw)
    monkeypatch.setattr(pipeline_ai, "DEFAULT_UOAIC_BASE", tmp_path / "uoaic")
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACEHUB_API_TOKEN", raising=False)
    env = SimpleNamespace(envars={})

    pipeline_ai.universal_offline_controls(env)

    assert any("Provide a valid data directory" in msg for kind, msg in messages if kind == "warning")
    assert any("Provide a valid directory for the Universal Offline vector store." in msg for kind, msg in messages if kind == "warning")
    assert any("Set `HF_TOKEN`" in msg for kind, msg in messages if kind == "info")
    assert any("Set the data directory before rebuilding" in msg for kind, msg in messages if kind == "error")


def test_ask_gpt_and_autofix_cover_empty_and_failed_repair_paths(monkeypatch):
    fake_st = SimpleNamespace(
        session_state={
            "lab_prompt": [],
            "lab_llm_provider": pipeline_ai.UOAIC_PROVIDER,
            pipeline_ai.UOAIC_MODE_STATE_KEY: pipeline_ai.UOAIC_MODE_OLLAMA,
            pipeline_ai.UOAIC_AUTOFIX_MAX_STATE_KEY: "bad",
            "loaded_df": pd.DataFrame({"x": [1]}),
        }
    )
    monkeypatch.setattr(pipeline_ai, "st", fake_st)
    monkeypatch.setattr(pipeline_ai, "chat_ollama_local", lambda *args: ("", "ollama-model"))

    result = pipeline_ai.ask_gpt("q", Path("df.csv"), "page", {})
    assert result[2:] == ["ollama-model", "", ""]

    env = SimpleNamespace(envars={})
    code, model, detail = pipeline_ai._maybe_autofix_generated_code(
        original_request="q",
        df_path=Path("df.csv"),
        index_page="page",
        env=env,
        merged_code="raise ValueError('boom')",
        model_label="model-a",
        detail="detail-a",
        load_df_cached=lambda path: pd.DataFrame({"x": [1]}),
        push_run_log=lambda *_args, **_kwargs: None,
        get_run_placeholder=lambda _page: "placeholder",
    )
    assert (code, model, detail) == ("raise ValueError('boom')", "model-a", "detail-a")

    fake_st.session_state[pipeline_ai.UOAIC_AUTOFIX_STATE_KEY] = False
    env.envars[pipeline_ai.UOAIC_AUTOFIX_ENV] = "1"
    logs: list[str] = []
    monkeypatch.setattr(
        pipeline_ai,
        "ask_gpt",
        lambda *args, **kwargs: [Path("df.csv"), "fix", "m2", "", "still broken"],
    )

    code, model, detail = pipeline_ai._maybe_autofix_generated_code(
        original_request="q",
        df_path=Path("df.csv"),
        index_page="page",
        env=env,
        merged_code="raise ValueError('boom')",
        model_label="model-a",
        detail="detail-a",
        load_df_cached=lambda path: pd.DataFrame({"x": [1]}),
        push_run_log=lambda *_args: logs.append(_args[1]),
        get_run_placeholder=lambda _page: "placeholder",
    )

    assert code == "raise ValueError('boom')"
    assert model == "model-a"
    assert detail == "detail-a"
    assert any("model returned no code" in entry for entry in logs)
    assert any("keeping the last generated code" in entry for entry in logs)


def test_autofix_and_provider_switch_cover_remaining_error_paths(monkeypatch):
    fake_st = SimpleNamespace(
        session_state={
            "lab_prompt": [],
            "lab_llm_provider": pipeline_ai.UOAIC_PROVIDER,
            pipeline_ai.UOAIC_AUTOFIX_STATE_KEY: True,
            pipeline_ai.UOAIC_AUTOFIX_MAX_STATE_KEY: 1,
            pipeline_ai.UOAIC_RUNTIME_KEY: {"status": "cached"},
            "index_page": "page",
            "page": [0, 0, 0, "stale-model"],
            "loaded_df": pd.DataFrame({"x": [1]}),
        },
        sidebar=SimpleNamespace(selectbox=lambda *_args, **_kwargs: "OpenAI (online)"),
    )
    monkeypatch.setattr(pipeline_ai, "st", fake_st)
    monkeypatch.setattr(pipeline_ai, "get_default_openai_model", lambda: "gpt-5.4")
    monkeypatch.setattr(
        pipeline_ai,
        "ask_gpt",
        lambda *args, **kwargs: [Path("df.csv"), "fix", "m2", "raise RuntimeError('still broken')", "detail"],
    )

    logs: list[str] = []
    code, model, detail = pipeline_ai._maybe_autofix_generated_code(
        original_request="q",
        df_path=Path("df.csv"),
        index_page="page",
        env=SimpleNamespace(envars={}),
        merged_code="raise ValueError('boom')",
        model_label="model-a",
        detail="detail-a",
        load_df_cached=lambda path: pd.DataFrame({"x": [1]}),
        push_run_log=lambda *_args: logs.append(_args[1]),
        get_run_placeholder=lambda _page: "placeholder",
    )

    assert code == "# detail\nraise RuntimeError('still broken')"
    assert model == "m2"
    assert detail == "detail"
    assert any("Auto-fix attempt 1 failed" in entry for entry in logs)
    assert any("keeping the last generated code" in entry for entry in logs)

    env = SimpleNamespace(envars={"LAB_LLM_PROVIDER": pipeline_ai.UOAIC_PROVIDER})
    provider = pipeline_ai.configure_assistant_engine(env)
    assert provider == "openai"
    assert pipeline_ai.UOAIC_RUNTIME_KEY not in fake_st.session_state
    assert fake_st.session_state["page"][3] == ""
    assert env.envars["OPENAI_MODEL"] == "gpt-5.4"


def test_universal_offline_controls_covers_invalid_defaults_and_blank_paths(monkeypatch, tmp_path):
    messages: list[tuple[str, str]] = []

    class RagSidebar:
        def selectbox(self, label, options, index=0, help=None):
            return "RAG (offline docs)"

        def expander(self, label, expanded=True):
            return nullcontext()

        def text_input(self, label, value="", help=None):
            mapping = {
                "Ollama endpoint": "http://127.0.0.1:11434",
                "Ollama model": "codegemma",
                "Universal Offline data directory": "",
                "Universal Offline vector store directory": "",
            }
            return mapping.get(label, value)

        def slider(self, *args, **kwargs):
            return kwargs["value"]

        def number_input(self, label, **kwargs):
            if label == "Max fix attempts":
                return kwargs["value"]
            return kwargs["value"]

        def checkbox(self, label, value=False, help=None):
            return False

        def button(self, label, key=None):
            return False

        def caption(self, message):
            messages.append(("caption", str(message)))

        def warning(self, message):
            messages.append(("warning", str(message)))

        def info(self, message):
            messages.append(("info", str(message)))

        def success(self, message):
            messages.append(("success", str(message)))

    fake_st = SimpleNamespace(
        session_state={"lab_llm_provider": pipeline_ai.UOAIC_PROVIDER},
        sidebar=RagSidebar(),
        spinner=lambda *_args, **_kwargs: nullcontext(),
        text_input=lambda *args, **kwargs: RagSidebar().text_input(*args, **kwargs),
        slider=lambda *args, **kwargs: RagSidebar().slider(*args, **kwargs),
        number_input=lambda *args, **kwargs: RagSidebar().number_input(*args, **kwargs),
        checkbox=lambda *args, **kwargs: RagSidebar().checkbox(*args, **kwargs),
    )
    monkeypatch.setattr(pipeline_ai, "st", fake_st)
    monkeypatch.setattr(pipeline_ai, "_default_ollama_model", lambda *_args, **_kwargs: "fallback-model")
    monkeypatch.setattr(pipeline_ai, "_normalize_user_path", lambda raw: "")
    monkeypatch.setattr(pipeline_ai, "DEFAULT_UOAIC_BASE", tmp_path / "uoaic")

    original_mkdir = Path.mkdir

    def _patched_mkdir(self, *args, **kwargs):
        if self in {
            tmp_path / "uoaic" / "data",
            tmp_path / "uoaic" / "vectorstore",
        }:
            raise OSError("no access")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", _patched_mkdir, raising=False)

    env = SimpleNamespace(
        envars={
            pipeline_ai.UOAIC_AUTOFIX_MAX_ENV: "bad",
        }
    )
    pipeline_ai.universal_offline_controls(env)

    assert fake_st.session_state[pipeline_ai.UOAIC_AUTOFIX_MAX_STATE_KEY] == 2
    assert pipeline_ai.UOAIC_DATA_STATE_KEY not in fake_st.session_state
    assert pipeline_ai.UOAIC_DB_STATE_KEY not in fake_st.session_state
    assert pipeline_ai.UOAIC_DATA_ENV not in env.envars
    assert pipeline_ai.UOAIC_DB_ENV not in env.envars


def test_universal_offline_controls_blank_inputs_clear_existing_saved_paths(monkeypatch):
    class RagSidebar:
        def selectbox(self, label, options, index=0, help=None):
            return "RAG (offline docs)"

        def expander(self, label, expanded=True):
            return nullcontext()

        def text_input(self, label, value="", help=None):
            mapping = {
                "Ollama endpoint": "http://127.0.0.1:11434",
                "Ollama model": "codegemma",
                "Universal Offline data directory": " ",
                "Universal Offline vector store directory": " ",
            }
            return mapping.get(label, value)

        def slider(self, *args, **kwargs):
            return kwargs["value"]

        def number_input(self, label, **kwargs):
            return kwargs["value"]

        def checkbox(self, label, value=False, help=None):
            return False

        def button(self, label, key=None):
            return False

        def caption(self, _message):
            return None

        def warning(self, _message):
            return None

        def info(self, _message):
            return None

        def success(self, _message):
            return None

    fake_st = SimpleNamespace(
        session_state={
            "lab_llm_provider": pipeline_ai.UOAIC_PROVIDER,
            pipeline_ai.UOAIC_DATA_STATE_KEY: "/tmp/old-data",
            pipeline_ai.UOAIC_DB_STATE_KEY: "/tmp/old-db",
            pipeline_ai.UOAIC_RUNTIME_KEY: "stale-runtime",
        },
        sidebar=RagSidebar(),
        spinner=lambda *_args, **_kwargs: nullcontext(),
        text_input=lambda *args, **kwargs: RagSidebar().text_input(*args, **kwargs),
        slider=lambda *args, **kwargs: RagSidebar().slider(*args, **kwargs),
        number_input=lambda *args, **kwargs: RagSidebar().number_input(*args, **kwargs),
        checkbox=lambda *args, **kwargs: RagSidebar().checkbox(*args, **kwargs),
    )
    monkeypatch.setattr(pipeline_ai, "st", fake_st)
    monkeypatch.setattr(pipeline_ai, "_default_ollama_model", lambda *_args, **_kwargs: "fallback-model")

    env = SimpleNamespace(
        envars={
            pipeline_ai.UOAIC_DATA_ENV: "/tmp/old-data",
            pipeline_ai.UOAIC_DB_ENV: "/tmp/old-db",
        }
    )
    pipeline_ai.universal_offline_controls(env)

    normalized_data = pipeline_ai._normalize_user_path("/tmp/old-data")
    normalized_db = pipeline_ai._normalize_user_path("/tmp/old-db")
    assert fake_st.session_state[pipeline_ai.UOAIC_DATA_STATE_KEY] == normalized_data
    assert fake_st.session_state[pipeline_ai.UOAIC_DB_STATE_KEY] == normalized_db
    assert env.envars[pipeline_ai.UOAIC_DATA_ENV] == normalized_data
    assert env.envars[pipeline_ai.UOAIC_DB_ENV] == normalized_db
    assert pipeline_ai.UOAIC_RUNTIME_KEY not in fake_st.session_state


def test_pipeline_ai_helper_edges_cover_blank_roles_and_cwd_fallback(monkeypatch, tmp_path):
    assert pipeline_ai.extract_code("   ") == ("", "")
    assert pipeline_ai._normalize_gpt_oss_endpoint("http://127.0.0.1:8000/") == "http://127.0.0.1:8000/v1/responses"
    assert (
        pipeline_ai._normalize_gpt_oss_endpoint("http://127.0.0.1:8000/v1/responses")
        == "http://127.0.0.1:8000/v1/responses"
    )

    instructions, history = pipeline_ai._prompt_to_gpt_oss_messages(
        [
            {"role": "system", "content": "   "},
            {"role": "critic", "content": ""},
        ],
        "question",
    )
    assert instructions is None
    assert history[-1]["content"] == [{"type": "input_text", "text": "question"}]

    response = SimpleNamespace(
        output=[
            SimpleNamespace(type="message", content=[SimpleNamespace(type="text", text=SimpleNamespace(value="alpha"))]),
            SimpleNamespace(type="tool", text="beta"),
        ]
    )
    assert pipeline_ai._response_to_text(response) == "alpha\nbeta"

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pipeline_ai, "_pipeline_export_root", lambda _env: (_ for _ in ()).throw(RuntimeError("boom")))
    resolved = pipeline_ai._resolve_uoaic_path("docs/manual.pdf", env=object())
    assert resolved == (tmp_path / "docs" / "manual.pdf").resolve()


def test_chat_offline_reports_missing_requests_dependency(monkeypatch):
    errors: list[str] = []
    fake_st = SimpleNamespace(session_state={}, error=lambda message: errors.append(str(message)))
    monkeypatch.setattr(pipeline_ai, "st", fake_st)
    original_import = __import__

    def _patched_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "requests":
            raise ImportError("missing requests")
        return original_import(name, globals, locals, fromlist, level)

    with patch("builtins.__import__", _patched_import):
        with pytest.raises(RuntimeError):
            pipeline_ai.chat_offline("question", [], {"GPT_OSS_MODEL": "gpt-oss-mini"})

    assert any("`requests` is required" in message for message in errors)


def test_universal_offline_controls_rebuild_requires_data_and_handles_jump(monkeypatch, tmp_path):
    class RebuildSidebar:
        def expander(self, _label, expanded=False):
            return nullcontext()

        def radio(self, _label, options, index=0, key=None, help=None):
            return "RAG (offline docs)"

        def selectbox(self, _label, options, index=0, key=None, help=None):
            return "RAG (offline docs)"

        def text_input(self, label, value="", help=None):
            if label == "Universal Offline data directory":
                return "bad-data"
            if label == "Universal Offline vector store directory":
                return "bad-db"
            return value

        def checkbox(self, label, value=False, help=None):
            return value

        def slider(self, label, min_value, max_value, value, step=1, help=None):
            return value

        def number_input(self, label, min_value=None, max_value=None, value=0, step=1, help=None):
            return value

        def button(self, label, key=None):
            return True

        def caption(self, _message):
            return None

        def warning(self, _message):
            return None

        def info(self, _message):
            return None

        def success(self, _message):
            return None

        def error(self, _message):
            return None

    sidebar_errors: list[str] = []
    fake_st = SimpleNamespace(
        session_state={"lab_llm_provider": pipeline_ai.UOAIC_PROVIDER},
        sidebar=RebuildSidebar(),
        spinner=lambda *_args, **_kwargs: nullcontext(),
        error=lambda _message: None,
        text_input=lambda *args, **kwargs: RebuildSidebar().text_input(*args, **kwargs),
        slider=lambda *args, **kwargs: RebuildSidebar().slider(*args, **kwargs),
        number_input=lambda *args, **kwargs: RebuildSidebar().number_input(*args, **kwargs),
        checkbox=lambda *args, **kwargs: RebuildSidebar().checkbox(*args, **kwargs),
    )
    monkeypatch.setattr(fake_st.sidebar, "error", lambda message: sidebar_errors.append(str(message)))
    monkeypatch.setattr(pipeline_ai, "st", fake_st)
    monkeypatch.setattr(pipeline_ai, "_default_ollama_model", lambda *_args, **_kwargs: "fallback-model")
    monkeypatch.setattr(pipeline_ai, "_normalize_user_path", lambda raw: "" if str(raw).startswith("bad") else str(raw))

    env = SimpleNamespace(envars={})
    pipeline_ai.universal_offline_controls(env)
    assert any("Set the data directory before rebuilding" in message for message in sidebar_errors)

    fake_st.session_state[pipeline_ai.UOAIC_DATA_STATE_KEY] = str(tmp_path / "docs")
    monkeypatch.setattr(pipeline_ai, "_ensure_uoaic_runtime", lambda _envars: (_ for _ in ()).throw(pipeline_ai.JumpToMain("boom")))
    pipeline_ai.universal_offline_controls(env)
    assert pipeline_ai.UOAIC_REBUILD_FLAG_KEY in fake_st.session_state


def test_universal_offline_controls_clears_paths_when_defaults_normalize_to_blank(monkeypatch):
    messages: list[tuple[str, str]] = []

    class BlankPathSidebar:
        def selectbox(self, _label, _options, index=0, help=None):
            return "RAG (offline docs)"

        def expander(self, _label, expanded=True):
            return nullcontext()

        def text_input(self, label, value="", help=None):
            mapping = {
                "Ollama endpoint": "http://127.0.0.1:11434",
                "Ollama model": "codegemma",
                "Universal Offline data directory": " ",
                "Universal Offline vector store directory": " ",
            }
            return mapping.get(label, value)

        def slider(self, *args, **kwargs):
            return kwargs["value"]

        def number_input(self, label, min_value=None, max_value=None, value=0, step=1, help=None):
            return value

        def checkbox(self, label, value=False, help=None):
            return False

        def button(self, label, key=None):
            return False

        def caption(self, message):
            messages.append(("caption", str(message)))

        def warning(self, message):
            messages.append(("warning", str(message)))

        def info(self, message):
            messages.append(("info", str(message)))

        def success(self, message):
            messages.append(("success", str(message)))

        def error(self, message):
            messages.append(("error", str(message)))

    sidebar = BlankPathSidebar()
    fake_st = SimpleNamespace(
        session_state={
            "lab_llm_provider": pipeline_ai.UOAIC_PROVIDER,
            pipeline_ai.UOAIC_RUNTIME_KEY: "stale-runtime",
        },
        sidebar=sidebar,
        spinner=lambda *_args, **_kwargs: nullcontext(),
        text_input=lambda *args, **kwargs: sidebar.text_input(*args, **kwargs),
        slider=lambda *args, **kwargs: sidebar.slider(*args, **kwargs),
        number_input=lambda *args, **kwargs: sidebar.number_input(*args, **kwargs),
        checkbox=lambda *args, **kwargs: sidebar.checkbox(*args, **kwargs),
    )
    monkeypatch.setattr(pipeline_ai, "st", fake_st)
    monkeypatch.setattr(pipeline_ai, "_default_ollama_model", lambda *_args, **_kwargs: "fallback-model")
    monkeypatch.setattr(
        pipeline_ai,
        "normalize_path",
        lambda path: "" if "mistral_offline" in str(path) else str(path),
    )

    env = SimpleNamespace(envars={})
    pipeline_ai.universal_offline_controls(env)

    assert pipeline_ai.UOAIC_DATA_STATE_KEY not in fake_st.session_state
    assert pipeline_ai.UOAIC_DB_STATE_KEY not in fake_st.session_state
    assert pipeline_ai.UOAIC_DATA_ENV not in env.envars
    assert pipeline_ai.UOAIC_DB_ENV not in env.envars


def test_universal_offline_controls_warns_when_normalized_paths_are_invalid(monkeypatch):
    messages: list[tuple[str, str]] = []

    class InvalidPathSidebar:
        def selectbox(self, _label, _options, index=0, help=None):
            return "RAG (offline docs)"

        def expander(self, _label, expanded=True):
            return nullcontext()

        def text_input(self, label, value="", help=None):
            mapping = {
                "Ollama endpoint": "http://127.0.0.1:11434",
                "Ollama model": "codegemma",
                "Universal Offline data directory": "invalid-data",
                "Universal Offline vector store directory": "invalid-db",
            }
            return mapping.get(label, value)

        def slider(self, *args, **kwargs):
            return kwargs["value"]

        def number_input(self, label, min_value=None, max_value=None, value=0, step=1, help=None):
            return value

        def checkbox(self, label, value=False, help=None):
            return False

        def button(self, label, key=None):
            return False

        def caption(self, message):
            messages.append(("caption", str(message)))

        def warning(self, message):
            messages.append(("warning", str(message)))

        def info(self, message):
            messages.append(("info", str(message)))

        def success(self, message):
            messages.append(("success", str(message)))

        def error(self, message):
            messages.append(("error", str(message)))

    sidebar = InvalidPathSidebar()
    fake_st = SimpleNamespace(
        session_state={"lab_llm_provider": pipeline_ai.UOAIC_PROVIDER},
        sidebar=sidebar,
        spinner=lambda *_args, **_kwargs: nullcontext(),
        text_input=lambda *args, **kwargs: sidebar.text_input(*args, **kwargs),
        slider=lambda *args, **kwargs: sidebar.slider(*args, **kwargs),
        number_input=lambda *args, **kwargs: sidebar.number_input(*args, **kwargs),
        checkbox=lambda *args, **kwargs: sidebar.checkbox(*args, **kwargs),
    )
    monkeypatch.setattr(pipeline_ai, "st", fake_st)
    monkeypatch.setattr(pipeline_ai, "_default_ollama_model", lambda *_args, **_kwargs: "fallback-model")
    monkeypatch.setattr(
        pipeline_ai,
        "_normalize_user_path",
        lambda raw: "" if str(raw).startswith("invalid-") else str(raw),
    )

    env = SimpleNamespace(envars={})
    pipeline_ai.universal_offline_controls(env)

    assert any("Provide a valid data directory" in message for kind, message in messages if kind == "warning")
    assert any("Provide a valid directory for the Universal Offline vector store." in message for kind, message in messages if kind == "warning")


def test_load_uoaic_modules_record_fallback_handles_missing_spec(monkeypatch, tmp_path):
    errors: list[str] = []
    fake_st = SimpleNamespace(session_state={}, error=lambda message: errors.append(str(message)))
    monkeypatch.setattr(pipeline_ai, "st", fake_st)

    wheel_root = tmp_path / "wheel"
    wheel_root.mkdir()
    chunker_file = wheel_root / "src" / "chunker.py"
    chunker_file.parent.mkdir(parents=True)
    chunker_file.write_text("IDENT = 'chunker'\n", encoding="utf-8")

    class FakeDist:
        files = []

        @staticmethod
        def locate_file(path):
            return wheel_root / str(path)

        @staticmethod
        def read_text(_name):
            return "src/chunker.py,,\n"

    monkeypatch.setattr(pipeline_ai.importlib_metadata, "distribution", lambda *_args, **_kwargs: FakeDist())
    monkeypatch.setattr(
        pipeline_ai.importlib,
        "import_module",
        lambda name: (_ for _ in ()).throw(ImportError("fallback", name=name)),
    )
    monkeypatch.setattr(pipeline_ai.importlib.util, "spec_from_file_location", lambda *_args, **_kwargs: None)

    with pytest.raises(RuntimeError):
        pipeline_ai._load_uoaic_modules()

    assert any("Failed to load Universal Offline AI Chatbot module files" in message for message in errors)


def test_load_uoaic_modules_record_fallback_exec_failure_uses_record_path(monkeypatch, tmp_path):
    errors: list[str] = []
    fake_st = SimpleNamespace(session_state={}, error=lambda message: errors.append(str(message)))
    monkeypatch.setattr(pipeline_ai, "st", fake_st)

    wheel_root = tmp_path / "wheel"
    wheel_root.mkdir()
    chunker_file = wheel_root / "src" / "chunker.py"
    chunker_file.parent.mkdir(parents=True)
    chunker_file.write_text("IDENT = 'chunker'\n", encoding="utf-8")

    class FakeDist:
        files = []

        @staticmethod
        def locate_file(path):
            return wheel_root / str(path)

        @staticmethod
        def read_text(_name):
            return "src/chunker.py\n"

    monkeypatch.setattr(pipeline_ai.importlib_metadata, "distribution", lambda *_args, **_kwargs: FakeDist())
    monkeypatch.setattr(
        pipeline_ai.importlib,
        "import_module",
        lambda name: (_ for _ in ()).throw(ImportError("fallback", name=name)),
    )

    class _Loader:
        @staticmethod
        def exec_module(_module):
            raise RuntimeError("boom")

    monkeypatch.setattr(
        pipeline_ai.importlib.util,
        "spec_from_file_location",
        lambda *_args, **_kwargs: SimpleNamespace(loader=_Loader()),
    )

    with pytest.raises(RuntimeError):
        pipeline_ai._load_uoaic_modules()

    assert any("Failed to load Universal Offline AI Chatbot module files" in message for message in errors)


def test_prompt_to_plaintext_and_uoaic_messages_cover_blank_and_system_only_inputs():
    text = pipeline_ai._prompt_to_plaintext(
        [
            {"role": "", "content": "fallback"},
            {"role": "assistant", "content": "   "},
        ],
        "follow up",
    )
    assert text == "Assistant: fallback\nUser: follow up"

    instructions, history = pipeline_ai._prompt_to_gpt_oss_messages(
        [{"role": "system", "content": ["line 1", "line 2"]}],
        "next",
    )
    assert instructions == "line 1\nline 2"
    assert history == [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "next"}],
        }
    ]


def test_prompt_to_plaintext_uses_user_prefix():
    text = pipeline_ai._prompt_to_plaintext(
        [{"role": "user", "content": "hello"}],
        "next",
    )

    assert text == "User: hello\nUser: next"


def test_synthesize_stub_response_empty_question_and_redact_sensitive_empty_text():
    message = pipeline_ai._synthesize_stub_response("")

    assert "stub backend only confirms connectivity" in message
    assert pipeline_ai._redact_sensitive("") == ""


def test_normalize_user_path_and_resolve_uoaic_path_cover_blank_and_export_root_fallback(monkeypatch, tmp_path):
    assert pipeline_ai._normalize_user_path("") == ""

    monkeypatch.setattr(pipeline_ai, "_pipeline_export_root", lambda _env: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.chdir(tmp_path)

    resolved = pipeline_ai._resolve_uoaic_path("docs/manual.pdf", env=object())

    assert resolved == (tmp_path / "docs" / "manual.pdf").resolve()


def test_chat_universal_offline_formats_sources_without_answer(monkeypatch):
    fake_st = SimpleNamespace(session_state={}, error=lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline_ai, "st", fake_st)

    class Doc:
        def __init__(self, metadata):
            self.metadata = metadata

    class Chain:
        def invoke(self, payload):
            return {"result": "", "source_documents": [Doc({"source": "doc.pdf", "page_number": 4})]}

    monkeypatch.setattr(
        pipeline_ai,
        "_ensure_uoaic_runtime",
        lambda _envars: {"chain": Chain(), "model_label": "uoaic"},
    )

    text, model = pipeline_ai.chat_universal_offline("question", [], {})

    assert model == "uoaic"
    assert text == "Sources:\n- doc.pdf (page 4)"


def test_chat_online_covers_generic_openai_error_branch(monkeypatch):
    errors: list[str] = []
    fake_st = SimpleNamespace(
        session_state={},
        info=lambda *_args, **_kwargs: None,
        error=lambda message: errors.append(str(message)),
    )
    monkeypatch.setattr(pipeline_ai, "st", fake_st)
    monkeypatch.setattr(pipeline_ai, "_load_env_file_map", lambda _path: {})
    monkeypatch.setattr(pipeline_ai, "ensure_cached_api_key", lambda _envars: "sk-DEMO1234567890")
    monkeypatch.setattr(pipeline_ai, "is_placeholder_api_key", lambda _key: False)

    class FakeOpenAIError(Exception):
        def __init__(self, message, status_code=None):
            super().__init__(message)
            self.status_code = status_code

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAIError=FakeOpenAIError))

    class GenericFailClient:
        class chat:
            class completions:
                @staticmethod
                def create(model, messages):
                    raise FakeOpenAIError("server exploded", status_code=500)

    monkeypatch.setattr(
        pipeline_ai,
        "make_openai_client_and_model",
        lambda _envars, _api_key: (GenericFailClient(), "gpt-5.4", False),
    )

    with pytest.raises(RuntimeError, match="server exploded"):
        pipeline_ai.chat_online("question", [{"role": "assistant", "content": "history"}], {})

    assert any("OpenAI/Azure error: server exploded" in message for message in errors)


def test_chat_offline_uses_instructions_and_response_object(monkeypatch):
    captured: dict[str, object] = {}
    fake_st = SimpleNamespace(session_state={"gpt_oss_backend_active": "transformers"}, error=lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline_ai, "st", fake_st)

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"output": [{"type": "message", "content": [{"text": "ignored"}]}]}

    fake_requests = ModuleType("requests")
    fake_requests.exceptions = SimpleNamespace(RequestException=RuntimeError)
    fake_requests.post = lambda endpoint, json=None, timeout=None: captured.update(  # type: ignore[attr-defined]
        {"endpoint": endpoint, "payload": json, "timeout": timeout}
    ) or _FakeResponse()

    fake_types = ModuleType("gpt_oss.responses_api.types")

    class ResponseObject:
        @staticmethod
        def model_validate(data):
            return SimpleNamespace(output_text="```python\nprint(7)\n```")

    fake_types.ResponseObject = ResponseObject
    monkeypatch.setitem(sys.modules, "requests", fake_requests)
    monkeypatch.setitem(sys.modules, "gpt_oss", ModuleType("gpt_oss"))
    monkeypatch.setitem(sys.modules, "gpt_oss.responses_api", ModuleType("gpt_oss.responses_api"))
    monkeypatch.setitem(sys.modules, "gpt_oss.responses_api.types", fake_types)

    text, model = pipeline_ai.chat_offline(
        "question",
        [{"role": "system", "content": "rules"}],
        {"GPT_OSS_MODEL": "demo-model", "GPT_OSS_BACKEND": "transformers"},
    )

    assert "print(7)" in text
    assert model == "demo-model"
    assert captured["payload"]["instructions"] == "rules"


def test_normalize_user_path_uses_absolute_fallback_when_resolve_fails(monkeypatch, tmp_path):
    target = tmp_path / "missing.csv"
    original_resolve = Path.resolve

    def _patched_resolve(self, *args, **kwargs):
        if self == target:
            raise RuntimeError("resolve boom")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", _patched_resolve, raising=False)

    normalized = pipeline_ai._normalize_user_path(str(target))

    assert normalized.endswith("missing.csv")


def test_chat_universal_offline_accepts_plain_string_response(monkeypatch):
    fake_st = SimpleNamespace(session_state={}, error=lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline_ai, "st", fake_st)
    monkeypatch.setattr(
        pipeline_ai,
        "_ensure_uoaic_runtime",
        lambda _envars: {"chain": SimpleNamespace(invoke=lambda payload: "plain answer"), "model_label": "uoaic"},
    )

    text, model = pipeline_ai.chat_universal_offline("question", [], {})

    assert text == "plain answer"
    assert model == "uoaic"


def test_gpt_oss_controls_returns_early_when_provider_is_not_selected(monkeypatch):
    fake_st = SimpleNamespace(session_state={"lab_llm_provider": "openai"}, sidebar=SimpleNamespace())
    monkeypatch.setattr(pipeline_ai, "st", fake_st)

    pipeline_ai.gpt_oss_controls(SimpleNamespace(envars={}))

    assert fake_st.session_state["lab_llm_provider"] == "openai"


def test_universal_offline_controls_returns_early_when_provider_is_not_selected(monkeypatch):
    fake_st = SimpleNamespace(session_state={"lab_llm_provider": "openai"}, sidebar=SimpleNamespace())
    monkeypatch.setattr(pipeline_ai, "st", fake_st)

    pipeline_ai.universal_offline_controls(SimpleNamespace(envars={}))

    assert fake_st.session_state["lab_llm_provider"] == "openai"


def test_gpt_oss_controls_uses_env_and_os_defaults_when_session_state_is_blank(monkeypatch):
    seen: dict[str, object] = {}

    class Sidebar:
        def selectbox(self, label, options, index=0, help=None):
            seen["backend_options"] = list(options)
            seen["backend_index"] = index
            return options[index]

        def text_input(self, label, value="", help=None):
            seen.setdefault("text_inputs", {})[label] = value
            return value

        def button(self, label, key=None):
            return False

        def info(self, message):
            seen["info"] = str(message)

        def warning(self, message):
            seen["warning"] = str(message)

        def success(self, message):
            seen["success"] = str(message)

    fake_st = SimpleNamespace(session_state={"lab_llm_provider": "gpt-oss"}, sidebar=Sidebar())
    monkeypatch.setattr(pipeline_ai, "st", fake_st)
    monkeypatch.delenv("GPT_OSS_ENDPOINT", raising=False)
    monkeypatch.delenv("GPT_OSS_BACKEND", raising=False)
    env = SimpleNamespace(envars={})

    pipeline_ai.gpt_oss_controls(env)

    assert seen["text_inputs"]["GPT-OSS checkpoint / model"] == ""
    assert seen["backend_options"][0] == "stub"


def test_ensure_uoaic_runtime_defaults_db_path_from_data_dir(monkeypatch, tmp_path):
    fake_st = SimpleNamespace(
        session_state={"env": object(), pipeline_ai.UOAIC_DATA_STATE_KEY: str(tmp_path / "docs")},
        error=lambda *_args, **_kwargs: None,
        spinner=lambda *_args, **_kwargs: nullcontext(),
    )
    monkeypatch.setattr(pipeline_ai, "st", fake_st)

    data_dir = tmp_path / "docs"
    data_dir.mkdir(parents=True)

    seen: dict[str, str] = {}

    def _resolve(raw, _env):
        path = Path(raw)
        seen.setdefault("resolved", []).append(str(path))
        return path

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
        build_vector_db=lambda chunks, embedding_model, path: seen.setdefault("built", path),
        load_vector_db=lambda path, embedding_model: {"path": path, "embedding_model": embedding_model},
    )

    monkeypatch.setattr(pipeline_ai, "_resolve_uoaic_path", _resolve)
    monkeypatch.setattr(
        pipeline_ai,
        "_load_uoaic_modules",
        lambda: (chunker, embedding, loader, model_loader, prompts, qa_chain, vectorstore),
    )

    runtime = pipeline_ai._ensure_uoaic_runtime({})

    expected_db = str(data_dir / pipeline_ai.UOAIC_DEFAULT_DB_DIRNAME)
    assert fake_st.session_state[pipeline_ai.UOAIC_DB_STATE_KEY] == expected_db
    assert runtime["vector_store"]["path"] == expected_db
    assert expected_db in seen["resolved"]
