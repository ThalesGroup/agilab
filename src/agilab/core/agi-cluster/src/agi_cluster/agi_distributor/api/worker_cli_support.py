"""Resolve worker CLI artifacts for cluster deployment paths."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def resolve_worker_cli_path(env: Any) -> Path:
    """Return the node-owned worker CLI path, with legacy env fallback."""
    cli = getattr(env, "cli", None)
    if cli is not None:
        return Path(cli)
    return Path(env.cluster_pck) / "agi_distributor" / "cli.py"
