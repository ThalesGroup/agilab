"""Pure worker source-inspection helpers for AGILAB."""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import Callable

from agi_env.source_analysis_support import extract_base_info, get_import_mapping


def get_base_classes(
    module_path: str | Path,
    class_name: str,
    *,
    logger: logging.Logger | None = None,
    import_mapping_fn: Callable[[str], dict[str, str | None]] = get_import_mapping,
    extract_base_info_fn: Callable[[ast.AST, dict[str, str | None]], tuple[str, str | None] | None] = extract_base_info,
) -> list[tuple[str, str | None]]:
    """Inspect ``module_path`` AST to retrieve base classes of ``class_name``."""

    try:
        with open(module_path, "r", encoding="utf-8") as file:
            source = file.read()
    except (IOError, FileNotFoundError) as exc:
        if logger is not None:
            logger.error(f"Error reading module file {module_path}: {exc}")
        return []

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        if logger is not None:
            logger.error(f"Syntax error parsing {module_path}: {exc}")
        raise RuntimeError(f"Syntax error parsing {module_path}: {exc}")

    import_mapping = import_mapping_fn(source)
    base_classes: list[tuple[str, str | None]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for base in node.bases:
                base_info = extract_base_info_fn(base, import_mapping)
                if base_info:
                    base_classes.append(base_info)
            break
    return base_classes


def get_base_worker_cls(
    module_path: str | Path,
    class_name: str,
    *,
    logger: logging.Logger | None = None,
    get_base_classes_fn: Callable[[str | Path, str], list[tuple[str, str | None]]] = get_base_classes,
) -> tuple[str | None, str | None]:
    """Return the base worker class name and module for ``class_name``."""

    base_info_list = get_base_classes_fn(module_path, class_name)
    try:
        base_class, module_name = next(
            (base, mod) for base, mod in base_info_list if base.endswith("Worker")
        )
        return base_class, module_name
    except StopIteration:
        return None, None
