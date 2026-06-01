from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tomllib
from types import SimpleNamespace

import pytest

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
SRC_PACKAGE = SRC_ROOT / "agilab"
sys.path.insert(0, str(SRC_ROOT))

import agilab as _agilab_package

if str(SRC_PACKAGE) not in _agilab_package.__path__:
    _agilab_package.__path__.insert(0, str(SRC_PACKAGE))

import agilab.page_bundle_registry as page_registry
from agilab.page_bundle_registry import (
    PAGE_BUNDLE_SCHEMA,
    PAGE_TEMPLATE_SCHEMA,
    PageBundleRegistry,
    PageBundleSpec,
    PageTemplateRegistry,
    PageTemplateSpec,
    clear_page_bundle_discovery_cache,
    configured_page_bundle_names,
    discover_page_bundle,
    discover_page_bundles,
    discover_page_template,
    discover_page_templates,
    resolve_page_bundles,
)
from agilab.template_contracts import (
    TEMPLATE_CONTRACT_SCHEMA,
    load_optional_template_contract,
    load_template_contract,
    missing_required_files,
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


def test_discover_page_bundles_reuses_cache_until_directory_signature_changes(tmp_path: Path) -> None:
    clear_page_bundle_discovery_cache()
    _write_bundle(tmp_path, "view_first")

    first = discover_page_bundles(tmp_path)
    second = discover_page_bundles(tmp_path)

    assert second is first

    top_level = tmp_path / "view_second.py"
    top_level.write_text("def main(): pass\n", encoding="utf-8")

    third = discover_page_bundles(tmp_path)

    assert third is not first
    assert third.names() == ("view_first", "view_second")
    clear_page_bundle_discovery_cache()


def test_discover_page_bundles_cache_can_be_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_page_bundle_discovery_cache()
    monkeypatch.setenv("AGILAB_DISABLE_UI_DISCOVERY_CACHE", "1")
    _write_bundle(tmp_path, "view_first")

    first = discover_page_bundles(tmp_path)
    second = discover_page_bundles(tmp_path)

    assert second is not first
    clear_page_bundle_discovery_cache()


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


def test_page_bundle_discovery_and_resolution_edge_cases(tmp_path: Path) -> None:
    assert discover_page_bundles(object()).names() == ()
    assert discover_page_templates(object()).names() == ()
    assert discover_page_bundle(object(), "view_demo") is None
    assert discover_page_bundle(tmp_path, "") is None
    assert discover_page_template(object(), "demo_page_template") is None
    assert discover_page_template(tmp_path, "not_a_template") is None
    assert discover_page_template(tmp_path, "missing_page_template") is None

    pages_root = tmp_path / "pages"
    pages_root.mkdir()
    (pages_root / "__init__.py").write_text("", encoding="utf-8")
    (pages_root / ".hidden.py").write_text("", encoding="utf-8")
    (pages_root / ".hidden").mkdir()
    direct = pages_root / "view_direct.py"
    direct.write_text("def main(): pass\n", encoding="utf-8")
    no_entry = pages_root / "view_no_entry"
    no_entry.mkdir()
    (no_entry / "pyproject.toml").write_text("[project]\nname='view_no_entry'\n", encoding="utf-8")
    app_bundle = pages_root / "view_app"
    app_bundle.mkdir()
    app_script = app_bundle / "app.py"
    app_script.write_text("def main(): pass\n", encoding="utf-8")
    contractless = pages_root / "view_contractless"
    (contractless / "src" / "view_contractless").mkdir(parents=True)
    (contractless / "src" / "view_contractless" / "view_contractless.py").write_text(
        "def main(): pass\n",
        encoding="utf-8",
    )

    registry = discover_page_bundles(pages_root)
    assert registry.names() == ("view_app", "view_contractless", "view_direct")
    assert discover_page_bundle(pages_root, "view_direct").script_path == direct.resolve()
    assert discover_page_bundle(pages_root, "view_no_entry") is None
    assert discover_page_bundle(pages_root, "view_contractless", require_contract=True) is None
    assert discover_page_bundle(pages_root, "view_no_entry", require_pyproject=True) is None
    assert discover_page_bundle(pages_root, "view_app").script_path == app_script.resolve()

    templates_root = tmp_path / "templates"
    templates_root.mkdir()
    (templates_root / "not_a_template").mkdir()
    missing_pyproject = templates_root / "missing_page_template"
    missing_pyproject.mkdir()
    missing_contract = templates_root / "missing_contract_page_template"
    missing_contract.mkdir()
    (missing_contract / "pyproject.toml").write_text("[project]\nname='missing-contract'\n", encoding="utf-8")
    complete = templates_root / "complete_page_template"
    complete.mkdir()
    (complete / "pyproject.toml").write_text("[project]\nname='complete'\n", encoding="utf-8")

    assert discover_page_templates(templates_root).names() == ()
    assert discover_page_template(templates_root, "missing_page_template") is None
    assert discover_page_template(templates_root, "missing_contract_page_template") is None
    assert discover_page_template(templates_root, "complete_page_template", require_contract=False) is not None
    assert discover_page_templates(templates_root, require_contract=False).names() == (
        "complete_page_template",
        "missing_contract_page_template",
    )

    with pytest.raises(ValueError, match="Unknown apps-page bundle"):
        resolve_page_bundles((" ", "missing"), pages_root=pages_root)
    with pytest.raises(ValueError, match="no supported entrypoint"):
        resolve_page_bundles((str(no_entry),), pages_root=pages_root)


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


def test_page_bundle_and_template_registries_cover_edge_helpers(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="non-empty string"):
        PageBundleSpec("  ", tmp_path / "root", tmp_path / "root.py")

    contract = SimpleNamespace(template_version=7)
    bundle = PageBundleSpec(
        " view_demo ",
        str(tmp_path / "root"),
        str(tmp_path / "root" / "view_demo.py"),
        contract_path=str(tmp_path / "root" / "agilab.template.toml"),
        contract=contract,
    )
    registry = PageBundleRegistry((bundle,))

    assert bundle.name == "view_demo"
    assert bundle.root_path == tmp_path / "root"
    assert bundle.script_path == tmp_path / "root" / "view_demo.py"
    assert bundle.contract_path == tmp_path / "root" / "agilab.template.toml"
    assert bundle.as_row()["template_version"] == "7"
    assert "view_demo" in registry
    assert object() not in registry
    assert len(registry) == 1
    assert tuple(registry) == (bundle,)
    assert registry.bundles == (bundle,)
    assert registry.get("missing", "fallback") == "fallback"

    template_contract = SimpleNamespace(kind="page", template_version=3)
    template = PageTemplateSpec(
        " demo_page_template ",
        str(tmp_path / "template"),
        str(tmp_path / "template" / "pyproject.toml"),
        contract_path=str(tmp_path / "template" / "agilab.template.toml"),
        contract=template_contract,
    )
    template_registry = PageTemplateRegistry((template,))
    assert template.name == "demo_page_template"
    assert template.root_path == tmp_path / "template"
    assert template.pyproject_path == tmp_path / "template" / "pyproject.toml"
    assert template.contract_path == tmp_path / "template" / "agilab.template.toml"
    assert template.as_row()["template_kind"] == "page"
    assert template.as_row()["template_version"] == "3"
    assert "DEMO_PAGE_TEMPLATE" in template_registry
    assert object() not in template_registry
    assert len(template_registry) == 1
    assert tuple(template_registry) == (template,)
    assert template_registry.templates == (template,)
    assert template_registry.get("missing", "fallback") == "fallback"
    assert template_registry.select(("missing", "", "demo_page_template", "DEMO_PAGE_TEMPLATE")) == (template,)
    assert template_registry.as_rows()[0]["schema"] == PAGE_TEMPLATE_SCHEMA
    with pytest.raises(ValueError, match="Duplicate page template"):
        PageTemplateRegistry((template, template))
    with pytest.raises(KeyError, match="Unknown page template 'missing'"):
        template_registry.require("missing")


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


def test_discover_page_templates_reuses_cache_until_directory_signature_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_page_bundle_discovery_cache()
    monkeypatch.delenv("AGILAB_DISABLE_UI_DISCOVERY_CACHE", raising=False)
    template_root = tmp_path / "first_page_template"
    template_root.mkdir()
    (template_root / "pyproject.toml").write_text("[project]\nname='first'\n", encoding="utf-8")
    _write_contract(template_root)

    first = discover_page_templates(tmp_path)
    second = discover_page_templates(tmp_path)

    assert second is first

    second_template = tmp_path / "second_page_template"
    second_template.mkdir()
    (second_template / "pyproject.toml").write_text("[project]\nname='second'\n", encoding="utf-8")
    _write_contract(second_template)
    third = discover_page_templates(tmp_path)

    assert third is not first
    assert third.names() == ("first_page_template", "second_page_template")
    clear_page_bundle_discovery_cache()


def test_discover_page_templates_cache_can_be_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_page_bundle_discovery_cache()
    monkeypatch.setenv("AGILAB_DISABLE_UI_DISCOVERY_CACHE", "1")
    template_root = tmp_path / "analysis_page_template"
    template_root.mkdir()
    (template_root / "pyproject.toml").write_text("[project]\nname='analysis'\n", encoding="utf-8")
    _write_contract(template_root)

    first = discover_page_templates(tmp_path)
    second = discover_page_templates(tmp_path)

    assert second is not first
    assert first.names() == ("analysis_page_template",)
    clear_page_bundle_discovery_cache()


def test_template_contract_helpers_handle_missing_and_malformed_optional_fields(tmp_path: Path) -> None:
    assert load_optional_template_contract(tmp_path) == (None, None)

    contract_path = tmp_path / "agilab.template.toml"
    contract_path.write_text(
        "\n".join(
            [
                f'schema = "{TEMPLATE_CONTRACT_SCHEMA}"',
                'kind = "page"',
                'template_version = "bad"',
                'package_name_pattern = " view-{page_slug} "',
                'entrypoint = " src/view_demo/view_demo.py "',
                'files = "not-a-table"',
            ]
        ),
        encoding="utf-8",
    )

    loaded_path, contract = load_optional_template_contract(tmp_path)

    assert loaded_path == contract_path.resolve()
    assert contract == load_template_contract(contract_path)
    assert contract is not None
    assert contract.template_version == 0
    assert contract.required_files == ()
    assert contract.package_name_pattern == "view-{page_slug}"
    assert contract.entrypoint == "src/view_demo/view_demo.py"


def test_missing_required_files_reports_absent_contract_files(tmp_path: Path) -> None:
    contract_path = _write_contract(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    contract = load_template_contract(contract_path)

    assert missing_required_files(tmp_path, contract) == ("src/view_demo/view_demo.py",)


def test_configured_page_bundle_names_reads_default_and_view_module() -> None:
    settings = {
        "pages": {
            "default_view": "view_default",
            "view_module": ["view_extra", "view_default", "", 42],
        }
    }

    assert configured_page_bundle_names(settings) == ("view_default", "view_extra")
    assert configured_page_bundle_names({}) == ()
    assert configured_page_bundle_names({"pages": {"default_view": " ", "view_module": ("view_tuple",)}}) == ()


def test_resolve_page_bundles_uses_direct_discovery_fallback(tmp_path: Path, monkeypatch) -> None:
    script = tmp_path / "view_dynamic.py"
    script.write_text("def main(): pass\n", encoding="utf-8")
    dynamic = PageBundleSpec("view_dynamic", tmp_path, script)

    monkeypatch.setattr(page_registry, "discover_page_bundles", lambda *_args, **_kwargs: PageBundleRegistry())
    monkeypatch.setattr(page_registry, "discover_page_bundle", lambda *_args, **_kwargs: dynamic)

    assert resolve_page_bundles(("view_dynamic",), pages_root=tmp_path) == (dynamic,)


def test_page_bundle_cache_keys_cover_error_and_signature_edges(tmp_path: Path, monkeypatch) -> None:
    clear_page_bundle_discovery_cache()
    pages_root = tmp_path / "pages"
    pages_root.mkdir()
    hidden = pages_root / ".hidden.py"
    hidden.write_text("def main(): pass\n", encoding="utf-8")
    direct = pages_root / "view_direct.py"
    direct.write_text("def main(): pass\n", encoding="utf-8")
    bundle_root = pages_root / "view_bundle"
    view_dir = bundle_root / "src" / "custom"
    view_dir.mkdir(parents=True)
    view_file = view_dir / "view_custom.py"
    view_file.write_text("def main(): pass\n", encoding="utf-8")
    src_note = bundle_root / "src" / "notes.txt"
    src_note.write_text("not a package\n", encoding="utf-8")
    root_note = pages_root / "README.txt"
    root_note.write_text("not a page\n", encoding="utf-8")
    template_root = tmp_path / "templates"
    template_root.mkdir()
    template = template_root / "analysis_page_template"
    template.mkdir()
    _write_contract(template)

    bundle_key = page_registry._page_bundle_discovery_cache_key(
        pages_root,
        require_pyproject=False,
        require_contract=False,
    )
    template_key = page_registry._page_template_discovery_cache_key(
        template_root,
        require_pyproject=False,
        require_contract=False,
    )

    assert any(signature[0] == "view_direct.py" for signature in bundle_key[3])
    assert any(signature[0].endswith("view_custom.py") for signature in bundle_key[3])
    assert any(signature[0].endswith("notes.txt") for signature in bundle_key[3])
    assert any(signature[0].startswith("analysis_page_template/") for signature in template_key[3])

    original_iterdir = Path.iterdir
    original_glob = Path.glob
    original_stat_signature = page_registry._stat_signature

    def fail_iterdir_for_selected(path: Path):
        if path in {pages_root, template_root, bundle_root / "src"}:
            raise OSError("cannot scan")
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", fail_iterdir_for_selected)

    assert page_registry._page_bundle_dir_signature(bundle_root)
    assert page_registry._page_bundle_discovery_cache_key(
        pages_root,
        require_pyproject=False,
        require_contract=False,
    )[3]
    assert page_registry._page_template_discovery_cache_key(
        template_root,
        require_pyproject=False,
        require_contract=False,
    )[3]

    monkeypatch.setattr(Path, "iterdir", original_iterdir)

    def fail_glob_for_view_dir(path: Path, pattern: str):
        if path == view_dir:
            raise OSError("cannot glob")
        return original_glob(path, pattern)

    monkeypatch.setattr(Path, "glob", fail_glob_for_view_dir)
    assert page_registry._page_bundle_dir_signature(bundle_root)
    monkeypatch.setattr(Path, "glob", original_glob)

    missing_signature_paths = {pages_root, template_root, direct, view_dir, view_file, src_note}

    def missing_signature_for_selected(path: Path, *, label: str | None = None):
        if path in missing_signature_paths:
            return None
        return original_stat_signature(path, label=label)

    monkeypatch.setattr(page_registry, "_stat_signature", missing_signature_for_selected)

    no_signature_bundle_key = page_registry._page_bundle_discovery_cache_key(
        pages_root,
        require_pyproject=False,
        require_contract=False,
    )
    no_signature_template_key = page_registry._page_template_discovery_cache_key(
        template_root,
        require_pyproject=False,
        require_contract=False,
    )

    assert not any(signature[0] == "view_direct.py" for signature in no_signature_bundle_key[3])
    assert not any(signature[0].endswith("view_custom.py") for signature in no_signature_bundle_key[3])
    assert not any(signature[0] == "." for signature in no_signature_template_key[3])


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
    (pages_root / "__init__.py").write_text("", encoding="utf-8")
    (pages_root / ".hidden.py").write_text("def main(): pass\n", encoding="utf-8")
    top_level = pages_root / "view_top.py"
    top_level.write_text("def main(): pass\n", encoding="utf-8")
    duplicate_source_dir = pages_root / "view_top"
    duplicate_source_dir.mkdir()
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
def test_page_provider_installed_resolution_covers_edge_fallbacks(
    provider_name: str,
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = _load_page_provider(provider_name)
    valid_root = tmp_path / "site-packages" / "view_valid"
    valid_root.mkdir(parents=True)
    valid_script = valid_root / "view_valid.py"
    valid_script.write_text("def main(): pass\n", encoding="utf-8")
    no_script_root = tmp_path / "site-packages" / "view_no_script"
    no_script_root.mkdir(parents=True)
    invalid_location = tmp_path / "site-packages" / "view_invalid_location"

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
                FakeEntryPoint("ignored", valid_root),
                FakeEntryPoint("view_no_script", no_script_root),
                FakeEntryPoint("view_valid", valid_root),
                FakeEntryPoint("view_valid", valid_root),
            )
        ),
    )
    monkeypatch.setattr(provider, "PUBLIC_PAGE_MODULES", ())

    assert provider.resolve_bundle("view_valid", pages_root=tmp_path / "stale").script_path == valid_script.resolve()
    assert provider.resolve_bundle("view_no_script", pages_root=tmp_path / "stale") is None
    assert tuple(bundle.name for bundle in provider._iter_installed_bundles()) == ("view_valid",)
    assert provider._bundle_from_installed_module("") is None

    def fake_find_spec(name: str):
        if name == "view_valid":
            return SimpleNamespace(submodule_search_locations=[str(invalid_location), str(valid_root)])
        if name == "view_no_script":
            return SimpleNamespace(submodule_search_locations=[str(no_script_root)])
        if name == "raise":
            raise ValueError("bad module")
        return None

    monkeypatch.setattr(provider.importlib.metadata, "entry_points", lambda: FakeEntryPoints(()))
    monkeypatch.setattr(provider.importlib.util, "find_spec", fake_find_spec)

    assert provider._bundle_from_installed_module("raise") is None
    assert provider._bundle_from_installed_module("view_no_script") is None
    assert provider._bundle_from_installed_module("view_valid").script_path == valid_script.resolve()


