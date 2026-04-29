from __future__ import annotations

from pathlib import Path
import sys

import pytest

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
SRC_PACKAGE = SRC_ROOT / "agilab"
sys.path.insert(0, str(SRC_ROOT))

import agilab as _agilab_package

if str(SRC_PACKAGE) not in _agilab_package.__path__:
    _agilab_package.__path__.insert(0, str(SRC_PACKAGE))

from agilab.page_bundle_registry import (
    PAGE_BUNDLE_SCHEMA,
    PageBundleRegistry,
    PageBundleSpec,
    configured_page_bundle_names,
    discover_page_bundle,
    discover_page_bundles,
    resolve_page_bundles,
)


def _write_bundle(root: Path, name: str, *, pyproject: bool = True, script_name: str | None = None) -> Path:
    bundle_root = root / name
    package_root = bundle_root / "src" / name
    package_root.mkdir(parents=True)
    if pyproject:
        (bundle_root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    script = package_root / (script_name or f"{name}.py")
    script.write_text("def main(): pass\n", encoding="utf-8")
    return script


def test_discover_page_bundles_supports_top_level_and_packaged_layouts(tmp_path: Path) -> None:
    top_level = tmp_path / "view_top.py"
    top_level.write_text("def main(): pass\n", encoding="utf-8")
    packaged_script = _write_bundle(tmp_path, "view_packaged")

    registry = discover_page_bundles(tmp_path)

    assert registry.names() == ("view_packaged", "view_top")
    assert registry.require("view_top").script_path == top_level.resolve()
    assert registry.require("view_packaged").script_path == packaged_script.resolve()
    assert registry.require("view_packaged").schema == PAGE_BUNDLE_SCHEMA


def test_discover_page_bundles_can_require_pyproject(tmp_path: Path) -> None:
    _write_bundle(tmp_path, "view_public", pyproject=True)
    _write_bundle(tmp_path, "view_private", pyproject=False)

    registry = discover_page_bundles(tmp_path, require_pyproject=True)

    assert registry.names() == ("view_public",)


def test_discover_page_bundle_supports_main_app_and_view_fallbacks(tmp_path: Path) -> None:
    main_script = _write_bundle(tmp_path, "view_main", script_name="main.py")
    fallback_root = tmp_path / "view_fallback" / "src" / "custom"
    fallback_root.mkdir(parents=True)
    fallback_script = fallback_root / "view_fallback_demo.py"
    fallback_script.write_text("def main(): pass\n", encoding="utf-8")

    assert discover_page_bundle(tmp_path, "view_main").script_path == main_script.resolve()
    assert discover_page_bundle(tmp_path, "view_fallback").script_path == fallback_script.resolve()
    assert discover_page_bundle(tmp_path, "missing") is None


def test_resolve_page_bundles_accepts_names_files_and_directories(tmp_path: Path) -> None:
    script = _write_bundle(tmp_path, "view_named")
    explicit_file = tmp_path / "custom_view.py"
    explicit_file.write_text("def main(): pass\n", encoding="utf-8")

    resolved = resolve_page_bundles(
        ("view_named", str(explicit_file), str(script.parents[2])),
        pages_root=tmp_path,
    )

    assert tuple(bundle.name for bundle in resolved) == ("view_named", "custom_view", "view_named")
    assert resolved[0].source == "discovered"
    assert resolved[1].source == "explicit_path"
    assert resolved[2].source == "explicit_path"


def test_page_bundle_registry_selects_configured_names_without_duplicates(tmp_path: Path) -> None:
    first = PageBundleSpec("view_first", tmp_path / "view_first", tmp_path / "view_first.py")
    second = PageBundleSpec("view_second", tmp_path / "view_second", tmp_path / "view_second.py")
    registry = PageBundleRegistry((second, first))

    selected = registry.select(("view_second", "view_first", "view_second", "missing"))

    assert registry.names() == ("view_first", "view_second")
    assert tuple(bundle.name for bundle in selected) == ("view_second", "view_first")
    assert registry.as_rows()[0]["schema"] == PAGE_BUNDLE_SCHEMA


def test_page_bundle_registry_reports_unknown_and_duplicate_names(tmp_path: Path) -> None:
    first = PageBundleSpec("view_demo", tmp_path / "a", tmp_path / "a.py")
    duplicate = PageBundleSpec("view_demo", tmp_path / "b", tmp_path / "b.py")

    with pytest.raises(ValueError, match="Duplicate apps-page bundle"):
        PageBundleRegistry((first, duplicate))
    with pytest.raises(KeyError, match="Unknown apps-page bundle 'missing'"):
        PageBundleRegistry((first,)).require("missing")


def test_configured_page_bundle_names_reads_default_and_view_module() -> None:
    settings = {
        "pages": {
            "default_view": "view_default",
            "view_module": ["view_extra", "view_default", "", 42],
        }
    }

    assert configured_page_bundle_names(settings) == ("view_default", "view_extra")
    assert configured_page_bundle_names({}) == ()
