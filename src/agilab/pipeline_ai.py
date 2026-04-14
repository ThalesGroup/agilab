from __future__ import annotations

import importlib
import importlib.metadata as importlib_metadata
import importlib.util
import logging
import os
import re
import sys
from contextlib import nullcontext
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

from agi_env import AgiEnv, normalize_path
from agi_env.defaults import get_default_openai_model
from agi_env.pagelib import activate_gpt_oss

try:
    from agilab.env_file_utils import load_env_file_map as _load_env_file_map
except ModuleNotFoundError:
    _env_file_utils_path = Path(__file__).resolve().parent / "env_file_utils.py"
    _env_file_utils_spec = importlib.util.spec_from_file_location("agilab_env_file_utils_fallback", _env_file_utils_path)
    if _env_file_utils_spec is None or _env_file_utils_spec.loader is None:
        raise
    _env_file_utils_module = importlib.util.module_from_spec(_env_file_utils_spec)
    _env_file_utils_spec.loader.exec_module(_env_file_utils_module)
    _load_env_file_map = _env_file_utils_module.load_env_file_map

try:
    from agilab.pipeline_openai import (
        ensure_cached_api_key,
        is_placeholder_api_key,
        make_openai_client_and_model,
        prompt_for_openai_api_key,
    )
except ModuleNotFoundError:
    _pipeline_openai_path = Path(__file__).resolve().parent / "pipeline_openai.py"
    _pipeline_openai_spec = importlib.util.spec_from_file_location("agilab_pipeline_openai_fallback", _pipeline_openai_path)
    if _pipeline_openai_spec is None or _pipeline_openai_spec.loader is None:
        raise
    _pipeline_openai_module = importlib.util.module_from_spec(_pipeline_openai_spec)
    _pipeline_openai_spec.loader.exec_module(_pipeline_openai_module)
    ensure_cached_api_key = _pipeline_openai_module.ensure_cached_api_key
    is_placeholder_api_key = _pipeline_openai_module.is_placeholder_api_key
    make_openai_client_and_model = _pipeline_openai_module.make_openai_client_and_model
    prompt_for_openai_api_key = _pipeline_openai_module.prompt_for_openai_api_key

try:
    from agilab.pipeline_steps import pipeline_export_root as _pipeline_export_root
except ModuleNotFoundError:
    _pipeline_steps_path = Path(__file__).resolve().parent / "pipeline_steps.py"
    _pipeline_steps_spec = importlib.util.spec_from_file_location("agilab_pipeline_steps_fallback", _pipeline_steps_path)
    if _pipeline_steps_spec is None or _pipeline_steps_spec.loader is None:
        raise
    _pipeline_steps_module = importlib.util.module_from_spec(_pipeline_steps_spec)
    _pipeline_steps_spec.loader.exec_module(_pipeline_steps_module)
    _pipeline_export_root = _pipeline_steps_module.pipeline_export_root

try:
    from agilab.pipeline_ai_support import (
        CODE_STRICT_INSTRUCTIONS,
        DEFAULT_GPT_OSS_ENDPOINT,
        _API_KEY_PATTERNS,
        normalize_user_path as _normalize_user_path,
        _OLLAMA_CODE_MODEL_RE,
        _BLOCKED_BUILTINS,
        _BLOCKED_DUNDER_ATTRS,
        _BLOCKED_MODULES,
        _SAFE_BUILTINS,
        _UnsafeCodeError,
        extract_code,
        _build_autofix_prompt,
        _exec_code_on_df,
        _validate_code_safety,
        format_uoaic_question as _format_uoaic_question_impl,
        format_for_responses as _format_for_responses,
        _ollama_available_models as _ollama_available_models_impl,
        _ollama_generate as _ollama_generate_impl,
        normalize_gpt_oss_endpoint as _normalize_gpt_oss_endpoint,
        normalize_identifier as _normalize_identifier,
        normalize_ollama_endpoint as _normalize_ollama_endpoint,
        prompt_to_gpt_oss_messages as _prompt_to_gpt_oss_messages,
        prompt_to_plaintext as _prompt_to_plaintext,
        redact_sensitive as _redact_sensitive,
        response_to_text as _response_to_text,
        synthesize_stub_response as _synthesize_stub_response,
    )
