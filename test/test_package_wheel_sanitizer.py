from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path("tools/package_wheel_sanitizer.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("package_wheel_sanitizer_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_strip_packaged_core_uv_sources_removes_empty_source_section() -> None:
    module = _load_module()

    sanitized = module.strip_packaged_core_uv_sources(
        "\n".join(
            [
                "[project]",
                'name = "flight_project"',
                'dependencies = ["agi-env", "agi-node"]',
                "",
                "[tool.uv.sources]",
                'agi-env = { path = "../../../core/agi-env", editable = true }',
                'agi-node = { path = "../../../core/agi-node", editable = true }',
                "",
                "[build-system]",
                'requires = ["setuptools"]',
                "",
            ]
        )
    )

    assert "[tool.uv.sources]" not in sanitized
    assert 'dependencies = ["agi-env", "agi-node"]' in sanitized
    assert "[build-system]" in sanitized


def test_strip_packaged_core_uv_sources_preserves_non_core_sources() -> None:
    module = _load_module()

    sanitized = module.strip_packaged_core_uv_sources(
        "\n".join(
            [
                "[tool.uv.sources]",
                'agi-env = { path = "../../../core/agi-env", editable = true }',
                'demo-lib = { path = "../demo-lib", editable = true }',
                "",
            ]
        )
    )

    assert "agi-env" not in sanitized
    assert "[tool.uv.sources]" in sanitized
    assert "demo-lib" in sanitized


def test_sanitize_packaged_builtin_app_pyprojects_updates_build_tree(tmp_path: Path) -> None:
    module = _load_module()
    pyproject = tmp_path / "agilab/apps/builtin/flight_project/pyproject.toml"
    pyproject.parent.mkdir(parents=True)
    pyproject.write_text(
        "\n".join(
            [
                "[project]",
                'name = "flight_project"',
                'dependencies = ["agi-env"]',
                "",
                "[tool.uv.sources]",
                'agi-env = { path = "../../../core/agi-env", editable = true }',
                "",
            ]
        ),
        encoding="utf-8",
    )

    changed = module.sanitize_packaged_builtin_app_pyprojects(tmp_path)

    assert changed == [pyproject]
    assert "[tool.uv.sources]" not in pyproject.read_text(encoding="utf-8")
