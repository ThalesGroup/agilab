from __future__ import annotations

from pathlib import Path


FIRST_PARTY_STREAMLIT_MANIFESTS = [
    Path("pyproject.toml"),
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


def test_analysis_page_uses_streamlit_156_navigation_widgets() -> None:
    source = Path("src/agilab/pages/4_▶️ ANALYSIS.py").read_text(encoding="utf-8")

    assert "st.menu_button(" in source
    assert 'filter_mode="contains"' in source


def test_project_page_code_symbol_selectors_use_filter_mode() -> None:
    source = Path("src/agilab/pages/1_▶️ PROJECT.py").read_text(encoding="utf-8")

    assert source.count('filter_mode="contains"') >= 2


def test_top_level_ui_pages_guard_streamlit_156_runtime() -> None:
    for page_path in (
        Path("src/agilab/About_agilab.py"),
        Path("src/agilab/pages/1_▶️ PROJECT.py"),
        Path("src/agilab/pages/4_▶️ ANALYSIS.py"),
    ):
        source = page_path.read_text(encoding="utf-8")
        assert "agilab.streamlit_version_guard" in source
        assert "require_streamlit_min_version(st" in source


def test_streamlit_156_deprecated_ui_apis_are_not_used() -> None:
    checked_paths = (
        Path("src/agilab/About_agilab.py"),
        Path("src/agilab/pipeline_sidebar.py"),
        Path("src/agilab/apps-pages/view_release_decision/src/view_release_decision/view_release_decision.py"),
    )

    offenders: list[str] = []
    for path in checked_paths:
        source = path.read_text(encoding="utf-8")
        for deprecated in ("st.components.v1.html", "use_container_width=True"):
            if deprecated in source:
                offenders.append(f"{path}:{deprecated}")

    assert offenders == []
