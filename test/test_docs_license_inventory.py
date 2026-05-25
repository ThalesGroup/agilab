from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "generate_docs_license_inventories.py"
DOCS_SOURCE = ROOT / "docs" / "source"


def _load_module():
    spec = importlib.util.spec_from_file_location("docs_license_inventory_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_license_inventory_specs_follow_package_split_contract() -> None:
    module = _load_module()

    spec_names = [spec.package.name for spec in module.inventory_specs(ROOT)]

    assert spec_names == [package.name for package in module.PACKAGE_CONTRACTS]


def test_license_inventory_filters_retired_local_packages() -> None:
    module = _load_module()

    rows = module._merge_packages(
        [
            {"name": "agi-env", "version": "2026.5.25", "license": ""},
            {"name": "agi-app-retired-demo", "version": "2026.5.1", "license": ""},
            {"name": "agilab-old-addon", "version": "2026.5.1", "license": ""},
            {"name": "numpy", "version": "2.3.5", "license": "BSD"},
        ]
    )

    assert [row["name"] for row in rows] == ["agi-env", "numpy"]
    assert rows[0]["license"] == module.LOCAL_PACKAGE_LICENSE


def test_license_docs_cover_public_package_split() -> None:
    module = _load_module()
    index = (DOCS_SOURCE / "license.rst").read_text(encoding="utf-8")
    specs = module.inventory_specs(ROOT)

    assert "tools/generate_docs_license_inventories.py" in index
    assert "tools/package_split_contract.py" in index
    assert "LICENSES/LICENSE-MIT-barviz-mod" in index

    for spec in specs:
        assert f"   {spec.package.name} <{spec.docname}>" in index
        page = DOCS_SOURCE / spec.output_name
        assert page.exists(), spec.output_name
        text = page.read_text(encoding="utf-8")
        assert module.GENERATED_MARKER in text
        assert f"Source package role: `{spec.package.role}`." in text
        assert "| Package Name | Version | License |" in text

    assert not (DOCS_SOURCE / "flight-telemetry-project-licenses.md").exists()
    assert not (DOCS_SOURCE / "mycode-project-licenses.md").exists()
