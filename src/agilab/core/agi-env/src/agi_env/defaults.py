"""Shared default values for AGILab environment configuration."""

import os
from typing import Final

# Baseline defaults – update in one place when the recommended model changes.
DEFAULT_OPENAI_MODEL_NAME: Final[str] = "gpt-4o"
DEFAULT_OPENAI_MODEL_ENVVAR: Final[str] = "AGILAB_DEFAULT_OPENAI_MODEL"


def get_default_openai_model() -> str:
    """Return the default OpenAI model name, allowing an env override."""

    return os.getenv(DEFAULT_OPENAI_MODEL_ENVVAR, DEFAULT_OPENAI_MODEL_NAME)


__all__ = [
    "DEFAULT_OPENAI_MODEL_NAME",
    "DEFAULT_OPENAI_MODEL_ENVVAR",
    "get_default_openai_model",
]