except ModuleNotFoundError:
    _pipeline_ai_support_path = Path(__file__).resolve().parent / "pipeline_ai_support.py"
    _pipeline_ai_support_spec = importlib.util.spec_from_file_location(
        "agilab_pipeline_ai_support_fallback",
        _pipeline_ai_support_path,
    )
    if _pipeline_ai_support_spec is None or _pipeline_ai_support_spec.loader is None:
        raise
    _pipeline_ai_support_module = importlib.util.module_from_spec(_pipeline_ai_support_spec)
    _pipeline_ai_support_spec.loader.exec_module(_pipeline_ai_support_module)
    CODE_STRICT_INSTRUCTIONS = _pipeline_ai_support_module.CODE_STRICT_INSTRUCTIONS
    DEFAULT_GPT_OSS_ENDPOINT = _pipeline_ai_support_module.DEFAULT_GPT_OSS_ENDPOINT
    _API_KEY_PATTERNS = _pipeline_ai_support_module._API_KEY_PATTERNS
    _normalize_user_path = _pipeline_ai_support_module.normalize_user_path
    _OLLAMA_CODE_MODEL_RE = _pipeline_ai_support_module._OLLAMA_CODE_MODEL_RE
    _BLOCKED_BUILTINS = _pipeline_ai_support_module._BLOCKED_BUILTINS
    _BLOCKED_DUNDER_ATTRS = _pipeline_ai_support_module._BLOCKED_DUNDER_ATTRS
    _BLOCKED_MODULES = _pipeline_ai_support_module._BLOCKED_MODULES
    _SAFE_BUILTINS = _pipeline_ai_support_module._SAFE_BUILTINS
    _UnsafeCodeError = _pipeline_ai_support_module._UnsafeCodeError
    extract_code = _pipeline_ai_support_module.extract_code
    _build_autofix_prompt = _pipeline_ai_support_module._build_autofix_prompt
    _exec_code_on_df = _pipeline_ai_support_module._exec_code_on_df
    _validate_code_safety = _pipeline_ai_support_module._validate_code_safety
    _format_uoaic_question_impl = _pipeline_ai_support_module.format_uoaic_question
    _format_for_responses = _pipeline_ai_support_module.format_for_responses
    _ollama_available_models_impl = _pipeline_ai_support_module._ollama_available_models
    _ollama_generate_impl = _pipeline_ai_support_module._ollama_generate
    _normalize_gpt_oss_endpoint = _pipeline_ai_support_module.normalize_gpt_oss_endpoint
    _normalize_identifier = _pipeline_ai_support_module.normalize_identifier
    _normalize_ollama_endpoint = _pipeline_ai_support_module.normalize_ollama_endpoint
    _prompt_to_gpt_oss_messages = _pipeline_ai_support_module.prompt_to_gpt_oss_messages
    _prompt_to_plaintext = _pipeline_ai_support_module.prompt_to_plaintext
    _redact_sensitive = _pipeline_ai_support_module.redact_sensitive
    _response_to_text = _pipeline_ai_support_module.response_to_text
    _synthesize_stub_response = _pipeline_ai_support_module.synthesize_stub_response

try:
    from agilab.pipeline_ai_uoaic import (
        UOAIC_AUTOFIX_ENV,
        UOAIC_AUTOFIX_MAX_ENV,
        UOAIC_AUTOFIX_MAX_STATE_KEY,
        UOAIC_AUTOFIX_STATE_KEY,
        UOAIC_DATA_ENV,
        UOAIC_DATA_STATE_KEY,
        UOAIC_DB_ENV,
        UOAIC_DB_STATE_KEY,
        UOAIC_MODE_ENV,
        UOAIC_MODE_OLLAMA,
        UOAIC_MODE_RAG,
        UOAIC_MODE_STATE_KEY,
        UOAIC_MODEL_ENV,
        UOAIC_NUM_CTX_ENV,
        UOAIC_NUM_PREDICT_ENV,
        UOAIC_OLLAMA_ENDPOINT_ENV,
        DEFAULT_UOAIC_BASE,
        UOAIC_PROVIDER,
        UOAIC_DEFAULT_DB_DIRNAME,
        UOAIC_REBUILD_FLAG_KEY,
        UOAIC_RUNTIME_KEY,
        UOAIC_SEED_ENV,
        UOAIC_TEMPERATURE_ENV,
        UOAIC_TOP_P_ENV,
        UoaicControlDeps,
        UoaicRuntimeDeps,
        _normalize_user_path,
        chat_universal_offline as _chat_universal_offline_impl,
        ensure_uoaic_runtime as _ensure_uoaic_runtime_impl,
        load_uoaic_modules as _load_uoaic_modules_impl,
        render_universal_offline_controls as _render_universal_offline_controls_impl,
        resolve_uoaic_path as _resolve_uoaic_path_impl,
    )
