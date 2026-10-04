from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest


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


def test_historical_snapshot_preserves_tables_without_resolution(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    specs = module.inventory_specs(ROOT)
    spec = specs[0]
    monkeypatch.setattr(module, "inventory_specs", lambda root: (spec,))
    def reject_resolution(*args):
        pytest.fail("Snapshot retention must not run licensecheck or resolve dependencies.")
    monkeypatch.setattr(module, "_run_licensecheck", reject_resolution)
    original = module.render_inventory(spec, {
        "info": {"version": "2025.1.0"},
        "packages": [
            {"name": "streamlit", "version": "1.56.0", "license": "APACHE-2.0"},
            {"name": "numpy", "version": "2.3.5", "license": "BSD"},
        ],
    })
    inventory = tmp_path / spec.output_name
    inventory.write_text(original, encoding="utf-8")
    legacy = tmp_path / "old-package-licenses.md"
    legacy.write_text(original, encoding="utf-8")
    day = date(2026, 10, 4)
    assert module.generate(tmp_path, check=True, retained_on=day) == 1
    assert inventory.read_text() == original
    assert module.main([
        "--docs-source", str(tmp_path), "--preserve-existing-snapshot", str(day)
    ]) == 0
    updated = inventory.read_text()
    assert updated.split("| Package Name |", 1)[1] == original.split("| Package Name |", 1)[1]
    assert "Original acquisition date and manifest revisions were not recorded." in updated
    assert "does not describe current native source dependencies" in updated
    assert "Package manifest locations:" in updated
    assert "Source manifests:" not in updated
    assert legacy.read_text().split("| Package Name |", 1)[1] == original.split("| Package Name |", 1)[1]
    assert "Historical dependency metadata snapshot" in legacy.read_text()
    index = (tmp_path / "license.rst").read_text()
    assert "Historical Python dependency snapshots" in index
    assert "tools/generate_docs_license_inventories.py --preserve-existing-snapshot 2026-10-04" in index
    assert "A current resolved license inventory for the native source is not available here." in index
    assert "The dependency inventories are generated" not in index
    assert "Additional historical snapshots" in index
    assert "   old-package-licenses" in index
    assert module.generate(tmp_path, check=True, retained_on=day) == 0
    assert module.generate(tmp_path, retained_on=day) == 0
    assert inventory.read_text() == updated


def test_snapshot_retention_rejects_unrecorded_or_malformed_reports(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    spec = module.inventory_specs(ROOT)[0]
    monkeypatch.setattr(module, "inventory_specs", lambda root: (spec,))
    with pytest.raises(FileNotFoundError):
        module.generate(tmp_path, retained_on=date(2026, 10, 4))
    assert not (tmp_path / "license.rst").exists()
    with pytest.raises(ValueError, match="unrecognized"):
        module.retain_inventory_snapshot("Unrecorded inventory", date(2026, 10, 4))
    with pytest.raises(ValueError, match="Malformed"):
        module.retain_inventory_snapshot(
            module.GENERATED_MARKER + "\n| Package Name | Version | License |\n" + module.SNAPSHOT_START,
            date(2026, 10, 4),
        )
    with pytest.raises(ValueError, match="must not change the dependency table"):
        module.retain_inventory_snapshot(
            module.GENERATED_MARKER + "\n" + module.SNAPSHOT_START
            + "\n| Package Name | Version | License |\n| streamlit | 1.56.0 | APACHE-2.0 |\n"
            + module.SNAPSHOT_END,
            date(2026, 10, 4),
        )
    page = tmp_path / spec.output_name
    original = module.render_inventory(spec, {"packages": []})
    page.write_text(original)
    (tmp_path / "legacy-licenses.md").write_text("This is a generated inventory with unrecorded format.")
    with pytest.raises(ValueError, match="unrecognized"):
        module.generate(tmp_path, retained_on=date(2026, 10, 4))
    assert page.read_text() == original
    assert not (tmp_path / "license.rst").exists()


def test_snapshot_mode_does_not_create_missing_source(tmp_path: Path) -> None:
    module = _load_module()
    absent = tmp_path / "missing" / "docs"
    with pytest.raises(FileNotFoundError):
        module.generate(absent, check=True, retained_on=date(2026, 10, 4))
    assert not absent.parent.exists()


def test_snapshot_mode_rejects_symlinks(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    spec = module.inventory_specs(ROOT)[0]
    monkeypatch.setattr(module, "inventory_specs", lambda root: (spec,))
    def symlink_or_skip(link: Path, target: Path, *, directory: bool = False) -> None:
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (NotImplementedError, OSError) as exc:
            pytest.skip(f"symlink creation is unavailable: {exc}")
    target = tmp_path / "external-report.md"
    original = module.render_inventory(spec, {"packages": []})
    target.write_text(original)
    docs = tmp_path / "docs"
    docs.mkdir()
    page = docs / spec.output_name
    symlink_or_skip(page, target)
    with pytest.raises(ValueError, match="real files"):
        module.generate(docs, retained_on=date(2026, 10, 4))
    assert target.read_text() == original
    page.unlink()
    page.write_text(original)
    symlink_or_skip(docs / "license.rst", target)
    with pytest.raises(ValueError, match="real file"):
        module.generate(docs, retained_on=date(2026, 10, 4))
    assert page.read_text() == original
    alias = tmp_path / "docs-link"
    symlink_or_skip(alias, docs, directory=True)
    with pytest.raises(ValueError, match="real directory"):
        module.main([
            "--docs-source", str(alias), "--preserve-existing-snapshot", "2026-10-04"
        ])
