from __future__ import annotations

import importlib.util
import json
import subprocess
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


def test_licensecheck_compat_script_uses_declared_console_entrypoint(tmp_path: Path) -> None:
    module = _load_module()
    package = tmp_path / "licensecheck"
    package.mkdir()
    (package / "__init__.py").write_text(
        "import json, sys\n"
        "def cli():\n"
        "    assert sys.argv[1:] == ['--format', 'json']\n"
        "    from license_expression import LicenseWithExceptionSymbol\n"
        "    from types import SimpleNamespace\n"
        "    symbol = LicenseWithExceptionSymbol()\n"
        "    symbol.license_symbol = SimpleNamespace(key='GPL-2.0-only')\n"
        "    symbol.exception_symbol = SimpleNamespace(key='Classpath-exception-2.0')\n"
        "    assert symbol.key == 'GPL-2.0-only WITH Classpath-exception-2.0'\n"
        "    print(json.dumps({'packages': [], 'info': {'version': '2026.0.8'}}))\n"
        "    return 0\n",
        encoding="utf-8",
    )
    (tmp_path / "license_expression.py").write_text(
        "class LicenseWithExceptionSymbol:\n    pass\n", encoding="utf-8"
    )
    metadata = tmp_path / "licensecheck-2026.0.8.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: licensecheck\nVersion: 2026.0.8\n", encoding="utf-8"
    )
    (metadata / "entry_points.txt").write_text(
        "[console_scripts]\nlicensecheck = licensecheck:cli\n", encoding="utf-8"
    )
    result = subprocess.run(
        [sys.executable, "-c", module.LICENSECHECK_COMPAT_SCRIPT, "--format", "json"],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["info"]["version"] == "2026.0.8"


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
    assert not (DOCS_SOURCE / "minimal-app-project-licenses.md").exists()
