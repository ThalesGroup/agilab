#!/usr/bin/env python
"""Export an AGILAB project as a Hugging Face Docker Space skeleton."""

from __future__ import annotations

import sys

from agilab import bridge_cli


def main(argv: list[str] | None = None) -> int:
    return bridge_cli.main(
        ["export", "hf-space", *(sys.argv[1:] if argv is None else argv)]
    )


if __name__ == "__main__":
    raise SystemExit(main())
