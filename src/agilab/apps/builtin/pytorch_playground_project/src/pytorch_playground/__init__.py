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
from .reduction import (
    PYTORCH_PLAYGROUND_REDUCE_CONTRACT,
    REDUCE_ARTIFACT_FILENAME_TEMPLATE,
    REDUCE_ARTIFACT_NAME,
    REDUCER_NAME,
    build_reduce_artifact,
    partial_from_summary,
    reduce_artifact_path,
    write_reduce_artifact,
)

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
    "REDUCE_ARTIFACT_FILENAME_TEMPLATE",
    "REDUCE_ARTIFACT_NAME",
    "REDUCER_NAME",
    "build_reduce_artifact",
    "dump_args",
    "ensure_defaults",
    "load_args",
    "merge_args",
    "partial_from_summary",
    "reduce_artifact_path",
    "to_playground_config",
    "write_reduce_artifact",
]
