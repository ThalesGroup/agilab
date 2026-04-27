from __future__ import annotations

from pathlib import Path


FIRST_PARTY_STREAMLIT_MANIFESTS = [
    Path("pyproject.toml"),
    Path("src/agilab/lib/agi-gui/pyproject.toml"),
    *sorted(Path("src/agilab/apps-pages").glob("*/pyproject.toml")),
    *sorted(Path("src/agilab/apps/builtin").glob("*/pyproject.toml")),
]


def test_first_party_streamlit_manifests_require_156_when_pinned() -> None:
    stale = []
    for manifest in FIRST_PARTY_STREAMLIT_MANIFESTS:
        text = manifest.read_text(encoding="utf-8")
        if "streamlit>=1.55.0" in text:
            stale.append(str(manifest))

    assert stale == []
