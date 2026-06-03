from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APPS_PAGES_ROOT = ROOT / "src/agilab/apps-pages"


def _imports_agi_pages(page_bundle: Path) -> bool:
    return any(
        "agi_pages" in path.read_text(encoding="utf-8")
        for path in sorted((page_bundle / "src").rglob("*.py"))
    )


def _declares_dependency(dependencies: list[str], package: str) -> bool:
    normalized = package.replace("_", "-")
    return any(
        str(dependency).split(">=", 1)[0].split("==", 1)[0].strip().replace("_", "-")
        == normalized
        for dependency in dependencies
    )


def test_apps_pages_importing_agi_pages_declare_runtime_dependency() -> None:
    missing: list[str] = []
    for pyproject in sorted(APPS_PAGES_ROOT.glob("*/pyproject.toml")):
        page_bundle = pyproject.parent
        if not _imports_agi_pages(page_bundle):
            continue
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        dependencies = data.get("project", {}).get("dependencies", [])
        sources = data.get("tool", {}).get("uv", {}).get("sources", {})
        if not _declares_dependency(dependencies, "agi-pages"):
            missing.append(f"{page_bundle.name}: missing project dependency")
        if "agi-pages" not in sources:
            missing.append(f"{page_bundle.name}: missing local uv source")

    assert missing == []
