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


class _StopCalled(RuntimeError):
    pass


class _FakeForm:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeMistralStreamlit:
    def __init__(self, *, new_key: str = "", save_profile: bool = False, submitted: bool = True):
        self.session_state: dict[str, object] = {}
        self.secrets: dict[str, str] = {}
        self.new_key = new_key
        self.save_profile = save_profile
        self.submitted = submitted
        self.events: list[tuple[str, str]] = []
        self.reruns = 0

    def warning(self, message):
        self.events.append(("warning", str(message)))

    def error(self, message):
        self.events.append(("error", str(message)))

    def success(self, message):
        self.events.append(("success", str(message)))

    def form(self, _key):
        return _FakeForm()

    def text_input(self, *_args, **_kwargs):
        return self.new_key

    def checkbox(self, *_args, **_kwargs):
        return self.save_profile

    def form_submit_button(self, *_args, **_kwargs):
        return self.submitted

    def rerun(self):
        self.reruns += 1

    def stop(self):
        raise _StopCalled


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


def test_mistral_normalizes_urls_and_reads_model_from_environment(monkeypatch):
    normalize = pipeline_mistral.normalize_mistral_base_url
    monkeypatch.setenv("MISTRAL_MODEL", " env-medium ")

    assert normalize(None) == "https://api.mistral.ai/v1"
    assert normalize(" https://gateway.example/v1/chat/completions/ ") == "https://gateway.example/v1"
    assert pipeline_mistral.mistral_chat_completions_url("https://gateway.example/v1/") == (
        "https://gateway.example/v1/chat/completions"
    )
    assert pipeline_mistral.resolve_mistral_model({}) == "env-medium"


@pytest.mark.parametrize(
    ("envars", "message"),
    [
        ({"MISTRAL_MODEL": "  "}, "MISTRAL_MODEL cannot be empty"),
        ({"MISTRAL_REASONING_EFFORT": "medium"}, "MISTRAL_REASONING_EFFORT must be one of"),
        ({"MISTRAL_TEMPERATURE": "warm"}, "MISTRAL_TEMPERATURE must be numeric"),
        ({"MISTRAL_TEMPERATURE": "2.0"}, "MISTRAL_TEMPERATURE must be between"),
        ({"MISTRAL_MAX_TOKENS": "many"}, "MISTRAL_MAX_TOKENS must be an integer"),
        ({"MISTRAL_MAX_TOKENS": "0"}, "MISTRAL_MAX_TOKENS must be positive"),
    ],
)
def test_mistral_payload_rejects_invalid_settings(envars, message):
    with pytest.raises(ValueError, match=message):
        pipeline_mistral.build_mistral_chat_payload(
            [{"role": "user", "content": "hello"}],
            envars,
        )


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


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (None, "unexpected payload"),
        ({}, "did not include any choices"),
        ({"choices": ["bad"]}, "choice was not an object"),
        ({"choices": [{}]}, "did not include a message"),
        ({"choices": [{"message": {"content": None}}]}, ""),
        ({"choices": [{"message": {"content": ["alpha", {"text": "beta"}]}}]}, "alpha\nbeta"),
    ],
)
def test_mistral_response_to_text_handles_payload_shapes(payload, message):
    if message in {"", "alpha\nbeta"}:
        assert pipeline_mistral._response_to_text(payload) == message
    else:
        with pytest.raises(pipeline_mistral.MistralApiError, match=message):
            pipeline_mistral._response_to_text(payload)


def test_call_mistral_chat_completion_rejects_invalid_json():
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"not-json"

    with pytest.raises(pipeline_mistral.MistralApiError, match="invalid JSON"):
        pipeline_mistral.call_mistral_chat_completion(
            [{"role": "user", "content": "make code"}],
            {},
            "mistral-secret-value-123456",
            urlopen=lambda *_args, **_kwargs: Response(),
        )


def test_call_mistral_chat_completion_reports_unreachable_gateway():
    def fake_urlopen(_request, timeout):
        assert timeout == 120.0
        raise urllib.error.URLError("offline")

    with pytest.raises(pipeline_mistral.MistralApiError) as exc_info:
        pipeline_mistral.call_mistral_chat_completion(
            [{"role": "user", "content": "make code"}],
            {"MISTRAL_BASE_URL": "https://gateway.example/v1"},
            "mistral-secret-value-123456",
            urlopen=fake_urlopen,
        )

    assert "Unable to reach Mistral API at https://gateway.example/v1/chat/completions" in str(exc_info.value)


