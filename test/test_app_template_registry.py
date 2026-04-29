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

from agilab.app_template_registry import (
    APP_TEMPLATE_SCHEMA,
    AppTemplateRegistry,
    AppTemplateSpec,
    discover_app_template,
    discover_app_templates,
)


def _write_template(root: Path, name: str, *, pyproject: bool = True, settings: bool = True) -> Path:
    template_root = root / name
    template_root.mkdir(parents=True)
    if pyproject:
        (template_root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    if settings:
        settings_path = template_root / "src" / "app_settings.toml"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text("[cluster]\ncluster_enabled=false\n", encoding="utf-8")
    return template_root


def test_discover_app_templates_returns_deterministic_template_specs(tmp_path: Path) -> None:
    z_template = _write_template(tmp_path, "z_app_template")
    a_template = _write_template(tmp_path, "a_app_template")
    _write_template(tmp_path, "not_a_template")

    registry = discover_app_templates(tmp_path)

    assert registry.names() == ("a_app_template", "z_app_template")
    assert registry.require("a_app_template").root_path == a_template.resolve()
    assert registry.require("z_app_template").settings_path == z_template.resolve() / "src" / "app_settings.toml"
    assert registry.require("a_app_template").schema == APP_TEMPLATE_SCHEMA


def test_discover_app_templates_can_require_manifest_and_settings(tmp_path: Path) -> None:
    _write_template(tmp_path, "complete_app_template")
    _write_template(tmp_path, "missing_settings_app_template", settings=False)
    _write_template(tmp_path, "missing_pyproject_app_template", pyproject=False)

    assert discover_app_templates(tmp_path).names() == ("complete_app_template", "missing_settings_app_template")
    assert discover_app_templates(tmp_path, require_settings=True).names() == ("complete_app_template",)
    assert discover_app_templates(tmp_path, require_pyproject=False).names() == (
        "complete_app_template",
        "missing_pyproject_app_template",
        "missing_settings_app_template",
    )


def test_discover_app_template_resolves_one_template(tmp_path: Path) -> None:
    template_root = _write_template(tmp_path, "demo_app_template")

    template = discover_app_template(tmp_path, "demo_app_template")

    assert template is not None
    assert template.root_path == template_root.resolve()
    assert template.pyproject_path == template_root.resolve() / "pyproject.toml"
    assert discover_app_template(tmp_path, "demo_app") is None
    assert discover_app_template(tmp_path, "missing_app_template") is None


def test_app_template_registry_selects_configured_names_without_duplicates(tmp_path: Path) -> None:
    first = AppTemplateSpec("first_app_template", tmp_path / "first", tmp_path / "first" / "pyproject.toml")
    second = AppTemplateSpec("second_app_template", tmp_path / "second", tmp_path / "second" / "pyproject.toml")
    registry = AppTemplateRegistry((second, first))

    selected = registry.select(("second_app_template", "first_app_template", "second_app_template", "missing"))

    assert registry.names() == ("first_app_template", "second_app_template")
    assert tuple(template.name for template in selected) == ("second_app_template", "first_app_template")
    assert registry.as_rows()[0]["schema"] == APP_TEMPLATE_SCHEMA


def test_app_template_registry_reports_invalid_unknown_and_duplicate_names(tmp_path: Path) -> None:
    first = AppTemplateSpec("demo_app_template", tmp_path / "a", tmp_path / "a" / "pyproject.toml")
    duplicate = AppTemplateSpec("demo_app_template", tmp_path / "b", tmp_path / "b" / "pyproject.toml")

    with pytest.raises(ValueError, match="must end with '_app_template'"):
        AppTemplateSpec("demo_app", tmp_path / "demo", tmp_path / "demo" / "pyproject.toml")
    with pytest.raises(ValueError, match="Duplicate app template"):
        AppTemplateRegistry((first, duplicate))
    with pytest.raises(KeyError, match="Unknown app template 'missing_app_template'"):
        AppTemplateRegistry((first,)).require("missing_app_template")
