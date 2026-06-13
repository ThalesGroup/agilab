"""Conservative Cython local-variable preprocessing for worker sources.

Scope and non-goals:
- This pass only emits local Cython declarations when a value is proven stable
  from simple AST evidence inside one function body.
- Declarations are emitted as a single ``@cython.locals(...)`` decorator placed
  directly above each typed ``def`` (plus an idempotent ``import cython``), so
  the output stays valid Python for any user formatting and is checked with
  ``compile()``. A fail-open wrapper guarantees the preprocessor can never
  break a build: any failure falls back to the unmodified source.
- It never rewrites function signatures, parameters, return types, author
  decorators, or Python control flow. AGILAB dispatch inspects worker
  signatures at runtime.
- Unknown binding syntax is default-deny: if a statement binds a name without a
  positive handler, that name is skipped instead of guessed.
- Bare integer assignments remain Python objects. C integer arithmetic is only
  inferred inside guarded expressions where semantics stay narrow.
- Bounded propagation: names resolving to exactly one inferred type with zero
  blockers feed ``ast.Name`` lookups on later passes; any conflict demotes the
  name back to untyped (demote-on-doubt, monotone). Known limit:
  self-referential chains (``x = x + 1.0``) stay untyped.
- ``float``/``bool`` annotations on parameters and locals seed inference only,
  mirroring exactly what Cython 3 ``annotation_typing`` already enforces.
  ``int`` annotations deliberately stay Python ints (arbitrary precision), and
  annotated names themselves are never redeclared.
"""

from __future__ import annotations

import argparse
import ast
import builtins
import json
import logging
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence


logger = logging.getLogger(__name__)

CYTHON_NUMERIC_TYPES = {"bint", "double", "Py_ssize_t"}
_CALL_BUILTINS = {"bool", "enumerate", "float", "isinstance", "len", "range"}
_SMALL_INT_LITERAL_ABS_LIMIT = 1_000_000
_PY_SSIZE_MIN = -sys.maxsize - 1
_PY_SSIZE_MAX = sys.maxsize
_CYTHON_LOCALS_TYPE_MAP = {
    "Py_ssize_t": "cython.Py_ssize_t",
    "bint": "cython.bint",
    "double": "cython.double",
}
_STATIC_INT_UNKNOWN = object()
#: Distinct from ``_STATIC_INT_UNKNOWN``: the operand is provably an integer whose
#: magnitude cannot fit in ``Py_ssize_t`` (or is too large to evaluate exactly).
#: An *unknown* (e.g. a variable bound) stays optimistically typed, but an
#: *overflow* must block the loop-index typing — and it must stay overflow through
#: further arithmetic so a later ``- 1`` cannot cancel it back into range.
_STATIC_INT_OVERFLOW = object()


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
    def_line: int
    indent: str
    variables: tuple[TypedVariable, ...]


@dataclass(frozen=True)
class PreprocessPreview:
    declarations: tuple[FunctionDeclarations, ...]
    skipped: tuple[SkippedVariable, ...]
    degraded_reasons: tuple[str, ...] = ()

    @property
    def typed_variables(self) -> tuple[TypedVariable, ...]:
        return tuple(variable for group in self.declarations for variable in group.variables)

    def to_report(self, *, input_path: str | None = None, output_path: str | None = None) -> dict:
        report: dict[str, object] = {
            "declarations": [asdict(variable) for variable in self.typed_variables],
            "skipped": [asdict(variable) for variable in self.skipped],
            "degraded_reasons": list(self.degraded_reasons),
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


def _static_int_value(node: ast.AST) -> int | object:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, int) and not isinstance(node.value, bool):
            return node.value
        return _STATIC_INT_UNKNOWN
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd):
        return _static_int_value(node.operand)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        value = _static_int_value(node.operand)
        if isinstance(value, int):
            return -value
        # Negating a provably-overflowing magnitude still overflows.
        return _STATIC_INT_OVERFLOW if value is _STATIC_INT_OVERFLOW else _STATIC_INT_UNKNOWN
    if not isinstance(node, ast.BinOp):
        return _STATIC_INT_UNKNOWN

    left = _static_int_value(node.left)
    right = _static_int_value(node.right)
    # An unknown operand makes the whole expression unknown; a provably
    # out-of-range operand makes it provably out-of-range. Propagate overflow
    # rather than collapsing it to a concrete sentinel int, so a later ``- 1``
    # or ``+ k`` cannot cancel it back into Py_ssize_t range.
    if left is _STATIC_INT_UNKNOWN or right is _STATIC_INT_UNKNOWN:
        return _STATIC_INT_UNKNOWN
    if left is _STATIC_INT_OVERFLOW or right is _STATIC_INT_OVERFLOW:
        return _STATIC_INT_OVERFLOW
    try:
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.FloorDiv) and right != 0:
            return left // right
        if isinstance(node.op, ast.Mod) and right != 0:
            return left % right
        if isinstance(node.op, ast.Pow) and right >= 0:
            if abs(left) > 1 and right > _PY_SSIZE_MAX.bit_length():
                return _STATIC_INT_OVERFLOW
            return left**right
    except ArithmeticError:
        return _STATIC_INT_UNKNOWN
    return _STATIC_INT_UNKNOWN


