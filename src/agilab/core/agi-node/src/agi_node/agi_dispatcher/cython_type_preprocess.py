"""Conservative Cython local-variable preprocessing for worker sources."""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence


CYTHON_NUMERIC_TYPES = {"bint", "double", "Py_ssize_t"}


@dataclass(frozen=True)
class TypedVariable:
    function: str
    name: str
    cython_type: str
    line: int
    reason: str


@dataclass(frozen=True)
class SkippedVariable:
    function: str
    name: str
    lines: tuple[int, ...]
    reason: str


@dataclass(frozen=True)
class FunctionDeclarations:
    function: str
    insert_after_line: int
    indent: str
    variables: tuple[TypedVariable, ...]


@dataclass(frozen=True)
class PreprocessPreview:
    declarations: tuple[FunctionDeclarations, ...]
    skipped: tuple[SkippedVariable, ...]

    @property
    def typed_variables(self) -> tuple[TypedVariable, ...]:
        return tuple(variable for group in self.declarations for variable in group.variables)

    def to_report(self, *, input_path: str | None = None, output_path: str | None = None) -> dict:
        report: dict[str, object] = {
            "declarations": [asdict(variable) for variable in self.typed_variables],
            "skipped": [asdict(variable) for variable in self.skipped],
        }
        if input_path is not None:
            report["input"] = input_path
        if output_path is not None:
            report["output"] = output_path
        return report


@dataclass(frozen=True)
class _Candidate:
    cython_type: str | None
    line: int
    reason: str


@dataclass(frozen=True)
class _FunctionInfo:
    qualname: str
    node: ast.FunctionDef | ast.AsyncFunctionDef
    insert_after_line: int
    indent: str


