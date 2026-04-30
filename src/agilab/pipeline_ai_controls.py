from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any, Callable

import streamlit as st  # noqa: F401 - imported for parity with the broader UI modules

from agi_env import AgiEnv
from agi_env.defaults import get_default_openai_model
from agi_gui.pagelib import activate_gpt_oss

_import_guard_path = Path(__file__).resolve().parent / "import_guard.py"
_import_guard_spec = importlib.util.spec_from_file_location("agilab_import_guard_local", _import_guard_path)
if _import_guard_spec is None or _import_guard_spec.loader is None:
    raise ModuleNotFoundError(f"Unable to load import_guard.py from {_import_guard_path}")
_import_guard_module = importlib.util.module_from_spec(_import_guard_spec)
_import_guard_spec.loader.exec_module(_import_guard_module)
import_agilab_module = _import_guard_module.import_agilab_module

_pipeline_ai_uoaic_module = import_agilab_module(
    "agilab.pipeline_ai_uoaic",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "pipeline_ai_uoaic.py",
    fallback_name="agilab_pipeline_ai_uoaic_fallback",
)
UOAIC_MODE_ENV = _pipeline_ai_uoaic_module.UOAIC_MODE_ENV
UOAIC_MODE_OLLAMA = _pipeline_ai_uoaic_module.UOAIC_MODE_OLLAMA
UOAIC_MODE_STATE_KEY = _pipeline_ai_uoaic_module.UOAIC_MODE_STATE_KEY
UOAIC_MODEL_ENV = _pipeline_ai_uoaic_module.UOAIC_MODEL_ENV
UOAIC_OLLAMA_ENDPOINT_ENV = _pipeline_ai_uoaic_module.UOAIC_OLLAMA_ENDPOINT_ENV
UOAIC_PROVIDER = _pipeline_ai_uoaic_module.UOAIC_PROVIDER
UOAIC_RUNTIME_KEY = _pipeline_ai_uoaic_module.UOAIC_RUNTIME_KEY

_pipeline_mistral_module = import_agilab_module(
    "agilab.pipeline_mistral",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "pipeline_mistral.py",
    fallback_name="agilab_pipeline_mistral_fallback",
)
MISTRAL_DEFAULT_MODEL = _pipeline_mistral_module.MISTRAL_DEFAULT_MODEL
MISTRAL_DEFAULT_REASONING_EFFORT = _pipeline_mistral_module.MISTRAL_DEFAULT_REASONING_EFFORT
MISTRAL_MODEL_ENV = _pipeline_mistral_module.MISTRAL_MODEL_ENV
MISTRAL_PROVIDER = _pipeline_mistral_module.MISTRAL_PROVIDER
MISTRAL_REASONING_EFFORT_ENV = _pipeline_mistral_module.MISTRAL_REASONING_EFFORT_ENV
MISTRAL_TEMPERATURE_ENV = _pipeline_mistral_module.MISTRAL_TEMPERATURE_ENV

_pipeline_ai_support_module = import_agilab_module(
    "agilab.pipeline_ai_support",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "pipeline_ai_support.py",
    fallback_name="agilab_pipeline_ai_support_fallback",
)
OLLAMA_DEEPSEEK_PROVIDER = _pipeline_ai_support_module.OLLAMA_DEEPSEEK_PROVIDER
OLLAMA_QWEN_PROVIDER = _pipeline_ai_support_module.OLLAMA_QWEN_PROVIDER
default_ollama_family_model = _pipeline_ai_support_module.default_ollama_family_model
normalize_ollama_endpoint = _pipeline_ai_support_module.normalize_ollama_endpoint
ollama_model_matches_family = _pipeline_ai_support_module.ollama_model_matches_family


class PipelineAiControlDeps:
    def __init__(
        self,
        *,
        session_state: Any,
        sidebar: Any,
        activate_gpt_oss_fn: Callable[[AgiEnv], bool] = activate_gpt_oss,
        get_default_openai_model_fn: Callable[[], str] = get_default_openai_model,
    ) -> None:
        self.session_state = session_state
        self.sidebar = sidebar
        self.activate_gpt_oss_fn = activate_gpt_oss_fn
        self.get_default_openai_model_fn = get_default_openai_model_fn


