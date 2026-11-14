"""Resolve worker CLI artifacts for cluster deployment paths."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from agi_env.runtime import runtime_bootstrap_support


def resolve_worker_cli_path(env: Any) -> Path:
    """Return the node-owned worker CLI path, with legacy env fallback."""
    cli = getattr(env, "cli", None)
    if cli is not None:
        return Path(cli)
    return Path(env.cluster_pck) / "agi_distributor" / "cli.py"


def prepare_local_worker_cli(env: Any, *, copy_fn=shutil.copy) -> Path:
    """Prepare the local CLI, including pure policy for pre-SDK cleanup."""
    cli = Path(env.wenv_abs).parent / "cli.py"
    context = getattr(env, "_agilab_worker_root_context", None)
    if context is not None:
        root = runtime_bootstrap_support.resolve_worker_root(
            home_path=getattr(env, "home_abs", None),
            environ={runtime_bootstrap_support.WORKER_ROOT_ENV: str(context)},
        )
        if cli.parent.resolve(strict=False) != root:
            raise ValueError("Local CLI path does not match the selected worker root")
        helper = cli.with_name("agilab_runtime_bootstrap_support.py")
        if cli.is_symlink() or helper.is_symlink():
            raise ValueError("Local worker CLI artifacts must not be symbolic links")
        # Refresh both files together on supported preparation paths so a
        # partially installed worker never needs agi-env to validate its root.
        copy_fn(Path(runtime_bootstrap_support.__file__), helper)
    if context is not None or not cli.exists():
        copy_fn(resolve_worker_cli_path(env), cli)
    return cli
