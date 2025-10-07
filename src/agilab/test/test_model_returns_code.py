import os
import re
from pathlib import Path
import pytest


def _extract_fenced_code(text: str) -> str:
    """Return code inside the first triple‑backtick block, if any.

    Accepts ```python ...``` or plain ``` ... ``` blocks.
    """
    if not isinstance(text, str):
        return ""
    # Look for ```python ... ``` first
    m = re.search(r"```\s*python\s*\n(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip()
    # Then any fenced block
    m = re.search(r"```\s*\n(.*?)```", text, flags=re.DOTALL)
    if m:
        return m.group(1).strip()
    return ""


def test_model_returns_fenced_python_code_for_savgol():
    """Queries the configured model and checks it returns fenced Python code.

    This is a live (integration) test that helps validate whether the current
    model + pre-prompt convention will produce code consumable by the UI editor.
    """
    # Resolve API key strictly from ~/.agilab/.env (no fallback)
    api_key = None
    candidate = Path.home() / ".agilab/.env"
    if candidate.exists():
        try:
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k == "OPENAI_API_KEY" and v:
                    api_key = v
                    break
        except Exception:
            pass

    if not api_key:
        pytest.skip("OPENAI_API_KEY not found in ~/.agilab/.env; skipping live API test")

    try:
        import openai  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency in CI
        pytest.skip(f"openai SDK not available: {exc}")

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    client = openai.OpenAI(api_key=api_key)

    system = (
        "You are a helpful coding assistant. "
        "Return ONLY Python code inside a fenced block like ```python ... ``` with no explanations."
    )
    user = (
        "add smoothing of col long with savgol. "
        "Assume there is a pandas DataFrame df."
    )

    # Keep the request minimal to avoid model‑specific parameter errors
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    # Prefer chat.completions path; minimal required fields only
    resp = client.chat.completions.create(model=model, messages=messages)
    text = resp.choices[0].message.content or ""
    code = _extract_fenced_code(text)

    # Assertion: editor expects fenced code; fail with helpful context if missing
    assert code, (
        "Model did not return fenced Python code. "
        "Ensure your pre‑prompt instructs the model to wrap output in ```python ... ``` and returns only code."
    )