def _fits_py_ssize_t(value: int) -> bool:
    return _PY_SSIZE_MIN <= value <= _PY_SSIZE_MAX


def _numeric_operand_type(
    node: ast.AST,
    *,
    shadowed_builtins: set[str],
    allow_int_literal: bool,
    env: dict[str, str] | None = None,
) -> tuple[str | None, str]:
    cython_type, reason = _expr_type(node, shadowed_builtins=shadowed_builtins, env=env)
    if cython_type is not None:
        return cython_type, reason
    if allow_int_literal and _is_small_int_literal(node):
        return "Py_ssize_t", "small int literal operand"
    return None, reason


def _expr_type(
    node: ast.AST,
    *,
    shadowed_builtins: set[str] | None = None,
    env: dict[str, str] | None = None,
) -> tuple[str | None, str]:
    if shadowed_builtins is None:
        shadowed_builtins = set()

    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return "bint", "bool literal"
        if isinstance(node.value, float):
            return "double", "float literal"
        return None, "literal keeps Python object semantics"

    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
        resolved = env.get(node.id) if env else None
        if resolved is not None:
            return resolved, "propagated local type"
        return None, "name type is not statically known"

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return _expr_type(node.operand, shadowed_builtins=shadowed_builtins, env=env)

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
                    env=env,
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
            env=env,
        )
        right_type, _ = _numeric_operand_type(
            node.right,
            shadowed_builtins=shadowed_builtins,
            allow_int_literal=True,
            env=env,
        )
        if left_type in CYTHON_NUMERIC_TYPES and right_type in CYTHON_NUMERIC_TYPES:
            if isinstance(node.op, ast.Div):
                # Python 3 true division yields float even for integer operands.
                return "double", "true division result"
            if isinstance(node.op, ast.Pow):
                # Power results (e.g. negative exponents) are not statically safe.
                return None, "power expression type is not statically safe"
            if (
                isinstance(node.op, ast.Mult)
                and "double" not in {left_type, right_type}
                and not (_is_small_int_literal(node.left) or _is_small_int_literal(node.right))
            ):
                # Integer products can overflow silently; double products mirror
                # Python float semantics (IEEE inf), so only integer-typed
                # multiplication requires a small literal operand.
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


def _range_loop_index_candidate(
    node: ast.AST,
    *,
    shadowed_builtins: set[str],
) -> tuple[bool, str] | None:
    if not _is_range_call(node, shadowed_builtins=shadowed_builtins):
        return None
    if not isinstance(node, ast.Call):
        return None
    if node.keywords:
        return (False, "range() call uses keyword arguments")
    if len(node.args) not in {1, 2, 3}:
        return (False, "range() argument count is invalid")
    for argument in node.args:
        value = _static_int_value(argument)
        if value is _STATIC_INT_OVERFLOW or (
            isinstance(value, int) and not _fits_py_ssize_t(value)
        ):
            return (False, "range() bound exceeds Py_ssize_t")
    return (True, "range() loop index")


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


