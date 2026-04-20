from __future__ import annotations

import importlib
import importlib.util
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from agi_env import AgiEnv

try:
    from agilab.pipeline_ai_support import (
        _ensure_uoaic_runtime as _ensure_uoaic_runtime_impl,
        format_uoaic_question as _format_uoaic_question,
        _load_uoaic_modules as _load_uoaic_modules_impl,
        normalize_ollama_endpoint as _normalize_ollama_endpoint,
        normalize_user_path as _normalize_user_path,
        _resolve_uoaic_path as _resolve_uoaic_path_impl,
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
    _ensure_uoaic_runtime_impl = _pipeline_ai_support_module._ensure_uoaic_runtime
    _format_uoaic_question = _pipeline_ai_support_module.format_uoaic_question
    _load_uoaic_modules_impl = _pipeline_ai_support_module._load_uoaic_modules
    _normalize_ollama_endpoint = _pipeline_ai_support_module.normalize_ollama_endpoint
    _normalize_user_path = _pipeline_ai_support_module.normalize_user_path
    _resolve_uoaic_path_impl = _pipeline_ai_support_module._resolve_uoaic_path


UOAIC_PROVIDER = "universal-offline-ai-chatbot"
UOAIC_DATA_ENV = "UOAIC_DATA_PATH"
UOAIC_DB_ENV = "UOAIC_DB_PATH"
UOAIC_DEFAULT_DB_DIRNAME = "vectorstore/db_faiss"
UOAIC_RUNTIME_KEY = "uoaic_runtime"
UOAIC_DATA_STATE_KEY = "uoaic_data_path"
UOAIC_DB_STATE_KEY = "uoaic_db_path"
UOAIC_REBUILD_FLAG_KEY = "uoaic_rebuild_requested"
UOAIC_MODE_ENV = "UOAIC_MODE"
UOAIC_MODE_STATE_KEY = "uoaic_mode"
UOAIC_MODE_OLLAMA = "ollama"
UOAIC_MODE_RAG = "rag"
UOAIC_OLLAMA_ENDPOINT_ENV = "UOAIC_OLLAMA_ENDPOINT"
UOAIC_MODEL_ENV = "UOAIC_MODEL"
UOAIC_TEMPERATURE_ENV = "UOAIC_TEMPERATURE"
UOAIC_TOP_P_ENV = "UOAIC_TOP_P"
UOAIC_NUM_CTX_ENV = "UOAIC_NUM_CTX"
UOAIC_NUM_PREDICT_ENV = "UOAIC_NUM_PREDICT"
UOAIC_SEED_ENV = "UOAIC_SEED"
UOAIC_AUTOFIX_ENV = "UOAIC_AUTOFIX"
UOAIC_AUTOFIX_MAX_ENV = "UOAIC_AUTOFIX_MAX_ATTEMPTS"
UOAIC_AUTOFIX_STATE_KEY = "uoaic_autofix_enabled"
UOAIC_AUTOFIX_MAX_STATE_KEY = "uoaic_autofix_max_attempts"
DEFAULT_UOAIC_BASE = Path.home() / ".agilab" / "mistral_offline"
_HF_TOKEN_ENV_KEYS = ("HF_TOKEN", "HUGGINGFACEHUB_API_TOKEN")


@dataclass(frozen=True)
class UoaicRuntimeDeps:
    session_state: Any
    normalize_path_fn: Callable[[str | Path], str]
    pipeline_export_root_fn: Callable[[AgiEnv], Path]
    load_modules_fn: Callable[[], Tuple[Any, ...]]
    error_sink: Callable[[str], None]
    spinner_factory: Callable[[str], Any]


@dataclass(frozen=True)
class UoaicControlDeps:
    session_state: Any
    sidebar: Any
    normalize_path_fn: Callable[[str | Path], str]
    default_ollama_model_fn: Callable[..., str]
    ensure_runtime_fn: Callable[[Dict[str, str]], Dict[str, Any]]
    spinner_factory: Callable[[str], Any]
    normalize_user_path_fn: Callable[[str], str] = _normalize_user_path


def resolve_uoaic_path(
    raw_path: str,
    env: Optional[AgiEnv],
    *,
    pipeline_export_root_fn: Optional[Callable[[AgiEnv], Path]] = None,
) -> Path:
    base_dir: Optional[Path] = None
    if env is not None:
        try:
            if pipeline_export_root_fn is None:
                base_dir = Path.cwd()
            else:
                base_dir = pipeline_export_root_fn(env)
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):  # pragma: no cover - defensive
            base_dir = None
    return _resolve_uoaic_path_impl(raw_path, base_dir=base_dir)


