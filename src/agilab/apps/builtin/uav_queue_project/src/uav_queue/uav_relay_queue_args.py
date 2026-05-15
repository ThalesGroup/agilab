"""Compatibility wrapper for historical relay-queue argument imports."""

from .app_args import (
    UavRelayQueueArgs,
    UavRelayQueueArgsTD,
    dump_args,
    ensure_defaults,
    load_args,
    merge_args,
)

__all__ = [
    "UavRelayQueueArgs",
    "UavRelayQueueArgsTD",
    "dump_args",
    "ensure_defaults",
    "load_args",
    "merge_args",
]
