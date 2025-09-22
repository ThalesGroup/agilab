"""Compatibility helpers exposing Titi argument utilities under a common API."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from .titi_args import TitiArgs, TitiArgsTD, apply_source_defaults, dump_args_to_toml, load_args_from_toml, merge_args
ArgsModel = TitiArgs
ArgsOverrides = FlightArgsTD


def ensure_defaults(args: TitiArgs, **kwargs: Any) ->TitiArgs:
    return apply_source_defaults(args, **kwargs)


def load_args(settings_path: (str | Path), section: str='args') ->TitiArgs:
    return load_args_from_toml(settings_path, section=section)


def dump_args(args: TitiArgs, settings_path: (str | Path), *, section: str=
    'args', create_missing: bool=True) ->None:
    dump_args_to_toml(args, settings_path, section=section, create_missing=
        create_missing)


__all__ = ['ArgsModel', 'ArgsOverrides', 'ensure_defaults', 'load_args',
    'dump_args', 'merge_args', 'TitiArgs', 'FlightArgsTD']