except ModuleNotFoundError:
    _pipeline_ai_uoaic_path = Path(__file__).resolve().parent / "pipeline_ai_uoaic.py"
    _pipeline_ai_uoaic_spec = importlib.util.spec_from_file_location(
        "agilab_pipeline_ai_uoaic_fallback",
        _pipeline_ai_uoaic_path,
    )
    if _pipeline_ai_uoaic_spec is None or _pipeline_ai_uoaic_spec.loader is None:
        raise
    _pipeline_ai_uoaic_module = importlib.util.module_from_spec(_pipeline_ai_uoaic_spec)
    _pipeline_ai_uoaic_spec_modules = _pipeline_ai_uoaic_spec.name
    if _pipeline_ai_uoaic_spec_modules is not None:
        import sys

        sys.modules.setdefault(_pipeline_ai_uoaic_spec_modules, _pipeline_ai_uoaic_module)
    _pipeline_ai_uoaic_spec.loader.exec_module(_pipeline_ai_uoaic_module)
    UOAIC_AUTOFIX_ENV = _pipeline_ai_uoaic_module.UOAIC_AUTOFIX_ENV
    UOAIC_AUTOFIX_MAX_ENV = _pipeline_ai_uoaic_module.UOAIC_AUTOFIX_MAX_ENV
    UOAIC_AUTOFIX_MAX_STATE_KEY = _pipeline_ai_uoaic_module.UOAIC_AUTOFIX_MAX_STATE_KEY
    UOAIC_AUTOFIX_STATE_KEY = _pipeline_ai_uoaic_module.UOAIC_AUTOFIX_STATE_KEY
    UOAIC_DATA_ENV = _pipeline_ai_uoaic_module.UOAIC_DATA_ENV
    UOAIC_DATA_STATE_KEY = _pipeline_ai_uoaic_module.UOAIC_DATA_STATE_KEY
    UOAIC_DB_ENV = _pipeline_ai_uoaic_module.UOAIC_DB_ENV
    UOAIC_DB_STATE_KEY = _pipeline_ai_uoaic_module.UOAIC_DB_STATE_KEY
    UOAIC_MODE_ENV = _pipeline_ai_uoaic_module.UOAIC_MODE_ENV
    UOAIC_MODE_OLLAMA = _pipeline_ai_uoaic_module.UOAIC_MODE_OLLAMA
    UOAIC_MODE_RAG = _pipeline_ai_uoaic_module.UOAIC_MODE_RAG
    UOAIC_MODE_STATE_KEY = _pipeline_ai_uoaic_module.UOAIC_MODE_STATE_KEY
    UOAIC_MODEL_ENV = _pipeline_ai_uoaic_module.UOAIC_MODEL_ENV
    UOAIC_NUM_CTX_ENV = _pipeline_ai_uoaic_module.UOAIC_NUM_CTX_ENV
    UOAIC_NUM_PREDICT_ENV = _pipeline_ai_uoaic_module.UOAIC_NUM_PREDICT_ENV
    UOAIC_OLLAMA_ENDPOINT_ENV = _pipeline_ai_uoaic_module.UOAIC_OLLAMA_ENDPOINT_ENV
    DEFAULT_UOAIC_BASE = _pipeline_ai_uoaic_module.DEFAULT_UOAIC_BASE
    UOAIC_PROVIDER = _pipeline_ai_uoaic_module.UOAIC_PROVIDER
    UOAIC_DEFAULT_DB_DIRNAME = _pipeline_ai_uoaic_module.UOAIC_DEFAULT_DB_DIRNAME
    UOAIC_REBUILD_FLAG_KEY = _pipeline_ai_uoaic_module.UOAIC_REBUILD_FLAG_KEY
    UOAIC_RUNTIME_KEY = _pipeline_ai_uoaic_module.UOAIC_RUNTIME_KEY
    UOAIC_SEED_ENV = _pipeline_ai_uoaic_module.UOAIC_SEED_ENV
    UOAIC_TEMPERATURE_ENV = _pipeline_ai_uoaic_module.UOAIC_TEMPERATURE_ENV
    UOAIC_TOP_P_ENV = _pipeline_ai_uoaic_module.UOAIC_TOP_P_ENV
    UoaicControlDeps = _pipeline_ai_uoaic_module.UoaicControlDeps
    UoaicRuntimeDeps = _pipeline_ai_uoaic_module.UoaicRuntimeDeps
    _normalize_user_path = _pipeline_ai_uoaic_module._normalize_user_path
    _chat_universal_offline_impl = _pipeline_ai_uoaic_module.chat_universal_offline
    _ensure_uoaic_runtime_impl = _pipeline_ai_uoaic_module.ensure_uoaic_runtime
    _load_uoaic_modules_impl = _pipeline_ai_uoaic_module.load_uoaic_modules
    _render_universal_offline_controls_impl = _pipeline_ai_uoaic_module.render_universal_offline_controls
    _resolve_uoaic_path_impl = _pipeline_ai_uoaic_module.resolve_uoaic_path

