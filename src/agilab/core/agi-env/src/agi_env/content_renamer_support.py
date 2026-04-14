"""Pure AST content-renaming helpers for AGILAB."""

from __future__ import annotations

import ast
import logging


class ContentRenamer(ast.NodeTransformer):
    """Rename identifiers inside a Python AST according to ``rename_map``."""

    def __init__(self, rename_map: dict[str, str], *, logger: logging.Logger | None = None):
        self.rename_map = rename_map
        self.logger = logger

    def _log(self, message: str) -> None:
        if self.logger is not None:
            self.logger.info(message)

    def visit_Name(self, node):
        if node.id in self.rename_map:
            self._log(f"Renaming Name: {node.id} ➔ {self.rename_map[node.id]}")
            node.id = self.rename_map[node.id]
        self.generic_visit(node)
        return node

    def visit_Attribute(self, node):
        if node.attr in self.rename_map:
            self._log(f"Renaming Attribute: {node.attr} ➔ {self.rename_map[node.attr]}")
            node.attr = self.rename_map[node.attr]
        self.generic_visit(node)
        return node

    def visit_FunctionDef(self, node):
        if node.name in self.rename_map:
            self._log(f"Renaming Function: {node.name} ➔ {self.rename_map[node.name]}")
            node.name = self.rename_map[node.name]
        self.generic_visit(node)
        return node

    def visit_ClassDef(self, node):
        if node.name in self.rename_map:
            self._log(f"Renaming Class: {node.name} ➔ {self.rename_map[node.name]}")
            node.name = self.rename_map[node.name]
        self.generic_visit(node)
        return node

    def visit_arg(self, node):
        if node.arg in self.rename_map:
            self._log(f"Renaming Argument: {node.arg} ➔ {self.rename_map[node.arg]}")
            node.arg = self.rename_map[node.arg]
        self.generic_visit(node)
        return node

    def visit_Global(self, node):
        new_names = []
        for name in node.names:
            if name in self.rename_map:
                self._log(f"Renaming Global Variable: {name} ➔ {self.rename_map[name]}")
                new_names.append(self.rename_map[name])
            else:
                new_names.append(name)
        node.names = new_names
        self.generic_visit(node)
        return node

    def visit_nonlocal(self, node):
        new_names = []
        for name in node.names:
            if name in self.rename_map:
                self._log(f"Renaming Nonlocal Variable: {name} ➔ {self.rename_map[name]}")
                new_names.append(self.rename_map[name])
            else:
                new_names.append(name)
        node.names = new_names
        self.generic_visit(node)
        return node

    def visit_Assign(self, node):
        self.generic_visit(node)
        return node

    def visit_AnnAssign(self, node):
        self.generic_visit(node)
        return node

    def visit_For(self, node):
        if isinstance(node.target, ast.Name) and node.target.id in self.rename_map:
            self._log(
                f"Renaming For Loop Variable: {node.target.id} ➔ {self.rename_map[node.target.id]}"
            )
            node.target.id = self.rename_map[node.target.id]
        self.generic_visit(node)
        return node

    def visit_Import(self, node):
        for alias in node.names:
            original_name = alias.name
            if original_name in self.rename_map:
                self._log(
                    f"Renaming Import Module: {original_name} ➔ {self.rename_map[original_name]}"
                )
                alias.name = self.rename_map[original_name]
            else:
                for old, new in self.rename_map.items():
                    if original_name.startswith(old):
                        renamed = original_name.replace(old, new, 1)
                        self._log(f"Renaming Import Module: {original_name} ➔ {renamed}")
                        alias.name = renamed
                        break
        self.generic_visit(node)
        return node

    def visit_ImportFrom(self, node):
        if node.module in self.rename_map:
            self._log(
                f"Renaming ImportFrom Module: {node.module} ➔ {self.rename_map[node.module]}"
            )
            node.module = self.rename_map[node.module]
        else:
            for old, new in self.rename_map.items():
                if node.module and node.module.startswith(old):
                    new_module = node.module.replace(old, new, 1)
                    self._log(f"Renaming ImportFrom Module: {node.module} ➔ {new_module}")
                    node.module = new_module
                    break

        for alias in node.names:
            if alias.name in self.rename_map:
                self._log(
                    f"Renaming Imported Name: {alias.name} ➔ {self.rename_map[alias.name]}"
                )
                alias.name = self.rename_map[alias.name]
            else:
                for old, new in self.rename_map.items():
                    if alias.name.startswith(old):
                        renamed = alias.name.replace(old, new, 1)
                        self._log(f"Renaming Imported Name: {alias.name} ➔ {renamed}")
                        alias.name = renamed
                        break
        self.generic_visit(node)
        return node
