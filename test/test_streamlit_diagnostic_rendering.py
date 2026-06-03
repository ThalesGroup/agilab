from __future__ import annotations

import re
import tokenize
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src" / "agilab"

BAD_STREAMLIT_DIAGNOSTIC_PATTERNS = {
    re.compile(r"st\.error\(\s*traceback\.format_exc\(\)\s*\)"): (
        "Tracebacks should be rendered with st.code(..., language='text'), not st.error()."
    ),
    re.compile(r"st\.error\(\s*f?[\"']```"): (
        "Do not put Markdown code fences inside st.error(); use st.error() plus st.code()."
    ),
    re.compile(r"st\.code\(\s*f?[\"']```"): (
        "Do not put Markdown code fences inside st.code(); Streamlit already renders code blocks."
    ),
}


def test_streamlit_diagnostics_do_not_render_tracebacks_as_message_box_text() -> None:
    offenders: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        with tokenize.open(path) as source:
            text = source.read()
        for pattern, reason in BAD_STREAMLIT_DIAGNOSTIC_PATTERNS.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{line}: {reason}")

    assert offenders == []
