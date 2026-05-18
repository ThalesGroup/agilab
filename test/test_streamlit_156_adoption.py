from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
import tomllib

THEME_ENV_PATH = Path("src/agilab/streamlit_theme_env.py").resolve()
THEME_ENV_SPEC = importlib.util.spec_from_file_location("agilab_streamlit_theme_env_test", THEME_ENV_PATH)
assert THEME_ENV_SPEC and THEME_ENV_SPEC.loader
streamlit_theme_env = importlib.util.module_from_spec(THEME_ENV_SPEC)
sys.modules[THEME_ENV_SPEC.name] = streamlit_theme_env
THEME_ENV_SPEC.loader.exec_module(streamlit_theme_env)


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
    source_launch_config = tomllib.loads(Path(".streamlit/config.toml").read_text(encoding="utf-8"))

    assert theme_config["theme"]["base"] == "dark"
    assert theme_config["theme"]["primaryColor"] == "#4A90E2"
    assert theme_config["theme"]["backgroundColor"] == "#08111F"
    assert theme_config["theme"]["secondaryBackgroundColor"] == "#102334"
    assert theme_config["theme"]["textColor"] == "#F7F2E8"
    assert source_launch_config["theme"] == theme_config["theme"]
    assert "--agilab-primary: #4A90E2;" in theme_css
    assert "--agilab-value-ready: #72d6b4;" in theme_css
    assert "--agilab-value-incomplete: #ffbe5e;" in theme_css
    assert ".agilab-header-value--ready" in theme_css
    assert ".agilab-header-value--incomplete" in theme_css
    assert "padding: clamp(1.25rem, 2.2vw, 1.85rem);" in theme_css
    assert "gap: 1.15rem !important;" in theme_css
    assert "gap: 1.15rem;" in theme_css
    assert "align-items: stretch;" in theme_css
    assert "grid-template-rows: auto minmax(1.65rem, 1fr) auto;" in theme_css
    assert '[data-testid="stVerticalBlock"]:has(> [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] .agilab-header-card)' in theme_css
    assert '[data-testid="stElementContainer"]:has(.agilab-header-card)' in theme_css
    assert "margin-bottom: 0 !important;" in theme_css
    assert "stVerticalBlockBorderWrapper" not in theme_css
    assert '[data-testid="stMetricValue"]' not in theme_css
    assert '[data-testid="stButtonGroup"]' in theme_css
    assert '[role="radio"][aria-checked="true"]' in theme_css
    assert '[role="checkbox"][aria-checked="true"]' in theme_css
    assert "var(--agilab-primary)" in theme_css
    assert "#ff4b4b" not in theme_css.lower()
    assert "255, 75, 75" not in theme_css


def test_agilab_theme_config_maps_to_streamlit_environment(monkeypatch) -> None:
    for env_key in [
        "STREAMLIT_CONFIG_FILE",
        "STREAMLIT_THEME_BASE",
        "STREAMLIT_THEME_PRIMARY_COLOR",
        "STREAMLIT_THEME_BACKGROUND_COLOR",
        "STREAMLIT_THEME_SECONDARY_BACKGROUND_COLOR",
        "STREAMLIT_THEME_TEXT_COLOR",
    ]:
        monkeypatch.delenv(env_key, raising=False)

    env: dict[str, str] = {}
    config_path = Path("src/agilab/resources/config.toml")
    streamlit_theme_env.apply_streamlit_theme_environment(config_path, environ=env)

    assert streamlit_theme_env.load_streamlit_theme_values(config_path) == {
        "base": "dark",
        "primaryColor": "#4A90E2",
        "backgroundColor": "#08111F",
        "secondaryBackgroundColor": "#102334",
        "textColor": "#F7F2E8",
    }
    assert env["STREAMLIT_CONFIG_FILE"] == str(config_path)
    assert env["STREAMLIT_THEME_BASE"] == "dark"
    assert env["STREAMLIT_THEME_PRIMARY_COLOR"] == "#4A90E2"
    assert env["STREAMLIT_THEME_BACKGROUND_COLOR"] == "#08111F"
    assert env["STREAMLIT_THEME_SECONDARY_BACKGROUND_COLOR"] == "#102334"
    assert env["STREAMLIT_THEME_TEXT_COLOR"] == "#F7F2E8"


def test_streamlit_theme_values_ignore_missing_malformed_and_non_theme_configs(tmp_path) -> None:
    missing = tmp_path / "missing.toml"
    malformed = tmp_path / "malformed.toml"
    non_theme = tmp_path / "server.toml"
    malformed.write_text("[theme\n", encoding="utf-8")
    non_theme.write_text("[server]\nheadless = true\n", encoding="utf-8")

    assert streamlit_theme_env.load_streamlit_theme_values(missing) == {}
    assert streamlit_theme_env.load_streamlit_theme_values(malformed) == {}
    assert streamlit_theme_env.load_streamlit_theme_values(non_theme) == {}


def test_streamlit_theme_environment_preserves_existing_values_and_skips_empty_theme_values(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[theme]
base = "dark"
primaryColor = ""
""".strip(),
        encoding="utf-8",
    )
    env = {
        "STREAMLIT_CONFIG_FILE": "existing.toml",
        "STREAMLIT_THEME_BASE": "light",
    }
    module_file = tmp_path / "agilab" / "main_page.py"

    streamlit_theme_env.apply_streamlit_theme_environment(config_path, environ=env)

    assert streamlit_theme_env.packaged_streamlit_config_path(module_file) == (
        module_file.resolve().parent / "resources" / "config.toml"
    )
    assert streamlit_theme_env.load_streamlit_theme_values(config_path) == {
        "base": "dark",
        "primaryColor": "",
    }
    assert env["STREAMLIT_CONFIG_FILE"] == "existing.toml"
    assert env["STREAMLIT_THEME_BASE"] == "light"
    assert "STREAMLIT_THEME_PRIMARY_COLOR" not in env


def test_source_checkout_streamlit_config_matches_packaged_theme() -> None:
    source_config = tomllib.loads(Path(".streamlit/config.toml").read_text(encoding="utf-8"))
    theme_config = tomllib.loads(Path("src/agilab/resources/config.toml").read_text(encoding="utf-8"))

    assert source_config["theme"] == theme_config["theme"]


def test_first_party_streamlit_code_uses_width_api() -> None:
    offenders = []
    for path in sorted(Path("src/agilab").rglob("*.py")):
        if ".venv" in path.parts or "build" in path.parts:
            continue
        if b"use_container_width" in path.read_bytes():
            offenders.append(str(path))

    assert offenders == []
