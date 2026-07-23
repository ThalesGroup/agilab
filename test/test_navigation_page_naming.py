"""Guards for sidebar naming and URL-alias hygiene in main_page navigation.

The sidebar labels are a stable user-facing contract: renaming a visible menu
entry is a product decision, not a refactor side effect. URL aliases for old
deep links must stay a bounded, explicitly-listed set of redirects.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN_PAGE_SOURCE = (ROOT / "src" / "agilab" / "main_page.py").read_text(encoding="utf-8")
PAGES_ROOT = ROOT / "src" / "agilab" / "pages"

# The user-visible sidebar contract: these labels (and their URLs) must not
# change without an explicit product decision.
EXPECTED_VISIBLE_ENTRIES = ("PROJECT", "ORCHESTRATE", "WORKFLOW", "ANALYSIS")

# Deprecated deep-link aliases kept as redirects. This set must only shrink.
EXPECTED_REDIRECT_ALIASES = {"PROJECT_EDIT", "PROJECT_STATUS"}

_SPEC_BLOCK_RE = re.compile(
    r"_NavigationPageSpec\(\s*(?P<source>[^,]+),(?P<body>.*?)\n\s*\),",
    re.S,
)


def _parse_specs() -> list[dict[str, str | None]]:
    specs = []
    for match in _SPEC_BLOCK_RE.finditer(MAIN_PAGE_SOURCE):
        body = match.group("body")

        def _field(name: str) -> str | None:
            field = re.search(rf'{name}="([^"]*)"', body)
            return field.group(1) if field else None

        specs.append(
            {
                "source": match.group("source").strip(),
                "title": _field("title"),
                "url_path": _field("url_path"),
                "visibility": _field("visibility"),
            }
        )
    return specs


def test_visible_sidebar_labels_are_pinned():
    specs = _parse_specs()
    assert specs, "failed to parse _NavigationPageSpec entries from main_page.py"
    visible = [spec for spec in specs if spec["visibility"] is None]
    assert tuple(spec["title"] for spec in visible) == EXPECTED_VISIBLE_ENTRIES
    for spec in visible:
        assert spec["url_path"] == spec["title"], spec


def test_url_aliases_are_bounded_redirects():
    specs = _parse_specs()
    canonical_paths = {
        spec["url_path"] for spec in specs if "_page_file_runner" in str(spec["source"])
    }
    redirect_specs = [
        spec for spec in specs if "_navigation_redirect_runner" in str(spec["source"])
    ]
    redirect_paths = {spec["url_path"] for spec in redirect_specs}

    assert redirect_paths == EXPECTED_REDIRECT_ALIASES
    assert not (redirect_paths & canonical_paths)
    # Every canonical page has exactly one URL.
    canonical_specs = [
        spec for spec in specs if "_page_file_runner" in str(spec["source"])
    ]
    assert len(canonical_specs) == len(canonical_paths)


def test_page_titles_match_source_filenames():
    # Filenames must agree with the rendered title (numeric ordering prefixes
    # are legacy and carry no routing meaning; spaces map to underscores).
    file_titles = {
        "0_SETTINGS.py": "SETTINGS",
        "PROJECT.py": "PROJECT",
        "PROJECT_EDITOR.py": "PROJECT EDITOR",
        "2_ORCHESTRATE.py": "ORCHESTRATE",
        "3_WORKFLOW.py": "WORKFLOW",
        "4_ANALYSIS.py": "ANALYSIS",
    }
    page_files = {
        path.name for path in PAGES_ROOT.glob("*.py") if path.name != "__init__.py"
    }
    assert page_files == set(file_titles)
    for file_name, title in file_titles.items():
        stem = re.sub(r"^\d+_", "", Path(file_name).stem)
        assert stem == title.replace(" ", "_"), (file_name, title)
        assert f'_AGILAB_PAGES_ROOT / "{file_name}"' in MAIN_PAGE_SOURCE
