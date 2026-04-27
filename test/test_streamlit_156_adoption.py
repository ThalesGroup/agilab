from __future__ import annotations

from pathlib import Path
import tomllib


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


def test_new_choice_widgets_use_agilab_blue_theme() -> None:
    theme_css = Path("src/agilab/resources/theme.css").read_text(encoding="utf-8")
    theme_config = tomllib.loads(Path("src/agilab/resources/config.toml").read_text(encoding="utf-8"))

    assert theme_config["theme"]["primaryColor"] == "#4A90E2"
    assert "--agilab-primary: #4A90E2;" in theme_css
    assert '[data-testid="stButtonGroup"]' in theme_css
    assert '[role="radio"][aria-checked="true"]' in theme_css
    assert '[role="checkbox"][aria-checked="true"]' in theme_css
    assert "var(--agilab-primary)" in theme_css
    assert "#ff4b4b" not in theme_css.lower()
    assert "255, 75, 75" not in theme_css
