"""Non-executing prerequisite inspection for the local notebook app builder.

This is a conservative inventory, not a Python interpreter or a compatibility
test. Only explicit user-selected inputs are inspected on disk. Notebook paths
never authorize reading or copying files from the user's machine.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
from pathlib import Path, PurePosixPath, PureWindowsPath
import sys
from typing import Callable, Mapping

from .notebook_import_doctor import READ_METHODS, WRITE_METHODS
from .notebook_pipeline_import import build_notebook_import_preflight

SCHEMA = "agilab.notebook_build_prerequisites.v1"
MAX_INPUT_BYTES = 64 * 1024 * 1024
RESERVED_INPUTS = {
    "source",
    "app.py",
    "solution.ipynb",
    "pyproject.toml",
    "lab_stages.toml",
    "notebook_import.json",
    "results.json",
    "metrics.json",
}


def relative_input_path(value: str) -> str:
    """Require a portable project-relative destination, without normalizing '..'."""
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or "\x00" in value
        or ":" in value
        or path.is_absolute()
        or PureWindowsPath(value).drive
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ValueError(
            "Input destinations must be project-relative paths without '..'"
        )
    return path.as_posix()


def stage_input_files(project: Path, files: Mapping[str, Path] | None) -> list[dict]:
    """Copy only explicitly supplied regular files into a new build project."""
    prepared = []
    names: set[str] = set()
    total = 0
    # Validate all selections before writing any of them.
    for name, source in (files or {}).items():
        name = relative_input_path(name)
        if name.split("/")[0].casefold() in RESERVED_INPUTS:
            raise ValueError(f"Input destination is reserved by the builder: {name}")
        folded = name.casefold()
        if any(
            folded == other
            or folded.startswith(other + "/")
            or other.startswith(folded + "/")
            for other in names
        ):
            raise ValueError(f"Conflicting input destinations: {name}")
        names.add(folded)
        selected = Path(source).expanduser()
        if not selected.is_file():
            raise ValueError(f"Select a regular input file for {name}")
        with selected.open("rb") as stream:
            payload = stream.read(MAX_INPUT_BYTES - total + 1)
        total += len(payload)
        if total > MAX_INPUT_BYTES:
            raise ValueError("Selected inputs exceed the 64 MiB total limit")
        target = project / name
        if (
            target.exists()
            or target.is_symlink()
            or not target.resolve().is_relative_to(project.resolve())
            or any(
                (project / parent).is_symlink()
                for parent in PurePosixPath(name).parents
            )
        ):
            raise ValueError(
                f"Input destination already exists or crosses a symlink: {name}"
            )
        prepared.append((name, target, payload))
    manifest = []
    for name, target, payload in prepared:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(payload)
        manifest.append(
            {
                "path": name,
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    return manifest


def verify_input_files(project: Path, manifest: list[dict]) -> None:
    for item in manifest:
        path = project / relative_input_path(item["path"])
        if (
            path.is_symlink()
            or not path.is_file()
            or not path.resolve().is_relative_to(project.resolve())
            or path.stat().st_size != item["bytes"]
            or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]
        ):
            raise ValueError(f"Supplied input changed during the build: {item['path']}")


def _available(module: str) -> bool:
    # Root modules only: find_spec('package.child') could execute package code.
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def _literal(node: ast.AST | None, bindings: Mapping[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return bindings.get(node.id)
    if (
        isinstance(node, ast.Call)
        and _method(node.func) in {"Path", "PurePath"}
        and len(node.args) == 1
    ):
        return _literal(node.args[0], bindings)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.Add)):
        left, right = _literal(node.left, bindings), _literal(node.right, bindings)
        if left is not None and right is not None:
            return (
                str(PurePosixPath(left) / right)
                if isinstance(node.op, ast.Div)
                else left + right
            )
    return None


def _method(node: ast.AST) -> str:
    return (
        node.id
        if isinstance(node, ast.Name)
        else node.attr
        if isinstance(node, ast.Attribute)
        else ""
    )


class _Inventory(ast.NodeVisitor):
    def __init__(self, inputs: list[dict], available: Callable[[str], bool]):
        self.supplied = {item["path"] for item in inputs}
        self.available = available
        self.bindings: dict[str, str] = {}
        self.produced: set[str] = set()
        self.modules: list[dict] = []
        self.inputs: list[dict] = []
        self.models: list[dict] = []
        self.issues: list[dict] = []
        self.cell = "builder"
        self.conditional = 0

    def issue(self, code: str, message: str, *, blocked: bool = False):
        self.issues.append(
            {
                "severity": "error" if blocked else "warning",
                "code": code,
                "cell": self.cell,
                "message": message,
            }
        )

    def module(self, module: str, *, relative: bool = False):
        found = not relative and (
            self.available(module)
            or f"{module}.py" in self.supplied
            or f"{module}/__init__.py" in self.supplied
        )
        required = not self.conditional and not relative
        self.modules.append(
            {
                "module": module,
                "cell": self.cell,
                "required": required,
                "status": "discoverable" if found else "missing",
            }
        )
        if not found:
            self.issue(
                "missing_module",
                f"Module {module!r} is not discoverable. Prepare its dependency "
                "in the builder's Python environment, or supply the local module explicitly.",
                blocked=required,
            )

    def visit_Import(self, node):
        for alias in node.names:
            self.module(alias.name.split(".")[0])
            self.bindings.pop(alias.asname or alias.name.split(".")[0], None)

    def visit_ImportFrom(self, node):
        self.module((node.module or "").split(".")[0], relative=bool(node.level))
        for alias in node.names:
            self.bindings.pop(alias.asname or alias.name, None)

    def visit_Assign(self, node):
        self.visit(node.value)
        value = _literal(node.value, self.bindings)
        for target in node.targets:
            for child in ast.walk(target):
                if isinstance(child, ast.Name):
                    self.bindings.pop(child.id, None)
            if isinstance(target, ast.Name) and value is not None:
                self.bindings[target.id] = value

    def visit_AnnAssign(self, node):
        if node.value is not None:
            self.visit_Assign(ast.Assign(targets=[node.target], value=node.value))

    def visit_AugAssign(self, node):
        self.generic_visit(node)
        if isinstance(node.target, ast.Name):
            self.bindings.pop(node.target.id, None)

    def visit_Delete(self, node):
        for child in ast.walk(node):
            if isinstance(child, ast.Name):
                self.bindings.pop(child.id, None)

    def visit_NamedExpr(self, node):
        self.visit_Assign(ast.Assign(targets=[node.target], value=node.value))

    def _uncertain(self, node):
        # Branches, loops and function bodies are only potential requirements.
        previous = self.bindings.copy()
        self.bindings = {}  # Do not pretend to resolve closure or branch-local state.
        self.conditional += 1
        self.generic_visit(node)
        self.conditional -= 1
        self.bindings = previous
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            self.bindings.pop(node.name, None)
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and isinstance(
                child.ctx, (ast.Store, ast.Del)
            ):
                self.bindings.pop(child.id, None)

    visit_FunctionDef = _uncertain
    visit_AsyncFunctionDef = _uncertain
    visit_ClassDef = _uncertain
    visit_If = _uncertain
    visit_IfExp = _uncertain
    visit_Try = _uncertain
    visit_TryStar = _uncertain
    visit_For = _uncertain
    visit_AsyncFor = _uncertain
    visit_While = _uncertain
    visit_Match = _uncertain
    visit_Lambda = _uncertain
    visit_ListComp = _uncertain
    visit_SetComp = _uncertain
    visit_DictComp = _uncertain
    visit_GeneratorExp = _uncertain
    visit_BoolOp = _uncertain

    def visit_Call(self, node):
        self.generic_visit(node)  # Inner reads happen before outer writes.
        method = _method(node.func)
        keywords = {k.arg: k.value for k in node.keywords if k.arg}
        if method == "from_pretrained":
            values = {
                "model_id": node.args[0]
                if node.args
                else keywords.get("pretrained_model_name_or_path")
            }
            values.update(
                {key: keywords.get(key) for key in ("revision", "device", "device_map")}
            )
            model = {
                key: _literal(value, self.bindings) for key, value in values.items()
            }
            model.update(
                cell=self.cell,
                status="unverified",
                unresolved=[
                    key
                    for key, value in values.items()
                    if value is not None and model[key] is None
                ],
            )
            self.models.append(model)
            self.issue(
                "model_assets_unverified",
                "Model identity was recorded; cache contents, revision availability "
                "and device compatibility require review. No model was loaded or downloaded.",
            )
            return
        reading = method in READ_METHODS or method == "read_bytes"
        writing = method in WRITE_METHODS
        value = (
            node.args[0]
            if node.args
            else next(
                (
                    keywords[key]
                    for key in (
                        "path",
                        "filepath_or_buffer",
                        "path_or_buf",
                        "fname",
                        "file",
                    )
                    if key in keywords
                ),
                None,
            )
        )
        if method in {
            "read_text",
            "read_bytes",
            "write_text",
            "write_bytes",
            "open",
        } and isinstance(node.func, ast.Attribute):
            value = node.func.value
        if method == "open":
            mode_node = keywords.get("mode")
            if mode_node is None:
                position = 0 if isinstance(node.func, ast.Attribute) else 1
                mode_node = node.args[position] if len(node.args) > position else None
            mode = _literal(mode_node, self.bindings) if mode_node is not None else "r"
            if mode is None:
                self.issue(
                    "unresolved_file_mode",
                    "File open mode is computed; review its input/output role.",
                )
                return
            reading, writing = "r" in mode, any(flag in mode for flag in "wax")
        if not (reading or writing):
            return
        path = _literal(value, self.bindings)
        if path is None:
            self.issue(
                "unresolved_file_path",
                "A file operation uses a computed path or file-like value; review its inputs.",
            )
            return
        try:
            # './data.csv' is a normal notebook spelling, unlike user destinations.
            while path.startswith("./"):
                path = path[2:]
            path = relative_input_path(path)
        except ValueError:
            self.issue(
                "external_file_path",
                "A file operation refers outside the project or to a URL; "
                "supply a project-relative input and adapt the path.",
                blocked=bool(reading and not self.conditional),
            )
            return
        if reading:
            status = (
                "supplied"
                if path in self.supplied
                else "produced_earlier"
                if path in self.produced
                else "unverified"
                if self.conditional
                else "missing"
            )
            self.inputs.append({"path": path, "cell": self.cell, "status": status})
            if status in {"missing", "unverified"}:
                self.issue(
                    "missing_input" if status == "missing" else "potential_input",
                    f"Input {path!r} needs review. Supply it with --input-file '{path}=PATH' "
                    "or make its generation explicit.",
                    blocked=status == "missing",
                )
        if writing and not self.conditional:
            self.produced.add(path)


def inspect_prerequisites(
    notebook_import: Mapping,
    *,
    inputs: list[dict] | None = None,
    module_available: Callable[[str], bool] = _available,
) -> dict:
    """Inspect imported sources in cell order, without executing cells or imports."""
    preflight = build_notebook_import_preflight(notebook_import)
    inventory = _Inventory(inputs or [], module_available)
    inventory.module("streamlit")  # The builder's independent interface verifier.
    for stage in notebook_import.get("pipeline_stages", []):
        inventory.cell = stage["id"]
        source = "".join(stage["source_lines"])
        try:
            inventory.visit(ast.parse(source))
        except (SyntaxError, ValueError, RecursionError):
            inventory.issue(
                "unparsed_cell",
                "Cell could not be inspected as Python; review magics or unsupported syntax.",
            )
            inventory.bindings.clear()
    blocked = not preflight["safe_to_import"] or any(
        i["severity"] == "error" for i in inventory.issues
    )
    review = bool(inventory.issues) or preflight["status"] == "review"
    return {
        "schema": SCHEMA,
        "status": "blocked" if blocked else "review" if review else "ready",
        "safe_to_build": not blocked,
        "inspection_only": True,
        "python_version": sys.version.split()[0],
        "source": notebook_import.get("source", {}),
        "modules": inventory.modules,
        "inputs": inventory.inputs,
        "supplied_inputs": inputs or [],
        "models": inventory.models,
        "issues": inventory.issues,
        "import_preflight": preflight,
        "limits": [
            "Static discovery does not verify package versions or runtime API compatibility.",
            "Only notebook cells are analyzed; dependencies inside supplied modules are not traversed.",
            "Computed paths, optional code and model caches require review.",
            "No notebook code, imported module, model or supplied input was executed.",
        ],
    }