def _annotation_env_seeds(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    shadowed_builtins: set[str],
) -> dict[str, str]:
    """Mirror Cython 3 ``annotation_typing`` for ``float``/``bool`` annotations.

    Seeded names feed dependent inference only and are never redeclared by this
    pass: Cython already types them, so re-emitting a declaration would be a
    redeclaration. ``int`` annotations are deliberately not seeded because
    Cython 3 keeps them Python ints (arbitrary precision).
    """

    seeds: dict[str, str] = {}
    conflicted: set[str] = set()

    def _add(name: str, annotation: ast.AST | None) -> None:
        if annotation is None:
            return
        if isinstance(annotation, ast.Name) and annotation.id in shadowed_builtins:
            return
        cython_type = _annotation_type(annotation)
        if cython_type is None:
            return
        if seeds.get(name, cython_type) != cython_type:
            conflicted.add(name)
        seeds[name] = cython_type

    args = node.args
    for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
        _add(arg.arg, arg.annotation)

    def _scan(statements: Iterable[ast.stmt]) -> None:
        for statement in statements:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                _add(statement.target.id, statement.annotation)
            for body_field in ("body", "orelse", "finalbody"):
                _scan(getattr(statement, body_field, None) or [])
            for handler in getattr(statement, "handlers", None) or []:
                _scan(handler.body)
            for case in getattr(statement, "cases", None) or []:
                _scan(case.body)

    _scan(node.body)
    for name in conflicted:
        seeds.pop(name, None)
    return seeds


def _cython_name_rebound(tree: ast.AST) -> bool:
    """Return True when the source rebinds the name ``cython`` anywhere.

    An emitted ``@cython.locals`` decorator would resolve against the user's
    object instead of the cython module; demote-on-doubt and skip emission.
    A plain top-level ``import cython`` is the supported case, not a rebind.
    """

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)) and node.id == "cython":
            return True
        if isinstance(node, ast.arg) and node.arg == "cython":
            return True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == "cython":
            return True
        if isinstance(node, ast.ExceptHandler) and node.name == "cython":
            return True
        if isinstance(node, (ast.Global, ast.Nonlocal)) and "cython" in node.names:
            return True
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".", 1)[0]
                if bound == "cython" and not (alias.name == "cython" and alias.asname is None):
                    return True
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if (alias.asname or alias.name) == "cython":
                    return True
        if isinstance(node, (ast.MatchAs, ast.MatchStar)) and getattr(node, "name", None) == "cython":
            return True
        if isinstance(node, ast.MatchMapping) and node.rest == "cython":
            return True
    return False


