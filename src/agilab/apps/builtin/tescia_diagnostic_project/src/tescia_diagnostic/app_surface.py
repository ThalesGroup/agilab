"""Compatibility shim for tescia_diagnostic.app_surface.

The implementation now lives in tescia_diagnostic.ui.app_surface. Keep this shim so existing
imports continue to work while internal code migrates to the classified
package layout.
"""

from __future__ import annotations

import sys
from pathlib import Path

from tescia_diagnostic.compat.module_shim import activate_compat_module as _activate_compat_module

_APP_SRC = Path(__file__).resolve().parents[1]
if str(_APP_SRC) not in sys.path:
    sys.path.insert(0, str(_APP_SRC))

_TARGET_MODULE = "tescia_diagnostic.ui.app_surface"
_module = _activate_compat_module(__name__, _TARGET_MODULE)
if _module is not None:
    globals().update(_module.__dict__)
