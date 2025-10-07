"""Streamlit entry-point for the autoencoder latent space viewer."""

from __future__ import annotations

import sys
from pathlib import Path

try:  # When executed as part of the package (e.g. `view_autoencoder_latentspace` module)
    from .autoencoder_latentspace import *  # noqa: F401,F403
except ImportError:  # pragma: no cover - fallback for `streamlit run <file>` execution
    current_dir = Path(__file__).resolve().parent
    if str(current_dir) not in sys.path:
        sys.path.insert(0, str(current_dir))
    from autoencoder_latentspace import *  # type: ignore # noqa: F401,F403
