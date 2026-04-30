from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
import urllib.error
import urllib.request

import streamlit as st

from agi_env import AgiEnv

_import_guard_path = Path(__file__).resolve().parent / "import_guard.py"
_import_guard_spec = importlib.util.spec_from_file_location("agilab_import_guard_local", _import_guard_path)
if _import_guard_spec is None or _import_guard_spec.loader is None:
    raise ModuleNotFoundError(f"Unable to load import_guard.py from {_import_guard_path}")
_import_guard_module = importlib.util.module_from_spec(_import_guard_spec)
_import_guard_spec.loader.exec_module(_import_guard_module)
import_agilab_symbols = _import_guard_module.import_agilab_symbols

import_agilab_symbols(
    globals(),
    "agilab.pipeline_openai",
    {
        "is_placeholder_api_key": "is_placeholder_api_key",
        "persist_env_var": "persist_env_var",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "pipeline_openai.py",
    fallback_name="agilab_pipeline_openai_fallback",
)

MISTRAL_PROVIDER = "mistral"
MISTRAL_API_KEY_ENV = "MISTRAL_API_KEY"
MISTRAL_BASE_URL_ENV = "MISTRAL_BASE_URL"
MISTRAL_MODEL_ENV = "MISTRAL_MODEL"
MISTRAL_REASONING_EFFORT_ENV = "MISTRAL_REASONING_EFFORT"
MISTRAL_TEMPERATURE_ENV = "MISTRAL_TEMPERATURE"
MISTRAL_MAX_TOKENS_ENV = "MISTRAL_MAX_TOKENS"
MISTRAL_TIMEOUT_ENV = "MISTRAL_TIMEOUT"

MISTRAL_DEFAULT_BASE_URL = "https://api.mistral.ai/v1"
MISTRAL_DEFAULT_MODEL = "mistral-medium-3.5"
MISTRAL_OPEN_WEIGHT_MODEL = "mistralai/Mistral-Medium-3.5-128B"
MISTRAL_DEFAULT_REASONING_EFFORT = "high"

_VALID_REASONING_EFFORTS = {"high", "none"}


class MistralApiError(RuntimeError):
    """Raised when the Mistral API request fails before returning usable text."""


def normalize_mistral_base_url(raw_base_url: Optional[str]) -> str:
    base_url = (raw_base_url or "").strip() or MISTRAL_DEFAULT_BASE_URL
    base_url = base_url.rstrip("/")
    suffix = "/chat/completions"
    if base_url.endswith(suffix):
        base_url = base_url[: -len(suffix)]
    return base_url


def mistral_chat_completions_url(base_url: Optional[str]) -> str:
    return f"{normalize_mistral_base_url(base_url)}/chat/completions"


def resolve_mistral_model(envars: Dict[str, str]) -> str:
    return (
        envars.get(MISTRAL_MODEL_ENV)
        or os.getenv(MISTRAL_MODEL_ENV)
        or MISTRAL_DEFAULT_MODEL
    ).strip()


def resolve_mistral_reasoning_effort(envars: Dict[str, str]) -> str:
    effort = (
        envars.get(MISTRAL_REASONING_EFFORT_ENV)
        or os.getenv(MISTRAL_REASONING_EFFORT_ENV)
        or MISTRAL_DEFAULT_REASONING_EFFORT
    ).strip().lower()
    if effort not in _VALID_REASONING_EFFORTS:
        raise ValueError(
            f"{MISTRAL_REASONING_EFFORT_ENV} must be one of: "
            f"{', '.join(sorted(_VALID_REASONING_EFFORTS))}"
        )
    return effort


def resolve_mistral_temperature(envars: Dict[str, str], reasoning_effort: str) -> float:
    raw = envars.get(MISTRAL_TEMPERATURE_ENV) or os.getenv(MISTRAL_TEMPERATURE_ENV)
    if raw is None or not str(raw).strip():
        return 0.7 if reasoning_effort == "high" else 0.1
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{MISTRAL_TEMPERATURE_ENV} must be numeric.") from exc
    if value < 0.0 or value > 1.5:
        raise ValueError(f"{MISTRAL_TEMPERATURE_ENV} must be between 0.0 and 1.5.")
    return value


def _optional_positive_int(envars: Dict[str, str], name: str) -> Optional[int]:
    raw = envars.get(name) or os.getenv(name)
    if raw is None or not str(raw).strip():
        return None
    try:
        value = int(float(raw))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer.") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive.")
    return value


def _resolve_timeout(envars: Dict[str, str]) -> float:
    raw = envars.get(MISTRAL_TIMEOUT_ENV) or os.getenv(MISTRAL_TIMEOUT_ENV)
    if raw is None or not str(raw).strip():
        return 120.0
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{MISTRAL_TIMEOUT_ENV} must be numeric.") from exc
    if value <= 0:
        raise ValueError(f"{MISTRAL_TIMEOUT_ENV} must be positive.")
    return value


def _redact_mistral_secret(text: str, api_key: str) -> str:
    message = str(text)
    if api_key:
        message = message.replace(api_key, "<redacted>")
    return message


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
            elif item:
                parts.append(str(item))
        return "\n".join(parts)
    if content is None:
        return ""
    return str(content)