try:
    from agilab.pipeline_ai_controls import (
        PipelineAiControlDeps,
        configure_assistant_engine as _configure_assistant_engine_impl,
        gpt_oss_controls as _gpt_oss_controls_impl,
    )
except ModuleNotFoundError:
    _pipeline_ai_controls_path = Path(__file__).resolve().parent / "pipeline_ai_controls.py"
    _pipeline_ai_controls_spec = importlib.util.spec_from_file_location(
        "agilab_pipeline_ai_controls_fallback",
        _pipeline_ai_controls_path,
    )
    if _pipeline_ai_controls_spec is None or _pipeline_ai_controls_spec.loader is None:
        raise
    _pipeline_ai_controls_module = importlib.util.module_from_spec(_pipeline_ai_controls_spec)
    sys.modules[_pipeline_ai_controls_spec.name] = _pipeline_ai_controls_module
    _pipeline_ai_controls_spec.loader.exec_module(_pipeline_ai_controls_module)
    PipelineAiControlDeps = _pipeline_ai_controls_module.PipelineAiControlDeps
    _configure_assistant_engine_impl = _pipeline_ai_controls_module.configure_assistant_engine
    _gpt_oss_controls_impl = _pipeline_ai_controls_module.gpt_oss_controls

logger = logging.getLogger(__name__)
JumpToMain = RuntimeError


@st.cache_data(show_spinner=False)
def _ollama_available_models(endpoint: str) -> List[str]:
    return _ollama_available_models_impl(endpoint)


def _default_ollama_model(
    endpoint: str,
    *,
    preferred: str = "mistral:instruct",
    prefer_code: bool = False,
) -> str:
    models = _ollama_available_models(endpoint)
    if models and prefer_code:
        for name in models:
            if _OLLAMA_CODE_MODEL_RE.search(name):
                return name
    if preferred and preferred in models:
        return preferred
    if models:
        return models[0]
    return preferred


def _ollama_generate(
    *,
    endpoint: str,
    model: str,
    prompt: str,
    temperature: float = 0.1,
    top_p: float = 0.9,
    num_ctx: Optional[int] = None,
    num_predict: Optional[int] = None,
    seed: Optional[int] = None,
    timeout_s: float = 120.0,
) -> str:
    return _ollama_generate_impl(
        endpoint=endpoint,
        model=model,
        prompt=prompt,
        temperature=temperature,
        top_p=top_p,
        num_ctx=num_ctx,
        num_predict=num_predict,
        seed=seed,
        timeout_s=timeout_s,
        endpoint_var_name=UOAIC_OLLAMA_ENDPOINT_ENV,
    )


