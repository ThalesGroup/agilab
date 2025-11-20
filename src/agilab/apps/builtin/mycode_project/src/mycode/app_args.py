"""Compatibility wrapper for documentation tooling.

Older scripts expect each app to expose an ``app_args`` module. The project now
stores its argument models in ``mycode_args.py``, so this module simply re-exports
those symbols.
"""

from .mycode_args import (
    MycodeArgs,
    MycodeArgsTD,
    ArgsModel,
    ArgsOverrides,
    load_args,
    merge_args,
    dump_args,
    ensure_defaults,
)

__all__ = [
    "MycodeArgs",
    "MycodeArgsTD",
    "ArgsModel",
    "ArgsOverrides",
    "load_args",
    "merge_args",
    "dump_args",
    "ensure_defaults",
]
