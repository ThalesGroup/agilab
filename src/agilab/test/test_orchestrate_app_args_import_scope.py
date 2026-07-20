"""Regression coverage for external custom app argument forms."""

from __future__ import annotations

import ast
from pathlib import Path


ORCHESTRATE_PAGE = (
    Path(__file__).resolve().parents[2] / "agilab" / "pages" / "2_ORCHESTRATE.py"
)


def _is_call(expression: ast.expr, name: str) -> bool:
    return (
        isinstance(expression, ast.Call)
        and isinstance(expression.func, ast.Name)
        and expression.func.id == name
    )


def _contains_runpy_execution(node: ast.AST) -> bool:
    return any(
        isinstance(candidate, ast.Call)
        and isinstance(candidate.func, ast.Attribute)
        and isinstance(candidate.func.value, ast.Name)
        and candidate.func.value.id == "runpy"
        and candidate.func.attr == "run_path"
        for candidate in ast.walk(node)
    )


def test_custom_app_args_form_execution_uses_active_app_import_scope():
    """External forms can import their app package without an editable UI install."""

    page_tree = ast.parse(ORCHESTRATE_PAGE.read_text(encoding="utf-8"))
    scoped_form_execution = False
    for node in ast.walk(page_tree):
        if not isinstance(node, ast.With):
            continue
        context_expressions = [item.context_expr for item in node.items]
        has_app_scope = any(
            _is_call(expression, "_active_app_import_scope")
            for expression in context_expressions
        )
        has_ui_scope = any(
            _is_call(expression, "_with_app_args_env")
            for expression in context_expressions
        )
        if has_app_scope and has_ui_scope and _contains_runpy_execution(node):
            scoped_form_execution = True
            break

    assert scoped_form_execution