@pytest.mark.parametrize("provider_name", sorted(PAGE_PROVIDER_PATHS))
def test_page_provider_public_modules_and_root_error_branches(
    provider_name: str,
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = _load_page_provider(provider_name)
    public_root = tmp_path / "site-packages" / "view_public"
    public_root.mkdir(parents=True)
    public_script = public_root / "view_public.py"
    public_script.write_text("def main(): pass\n", encoding="utf-8")

    monkeypatch.setattr(provider.importlib.metadata, "entry_points", lambda: ())
    monkeypatch.setattr(provider, "PUBLIC_PAGE_MODULES", ("view_public",))
    monkeypatch.setattr(
        provider.importlib.util,
        "find_spec",
        lambda name: SimpleNamespace(submodule_search_locations=[str(public_root)])
        if name == "view_public"
        else None,
    )

    bundles = provider._iter_installed_bundles()

    assert tuple(bundle.name for bundle in bundles) == ("view_public",)
    assert bundles[0].script_path == public_script.resolve()

    class BrokenRoot:
        def exists(self):
            return True

        def is_dir(self):
            return True

        def glob(self, _pattern: str):
            return ()

        def iterdir(self):
            raise OSError("cannot scan")

    class BrokenScript:
        def resolve(self, *, strict: bool = False):
            raise OSError("cannot resolve")

    assert provider._has_bundle_payload(BrokenRoot()) is False
    assert provider._inline_renderer_target(BrokenScript()) == ""


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
    (directory_payload / "empty").mkdir()

    assert provider._has_bundle_payload(tmp_path / "missing") is False
    assert provider._has_bundle_payload(empty_root) is False
    assert provider._has_bundle_payload(fallback_root) is True
    assert provider._has_bundle_payload(directory_payload) is True
    assert provider._source_checkout_bundle_roots(package_root)

    monkeypatch.setattr(provider, "_has_bundle_payload", lambda root: root == package_root)
    assert provider.bundles_root() == package_root

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

    pyproject = tomllib.loads((template.root_path / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = pyproject["project"]["dependencies"]
    assert pyproject["project"]["requires-python"] == ">=3.11"
    assert "streamlit>=1.58,<2" in dependencies
    assert any(dependency.startswith("agi-env>=") for dependency in dependencies)

    entrypoint_text = (template.root_path / template.contract.entrypoint).read_text(encoding="utf-8")
    assert "def get_docs_menu_items" in entrypoint_text
    assert "--active-app" in entrypoint_text