def _has_author_cython_locals(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if (
            isinstance(target, ast.Attribute)
            and target.attr == "locals"
            and isinstance(target.value, ast.Name)
            and target.value.id == "cython"
        ):
            return True
    return False


def _iter_functions(
    nodes: Iterable[ast.stmt],
    prefix: tuple[str, ...] = (),
) -> Iterable[_FunctionInfo]:
    for node in nodes:
        if isinstance(node, ast.ClassDef):
            yield from _iter_functions(node.body, (*prefix, node.name))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qualname = ".".join((*prefix, node.name))
            yield _FunctionInfo(qualname=qualname, node=node)
            yield from _iter_functions(node.body, (*prefix, node.name))


class _FunctionCollector(ast.NodeVisitor):
    def __init__(
        self,
        *,
        function: str,
        parameters: set[str],
        shadowed_builtins: set[str],
        env: dict[str, str] | None = None,
    ) -> None:
        self.function = function
        self.parameters = parameters
        self.shadowed_builtins = shadowed_builtins
        self.env = env or {}
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
        cython_type, reason = _expr_type(
            node.value,
            shadowed_builtins=self.shadowed_builtins,
            env=self.env,
        )
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
            _, value_reason = _expr_type(
                node.value,
                shadowed_builtins=self.shadowed_builtins,
                env=self.env,
            )

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
        if isinstance(node.target, ast.Name):
            name = node.target.id
            if self.env.get(name) is None:
                # Pending: the target's type is not in the environment yet.
                # Recording nothing keeps the name env-eligible from its other
                # binding sites; the next propagation pass re-evaluates this
                # site target-aware and demotes on any conflict.
                pass
            else:
                synthetic = ast.BinOp(
                    left=ast.Name(id=name, ctx=ast.Load()),
                    op=node.op,
                    right=node.value,
                )
                cython_type, reason = _expr_type(
                    synthetic,
                    shadowed_builtins=self.shadowed_builtins,
                    env=self.env,
                )
                if cython_type is not None:
                    self._record(name, _Candidate(cython_type, node.lineno, reason))
                else:
                    self._block(name, line=node.lineno, reason=reason)
        else:
            cython_type, reason = _expr_type(
                node.value,
                shadowed_builtins=self.shadowed_builtins,
                env=self.env,
            )
            for name in _bound_names(node.target):
                self._block(name, line=node.lineno, reason=reason)
        self.generic_visit(node.value)

    def visit_For(self, node: ast.For) -> None:
        names = _bound_names(node.target)
        range_candidate = _range_loop_index_candidate(
            node.iter,
            shadowed_builtins=self.shadowed_builtins,
        )
        if isinstance(node.target, ast.Name) and range_candidate is not None:
            is_safe_range_index, reason = range_candidate
            if is_safe_range_index:
                self._record(
                    node.target.id,
                    _Candidate("Py_ssize_t", node.lineno, reason),
                )
            else:
                self._block(node.target.id, line=node.lineno, reason=reason)
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
        # Cython forbids deleting C-typed locals; never give del'ed names a type.
        for target in node.targets:
            for name in _bound_names(target):
                self._block(name, line=node.lineno, reason="variable is deleted")

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        cython_type, reason = _expr_type(
            node.value,
            shadowed_builtins=self.shadowed_builtins,
            env=self.env,
        )
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


def _analyze_function(
    info: _FunctionInfo,
) -> tuple[tuple[TypedVariable, ...], tuple[SkippedVariable, ...]]:
    """Run bounded propagation passes over one function body.

    Pass 1 is the plain per-site collection; names resolving to exactly one
    inferred type with zero blockers (plus annotation seeds) form the
    environment for the next pass, where ``_expr_type`` resolves ``ast.Name``
    loads. Conflicts demote names permanently (demote-on-doubt) and the loop
    repeats until the environment is stable. Each non-stable pass either grows
    the demoted set or the environment, so the pass budget always suffices.
    Known limit: self-referential chains (``x = x + 1.0``) stay untyped.
    """

    node = info.node
    parameters = _function_args(node)
    shadowed = _shadowed_builtins(node)
    seeds = _annotation_env_seeds(node, shadowed_builtins=shadowed)
    env: dict[str, str] = dict(seeds)
    demoted: dict[str, str] = {}
    pass_budget: int | None = None
    typed: tuple[TypedVariable, ...] = ()
    function_skipped: tuple[SkippedVariable, ...] = ()

    while True:
        collector = _FunctionCollector(
            function=info.qualname,
            parameters=parameters,
            shadowed_builtins=shadowed,
            env=env,
        )
        for statement in node.body:
            collector.visit(statement)
        typed, function_skipped = collector.resolve()
        if pass_budget is None:
            names = set(collector.candidates) | set(collector.blocked) | set(seeds)
            pass_budget = 2 * len(names) + 2

        next_env = dict(seeds)
        for variable in typed:
            if variable.name not in demoted and variable.name not in seeds:
                next_env[variable.name] = variable.cython_type
        for name, cython_type in env.items():
            if name in seeds:
                continue
            if next_env.get(name) != cython_type:
                demoted[name] = "propagated type conflicted across passes; demoted to untyped"
                next_env.pop(name, None)

        if next_env == env:
            break
        pass_budget -= 1
        if pass_budget <= 0:
            # Unreachable by the monotonicity bound; demote everything rather
            # than emit declarations derived from an unstable environment.
            demoted.update(
                {
                    variable.name: "propagation did not stabilize; demoted to untyped"
                    for variable in typed
                }
            )
            break
        env = next_env

    skipped_names = {item.name for item in function_skipped}
    extra_skipped = tuple(
        SkippedVariable(
            function=info.qualname,
            name=variable.name,
            lines=(variable.line,),
            reason=demoted[variable.name],
        )
        for variable in typed
        if variable.name in demoted and variable.name not in skipped_names
    )
    final_typed = tuple(variable for variable in typed if variable.name not in demoted)
    return final_typed, (*function_skipped, *extra_skipped)


def analyze_source(source: str, *, filename: str = "<source>") -> PreprocessPreview:
    tree = ast.parse(source, filename=filename)
    source_lines = source.splitlines()
    cython_rebound = _cython_name_rebound(tree)
    declarations: list[FunctionDeclarations] = []
    skipped: list[SkippedVariable] = []

    for info in _iter_functions(tree.body):
        typed, function_skipped = _analyze_function(info)
        if typed and cython_rebound:
            skipped.extend(
                SkippedVariable(
                    function=info.qualname,
                    name=variable.name,
                    lines=(variable.line,),
                    reason="the name 'cython' is rebound in source",
                )
                for variable in typed
            )
        elif typed and _has_author_cython_locals(info.node):
            skipped.extend(
                SkippedVariable(
                    function=info.qualname,
                    name=variable.name,
                    lines=(variable.line,),
                    reason="author-owned cython.locals present",
                )
                for variable in typed
            )
        elif typed:
            def_line = int(info.node.lineno)
            line_text = source_lines[def_line - 1] if def_line - 1 < len(source_lines) else ""
            declarations.append(
                FunctionDeclarations(
                    function=info.qualname,
                    def_line=def_line,
                    indent=line_text[: info.node.col_offset],
                    variables=typed,
                )
            )
        skipped.extend(function_skipped)

    return PreprocessPreview(
        declarations=tuple(declarations),
        skipped=tuple(skipped),
    )


def _locals_decorator_line(group: FunctionDeclarations, newline: str) -> str:
    arguments = ", ".join(
        f"{variable.name}={_CYTHON_LOCALS_TYPE_MAP[variable.cython_type]}"
        for variable in sorted(group.variables, key=lambda item: (item.cython_type, item.name))
    )
    return f"{group.indent}@cython.locals({arguments}){newline}"


def _has_top_level_cython_import(tree: ast.Module, *, before_line: int) -> bool:
    for statement in tree.body:
        if isinstance(statement, ast.Import) and statement.lineno < before_line:
            for alias in statement.names:
                if alias.name == "cython" and alias.asname is None:
                    return True
    return False


def _module_prelude_insert_index(tree: ast.Module, lines: Sequence[str]) -> int:
    """Return the 0-based line index where ``import cython`` belongs.

    The import lands after the module docstring and any ``__future__`` imports;
    without those it lands after leading blank/comment lines (shebang, coding
    declaration, agilab-pyx stamp).
    """

    insert_after = 0
    index = 0
    body = tree.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        insert_after = int(getattr(body[0], "end_lineno", body[0].lineno))
        index = 1
    while (
        index < len(body)
        and isinstance(body[index], ast.ImportFrom)
        and body[index].module == "__future__"
    ):
        insert_after = int(getattr(body[index], "end_lineno", body[index].lineno))
        index += 1
    if insert_after:
        return insert_after

    limit = body[0].lineno - 1 if body else len(lines)
    position = 0
    while position < limit:
        stripped = lines[position].strip()
        if stripped and not stripped.startswith("#"):
            break
        position += 1
    return position


def render_pyx(source: str, preview: PreprocessPreview) -> str:
    groups = [group for group in preview.declarations if group.variables]
    if not groups:
        return source

    lines = source.splitlines(keepends=True)
    newline = "\r\n" if lines and lines[0].endswith("\r\n") else "\n"
    for group in sorted(groups, key=lambda item: item.def_line, reverse=True):
        lines.insert(group.def_line - 1, _locals_decorator_line(group, newline))

    tree = ast.parse(source)
    first_def_line = min(group.def_line for group in groups)
    if not _has_top_level_cython_import(tree, before_line=first_def_line):
        lines.insert(
            _module_prelude_insert_index(tree, source.splitlines()),
            f"import cython{newline}",
        )
    return "".join(lines)


def preprocess_source(source: str, *, filename: str = "<source>") -> tuple[str, PreprocessPreview]:
    preview: PreprocessPreview | None = None
    try:
        preview = analyze_source(source, filename=filename)
        rendered = render_pyx(source, preview)
        # The decorator-based output is valid Python; gate it before use.
        compile(rendered, filename, "exec")
        return rendered, preview
    # Defensive boundary: the preprocessor is an optional optimization pass and
    # must never break a worker build; fall back to the unmodified source and
    # record the degradation in the report.
    except Exception as error:
        reason = f"{type(error).__name__}: {error}"
        logger.warning(
            "Cython type preprocessing failed for %s; using original source (%s)",
            filename,
            reason,
        )
        return source, PreprocessPreview(
            declarations=(),
            skipped=preview.skipped if preview is not None else (),
            degraded_reasons=(f"preprocessing degraded to passthrough: {reason}",),
        )


def preprocess_file(path: Path) -> tuple[str, PreprocessPreview]:
    source = path.read_text(encoding="utf-8")
    return preprocess_source(source, filename=str(path))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a conservative .pyx preview from a Python source by adding "
            "@cython.locals decorators only where simple AST evidence is stable."
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
