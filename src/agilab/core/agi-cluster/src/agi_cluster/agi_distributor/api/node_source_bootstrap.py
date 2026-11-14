"""Establish the selected node origin before eager cluster or node imports."""

from __future__ import annotations

from importlib.util import find_spec
import os
from pathlib import Path
import runpy
import sys


def _load_node_source_resolver():
    """Read the standalone bootstrap API without executing node initializers."""
    spec = find_spec("agi_node")
    if spec is None or spec.origin is None:
        raise ImportError("agi-node is required before starting the cluster SDK")
    bootstrap = Path(spec.origin).parent / "agi_dispatcher/bootstrap_source_paths.py"
    return runpy.run_path(str(bootstrap))["resolve_node_source_path"]


resolve_node_source_path = _load_node_source_resolver()


def _resolve_node_src(
    sys_prefix: str | os.PathLike[str] | None = None,
    source_file: str | os.PathLike[str] | None = None,
    is_source_env: bool | None = None,
) -> str | None:
    """Return the best ``agi-node/src`` path for the current runtime layout."""
    node_src = resolve_node_source_path(
        sys_prefix=sys_prefix,
        source_file=source_file or __file__,
        is_source_env=is_source_env,
    )
    return str(node_src) if node_src is not None else None


def _bootstrap_node_src(
    *,
    sys_path: list[str] | None = None,
    sys_prefix: str | os.PathLike[str] | None = None,
    source_file: str | os.PathLike[str] | None = None,
    is_source_env: bool | None = None,
) -> str | None:
    """Reject a loaded incompatible SDK before changing import/metadata lookup."""
    target_sys_path = sys.path if sys_path is None else sys_path
    node_src = _resolve_node_src(
        sys_prefix=sys_prefix,
        source_file=source_file,
        is_source_env=is_source_env,
    )
    if node_src is None:
        return None
    if target_sys_path is sys.path:
        expected = (Path(node_src) / "agi_node").resolve()
        for name, module in tuple(sys.modules.items()):
            if name != "agi_node" and not name.startswith("agi_node."):
                continue
            origins = [getattr(module, "__file__", None)]
            origins.extend(getattr(module, "__path__", ()))
            if any(
                origin is None or not Path(origin).resolve().is_relative_to(expected)
                for origin in origins
            ):
                raise ImportError(
                    f"agi-node already loaded from an incompatible origin ({name}); "
                    f"start a fresh interpreter with {node_src} selected before SDK imports"
                )
    target_sys_path[:] = [path for path in target_sys_path if path != node_src]
    target_sys_path.insert(0, node_src)
    return node_src


# This module is imported before cluster helpers that may eagerly import node.
_node_src = _bootstrap_node_src()
