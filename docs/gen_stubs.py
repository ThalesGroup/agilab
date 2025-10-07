"""Generate lightweight type stubs for key AGILab packages.

The generated stubs live under ``docs/stubs`` by default and mirror the
package structure of the source tree.  They provide a minimal view of the
public API that can be reused by documentation tooling or type checkers
without importing the full runtime implementation.
"""

from __future__ import annotations

import argparse
import ast
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence

# Ignore these path fragments when scanning for packages.  We exclude virtual
# environments, build artefacts, tests, and various editor scratch files.
SKIP_PARTS: set[str] = {
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "tests",
    "test",
    "snippets",
    "scripts",
    "diagrams",
    "data",
    "~",
}


@dataclass(frozen=True)
class StubTarget:
    """A Python package to stub.

    Attributes
    ----------
    package_dir:
        Absolute path to the directory that contains the package ``__init__.py``.
    stub_root:
        Output directory where the stub package should be created.
    """

    package_dir: Path
    stub_root: Path

    @property
    def package_name(self) -> str:
        return self.package_dir.name

    def iter_source_files(self) -> Iterator[Path]:
        for path in self.package_dir.rglob("*.py"):
            if should_skip(path):
                continue
            yield path

    def destination_for(self, source: Path) -> Path:
        relative = source.relative_to(self.package_dir)
        return self.stub_root / self.package_name / relative.with_suffix(".pyi")


def should_skip(path: Path) -> bool:
    parts = set(path.parts)
    return any(part in SKIP_PARTS or part.startswith(".") for part in parts)


def discover_packages(root: Path, *, limit: Sequence[Path] | None = None) -> list[Path]:
    """Return candidate package directories under ``root``.

    If ``limit`` is provided, only directories that are descendants of one of
    the given paths are considered.
    """

    limit = [p.resolve() for p in (limit or [])]
    packages: set[Path] = set()
    for init_file in root.glob("src/agilab/**/__init__.py"):
        package_dir = init_file.parent
        if should_skip(package_dir):
            continue
        if limit and not any(package_dir.is_relative_to(candidate) for candidate in limit):
            continue
        packages.add(package_dir.resolve())
    return sorted(packages)


def render_stub(source_path: Path) -> str:
    source = source_path.read_text(encoding="utf-8")
    try:
        module = ast.parse(source)
    except SyntaxError:
        return "...\n"

    docstring = ast.get_docstring(module)
    body_nodes = list(module.body)

    import_lines: list[str] = []
    stub_lines: list[str] = []
    needs_any = False

    for node in body_nodes:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            # Skip module docstring – we already captured it.
            continue

        segment = ast.get_source_segment(source, node)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if segment:
                import_lines.append(segment.strip())
            continue

        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets):
                if segment:
                    stub_lines.append(segment.strip())
                    stub_lines.append("")
                continue

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            needs_any = True
            stub_lines.append(function_stub(node))
            stub_lines.append("")
            continue

        if isinstance(node, ast.ClassDef):
            needs_any = True
            stub_lines.extend(class_stub(node))
            stub_lines.append("")
            continue

        if isinstance(node, ast.Assign) and segment:
            stub_lines.append(segment.strip())
            stub_lines.append("")
            continue

        # Other node types are skipped – they typically encode runtime behaviour
        # that is not required for type stubs (e.g., control flow).

    import_lines = deduplicate(import_lines)

    if needs_any and not any("typing" in line and "Any" in line for line in import_lines):
        import_lines.append("from typing import Any")

    header: list[str] = []
    if docstring:
        safe_doc = docstring.replace('"""', '\"\"\"')
        header.append(f'"""{safe_doc}"""')
        header.append("")

    if import_lines:
        header.extend(import_lines)
        header.append("")

    content = header + stub_lines
    content = [line.rstrip() for line in content if line is not None]

    # Ensure the stub is not empty – mypy expects at least one statement.
    if not any(line for line in content if line.strip()):
        content.append("...")

    if content[-1] != "":
        content.append("")

    return "\n".join(content)


def deduplicate(lines: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for line in lines:
        if line not in seen:
            seen.add(line)
            result.append(line)
    return result


def function_stub(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    name = node.name
    params = format_params(node)
    return f"def {name}({params}) -> Any: ..."


def class_stub(node: ast.ClassDef) -> list[str]:
    bases: list[str] = []
    for base in node.bases:
        try:
            bases.append(ast.unparse(base))
        except AttributeError:  # pragma: no cover - Python < 3.9 compatibility guard
            if isinstance(base, ast.Name):
                bases.append(base.id)
            else:
                bases.append("object")

    header = f"class {node.name}"
    if bases:
        header += "(" + ", ".join(bases) + ")"
    header += ":"

    lines: list[str] = [header]
    method_emitted = False
    for sub in node.body:
        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
            params = format_params(sub, is_method=True)
            lines.append(f"    def {sub.name}({params}) -> Any: ...")
            method_emitted = True
    if not method_emitted:
        lines.append("    ...")
    return lines


def format_params(func: ast.FunctionDef | ast.AsyncFunctionDef, *, is_method: bool = False) -> str:
    args = list(func.args.args)
    params: list[str] = []

    if args:
        first = args[0].arg
        if is_method and first in {"self", "cls"}:
            params.append(first)
            args = args[1:]

    if args or func.args.vararg or func.args.kwonlyargs or func.args.kwarg:
        params.append("*args: Any")
        params.append("**kwargs: Any")
    elif not params:
        params.append("*args: Any")
        params.append("**kwargs: Any")

    return ", ".join(params)


def build_targets(root: Path, *, output: Path, limit: Sequence[Path] | None = None) -> list[StubTarget]:
    packages = discover_packages(root, limit=limit)
    return [StubTarget(package_dir=pkg, stub_root=output) for pkg in packages]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate .pyi stub files for documentation tooling")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("docs/stubs"),
        help="Directory where stub packages will be written (default: docs/stubs)",
    )
    parser.add_argument(
        "--limit",
        type=Path,
        nargs="*",
        default=None,
        help="Optional list of package roots to restrict stub generation",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove the output directory before generating new stubs",
    )

    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    output_dir = (args.output if args.output.is_absolute() else repo_root / args.output).resolve()

    if args.clean and output_dir.exists():
        shutil.rmtree(output_dir)

    targets = build_targets(repo_root, output=output_dir, limit=args.limit)
    if not targets:
        print("[gen_stubs] No packages discovered – nothing to do.")
        return 0

    for target in targets:
        for src in target.iter_source_files():
            dest = target.destination_for(src)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(render_stub(src), encoding="utf-8")

    print(f"[gen_stubs] Generated stubs for {len(targets)} packages in {output_dir}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