def configure_assistant_engine(
    env: AgiEnv,
    *,
    deps: PipelineAiControlDeps,
    uoaic_provider: str = UOAIC_PROVIDER,
    uoaic_runtime_key: str = UOAIC_RUNTIME_KEY,
) -> str:
    """Render assistant-provider controls and persist provider-specific settings."""
    local_family_providers = {
        "Qwen (local)": OLLAMA_QWEN_PROVIDER,
        "DeepSeek (local)": OLLAMA_DEEPSEEK_PROVIDER,
    }
    provider_options = {
        "OpenAI (online)": "openai",
        "Mistral Medium 3.5 (online)": MISTRAL_PROVIDER,
        "GPT-OSS (local)": "gpt-oss",
        **local_family_providers,
        "Ollama (local)": uoaic_provider,
    }
    provider_families = {
        OLLAMA_QWEN_PROVIDER: "qwen",
        OLLAMA_DEEPSEEK_PROVIDER: "deepseek",
    }
    stored_provider = deps.session_state.get("lab_llm_provider")
    current_provider = stored_provider or env.envars.get("LAB_LLM_PROVIDER", "openai")
    provider_labels = list(provider_options.keys())
    provider_to_label = {v: k for k, v in provider_options.items()}
    current_label = provider_to_label.get(current_provider, provider_labels[0])
    current_index = provider_labels.index(current_label) if current_label in provider_labels else 0
    selected_label = deps.sidebar.selectbox(
        "Assistant engine",
        provider_labels,
        index=current_index,
    )
    selected_provider = provider_options[selected_label]
    previous_provider = deps.session_state.get("lab_llm_provider")
    deps.session_state["lab_llm_provider"] = selected_provider
    env.envars["LAB_LLM_PROVIDER"] = selected_provider
    if previous_provider != selected_provider and previous_provider == uoaic_provider:
        deps.session_state.pop(uoaic_runtime_key, None)
    if previous_provider != selected_provider:
        index_page = deps.session_state.get("index_page") or deps.session_state.get("lab_dir")
        if index_page is not None:
            index_page_str = str(index_page)
            row = deps.session_state.get(index_page_str)
            if isinstance(row, list) and len(row) > 3:
                row[3] = ""
        deps.session_state.setdefault("_experiment_reload_required", True)

        if selected_provider == "openai":
            env.envars["OPENAI_MODEL"] = deps.get_default_openai_model_fn()
        elif selected_provider == MISTRAL_PROVIDER:
            env.envars.pop("OPENAI_MODEL", None)
            model = str(
                deps.session_state.get("mistral_model")
                or env.envars.get(MISTRAL_MODEL_ENV)
                or os.getenv(MISTRAL_MODEL_ENV, MISTRAL_DEFAULT_MODEL)
            ).strip() or MISTRAL_DEFAULT_MODEL
            deps.session_state["mistral_model"] = model
            env.envars[MISTRAL_MODEL_ENV] = model
            env.envars.setdefault(MISTRAL_REASONING_EFFORT_ENV, MISTRAL_DEFAULT_REASONING_EFFORT)
        elif selected_provider == "gpt-oss":
            oss_model = (
                deps.session_state.get("gpt_oss_model")
                or env.envars.get("GPT_OSS_MODEL")
                or os.getenv("GPT_OSS_MODEL", "gpt-oss-120b")
            )
            env.envars["OPENAI_MODEL"] = oss_model
        else:
            env.envars.pop("OPENAI_MODEL", None)
            if selected_provider in provider_families:
                deps.session_state[UOAIC_MODE_STATE_KEY] = UOAIC_MODE_OLLAMA
                env.envars[UOAIC_MODE_ENV] = UOAIC_MODE_OLLAMA
                endpoint = normalize_ollama_endpoint(
                    deps.session_state.get("uoaic_ollama_endpoint")
                    or env.envars.get(UOAIC_OLLAMA_ENDPOINT_ENV)
                    or os.getenv(UOAIC_OLLAMA_ENDPOINT_ENV, "")
                )
                family = provider_families[selected_provider]
                local_model = str(
                    deps.session_state.get("uoaic_model")
                    or env.envars.get(UOAIC_MODEL_ENV)
                    or os.getenv(UOAIC_MODEL_ENV, "")
                ).strip()
                if not ollama_model_matches_family(local_model, family):
                    local_model = default_ollama_family_model(
                        endpoint,
                        family=family,
                        prefer_code=True,
                    )
                deps.session_state["uoaic_model"] = local_model
                if local_model:
                    env.envars[UOAIC_MODEL_ENV] = local_model
                else:
                    env.envars.pop(UOAIC_MODEL_ENV, None)

    if selected_provider == "gpt-oss":
        default_endpoint = (
            deps.session_state.get("gpt_oss_endpoint")
            or env.envars.get("GPT_OSS_ENDPOINT")
            or os.getenv("GPT_OSS_ENDPOINT", "http://127.0.0.1:8000")
        )
        endpoint = deps.sidebar.text_input(
            "GPT-OSS endpoint",
            value=default_endpoint,
            help="Point to a running GPT-OSS responses API (e.g. start with `python -m gpt_oss.responses_api.serve --inference-backend stub --port 8000`).",
        ).strip() or default_endpoint
        deps.session_state["gpt_oss_endpoint"] = endpoint
        env.envars["GPT_OSS_ENDPOINT"] = endpoint
    else:
        deps.session_state.pop("gpt_oss_endpoint", None)

    if selected_provider == MISTRAL_PROVIDER:
        default_model = str(
            deps.session_state.get("mistral_model")
            or env.envars.get(MISTRAL_MODEL_ENV)
            or os.getenv(MISTRAL_MODEL_ENV, MISTRAL_DEFAULT_MODEL)
        ).strip() or MISTRAL_DEFAULT_MODEL
        model = deps.sidebar.text_input(
            "Mistral model",
            value=default_model,
        ).strip() or MISTRAL_DEFAULT_MODEL
        deps.session_state["mistral_model"] = model
        env.envars[MISTRAL_MODEL_ENV] = model

        reasoning_options = ["high", "none"]
        default_reasoning = str(
            deps.session_state.get("mistral_reasoning_effort")
            or env.envars.get(MISTRAL_REASONING_EFFORT_ENV)
            or os.getenv(MISTRAL_REASONING_EFFORT_ENV, MISTRAL_DEFAULT_REASONING_EFFORT)
        ).strip().lower()
        if default_reasoning not in reasoning_options:
            default_reasoning = MISTRAL_DEFAULT_REASONING_EFFORT
        reasoning = deps.sidebar.selectbox(
            "Mistral reasoning",
            reasoning_options,
            index=reasoning_options.index(default_reasoning),
        )
        deps.session_state["mistral_reasoning_effort"] = reasoning
        env.envars[MISTRAL_REASONING_EFFORT_ENV] = reasoning

        default_temperature = str(
            deps.session_state.get("mistral_temperature")
            or env.envars.get(MISTRAL_TEMPERATURE_ENV)
            or os.getenv(MISTRAL_TEMPERATURE_ENV)
            or ("0.7" if reasoning == "high" else "0.1")
        )
        temperature = deps.sidebar.text_input(
            "Mistral temperature",
            value=default_temperature,
        ).strip()
        if temperature:
            deps.session_state["mistral_temperature"] = temperature
            env.envars[MISTRAL_TEMPERATURE_ENV] = temperature
        else:
            deps.session_state.pop("mistral_temperature", None)
            env.envars.pop(MISTRAL_TEMPERATURE_ENV, None)

    return selected_provider