def _response_to_text(data: Any) -> str:
    if not isinstance(data, dict):
        raise MistralApiError(f"Mistral returned unexpected payload: {type(data).__name__}")
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise MistralApiError("Mistral response did not include any choices.")
    first = choices[0]
    if not isinstance(first, dict):
        raise MistralApiError("Mistral response choice was not an object.")
    message = first.get("message")
    if not isinstance(message, dict):
        raise MistralApiError("Mistral response choice did not include a message.")
    return _content_to_text(message.get("content")).strip()


def build_mistral_chat_payload(
    messages: List[Dict[str, str]],
    envars: Dict[str, str],
) -> Tuple[Dict[str, Any], str]:
    model = resolve_mistral_model(envars)
    if not model:
        raise ValueError(f"{MISTRAL_MODEL_ENV} cannot be empty.")
    reasoning_effort = resolve_mistral_reasoning_effort(envars)
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "reasoning_effort": reasoning_effort,
        "temperature": resolve_mistral_temperature(envars, reasoning_effort),
    }
    max_tokens = _optional_positive_int(envars, MISTRAL_MAX_TOKENS_ENV)
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    return payload, model


def call_mistral_chat_completion(
    messages: List[Dict[str, str]],
    envars: Dict[str, str],
    api_key: str,
    *,
    urlopen: Callable[..., Any] = urllib.request.urlopen,
) -> Tuple[str, str]:
    payload, model = build_mistral_chat_payload(messages, envars)
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        mistral_chat_completions_url(
            envars.get(MISTRAL_BASE_URL_ENV) or os.getenv(MISTRAL_BASE_URL_ENV)
        ),
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=_resolve_timeout(envars)) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except (OSError, ValueError):
            pass
        safe_detail = _redact_mistral_secret(detail or exc.reason, api_key)
        raise MistralApiError(f"Mistral API error {exc.code}: {safe_detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise MistralApiError(
            f"Unable to reach Mistral API at {request.full_url}. "
            f"Update {MISTRAL_BASE_URL_ENV} if you use a gateway."
        ) from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MistralApiError(f"Mistral returned invalid JSON: {raw[:2000]}") from exc

    return _response_to_text(parsed), model


def ensure_cached_mistral_api_key(
    envars: Dict[str, str],
    *,
    is_placeholder: Callable[[Optional[str]], bool] = is_placeholder_api_key,
) -> str:
    cached = st.session_state.get("mistral_api_key")
    if cached and not is_placeholder(cached):
        return cached

    secret = ""
    try:
        secret = st.secrets.get(MISTRAL_API_KEY_ENV, "")
    except (AttributeError, RuntimeError, TypeError):
        pass

    candidate = secret or envars.get(MISTRAL_API_KEY_ENV) or os.environ.get(MISTRAL_API_KEY_ENV, "")
    if candidate and not is_placeholder(candidate):
        st.session_state["mistral_api_key"] = candidate
        return candidate

    st.session_state["mistral_api_key"] = ""
    return ""


def prompt_for_mistral_api_key(message: str) -> None:
    st.warning(message)
    default_value = st.session_state.get("mistral_api_key", "")
    with st.form("experiment_missing_mistral_api_key"):
        new_key = st.text_input(
            "Mistral API key",
            value=default_value,
            type="password",
        )
        save_profile = st.checkbox(
            "Save to ~/.agilab/.env",
            value=False,
            help="Opt in only on a trusted single-user machine. The file is written with owner-only permissions.",
        )
        submitted = st.form_submit_button("Update key")

    if submitted:
        cleaned = new_key.strip()
        if not cleaned:
            st.error("API key cannot be empty.")
        else:
            try:
                AgiEnv.set_env_var(MISTRAL_API_KEY_ENV, cleaned)
            except (AttributeError, ImportError, RuntimeError):
                pass
            env_obj = st.session_state.get("env")
            if isinstance(env_obj, AgiEnv) and env_obj.envars is not None:
                env_obj.envars[MISTRAL_API_KEY_ENV] = cleaned
            st.session_state["mistral_api_key"] = cleaned
            if save_profile:
                try:
                    persist_env_var(MISTRAL_API_KEY_ENV, cleaned)
                    st.success("API key saved to ~/.agilab/.env")
                except OSError as exc:
                    st.warning(f"Could not persist API key: {exc}")
            else:
                st.success("API key updated for this session.")
            st.rerun()

    st.stop()


__all__ = [
    "MISTRAL_API_KEY_ENV",
    "MISTRAL_BASE_URL_ENV",
    "MISTRAL_DEFAULT_BASE_URL",
    "MISTRAL_DEFAULT_MODEL",
    "MISTRAL_DEFAULT_REASONING_EFFORT",
    "MISTRAL_MAX_TOKENS_ENV",
    "MISTRAL_MODEL_ENV",
    "MISTRAL_OPEN_WEIGHT_MODEL",
    "MISTRAL_PROVIDER",
    "MISTRAL_REASONING_EFFORT_ENV",
    "MISTRAL_TEMPERATURE_ENV",
    "MistralApiError",
    "build_mistral_chat_payload",
    "call_mistral_chat_completion",
    "ensure_cached_mistral_api_key",
    "mistral_chat_completions_url",
    "normalize_mistral_base_url",
    "prompt_for_mistral_api_key",
    "resolve_mistral_model",
]
