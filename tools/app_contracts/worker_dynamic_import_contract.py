"""Inspect worker bindings without importing or executing application code.

Worker base declarations are inputs to the SDK's AST discovery. Execution must
use its runtime loader so Python/Cython selection and cache eviction remain in
one place. This check covers explicit imports and literal import calls; arbitrary
computed Python expressions require runtime tests and code review.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import tomllib
from typing import Sequence


EXCLUDED_DIRS = frozenset({
    ".git", ".external", ".venv", ".venv-dev", "__pycache__", "build", "dist",
    "node_modules", "reports", "test", "tests", "wheelhouse",
})
SDK_WORKER_BASES = frozenset({"BaseWorker", "DagWorker", "PandasWorker", "PolarsWorker", "FireducksWorker"})


@dataclass(frozen=True)
class WorkerPackage:
    name: str
    root: Path
    project_root: Path
    project_name: str
    distribution_name: str
    classes: frozenset[str]


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    message: str


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _python_files(roots: Sequence[Path]) -> list[Path]:
    files: set[Path] = set()
    for root in roots:
        for directory, names, filenames in os.walk(root, followlinks=False):
            names[:] = sorted(name for name in names if name not in EXCLUDED_DIRS and not name.startswith(".venv"))
            for name in filenames:
                if name.endswith(".py") and not name.startswith("test_") and not name.endswith("_test.py"):
                    files.add(Path(directory) / name)
    return sorted(files)


def discover_workers(apps_roots: Sequence[Path]) -> tuple[WorkerPackage, ...]:
    workers = []
    for source in _python_files(apps_roots):
        root = source.parent
        if not root.name.endswith("_worker") or source.stem != root.name:
            continue
        project = next((parent for parent in root.parents if (parent / "src/app_settings.toml").is_file()), None)
        if project is None:
            continue
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        project_data = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        worker_manifest = root / "pyproject.toml"
        worker_data = tomllib.loads(worker_manifest.read_text(encoding="utf-8")) if worker_manifest.is_file() else {}
        workers.append(WorkerPackage(
            name=root.name, root=root, project_root=project,
            project_name=project_data["name"],
            distribution_name=worker_data.get("project", {}).get("name", root.name),
            classes=frozenset(node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name.endswith("Worker")),
        ))
    return tuple(workers)


def _dependencies(worker: WorkerPackage) -> set[str]:
    dependencies: set[str] = set()
    for path in (worker.project_root / "pyproject.toml", worker.root / "pyproject.toml"):
        if path.is_file():
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            for requirement in data.get("project", {}).get("dependencies", []):
                dependencies.add(_normalize(re.split(r"[\[<=>!~;@\s]", requirement, maxsplit=1)[0]))
    return dependencies


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted(node.value)
        return f"{prefix}.{node.attr}" if prefix else ""
    return ""


def _import_module(node: ast.ImportFrom, path: Path) -> str:
    if not node.level:
        return node.module or ""
    parts = path.parts
    if "src" in parts:
        parts = parts[len(parts) - 1 - tuple(reversed(parts)).index("src") + 1:]
    else:
        package_parts = []
        parent = path.parent
        while (parent / "__init__.py").is_file():
            package_parts.insert(0, parent.name)
            parent = parent.parent
        parts = (*package_parts, path.name)
    package = list(parts[:-1])
    if node.level > 1:
        package = package[:-(node.level - 1)]
    return ".".join([*package, *((node.module or "").split(".") if node.module else [])])


def _targets(module: str, workers: Sequence[WorkerPackage], imported: str | None = None) -> list[WorkerPackage]:
    targets = []
    for worker in workers:
        compiled = f"{worker.name}_cy"
        if module == compiled or module.startswith(f"{compiled}.") or module == f"{worker.name}.{worker.name}":
            if imported is None or imported in worker.classes | {"*"}:
                targets.append(worker)
        elif module == worker.name and (imported is None or imported in worker.classes | {worker.name, "*"}):
            targets.append(worker)
        elif module.startswith(f"{worker.name}.") and imported in worker.classes:
            targets.append(worker)
    return targets


def inspect_source(path: Path, workers: Sequence[WorkerPackage]) -> list[Finding]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeError) as exc:
        return [Finding(str(path), getattr(exc, "lineno", 1) or 1, f"Source cannot be inspected: {exc}")]
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    base_nodes = {node for definition in ast.walk(tree) if isinstance(definition, ast.ClassDef) for base in definition.bases for node in ast.walk(base)}
    consumer = next((worker for worker in workers if path.is_relative_to(worker.root)), None)
    imports: dict[tuple[int, str], str] = {}
    findings: list[Finding] = []
    local_name_cache: dict[int, set[str]] = {}

    def scope(node: ast.AST) -> ast.AST:
        while node in parents:
            node = parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                return node
        return tree

    def local_names(owner: ast.AST) -> set[str]:
        if id(owner) in local_name_cache:
            return local_name_cache[id(owner)]
        names: set[str] = set()
        pending = list(ast.iter_child_nodes(owner))
        while pending:
            item = pending.pop()
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(item.name)
                continue
            if isinstance(item, ast.Lambda):
                continue
            if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store):
                names.add(item.id)
            elif isinstance(item, ast.arg):
                names.add(item.arg)
            elif isinstance(item, (ast.Import, ast.ImportFrom)):
                names.update(alias.asname or (alias.name.split(".")[0] if isinstance(item, ast.Import) else alias.name) for alias in item.names)
            pending.extend(ast.iter_child_nodes(item))
        local_name_cache[id(owner)] = names
        return names

    def references(node: ast.AST, binding: str) -> list[ast.Name]:
        owner = scope(node)
        matches = []
        for item in ast.walk(owner):
            if not isinstance(item, ast.Name) or not isinstance(item.ctx, ast.Load) or item.id != binding:
                continue
            current = scope(item)
            while current is not owner and current is not tree:
                if binding in local_names(current):
                    break
                current = scope(current)
            else:
                if current is owner:
                    matches.append(item)
        return matches

    def selects_worker(reference: ast.AST, targets: Sequence[WorkerPackage]) -> bool:
        """Helpers are shared freely; worker-class access or module escape is gated."""
        names = set().union(*(target.classes for target in targets))
        current = reference
        attributes: list[str] = []
        while isinstance(parents.get(current), ast.Attribute) and parents[current].value is current:
            current = parents[current]
            attributes.append(current.attr)
        if attributes:
            return "__dict__" in attributes or bool(names.intersection(attributes))
        parent = parents.get(reference)
        if isinstance(parent, ast.Call) and _dotted(parent.func) in {"getattr", "hasattr"} and parent.args[0] is reference:
            if len(parent.args) > 1 and isinstance(parent.args[1], ast.Constant):
                return parent.args[1].value in names
        # Passing/returning a module, or computed attribute access, hides its use.
        return True

    def typing_only(node: ast.AST) -> bool:
        child = node
        while child in parents:
            parent = parents[child]
            if isinstance(parent, ast.If) and _dotted(parent.test) in {"TYPE_CHECKING", "typing.TYPE_CHECKING"} and child in parent.body:
                return True
            child = parent
        return False

    def check_binding(node: ast.AST, module: str, imported: str | None, binding: str, renamed: bool = False) -> None:
        if (consumer is not None and renamed and module.startswith("agi_node.")
                and imported in SDK_WORKER_BASES and not typing_only(node)
                and any(item in base_nodes for item in references(node, binding))):
            findings.append(Finding(str(path), node.lineno, "Renamed SDK worker class bases are not supported by AST discovery; use a module alias."))
            return
        targets = _targets(module, workers, imported)
        if not targets or typing_only(node):
            return
        refs = references(node, binding)
        worker_class_import = imported == "*" or any(imported in target.classes for target in targets)
        if not worker_class_import:
            refs = [item for item in refs if selects_worker(item, targets)]
            if not refs:
                return
        own_export = consumer is not None and path == consumer.root / "__init__.py" and any(target.root == consumer.root for target in targets)
        if own_export and not refs:
            return
        if consumer is not None and refs and all(item in base_nodes for item in refs):
            if renamed and worker_class_import:
                findings.append(Finding(str(path), node.lineno, "Renamed worker class bases are not supported by SDK AST discovery; use a module alias."))
                return
            dependencies = _dependencies(consumer)
            if any(target.project_root == consumer.project_root or {_normalize(target.project_name), _normalize(target.distribution_name)} & dependencies for target in targets):
                return
            findings.append(Finding(str(path), node.lineno, "Worker inheritance requires a declared parent project or worker dependency."))
            return
        findings.append(Finding(str(path), node.lineno, "Static application worker binding bypasses SDK loading; use load_worker(env, mode, ...) for execution."))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                binding = alias.asname or alias.name.split(".")[0]
                imports[id(scope(node)), binding] = alias.name if alias.asname else binding
                check_binding(node, alias.name, None, binding)
        elif isinstance(node, ast.ImportFrom):
            module = _import_module(node, path)
            for alias in node.names:
                binding = alias.asname or alias.name
                imports[id(scope(node)), binding] = f"{module}.{alias.name}"
                check_binding(node, module, alias.name, binding, bool(alias.asname and alias.asname != alias.name))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args or typing_only(node):
            continue
        argument = node.args[0]
        if not isinstance(argument, ast.Constant) or not isinstance(argument.value, str):
            continue
        name = _dotted(node.func)
        head, separator, tail = name.partition(".")
        owner = scope(node)
        resolved_head = head
        while True:
            imported = imports.get((id(owner), head))
            if imported is not None:
                resolved_head = imported
                break
            if head in local_names(owner):
                resolved_head = ""
                break
            if owner is tree:
                break
            owner = scope(owner)
        resolved = resolved_head + (f".{tail}" if separator else "")
        if resolved not in {"importlib.import_module", "__import__"}:
            continue
        targets = _targets(argument.value, workers)
        if not targets:
            continue
        parent = parents.get(node)
        if isinstance(parent, ast.Expr):
            # Discarded imports may register serialized model providers. They do
            # not bind a worker class; keep checkpoint compatibility intact.
            continue
        if isinstance(parent, (ast.Assign, ast.AnnAssign)):
            assigned = parent.targets if isinstance(parent, ast.Assign) else [parent.target]
            bindings = [target.id for target in assigned if isinstance(target, ast.Name)]
            if bindings and all(not any(selects_worker(item, targets) for item in references(parent, binding)) for binding in bindings):
                continue
        elif not selects_worker(node, targets):
            continue
        findings.append(Finding(str(path), node.lineno, "Literal application worker import pins an implementation; use SDK load_worker(env, mode, ...)."))
    return sorted(set(findings), key=lambda item: (item.path, item.line, item.message))


def inspect_roots(repo_root: Path, apps_roots: Sequence[Path] | None = None, source_roots: Sequence[Path] | None = None) -> dict:
    repo_root = repo_root.resolve()
    apps = [Path(path).resolve() for path in apps_roots] if apps_roots is not None else [repo_root / name for name in ("src/agilab/apps", "apps", "private/apps", "FCAS", "ENGRT") if (repo_root / name).is_dir()]
    sources = [Path(path).resolve() for path in source_roots] if source_roots is not None else [repo_root / name for name in ("src", "apps", "private/apps", "FCAS", "ENGRT") if (repo_root / name).is_dir()]
    if not apps or not sources or any(not path.is_dir() for path in [*apps, *sources]):
        raise ValueError("Existing app and production source roots are required; no empty success is allowed.")
    workers = discover_workers(apps)
    if not workers:
        raise ValueError("No application worker packages discovered; check the app roots.")
    files = _python_files(sources)
    findings = [finding for path in files for finding in inspect_source(path, workers)]
    return {"schema": "agilab.worker_dynamic_import_contract.v1", "python_files_checked": len(files), "worker_packages_checked": len(workers), "passed": not findings, "findings": [asdict(finding) for finding in findings]}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--apps-root", type=Path, action="append")
    parser.add_argument("--source-root", type=Path, action="append")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = inspect_roots(args.repo_root, args.apps_root, args.source_root)
    except (OSError, ValueError, SyntaxError, KeyError) as exc:
        parser.exit(2, f"Worker dynamic import contract could not run: {exc}\n")
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