def gpt_oss_controls(
    env: AgiEnv,
    *,
    deps: PipelineAiControlDeps,
) -> None:
    """Ensure GPT-OSS responses service is reachable and provide quick controls."""
    if deps.session_state.get("lab_llm_provider") != "gpt-oss":
        return

    endpoint = (
        deps.session_state.get("gpt_oss_endpoint")
        or env.envars.get("GPT_OSS_ENDPOINT")
        or os.getenv("GPT_OSS_ENDPOINT", "")
    )
    backend_choices = ["stub", "transformers", "metal", "triton", "ollama", "vllm"]
    backend_default = (
        deps.session_state.get("gpt_oss_backend")
        or env.envars.get("GPT_OSS_BACKEND")
        or os.getenv("GPT_OSS_BACKEND")
        or "stub"
    )
    if backend_default not in backend_choices:
        backend_choices = [backend_default] + [opt for opt in backend_choices if opt != backend_default]
    backend = deps.sidebar.selectbox(
        "GPT-OSS backend",
        backend_choices,
        index=backend_choices.index(backend_default if backend_default in backend_choices else backend_choices[0]),
        help="Select the inference backend for a local GPT-OSS server. "
             "Use 'transformers' for Hugging Face checkpoints or leave on 'stub' for a mock service.",
    )
    deps.session_state["gpt_oss_backend"] = backend
    env.envars["GPT_OSS_BACKEND"] = backend
    if deps.session_state.get("gpt_oss_server_started") and deps.session_state.get("gpt_oss_backend_active") not in (None, backend):
        deps.sidebar.warning("Restart GPT-OSS server to apply the new backend.")

    checkpoint_default = (
        deps.session_state.get("gpt_oss_checkpoint")
        or env.envars.get("GPT_OSS_CHECKPOINT")
        or os.getenv("GPT_OSS_CHECKPOINT")
        or ("gpt2" if backend == "transformers" else "")
    )
    checkpoint = deps.sidebar.text_input(
        "GPT-OSS checkpoint / model",
        value=checkpoint_default,
        help="Provide a Hugging Face model ID or local checkpoint path when using a local backend.",
    ).strip()
    if checkpoint:
        deps.session_state["gpt_oss_checkpoint"] = checkpoint
        env.envars["GPT_OSS_CHECKPOINT"] = checkpoint
    else:
        deps.session_state.pop("gpt_oss_checkpoint", None)
        env.envars.pop("GPT_OSS_CHECKPOINT", None)

    extra_args_default = (
        deps.session_state.get("gpt_oss_extra_args")
        or env.envars.get("GPT_OSS_EXTRA_ARGS")
        or os.getenv("GPT_OSS_EXTRA_ARGS")
        or ""
    )
    extra_args = deps.sidebar.text_input(
        "GPT-OSS extra flags",
        value=extra_args_default,
        help="Optional additional flags appended to the launch command (e.g. `--temperature 0.1`).",
    ).strip()
    if extra_args:
        deps.session_state["gpt_oss_extra_args"] = extra_args
        env.envars["GPT_OSS_EXTRA_ARGS"] = extra_args
    else:
        deps.session_state.pop("gpt_oss_extra_args", None)
        env.envars.pop("GPT_OSS_EXTRA_ARGS", None)

    if deps.session_state.get("gpt_oss_server_started"):
        active_checkpoint = deps.session_state.get("gpt_oss_checkpoint_active", "")
        active_extra = deps.session_state.get("gpt_oss_extra_args_active", "")
        if checkpoint != active_checkpoint or extra_args != active_extra:
            deps.sidebar.warning("Restart GPT-OSS server to apply updated checkpoint or flags.")

    auto_local = endpoint.startswith("http://127.0.0.1") or endpoint.startswith("http://localhost")
    autostart_failed = deps.session_state.get("gpt_oss_autostart_failed")

    if auto_local and not deps.session_state.get("gpt_oss_server_started") and not autostart_failed:
        if deps.activate_gpt_oss_fn(env):
            endpoint = deps.session_state.get("gpt_oss_endpoint", endpoint)

    if deps.session_state.get("gpt_oss_server_started"):
        endpoint = deps.session_state.get("gpt_oss_endpoint", endpoint)
        backend_active = deps.session_state.get("gpt_oss_backend_active", backend)
        deps.sidebar.success(f"GPT-OSS server running ({backend_active}) at {endpoint}")
        return

    if deps.sidebar.button("Start GPT-OSS server", key="gpt_oss_start_btn"):
        if deps.activate_gpt_oss_fn(env):
            endpoint = deps.session_state.get("gpt_oss_endpoint", endpoint)
            backend_active = deps.session_state.get("gpt_oss_backend_active", backend)
            deps.sidebar.success(f"GPT-OSS server running ({backend_active}) at {endpoint}")
            return

    if endpoint:
        deps.sidebar.info(f"Using GPT-OSS endpoint: {endpoint}")
    else:
        deps.sidebar.warning(
            "Configure a GPT-OSS endpoint or install the package with `pip install gpt-oss` "
            "to start a local server."
        )
