from __future__ import annotations

import agi_env.defaults as defaults


def test_get_default_openai_model_uses_default_and_env_override(monkeypatch):
    monkeypatch.delenv(defaults.DEFAULT_OPENAI_MODEL_ENVVAR, raising=False)
    assert defaults.get_default_openai_model() == defaults.DEFAULT_OPENAI_MODEL_NAME
    assert defaults.DEFAULT_OPENAI_MODEL_NAME == "gpt-5.4-mini"

    monkeypatch.setenv(defaults.DEFAULT_OPENAI_MODEL_ENVVAR, "gpt-test-model")
    assert defaults.get_default_openai_model() == "gpt-test-model"
