from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BUILTIN_APPS_ROOT = REPO_ROOT / "src" / "agilab" / "apps" / "builtin"
TEMPLATE_ONLY_BUILTIN_APPS = {
    "mycode_project": "starter template with placeholder worker hooks and no concrete merge output",
}


def _builtin_projects() -> list[Path]:
    return sorted(
        path
        for path in BUILTIN_APPS_ROOT.glob("*_project")
        if (path / "pyproject.toml").is_file()
    )


def _manager_package_dir(project_dir: Path) -> Path:
    packages = sorted(
        child
        for child in (project_dir / "src").iterdir()
        if child.is_dir()
        and (child / "__init__.py").is_file()
        and not child.name.endswith("_worker")
    )
    assert len(packages) == 1, f"{project_dir.name} should expose one manager package"
    return packages[0]


def test_non_template_builtin_apps_expose_reduce_contracts() -> None:
    failures: list[str] = []

    for project_dir in _builtin_projects():
        if project_dir.name in TEMPLATE_ONLY_BUILTIN_APPS:
            continue

        package_dir = _manager_package_dir(project_dir)
        init_path = package_dir / "__init__.py"
        reduction_path = package_dir / "reduction.py"
        if not reduction_path.is_file():
            failures.append(f"{project_dir.name}: missing {reduction_path.relative_to(REPO_ROOT)}")
            continue

        init_text = init_path.read_text(encoding="utf-8")
        reduction_text = reduction_path.read_text(encoding="utf-8")
        if "from .reduction import" not in init_text:
            failures.append(f"{project_dir.name}: manager package does not export reduction contract")
        if not re.search(r"\b[A-Z0-9_]+_REDUCE_CONTRACT\b", init_text):
            failures.append(f"{project_dir.name}: no exported *_REDUCE_CONTRACT symbol")
        if "REDUCE_ARTIFACT_FILENAME_TEMPLATE" not in reduction_text:
            failures.append(f"{project_dir.name}: reducer does not declare artifact filename template")
        if "reduce_summary_worker_{worker_id}.json" not in reduction_text:
            failures.append(f"{project_dir.name}: reducer does not use worker-scoped reduce summary name")
        if "write_reduce_artifact" not in reduction_text:
            failures.append(f"{project_dir.name}: reducer does not expose write_reduce_artifact")

    assert not failures, "\n".join(failures)


def test_template_only_builtin_apps_are_explicitly_exempted() -> None:
    discovered = {path.name for path in _builtin_projects()}

    assert set(TEMPLATE_ONLY_BUILTIN_APPS) <= discovered

    mycode_docs = (REPO_ROOT / "docs" / "source" / "mycode-project.rst").read_text(
        encoding="utf-8"
    )
    normalized_docs = re.sub(r"\s+", " ", mycode_docs.lower())
    assert "template-only" in normalized_docs
    assert "no concrete merge output" in normalized_docs
    assert "reduce_summary_worker_<id>.json" in mycode_docs