def test_call_mistral_chat_completion_rejects_invalid_timeout():
    with pytest.raises(ValueError, match="MISTRAL_TIMEOUT must be positive"):
        pipeline_mistral.call_mistral_chat_completion(
            [{"role": "user", "content": "make code"}],
            {"MISTRAL_TIMEOUT": "0"},
            "mistral-secret-value-123456",
            urlopen=lambda *_args, **_kwargs: None,
        )


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


def test_call_mistral_chat_completion_redacts_http_reason_when_body_unreadable():
    class UnreadableBody:
        def read(self):
            raise OSError("body unavailable")

        def close(self):
            pass

    def fake_urlopen(_request, timeout):
        assert timeout == 120.0
        raise urllib.error.HTTPError(
            url="https://api.mistral.ai/v1/chat/completions",
            code=500,
            msg="mistral-secret-value-123456 failed",
            hdrs=None,
            fp=UnreadableBody(),
        )

    with pytest.raises(pipeline_mistral.MistralApiError) as exc_info:
        pipeline_mistral.call_mistral_chat_completion(
            [{"role": "user", "content": "make code"}],
            {},
            "mistral-secret-value-123456",
            urlopen=fake_urlopen,
        )

    assert "mistral-secret-value-123456" not in str(exc_info.value)
    assert "<redacted>" in str(exc_info.value)


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


def test_ensure_cached_mistral_api_key_prefers_valid_cached_key(monkeypatch):
    fake_st = types.SimpleNamespace(
        session_state={"mistral_api_key": "cached-secret"},
        secrets={"MISTRAL_API_KEY": "other-secret"},
    )
    monkeypatch.setattr(pipeline_mistral, "st", fake_st)

    assert pipeline_mistral.ensure_cached_mistral_api_key({}) == "cached-secret"


def test_ensure_cached_mistral_api_key_handles_secret_store_errors(monkeypatch):
    class BrokenSecrets:
        def get(self, *_args, **_kwargs):
            raise RuntimeError("secrets unavailable")

    fake_st = types.SimpleNamespace(session_state={}, secrets=BrokenSecrets())
    monkeypatch.setattr(pipeline_mistral, "st", fake_st)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)

    assert pipeline_mistral.ensure_cached_mistral_api_key({"MISTRAL_API_KEY": "placeholder"}) == ""
    assert fake_st.session_state["mistral_api_key"] == ""


def test_prompt_for_mistral_api_key_rejects_empty_submission(monkeypatch):
    fake_st = _FakeMistralStreamlit(new_key="  ")
    monkeypatch.setattr(pipeline_mistral, "st", fake_st)

    with pytest.raises(_StopCalled):
        pipeline_mistral.prompt_for_mistral_api_key("Missing key")

    assert ("warning", "Missing key") in fake_st.events
    assert ("error", "API key cannot be empty.") in fake_st.events
    assert fake_st.reruns == 0


def test_prompt_for_mistral_api_key_updates_session_without_persisting(monkeypatch):
    fake_st = _FakeMistralStreamlit(new_key=" mistral-secret-value-123456 ", save_profile=False)
    monkeypatch.setattr(pipeline_mistral, "st", fake_st)
    monkeypatch.setattr(pipeline_mistral.AgiEnv, "set_env_var", lambda *_args, **_kwargs: None)

    with pytest.raises(_StopCalled):
        pipeline_mistral.prompt_for_mistral_api_key("Missing key")

    assert fake_st.session_state["mistral_api_key"] == "mistral-secret-value-123456"
    assert ("success", "API key updated for this session.") in fake_st.events
    assert fake_st.reruns == 1


def test_prompt_for_mistral_api_key_reports_persist_failure(monkeypatch):
    fake_st = _FakeMistralStreamlit(new_key="mistral-secret-value-123456", save_profile=True)
    monkeypatch.setattr(pipeline_mistral, "st", fake_st)
    monkeypatch.setattr(pipeline_mistral.AgiEnv, "set_env_var", lambda *_args, **_kwargs: None)

    def raise_os_error(*_args, **_kwargs):
        raise OSError("read-only")

    monkeypatch.setattr(pipeline_mistral, "persist_env_var", raise_os_error)

    with pytest.raises(_StopCalled):
        pipeline_mistral.prompt_for_mistral_api_key("Missing key")

    assert ("warning", "Could not persist API key: read-only") in fake_st.events
    assert fake_st.reruns == 1
