"""Pure AST/source-analysis helpers for AGILAB."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Optional, Union
from .source_analysis_ast import (
    extract_base_info,
    get_full_attribute_name,
    get_import_mapping,
)

SOURCE_READ_EXCEPTIONS = (OSError, UnicodeError)


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
    except SOURCE_READ_EXCEPTIONS as exc:
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
