"""AGILAB page bundle for the NetworkSim TRI/GTIA visibility view."""

from __future__ import annotations

from pathlib import Path


def bundle_root() -> str:
    return str(Path(__file__).resolve().parents[2])