def chat_ollama_local(
    input_request: str,
    prompt: List[Dict[str, str]],
    envars: Dict[str, str],
) -> Tuple[str, str]:
    """Call a local Ollama model for code generation."""
    endpoint = _normalize_ollama_endpoint(
        envars.get(UOAIC_OLLAMA_ENDPOINT_ENV)
        or os.getenv(UOAIC_OLLAMA_ENDPOINT_ENV)
        or os.getenv("OLLAMA_HOST")
    )
    fallback_model = _default_ollama_model(endpoint, prefer_code=True)
    model = (envars.get(UOAIC_MODEL_ENV) or os.getenv(UOAIC_MODEL_ENV) or fallback_model).strip()
    if not model:
        st.error("Set an Ollama model name to use the local assistant (see `ollama list`).")
        raise JumpToMain(ValueError("Missing Ollama model"))

    def _float_env(name: str, default: float) -> float:
        raw = envars.get(name) or os.getenv(name)
        try:
            return float(raw) if raw is not None and str(raw).strip() else float(default)
        except (TypeError, ValueError):
            return float(default)

    def _int_env(name: str) -> Optional[int]:
        raw = envars.get(name) or os.getenv(name)
        if raw is None or not str(raw).strip():
            return None
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return None

    temperature = _float_env(UOAIC_TEMPERATURE_ENV, 0.1)
    top_p = _float_env(UOAIC_TOP_P_ENV, 0.9)
    num_ctx = _int_env(UOAIC_NUM_CTX_ENV)
    num_predict = _int_env(UOAIC_NUM_PREDICT_ENV)
    seed = _int_env(UOAIC_SEED_ENV)

    history = _prompt_to_plaintext(prompt, input_request)
    full_prompt = f"{CODE_STRICT_INSTRUCTIONS}\n\n{history}"

    try:
        text = _ollama_generate(
            endpoint=endpoint,
            model=model,
            prompt=full_prompt,
            temperature=temperature,
            top_p=top_p,
            num_ctx=num_ctx,
            num_predict=num_predict,
            seed=seed,
        )
    except RuntimeError as exc:
        st.error(str(exc))
        raise JumpToMain(exc)

    return text, model

ENV_FILE_PATH = Path.home() / ".agilab/.env"


def _format_uoaic_question(prompt: List[Dict[str, str]], question: str) -> str:
    """Compatibility wrapper for legacy callers kept in tests and callers."""
    return _format_uoaic_question_impl(prompt, question)


