"""Sync guard for the divergent ``module_shim.py`` lineages.

Finding #13: ``module_shim.py`` exists in several lineages (top-level agilab,
agi-env, agi-cluster, plus per-app copies) that drift independently. A prior
fix wave updated some copies and skipped others.

The shared runtime mechanism is the ``_CompatModule`` proxy class that forwards
monkeypatches to the classified target module. This class MUST stay structurally
identical across every owned copy, modulo the per-package sentinel constant name
(``_AGILAB_COMPAT_TARGET_MODULE`` vs ``_COMPAT_TARGET_MODULE``). The higher-level
``activate_compat_module`` / ``_execute_target_in_current_module`` helpers carry
intentional per-package bits (gui-alias hook, legacy-name mapping, an extra
``legacy_name``/``namespace`` argument) so they are only checked for presence.

Canonical copy: ``agi-env/src/agi_env/compat/module_shim.py`` (see its docstring).
This test does NOT rewrite the loaders; it only detects silent drift.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]

# Copies owned by the deprecation-code bucket. Per-app copies are intentionally
# excluded here (they are generated/seeded from these); this guard covers the
# core lineages that drifted independently.
_OWNED_COPIES = {
    "agilab": _REPO_ROOT / "src/agilab/compat/module_shim.py",
    "agi_env": _REPO_ROOT
    / "src/agilab/core/agi-env/src/agi_env/compat/module_shim.py",
    "agi_cluster": _REPO_ROOT
    / "src/agilab/core/agi-cluster/src/agi_cluster/agi_distributor/compat/module_shim.py",
}

_CANONICAL = "agi_env"

# Known per-package sentinel constant referenced by ``_CompatModule``.
_SENTINELS = {
    "agilab": "_AGILAB_COMPAT_TARGET_MODULE",
    "agi_env": "_COMPAT_TARGET_MODULE",
    "agi_cluster": "_COMPAT_TARGET_MODULE",
}

# Public helpers that must exist in every copy.
_SHARED_CALLABLES = {"_execute_target_in_current_module", "activate_compat_module"}

_SENTINEL_PLACEHOLDER = "<AGILAB_COMPAT_SENTINEL>"


class _SentinelNormalizer(ast.NodeTransformer):
    """Replace the per-package sentinel string with a stable placeholder."""

    def __init__(self, sentinel: str) -> None:
        self._sentinel = sentinel

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        if isinstance(node.value, str) and node.value == self._sentinel:
            return ast.copy_location(ast.Constant(value=_SENTINEL_PLACEHOLDER), node)
        return node


def _module_tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _compat_module_dump(path: Path, sentinel: str) -> str:
    tree = _module_tree(path)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "_CompatModule":
            normalized = _SentinelNormalizer(sentinel).visit(node)
            ast.fix_missing_locations(normalized)
            return ast.dump(normalized)
    raise AssertionError(f"{path} does not define _CompatModule")


def _top_level_callables(path: Path) -> set[str]:
    tree = _module_tree(path)
    return {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}


def test_owned_module_shim_copies_exist() -> None:
    for name, path in _OWNED_COPIES.items():
        assert path.is_file(), f"missing module_shim copy for {name}: {path}"


@pytest.mark.parametrize("name", sorted(set(_OWNED_COPIES) - {_CANONICAL}))
def test_compat_module_proxy_matches_canonical(name: str) -> None:
    """The forwarding proxy class must not drift from the canonical copy."""

    canonical_dump = _compat_module_dump(
        _OWNED_COPIES[_CANONICAL], _SENTINELS[_CANONICAL]
    )
    candidate_dump = _compat_module_dump(_OWNED_COPIES[name], _SENTINELS[name])
    assert candidate_dump == canonical_dump, (
        f"_CompatModule in {_OWNED_COPIES[name]} drifted from the canonical copy "
        f"({_OWNED_COPIES[_CANONICAL]}); update every module_shim.py together."
    )


@pytest.mark.parametrize("name", sorted(_OWNED_COPIES))
def test_shared_callables_present_in_every_copy(name: str) -> None:
    callables = _top_level_callables(_OWNED_COPIES[name])
    missing = _SHARED_CALLABLES - callables
    assert not missing, f"{_OWNED_COPIES[name]} is missing shared helpers: {missing}"


@pytest.mark.parametrize("name", sorted(_OWNED_COPIES))
def test_declared_sentinel_is_referenced(name: str) -> None:
    """Each copy references exactly the sentinel this guard normalizes on."""

    sentinel = _SENTINELS[name]
    tree = _module_tree(_OWNED_COPIES[name])
    referenced = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.endswith("_COMPAT_TARGET_MODULE")
    }
    assert referenced == {sentinel}, (
        f"{_OWNED_COPIES[name]} references sentinels {referenced}, expected "
        f"only {{{sentinel!r}}}; update _SENTINELS if the constant name changed."
    )
