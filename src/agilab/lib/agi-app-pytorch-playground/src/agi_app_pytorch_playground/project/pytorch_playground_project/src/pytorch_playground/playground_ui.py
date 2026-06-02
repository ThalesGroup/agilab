"""Compatibility shim for ``pytorch_playground.playground_ui``.

The implementation now lives in ``pytorch_playground.ui.playground_ui``. Keep this shim so existing
imports continue to work while internal code migrates to the classified
package layout.
"""

from __future__ import annotations

import sys
from pathlib import Path

_APP_SRC = Path(__file__).resolve().parents[1]
_APP_SRC_TEXT = str(_APP_SRC)
if _APP_SRC_TEXT in sys.path:
    sys.path.remove(_APP_SRC_TEXT)
sys.path.insert(0, _APP_SRC_TEXT)

from pytorch_playground.compat.module_shim import activate_compat_module as _activate_compat_module

_TARGET_MODULE = "pytorch_playground.ui.playground_ui"
_module = _activate_compat_module(__name__, _TARGET_MODULE)
if _module is not None:
    globals().update(_module.__dict__)
