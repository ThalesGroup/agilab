from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APPS_PAGES_ROOT = REPO_ROOT / "src/agilab/apps-pages"
DOCS_SOURCE = REPO_ROOT / "docs/source"


def test_apps_pages_catalog_documents_every_source_bundle() -> None:
    catalog = (DOCS_SOURCE / "apps-pages.rst").read_text(encoding="utf-8")
    page_modules = sorted(
        path.name
        for path in APPS_PAGES_ROOT.iterdir()
        if path.is_dir() and (path / "pyproject.toml").is_file()
    )

    assert page_modules
    for module_name in page_modules:
        assert f"``{module_name}``" in catalog
        assert f"{module_name}\n" in catalog
