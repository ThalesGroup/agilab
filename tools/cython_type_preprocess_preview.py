#!/usr/bin/env python3
"""Preview conservative Cython local-variable declarations for Python sources."""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_SRC = REPO_ROOT / "src/agilab/core/agi-node/src"
if CORE_SRC.exists() and str(CORE_SRC) not in sys.path:
    sys.path.insert(0, str(CORE_SRC))

from agi_node.agi_dispatcher.cython_type_preprocess import (  # noqa: E402,F401
    FunctionDeclarations,
    PreprocessPreview,
    SkippedVariable,
    TypedVariable,
    analyze_source,
    main,
    preprocess_file,
    preprocess_source,
    render_pyx,
)


if __name__ == "__main__":
    raise SystemExit(main())