def load_uoaic_modules(
    *,
    distribution_fn: Callable[[str], Any] | None = None,
    import_module_fn: Callable[[str], Any] | None = None,
    spec_from_file_location_fn: Callable[[str, str], Any] | None = None,
    module_from_spec_fn: Callable[[Any], Any] | None = None,
) -> Tuple[Any, ...]:
    if distribution_fn is None:
        distribution_fn = importlib.metadata.distribution
    if import_module_fn is None:
        import_module_fn = importlib.import_module
    if spec_from_file_location_fn is None:
        spec_from_file_location_fn = importlib.util.spec_from_file_location
    if module_from_spec_fn is None:
        module_from_spec_fn = importlib.util.module_from_spec
    return _load_uoaic_modules_impl(
        distribution_fn=distribution_fn,
        import_module_fn=import_module_fn,
        spec_from_file_location_fn=spec_from_file_location_fn,
        module_from_spec_fn=module_from_spec_fn,
    )


def ensure_uoaic_runtime(
    envars: Dict[str, str],
    *,
    env: Optional[AgiEnv],
    deps: UoaicRuntimeDeps,
    resolve_uoaic_path_fn: Optional[Callable[[str, Optional[AgiEnv]], Path]] = None,
    load_uoaic_modules_fn: Optional[Callable[[], Tuple[Any, ...]]] = None,
) -> Dict[str, Any]:
    runtime_resolver = resolve_uoaic_path_fn
    if runtime_resolver is None:
        runtime_resolver = lambda raw_path, _env: resolve_uoaic_path(
            raw_path,
            _env,
            pipeline_export_root_fn=deps.pipeline_export_root_fn,
        )
    module_loader = load_uoaic_modules_fn
    if module_loader is None:
        module_loader = deps.load_modules_fn

    return _ensure_uoaic_runtime_impl(
        envars,
        session_state=deps.session_state,
        resolve_uoaic_path=lambda raw, base_dir=None: runtime_resolver(raw, env),
        load_uoaic_modules=module_loader,
        runtime_state_key=UOAIC_RUNTIME_KEY,
        data_state_key=UOAIC_DATA_STATE_KEY,
        db_state_key=UOAIC_DB_STATE_KEY,
        rebuild_state_key=UOAIC_REBUILD_FLAG_KEY,
        data_env_key=UOAIC_DATA_ENV,
        db_env_key=UOAIC_DB_ENV,
        model_env_key=UOAIC_MODEL_ENV,
        default_db_dirname=UOAIC_DEFAULT_DB_DIRNAME,
        spinner=deps.spinner_factory,
    )


def chat_universal_offline(
    input_request: str,
    prompt: List[Dict[str, str]],
    envars: Dict[str, str],
    *,
    ensure_runtime_fn: Callable[[Dict[str, str]], Dict[str, Any]],
    error_sink: Callable[[str], None],
) -> Tuple[str, str]:
    runtime = ensure_runtime_fn(envars)
    chain = runtime["chain"]
    model_label = runtime.get("model_label") or str(envars.get(UOAIC_MODEL_ENV) or "universal-offline")
    query_text = _format_uoaic_question(prompt, input_request) or input_request

    try:
        response = chain.invoke({"query": query_text})
    except (AttributeError, KeyError, RuntimeError, TypeError, ValueError) as exc:
        error_sink(f"Universal Offline AI Chatbot invocation failed: {exc}")
        raise RuntimeError(exc) from exc

    answer = ""
    sources: List[str] = []

    if isinstance(response, dict):
        answer = response.get("result") or response.get("answer") or ""
        source_documents = response.get("source_documents") or []
        for doc in source_documents:
            metadata = getattr(doc, "metadata", {}) if hasattr(doc, "metadata") else {}
            if isinstance(metadata, dict):
                source = metadata.get("source") or metadata.get("file") or metadata.get("path")
                page = metadata.get("page") or metadata.get("page_number")
                if source:
                    if page is not None:
                        sources.append(f"{source} (page {page})")
                    else:
                        sources.append(str(source))
    else:
        answer = str(response)

    answer_text = str(answer).strip()
    if sources:
        sources_block = "\n".join(f"- {entry}" for entry in sources)
        if answer_text:
            answer_text = f"{answer_text}\n\nSources:\n{sources_block}"
        else:
            answer_text = f"Sources:\n{sources_block}"

    return answer_text, model_label


