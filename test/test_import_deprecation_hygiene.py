from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = (
    REPO_ROOT / "src" / "agilab",
    REPO_ROOT / "tools",
)


def _python_files() -> list[Path]:
    skipped_parts = {
        ".venv",
        "__pycache__",
        "build",
        "dist",
        ".pytest_cache",
        ".mypy_cache",
    }
    files: list[Path] = []
    for root in SCAN_ROOTS:
        for path in root.rglob("*.py"):
            if skipped_parts.intersection(path.parts):
                continue
            files.append(path)
    return sorted(files)


def _parsed_python_files() -> list[tuple[Path, ast.AST]]:
    parsed: list[tuple[Path, ast.AST]] = []
    for path in _python_files():
        parsed.append((path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))))
    return parsed


def test_runtime_source_does_not_import_deprecated_astor_or_distutils() -> None:
    violations: list[str] = []
    for path, tree in _parsed_python_files():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_name = alias.name.split(".", 1)[0]
                    if root_name in {"astor", "distutils"}:
                        violations.append(f"{path.relative_to(REPO_ROOT)} imports {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                root_name = (node.module or "").split(".", 1)[0]
                if root_name in {"astor", "distutils"}:
                    violations.append(f"{path.relative_to(REPO_ROOT)} imports from {node.module}")

    assert violations == []


def test_runtime_source_does_not_hide_all_warnings_at_import_time() -> None:
    violations: list[str] = []
    for path, tree in _parsed_python_files():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (
                isinstance(func, ast.Attribute)
                and func.attr in {"filterwarnings", "simplefilter"}
                and isinstance(func.value, ast.Name)
                and func.value.id == "warnings"
            ):
                continue
            if not node.args:
                continue
            first_arg = node.args[0]
            has_category = any(keyword.arg == "category" for keyword in node.keywords)
            if isinstance(first_arg, ast.Constant) and first_arg.value == "ignore" and not has_category:
                violations.append(f"{path.relative_to(REPO_ROOT)} suppresses all warnings")

    assert violations == []
