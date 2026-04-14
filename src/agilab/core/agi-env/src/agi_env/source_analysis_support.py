"""Pure AST/source-analysis helpers for AGILAB."""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import Optional, Union


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


def get_functions_and_attributes(
    src_path: Union[str, Path],
    class_name: Optional[str] = None,
) -> dict[str, list[str]]:
    """Extract top-level or class-level functions and attributes from a Python source file."""

    path = Path(src_path)
    if not path.exists():
        raise FileNotFoundError(f"The file {path} does not exist.")

    try:
        content = path.read_text(encoding="utf-8")
    except Exception as exc:
        raise IOError(f"Error reading the file {path}: {exc}")

    try:
        tree = ast.parse(content, filename=str(path))
    except SyntaxError as exc:
        raise SyntaxError(f"Syntax error in the file {path}: {exc}")

    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child.parent = node  # type: ignore[attr-defined]

    function_names: list[str] = []
    attribute_names: list[str] = []

    if class_name:
        target_class = next(
            (
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.ClassDef) and node.name == class_name
            ),
            None,
        )
        if target_class is None:
            raise ValueError(f"Class '{class_name}' not found in {path}.")

        for item in target_class.body:
            if isinstance(item, ast.FunctionDef):
                function_names.append(item.name)
            elif isinstance(item, (ast.Assign, ast.AnnAssign)):
                targets = item.targets if isinstance(item, ast.Assign) else [item.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        attribute_names.append(target.id)
                    elif isinstance(target, ast.Tuple):
                        for elt in target.elts:
                            if isinstance(elt, ast.Name):
                                attribute_names.append(elt.id)
    else:
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                if not isinstance(getattr(node, "parent", None), (ast.FunctionDef, ast.ClassDef)):
                    function_names.append(node.name)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                if isinstance(getattr(node, "parent", None), ast.Module):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for target in targets:
                        if isinstance(target, ast.Name):
                            attribute_names.append(target.id)
                        elif isinstance(target, ast.Tuple):
                            for elt in target.elts:
                                if isinstance(elt, ast.Name):
                                    attribute_names.append(elt.id)

    return {"functions": function_names, "attributes": attribute_names}


def get_classes_name(src_path: Union[str, Path]) -> list[str]:
    """Extract class names from a Python source file."""

    content = Path(src_path).read_text(encoding="utf-8")
    return [node.name for node in ast.walk(ast.parse(content)) if isinstance(node, ast.ClassDef)]


def get_class_methods(src_path: Path, class_name: str) -> list[str]:
    """Extract method names from a specific class in a Python source file."""

    if not src_path.is_file():
        raise FileNotFoundError(f"The file {src_path} does not exist.")

    source = src_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(src_path))
    except SyntaxError as exc:
        raise SyntaxError(f"Syntax error in source file: {exc}")

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return [item.name for item in node.body if isinstance(item, ast.FunctionDef)]

    raise ValueError(f"Class '{class_name}' not found in the source file.")
