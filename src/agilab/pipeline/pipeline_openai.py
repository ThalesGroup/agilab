import os
from pathlib import Path
import re
from typing import Any, Callable, Dict, Optional

import streamlit as st

from agi_env.defaults import get_default_openai_model
from agi_env.runtime.env_config_support import update_env_file_text

_ENV_VAR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def is_placeholder_api_key(key: Optional[str]) -> bool:
    """True only when clearly missing or visibly redacted."""
    from agilab.security.api_keys import looks_placeholder_secret

    return looks_placeholder_secret(key)


def _dotenv_quote(value: str) -> str:
    escaped = (
        str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )
    return f'"{escaped}"'


def persist_env_var(name: str, value: str) -> None:
    """Persist a key/value pair under ~/.agilab/.env, replacing prior entries."""
    if not _ENV_VAR_NAME_RE.fullmatch(name):
        raise ValueError(f"Invalid environment variable name: {name!r}")

    env_dir = Path.home() / ".agilab"
    env_dir.mkdir(parents=True, exist_ok=True)
    env_dir.chmod(0o700)
    env_file = env_dir / ".env"
    symlink_error = f"Refusing to write API credentials through symlink: {env_file}"

    def _apply(current_text: str | None) -> str:
        lines = [
            line
            for line in (current_text or "").splitlines()
            if not line.strip().startswith(f"{name}=")
        ]
        lines.append(f"{name}={_dotenv_quote(value)}")
        return "\n".join(lines) + "\n"

    update_env_file_text(
        env_file,
        _apply,
        file_mode=0o600,
        refuse_symlink_message=symlink_error,
    )


def prompt_for_openai_api_key(message: str) -> None:
    """Prompt for a missing OpenAI API key and optionally persist it."""
    st.warning(message)
    default_value = st.session_state.get("openai_api_key", "")
    with st.form("experiment_missing_openai_api_key"):
        new_key = st.text_input(
            "OpenAI API key",
            value=default_value,
            type="password",
            help="Paste a valid OpenAI API token.",
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
                from agi_env import AgiEnv

                AgiEnv.set_env_var("OPENAI_API_KEY", cleaned)
            except (AttributeError, ImportError, RuntimeError):
                AgiEnv = None  # type: ignore[assignment]
            env_obj = st.session_state.get("env")
            if AgiEnv is not None and isinstance(env_obj, AgiEnv) and env_obj.envars is not None:
                env_obj.envars["OPENAI_API_KEY"] = cleaned
            st.session_state["openai_api_key"] = cleaned
            if save_profile:
                try:
                    persist_env_var("OPENAI_API_KEY", cleaned)
                    st.success("API key saved to ~/.agilab/.env")
                except OSError as exc:
                    st.warning(f"Could not persist API key: {exc}")
            else:
                st.success("API key updated for this session.")
            st.rerun()

    st.stop()


def make_openai_client_and_model(envars: Dict[str, str], api_key: str):
    """Return (client, model_name, is_azure) for OpenAI, Azure OpenAI, or proxies."""
    base_url = (
        envars.get("OPENAI_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or ""
    )
    azure_endpoint = (
        envars.get("AZURE_OPENAI_ENDPOINT")
        or os.getenv("AZURE_OPENAI_ENDPOINT")
        or ""
    )
    azure_version = (
        envars.get("AZURE_OPENAI_API_VERSION")
        or os.getenv("AZURE_OPENAI_API_VERSION")
        or "2024-06-01"
    )
    model_name = (
        envars.get("OPENAI_MODEL")
        or os.getenv("OPENAI_MODEL")
        or os.getenv("AZURE_OPENAI_DEPLOYMENT")
        or get_default_openai_model()
    )
    is_azure = bool(azure_endpoint) or bool(os.getenv("OPENAI_API_TYPE") == "azure") or bool(
        os.getenv("AZURE_OPENAI_API_KEY")
    )

    try:
        import openai
    except ImportError as exc:
        raise ImportError(
            "OpenAI features require the optional AI dependency. "
            "Install with `pip install 'agilab[ai]'` or `uv pip install 'agilab[ai]'`."
        ) from exc

    try:
        from openai import OpenAI as OpenAIClient
    except ImportError:
        OpenAIClient = getattr(openai, "OpenAI", None)

    if is_azure:
        try:
            from openai import AzureOpenAI
        except ImportError:
            AzureOpenAI = None

        if AzureOpenAI is not None:
            client = AzureOpenAI(
                api_key=api_key,
                azure_endpoint=azure_endpoint or os.getenv("AZURE_OPENAI_ENDPOINT"),
                api_version=azure_version,
            )
            model_name = (
                os.getenv("AZURE_OPENAI_DEPLOYMENT")
                or envars.get("AZURE_OPENAI_DEPLOYMENT")
                or model_name
            )
            return client, model_name, True

        client = OpenAIClient(api_key=api_key, base_url=base_url or None) if OpenAIClient else None
        return client, model_name, True

    if OpenAIClient:
        client_kwargs: Dict[str, Any] = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        client = OpenAIClient(**client_kwargs)
        return client, model_name, False

    openai.api_key = api_key
    if base_url:
        openai.api_base = base_url
    return openai, model_name, False


def ensure_cached_api_key(
    envars: Dict[str, str],
    *,
    is_placeholder: Callable[[Optional[str]], bool] = is_placeholder_api_key,
) -> str:
    """Seed the session from secrets, app env, or process env."""
    cached = st.session_state.get("openai_api_key")
    if cached and not is_placeholder(cached):
        return cached

    secret = ""
    try:
        secret = st.secrets.get("OPENAI_API_KEY", "")
    except (AttributeError, RuntimeError, TypeError):
        pass

    candidate = (
        secret
        or envars.get("OPENAI_API_KEY")
        or os.environ.get("OPENAI_API_KEY", "")
        or os.environ.get("AZURE_OPENAI_API_KEY", "")
    )
    if candidate and not is_placeholder(candidate):
        st.session_state["openai_api_key"] = candidate
        return candidate

    st.session_state["openai_api_key"] = ""
    return ""
