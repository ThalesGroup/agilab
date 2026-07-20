# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS

"""Compatibility entrypoint for the canonical inference comparison page.

The delegated page owns the shared page chrome through ``agi_pages.runtime``.
"""

from __future__ import annotations

from importlib import import_module
from typing import Callable


CANONICAL_MODULE = "view_inference_analysis.view_inference_analysis"


def _load_canonical_main() -> Callable[[], None]:
    """Resolve the canonical page lazily so bundle discovery stays lightweight."""

    module = import_module(CANONICAL_MODULE)
    main = getattr(module, "main", None)
    if not callable(main):
        raise RuntimeError(f"Canonical comparison page {CANONICAL_MODULE!r} has no main().")
    return main


def main() -> None:
    """Render the generic allocation comparison under the legacy route."""

    _load_canonical_main()()


if __name__ == "__main__":
    main()
