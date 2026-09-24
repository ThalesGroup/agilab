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
            # Environments are not repo source. Match by prefix: alongside plain
            # `.venv`, app and page bundles create siblings such as
            # `.venv.agilab-linking`, whose third-party contents would otherwise
            # be scanned as if they were ours.
            if any(part.startswith(".venv") for part in path.parts):
                continue
            files.append(path)
    return sorted(files)


def _parsed_python_files() -> list[tuple[Path, ast.AST]]:
    parsed: list[tuple[Path, ast.AST]] = []
    for path in _python_files():
        parsed.append((path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))))
    return parsed


def test_runtime_source_does_not_import_deprecated_apis() -> None:
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
                if node.module == "pathspec.patterns":
                    for alias in node.names:
                        if alias.name == "GitWildMatchPattern":
                            violations.append(
                                f"{path.relative_to(REPO_ROOT)} imports deprecated pathspec.patterns.GitWildMatchPattern"
                            )

    assert violations == []


def _unscoped_warning_filters(tree: ast.AST) -> list[ast.Call]:
    """Temporary catch_warnings scopes restore filters; global ignores do not."""
    class Visitor(ast.NodeVisitor):
        scoped = False

        def __init__(self):
            self.violations = []

        def visit_With(self, node):
            for item in node.items:
                self.visit(item.context_expr)
            previous = self.scoped
            self.scoped = previous or any(
                isinstance(item.context_expr, ast.Call)
                and isinstance(item.context_expr.func, ast.Attribute)
                and isinstance(item.context_expr.func.value, ast.Name)
                and item.context_expr.func.value.id == "warnings"
                and item.context_expr.func.attr == "catch_warnings"
                for item in node.items
            )
            for statement in node.body:
                self.visit(statement)
            self.scoped = previous

        def visit_FunctionDef(self, node):
            # A function declared in a with block may execute after it exits.
            previous, self.scoped = self.scoped, False
            self.generic_visit(node)
            self.scoped = previous

        visit_AsyncFunctionDef = visit_FunctionDef
        visit_Lambda = visit_FunctionDef

        def visit_Call(self, node):
            func = node.func
            if not (
                isinstance(func, ast.Attribute)
                and func.attr in {"filterwarnings", "simplefilter"}
                and isinstance(func.value, ast.Name)
                and func.value.id == "warnings"
            ):
                self.generic_visit(node)
                return
            if node.args and not self.scoped:
                first_arg = node.args[0]
                has_category = any(keyword.arg == "category" for keyword in node.keywords)
                if isinstance(first_arg, ast.Constant) and first_arg.value == "ignore" and not has_category:
                    self.violations.append(node)
            self.generic_visit(node)

    visitor = Visitor()
    visitor.visit(tree)
    return visitor.violations


def test_warning_guard_distinguishes_temporary_scopes_from_global_changes() -> None:
    assert len(_unscoped_warning_filters(ast.parse("warnings.simplefilter('ignore')"))) == 1
    assert not _unscoped_warning_filters(ast.parse(
        "with warnings.catch_warnings():\n    warnings.simplefilter('ignore')\n"
    ))
    assert len(_unscoped_warning_filters(ast.parse(
        "with warnings.catch_warnings():\n    def later():\n        warnings.simplefilter('ignore')\n"
    ))) == 1
    assert len(_unscoped_warning_filters(ast.parse(
        "with warnings.catch_warnings():\n    warnings.simplefilter('ignore')\n"
        "warnings.simplefilter('ignore')\n"
    ))) == 1


def test_runtime_source_does_not_hide_all_warnings_at_import_time() -> None:
    violations = [
        f"{path.relative_to(REPO_ROOT)} suppresses all warnings"
        for path, tree in _parsed_python_files()
        for _ in _unscoped_warning_filters(tree)
    ]

    assert violations == []
