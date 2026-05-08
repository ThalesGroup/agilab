from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

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


pipeline_ai_support = _load_module("agilab.pipeline_ai_support_test", "src/agilab/pipeline_ai_support.py")


def test_extract_code_splits_detail_and_python_block():
    message = "Use this.\n```python\nprint('ok')\n```\nDone."

    code, detail = pipeline_ai_support.extract_code(message)

    assert code == "print('ok')"
    assert detail == "Use this.\n\nDone."


def test_extract_code_handles_plain_python_empty_and_non_python_text():
    assert pipeline_ai_support.extract_code("value = 1\nprint(value)") == ("value = 1\nprint(value)", "")
    assert pipeline_ai_support.extract_code("") == ("", "")
    assert pipeline_ai_support.extract_code("not valid python!") == ("", "not valid python!")


def test_normalize_gpt_oss_endpoint_appends_responses_path():
    assert pipeline_ai_support.normalize_gpt_oss_endpoint("") == pipeline_ai_support.DEFAULT_GPT_OSS_ENDPOINT
    assert (
        pipeline_ai_support.normalize_gpt_oss_endpoint("http://127.0.0.1:8000")
        == "http://127.0.0.1:8000/v1/responses"
    )
    assert (
        pipeline_ai_support.normalize_gpt_oss_endpoint("http://127.0.0.1:8000/v1")
        == "http://127.0.0.1:8000/v1/responses"
    )


