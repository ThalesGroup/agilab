"""Regression test: container/vm sandbox modes must refuse, not run in-process.

Covers audit finding #3 (security-app bucket): the code advertised
``AGILAB_GENERATED_CODE_SANDBOX`` values of ``container`` and ``vm`` but nothing
isolated -- both fell through to the in-process executor. The honest behavior is
to refuse those modes (isolation not yet implemented) rather than silently
overclaiming isolation.

The module is loaded from its file path and Streamlit ``session_state`` is
driven directly so the test stays hermetic (no Streamlit runtime, no df, no
network).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

import streamlit as st

_MODULE_PATH = Path(__file__).resolve().parents[1] / "pipeline" / "pipeline_ai.py"


def _load_pipeline_ai():
    spec = importlib.util.spec_from_file_location(
        "agilab_pipeline_ai_under_test", _MODULE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


pipeline_ai = _load_pipeline_ai()


class _StubEnv:
    def __init__(self, envars):
        self.envars = envars


def _run_autofix(module, sandbox_value, *, exec_calls):
    def fake_exec(code, df):  # pragma: no cover - must never be reached here
        exec_calls.append(code)
        return None, ""

    module._exec_code_on_df = fake_exec

    logs = []

    def push_run_log(page, msg, placeholder):
        logs.append(msg)

    def get_run_placeholder(page):
        return None

    result = module._maybe_autofix_generated_code(
        original_request="request",
        df_path=Path("/tmp/does_not_exist.csv"),
        index_page="ORCHESTRATE",
        env=_StubEnv({"AGILAB_GENERATED_CODE_SANDBOX": sandbox_value}),
        merged_code="df['a'] = 1",
        model_label="model",
        detail="detail",
        load_df_cached=lambda *a, **k: None,
        push_run_log=push_run_log,
        get_run_placeholder=get_run_placeholder,
    )
    return result, logs


@pytest.fixture(autouse=True)
def _enable_autofix(monkeypatch):
    st.session_state["lab_llm_provider"] = pipeline_ai.UOAIC_PROVIDER
    st.session_state[pipeline_ai.UOAIC_AUTOFIX_STATE_KEY] = True
    st.session_state[pipeline_ai.UOAIC_AUTOFIX_MAX_STATE_KEY] = 2
    monkeypatch.delenv("AGILAB_GENERATED_CODE_SANDBOX", raising=False)
    yield
    for key in (
        "lab_llm_provider",
        pipeline_ai.UOAIC_AUTOFIX_STATE_KEY,
        pipeline_ai.UOAIC_AUTOFIX_MAX_STATE_KEY,
    ):
        try:
            del st.session_state[key]
        except KeyError:
            pass


@pytest.mark.parametrize("mode", ["container", "vm"])
def test_isolated_modes_refuse_instead_of_running_in_process(mode):
    exec_calls: list[str] = []
    result, logs = _run_autofix(pipeline_ai, mode, exec_calls=exec_calls)

    # Generated code is returned unchanged and NEVER executed in-process.
    assert result == ("df['a'] = 1", "model", "detail")
    assert exec_calls == []

    joined = "\n".join(logs)
    assert "not yet implemented" in joined
    assert mode in joined


def test_isolated_modes_are_declared_but_gated():
    # The mode names remain recognized (so operators get an honest refusal
    # message) but are distinguished from the only executing mode, 'process'.
    assert pipeline_ai.GENERATED_CODE_ISOLATED_SANDBOX_MODES == frozenset({"container", "vm"})
    assert "process" in pipeline_ai.GENERATED_CODE_SANDBOX_MODES
    assert "process" not in pipeline_ai.GENERATED_CODE_ISOLATED_SANDBOX_MODES
