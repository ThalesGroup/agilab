from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
import sys


def _load_module(module_name: str, relative_path: str):
    module_path = Path(relative_path)
    importlib.invalidate_caches()
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


pipeline_ai = _load_module("agilab.pipeline_ai", "src/agilab/pipeline_ai.py")


def test_extract_code_splits_detail_and_python_block():
    message = "Use this.\n```python\nprint('ok')\n```\nDone."

    code, detail = pipeline_ai.extract_code(message)

    assert code == "print('ok')"
    assert detail == "Use this.\n\nDone."


def test_normalize_gpt_oss_endpoint_appends_responses_path():
    assert pipeline_ai._normalize_gpt_oss_endpoint("") == pipeline_ai.DEFAULT_GPT_OSS_ENDPOINT
    assert (
        pipeline_ai._normalize_gpt_oss_endpoint("http://127.0.0.1:8000")
        == "http://127.0.0.1:8000/v1/responses"
    )
    assert (
        pipeline_ai._normalize_gpt_oss_endpoint("http://127.0.0.1:8000/v1")
        == "http://127.0.0.1:8000/v1/responses"
    )


def test_build_autofix_prompt_truncates_large_inputs():
    prompt = pipeline_ai._build_autofix_prompt(
        original_request="smooth the column",
        failing_code="x" * 7000,
        traceback_text="y" * 5000,
        attempt=2,
    )

    assert "attempt 2" in prompt
    assert "smooth the column" in prompt
    assert len(prompt) < 12000