def _annotation_type(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        if node.id == "float":
            return "double"
        if node.id == "bool":
            return "bint"
    return None


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    return None


def _expr_type(node: ast.AST) -> tuple[str | None, str]:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return "bint", "bool literal"
        if isinstance(node.value, float):
            return "double", "float literal"
        return None, "literal keeps Python object semantics"

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return _expr_type(node.operand)

    if isinstance(node, ast.Compare):
        return "bint", "comparison result"

    if isinstance(node, ast.BinOp):
        left_type, _ = _expr_type(node.left)
        right_type, _ = _expr_type(node.right)
        if left_type in CYTHON_NUMERIC_TYPES and right_type in CYTHON_NUMERIC_TYPES:
            if "double" in {left_type, right_type}:
                return "double", "numeric expression"
            return "Py_ssize_t", "integer-sized numeric expression"
        return None, "expression type is not statically safe"

    if isinstance(node, ast.Call):
        name = _call_name(node.func)
        if name == "len":
            return "Py_ssize_t", "len() result"
        if name == "float":
            return "double", "float() result"
        if name == "bool":
            return "bint", "bool() result"
        return None, "call result is dynamic"

    return None, "expression type is dynamic"


def _target_names(target: ast.AST) -> tuple[str, ...]:
    if isinstance(target, ast.Name):
        return (target.id,)
    if isinstance(target, (ast.Tuple, ast.List)):
        names: list[str] = []
        for item in target.elts:
            names.extend(_target_names(item))
        return tuple(names)
    return ()


def _is_range_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and _call_name(node.func) == "range"


def _function_args(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    args = node.args
    names = {arg.arg for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]}
    if args.vararg is not None:
        names.add(args.vararg.arg)
    if args.kwarg is not None:
        names.add(args.kwarg.arg)
    return names


def _insert_after_line(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    if node.body and isinstance(node.body[0], ast.Expr):
        value = node.body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return int(getattr(node.body[0], "end_lineno", node.body[0].lineno))
    return node.lineno


def _body_indent(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    if node.body:
        return " " * int(getattr(node.body[0], "col_offset", node.col_offset + 4))
    return " " * (node.col_offset + 4)


def _iter_functions(
    nodes: Iterable[ast.stmt],
    prefix: tuple[str, ...] = (),
) -> Iterable[_FunctionInfo]:
    for node in nodes:
        if isinstance(node, ast.ClassDef):
            yield from _iter_functions(node.body, (*prefix, node.name))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qualname = ".".join((*prefix, node.name))
            yield _FunctionInfo(
                qualname=qualname,
                node=node,
                insert_after_line=_insert_after_line(node),
                indent=_body_indent(node),
            )
            yield from _iter_functions(node.body, (*prefix, node.name))


class _FunctionCollector(ast.NodeVisitor):
    def __init__(self, *, function: str, parameters: set[str]) -> None:
        self.function = function
        self.parameters = parameters
        self.candidates: dict[str, list[_Candidate]] = {}
        self.blocked: dict[str, list[_Candidate]] = {}
        self.global_or_nonlocal: set[str] = set()

    def _record(self, name: str, candidate: _Candidate) -> None:
        if name in self.parameters or name in self.global_or_nonlocal:
            return
        self.candidates.setdefault(name, []).append(candidate)

    def _block(self, name: str, *, line: int, reason: str) -> None:
        if name in self.parameters or name in self.global_or_nonlocal:
            return
        self.blocked.setdefault(name, []).append(_Candidate(None, line, reason))

    def visit_Global(self, node: ast.Global) -> None:
        self.global_or_nonlocal.update(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.global_or_nonlocal.update(node.names)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def visit_Assign(self, node: ast.Assign) -> None:
        cython_type, reason = _expr_type(node.value)
        for target in node.targets:
            names = _target_names(target)
            if isinstance(target, ast.Name) and cython_type is not None:
                self._record(target.id, _Candidate(cython_type, node.lineno, reason))
            else:
                for name in names:
                    self._block(name, line=node.lineno, reason=reason)
        self.generic_visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        names = _target_names(node.target)
        annotation_type = _annotation_type(node.annotation)
        value_reason = "annotated assignment without value"
        if node.value is not None:
            _, value_reason = _expr_type(node.value)

        reason = (
            "source annotation already provides a type hint"
            if annotation_type
            else value_reason
        )
        for name in names:
            self._block(name, line=node.lineno, reason=reason)
        if node.value is not None:
            self.generic_visit(node.value)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        names = _target_names(node.target)
        cython_type, reason = _expr_type(node.value)
        if isinstance(node.target, ast.Name) and cython_type is not None:
            self._record(node.target.id, _Candidate(cython_type, node.lineno, reason))
        else:
            for name in names:
                self._block(name, line=node.lineno, reason=reason)
        self.generic_visit(node.value)

    def visit_For(self, node: ast.For) -> None:
        names = _target_names(node.target)
        if isinstance(node.target, ast.Name) and _is_range_call(node.iter):
            self._record(
                node.target.id,
                _Candidate("Py_ssize_t", node.lineno, "range() loop index"),
            )
        else:
            for name in names:
                self._block(name, line=node.lineno, reason="loop target is dynamic")
        for statement in [*node.body, *node.orelse]:
            self.visit(statement)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        for name in _target_names(node.target):
            self._block(name, line=node.lineno, reason="async loop target is dynamic")
        for statement in [*node.body, *node.orelse]:
            self.visit(statement)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            if item.optional_vars is not None:
                for name in _target_names(item.optional_vars):
                    self._block(
                        name,
                        line=node.lineno,
                        reason="context manager target is dynamic",
                    )
        for statement in node.body:
            self.visit(statement)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        for item in node.items:
            if item.optional_vars is not None:
                for name in _target_names(item.optional_vars):
                    self._block(
                        name,
                        line=node.lineno,
                        reason="async context manager target is dynamic",
                    )
        for statement in node.body:
            self.visit(statement)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self._block(node.name, line=node.lineno, reason="exception target is dynamic")
        for statement in node.body:
            self.visit(statement)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        cython_type, reason = _expr_type(node.value)
        for name in _target_names(node.target):
            if cython_type is not None and isinstance(node.target, ast.Name):
                self._record(name, _Candidate(cython_type, node.lineno, reason))
            else:
                self._block(name, line=node.lineno, reason=reason)
        self.generic_visit(node.value)

    def resolve(self) -> tuple[tuple[TypedVariable, ...], tuple[SkippedVariable, ...]]:
        typed: list[TypedVariable] = []
        skipped: list[SkippedVariable] = []
        all_names = set(self.candidates) | set(self.blocked)

        for name in sorted(all_names):
            entries = [*self.candidates.get(name, ()), *self.blocked.get(name, ())]
            lines = tuple(sorted({entry.line for entry in entries}))
            types = {entry.cython_type for entry in entries if entry.cython_type is not None}
            blocked_entries = self.blocked.get(name, [])

            if blocked_entries:
                reason = "; ".join(sorted({entry.reason for entry in blocked_entries}))
                skipped.append(
                    SkippedVariable(
                        function=self.function,
                        name=name,
                        lines=lines,
                        reason=reason,
                    )
                )
                continue

            if len(types) != 1:
                skipped.append(
                    SkippedVariable(
                        function=self.function,
                        name=name,
                        lines=lines,
                        reason="variable has mixed or unknown inferred types",
                    )
                )
                continue

            entry = min(entries, key=lambda item: item.line)
            typed.append(
                TypedVariable(
                    function=self.function,
                    name=name,
                    cython_type=next(iter(types)),
                    line=entry.line,
                    reason=entry.reason,
                )
            )

        return tuple(typed), tuple(skipped)


def analyze_source(source: str, *, filename: str = "<source>") -> PreprocessPreview:
    tree = ast.parse(source, filename=filename)
    declarations: list[FunctionDeclarations] = []
    skipped: list[SkippedVariable] = []

    for info in _iter_functions(tree.body):
        collector = _FunctionCollector(
            function=info.qualname,
            parameters=_function_args(info.node),
        )
        for statement in info.node.body:
            collector.visit(statement)
        typed, function_skipped = collector.resolve()
        if typed:
            declarations.append(
                FunctionDeclarations(
                    function=info.qualname,
                    insert_after_line=info.insert_after_line,
                    indent=info.indent,
                    variables=typed,
                )
            )
        skipped.extend(function_skipped)

    return PreprocessPreview(
        declarations=tuple(declarations),
        skipped=tuple(skipped),
    )


def render_pyx(source: str, preview: PreprocessPreview) -> str:
    lines = source.splitlines(keepends=True)
    newline = "\n"
    if lines:
        newline = "\r\n" if lines[0].endswith("\r\n") else "\n"

    groups = sorted(
        preview.declarations,
        key=lambda group: group.insert_after_line,
        reverse=True,
    )
    for group in groups:
        insert_at = group.insert_after_line
        declarations = [
            f"{group.indent}cdef {variable.cython_type} {variable.name}{newline}"
            for variable in sorted(group.variables, key=lambda item: (item.cython_type, item.name))
        ]
        lines[insert_at:insert_at] = declarations
    return "".join(lines)


def preprocess_source(source: str, *, filename: str = "<source>") -> tuple[str, PreprocessPreview]:
    preview = analyze_source(source, filename=filename)
    return render_pyx(source, preview), preview


def preprocess_file(path: Path) -> tuple[str, PreprocessPreview]:
    source = path.read_text(encoding="utf-8")
    return preprocess_source(source, filename=str(path))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a conservative .pyx preview from a Python source by inserting "
            "Cython local cdef declarations only where simple AST evidence is stable."
        )
    )
    parser.add_argument("input", type=Path, help="Python source to inspect.")
    parser.add_argument(
        "--output",
        type=Path,
        help="Path for the generated .pyx preview. Defaults to stdout when omitted.",
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        help="Optional JSON report path for declarations and skipped variables.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the JSON report to stdout instead of the generated source.",
    )
    parser.add_argument(
        "--fail-on-empty",
        action="store_true",
        help="Return a non-zero status when no safe declarations are found.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    pyx_source, preview = preprocess_file(args.input)
    report = preview.to_report(
        input_path=str(args.input),
        output_path=str(args.output) if args.output is not None else None,
    )

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(pyx_source, encoding="utf-8")

    if args.report_json is not None:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        args.report_json.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    elif args.output is None:
        print(pyx_source, end="")

    if args.fail_on_empty and not preview.typed_variables:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
