from __future__ import annotations

from io import BytesIO
import importlib
import json
from pathlib import Path
import sys
import types
import urllib.error

import pytest


def _import_agilab_module(module_name: str):
    src_root = Path(__file__).resolve().parents[1] / "src"
    package_root = src_root / "agilab"
    src_root_str = str(src_root)
    package_root_str = str(package_root)
    if src_root_str not in sys.path:
        sys.path.insert(0, src_root_str)
    pkg = sys.modules.get("agilab")
    if pkg is None or not hasattr(pkg, "__path__"):
        pkg = types.ModuleType("agilab")
        pkg.__path__ = [package_root_str]
        sys.modules["agilab"] = pkg
    else:
        package_path = list(pkg.__path__)
        if package_root_str not in package_path:
            pkg.__path__ = [package_root_str, *package_path]
    importlib.invalidate_caches()
    return importlib.import_module(module_name)


pipeline_mistral = _import_agilab_module("agilab.pipeline_mistral")


def test_mistral_payload_defaults_to_medium_3_5_high_reasoning(monkeypatch):
    monkeypatch.delenv("MISTRAL_MODEL", raising=False)
    monkeypatch.delenv("MISTRAL_REASONING_EFFORT", raising=False)
    monkeypatch.delenv("MISTRAL_TEMPERATURE", raising=False)

    payload, model = pipeline_mistral.build_mistral_chat_payload(
        [{"role": "user", "content": "hello"}],
        {},
    )

    assert model == "mistral-medium-3.5"
    assert payload == {
        "model": "mistral-medium-3.5",
        "messages": [{"role": "user", "content": "hello"}],
        "stream": False,
        "reasoning_effort": "high",
        "temperature": 0.7,
    }


def test_mistral_payload_accepts_none_reasoning_temperature_and_max_tokens():
    payload, model = pipeline_mistral.build_mistral_chat_payload(
        [{"role": "user", "content": "hello"}],
        {
            "MISTRAL_MODEL": "custom-medium",
            "MISTRAL_REASONING_EFFORT": "none",
            "MISTRAL_TEMPERATURE": "0.2",
            "MISTRAL_MAX_TOKENS": "512",
        },
    )

    assert model == "custom-medium"
    assert payload["reasoning_effort"] == "none"
    assert payload["temperature"] == 0.2
    assert payload["max_tokens"] == 512


def test_call_mistral_chat_completion_posts_to_chat_endpoint_and_reads_text():
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": "```python\nprint(1)\n```"}}]}
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return Response()

    text, model = pipeline_mistral.call_mistral_chat_completion(
        [{"role": "user", "content": "make code"}],
        {"MISTRAL_TIMEOUT": "12"},
        "mistral-secret-value-123456",
        urlopen=fake_urlopen,
    )

    assert text == "```python\nprint(1)\n```"
    assert model == "mistral-medium-3.5"
    assert captured["url"] == "https://api.mistral.ai/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer mistral-secret-value-123456"
    assert captured["payload"]["model"] == "mistral-medium-3.5"
    assert captured["payload"]["reasoning_effort"] == "high"
    assert captured["timeout"] == 12.0


def test_call_mistral_chat_completion_accepts_custom_base_and_structured_content():
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": [{"text": "alpha"}, {"text": "beta"}]}}]}
            ).encode("utf-8")

    text, _model = pipeline_mistral.call_mistral_chat_completion(
        [{"role": "user", "content": "make code"}],
        {"MISTRAL_BASE_URL": "https://gateway.example/v1/chat/completions"},
        "mistral-secret-value-123456",
        urlopen=lambda *_args, **_kwargs: Response(),
    )

    assert pipeline_mistral.mistral_chat_completions_url(
        "https://gateway.example/v1/chat/completions"
    ) == "https://gateway.example/v1/chat/completions"
    assert text == "alpha\nbeta"


def test_call_mistral_chat_completion_redacts_http_error_key():
    def fake_urlopen(_request, timeout):
        assert timeout == 120.0
        raise urllib.error.HTTPError(
            url="https://api.mistral.ai/v1/chat/completions",
            code=401,
            msg="unauthorized",
            hdrs=None,
            fp=BytesIO(b"bad mistral-secret-value-123456"),
        )

    with pytest.raises(pipeline_mistral.MistralApiError) as exc_info:
        pipeline_mistral.call_mistral_chat_completion(
            [{"role": "user", "content": "make code"}],
            {},
            "mistral-secret-value-123456",
            urlopen=fake_urlopen,
        )

    message = str(exc_info.value)
    assert "Mistral API error 401" in message
    assert "mistral-secret-value-123456" not in message
    assert "<redacted>" in message


def test_ensure_cached_mistral_api_key_uses_secret_and_process_env(monkeypatch):
    fake_st = types.SimpleNamespace(session_state={}, secrets={"MISTRAL_API_KEY": "mistral-secret-1"})
    monkeypatch.setattr(pipeline_mistral, "st", fake_st)

    assert pipeline_mistral.ensure_cached_mistral_api_key({}) == "mistral-secret-1"
    assert fake_st.session_state["mistral_api_key"] == "mistral-secret-1"

    fake_st.session_state.clear()
    fake_st.secrets = {}
    monkeypatch.setenv("MISTRAL_API_KEY", "mistral-secret-2")

    assert pipeline_mistral.ensure_cached_mistral_api_key({}) == "mistral-secret-2"
    assert fake_st.session_state["mistral_api_key"] == "mistral-secret-2"
