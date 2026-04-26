#!/usr/bin/env python3
"""Source-tree wrapper for the packaged AGILAB Flight cluster doctor."""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agilab.cluster_flight_validation import main


if __name__ == "__main__":
    raise SystemExit(main())
