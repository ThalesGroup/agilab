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


def _catalog_rows() -> dict[str, dict[str, str]]:
    lines = CATALOG_PATH.read_text(encoding="utf-8").splitlines()
    rows: dict[str, dict[str, str]] = {}
    current: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("* - "):
            if len(current) >= 4 and current[0] != "Project":
                rows[current[0]] = {
                    "package": current[1],
                    "status": current[2],
                    "use": " ".join(current[3:]),
                }
            current = [stripped.removeprefix("* - ").strip("`")]
        elif stripped.startswith("- ") and current:
            current.append(stripped.removeprefix("- ").strip("`"))
        elif current and len(current) >= 4 and stripped and not stripped.startswith((".. ", ":")):
            current[-1] = f"{current[-1]} {stripped}".strip()
    if len(current) >= 4 and current[0] != "Project":
        rows[current[0]] = {
            "package": current[1],
            "status": current[2],
            "use": " ".join(current[3:]),
        }
    return rows


def _project_name_for_package(package_path: str) -> str:
    package_root = REPO_ROOT / package_path
    for pyproject_path in sorted(package_root.glob("src/*/project/*_project/pyproject.toml")):
        return pyproject_path.parent.name

    provider_init_path = next(package_root.glob("src/*/__init__.py"))
    for line in provider_init_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("PROJECT_NAME"):
            return line.split("=", 1)[1].strip().strip("'\"")
    raise AssertionError(f"Unable to resolve project name for {package_path}")


def test_public_app_catalog_lists_all_public_app_packages() -> None:
    catalog = CATALOG_PATH.read_text(encoding="utf-8")

    missing = [package for package, _project in package_split_contract.APP_PROJECT_PACKAGE_SPECS if package not in catalog]

    assert missing == []


def test_public_app_catalog_status_matches_release_contract() -> None:
    rows = _catalog_rows()
    promoted_packages = set(package_split_contract.PROMOTED_APP_PROJECT_PACKAGE_NAMES)

    expected: dict[str, tuple[str, str]] = {}
    for package, package_path in package_split_contract.APP_PROJECT_PACKAGE_SPECS:
        project_name = _project_name_for_package(package_path)
        status = "PyPI app package" if package in promoted_packages else "Release artifact"
        expected[project_name] = (package, status)
    for project_path in sorted(BUILTIN_APPS_PATH.glob("*_project")):
        expected.setdefault(project_path.name, ("None", "Source built-in"))

    mismatches = {
        project: {
            "expected": {"package": package, "status": status},
            "actual": {
                "package": rows.get(project, {}).get("package"),
                "status": rows.get(project, {}).get("status"),
            },
        }
        for project, (package, status) in sorted(expected.items())
        if rows.get(project, {}).get("package") != package or rows.get(project, {}).get("status") != status
    }

    assert mismatches == {}


def test_public_app_catalog_lists_all_builtin_projects() -> None:
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    builtin_projects = sorted(path.name for path in BUILTIN_APPS_PATH.glob("*_project") if path.is_dir())

    missing = [project for project in builtin_projects if project not in catalog]

    assert missing == []