def render_universal_offline_controls(
    env: AgiEnv,
    *,
    deps: UoaicControlDeps,
) -> None:
    if deps.session_state.get("lab_llm_provider") != UOAIC_PROVIDER:
        return

    mode_default = (
        deps.session_state.get(UOAIC_MODE_STATE_KEY)
        or env.envars.get(UOAIC_MODE_ENV)
        or os.getenv(UOAIC_MODE_ENV)
        or UOAIC_MODE_OLLAMA
    )
    mode_options = {
        "Code (Ollama)": UOAIC_MODE_OLLAMA,
        "RAG (offline docs)": UOAIC_MODE_RAG,
    }
    mode_labels = list(mode_options.keys())
    current_mode_label = next(
        (label for label, value in mode_options.items() if value == mode_default),
        mode_labels[0],
    )
    selected_mode_label = deps.sidebar.selectbox(
        "Local assistant mode",
        mode_labels,
        index=mode_labels.index(current_mode_label),
        help="Use direct Ollama generation for code correctness, or the Universal Offline RAG chain for doc Q&A.",
    )
    selected_mode = mode_options[selected_mode_label]
    previous_mode = deps.session_state.get(UOAIC_MODE_STATE_KEY)
    deps.session_state[UOAIC_MODE_STATE_KEY] = selected_mode
    env.envars[UOAIC_MODE_ENV] = selected_mode
    if previous_mode and previous_mode != selected_mode:
        deps.session_state.pop(UOAIC_RUNTIME_KEY, None)

    with deps.sidebar.expander("Ollama settings", expanded=True):
        endpoint_default = (
            deps.session_state.get("uoaic_ollama_endpoint")
            or env.envars.get(UOAIC_OLLAMA_ENDPOINT_ENV)
            or os.getenv(UOAIC_OLLAMA_ENDPOINT_ENV)
            or os.getenv("OLLAMA_HOST", "")
            or "http://127.0.0.1:11434"
        )
        endpoint_input = deps.sidebar.text_input(
            "Ollama endpoint",
            value=str(endpoint_default),
            help="Base URL of the Ollama server (default: http://127.0.0.1:11434).",
        ).strip()
        normalized_endpoint = _normalize_ollama_endpoint(endpoint_input)
        deps.session_state["uoaic_ollama_endpoint"] = normalized_endpoint
        env.envars[UOAIC_OLLAMA_ENDPOINT_ENV] = normalized_endpoint

        model_default = (
            deps.session_state.get("uoaic_model")
            or env.envars.get(UOAIC_MODEL_ENV)
            or os.getenv(UOAIC_MODEL_ENV, "")
            or deps.default_ollama_model_fn(
                normalized_endpoint,
                prefer_code=selected_mode == UOAIC_MODE_OLLAMA,
            )
        )
        model_input = deps.sidebar.text_input(
            "Ollama model",
            value=str(model_default),
            help="Model name (as shown by `ollama list`). For best code correctness, use a code-tuned model when available.",
        ).strip()
        deps.session_state["uoaic_model"] = model_input
        if model_input:
            env.envars[UOAIC_MODEL_ENV] = model_input
        else:
            env.envars.pop(UOAIC_MODEL_ENV, None)

        def _float_default(name: str, fallback: float) -> float:
            raw = deps.session_state.get(name) or env.envars.get(name) or os.getenv(name)
            try:
                return float(raw)
            except (TypeError, ValueError):
                return float(fallback)

        temperature_default = max(0.0, min(1.0, _float_default(UOAIC_TEMPERATURE_ENV, 0.1)))
        temperature = deps.sidebar.slider(
            "temperature",
            min_value=0.0,
            max_value=1.0,
            value=float(temperature_default),
            step=0.05,
            help="Lower values improve determinism for code generation.",
        )
        env.envars[UOAIC_TEMPERATURE_ENV] = str(float(temperature))

        top_p_default = max(0.0, min(1.0, _float_default(UOAIC_TOP_P_ENV, 0.9)))
        top_p = deps.sidebar.slider(
            "top_p",
            min_value=0.0,
            max_value=1.0,
            value=float(top_p_default),
            step=0.05,
            help="Nucleus sampling. Lower values can reduce hallucinations for code.",
        )
        env.envars[UOAIC_TOP_P_ENV] = str(float(top_p))

        def _int_default(name: str, fallback: int) -> int:
            raw = deps.session_state.get(name) or env.envars.get(name) or os.getenv(name)
            try:
                return int(float(raw))
            except (TypeError, ValueError):
                return int(fallback)

        num_ctx = deps.sidebar.number_input(
            "num_ctx (0 = default)",
            min_value=0,
            max_value=262144,
            value=_int_default(UOAIC_NUM_CTX_ENV, 0),
            step=256,
            help="Context window. Increase if prompts are truncated (requires RAM).",
        )
        if int(num_ctx) > 0:
            env.envars[UOAIC_NUM_CTX_ENV] = str(int(num_ctx))
        else:
            env.envars.pop(UOAIC_NUM_CTX_ENV, None)

        num_predict = deps.sidebar.number_input(
            "num_predict (0 = default)",
            min_value=0,
            max_value=65536,
            value=_int_default(UOAIC_NUM_PREDICT_ENV, 0),
            step=128,
            help="Max tokens to generate. Set 0 to use Ollama defaults.",
        )
        if int(num_predict) > 0:
            env.envars[UOAIC_NUM_PREDICT_ENV] = str(int(num_predict))
        else:
            env.envars.pop(UOAIC_NUM_PREDICT_ENV, None)

        seed = deps.sidebar.number_input(
            "seed (0 = unset)",
            min_value=0,
            max_value=2**31 - 1,
            value=_int_default(UOAIC_SEED_ENV, 0),
            step=1,
            help="Optional deterministic seed for the local model.",
        )
        if int(seed) > 0:
            env.envars[UOAIC_SEED_ENV] = str(int(seed))
        else:
            env.envars.pop(UOAIC_SEED_ENV, None)

    with deps.sidebar.expander("Code correctness", expanded=True):
        autofix_default = env.envars.get(UOAIC_AUTOFIX_ENV) or os.getenv(UOAIC_AUTOFIX_ENV) or "0"
        autofix_enabled = bool(deps.session_state.get(UOAIC_AUTOFIX_STATE_KEY, autofix_default in {"1", "true", "True"}))
        autofix_enabled = deps.sidebar.checkbox(
            "Auto-run + auto-fix generated code",
            value=autofix_enabled,
            help="After generating code, run it against the loaded dataframe and ask the model to repair tracebacks.",
        )
        deps.session_state[UOAIC_AUTOFIX_STATE_KEY] = autofix_enabled
        env.envars[UOAIC_AUTOFIX_ENV] = "1" if autofix_enabled else "0"

        max_default = env.envars.get(UOAIC_AUTOFIX_MAX_ENV) or os.getenv(UOAIC_AUTOFIX_MAX_ENV) or "2"
        try:
            max_default_int = max(0, int(max_default))
        except (TypeError, ValueError):
            max_default_int = 2
        max_attempts = deps.sidebar.number_input(
            "Max fix attempts",
            min_value=0,
            max_value=10,
            value=int(deps.session_state.get(UOAIC_AUTOFIX_MAX_STATE_KEY, max_default_int)),
            step=1,
            help="0 disables iterative repairs; the first generated code is kept.",
        )
        deps.session_state[UOAIC_AUTOFIX_MAX_STATE_KEY] = int(max_attempts)
        env.envars[UOAIC_AUTOFIX_MAX_ENV] = str(int(max_attempts))

    if selected_mode != UOAIC_MODE_RAG:
        deps.sidebar.caption("RAG knowledge-base settings are hidden (switch mode to enable).")
        return

    default_data_path = DEFAULT_UOAIC_BASE / "data"
    data_default = (
        deps.session_state.get(UOAIC_DATA_STATE_KEY)
        or env.envars.get(UOAIC_DATA_ENV)
        or os.getenv(UOAIC_DATA_ENV, "")
    )
    if not data_default:
        try:
            default_data_path.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        data_default = deps.normalize_path_fn(default_data_path)
    data_input = deps.sidebar.text_input(
        "Universal Offline data directory",
        value=data_default,
        help="Path containing the PDF documents to index for the Universal Offline AI Chatbot.",
    ).strip()
    data_input_blank = not data_input
    if data_input_blank:
        data_input = data_default
    if data_input:
        normalized_data = deps.normalize_user_path_fn(data_input)
        if normalized_data:
            changed = normalized_data != deps.session_state.get(UOAIC_DATA_STATE_KEY)
            deps.session_state[UOAIC_DATA_STATE_KEY] = normalized_data
            env.envars[UOAIC_DATA_ENV] = normalized_data
            if changed or data_input_blank:
                deps.session_state.pop(UOAIC_RUNTIME_KEY, None)
        else:
            deps.sidebar.warning("Provide a valid data directory for the Universal Offline AI Chatbot.")
    else:
        deps.session_state.pop(UOAIC_DATA_STATE_KEY, None)
        env.envars.pop(UOAIC_DATA_ENV, None)

    default_db_path = DEFAULT_UOAIC_BASE / "vectorstore" / "db_faiss"
    db_default = (
        deps.session_state.get(UOAIC_DB_STATE_KEY)
        or env.envars.get(UOAIC_DB_ENV)
        or os.getenv(UOAIC_DB_ENV, "")
    )
    if not db_default:
        try:
            default_db_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        db_default = deps.normalize_path_fn(default_db_path)

    db_input = deps.sidebar.text_input(
        "Universal Offline vector store directory",
        value=db_default,
        help="Location for the FAISS vector store (defaults to `<data>/vectorstore/db_faiss`).",
    ).strip()
    db_input_blank = not db_input
    if db_input_blank:
        db_input = db_default
    if db_input:
        normalized_db = deps.normalize_user_path_fn(db_input)
        if normalized_db:
            changed = normalized_db != deps.session_state.get(UOAIC_DB_STATE_KEY)
            deps.session_state[UOAIC_DB_STATE_KEY] = normalized_db
            env.envars[UOAIC_DB_ENV] = normalized_db
            if changed or db_input_blank:
                deps.session_state.pop(UOAIC_RUNTIME_KEY, None)
        else:
            deps.sidebar.warning("Provide a valid directory for the Universal Offline vector store.")
    else:
        deps.session_state.pop(UOAIC_DB_STATE_KEY, None)
        env.envars.pop(UOAIC_DB_ENV, None)

    if not any(os.getenv(key) for key in _HF_TOKEN_ENV_KEYS):
        deps.sidebar.info(
            "Set `HF_TOKEN` (or `HUGGINGFACEHUB_API_TOKEN`) so the embedding model can download once."
        )

    if deps.sidebar.button("Rebuild Universal Offline knowledge base", key="uoaic_rebuild_btn"):
        if not deps.session_state.get(UOAIC_DATA_STATE_KEY):
            deps.sidebar.error("Set the data directory before rebuilding the Universal Offline knowledge base.")
            return
        deps.session_state[UOAIC_REBUILD_FLAG_KEY] = True
        try:
            with deps.spinner_factory("Rebuilding Universal Offline AI Chatbot knowledge base…"):
                deps.ensure_runtime_fn(env.envars)
        except RuntimeError:
            return
        deps.sidebar.success("Universal Offline knowledge base updated.")
