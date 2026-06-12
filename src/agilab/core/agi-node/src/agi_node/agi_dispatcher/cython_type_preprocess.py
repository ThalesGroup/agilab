"""Conservative Cython local-variable preprocessing for worker sources.

Scope and non-goals:
- This pass only emits local Cython declarations when a value is proven stable
  from simple AST evidence inside one function body.
- It never rewrites function signatures, parameters, return types, decorators,
  or Python control flow. AGILAB dispatch inspects worker signatures at runtime.
- Unknown binding syntax is default-deny: if a statement binds a name without a
  positive handler, that name is skipped instead of guessed.
- Bare integer assignments remain Python objects. C integer arithmetic is only
  inferred inside guarded expressions where semantics stay narrow.
"""

from __future__ import annotations

import argparse
import ast
import builtins
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence


CYTHON_NUMERIC_TYPES = {"bint", "double", "Py_ssize_t"}
_CALL_BUILTINS = {"bool", "enumerate", "float", "isinstance", "len", "range"}
_SMALL_INT_LITERAL_ABS_LIMIT = 1_000_000


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


def _is_small_int_literal(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return (
            isinstance(node.value, int)
            and not isinstance(node.value, bool)
            and abs(node.value) <= _SMALL_INT_LITERAL_ABS_LIMIT
        )
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return _is_small_int_literal(node.operand)
    return False


def _numeric_operand_type(
    node: ast.AST,
    *,
    shadowed_builtins: set[str],
    allow_int_literal: bool,
) -> tuple[str | None, str]:
    cython_type, reason = _expr_type(node, shadowed_builtins=shadowed_builtins)
    if cython_type is not None:
        return cython_type, reason
    if allow_int_literal and _is_small_int_literal(node):
        return "Py_ssize_t", "small int literal operand"
    return None, reason


def _expr_type(
    node: ast.AST,
    *,
    shadowed_builtins: set[str] | None = None,
) -> tuple[str | None, str]:
    if shadowed_builtins is None:
        shadowed_builtins = set()

    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return "bint", "bool literal"
        if isinstance(node.value, float):
            return "double", "float literal"
        return None, "literal keeps Python object semantics"

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return _expr_type(node.operand, shadowed_builtins=shadowed_builtins)

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return "bint", "not expression"

    if isinstance(node, ast.Compare):
        boolean_ops = (ast.Is, ast.IsNot, ast.In, ast.NotIn)
        numeric_ops = (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE)
        if all(isinstance(op, boolean_ops) for op in node.ops):
            return "bint", "identity or membership comparison"
        if all(isinstance(op, numeric_ops) for op in node.ops):
            operands = (node.left, *node.comparators)
            operand_types = [
                _numeric_operand_type(
                    operand,
                    shadowed_builtins=shadowed_builtins,
                    allow_int_literal=True,
                )[0]
                for operand in operands
            ]
            if all(operand_type in CYTHON_NUMERIC_TYPES for operand_type in operand_types):
                return "bint", "numeric comparison result"
        return None, "comparison operands are not statically numeric"

    if isinstance(node, ast.BinOp):
        left_type, _ = _numeric_operand_type(
            node.left,
            shadowed_builtins=shadowed_builtins,
            allow_int_literal=True,
        )
        right_type, _ = _numeric_operand_type(
            node.right,
            shadowed_builtins=shadowed_builtins,
            allow_int_literal=True,
        )
        if left_type in CYTHON_NUMERIC_TYPES and right_type in CYTHON_NUMERIC_TYPES:
            if isinstance(node.op, ast.Div):
                # Python 3 true division yields float even for integer operands.
                return "double", "true division result"
            if isinstance(node.op, ast.Pow):
                # Power results (e.g. negative exponents) are not statically safe.
                return None, "power expression type is not statically safe"
            if isinstance(node.op, ast.Mult) and not (
                _is_small_int_literal(node.left) or _is_small_int_literal(node.right)
            ):
                return None, "multiplication requires a small literal operand"
            if not isinstance(
                node.op,
                (ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.Mod, ast.Div),
            ):
                return None, "operator is not statically safe"
            if "double" in {left_type, right_type}:
                return "double", "numeric expression"
            return "Py_ssize_t", "integer-sized numeric expression"
        return None, "expression type is not statically safe"

    if isinstance(node, ast.Call):
        name = _call_name(node.func)
        if name == "len" and name not in shadowed_builtins:
            return "Py_ssize_t", "len() result"
        if name == "float" and name not in shadowed_builtins:
            return "double", "float() result"
        if name == "bool" and name not in shadowed_builtins:
            return "bint", "bool() result"
        if name == "isinstance" and name not in shadowed_builtins:
            return "bint", "isinstance() result"
        return None, "call result is dynamic"

    return None, "expression type is dynamic"


def _pattern_bound_names(pattern: ast.AST) -> tuple[str, ...]:
    names: list[str] = []
    if isinstance(pattern, ast.MatchAs):
        if pattern.name:
            names.append(pattern.name)
        if pattern.pattern is not None:
            names.extend(_pattern_bound_names(pattern.pattern))
    elif isinstance(pattern, ast.MatchStar):
        if pattern.name:
            names.append(pattern.name)
    elif isinstance(pattern, ast.MatchMapping):
        if pattern.rest:
            names.append(pattern.rest)
        for child in pattern.patterns:
            names.extend(_pattern_bound_names(child))
    elif isinstance(pattern, ast.MatchClass):
        for child in [*pattern.patterns, *pattern.kwd_patterns]:
            names.extend(_pattern_bound_names(child))
    elif isinstance(pattern, (ast.MatchSequence, ast.MatchOr)):
        for child in pattern.patterns:
            names.extend(_pattern_bound_names(child))
    return tuple(names)


def _bound_names(target: ast.AST) -> tuple[str, ...]:
    if isinstance(target, ast.Name) and isinstance(target.ctx, (ast.Store, ast.Del)):
        return (target.id,)
    if isinstance(target, ast.Starred):
        return _bound_names(target.value)
    if isinstance(target, (ast.Tuple, ast.List)):
        names: list[str] = []
        for item in target.elts:
            names.extend(_bound_names(item))
        return tuple(names)
    if isinstance(target, ast.ExceptHandler):
        return (target.name,) if target.name else ()
    if isinstance(target, ast.alias):
        return (target.asname or target.name.split(".", 1)[0],)
    if isinstance(target, (ast.MatchAs, ast.MatchStar, ast.MatchMapping, ast.MatchClass, ast.MatchSequence, ast.MatchOr)):
        return _pattern_bound_names(target)
    if isinstance(target, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return (target.name,)
    return ()


def _is_range_call(node: ast.AST, *, shadowed_builtins: set[str]) -> bool:
    return (
        isinstance(node, ast.Call)
        and _call_name(node.func) == "range"
        and "range" not in shadowed_builtins
    )


def _is_safe_enumerate_call(node: ast.AST, *, shadowed_builtins: set[str]) -> bool:
    return (
        isinstance(node, ast.Call)
        and _call_name(node.func) == "enumerate"
        and "enumerate" not in shadowed_builtins
        and len(node.args) == 1
        and not node.keywords
    )


def _statement_bound_names(statement: ast.stmt) -> tuple[str, ...]:
    names: list[str] = []
    for child in ast.walk(statement):
        if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
            names.append(child.id)
        elif isinstance(child, ast.alias):
            names.extend(_bound_names(child))
        elif isinstance(child, ast.ExceptHandler):
            names.extend(_bound_names(child))
        elif isinstance(child, (ast.MatchAs, ast.MatchStar, ast.MatchMapping, ast.MatchClass, ast.MatchSequence, ast.MatchOr)):
            names.extend(_bound_names(child))
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and child is statement:
            names.extend(_bound_names(child))
    return tuple(names)


def _shadowed_builtins(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    builtin_names = set(dir(builtins)) | _CALL_BUILTINS
    bound: set[str] = set()
    for statement in node.body:
        bound.update(_statement_bound_names(statement))
    return bound & builtin_names


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
            if node.body[0].lineno == node.lineno:
                return -1
            return int(getattr(node.body[0], "end_lineno", node.body[0].lineno))
    if node.body and node.body[0].lineno > node.lineno:
        # Insert just before the first body statement so multi-line signatures
        # ("def foo(\n    a,\n):") never receive cdefs inside the parens.
        return int(node.body[0].lineno) - 1
    # Inline one-liner def ("def f(): x = 1.0"): no valid insertion point.
    return -1


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
    def __init__(self, *, function: str, parameters: set[str], shadowed_builtins: set[str]) -> None:
        self.function = function
        self.parameters = parameters
        self.shadowed_builtins = shadowed_builtins
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
        self._block(node.name, line=node.lineno, reason="nested function binding is dynamic")
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._block(node.name, line=node.lineno, reason="nested async function binding is dynamic")
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._block(node.name, line=node.lineno, reason="nested class binding is dynamic")
        return

    def visit_Assign(self, node: ast.Assign) -> None:
        cython_type, reason = _expr_type(node.value, shadowed_builtins=self.shadowed_builtins)
        for target in node.targets:
            names = _bound_names(target)
            if isinstance(target, ast.Name) and cython_type is not None:
                self._record(target.id, _Candidate(cython_type, node.lineno, reason))
            else:
                for name in names:
                    self._block(name, line=node.lineno, reason=reason)
        self.generic_visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        names = _bound_names(node.target)
        annotation_type = _annotation_type(node.annotation)
        value_reason = "annotated assignment without value"
        if node.value is not None:
            _, value_reason = _expr_type(node.value, shadowed_builtins=self.shadowed_builtins)

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
        names = _bound_names(node.target)
        cython_type, reason = _expr_type(node.value, shadowed_builtins=self.shadowed_builtins)
        if isinstance(node.target, ast.Name) and cython_type is not None:
            self._record(node.target.id, _Candidate(cython_type, node.lineno, reason))
        else:
            for name in names:
                self._block(name, line=node.lineno, reason=reason)
        self.generic_visit(node.value)

    def visit_For(self, node: ast.For) -> None:
        names = _bound_names(node.target)
        if isinstance(node.target, ast.Name) and _is_range_call(
            node.iter,
            shadowed_builtins=self.shadowed_builtins,
        ):
            self._record(
                node.target.id,
                _Candidate("Py_ssize_t", node.lineno, "range() loop index"),
            )
        elif (
            isinstance(node.target, (ast.Tuple, ast.List))
            and len(node.target.elts) == 2
            and isinstance(node.target.elts[0], ast.Name)
            and _is_safe_enumerate_call(node.iter, shadowed_builtins=self.shadowed_builtins)
        ):
            self._record(
                node.target.elts[0].id,
                _Candidate("Py_ssize_t", node.lineno, "enumerate() loop index"),
            )
            for name in _bound_names(node.target.elts[1]):
                self._block(name, line=node.lineno, reason="enumerate() value target is dynamic")
        else:
            for name in names:
                self._block(name, line=node.lineno, reason="loop target is dynamic")
        for statement in [*node.body, *node.orelse]:
            self.visit(statement)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        for name in _bound_names(node.target):
            self._block(name, line=node.lineno, reason="async loop target is dynamic")
        for statement in [*node.body, *node.orelse]:
            self.visit(statement)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            if item.optional_vars is not None:
                for name in _bound_names(item.optional_vars):
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
                for name in _bound_names(item.optional_vars):
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

    def visit_Delete(self, node: ast.Delete) -> None:
        # Cython forbids deleting C-typed locals; never give del'ed names a cdef.
        for target in node.targets:
            for name in _bound_names(target):
                self._block(name, line=node.lineno, reason="variable is deleted")

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        cython_type, reason = _expr_type(node.value, shadowed_builtins=self.shadowed_builtins)
        for name in _bound_names(node.target):
            if cython_type is not None and isinstance(node.target, ast.Name):
                self._record(name, _Candidate(cython_type, node.lineno, reason))
            else:
                self._block(name, line=node.lineno, reason=reason)
        self.generic_visit(node.value)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            for name in _bound_names(alias):
                self._block(name, line=node.lineno, reason="import target is dynamic")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            for name in _bound_names(alias):
                self._block(name, line=node.lineno, reason="import target is dynamic")

    def visit_Match(self, node: ast.Match) -> None:
        for case in node.cases:
            for name in _bound_names(case.pattern):
                self._block(name, line=node.lineno, reason="match capture target is dynamic")
            if case.guard is not None:
                self.visit(case.guard)
            for statement in case.body:
                self.visit(statement)

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
            shadowed_builtins=_shadowed_builtins(info.node),
        )
        for statement in info.node.body:
            collector.visit(statement)
        typed, function_skipped = collector.resolve()
        if typed and info.insert_after_line < 0:
            skipped.extend(
                SkippedVariable(
                    function=info.qualname,
                    name=variable.name,
                    lines=(variable.line,),
                    reason="no safe insertion point for inline function body",
                )
                for variable in typed
            )
        elif typed:
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