def chat_offline(
    input_request: str,
    prompt: List[Dict[str, str]],
    envars: Dict[str, str],
) -> Tuple[str, str]:
    """Call the GPT-OSS Responses API endpoint configured for offline use."""

    try:
        import requests  # type: ignore
    except ImportError as exc:  # pragma: no cover - optional dependency
        st.error("`requests` is required for GPT-OSS offline mode. Install it with `pip install requests`." )
        raise JumpToMain(exc)

    endpoint = _normalize_gpt_oss_endpoint(
        envars.get("GPT_OSS_ENDPOINT")
        or os.getenv("GPT_OSS_ENDPOINT")
        or st.session_state.get("gpt_oss_endpoint")
    )
    envars["GPT_OSS_ENDPOINT"] = endpoint

    instructions, items = _prompt_to_gpt_oss_messages(prompt, input_request)
    payload: Dict[str, Any] = {
        "model": envars.get("GPT_OSS_MODEL", "gpt-oss-120b"),
        "input": items,
        "temperature": float(envars.get("GPT_OSS_TEMPERATURE", 0.0) or 0.0),
        "stream": False,
        "reasoning": {"effort": envars.get("GPT_OSS_REASONING", "low")},
    }
    if instructions:
        payload["instructions"] = instructions

    timeout = float(envars.get("GPT_OSS_TIMEOUT", 60))
    model_name = str(payload.get("model", ""))
    try:
        response = requests.post(endpoint, json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as exc:
        st.error(
            "Failed to reach GPT-OSS at {endpoint}. Start it with `python -m gpt_oss.responses_api.serve --inference-backend stub --port 8000` or configure `GPT_OSS_ENDPOINT`.".format(
                endpoint=endpoint
            )
        )
        raise JumpToMain(exc)
    except ValueError as exc:
        st.error("GPT-OSS returned an invalid JSON payload.")
        raise JumpToMain(exc)

    # The Responses API returns a dictionary; reuse helper to extract text.
    text = ""
    if isinstance(data, dict):
        try:
            from gpt_oss.responses_api.types import ResponseObject

            text = _response_to_text(ResponseObject.model_validate(data))
        except (ImportError, AttributeError, TypeError, ValueError):
            # Best-effort extraction for plain dicts.
            output = data.get("output", []) if isinstance(data, dict) else []
            chunks = []
            for item in output:
                if isinstance(item, dict) and item.get("type") == "message":
                    for part in item.get("content", []) or []:
                        if isinstance(part, dict) and part.get("text"):
                            chunks.append(str(part.get("text")))
            text = "\n".join(chunks).strip()

    text = text.strip()
    backend_hint = (
        st.session_state.get("gpt_oss_backend_active")
        or st.session_state.get("gpt_oss_backend")
        or envars.get("GPT_OSS_BACKEND")
        or os.getenv("GPT_OSS_BACKEND")
        or "stub"
    ).lower()
    if backend_hint == "stub" and (not text or "2 + 2 = 4" in text):
        return _synthesize_stub_response(input_request), model_name

    return text, model_name

def _ensure_uoaic_runtime(envars: Dict[str, str]) -> Dict[str, Any]:
    env: Optional[AgiEnv] = st.session_state.get("env")
    try:
        return _ensure_uoaic_runtime_impl(
            envars,
            env=env,
            deps=UoaicRuntimeDeps(
                session_state=st.session_state,
                normalize_path_fn=normalize_path,
                pipeline_export_root_fn=_pipeline_export_root,
                load_modules_fn=_load_uoaic_modules,
                error_sink=st.error,
                spinner_factory=getattr(st, "spinner", nullcontext),
            ),
            resolve_uoaic_path_fn=lambda raw_path, _env: _resolve_uoaic_path(raw_path, _env),
        )
    except (RuntimeError, ValueError) as exc:
        if str(exc) == "Missing Universal Offline data directory":
            st.error("Configure the Universal Offline data directory in the sidebar to enable this provider.")
        else:
            st.error(str(exc))
        if isinstance(exc, ValueError):
            raise JumpToMain(str(exc)) from exc
        raise JumpToMain(exc)


def _resolve_uoaic_path(raw_path: str, env: Optional[AgiEnv]) -> Path:
    return _resolve_uoaic_path_impl(raw_path, env, pipeline_export_root_fn=_pipeline_export_root)


def _load_uoaic_modules(
    *,
    distribution_fn: Callable[[str], Any] | None = None,
    import_module_fn: Callable[[str], Any] | None = None,
    spec_from_file_location_fn: Callable[[str, str], Any] | None = None,
    module_from_spec_fn: Callable[[Any], Any] | None = None,
) -> Tuple[Any, ...]:
    if distribution_fn is None:
        distribution_fn = importlib_metadata.distribution
    if import_module_fn is None:
        import_module_fn = importlib.import_module
    if spec_from_file_location_fn is None:
        spec_from_file_location_fn = importlib.util.spec_from_file_location
    if module_from_spec_fn is None:
        module_from_spec_fn = importlib.util.module_from_spec
    try:
        return _load_uoaic_modules_impl(
            distribution_fn=distribution_fn,
            import_module_fn=import_module_fn,
            spec_from_file_location_fn=spec_from_file_location_fn,
            module_from_spec_fn=module_from_spec_fn,
        )
    except RuntimeError as exc:
        st.error(str(exc))
        raise JumpToMain(exc)


def chat_universal_offline(
    input_request: str,
    prompt: List[Dict[str, str]],
    envars: Dict[str, str],
) -> Tuple[str, str]:
    try:
        return _chat_universal_offline_impl(
            input_request,
            prompt,
            envars,
            ensure_runtime_fn=_ensure_uoaic_runtime,
            error_sink=st.error,
        )
    except RuntimeError as exc:
        raise JumpToMain(exc) from exc


def chat_online(
    input_request: str,
    prompt: List[Dict[str, str]],
    envars: Dict[str, str],
) -> Tuple[str, str]:
    """Robust Chat Completions call: OpenAI, Azure OpenAI, or proxy base_url."""
    import openai

    # Refresh envars from the latest .env so model/key changes take effect without restart.
    env_file_map = _load_env_file_map(ENV_FILE_PATH)
    if env_file_map:
        envars.update(env_file_map)

    api_key = ensure_cached_api_key(envars)
    if not api_key or is_placeholder_api_key(api_key):
        prompt_for_openai_api_key(
            "OpenAI API key appears missing or redacted. Supply a valid key to continue."
        )
        raise JumpToMain(ValueError("OpenAI API key unavailable"))

    # Persist to session + envars to survive reruns
    st.session_state["openai_api_key"] = api_key
    envars["OPENAI_API_KEY"] = api_key

    # Build messages
    system_msg = {
        "role": "system",
        "content": (
            "Return ONLY Python code wrapped in ```python ... ``` with no explanations. "
            "Assume there is a pandas DataFrame df and pandas is imported as pd."
        ),
    }
    messages: List[Dict[str, str]] = [system_msg]
    for item in prompt:
        role = item.get("role", "assistant")
        content = str(item.get("content", ""))
        if content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": input_request})

    # Create client (supports OpenAI/Azure/proxy)
    try:
        client, model_name, is_azure = make_openai_client_and_model(envars, api_key)
    except (RuntimeError, TypeError, ValueError, AttributeError, ImportError, OSError) as e:
        st.error("Failed to initialise OpenAI/Azure client. Check your SDK install and environment variables.")
        logger.error(f"Client init error: {_redact_sensitive(str(e))}")
        raise JumpToMain(e)

    # Call – support new and old SDKs
    try:
        # New-style client returns objects; old SDK returns dicts
        if hasattr(client, "chat") and hasattr(client.chat, "completions"):
            resp = client.chat.completions.create(model=model_name, messages=messages)
            content = resp.choices[0].message.content
        else:
            # Old SDK (module-style)
            resp = client.ChatCompletion.create(model=model_name, messages=messages)
            content = resp["choices"][0]["message"]["content"]

        return content or "", str(model_name)

    except openai.OpenAIError as e:
        # Don’t re-prompt for key here; surface the *actual* problem.
        msg = _redact_sensitive(str(e))
        status = getattr(e, "status_code", None) or getattr(e, "status", None)
        if status == 404 or "model_not_found" in msg or "does not exist" in msg:
            st.info(
                "The requested model is unavailable. Please select a different model in the LLM provider settings "
                "or update the model name in the Environment Variables expander (OPENAI_MODEL/AZURE deployment)."
            )
            logger.info(f"Model not found/unavailable: {msg}")
        elif status in (401, 403):
            # Most common causes:
            # - Azure key used without proper Azure endpoint/version/deployment
            # - Wrong org / no access to model
            # - Proxy/base_url misconfigured
            st.error(
                "Authentication/authorization failed.\n\n"
                "Common causes:\n"
                "• Using an **Azure OpenAI** key but missing `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_API_VERSION` / deployment name.\n"
                "• Using a **gateway/proxy** but missing `OPENAI_BASE_URL`.\n"
                "• The key doesn’t have access to the requested model/deployment.\n\n"
                f"Details: {msg}"
            )
        else:
            st.error(f"OpenAI/Azure error: {msg}")
        logger.error(f"OpenAI error: {msg}")
        raise JumpToMain(e)
    except (RuntimeError, TypeError, ValueError, AttributeError, KeyError, IndexError) as e:
        msg = _redact_sensitive(str(e))
        st.error(f"Unexpected client error: {msg}")
        logger.error(f"General error in chat_online: {msg}")
        raise JumpToMain(e)


def ask_gpt(
    question: str,
    df_file: Path,
    index_page: str,
    envars: Dict[str, str],
) -> List[Any]:
    """Send a question to GPT and get the response."""
    prompt = st.session_state.get("lab_prompt", [])
    provider = st.session_state.get(
        "lab_llm_provider",
        envars.get("LAB_LLM_PROVIDER", "openai"),
    )
    model_label = ""
    if provider == "gpt-oss":
        result, model_label = chat_offline(question, prompt, envars)
    elif provider == UOAIC_PROVIDER:
        mode = (
            st.session_state.get(UOAIC_MODE_STATE_KEY)
            or envars.get(UOAIC_MODE_ENV)
            or os.getenv(UOAIC_MODE_ENV)
            or UOAIC_MODE_OLLAMA
        )
        if mode == UOAIC_MODE_RAG:
            result, model_label = chat_universal_offline(question, prompt, envars)
        else:
            result, model_label = chat_ollama_local(question, prompt, envars)
    else:
        result, model_label = chat_online(question, prompt, envars)

    model_label = str(model_label or "")
    if not result:
        return [df_file, question, model_label, "", ""]

    code, detail = extract_code(result)
    detail = detail or ("" if code else result.strip())
    return [
        df_file,
        question,
        model_label,
        code.strip() if code else "",
        detail,
    ]


def _maybe_autofix_generated_code(
    *,
    original_request: str,
    df_path: Path,
    index_page: str,
    env: AgiEnv,
    merged_code: str,
    model_label: str,
    detail: str,
    load_df_cached: Any,
    push_run_log: Any,
    get_run_placeholder: Any,
) -> Tuple[str, str, str]:
    """Optionally run + repair generated code using the active assistant."""
    provider = st.session_state.get("lab_llm_provider") or env.envars.get("LAB_LLM_PROVIDER", "openai")
    if provider != UOAIC_PROVIDER:
        return merged_code, model_label, detail

    enabled = bool(st.session_state.get(UOAIC_AUTOFIX_STATE_KEY, False))
    if not enabled:
        enabled_env = (env.envars.get(UOAIC_AUTOFIX_ENV) or os.getenv(UOAIC_AUTOFIX_ENV) or "").strip().lower()
        enabled = enabled_env in {"1", "true", "yes", "on"}
    if not enabled:
        return merged_code, model_label, detail

    try:
        max_attempts = int(st.session_state.get(UOAIC_AUTOFIX_MAX_STATE_KEY, 2))
    except (TypeError, ValueError):
        max_attempts = 2
    if max_attempts <= 0:
        return merged_code, model_label, detail

    df: Any = st.session_state.get("loaded_df")
    if not isinstance(df, pd.DataFrame) or df.empty:
        df_file = st.session_state.get("df_file")
        if df_file:
            df = load_df_cached(Path(df_file))

    if not isinstance(df, pd.DataFrame) or df.empty:
        push_run_log(index_page, "Auto-fix skipped: no dataframe is loaded.", get_run_placeholder(index_page))
        return merged_code, model_label, detail

    placeholder = get_run_placeholder(index_page)
    _, err = _exec_code_on_df(merged_code, df)
    if not err:
        push_run_log(index_page, "Auto-fix: generated code validated successfully.", placeholder)
        return merged_code, model_label, detail

    push_run_log(index_page, f"Auto-fix: initial execution failed.\n{err}", placeholder)
    current_code = merged_code
    current_model = model_label
    current_detail = detail
    current_err = err

    for attempt in range(1, max_attempts + 1):
        fix_question = _build_autofix_prompt(
            original_request=original_request,
            failing_code=current_code,
            traceback_text=current_err,
            attempt=attempt,
        )
        fix_answer = ask_gpt(fix_question, df_path, index_page, env.envars)
        fix_code = fix_answer[3] if len(fix_answer) > 3 else ""
        fix_detail = (fix_answer[4] or "").strip() if len(fix_answer) > 4 else ""
        fix_model = str(fix_answer[2] or "") if len(fix_answer) > 2 else current_model
        if not fix_code.strip():
            push_run_log(index_page, f"Auto-fix attempt {attempt}: model returned no code.", placeholder)
            break

        candidate = f"# {fix_detail}\n{fix_code}".strip() if fix_detail else fix_code.strip()
        _, candidate_err = _exec_code_on_df(candidate, df)
        if not candidate_err:
            push_run_log(index_page, f"Auto-fix: success on attempt {attempt}.", placeholder)
            return candidate, fix_model, fix_detail

        summary = candidate_err.strip().splitlines()[-1] if candidate_err.strip() else "Unknown error"
        push_run_log(index_page, f"Auto-fix attempt {attempt} failed: {summary}", placeholder)
        current_code = candidate
        current_model = fix_model
        current_detail = fix_detail
        current_err = candidate_err

    push_run_log(index_page, "Auto-fix failed; keeping the last generated code.", placeholder)
    return current_code, current_model, current_detail


def configure_assistant_engine(env: AgiEnv) -> str:
    """Render assistant-provider controls and persist provider-specific settings."""
    return _configure_assistant_engine_impl(
        env,
        deps=PipelineAiControlDeps(
            session_state=st.session_state,
            sidebar=st.sidebar,
            activate_gpt_oss_fn=activate_gpt_oss,
            get_default_openai_model_fn=get_default_openai_model,
        ),
        uoaic_provider=UOAIC_PROVIDER,
        uoaic_runtime_key=UOAIC_RUNTIME_KEY,
    )



def gpt_oss_controls(env: AgiEnv) -> None:
    """Ensure GPT-OSS responses service is reachable and provide quick controls."""
    _gpt_oss_controls_impl(
        env,
        deps=PipelineAiControlDeps(
            session_state=st.session_state,
            sidebar=st.sidebar,
            activate_gpt_oss_fn=activate_gpt_oss,
            get_default_openai_model_fn=get_default_openai_model,
        ),
    )


def universal_offline_controls(env: AgiEnv) -> None:
    _render_universal_offline_controls_impl(
        env,
        deps=UoaicControlDeps(
            session_state=st.session_state,
            sidebar=st.sidebar,
            normalize_path_fn=normalize_path,
            default_ollama_model_fn=_default_ollama_model,
            ensure_runtime_fn=_ensure_uoaic_runtime,
            normalize_user_path_fn=_normalize_user_path,
            spinner_factory=getattr(st, "spinner", nullcontext),
        ),
    )
