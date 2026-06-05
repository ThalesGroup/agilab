from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APPS_PAGES_ROOT = REPO_ROOT / "src/agilab/apps-pages"
DOCS_SOURCE = REPO_ROOT / "docs/source"
APPS_PAGES_GALLERY = DOCS_SOURCE / "apps-pages-gallery.rst"
APPS_PAGES_GALLERY_ASSETS = DOCS_SOURCE / "_static/apps-pages-gallery"


def _page_modules() -> list[str]:
    return sorted(
        path.name
        for path in APPS_PAGES_ROOT.iterdir()
        if path.is_dir() and (path / "pyproject.toml").is_file()
    )


def test_apps_pages_catalog_documents_every_source_bundle() -> None:
    catalog = (DOCS_SOURCE / "apps-pages.rst").read_text(encoding="utf-8")
    page_modules = _page_modules()

    assert page_modules
    for module_name in page_modules:
        assert f"``{module_name}``" in catalog
        assert f"{module_name}\n" in catalog


def test_apps_pages_quality_bar_is_documented_and_enforced() -> None:
    page_modules = _page_modules()
    gallery = APPS_PAGES_GALLERY.read_text(encoding="utf-8")
    root_readme = (APPS_PAGES_ROOT / "README.md").read_text(encoding="utf-8")
    test_files = sorted((REPO_ROOT / "test").glob("test*.py"))

    assert page_modules
    for module_name in page_modules:
        page_root = APPS_PAGES_ROOT / module_name
        readme = page_root / "README.md"
        preview = APPS_PAGES_GALLERY_ASSETS / f"{module_name}.svg"
        source_files = sorted((page_root / "src" / module_name).glob("*.py"))
        direct_tests = [
            path
            for path in test_files
            if module_name in path.read_text(encoding="utf-8", errors="ignore")
        ]

        assert readme.is_file(), module_name
        readme_text = readme.read_text(encoding="utf-8")
        assert f"apps-pages-gallery/{module_name}.svg" in readme_text, module_name
        assert preview.is_file(), module_name
        assert f"_static/apps-pages-gallery/{module_name}.svg" in gallery, module_name
        assert f"**{module_name}**" in gallery, module_name
        assert f"apps-pages-gallery/{module_name}.svg" in root_readme, module_name
        assert direct_tests, module_name
        assert any(
            "agi_pages.runtime" in path.read_text(encoding="utf-8", errors="ignore")
            for path in source_files
        ), module_name
