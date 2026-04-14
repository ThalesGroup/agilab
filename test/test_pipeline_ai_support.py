from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
import sys

import pandas as pd
import pytest


def _load_module(module_name: str, relative_path: str):
    module_path = Path(relative_path)
    importlib.invalidate_caches()
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


pipeline_ai_support = _load_module("agilab.pipeline_ai_support_test", "src/agilab/pipeline_ai_support.py")


def test_validate_code_safety_rejects_import_statements():
    with pytest.raises(pipeline_ai_support._UnsafeCodeError, match="Import statements are not allowed"):
        pipeline_ai_support._validate_code_safety("import os")


def test_validate_code_safety_rejects_blocked_builtin():
    with pytest.raises(pipeline_ai_support._UnsafeCodeError, match="Call to blocked builtin"):
        pipeline_ai_support._validate_code_safety("open('x', 'r')")


def test_validate_code_safety_rejects_blocked_module_attribute():
    with pytest.raises(pipeline_ai_support._UnsafeCodeError, match="Access to module 'os' is not allowed"):
        pipeline_ai_support._validate_code_safety("os.system('echo hi')")


def test_validate_code_safety_rejects_blocked_dunder_attr():
    with pytest.raises(pipeline_ai_support._UnsafeCodeError, match="Access to '__class__' is not allowed"):
        pipeline_ai_support._validate_code_safety("x = 1\nx.__class__")


def test_exec_code_on_df_blocks_unsafe_code():
    updated, error = pipeline_ai_support._exec_code_on_df("os.system('echo hi')", pd.DataFrame({"x": [1]}))
    assert updated is None
    assert "Safety check failed" in error


def test_build_autofix_prompt_clips_traceback_and_code():
    prompt = pipeline_ai_support._build_autofix_prompt(
        original_request="smooth",
        failing_code="x" * 7000,
        traceback_text="y" * 5000,
        attempt=1,
    )

    assert "attempt 1" in prompt
    assert len(prompt) < 12000