def test_normalize_ollama_endpoint_strips_generate_path_and_uses_env(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://ollama.local:11434/")

    assert pipeline_ai_support.normalize_ollama_endpoint("") == "http://ollama.local:11434"
    assert (
        pipeline_ai_support.normalize_ollama_endpoint("http://127.0.0.1:11434/api/generate")
        == "http://127.0.0.1:11434"
    )


class _FakeURLOpenResponse:
    def __init__(self, payload: str):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def read(self):
        return self.payload.encode("utf-8")


def test_ollama_available_models_parses_models_and_removes_duplicates(monkeypatch):
    models_payload = {
        "models": [
            {"name": "qwen2.5-coder:latest"},
            {"name": "qwen2.5-coder:latest"},
            {"name": "llama"},
        ]
    }

    monkeypatch.setattr(
        pipeline_ai_support.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _FakeURLOpenResponse(json.dumps(models_payload)),
    )

    models = pipeline_ai_support._ollama_available_models("http://127.0.0.1:11434")

    assert models == ["qwen2.5-coder:latest", "llama"]


def test_ollama_readiness_classifies_ready_missing_and_unreachable_models():
    ready = pipeline_ai_support.ollama_readiness(
        "http://127.0.0.1:11434/api/generate",
        "gpt-oss:20b",
        model_fetcher=lambda _endpoint: ["gpt-oss:20b", "qwen2.5-coder:latest"],
    )
    assert ready.status == "ready"
    assert ready.endpoint == "http://127.0.0.1:11434"
    assert ready.is_ready is True

    missing = pipeline_ai_support.ollama_readiness(
        "http://127.0.0.1:11434",
        "qwen3-coder:30b-a3b-q4_K_M",
        model_fetcher=lambda _endpoint: ["qwen2.5-coder:latest"],
    )
    assert missing.status == "model_missing"
    assert "ollama pull qwen3-coder:30b-a3b-q4_K_M" in missing.action

    def _raise(_endpoint: str):
        raise RuntimeError("Ollama is not reachable at http://127.0.0.1:11434.")

    unreachable = pipeline_ai_support.ollama_readiness(
        "http://127.0.0.1:11434",
        "gpt-oss:20b",
        model_fetcher=_raise,
    )
    assert unreachable.status == "service_unreachable"
    assert "Start Ollama" in unreachable.action


def test_gpt_oss_readiness_treats_method_not_allowed_as_reachable():
    class _HTTP405:
        def __call__(self, *_args, **_kwargs):
            raise pipeline_ai_support.urllib.error.HTTPError(
                url="http://127.0.0.1:8000/v1/responses",
                code=405,
                msg="Method Not Allowed",
                hdrs=None,
                fp=None,
            )

    readiness = pipeline_ai_support.gpt_oss_readiness(
        "http://127.0.0.1:8000",
        urlopen_fn=_HTTP405(),
    )

    assert readiness.status == "ready"
    assert readiness.endpoint == "http://127.0.0.1:8000/v1/responses"


def test_default_ollama_model_prefers_code_model_when_requested():
    def _fake_available(_endpoint: str):
        return ["qwen2.5-coder:latest", "codestral:latest", "llama"]

    original = pipeline_ai_support._ollama_available_models
    pipeline_ai_support._ollama_available_models = _fake_available
    try:
        assert pipeline_ai_support._default_ollama_model("http://127.0.0.1:11434", prefer_code=True) == "codestral:latest"
        assert pipeline_ai_support._default_ollama_model(
            "http://127.0.0.1:11434",
            preferred="llama",
        ) == "llama"
    finally:
        pipeline_ai_support._ollama_available_models = original


def test_default_ollama_family_model_and_matchers_cover_qwen_and_deepseek():
    def _fake_available(_endpoint: str):
        return [
            "qwen2.5-coder:7b",
            "gpt-oss:20b",
            "qwen2.5:14b",
            "deepseek-r1:8b",
            "deepseek-coder:latest",
            "qwen3:30b-a3b-instruct-2507-q4_K_M",
            "qwen3-coder:30b-a3b-q4_K_M",
            "ministral-3:14b-instruct-2512-q4_K_M",
            "phi4-mini:3.8b-q4_K_M",
        ]

    original = pipeline_ai_support._ollama_available_models
    pipeline_ai_support._ollama_available_models = _fake_available
    try:
        assert pipeline_ai_support.default_ollama_family_model(
            "http://127.0.0.1:11434",
            family="qwen",
            prefer_code=True,
        ) == "qwen2.5-coder:7b"
        assert pipeline_ai_support.default_ollama_family_model(
            "http://127.0.0.1:11434",
            family="deepseek",
            prefer_code=True,
        ) == "deepseek-r1:8b"
        assert pipeline_ai_support.ollama_model_matches_family("qwen2.5-coder:7b", "qwen") is True
        assert pipeline_ai_support.ollama_model_matches_family("gpt-oss:20b", "gpt-oss") is True
        assert pipeline_ai_support.ollama_model_matches_family("deepseek-coder:latest", "deepseek") is True
        assert pipeline_ai_support.ollama_model_matches_family("qwen3:30b-a3b-instruct-2507-q4_K_M", "qwen3") is True
        assert pipeline_ai_support.ollama_model_matches_family("qwen3-coder:30b-a3b-q4_K_M", "qwen3-coder") is True
        assert pipeline_ai_support.ollama_model_matches_family("ministral-3:14b-instruct-2512-q4_K_M", "ministral") is True
        assert pipeline_ai_support.ollama_model_matches_family("phi4-mini:3.8b-q4_K_M", "phi4-mini") is True
        assert pipeline_ai_support.ollama_model_matches_family("codestral:latest", "qwen") is False
        assert pipeline_ai_support.ollama_model_matches_family("qwen3-coder:30b", "qwen3") is False
    finally:
        pipeline_ai_support._ollama_available_models = original


def test_default_ollama_family_model_returns_efficient_profile_defaults_when_missing():
    original = pipeline_ai_support._ollama_available_models
    pipeline_ai_support._ollama_available_models = lambda _endpoint: []
    try:
        assert (
            pipeline_ai_support.default_ollama_family_model("http://127.0.0.1:11434", family="gpt-oss")
            == "gpt-oss:20b"
        )
        assert (
            pipeline_ai_support.default_ollama_family_model("http://127.0.0.1:11434", family="qwen3")
            == "qwen3:30b-a3b-instruct-2507-q4_K_M"
        )
        assert (
            pipeline_ai_support.default_ollama_family_model("http://127.0.0.1:11434", family="qwen3-coder")
            == "qwen3-coder:30b-a3b-q4_K_M"
        )
        assert (
            pipeline_ai_support.default_ollama_family_model("http://127.0.0.1:11434", family="ministral")
            == "ministral-3:14b-instruct-2512-q4_K_M"
        )
        assert (
            pipeline_ai_support.default_ollama_family_model("http://127.0.0.1:11434", family="phi4-mini")
            == "phi4-mini:3.8b-q4_K_M"
        )
    finally:
        pipeline_ai_support._ollama_available_models = original


def test_ollama_generate_parses_generate_response_and_forwards_payload(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = str(getattr(request, "full_url", ""))
        captured["method"] = getattr(request, "method", "")
        captured["data"] = request.data.decode("utf-8")
        return _FakeURLOpenResponse('{"response":"ok"}')

    monkeypatch.setattr(pipeline_ai_support.urllib.request, "urlopen", fake_urlopen)

    text = pipeline_ai_support._ollama_generate(
        endpoint="http://127.0.0.1:11434",
        model="qwen2.5-coder:latest",
        prompt="hello",
        num_ctx=256,
        num_predict=128,
        seed=1,
    )

    assert text == "ok"
    assert "/api/generate" in captured["url"]
    payload = json.loads(captured["data"])
    assert payload["model"] == "qwen2.5-coder:latest"
    assert payload["options"]["num_ctx"] == 256
    assert payload["options"]["num_predict"] == 128
def test_prompt_to_plaintext_flattens_list_content_and_unknown_roles():
    text = pipeline_ai_support.prompt_to_plaintext(
        [
            {"role": "system", "content": "rules"},
            {"role": "critic", "content": ["alpha", "beta"]},
        ],
        "continue",
    )

    assert "System: rules" in text
    assert "Critic: alpha\nbeta" in text
    assert text.endswith("User: continue")


def test_normalize_identifier_handles_digits_and_fallback():
    assert pipeline_ai_support.normalize_identifier("Flight Level (%)") == "flight_level"
    assert pipeline_ai_support.normalize_identifier("12-bearers") == "_12_bearers"
    assert pipeline_ai_support.normalize_identifier("", fallback="service") == "service"


def test_synthesize_stub_response_builds_savgol_code_with_odd_window():
    response = pipeline_ai_support.synthesize_stub_response("Apply savgol on column Air-Speed with window 8")

    assert "from scipy.signal import savgol_filter" in response
    assert "column = 'air_speed'" in response
    assert "window_length = 9" in response


def test_synthesize_stub_response_returns_generic_stub_message():
    response = pipeline_ai_support.synthesize_stub_response("Summarize the dataframe")

    assert "stub backend" in response
    assert "real backend" in response


def test_format_for_responses_wraps_plain_text_and_preserves_list_content():
    conversation = [
        {"role": "system", "content": "rules"},
        {"role": "assistant", "content": [{"type": "text", "text": "already structured"}]},
    ]

    formatted = pipeline_ai_support.format_for_responses(conversation)

    assert formatted[0] == {
        "role": "system",
        "content": [{"type": "text", "text": "rules"}],
    }
    assert formatted[1]["content"] == [{"type": "text", "text": "already structured"}]


def test_response_to_text_prefers_output_text_then_structured_and_legacy_choices():
    direct = SimpleNamespace(output_text="  done  ")
    assert pipeline_ai_support.response_to_text(direct) == "done"

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
    assert pipeline_ai_support.response_to_text(structured) == "alpha\nbeta"

    legacy = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=" legacy "))])
    assert pipeline_ai_support.response_to_text(legacy) == "legacy"


