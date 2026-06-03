"""PyTorch playground AGILAB app."""

from __future__ import annotations

from .runtime.app_args import (
    ArgsModel,
    ArgsOverrides,
    PytorchPlaygroundArgs,
    PytorchPlaygroundArgsTD,
    dump_args,
    ensure_defaults,
    load_args,
    merge_args,
    to_playground_config,
)
from .runtime.reduction import PYTORCH_PLAYGROUND_REDUCE_CONTRACT

_MANAGER_EXPORTS = {"PytorchPlayground", "PytorchPlaygroundApp"}


def __getattr__(name: str):
    if name in _MANAGER_EXPORTS:
        from .runtime.pytorch_playground import PytorchPlayground, PytorchPlaygroundApp

        exports = {
            "PytorchPlayground": PytorchPlayground,
            "PytorchPlaygroundApp": PytorchPlaygroundApp,
        }
        value = exports[name]
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "ArgsModel",
    "ArgsOverrides",
    "PytorchPlayground",
    "PytorchPlaygroundApp",
    "PYTORCH_PLAYGROUND_REDUCE_CONTRACT",
    "PytorchPlaygroundArgs",
    "PytorchPlaygroundArgsTD",
    "PYTORCH_PLAYGROUND_REDUCE_CONTRACT",
    "dump_args",
    "ensure_defaults",
    "load_args",
    "merge_args",
    "to_playground_config",
]
