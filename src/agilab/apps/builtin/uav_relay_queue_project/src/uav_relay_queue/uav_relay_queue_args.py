"""Compatibility wrapper for descriptive UAV relay queue argument imports."""

from .app_args import (
    UavRelayQueueArgs,
    UavRelayQueueArgsTD,
    UavQueueArgs,
    UavQueueArgsTD,
    dump_args,
    ensure_defaults,
    load_args,
    merge_args,
)

__all__ = [
    "UavRelayQueueArgs",
    "UavRelayQueueArgsTD",
    "UavQueueArgs",
    "UavQueueArgsTD",
    "dump_args",
    "ensure_defaults",
    "load_args",
    "merge_args",
]
