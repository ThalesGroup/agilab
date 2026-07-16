from __future__ import annotations

import ast
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


def test_autoencoder_latentspace_is_marked_as_opt_in_playground_exception() -> None:
    texts = [
        (APPS_PAGES_ROOT / "README.md").read_text(encoding="utf-8"),
        (APPS_PAGES_ROOT / "autoencoder_latentspace" / "README.md").read_text(encoding="utf-8"),
        (DOCS_SOURCE / "apps-pages.rst").read_text(encoding="utf-8"),
        APPS_PAGES_GALLERY.read_text(encoding="utf-8"),
    ]

    for text in texts:
        assert "opt-in" in text.lower()
        assert "autoencoder" in text.lower()
        assert "in-page" in text.lower()


def test_view_prefix_remains_the_generic_page_family() -> None:
    docs = (DOCS_SOURCE / "apps-pages.rst").read_text(encoding="utf-8")
    readme = (APPS_PAGES_ROOT / "README.md").read_text(encoding="utf-8")

    for text in (docs, readme):
        assert "view_*" in text
        assert "generic app-agnostic sidecars" in text
        assert "app_ui" in text
        assert "autoencoder_latentspace" in text


def test_apps_pages_never_borrow_the_process_agienv_singleton() -> None:
    source_files = sorted(APPS_PAGES_ROOT.rglob("*.py"))
    offenders: list[str] = []
    for source_file in source_files:
        source = source_file.read_text(encoding="utf-8", errors="ignore")
        if (
            "AgiEnv.for_app(" in source
            or 'getattr(AgiEnv, "for_app"' in source
            or "AgiEnv.current()" in source
            or "AgiEnv(" in source
        ):
            offenders.append(str(source_file.relative_to(REPO_ROOT)))

    assert offenders == []


def test_barycentric_dataframe_selector_avoids_session_state_double_init() -> None:
    source = (
        APPS_PAGES_ROOT
        / "view_barycentric"
        / "src"
        / "view_barycentric"
        / "view_barycentric.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)

    dataframe_selectboxes = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "selectbox"
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == "sidebar"
        ):
            labels = [
                keyword.value.value
                for keyword in node.keywords
                if keyword.arg == "label"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
            ]
            if labels == ["DataFrame"]:
                dataframe_selectboxes.append(node)

    assert len(dataframe_selectboxes) == 1
    keywords = {keyword.arg: keyword for keyword in dataframe_selectboxes[0].keywords}
    key_value = keywords["key"].value
    assert isinstance(key_value, ast.Name)
    assert key_value.id == "DF_FILE_KEY"
    assert 'DF_FILE_KEY = _vb_key("df_file")' in source
    assert "index" not in keywords
    assert "args" not in keywords
