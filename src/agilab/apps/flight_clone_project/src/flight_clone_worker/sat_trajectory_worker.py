"""Lightweight shim providing sat_trajectory_worker symbols when the package is absent."""

from ._satellite_helpers import (
    DEFAULT_EPOCH,
    TLEEntry,
    compute_trajectory,
    load_tle_catalog,
)

__all__ = [
    "DEFAULT_EPOCH",
    "TLEEntry",
    "compute_trajectory",
    "load_tle_catalog",
]
