"""Pure AST/source-analysis helpers for AGILAB."""

from __future__ import annotations

import ast
import logging


def get_import_mapping(source: str, *, logger: logging.Logger | None = None) -> dict[str, str | None]:
    """Build a mapping of names to modules from ``import`` statements in ``source``."""

    mapping: dict[str, str | None] = {}
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        if logger is not None:
            logger.error(f"Syntax error during import mapping: {exc}")
        raise
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mapping[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom):
            module = node.module
            for alias in node.names:
                mapping[alias.asname or alias.name] = module
    return mapping


def get_full_attribute_name(node: ast.AST) -> str:
    """Reconstruct the dotted attribute path represented by ``node``."""

    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return get_full_attribute_name(node.value) + "." + node.attr
    return ""


def extract_base_info(base: ast.AST, import_mapping: dict[str, str | None]) -> tuple[str, str | None] | None:
    """Return the base-class name and originating module for ``base`` nodes."""

    if isinstance(base, ast.Name):
        module_name = import_mapping.get(base.id)
        return base.id, module_name
    if isinstance(base, ast.Attribute):
        full_name = get_full_attribute_name(base)
        parts = full_name.split(".")
        if len(parts) > 1:
            alias = parts[0]
            module_name = import_mapping.get(alias, alias)
            return parts[-1], module_name
        return base.attr, None
    return None
