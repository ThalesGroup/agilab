from pathlib import Path
import importlib.util
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = REPO_ROOT / "docs" / "source" / "public-app-catalog.rst"
BUILTIN_APPS_PATH = REPO_ROOT / "src" / "agilab" / "apps" / "builtin"
PACKAGE_SPLIT_CONTRACT_PATH = REPO_ROOT / "tools" / "package_split_contract.py"
SPEC = importlib.util.spec_from_file_location("agilab_package_split_contract", PACKAGE_SPLIT_CONTRACT_PATH)
assert SPEC and SPEC.loader
package_split_contract = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = package_split_contract
SPEC.loader.exec_module(package_split_contract)


def test_public_app_catalog_lists_all_public_app_packages() -> None:
    catalog = CATALOG_PATH.read_text(encoding="utf-8")

    missing = [package for package, _project in package_split_contract.APP_PROJECT_PACKAGE_SPECS if package not in catalog]

    assert missing == []


def test_public_app_catalog_lists_all_builtin_projects() -> None:
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    builtin_projects = sorted(path.name for path in BUILTIN_APPS_PATH.glob("*_project") if path.is_dir())

    missing = [project for project in builtin_projects if project not in catalog]

    assert missing == []
