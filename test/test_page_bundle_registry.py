from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
SRC_PACKAGE = SRC_ROOT / "agilab"
sys.path.insert(0, str(SRC_ROOT))

import agilab as _agilab_package

if str(SRC_PACKAGE) not in _agilab_package.__path__:
    _agilab_package.__path__.insert(0, str(SRC_PACKAGE))

from agilab.page_bundle_registry import (
    PAGE_BUNDLE_SCHEMA,
    PAGE_TEMPLATE_SCHEMA,
    PageBundleRegistry,
    PageBundleSpec,
    PageTemplateRegistry,
    PageTemplateSpec,
    configured_page_bundle_names,
    discover_page_bundle,
    discover_page_bundles,
    discover_page_template,
    discover_page_templates,
    resolve_page_bundles,
)
from agilab.template_contracts import TEMPLATE_CONTRACT_SCHEMA, missing_required_files


def _write_bundle(root: Path, name: str, *, pyproject: bool = True, script_name: str | None = None) -> Path:
    bundle_root = root / name
    package_root = bundle_root / "src" / name
    package_root.mkdir(parents=True)
    if pyproject:
        (bundle_root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    script = package_root / (script_name or f"{name}.py")
    script.write_text("def main(): pass\n", encoding="utf-8")
    return script


def _write_contract(root: Path, *, kind: str = "page") -> Path:
    contract_path = root / "agilab.template.toml"
    contract_path.write_text(
        "\n".join(
            [
                f'schema = "{TEMPLATE_CONTRACT_SCHEMA}"',
                f'kind = "{kind}"',
                "template_version = 1",
                'package_name_pattern = "view-{page_slug}"',
                'entrypoint = "src/view_demo/view_demo.py"',
                "",
                "[files]",
                'required = ["pyproject.toml", "src/view_demo/view_demo.py"]',
                "",
            ]
        ),
        encoding="utf-8",
    )
    return contract_path


PAGE_PROVIDER_PATHS = {
    "agi_pages": Path(__file__).resolve().parents[1] / "src/agilab/lib/agi-pages/src/agi_pages/__init__.py",
    "apps_pages": Path(__file__).resolve().parents[1] / "src/agilab/apps-pages/__init__.py",
}


def _load_page_provider(provider_name: str):
    provider_path = PAGE_PROVIDER_PATHS[provider_name]
    spec = importlib.util.spec_from_file_location(f"{provider_name}_provider_test_module", provider_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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


def test_discover_page_bundle_loads_contract_metadata(tmp_path: Path) -> None:
    script = _write_bundle(tmp_path, "view_demo")
    contract_path = _write_contract(script.parents[2])

    bundle = discover_page_bundle(tmp_path, "view_demo", require_contract=True)

    assert bundle is not None
    assert bundle.contract_path == contract_path.resolve()
    assert bundle.contract is not None
    assert bundle.contract.kind == "page"
    assert bundle.as_row()["template_version"] == "1"


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


def test_page_template_registry_discovers_contract_templates(tmp_path: Path) -> None:
    template_root = tmp_path / "analysis_page_template"
    package_root = template_root / "src" / "view_demo"
    package_root.mkdir(parents=True)
    (template_root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    script = package_root / "view_demo.py"
    script.write_text("def main(): pass\n", encoding="utf-8")
    contract_path = _write_contract(template_root)

    registry = discover_page_templates(tmp_path)
    template = registry.require("analysis_page_template")

    assert isinstance(registry, PageTemplateRegistry)
    assert template.schema == PAGE_TEMPLATE_SCHEMA
    assert template.contract_path == contract_path.resolve()
    assert template.contract is not None
    assert missing_required_files(template.root_path, template.contract) == ()
    assert template.as_row()["template_kind"] == "page"
    assert discover_page_template(tmp_path, "analysis_page_template") == template
    with pytest.raises(ValueError, match="must end with '_page_template'"):
        PageTemplateSpec("analysis_page", tmp_path / "x", tmp_path / "x" / "pyproject.toml")


def test_configured_page_bundle_names_reads_default_and_view_module() -> None:
    settings = {
        "pages": {
            "default_view": "view_default",
            "view_module": ["view_extra", "view_default", "", 42],
        }
    }

    assert configured_page_bundle_names(settings) == ("view_default", "view_extra")
    assert configured_page_bundle_names({}) == ()


@pytest.mark.parametrize("provider_name", sorted(PAGE_PROVIDER_PATHS))
def test_page_provider_resolves_scripts_and_inline_renderers(provider_name: str, tmp_path: Path) -> None:
    provider = _load_page_provider(provider_name)
    script = _write_bundle(tmp_path, "view_demo")
    inline = script.with_name("notebook_inline.py")
    inline.write_text("def render_inline(): pass\n", encoding="utf-8")

    bundle = provider.resolve_bundle("view_demo", pages_root=tmp_path)

    assert bundle is not None
    assert bundle.script_path == script.resolve()
    assert bundle.inline_renderer == f"{inline.resolve()}:render_inline"
    assert provider.script_path("view_demo", pages_root=tmp_path) == script.resolve()
    assert provider.inline_renderer_target("view_demo", pages_root=tmp_path).endswith(
        "notebook_inline.py:render_inline"
    )
    assert provider.iter_bundles(tmp_path)[0].as_dict()["module"] == "view_demo"


@pytest.mark.parametrize("provider_name", sorted(PAGE_PROVIDER_PATHS))
def test_page_provider_resolves_installed_entry_point_when_source_root_is_stale(
    provider_name: str,
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = _load_page_provider(provider_name)
    package_root = tmp_path / "site-packages" / "view_maps"
    package_root.mkdir(parents=True)
    script = package_root / "view_maps.py"
    script.write_text("def main(): pass\n", encoding="utf-8")

    class FakeEntryPoint:
        name = "view_maps"

        @staticmethod
        def load():
            return lambda: package_root

    class FakeEntryPoints(tuple):
        def select(self, *, group: str):
            if group == provider.PAGE_BUNDLE_ENTRYPOINT_GROUP:
                return self
            return ()

    monkeypatch.setattr(
        provider.importlib.metadata,
        "entry_points",
        lambda: FakeEntryPoints((FakeEntryPoint(),)),
    )

    bundle = provider.resolve_bundle("view_maps", pages_root=tmp_path / "stale-apps-pages")

    assert bundle is not None
    assert bundle.root_path == package_root.resolve()
    assert bundle.script_path == script.resolve()


@pytest.mark.parametrize("provider_name", sorted(PAGE_PROVIDER_PATHS))
def test_page_provider_iter_bundles_deduplicates_source_and_installed_bundles(
    provider_name: str,
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = _load_page_provider(provider_name)
    pages_root = tmp_path / "apps-pages"
    pages_root.mkdir()
    top_level = pages_root / "view_top.py"
    top_level.write_text("def main(): pass\n", encoding="utf-8")
    packaged_script = _write_bundle(pages_root, "view_packaged")
    installed_root = tmp_path / "site-packages" / "view_installed"
    installed_root.mkdir(parents=True)
    installed_script = installed_root / "view_installed.py"
    installed_script.write_text("def main(): pass\n", encoding="utf-8")
    duplicate_installed_root = tmp_path / "site-packages" / "view_top"
    duplicate_installed_root.mkdir(parents=True)
    (duplicate_installed_root / "view_top.py").write_text("def main(): pass\n", encoding="utf-8")

    class FakeEntryPoint:
        def __init__(self, name: str, root: Path):
            self.name = name
            self._root = root

        def load(self):
            return lambda: self._root

    class FakeEntryPoints(tuple):
        def select(self, *, group: str):
            if group == provider.PAGE_BUNDLE_ENTRYPOINT_GROUP:
                return self
            return ()

    monkeypatch.setattr(
        provider.importlib.metadata,
        "entry_points",
        lambda: FakeEntryPoints(
            (
                FakeEntryPoint("view_installed", installed_root),
                FakeEntryPoint("view_top", duplicate_installed_root),
            )
        ),
    )
    monkeypatch.setattr(provider, "bundles_root", lambda: pages_root)
    monkeypatch.setattr(provider, "PUBLIC_PAGE_MODULES", ())

    explicit_bundles = provider.iter_bundles(pages_root)
    default_bundles = provider.iter_bundles()

    assert tuple(bundle.name for bundle in explicit_bundles) == ("view_packaged", "view_top")
    assert provider.resolve_bundle("view_top", pages_root=pages_root).script_path == top_level.resolve()
    assert provider.resolve_bundle("view_packaged", pages_root=pages_root).script_path == packaged_script.resolve()
    assert tuple(bundle.name for bundle in default_bundles) == ("view_installed", "view_packaged", "view_top")
    assert provider.resolve_bundle("view_installed", pages_root=pages_root / "stale").script_path == installed_script.resolve()


@pytest.mark.parametrize("provider_name", sorted(PAGE_PROVIDER_PATHS))
def test_page_provider_installed_module_fallback_and_invalid_inputs(
    provider_name: str,
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = _load_page_provider(provider_name)
    module_root = tmp_path / "site-packages" / "view_module"
    module_root.mkdir(parents=True)
    script = module_root / "view_module.py"
    script.write_text("def main(): pass\n", encoding="utf-8")

    monkeypatch.setattr(provider.importlib.metadata, "entry_points", lambda: ())
    monkeypatch.setattr(
        provider.importlib.util,
        "find_spec",
        lambda name: SimpleNamespace(submodule_search_locations=[str(module_root)])
        if name == "view_module"
        else None,
    )

    assert provider.resolve_bundle("", pages_root=tmp_path) is None
    assert provider.resolve_bundle("missing", pages_root=object()) is None
    assert provider.resolve_bundle("view_module", pages_root=tmp_path / "stale").script_path == script.resolve()
    assert provider.script_path("missing", pages_root=tmp_path) is None
    assert provider.inline_renderer_target("missing", pages_root=tmp_path) == ""


@pytest.mark.parametrize("provider_name", sorted(PAGE_PROVIDER_PATHS))
def test_page_provider_handles_broken_entry_points_and_mapping_api(
    provider_name: str,
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = _load_page_provider(provider_name)
    valid_root = tmp_path / "view_valid"
    valid_root.mkdir()
    valid_script = valid_root / "view_valid.py"
    valid_script.write_text("def main(): pass\n", encoding="utf-8")

    class FakeEntryPoint:
        def __init__(self, name: str, value):
            self.name = name
            self._value = value

        def load(self):
            if isinstance(self._value, Exception):
                raise self._value
            return self._value

    monkeypatch.setattr(
        provider.importlib.metadata,
        "entry_points",
        lambda: {
            provider.PAGE_BUNDLE_ENTRYPOINT_GROUP: (
                FakeEntryPoint("", lambda: valid_root),
                FakeEntryPoint("broken", RuntimeError("boom")),
                FakeEntryPoint("missing", lambda: tmp_path / "missing"),
                FakeEntryPoint("view_valid", lambda: valid_root),
            )
        },
    )
    monkeypatch.setattr(provider, "PUBLIC_PAGE_MODULES", ("view_valid", "missing_module"))
    monkeypatch.setattr(provider.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(provider, "bundles_root", lambda: tmp_path / "not-a-source-root")

    bundles = provider.iter_bundles()

    assert tuple(bundle.name for bundle in bundles) == ("view_valid",)
    assert bundles[0].script_path == valid_script.resolve()

    monkeypatch.setattr(provider.importlib.metadata, "entry_points", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert provider.iter_bundles() == ()


@pytest.mark.parametrize("provider_name", sorted(PAGE_PROVIDER_PATHS))
def test_page_provider_root_helpers_cover_payload_and_checkout_fallbacks(
    provider_name: str,
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = _load_page_provider(provider_name)
    package_root = Path(provider.__file__).resolve().parent
    fallback_root = tmp_path / "apps-pages"
    fallback_root.mkdir()
    (fallback_root / "view_fallback.py").write_text("def main(): pass\n", encoding="utf-8")
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    (empty_root / "__init__.py").write_text("", encoding="utf-8")
    directory_payload = tmp_path / "directory-payload"
    _write_bundle(directory_payload, "view_directory")

    assert provider._has_bundle_payload(tmp_path / "missing") is False
    assert provider._has_bundle_payload(empty_root) is False
    assert provider._has_bundle_payload(fallback_root) is True
    assert provider._has_bundle_payload(directory_payload) is True
    assert provider._source_checkout_bundle_roots(package_root)

    monkeypatch.setattr(provider, "_has_bundle_payload", lambda root: root == fallback_root)
    monkeypatch.setattr(provider, "_source_checkout_bundle_roots", lambda root: (tmp_path / "missing", fallback_root))
    assert provider.bundles_root() == fallback_root

    monkeypatch.setattr(provider, "_has_bundle_payload", lambda root: False)
    assert provider.bundles_root() == package_root


def test_repository_analysis_page_template_is_complete() -> None:
    templates_root = Path(__file__).resolve().parents[1] / "src/agilab/apps-pages/templates"

    registry = discover_page_templates(templates_root)
    template = registry.require("analysis_page_template")

    assert template.contract is not None
    assert template.contract.schema == TEMPLATE_CONTRACT_SCHEMA
    assert template.contract.kind == "page"
    assert template.contract.package_name_pattern == "view-{page_slug}"
    assert (template.root_path / template.contract.entrypoint).is_file()
    assert missing_required_files(template.root_path, template.contract) == ()