def test_response_to_text_handles_text_chunks_and_empty_payloads():
    chunked = SimpleNamespace(output=[SimpleNamespace(type="tool", text=SimpleNamespace(value="chunk"))])
    assert pipeline_ai_support.response_to_text(chunked) == "chunk"

    broken_legacy = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace())])
    assert pipeline_ai_support.response_to_text(broken_legacy) == ""
    assert pipeline_ai_support.response_to_text(None) == ""


def test_redact_sensitive_masks_openai_style_keys():
    message = "bad key sk-ABCD1234567890 and project key sk-proj-WXYZabcdefgh123456"

    redacted = pipeline_ai_support.redact_sensitive(message)

    assert "sk-ABCD12…" in redacted
    assert "sk-proj…" in redacted
    assert "1234567890" not in redacted


def test_prompt_to_gpt_oss_messages_separates_system_and_normalizes_roles():
    instructions, history = pipeline_ai_support.prompt_to_gpt_oss_messages(
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
    text = pipeline_ai_support.format_uoaic_question(
        [
            {"role": "system", "content": "rules"},
            {"role": "assistant", "content": "previous answer"},
        ],
        "plot value",
    )

    assert text.startswith(pipeline_ai_support.CODE_STRICT_INSTRUCTIONS)
    assert "System: rules" in text
    assert "Assistant: previous answer" in text
    assert text.endswith("User: plot value")


def test_format_uoaic_question_handles_list_content_blank_entries_and_fallback_roles():
    text = pipeline_ai_support.format_uoaic_question(
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

    normalized = pipeline_ai_support.normalize_user_path("dataset.csv")

    assert normalized == str(target.resolve())


def test_resolve_uoaic_path_uses_base_dir_and_rejects_empty_input(tmp_path):
    assert pipeline_ai_support._resolve_uoaic_path("docs/manual.pdf", base_dir=tmp_path) == (
        tmp_path / "docs" / "manual.pdf"
    ).resolve()

    with pytest.raises(ValueError, match="Path is empty"):
        pipeline_ai_support._resolve_uoaic_path("", base_dir=tmp_path)


def test_load_uoaic_modules_reports_missing_package():
    def _missing_distribution(_name: str):
        raise pipeline_ai_support.importlib_metadata.PackageNotFoundError()

    with pytest.raises(RuntimeError, match="universal-offline-ai-chatbot"):
        pipeline_ai_support._load_uoaic_modules(distribution_fn=_missing_distribution)


def test_load_uoaic_modules_loads_modules_from_wheel_files(tmp_path):
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

    def _failing_import(name: str):
        raise ImportError("fallback", name=name)

    modules = pipeline_ai_support._load_uoaic_modules(
        distribution_fn=lambda _name: FakeDist(),
        import_module_fn=_failing_import,
    )

    assert [module.IDENT for module in modules] == [
        "chunker",
        "embedding",
        "loader",
        "model_loader",
        "prompts",
        "qa_chain",
        "vectorstore",
    ]


def test_ensure_uoaic_runtime_builds_and_reuses_cached_runtime(tmp_path):
    data_dir = tmp_path / "docs"
    data_dir.mkdir()
    session_state = {}
    envars = {
        "UOAIC_DATA_DIR": str(data_dir),
        "UOAIC_MODEL": "offline-model",
    }
    build_calls = []

    chunker = SimpleNamespace(create_chunks=lambda docs: ["chunk"] if docs == ["doc"] else [])
    embedding = SimpleNamespace(get_embedding_model=lambda: "embedding-model")
    loader = SimpleNamespace(load_pdf_files=lambda path: ["doc"] if path == str(data_dir) else [])
    model_loader = SimpleNamespace(load_llm=lambda: SimpleNamespace(model_name="local-model"))
    prompts = SimpleNamespace(
        CUSTOM_PROMPT_TEMPLATE="prompt-template",
        set_custom_prompt=lambda template: f"custom:{template}",
    )
    qa_chain = SimpleNamespace(setup_qa_chain=lambda llm, db, prompt: ("chain", llm, db, prompt))
    vectorstore = SimpleNamespace(
        build_vector_db=lambda chunks, emb, path: build_calls.append((chunks, emb, path)),
        load_vector_db=lambda path, emb: {"path": path, "embedding": emb},
    )

    runtime = pipeline_ai_support._ensure_uoaic_runtime(
        envars,
        session_state=session_state,
        resolve_uoaic_path=lambda raw_path, base_dir=None: pipeline_ai_support._resolve_uoaic_path(
            raw_path, base_dir=base_dir
        ),
        load_uoaic_modules=lambda: (chunker, embedding, loader, model_loader, prompts, qa_chain, vectorstore),
        runtime_state_key="runtime",
        data_state_key="data_dir",
        db_state_key="db_dir",
        rebuild_state_key="rebuild",
        data_env_key="UOAIC_DATA_DIR",
        db_env_key="UOAIC_DB_DIR",
        model_env_key="UOAIC_MODEL",
        default_db_dirname="vectorstore",
        base_dir=tmp_path,
    )

    assert runtime["model_label"] == "local-model"
    assert runtime["prompt"] == "custom:prompt-template"
    assert build_calls == [(["chunk"], "embedding-model", str(data_dir / "vectorstore"))]
    assert session_state["runtime"] is runtime

    cached = pipeline_ai_support._ensure_uoaic_runtime(
        envars,
        session_state=session_state,
        resolve_uoaic_path=lambda raw_path, base_dir=None: pipeline_ai_support._resolve_uoaic_path(
            raw_path, base_dir=base_dir
        ),
        load_uoaic_modules=lambda: pytest.fail("cached runtime should be reused"),
        runtime_state_key="runtime",
        data_state_key="data_dir",
        db_state_key="db_dir",
        rebuild_state_key="rebuild",
        data_env_key="UOAIC_DATA_DIR",
        db_env_key="UOAIC_DB_DIR",
        model_env_key="UOAIC_MODEL",
        default_db_dirname="vectorstore",
        base_dir=tmp_path,
    )

    assert cached is runtime


def test_validate_code_safety_rejects_import_statements():
    with pytest.raises(pipeline_ai_support._UnsafeCodeError, match="Import statements are not allowed"):
        pipeline_ai_support._validate_code_safety("import os")


def test_validate_code_safety_rejects_blocked_builtin():
    with pytest.raises(pipeline_ai_support._UnsafeCodeError, match="Call to blocked builtin"):
        pipeline_ai_support._validate_code_safety("open('x', 'r')")


def test_validate_code_safety_rejects_blocked_module_attribute():
    with pytest.raises(pipeline_ai_support._UnsafeCodeError, match="Access to module 'os' is not allowed"):
        pipeline_ai_support._validate_code_safety("os.system('echo hi')")


def test_validate_code_safety_rejects_blocked_dunder_attr():
    with pytest.raises(pipeline_ai_support._UnsafeCodeError, match="Access to '__class__' is not allowed"):
        pipeline_ai_support._validate_code_safety("x = 1\nx.__class__")


def test_exec_code_on_df_blocks_unsafe_code():
    updated, error = pipeline_ai_support._exec_code_on_df("os.system('echo hi')", pd.DataFrame({"x": [1]}))
    assert updated is None
    assert "Safety check failed" in error


def test_build_autofix_prompt_clips_traceback_and_code():
    prompt = pipeline_ai_support._build_autofix_prompt(
        original_request="smooth",
        failing_code="x" * 7000,
        traceback_text="y" * 5000,
        attempt=1,
    )

    assert "attempt 1" in prompt
    assert len(prompt) < 12000
