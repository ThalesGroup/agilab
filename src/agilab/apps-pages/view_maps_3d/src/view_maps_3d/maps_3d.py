"""Support module for the 3D cartography Streamlit page."""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from .view_maps_3d import *  # type: ignore # noqa: F401,F403
except ImportError:  # pragma: no cover
    _HERE = Path(__file__).resolve().parent
    if str(_HERE) not in sys.path:
        sys.path.insert(0, str(_HERE))
    from view_maps_3d import *  # type: ignore # noqa: F401,F403
