# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Provider and model capability helpers for AGILAB agent workflows."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


CAPABILITY_SCHEMA = "agilab.agent_provider_capability.v1"


@dataclass(frozen=True)
class ProviderCapability:
    """Conservative provider/model capability metadata."""

    schema: str
    provider: str
    model: str
    context_window: int | None = None
    max_output_tokens: int | None = None
    supports_reasoning: bool | None = None
    supports_image_input: bool | None = None
    supports_pdf_input: bool | None = None
    source: str = "default"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_DEFAULT_PROVIDER_MODELS: dict[str, str] = {
    "openai": "gpt-5.4-mini",
    "mistral": "mistral-large-latest",
    "openai-compatible": "openai-compatible",
    "gpt-oss": "gpt-oss-120b",
    "ollama": "qwen2.5-coder:latest",
    "local": "local-model",
}

_PROVIDER_DEFAULTS: dict[str, dict[str, Any]] = {
    "openai": {
        "context_window": None,
        "max_output_tokens": None,
        "supports_reasoning": True,
        "supports_image_input": True,
        "supports_pdf_input": True,
    },
    "mistral": {
        "context_window": None,
        "max_output_tokens": None,
        "supports_reasoning": False,
        "supports_image_input": True,
        "supports_pdf_input": False,
    },
    "openai-compatible": {
        "context_window": None,
        "max_output_tokens": None,
        "supports_reasoning": None,
        "supports_image_input": None,
        "supports_pdf_input": None,
    },
    "gpt-oss": {
        "context_window": None,
        "max_output_tokens": None,
        "supports_reasoning": True,
        "supports_image_input": False,
        "supports_pdf_input": False,
    },
    "ollama": {
        "context_window": None,
        "max_output_tokens": None,
        "supports_reasoning": None,
        "supports_image_input": False,
        "supports_pdf_input": False,
    },
    "local": {
        "context_window": None,
        "max_output_tokens": None,
        "supports_reasoning": None,
        "supports_image_input": False,
        "supports_pdf_input": False,
    },
}

_MODEL_OVERRIDES: dict[tuple[str, str], dict[str, Any]] = {
    ("openai", "gpt-5.4-mini"): {
        "supports_reasoning": True,
        "supports_image_input": True,
        "supports_pdf_input": True,
    },
    ("openai", "gpt-5"): {
        "supports_reasoning": True,
        "supports_image_input": True,
        "supports_pdf_input": True,
    },
    ("openai", "gpt-5-mini"): {
        "supports_reasoning": True,
        "supports_image_input": True,
        "supports_pdf_input": True,
    },
    ("openai", "gpt-4.1"): {
        "supports_reasoning": False,
        "supports_image_input": True,
        "supports_pdf_input": True,
    },
    ("gpt-oss", "gpt-oss-120b"): {
        "supports_reasoning": True,
        "supports_image_input": False,
        "supports_pdf_input": False,
    },
}


def normalize_provider(provider: str | None, model: str | None = None) -> str:
    """Normalize provider aliases and infer a provider when only a model is known."""

    raw = str(provider or "").strip().lower().replace("_", "-")
    if raw in {"openai", "azure-openai"}:
        return "openai"
    if raw in {"mistral", "mistralai"}:
        return "mistral"
    if raw in {"openai-compatible", "openai-compatible-chat", "vllm", "litellm"}:
        return "openai-compatible"
    if raw in {"gpt-oss", "gptoss"}:
        return "gpt-oss"
    if raw in {"ollama", "uoaic"}:
        return "ollama"
    if raw in {"local", "local-llm"}:
        return "local"
    if raw:
        return raw

    model_id = str(model or "").strip().lower()
    if model_id.startswith("gpt-oss"):
        return "gpt-oss"
    if model_id.startswith(("gpt-", "o", "text-embedding")):
        return "openai"
    if "mistral" in model_id or "ministral" in model_id:
        return "mistral"
    if any(token in model_id for token in ("qwen", "deepseek", "llama", "phi")):
        return "ollama"
    return "local"


def default_model_for_provider(provider: str) -> str:
    """Return a conservative default model label for ``provider``."""

    normalized = normalize_provider(provider)
    return _DEFAULT_PROVIDER_MODELS.get(normalized, normalized or "model")


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return None


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _capability_overrides(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    if not raw:
        return {}
    payload: dict[str, Any] = {}
    for key in ("context_window", "max_output_tokens"):
        parsed = _coerce_int(raw.get(key))
        if parsed is not None:
            payload[key] = parsed
    for key in ("supports_reasoning", "supports_image_input", "supports_pdf_input"):
        parsed_bool = _coerce_bool(raw.get(key))
        if parsed_bool is not None:
            payload[key] = parsed_bool
    return payload


def resolve_provider_capability(
    provider: str | None = None,
    model: str | None = None,
    *,
    overrides: Mapping[str, Any] | None = None,
) -> ProviderCapability:
    """Resolve provider/model capability metadata with explicit overrides last."""

    normalized_provider = normalize_provider(provider, model)
    model_id = str(model or "").strip() or default_model_for_provider(normalized_provider)
    payload = dict(_PROVIDER_DEFAULTS.get(normalized_provider, {}))
    source = "provider-default"
    model_payload = _MODEL_OVERRIDES.get((normalized_provider, model_id))
    if model_payload:
        payload.update(model_payload)
        source = "model-default"
    override_payload = _capability_overrides(overrides)
    if override_payload:
        payload.update(override_payload)
        source = "override"

    return ProviderCapability(
        schema=CAPABILITY_SCHEMA,
        provider=normalized_provider,
        model=model_id,
        context_window=payload.get("context_window") if isinstance(payload.get("context_window"), int) else None,
        max_output_tokens=payload.get("max_output_tokens") if isinstance(payload.get("max_output_tokens"), int) else None,
        supports_reasoning=payload.get("supports_reasoning") if isinstance(payload.get("supports_reasoning"), bool) else None,
        supports_image_input=payload.get("supports_image_input") if isinstance(payload.get("supports_image_input"), bool) else None,
        supports_pdf_input=payload.get("supports_pdf_input") if isinstance(payload.get("supports_pdf_input"), bool) else None,
        source=source,
    )
