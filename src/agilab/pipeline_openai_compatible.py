from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

OPENAI_COMPAT_PROVIDER = "openai-compatible"
OPENAI_COMPAT_BASE_URL_ENV = "AGILAB_LLM_BASE_URL"
OPENAI_COMPAT_API_KEY_ENV = "AGILAB_LLM_API_KEY"
OPENAI_COMPAT_MODEL_ENV = "AGILAB_LLM_MODEL"
OPENAI_COMPAT_TEMPERATURE_ENV = "AGILAB_LLM_TEMPERATURE"
OPENAI_COMPAT_MAX_TOKENS_ENV = "AGILAB_LLM_MAX_TOKENS"
OPENAI_COMPAT_TIMEOUT_ENV = "AGILAB_LLM_TIMEOUT"

DEFAULT_OPENAI_COMPAT_BASE_URL = "http://127.0.0.1:8000/v1"
DEFAULT_OPENAI_COMPAT_API_KEY = "EMPTY"
DEFAULT_OPENAI_COMPAT_MODEL = "Qwen/Qwen2.5-Coder-7B-Instruct"


@dataclass(frozen=True)
class OpenAICompatibleSettings:
    base_url: str
    api_key: str
    model: str
    temperature: float
    max_tokens: Optional[int]
    timeout_s: float


def normalize_openai_compatible_base_url(raw_base_url: Optional[str]) -> str:
    """Normalize OpenAI-compatible base URLs to the SDK base URL shape."""
    base_url = (raw_base_url or "").strip() or DEFAULT_OPENAI_COMPAT_BASE_URL
    base_url = base_url.rstrip("/")
    for suffix in ("/chat/completions", "/completions", "/responses"):
        if base_url.endswith(suffix):
            base_url = base_url[: -len(suffix)].rstrip("/")
            break
    if base_url.endswith("/v1"):
        return base_url
    return f"{base_url}/v1"


def _env_value(envars: Dict[str, str], name: str, default: str = "") -> str:
    return str(envars.get(name) or os.getenv(name) or default).strip()


def _float_setting(envars: Dict[str, str], name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw = _env_value(envars, name)
    if not raw:
        return float(default)
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric.") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")
    return value


def _optional_positive_int(envars: Dict[str, str], name: str) -> Optional[int]:
    raw = _env_value(envars, name)
    if not raw:
        return None
    try:
        value = int(float(raw))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer.") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive.")
    return value


def resolve_openai_compatible_settings(envars: Dict[str, str]) -> OpenAICompatibleSettings:
    """Resolve settings for vLLM and other OpenAI-compatible Chat Completions servers."""
    base_url = normalize_openai_compatible_base_url(_env_value(envars, OPENAI_COMPAT_BASE_URL_ENV))
    api_key = _env_value(envars, OPENAI_COMPAT_API_KEY_ENV, DEFAULT_OPENAI_COMPAT_API_KEY)
    model = _env_value(envars, OPENAI_COMPAT_MODEL_ENV, DEFAULT_OPENAI_COMPAT_MODEL)
    if not model:
        raise ValueError(f"{OPENAI_COMPAT_MODEL_ENV} cannot be empty.")
    return OpenAICompatibleSettings(
        base_url=base_url,
        api_key=api_key or DEFAULT_OPENAI_COMPAT_API_KEY,
        model=model,
        temperature=_float_setting(envars, OPENAI_COMPAT_TEMPERATURE_ENV, 0.1, minimum=0.0, maximum=2.0),
        max_tokens=_optional_positive_int(envars, OPENAI_COMPAT_MAX_TOKENS_ENV),
        timeout_s=_float_setting(envars, OPENAI_COMPAT_TIMEOUT_ENV, 120.0, minimum=1.0, maximum=3600.0),
    )


def build_openai_compatible_completion_kwargs(
    messages: List[Dict[str, str]],
    envars: Dict[str, str],
) -> Tuple[Dict[str, Any], OpenAICompatibleSettings]:
    settings = resolve_openai_compatible_settings(envars)
    payload: Dict[str, Any] = {
        "model": settings.model,
        "messages": messages,
        "temperature": settings.temperature,
    }
    if settings.max_tokens is not None:
        payload["max_tokens"] = settings.max_tokens
    return payload, settings


__all__ = [
    "DEFAULT_OPENAI_COMPAT_API_KEY",
    "DEFAULT_OPENAI_COMPAT_BASE_URL",
    "DEFAULT_OPENAI_COMPAT_MODEL",
    "OPENAI_COMPAT_API_KEY_ENV",
    "OPENAI_COMPAT_BASE_URL_ENV",
    "OPENAI_COMPAT_MAX_TOKENS_ENV",
    "OPENAI_COMPAT_MODEL_ENV",
    "OPENAI_COMPAT_PROVIDER",
    "OPENAI_COMPAT_TEMPERATURE_ENV",
    "OPENAI_COMPAT_TIMEOUT_ENV",
    "OpenAICompatibleSettings",
    "build_openai_compatible_completion_kwargs",
    "normalize_openai_compatible_base_url",
    "resolve_openai_compatible_settings",
]
