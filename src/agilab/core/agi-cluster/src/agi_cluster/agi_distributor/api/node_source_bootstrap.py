"""Establish the selected node origin before eager cluster or node imports."""

from __future__ import annotations

from importlib.util import find_spec
from inspect import Parameter, signature
import os
from pathlib import Path
import runpy
import sys


def _cluster_core_source_root(source_file: str | os.PathLike[str]) -> Path | None:
    """Recognize only this cluster package's own source SDK layout."""
    try:
        source_path = Path(source_file).resolve()
    except (OSError, RuntimeError):
        return None
    if {"site-packages", "dist-packages"}.intersection(source_path.parts):
        return None
    for package_root in source_path.parents:
        core_root = package_root.parent
        if (
            package_root.name == "agi-cluster"
            and core_root.name == "core"
            and core_root.parent.name == "agilab"
            and source_path.relative_to(package_root).parts[:2] == ("src", "agi_cluster")
        ):
            return core_root
    return None


def _load_node_source_resolver():
    """Read the standalone bootstrap API without executing node initializers."""
    # A released node may precede a source SDK on sys.path. Prefer this source
    # policy; the policy itself still honors source opt-out.
    core_root = _cluster_core_source_root(__file__)
    if core_root is not None:
        bootstrap = (
            core_root / "agi-node" / "src" / "agi_node"
            / "agi_dispatcher" / "bootstrap_source_paths.py"
        )
        if bootstrap.is_file():
            return runpy.run_path(str(bootstrap))["resolve_node_source_path"]
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
    """Return the selected agi-node source path for the current runtime layout."""
    parameters = signature(resolve_node_source_path).parameters
    selector = parameters.get("is_source_env")
    accepts_selector = (
        selector is not None
        and selector.kind in (Parameter.POSITIONAL_OR_KEYWORD, Parameter.KEYWORD_ONLY)
    ) or any(parameter.kind == Parameter.VAR_KEYWORD for parameter in parameters.values())
    if not accepts_selector:
        # Never strip the selector and invoke the old permissive ancestor search.
        selected = is_source_env
        if selected is None:
            raw = os.environ.get("IS_SOURCE_ENV")
            if raw is not None:
                selected = raw.strip().lower() not in {"", "0", "false", "no"}
        if selected is False:
            return None
        if selected is True or _cluster_core_source_root(source_file or __file__) is not None:
            raise ImportError(
                "Source SDK bootstrap requires agi-cluster and agi-node "
                "from the same source snapshot; the selected agi-node policy "
                "does not support source selection."
            )
        return None
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
